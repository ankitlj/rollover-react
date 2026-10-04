"""
Arrow SDK connector — login, instrument resolution, subscription, tick handling.

Design principles (from 14 learnings):
  - Capture tick in callback, return immediately (SDK uses WS threads)
  - Invalidate snapshots on disconnect, wait for fresh ticks after reconnect
  - Verify price scale on first tick
  - Separate feed health from connection state
  - Zero order operations — read-only market data
"""

import csv
import io
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Optional

from pyarrow_client import ArrowClient, ArrowStreams, DataMode

import config

log = logging.getLogger("arrow_connector")

# ─────────────────────────────────────────────────────────
# FEED HEALTH STATE MACHINE
# ─────────────────────────────────────────────────────────

class FeedState(Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    WAITING_FOR_FRESH_BOOKS = "WAITING_FOR_FRESH_BOOKS"
    HEALTHY = "HEALTHY"


# ─────────────────────────────────────────────────────────
# TICK SNAPSHOT
# ─────────────────────────────────────────────────────────

@dataclass
class TickSnapshot:
    token: int
    ltp: int
    mode: int
    open: int = 0
    high: int = 0
    low: int = 0
    close: int = 0
    volume: int = 0
    net_change: int = 0
    ltq: int = 0
    avg_price: int = 0
    total_buy_qty: int = 0
    total_sell_qty: int = 0
    oi: int = 0
    oi_day_high: int = 0
    oi_day_low: int = 0
    upper_limit: int = 0
    lower_limit: int = 0
    bids: list = field(default_factory=list)
    asks: list = field(default_factory=list)
    ltt: int = 0
    exchange_time: int = 0
    timestamp_ns: int = 0
    receive_epoch_ms: float = 0.0
    receive_ist: str = ""
    generation: int = 0

    @property
    def ltp_rupees(self):
        return self.ltp / 100.0

    @property
    def age_ms(self):
        if self.timestamp_ns == 0:
            return float('inf')
        return (time.monotonic_ns() - self.timestamp_ns) / 1_000_000


# ─────────────────────────────────────────────────────────
# ARROW CONNECTOR
# ─────────────────────────────────────────────────────────

class ArrowConnector:
    def __init__(self, on_tick_callback=None):
        self.client: Optional[ArrowClient] = None
        self.streams: Optional[ArrowStreams] = None

        self._on_tick = on_tick_callback

        self._lock = threading.RLock()
        self._snapshots: dict[int, TickSnapshot] = {}
        self._token_to_info: dict[int, dict] = {}
        self._all_tokens: list[int] = []

        self._state = FeedState.DISCONNECTED
        self._generation = 0
        self._state_lock = threading.Lock()
        self._state_listeners: list = []
        self._event_listeners: list = []

        self._price_scale_verified = False
        self._price_scale = 100

        self._tick_count = 0
        self._tick_count_lock = threading.Lock()
        self._last_tick_time = 0.0

        self._symbol_to_token: dict[str, int] = {}
        self._cash_tokens: list[int] = []
        self._fut_cur_tokens: list[int] = []
        self._fut_next_tokens: list[int] = []

        self._current_expiry: str = ""
        self._next_expiry: str = ""

        self._shutdown = threading.Event()

        self._recovering_from_401 = False
        self._recovery_lock = threading.Lock()
        self._401_count = 0

    # ─── PROPERTIES ──────────────────────────────────────

    @property
    def state(self) -> FeedState:
        return self._state

    @property
    def tick_count(self) -> int:
        with self._tick_count_lock:
            return self._tick_count

    @property
    def snapshots(self) -> dict[int, TickSnapshot]:
        with self._lock:
            return dict(self._snapshots)

    # ─── STATE MANAGEMENT ────────────────────────────────

    def _set_state(self, new_state: FeedState, reason: str = ""):
        with self._state_lock:
            old = self._state
            self._state = new_state
            if old != new_state:
                log.info(f"Feed state: {old.value} -> {new_state.value}  ({reason})")
                for listener in self._state_listeners:
                    try:
                        listener(new_state, old, reason)
                    except Exception:
                        pass

    def add_state_listener(self, callback):
        with self._state_lock:
            self._state_listeners.append(callback)

    def add_event_listener(self, callback):
        with self._state_lock:
            self._event_listeners.append(callback)

    def _fire_event(self, event_type: str, **kwargs):
        with self._state_lock:
            listeners = list(self._event_listeners)
        for listener in listeners:
            try:
                listener(event_type, kwargs)
            except Exception:
                pass

    # ─── LOGIN ───────────────────────────────────────────

    def login(self) -> bool:
        try:
            self.client = ArrowClient(app_id=config.APP_ID)
            result = self.client.auto_login(
                user_id=config.USER_ID,
                password=config.PASSWORD,
                app_secret=config.APP_SECRET,
                totp_secret=config.TOTP_SECRET,
            )
            log.info(f"Login OK: {result.get('name', '?')} (token expires at {result.get('userID','')})")
            return True
        except Exception as e:
            log.error(f"Login FAILED: {e}")
            return False

    # ─── INSTRUMENT RESOLUTION ───────────────────────────

    def resolve_instruments(self) -> bool:
        if not self.client:
            log.error("Must login before resolving instruments")
            return False

        try:
            raw = self.client.get_instruments()
            text = raw.decode() if isinstance(raw, bytes) else raw
            instruments = list(csv.DictReader(io.StringIO(text)))
            log.info(f"Loaded {len(instruments)} instruments from master")
        except Exception as e:
            log.error(f"Failed to load instrument master: {e}")
            return False

        arrow_symbol_map = {
            "INFOSYS": "INFY",
            "BANDHANBANK": "BANDHANBNK",
        }

        resolved = {}
        arrow_syms = set()
        for stock in config.STOCKS:
            sym = stock["sym"]
            arrow_sym = arrow_symbol_map.get(sym, sym)
            resolved[sym] = {"arrow_sym": arrow_sym, "cash": None, "fut_cur": None, "fut_next": None}
            arrow_syms.add(arrow_sym)

        all_fut_expiries = set()
        for r in instruments:
            if (r["Segment"] == "FO" and r["OptionType"] == "XX"
                    and r.get("Expiry", "").strip()
                    and r["Symbol"] in arrow_syms):
                all_fut_expiries.add(r["Expiry"].strip())

        sorted_expiries = sorted(all_fut_expiries, key=lambda e: datetime.strptime(e, "%d-%b-%Y"))
        today_dt = datetime.now(config.IST).date()

        # Business rule: select first two distinct monthly expiries >= today.
        # On expiry day the current month's expiry equals today, so we roll forward:
        # current → next month, next → month after. This ensures we always trade
        # live (non-expiring) contracts.
        future_expiries = []
        for exp_str in sorted_expiries:
            exp_dt = datetime.strptime(exp_str, "%d-%b-%Y").date()
            if exp_dt >= today_dt:
                future_expiries.append(exp_str)

        seen_months = set()
        monthly_expiries = []
        for exp_str in future_expiries:
            exp_dt = datetime.strptime(exp_str, "%d-%b-%Y").date()
            month_key = (exp_dt.year, exp_dt.month)
            if month_key not in seen_months:
                seen_months.add(month_key)
                monthly_expiries.append(exp_str)

        future_expiries = monthly_expiries

        if len(future_expiries) < 2:
            log.error(f"Need at least 2 future expiries, found {len(future_expiries)}: {future_expiries}")
            return False

        self._current_expiry = future_expiries[0]
        self._next_expiry = future_expiries[1]

        cur_exp_dt = datetime.strptime(self._current_expiry, "%d-%b-%Y").date()
        if cur_exp_dt == today_dt:
            if len(future_expiries) >= 3:
                self._current_expiry = future_expiries[1]
                self._next_expiry = future_expiries[2]
                log.info(f"Current expiry is today, rolling forward: cur={self._current_expiry}, next={self._next_expiry}")
            else:
                log.warning(f"Current expiry is today and no further expiries available")

        log.info(f"Future expiries: current={self._current_expiry}, next={self._next_expiry}")

        for r in instruments:
            sym = r["Symbol"]
            segment = r["Segment"]
            token_str = r.get("Token", "")
            if not token_str:
                continue
            try:
                token = int(float(token_str))
            except (ValueError, TypeError):
                continue

            for stock_sym, info in resolved.items():
                if sym != info["arrow_sym"]:
                    continue

                if segment == "CM" and r.get("Series") == "EQ":
                    info["cash"] = {"token": token, "tsym": r["TradingSymbol"], "lot": int(r.get("LotSize", 1))}

                elif segment == "FO" and r["OptionType"] == "XX":
                    expiry = r.get("Expiry", "").strip()
                    if expiry == self._current_expiry:
                        info["fut_cur"] = {"token": token, "tsym": r["TradingSymbol"], "expiry": expiry, "lot": int(r.get("LotSize", 1))}
                    elif expiry == self._next_expiry:
                        info["fut_next"] = {"token": token, "tsym": r["TradingSymbol"], "expiry": expiry, "lot": int(r.get("LotSize", 1))}

        missing = []
        all_tokens = []
        token_to_info = {}

        for stock_sym, info in resolved.items():
            if not info["cash"]:
                missing.append(f"{stock_sym}_CASH")
            else:
                t = info["cash"]["token"]
                all_tokens.append(t)
                self._cash_tokens.append(t)
                token_to_info[t] = {"type": "cash", "sym": stock_sym, **info["cash"]}
                self._symbol_to_token[f"CASH:{stock_sym}"] = t

            if not info["fut_cur"]:
                missing.append(f"{stock_sym}_FUT_CUR")
            else:
                t = info["fut_cur"]["token"]
                all_tokens.append(t)
                self._fut_cur_tokens.append(t)
                token_to_info[t] = {"type": "future", "month": "current", "sym": stock_sym, **info["fut_cur"]}
                self._symbol_to_token[f"FUTCUR:{stock_sym}"] = t

            if not info["fut_next"]:
                missing.append(f"{stock_sym}_FUT_NEXT")
            else:
                t = info["fut_next"]["token"]
                all_tokens.append(t)
                self._fut_next_tokens.append(t)
                token_to_info[t] = {"type": "future", "month": "next", "sym": stock_sym, **info["fut_next"]}
                self._symbol_to_token[f"FUTNEXT:{stock_sym}"] = t

        self._all_tokens = all_tokens
        self._token_to_info = token_to_info

        log.info(f"Resolved {len(all_tokens)}/57 tokens")
        for stock_sym, info in resolved.items():
            c = info['cash']['token'] if info['cash'] else 'MISSING'
            fc = info['fut_cur']['token'] if info['fut_cur'] else 'MISSING'
            fn = info['fut_next']['token'] if info['fut_next'] else 'MISSING'
            log.debug(f"  {stock_sym}: cash={c}, fut_cur={fc}({self._current_expiry}), fut_next={fn}({self._next_expiry})")

        if missing:
            log.warning(f"Missing tokens: {missing}")

        return len(missing) == 0

    # ─── STREAM CONNECTION ───────────────────────────────

    def connect_streams(self):
        if not self.client:
            raise RuntimeError("Must login first")

        token = self.client.get_token()
        self._generation += 1
        self.streams = ArrowStreams(appID=config.APP_ID, token=token, debug=False)
        self.bind_stream_callbacks(self._generation)

        self._set_state(FeedState.CONNECTING, "connecting data stream")
        self.streams.connect_data_stream()

    def subscribe_all(self):
        if not self.streams or not self._all_tokens:
            log.error("Cannot subscribe: streams or tokens not ready")
            return

        self.streams.subscribe_market_data(DataMode.FULL, self._all_tokens)
        log.info(f"Subscribed {len(self._all_tokens)} tokens to DataMode.FULL")

    # ─── WEBSOCKET CALLBACKS (run on SDK WS threads) ─────

    def _on_ws_connect(self):
        log.info("WebSocket CONNECTED")
        self._set_state(FeedState.CONNECTED, "ws connected")
        self.subscribe_all()
        self._set_state(FeedState.WAITING_FOR_FRESH_BOOKS, "waiting for first ticks")

    def _on_ws_close(self, close_status_code, close_msg):
        log.warning(f"WebSocket CLOSED: code={close_status_code}, msg={close_msg}")
        self._fire_event("ws_close", code=close_status_code, msg=str(close_msg))
        self._set_state(FeedState.DISCONNECTED, f"ws closed: {close_msg}")
        self._invalidate_all_snapshots()

    def _on_ws_disconnect(self):
        log.warning("WebSocket DISCONNECTED (SDK callback)")
        self._fire_event("ws_disconnect")
        self._set_state(FeedState.RECONNECTING, "ws disconnected")
        self._invalidate_all_snapshots()

    def _on_ws_error(self, error):
        log.error(f"WebSocket ERROR: {error}")
        self._fire_event("ws_error", error=str(error))

        error_str = str(error).lower()
        if "401" in error_str or "unauthorized" in error_str:
            log.warning("401 detected in on_error, starting full_recovery")
            threading.Thread(target=self.full_recovery, daemon=True).start()

    def _on_ws_reconnect(self, reconnect_count, reconnect_delay):
        log.info(f"WebSocket RECONNECTING: attempt={reconnect_count}, delay={reconnect_delay}s")
        self._generation += 1
        self._fire_event("ws_reconnect", attempt=reconnect_count, delay=reconnect_delay, generation=self._generation)
        self._set_state(FeedState.WAITING_FOR_FRESH_BOOKS, f"reconnect attempt={reconnect_count} gen={self._generation}")
        self._invalidate_all_snapshots()

    def _on_ws_no_reconnect(self):
        log.error("WebSocket: max reconnection attempts exhausted, starting full_recovery")
        self._fire_event("ws_no_reconnect")
        self._set_state(FeedState.DISCONNECTED, "max reconnect attempts exhausted")
        threading.Thread(target=self.full_recovery, daemon=True).start()

    def _invalidate_all_snapshots(self):
        with self._lock:
            self._snapshots.clear()
        log.info(f"Invalidated all snapshots (generation={self._generation})")

    def _on_ws_ticks(self, tick):
        now_ns = time.monotonic_ns()
        now_epoch_ms = time.time() * 1000.0
        now_ist = datetime.now(config.IST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        gen = self._generation

        try:
            token = tick.token

            if not self._price_scale_verified:
                self._verify_price_scale(tick)

            snap = TickSnapshot(
                token=token,
                ltp=tick.ltp,
                mode=tick.mode,
                open=getattr(tick, 'open', 0) or 0,
                high=getattr(tick, 'high', 0) or 0,
                low=getattr(tick, 'low', 0) or 0,
                close=getattr(tick, 'close', 0) or 0,
                volume=getattr(tick, 'volume', 0) or 0,
                net_change=getattr(tick, 'net_change', 0) or 0,
                ltq=getattr(tick, 'ltq', 0) or 0,
                avg_price=getattr(tick, 'avg_price', 0) or 0,
                total_buy_qty=getattr(tick, 'total_buy_quantity', 0) or 0,
                total_sell_qty=getattr(tick, 'total_sell_quantity', 0) or 0,
                oi=getattr(tick, 'oi', 0) or 0,
                oi_day_high=getattr(tick, 'oi_day_high', 0) or 0,
                oi_day_low=getattr(tick, 'oi_day_low', 0) or 0,
                upper_limit=getattr(tick, 'upper_limit', 0) or 0,
                lower_limit=getattr(tick, 'lower_limit', 0) or 0,
                bids=getattr(tick, 'bids', None) or [],
                asks=getattr(tick, 'asks', None) or [],
                ltt=getattr(tick, 'ltt', 0) or 0,
                exchange_time=getattr(tick, 'time', 0) or 0,
                timestamp_ns=now_ns,
                receive_epoch_ms=now_epoch_ms,
                receive_ist=now_ist,
                generation=gen,
            )

            with self._lock:
                self._snapshots[token] = snap

            with self._tick_count_lock:
                self._tick_count += 1
            self._last_tick_time = time.monotonic()

            if self._on_tick:
                self._on_tick(snap)

        except Exception as e:
            log.error(f"Error processing tick: {e}", exc_info=True)

        if self._state == FeedState.WAITING_FOR_FRESH_BOOKS:
            with self._lock:
                covered_tokens = sum(1 for t in self._all_tokens if t in self._snapshots)
                if covered_tokens >= len(self._all_tokens) * 0.8:
                    self._set_state(FeedState.HEALTHY, f"{covered_tokens}/{len(self._all_tokens)} tokens have fresh data")

    def _verify_price_scale(self, tick):
        ltp = tick.ltp
        if ltp > 100000:
            self._price_scale = 100
            log.info(f"Price scale verified: paise (LTP raw={ltp})")
        elif ltp > 1000:
            self._price_scale = 100
            log.info(f"Price scale assumed paise (LTP raw={ltp})")
        else:
            self._price_scale = 1
            log.warning(f"Price scale unexpected: LTP raw={ltp}, assuming rupees")
        self._price_scale_verified = True

    # ─── AUTH RECOVERY (v4 pattern) ──────────────────────

    def _guard_stream_callback(self, generation, callback):
        def guarded(*args, **kwargs):
            if self._generation != generation:
                return
            return callback(*args, **kwargs)
        return guarded

    def _noop_stream_callback(self, *args, **kwargs):
        pass

    def bind_stream_callbacks(self, generation):
        if not self.streams:
            return
        ds = self.streams.data_stream
        ds.on_ticks = self._guard_stream_callback(generation, self._on_ws_ticks)
        ds.on_connect = self._guard_stream_callback(generation, self._on_ws_connect)
        ds.on_close = self._guard_stream_callback(generation, self._on_ws_close)
        ds.on_disconnect = self._guard_stream_callback(generation, self._on_ws_disconnect)
        ds.on_error = self._guard_stream_callback(generation, self._on_ws_error)
        ds.on_reconnect = self._guard_stream_callback(generation, self._on_ws_reconnect)
        ds.on_no_reconnect = self._guard_stream_callback(generation, self._on_ws_no_reconnect)

    def detach_stream_callbacks(self, old_streams):
        if not old_streams:
            return
        ds = old_streams.data_stream
        ds.on_ticks = self._noop_stream_callback
        ds.on_connect = self._noop_stream_callback
        ds.on_close = self._noop_stream_callback
        ds.on_disconnect = self._noop_stream_callback
        ds.on_error = self._noop_stream_callback
        ds.on_reconnect = self._noop_stream_callback
        ds.on_no_reconnect = self._noop_stream_callback

    def retire_active_streams(self):
        old = self.streams
        self.streams = None
        self._generation += 1
        if old:
            self.detach_stream_callbacks(old)
            try:
                old.data_stream.disconnect()
            except Exception:
                pass
        log.info(f"Retired active streams (generation={self._generation})")

    def _attempt_stream_reconnect(self, token, settle_seconds=6.0):
        self._generation += 1
        self.streams = ArrowStreams(appID=config.APP_ID, token=token, debug=False)
        self.bind_stream_callbacks(self._generation)

        self._set_state(FeedState.CONNECTING, "recovery: connecting data stream")
        self.streams.connect_data_stream()
        time.sleep(settle_seconds)
        log.info(f"Stream reconnect settle complete (generation={self._generation})")

    def full_recovery(self):
        if not self._recovery_lock.acquire(blocking=False):
            return
        try:
            if self._recovering_from_401:
                return
            self._recovering_from_401 = True
            self._401_count += 1
            count = self._401_count

            log.info(f"=== FULL RECOVERY #{count} STARTING ===")

            self.retire_active_streams()
            self._set_state(FeedState.DISCONNECTED, f"recovery #{count} started")
            self._price_scale_verified = False

            time.sleep(2.0)

            log.info(f"Recovery #{count}: re-authenticating...")
            self.client.auto_login(
                user_id=config.USER_ID,
                password=config.PASSWORD,
                app_secret=config.APP_SECRET,
                totp_secret=config.TOTP_SECRET,
            )
            token = self.client.get_token()
            if not token:
                raise RuntimeError("Arrow returned an empty token during recovery.")

            log.info(f"Recovery #{count}: login OK, reconnecting streams...")
            self._attempt_stream_reconnect(token)

            log.info(f"=== FULL RECOVERY #{count} COMPLETE ===")

        except Exception as e:
            log.error(f"full_recovery FAILED: {e}", exc_info=True)
        finally:
            self._recovering_from_401 = False
            self._recovery_lock.release()

    # ─── QUERY HELPERS ───────────────────────────────────

    def get_snapshot(self, token: int) -> Optional[TickSnapshot]:
        with self._lock:
            return self._snapshots.get(token)

    def get_token_info(self, token: int) -> Optional[dict]:
        return self._token_to_info.get(token)

    def get_token_by_key(self, key: str) -> Optional[int]:
        return self._symbol_to_token.get(key)

    def get_all_tokens(self) -> list[int]:
        return list(self._all_tokens)

    def get_token_to_info(self) -> dict:
        return dict(self._token_to_info)

    def get_health_summary(self) -> dict:
        with self._lock:
            total = len(self._all_tokens)
            received = len(self._snapshots)
            stale = 0
            fresh = 0
            for t, snap in self._snapshots.items():
                age = snap.age_ms
                if age > 10000:
                    stale += 1
                else:
                    fresh += 1

        return {
            "state": self._state.value,
            "generation": self._generation,
            "total_tokens": total,
            "instruments_with_data": received,
            "fresh": fresh,
            "stale_10s": stale,
            "tick_count": self.tick_count,
            "current_expiry": self._current_expiry,
            "next_expiry": self._next_expiry,
        }

    # ─── SHUTDOWN ────────────────────────────────────────

    def disconnect(self):
        log.info("Disconnecting Arrow streams...")
        self._shutdown.set()
        try:
            if self.streams:
                self.streams.data_stream.disconnect()
        except Exception as e:
            log.error(f"Error during disconnect: {e}")
        self._set_state(FeedState.DISCONNECTED, "manual disconnect")
