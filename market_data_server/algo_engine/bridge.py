import json
import logging
import threading
import time
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Optional, List

try:
    import websockets
    import websockets.client
except ImportError:
    websockets = None

log = logging.getLogger("algo_bridge")


@dataclass
class Tick:
    token: int
    ltp: float
    ts: str
    recv_mono_ns: int
    gen: int = 0
    mode: int = 0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    ltq: int = 0
    oi: int = 0
    info: dict = field(default_factory=dict)

    @property
    def sym(self) -> Optional[str]:
        return self.info.get("sym")

    @property
    def fut_month(self) -> Optional[str]:
        return self.info.get("month")

    @property
    def inst_type(self) -> Optional[str]:
        return self.info.get("type")


class TickBridge:
    def __init__(self, uri: str = "ws://127.0.0.1:8765"):
        self.uri = uri
        self._lock = threading.Lock()
        self._ticks: Dict[int, Tick] = {}
        self._recv_times: Dict[int, int] = {}
        self._token_info: Dict[int, dict] = {}
        self._stocks: list = []
        self._metadata: dict = {}
        self._health: dict = {}
        self._tick_count: int = 0
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_ready = threading.Event()
        self._ws = None
        self._connected = threading.Event()

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def tick_count(self) -> int:
        with self._lock:
            return self._tick_count

    @property
    def token_count(self) -> int:
        with self._lock:
            return len(self._token_info)

    @property
    def stocks(self) -> list:
        with self._lock:
            return list(self._stocks)

    def _on_metadata(self, msg: dict):
        tokens = msg.get("tokens") or {}
        parsed = {}
        for tok_str, info in tokens.items():
            try:
                parsed[int(tok_str)] = info
            except (ValueError, TypeError):
                log.warning("metadata: skipping non-numeric token key %r", tok_str)
        stocks = msg.get("stocks", [])
        with self._lock:
            self._token_info.update(parsed)
            self._stocks = stocks
            self._metadata = msg

    def _on_health(self, msg: dict):
        with self._lock:
            self._health = msg

    def _on_ticks(self, msg: dict):
        now_ns = time.monotonic_ns()
        for snap in (msg.get("data") or []):
            token = snap.get("token")
            if token is None:
                continue
            tick = Tick(
                token=token,
                ltp=snap.get("ltp_r", 0.0),
                ts=snap.get("ts", ""),
                recv_mono_ns=now_ns,
                gen=snap.get("gen", 0),
                mode=snap.get("mode", 0),
                open=float(snap.get("open") or 0) / 100.0,
                high=float(snap.get("high") or 0) / 100.0,
                low=float(snap.get("low") or 0) / 100.0,
                close=float(snap.get("close") or 0) / 100.0,
                volume=snap.get("volume", 0),
                ltq=snap.get("ltq", 0),
                oi=snap.get("oi", 0),
                info=snap.get("info", {}),
            )
            with self._lock:
                self._ticks[token] = tick
                self._recv_times[token] = now_ns
                self._tick_count += 1

    def _on_message(self, raw: str):
        if not raw:
            return
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        t = msg.get("type")
        if t == "metadata":
            self._on_metadata(msg)
        elif t == "health":
            self._on_health(msg)
        elif t == "ticks":
            self._on_ticks(msg)

    async def _shutdown_ws(self):
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass

    async def _connect_loop(self):
        if websockets is None:
            raise RuntimeError("websockets package not installed")
        while not self._stop_event.is_set():
            try:
                async with websockets.client.connect(self.uri) as ws:
                    self._ws = ws
                    await ws.send(json.dumps({"type": "ping"}))
                    self._connected.set()
                    log.info("connected to %s", self.uri)
                    async for raw in ws:
                        if self._stop_event.is_set():
                            break
                        self._on_message(raw)
            except Exception:
                if not self._stop_event.is_set():
                    log.debug("connection failed, retrying in 2s")
            finally:
                self._ws = None
                self._connected.clear()
            if self._stop_event.is_set():
                break
            await asyncio.sleep(2)

    def start(self):
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._loop = asyncio.new_event_loop()

        def _run():
            asyncio.set_event_loop(self._loop)
            self._loop_ready.set()
            try:
                self._loop.run_until_complete(self._connect_loop())
            finally:
                self._loop_ready.clear()
                self._loop.close()
                self._loop = None

        self._thread = threading.Thread(target=_run, daemon=True, name="algo-bridge")
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._connected.clear()
        if self._loop is not None and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._shutdown_ws(), self._loop)
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def get_tick(self, token: int) -> Optional[Tick]:
        with self._lock:
            return self._ticks.get(token)

    def get_all_ticks(self) -> Dict[int, Tick]:
        with self._lock:
            return dict(self._ticks)

    def get_token_info(self, token: int) -> Optional[dict]:
        with self._lock:
            return self._token_info.get(token)

    def get_tokens_for_stock(self, sym: str) -> dict:
        result = {"cash": None, "current": None, "next": None}
        with self._lock:
            for tok, info in self._token_info.items():
                if info.get("sym") != sym:
                    continue
                if info.get("type") == "cash":
                    result["cash"] = tok
                elif info.get("type") == "future":
                    month = info.get("month")
                    if month == "current":
                        result["current"] = tok
                    elif month == "next":
                        result["next"] = tok
        return result

    def tick_age_ms(self, token: int) -> Optional[float]:
        with self._lock:
            recv = self._recv_times.get(token)
        if recv is None:
            return None
        return (time.monotonic_ns() - recv) / 1e6

    def fresh_tokens(self, max_age_ms: float = 500) -> List[int]:
        now = time.monotonic_ns()
        result = []
        with self._lock:
            for tok, recv in self._recv_times.items():
                if (now - recv) / 1e6 <= max_age_ms:
                    result.append(tok)
        return result

    def inject_tick(self, token: int, ltp: float, ts: str = "",
                   info: dict = None, gen: int = 0):
        now_ns = time.monotonic_ns()
        tick = Tick(
            token=token, ltp=ltp, ts=ts, recv_mono_ns=now_ns,
            gen=gen, info=info or {},
        )
        with self._lock:
            self._ticks[token] = tick
            self._recv_times[token] = now_ns
            self._tick_count += 1

    def inject_metadata(self, tokens: dict, stocks: list):
        parsed = {}
        for tok_str, info in tokens.items():
            try:
                parsed[int(tok_str)] = info
            except (ValueError, TypeError):
                continue
        with self._lock:
            self._token_info.update(parsed)
            self._stocks = list(stocks)

    def clear(self):
        with self._lock:
            self._ticks.clear()
            self._recv_times.clear()
            self._tick_count = 0
