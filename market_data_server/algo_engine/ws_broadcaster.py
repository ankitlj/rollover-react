import asyncio
import json
import logging
import os
import threading
import time
from http import HTTPStatus
from pathlib import Path
from typing import Optional, Set, Dict, List
from datetime import datetime

from .config import IST, INITIAL_SPREADS, STOCK_CONFIG, SAMPLE_INTERVAL_SECONDS

log = logging.getLogger("algo_broadcaster")

BROADCAST_PORT = 8766
BROADCAST_HOST = "127.0.0.1"
HEALTH_API_PORT = 8767


class WSBroadcaster:
    def __init__(self, spread_engine, orchestrator, bridge, session_engine):
        self._spread = spread_engine
        self._orchestrator = orchestrator
        self._bridge = bridge
        self._session = session_engine

        self._clients: Set = set()
        self._clients_lock = threading.Lock()

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._shutdown = threading.Event()

        self._last_phase: Optional[str] = None
        self._last_bridge_connected: Optional[bool] = None

        self._start_time = datetime.now(IST)
        self._connection_events: List[Dict] = []
        self._messages_sent = 0
        self._send_failures = 0
        self._client_stats: Dict[str, Dict] = {}
        self._stats_lock = threading.Lock()

        self._health_api_thread: Optional[threading.Thread] = None

    def start(self):
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="algo-ws-broadcast"
        )
        self._thread.start()

        self._health_api_thread = threading.Thread(
            target=self._run_health_api, daemon=True, name="health-api"
        )
        self._health_api_thread.start()

    def _run_health_api(self):
        from http.server import HTTPServer, BaseHTTPRequestHandler

        class HealthAPIHandler(BaseHTTPRequestHandler):
            def do_POST(handler):
                if handler.path == "/health":
                    content_length = int(handler.headers.get("Content-Length", 0))
                    body = handler.rfile.read(content_length)
                    try:
                        data = json.loads(body.decode("utf-8"))
                        self._save_frontend_health(data)
                        handler.send_response(HTTPStatus.OK)
                        handler.send_header("Content-Type", "application/json")
                        handler.send_header("Access-Control-Allow-Origin", "*")
                        handler.end_headers()
                        handler.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
                    except Exception as e:
                        log.exception("Health API error")
                        handler.send_response(HTTPStatus.BAD_REQUEST)
                        handler.end_headers()
                        handler.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                else:
                    handler.send_response(HTTPStatus.NOT_FOUND)
                    handler.end_headers()

            def do_OPTIONS(handler):
                handler.send_response(HTTPStatus.OK)
                handler.send_header("Access-Control-Allow-Origin", "*")
                handler.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                handler.send_header("Access-Control-Allow-Headers", "Content-Type")
                handler.end_headers()

            def log_message(self, format, *args):
                pass

        try:
            server = HTTPServer((BROADCAST_HOST, HEALTH_API_PORT), HealthAPIHandler)
            log.info("Health API listening on http://%s:%d/health", BROADCAST_HOST, HEALTH_API_PORT)
            server.serve_forever()
        except Exception:
            log.exception("Health API server error")

    def _save_frontend_health(self, data: Dict):
        report_dir = Path(__file__).parent.parent / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        date_tag = datetime.now(IST).strftime("%Y%m%d")
        json_path = report_dir / f"frontend_health_{date_tag}.json"

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "component": "frontend",
                "received_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"),
                "data": data,
            }, f, indent=2, default=str)

        log.info("Frontend health data saved: %s", json_path)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def _startup():
            import websockets
            server = await websockets.serve(
                self._handle_client,
                BROADCAST_HOST,
                BROADCAST_PORT,
                ping_interval=20,
                ping_timeout=10,
            )
            log.info("Algo WS broadcaster listening on ws://%s:%d", BROADCAST_HOST, BROADCAST_PORT)
            self._loop.create_task(self._broadcast_loop())
            await asyncio.Future()

        try:
            self._loop.run_until_complete(_startup())
        except Exception:
            log.exception("Algo WS broadcaster error")

    async def _handle_client(self, websocket):
        client_addr = str(websocket.remote_address)
        connect_time = datetime.now(IST)
        log.info("Algo WS client connected: %s", client_addr)

        with self._clients_lock:
            self._clients.add(websocket)

        with self._stats_lock:
            self._connection_events.append({
                "event": "connect",
                "client": client_addr,
                "timestamp": connect_time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            self._client_stats[client_addr] = {
                "connected_at": connect_time.strftime("%Y-%m-%d %H:%M:%S"),
                "disconnected_at": None,
                "messages_sent": 0,
                "duration_sec": 0,
            }

        try:
            init_msg = self._build_init_message()
            await websocket.send(init_msg)
            self._messages_sent += 1
            with self._stats_lock:
                if client_addr in self._client_stats:
                    self._client_stats[client_addr]["messages_sent"] += 1

            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get("type") == "ping":
                        await websocket.send(json.dumps({"type": "pong"}))
                        self._messages_sent += 1
                        with self._stats_lock:
                            if client_addr in self._client_stats:
                                self._client_stats[client_addr]["messages_sent"] += 1
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass
        finally:
            disconnect_time = datetime.now(IST)
            with self._clients_lock:
                self._clients.discard(websocket)

            duration = (disconnect_time - connect_time).total_seconds()
            with self._stats_lock:
                self._connection_events.append({
                    "event": "disconnect",
                    "client": client_addr,
                    "timestamp": disconnect_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "duration_sec": round(duration, 1),
                })
                if client_addr in self._client_stats:
                    self._client_stats[client_addr]["disconnected_at"] = disconnect_time.strftime("%Y-%m-%d %H:%M:%S")
                    self._client_stats[client_addr]["duration_sec"] = round(duration, 1)

            log.info("Algo WS client disconnected: %s (duration: %.1fs)", client_addr, duration)

    def _build_init_message(self) -> str:
        snapshots = self._spread.snapshots
        stocks = []
        for sym in STOCK_CONFIG:
            snap = snapshots.get(sym)
            if snap:
                stocks.append(self._snapshot_to_dict(snap))
            else:
                stocks.append({
                    "stock": sym,
                    "initial_spread": INITIAL_SPREADS.get(sym, 0),
                    "current_spread": None,
                    "discount_pct": None,
                    "is_contango": None,
                    "current_fut_ltp": None,
                    "next_fut_ltp": None,
                    "timestamp": None,
                })

        phase = self._session.current_phase()
        self._last_phase = phase

        msg = {
            "type": "init",
            "stocks": stocks,
            "status": {
                "phase": phase,
                "is_connected": self._bridge.connected,
                "market_open": phase in ("WARMUP", "ACTIVE", "CLOSING"),
            },
        }
        return json.dumps(msg, default=str)

    def _snapshot_to_dict(self, snap) -> dict:
        return {
            "stock": snap.stock,
            "initial_spread": snap.initial_spread,
            "current_spread": round(snap.spread, 2),
            "discount_pct": round(snap.discount_pct, 2),
            "is_contango": snap.is_contango,
            "current_fut_ltp": snap.current_fut_ltp,
            "next_fut_ltp": snap.next_fut_ltp,
            "timestamp": snap.timestamp,
        }

    async def _broadcast_loop(self):
        while not self._shutdown.is_set():
            try:
                await asyncio.sleep(SAMPLE_INTERVAL_SECONDS)
                if self._shutdown.is_set():
                    break

                await self._broadcast_snapshot()
                await self._check_status_changes()

            except Exception:
                log.exception("Error in broadcast loop")
                await asyncio.sleep(5)

    async def _broadcast_snapshot(self):
        if not self._clients:
            return

        snapshots = self._spread.snapshots
        stocks = []
        for sym in STOCK_CONFIG:
            snap = snapshots.get(sym)
            if snap:
                stocks.append(self._snapshot_to_dict(snap))

        if not stocks:
            return

        msg = json.dumps({
            "type": "snapshot",
            "stocks": stocks,
            "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        }, default=str)

        await self._send_to_all(msg)

    async def _check_status_changes(self):
        phase = self._session.current_phase()
        bridge_connected = self._bridge.connected

        phase_changed = phase != self._last_phase
        conn_changed = bridge_connected != self._last_bridge_connected

        if phase_changed or conn_changed:
            self._last_phase = phase
            self._last_bridge_connected = bridge_connected

            msg = json.dumps({
                "type": "status",
                "phase": phase,
                "is_connected": bridge_connected,
                "market_open": phase in ("WARMUP", "ACTIVE", "CLOSING"),
            })
            await self._send_to_all(msg)

    def broadcast_alert(self, alert):
        if self._loop is None:
            return
        msg = json.dumps({
            "type": "alert",
            "stock": alert.stock,
            "discount_pct": round(alert.discount_pct, 2),
            "threshold": alert.threshold,
            "trigger_count": alert.trigger_count,
            "spread": round(alert.spread, 2),
            "initial_spread": alert.initial_spread,
            "current_fut_ltp": alert.current_fut_ltp,
            "next_fut_ltp": alert.next_fut_ltp,
            "timestamp": alert.timestamp,
        }, default=str)
        asyncio.run_coroutine_threadsafe(self._send_to_all(msg), self._loop)

    def broadcast_alert_expired(self, stock: str, final_spread: float, timestamp: str):
        if self._loop is None:
            return
        msg = json.dumps({
            "type": "alert_expired",
            "stock": stock,
            "final_spread": final_spread,
            "timestamp": timestamp,
        }, default=str)
        asyncio.run_coroutine_threadsafe(self._send_to_all(msg), self._loop)

    async def _send_to_all(self, message: str):
        if not self._clients:
            return
        with self._clients_lock:
            clients = list(self._clients)
        dead = []
        for ws in clients:
            try:
                await ws.send(message)
                self._messages_sent += 1
                client_addr = str(ws.remote_address)
                with self._stats_lock:
                    if client_addr in self._client_stats:
                        self._client_stats[client_addr]["messages_sent"] += 1
            except Exception:
                self._send_failures += 1
                dead.append(ws)
        if dead:
            with self._clients_lock:
                for ws in dead:
                    self._clients.discard(ws)

    def generate_report(self) -> Dict:
        end_time = datetime.now(IST)
        uptime_sec = (end_time - self._start_time).total_seconds()

        report_dir = Path(__file__).parent.parent / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        date_tag = self._start_time.strftime("%Y%m%d")

        with self._stats_lock:
            events_copy = list(self._connection_events)
            stats_copy = dict(self._client_stats)
            messages_sent = self._messages_sent
            send_failures = self._send_failures

        report_data = {
            "component": "ws_broadcaster",
            "start_time": self._start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S"),
            "uptime_sec": round(uptime_sec, 1),
            "total_connection_events": len(events_copy),
            "total_messages_sent": messages_sent,
            "total_send_failures": send_failures,
            "unique_clients": len(stats_copy),
            "connection_events": events_copy,
            "client_stats": stats_copy,
        }

        txt_path = report_dir / f"ws_bridge_{date_tag}.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("WS BROADCASTER DAILY REPORT\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"Start Time: {report_data['start_time']}\n")
            f.write(f"End Time: {report_data['end_time']}\n")
            f.write(f"Uptime: {uptime_sec:.1f} seconds ({uptime_sec/3600:.2f} hours)\n\n")
            f.write(f"Total Connection Events: {len(events_copy)}\n")
            f.write(f"Unique Clients: {len(stats_copy)}\n")
            f.write(f"Total Messages Sent: {messages_sent}\n")
            f.write(f"Total Send Failures: {send_failures}\n\n")

            if events_copy:
                f.write("CONNECTION EVENTS\n")
                f.write("-" * 60 + "\n")
                for evt in events_copy:
                    f.write(f"[{evt['timestamp']}] {evt['event'].upper()} - {evt['client']}")
                    if 'duration_sec' in evt:
                        f.write(f" (duration: {evt['duration_sec']}s)")
                    f.write("\n")
                f.write("\n")

            if stats_copy:
                f.write("CLIENT STATISTICS\n")
                f.write("-" * 60 + "\n")
                for client, stats in stats_copy.items():
                    f.write(f"\nClient: {client}\n")
                    f.write(f"  Connected: {stats['connected_at']}\n")
                    f.write(f"  Disconnected: {stats['disconnected_at'] or 'Still connected'}\n")
                    f.write(f"  Duration: {stats['duration_sec']}s\n")
                    f.write(f"  Messages Sent: {stats['messages_sent']}\n")

        json_path = report_dir / f"ws_bridge_{date_tag}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, default=str)

        log.info("WS bridge report generated: %s", txt_path)
        return report_data

    def stop(self):
        self._shutdown.set()
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        log.info("Algo WS broadcaster stopped")
