"""
Market Data Server — entry point.

Starts:
  1. Arrow SDK connector (login → resolve instruments → subscribe → stream)
  2. Daily reporter (operations tracking + end-of-day report)
  3. WebSocket server (broadcast ticks to React frontend)

Runs Mon-Fri, 9:20 AM to 3:00 PM IST.
Generates daily operations report on shutdown.
"""

import logging
import signal
import sys
import io
import time
import threading
from datetime import datetime, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import config
from arrow_connector import ArrowConnector, FeedState
from daily_reporter import DailyReporter
from ws_server import WebSocketServer

config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
config.LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d [%(threadName)-12s] %(name)-14s %(levelname)-5s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_DIR / f"server_{datetime.now(config.IST).strftime('%Y%m%d')}.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("main")

_shutdown_event = threading.Event()


def is_market_hours() -> bool:
    now = datetime.now(config.IST)
    if now.weekday() >= 5:
        return False
    open_minutes = now.hour * 60 + now.minute
    return (config.MARKET_OPEN_HOUR * 60 + config.MARKET_OPEN_MINUTE) <= open_minutes < (config.MARKET_CLOSE_HOUR * 60 + config.MARKET_CLOSE_MINUTE)


def seconds_until_market_open() -> float:
    now = datetime.now(config.IST)
    open_today = now.replace(hour=config.MARKET_OPEN_HOUR, minute=config.MARKET_OPEN_MINUTE, second=0, microsecond=0)
    if now < open_today and now.weekday() < 5:
        return (open_today - now).total_seconds()
    next_day = now + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    next_open = next_day.replace(hour=config.MARKET_OPEN_HOUR, minute=config.MARKET_OPEN_MINUTE, second=0, microsecond=0)
    return (next_open - now).total_seconds()


def run_server():
    log.info("=" * 60)
    log.info("ROLLOVER MARKET DATA SERVER")
    log.info(f"Date: {datetime.now(config.IST).strftime('%Y-%m-%d %H:%M:%S')} IST")
    log.info(f"Stocks: {len(config.STOCKS)} | Total instruments: {len(config.STOCKS) * 3}")
    log.info(f"Market hours: {config.MARKET_OPEN_HOUR:02d}:{config.MARKET_OPEN_MINUTE:02d} - {config.MARKET_CLOSE_HOUR:02d}:{config.MARKET_CLOSE_MINUTE:02d} IST")
    log.info(f"WebSocket: ws://{config.SERVER_HOST}:{config.SERVER_PORT}")
    log.info("=" * 60)

    if not all([config.APP_ID, config.APP_SECRET, config.USER_ID, config.PASSWORD, config.TOTP_SECRET]):
        log.error("Arrow credentials not set. Set environment variables: ARROW_APP_ID, ARROW_APP_SECRET, ARROW_USER_ID, ARROW_PASSWORD, ARROW_TOTP_SECRET")
        return

    reporter = DailyReporter()
    reporter.start()

    ws_server = WebSocketServer(None, reporter)

    def on_tick(snapshot):
        reporter.record_tick(snapshot)
        ws_server.on_tick(snapshot)

    connector = ArrowConnector(on_tick_callback=on_tick)
    ws_server.connector = connector

    connector.add_state_listener(lambda new, old, reason: reporter.record_state_transition(old, new, reason))
    connector.add_event_listener(lambda event_type, details: reporter.record_event(event_type, details))

    def signal_handler(sig, frame):
        log.info(f"Shutdown signal received ({sig})")
        _shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    connector_ref = connector
    reporter_ref = reporter
    ws_ref = ws_server

    try:
        log.info("Step 1/4: Logging into Arrow...")
        if not connector.login():
            log.error("Login failed. Check credentials.")
            return

        log.info("Step 2/4: Resolving instruments...")
        if not connector.resolve_instruments():
            log.error("Instrument resolution incomplete. Refusing to start with partial universe.")
            return

        log.info("Step 3/4: Starting WebSocket server...")
        ws_server.start()
        time.sleep(1)

        log.info("Step 4/4: Connecting Arrow data stream...")
        connector.connect_streams()

        log.info("ALL SYSTEMS RUNNING")
        log.info(f"  WebSocket: ws://{config.SERVER_HOST}:{config.SERVER_PORT}")
        log.info(f"  Reports: {config.REPORT_DIR}")
        log.info(f"  Logs: {config.LOG_DIR}")

        _print_status_loop(connector, reporter, ws_server)

    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
    finally:
        log.info("Shutting down gracefully...")
        try:
            connector_ref.disconnect()
        except Exception:
            pass
        try:
            ws_ref.stop()
        except Exception:
            pass
        try:
            reporter_ref.stop()
            report_text = reporter_ref.generate_report(connector_ref)
            log.info(f"\n{report_text}")
        except Exception:
            pass

        log.info("=" * 60)
        log.info("SERVER STOPPED")
        health = connector_ref.get_health_summary()
        log.info(f"Final stats: {health}")
        log.info("=" * 60)


def _print_status_loop(connector, reporter, ws_server):
    last_status_time = 0
    while not _shutdown_event.is_set():
        time.sleep(1)

        now = time.monotonic()
        if now - last_status_time >= 30:
            last_status_time = now
            health = connector.get_health_summary()
            rep = reporter.stats if reporter else {}
            log.info(
                f"STATUS | state={health['state']} | "
                f"instruments={health['instruments_with_data']}/{health['total_tokens']} | "
                f"fresh={health['fresh']} stale={health['stale_10s']} | "
                f"ticks={health['tick_count']} | "
                f"gaps={rep.get('gaps', 0)} errors={rep.get('errors', 0)} | "
                f"clients={ws_server.client_count}"
            )

        if not is_market_hours():
            wait = seconds_until_market_open()
            if wait > 3600:
                log.info(f"Outside market hours. Next open in {wait/3600:.1f}h. Server stays connected for monitoring.")

        if _shutdown_event.is_set():
            break


if __name__ == "__main__":
    run_server()
