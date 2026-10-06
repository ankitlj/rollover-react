import asyncio
import json
import logging
import threading
import time
from typing import Optional, Set
from datetime import datetime

from .config import IST, INITIAL_SPREADS, STOCK_CONFIG, SAMPLE_INTERVAL_SECONDS

log = logging.getLogger("algo_broadcaster")

BROADCAST_PORT = 8766
BROADCAST_HOST = "127.0.0.1"


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

    def start(self):
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="algo-ws-broadcast"
        )
        self._thread.start()

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
        client_addr = websocket.remote_address
        log.info("Algo WS client connected: %s", client_addr)

        with self._clients_lock:
            self._clients.add(websocket)

        try:
            init_msg = self._build_init_message()
            await websocket.send(init_msg)

            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get("type") == "ping":
                        await websocket.send(json.dumps({"type": "pong"}))
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass
        finally:
            with self._clients_lock:
                self._clients.discard(websocket)
            log.info("Algo WS client disconnected: %s", client_addr)

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
            except Exception:
                dead.append(ws)
        if dead:
            with self._clients_lock:
                for ws in dead:
                    self._clients.discard(ws)

    def stop(self):
        self._shutdown.set()
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        log.info("Algo WS broadcaster stopped")
