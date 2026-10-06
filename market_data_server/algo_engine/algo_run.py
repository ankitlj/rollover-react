"""
Algo Engine — separate process entry point.

Connects to market_data_server WebSocket as a client,
computes spreads, fires alerts. No changes to market_data_server files.

Usage:
    python algo_engine/algo_run.py
"""

import sys
import io
import os
import logging
import signal
import time
import threading
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algo_engine.config import IST, WS_URI, STOCK_CONFIG, INITIAL_SPREADS, SAMPLE_INTERVAL_SECONDS
from algo_engine.bridge import TickBridge
from algo_engine.validator import TickValidator
from algo_engine.spread import SpreadEngine
from algo_engine.alerts import AlertEngine, Alert
from algo_engine.session import SessionEngine
from algo_engine.orchestrator import AlgoOrchestrator
from algo_engine.algo_reporter import AlgoReporter
from algo_engine.ws_broadcaster import WSBroadcaster

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d [%(threadName)-12s] %(name)-14s %(levelname)-5s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(LOG_DIR, f"algo_{datetime.now(IST).strftime('%Y%m%d')}.log"),
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger("algo_run")

_shutdown = threading.Event()


def _status_loop(orchestrator: AlgoOrchestrator, bridge: TickBridge):
    while not _shutdown.is_set():
        _shutdown.wait(timeout=30)
        if _shutdown.is_set():
            break
        st = orchestrator.status()
        log.info(
            "STATUS | phase=%s | cycles=%d | alerts=%d | "
            "stocks_computed=%d stocks_skipped=%d | "
            "bridge_ticks=%d connected=%s",
            st["phase"],
            st["cycle_count"],
            st["alerts_fired"],
            st["stocks_computed"],
            st["stocks_skipped"],
            bridge.tick_count,
            bridge.connected,
        )


def run():
    log.info("=" * 60)
    log.info("ALGO ENGINE STARTING")
    log.info(f"Date: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')} IST")
    log.info(f"Stocks: {len(STOCK_CONFIG)} | WS: {WS_URI}")
    log.info(f"Sample interval: {SAMPLE_INTERVAL_SECONDS}s")
    log.info("=" * 60)

    bridge = TickBridge(uri=WS_URI)
    validator = TickValidator()
    spread = SpreadEngine(bridge, INITIAL_SPREADS)
    alerts = AlertEngine()
    session = SessionEngine()

    orchestrator = AlgoOrchestrator(
        bridge=bridge,
        validator=validator,
        spread=spread,
        alerts=alerts,
        session=session,
    )

    reporter = AlgoReporter(orchestrator, bridge)
    broadcaster = WSBroadcaster(spread, orchestrator, bridge, session)

    def on_alert(alert: Alert):
        log.info(
            "ALERT FIRED | %s | discount=%.2f%% >= %d%% | spread=%.2f | "
            "trigger#%d | fut_ltp=%.2f / %.2f",
            alert.stock,
            alert.discount_pct,
            alert.threshold,
            alert.spread,
            alert.trigger_count,
            alert.current_fut_ltp,
            alert.next_fut_ltp,
        )
        reporter.record_alert(alert)
        broadcaster.broadcast_alert(alert)

    def on_alert_expired(stock: str, final_spread: float, timestamp: str):
        log.info("ALERT EXPIRED | %s | final_spread=%.2f", stock, final_spread)
        broadcaster.broadcast_alert_expired(stock, final_spread, timestamp)

    orchestrator._on_alert = on_alert
    orchestrator._on_alert_expired = on_alert_expired

    def signal_handler(sig, frame):
        log.info(f"Shutdown signal ({sig})")
        _shutdown.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        bridge.start()
        log.info("Bridge connecting to %s ...", WS_URI)

        for _ in range(10):
            if bridge.connected:
                break
            time.sleep(1)

        if not bridge.connected:
            log.warning("Not connected yet — will keep retrying in background")

        orchestrator.start()
        reporter.start()
        broadcaster.start()

        status_thread = threading.Thread(
            target=_status_loop, args=(orchestrator, bridge),
            daemon=True, name="algo-status",
        )
        status_thread.start()

        log.info("ALGO ENGINE RUNNING — Ctrl+C to stop")

        while not _shutdown.is_set():
            _shutdown.wait(timeout=1)

    except Exception:
        log.exception("Fatal error in algo engine")
    finally:
        log.info("Shutting down algo engine...")
        orchestrator.stop()
        bridge.stop()
        reporter.stop()
        broadcaster.stop()

        st = orchestrator.status()
        log.info(
            "Final stats: cycles=%d alerts=%d stocks_computed=%d "
            "validator_rejected=%d bridge_ticks=%d",
            st["cycle_count"],
            st["alerts_fired"],
            st["stocks_computed"],
            st["validator_rejected"],
            bridge.tick_count,
        )
        
        log.info("Generating daily report...")
        try:
            report = reporter.generate_report()
            log.info("Daily report generated")
        except Exception:
            log.exception("Failed to generate daily report")
        
        log.info("ALGO ENGINE STOPPED")


if __name__ == "__main__":
    run()
