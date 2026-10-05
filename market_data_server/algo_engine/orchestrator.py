import threading
import logging
import time
from typing import Optional, Dict, Callable, List
from datetime import datetime

from .config import STOCK_CONFIG, INITIAL_SPREADS, SAMPLE_INTERVAL_SECONDS, IST
from .bridge import TickBridge
from .validator import TickValidator
from .spread import SpreadEngine, SpreadSnapshot
from .alerts import AlertEngine, Alert
from .session import SessionEngine

log = logging.getLogger("algo_orchestrator")


class AlgoOrchestrator:
    def __init__(
        self,
        bridge: TickBridge,
        validator: TickValidator,
        spread: SpreadEngine,
        alerts: AlertEngine,
        session: SessionEngine,
        on_alert: Optional[Callable[[Alert], None]] = None,
    ):
        self._bridge = bridge
        self._validator = validator
        self._spread = spread
        self._alerts = alerts
        self._session = session
        self._on_alert = on_alert

        self._lock = threading.Lock()
        self._cycle_count: int = 0
        self._alerts_fired: int = 0
        self._stocks_computed: int = 0
        self._stocks_skipped: int = 0
        self._stop_event = threading.Event()
        self._timer_thread: Optional[threading.Thread] = None

    def start(self):
        if self._timer_thread is not None:
            return
        self._stop_event.clear()
        self._timer_thread = threading.Thread(
            target=self._loop, daemon=True, name="algo-orchestrator"
        )
        self._timer_thread.start()
        log.info("Algo orchestrator started (interval=%ds)", SAMPLE_INTERVAL_SECONDS)

    def stop(self):
        self._stop_event.set()
        if self._timer_thread is not None:
            self._timer_thread.join(timeout=5)
            self._timer_thread = None
        log.info("Algo orchestrator stopped")

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self.cycle()
            except Exception:
                log.exception("error in orchestrator cycle")
            self._stop_event.wait(timeout=SAMPLE_INTERVAL_SECONDS)

    def cycle(self):
        phase = self._session.current_phase()

        if not self._session.should_compute_spreads():
            with self._lock:
                self._cycle_count += 1
            return

        computed = 0
        skipped = 0

        for stock in STOCK_CONFIG:
            snapshot = self._compute_stock(stock)
            if snapshot is not None:
                computed += 1
                alert = self._alerts.process_snapshot(snapshot)
                if alert is not None and self._session.should_fire_alerts():
                    with self._lock:
                        self._alerts_fired += 1
                    if self._on_alert is not None:
                        try:
                            self._on_alert(alert)
                        except Exception:
                            log.exception("on_alert callback error for %s", stock)
            else:
                skipped += 1

        with self._lock:
            self._cycle_count += 1
            self._stocks_computed += computed
            self._stocks_skipped += skipped

    def _compute_stock(self, stock: str) -> Optional[SpreadSnapshot]:
        initial_spread = INITIAL_SPREADS.get(stock)
        if initial_spread is None or initial_spread <= 0:
            return None

        tokens = self._bridge.get_tokens_for_stock(stock)
        current_token = tokens.get("current")
        next_token = tokens.get("next")
        if current_token is None or next_token is None:
            return None

        current_tick = self._bridge.get_tick(current_token)
        next_tick = self._bridge.get_tick(next_token)
        if current_tick is None or next_tick is None:
            return None

        cur_valid, cur_reason = self._validator.check(current_tick)
        if not cur_valid:
            return None

        nxt_valid, nxt_reason = self._validator.check(next_tick)
        if not nxt_valid:
            return None

        return self._spread.compute_for_stock(stock)

    def run_once(self):
        self.cycle()

    def status(self) -> Dict:
        with self._lock:
            return {
                "cycle_count": self._cycle_count,
                "alerts_fired": self._alerts_fired,
                "stocks_computed": self._stocks_computed,
                "stocks_skipped": self._stocks_skipped,
                "phase": self._session.current_phase(),
                "session_summary": self._session.session_summary(),
                "spread_skip_reasons": self._spread.skip_reasons,
                "validator_rejected": self._validator.rejected_count,
                "validator_passed": self._validator.passed_count,
            }

    def reset(self):
        with self._lock:
            self._cycle_count = 0
            self._alerts_fired = 0
            self._stocks_computed = 0
            self._stocks_skipped = 0
