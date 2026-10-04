import threading
import time
import logging
from dataclasses import dataclass
from typing import Dict, Optional, List
from datetime import datetime

from .config import (
    STOCK_CONFIG, INITIAL_SPREADS, SPREAD_FRESHNESS_SECONDS,
    SAMPLE_INTERVAL_SECONDS, IST,
)
from .bridge import TickBridge, Tick

log = logging.getLogger("algo_spread")


@dataclass
class SpreadSnapshot:
    stock: str
    spread: float
    discount_pct: float
    initial_spread: float
    current_fut_ltp: float
    next_fut_ltp: float
    timestamp: str
    is_contango: bool


class SpreadEngine:
    def __init__(self, bridge: TickBridge, initial_spreads: Dict[str, float]):
        self._bridge = bridge
        self._initial_spreads = dict(initial_spreads)
        self._lock = threading.Lock()
        self._snapshots: Dict[str, SpreadSnapshot] = {}
        self._skip_reasons: Dict[str, str] = {}
        self._stale_counters: Dict[str, int] = {}
        self._cycle_count: int = 0
        self._last_success_mono_ns: int = 0
        self._stop_event = threading.Event()
        self._timer_thread: Optional[threading.Thread] = None

    @property
    def snapshots(self) -> Dict[str, SpreadSnapshot]:
        with self._lock:
            return dict(self._snapshots)

    @property
    def skip_reasons(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._skip_reasons)

    @property
    def cycle_count(self) -> int:
        with self._lock:
            return self._cycle_count

    def get_snapshot(self, stock: str) -> Optional[SpreadSnapshot]:
        with self._lock:
            return self._snapshots.get(stock)

    def _get_tokens_for_stock(self, stock: str):
        tokens = self._bridge.get_tokens_for_stock(stock)
        return tokens.get("current"), tokens.get("next")

    def _tick_is_fresh(self, tick: Tick) -> bool:
        if not tick.ts:
            return False
        if not tick.recv_mono_ns:
            return False
        age_seconds = (time.monotonic_ns() - tick.recv_mono_ns) / 1e9
        return age_seconds < SPREAD_FRESHNESS_SECONDS

    def compute_for_stock(self, stock: str) -> Optional[SpreadSnapshot]:
        if stock not in STOCK_CONFIG:
            return None

        initial_spread = self._initial_spreads.get(stock)
        if initial_spread is None:
            with self._lock:
                self._skip_reasons[stock] = "no_initial_spread"
            return None

        if initial_spread <= 0:
            with self._lock:
                self._skip_reasons[stock] = "negative_initial_spread"
            return None

        current_token, next_token = self._get_tokens_for_stock(stock)
        if current_token is None or next_token is None:
            with self._lock:
                self._skip_reasons[stock] = "no_tokens"
            return None

        current_tick = self._bridge.get_tick(current_token)
        next_tick = self._bridge.get_tick(next_token)

        if current_tick is None or next_tick is None:
            with self._lock:
                self._skip_reasons[stock] = "no_ticks"
            return None

        if not self._tick_is_fresh(current_tick):
            with self._lock:
                self._skip_reasons[stock] = "stale_current"
                self._stale_counters[stock] = self._stale_counters.get(stock, 0) + 1
                if self._stale_counters[stock] % 10 == 0:
                    log.warning(f"Stock {stock}: current tick stale for {self._stale_counters[stock]} consecutive checks")
            return None

        if not self._tick_is_fresh(next_tick):
            with self._lock:
                self._skip_reasons[stock] = "stale_next"
                self._stale_counters[stock] = self._stale_counters.get(stock, 0) + 1
                if self._stale_counters[stock] % 10 == 0:
                    log.warning(f"Stock {stock}: next tick stale for {self._stale_counters[stock]} consecutive checks")
            return None

        with self._lock:
            if stock in self._stale_counters:
                del self._stale_counters[stock]

        spread = next_tick.ltp - current_tick.ltp

        if spread <= 0:
            now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            snapshot = SpreadSnapshot(
                stock=stock,
                spread=spread,
                discount_pct=0.0,
                initial_spread=initial_spread,
                current_fut_ltp=current_tick.ltp,
                next_fut_ltp=next_tick.ltp,
                timestamp=now_ist,
                is_contango=False,
            )
            with self._lock:
                self._snapshots[stock] = snapshot
                self._last_success_mono_ns = time.monotonic_ns()
                if stock in self._skip_reasons:
                    del self._skip_reasons[stock]
            return snapshot

        if initial_spread == 0:
            with self._lock:
                self._skip_reasons[stock] = "zero_initial_spread"
            return None

        discount_pct = (initial_spread - spread) / initial_spread * 100

        now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        snapshot = SpreadSnapshot(
            stock=stock,
            spread=spread,
            discount_pct=discount_pct,
            initial_spread=initial_spread,
            current_fut_ltp=current_tick.ltp,
            next_fut_ltp=next_tick.ltp,
            timestamp=now_ist,
            is_contango=True,
        )

        with self._lock:
            self._snapshots[stock] = snapshot
            self._last_success_mono_ns = time.monotonic_ns()
            if stock in self._skip_reasons:
                del self._skip_reasons[stock]

        return snapshot

    def compute_all(self) -> Dict[str, SpreadSnapshot]:
        results = {}
        for stock in STOCK_CONFIG:
            snapshot = self.compute_for_stock(stock)
            if snapshot is not None:
                results[stock] = snapshot
        with self._lock:
            self._cycle_count += 1
        return results

    def _timer_loop(self):
        while not self._stop_event.is_set():
            try:
                self.compute_all()
                if not self.is_healthy(max_stale_seconds=120):
                    age = self.pipeline_age_seconds()
                    log.warning(f"Pipeline stall detected: last success {age:.1f}s ago")
            except Exception:
                log.exception("error in spread computation cycle")
            self._stop_event.wait(timeout=SAMPLE_INTERVAL_SECONDS)

    def start(self):
        if self._timer_thread is not None:
            return
        self._stop_event.clear()
        self._timer_thread = threading.Thread(
            target=self._timer_loop, daemon=True, name="algo-spread"
        )
        self._timer_thread.start()
        log.info("spread engine started (interval=%ds)", SAMPLE_INTERVAL_SECONDS)

    def stop(self):
        self._stop_event.set()
        if self._timer_thread is not None:
            self._timer_thread.join(timeout=5)
            self._timer_thread = None
        log.info("spread engine stopped")

    def reset(self):
        with self._lock:
            self._snapshots.clear()
            self._skip_reasons.clear()
            self._stale_counters.clear()
            self._cycle_count = 0
            self._last_success_mono_ns = 0

    def is_healthy(self, max_stale_seconds: float = 120) -> bool:
        with self._lock:
            if self._last_success_mono_ns == 0:
                return True
            age_seconds = (time.monotonic_ns() - self._last_success_mono_ns) / 1e9
            return age_seconds <= max_stale_seconds

    def pipeline_age_seconds(self) -> float:
        with self._lock:
            if self._last_success_mono_ns == 0:
                return -1.0
            return (time.monotonic_ns() - self._last_success_mono_ns) / 1e9
