"""
WebSocket server — broadcasts tick data to React frontend clients.

Architecture:
  - Runs on asyncio event loop (separate thread from Arrow SDK)
  - Receives ticks from ArrowConnector via thread-safe queue
  - Batches ticks and broadcasts every TICK_BATCH_BROADCAST_MS
  - Sends health status periodically
  - Supports multiple simultaneous frontend clients
"""

import asyncio
import json
import logging
import queue
import threading
import time
from datetime import datetime
from typing import Optional

import config

log = logging.getLogger("ws_server")


class WebSocketServer:
    def __init__(self, connector, reporter):
        self.connector = connector
        self.reporter = reporter

        self._tick_queue: queue.Queue = queue.Queue(maxsize=50000)
        self._clients: set = set()
        self._clients_lock = threading.Lock()

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._shutdown = threading.Event()

        self._broadcast_count = 0
        self._total_ticks_sent = 0
        self._total_dropped = 0
        self._last_drop_log_time = 0

    def start(self):
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ws-server")
        self._thread.start()
        log.info(f"WebSocket server thread starting on {config.SERVER_HOST}:{config.SERVER_PORT}")

    def _run_loop(self):
        try:
            import websockets
        except ImportError:
            log.error("websockets package not installed. Run: pip install websockets")
            return

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def _startup():
            self._loop.create_task(self._broadcast_loop())
            self._loop.create_task(self._health_loop())

            import websockets
            server = await websockets.serve(
                self._handle_client,
                config.SERVER_HOST,
                config.SERVER_PORT,
                ping_interval=20,
                ping_timeout=10,
                max_size=10 * 1024 * 1024,
            )
            log.info(f"WebSocket server listening on ws://{config.SERVER_HOST}:{config.SERVER_PORT}")
            await asyncio.Future()

        try:
            self._loop.run_until_complete(_startup())
        except Exception as e:
            log.error(f"WebSocket server error: {e}", exc_info=True)

    async def _handle_client(self, websocket):
        client_addr = websocket.remote_address
        log.info(f"Frontend client connected: {client_addr}")
        if self.reporter:
            self.reporter.record_client_connect(client_addr)

        with self._clients_lock:
            self._clients.add(websocket)

        try:
            health = self.connector.get_health_summary()
            health["type"] = "health"
            await websocket.send(json.dumps(health, default=str))

            token_info = self.connector.get_token_to_info()
            master_lots = {}
            for info in token_info.values():
                sym = info.get("sym", "")
                lot = info.get("lot", 0)
                if sym and lot:
                    master_lots[sym] = lot
            stocks_meta = []
            for s in config.STOCKS:
                entry = dict(s)
                if s["sym"] in master_lots:
                    entry["lot"] = master_lots[s["sym"]]
                stocks_meta.append(entry)
            meta = {
                "type": "metadata",
                "tokens": {str(k): v for k, v in token_info.items()},
                "stocks": stocks_meta,
                "current_expiry": self.connector._current_expiry,
                "next_expiry": self.connector._next_expiry,
            }
            await websocket.send(json.dumps(meta, default=str))

            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get("type") == "ping":
                        await websocket.send(json.dumps({"type": "pong", "ts": time.time()}))
                    elif data.get("type") == "get_health":
                        health = self.connector.get_health_summary()
                        health["type"] = "health"
                        await websocket.send(json.dumps(health, default=str))
                    elif data.get("type") == "get_snapshots":
                        snaps = self.connector.snapshots
                        result = []
                        for token, snap in snaps.items():
                            info = self.connector.get_token_info(token)
                            result.append(self._snapshot_to_dict(snap, info))
                        await websocket.send(json.dumps({"type": "snapshots", "data": result}, default=str))
                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    log.error(f"Error handling client message: {e}")

        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            log.error(f"Client handler error: {e}")
        finally:
            with self._clients_lock:
                self._clients.discard(websocket)
            log.info(f"Frontend client disconnected: {client_addr}")
            if self.reporter:
                self.reporter.record_client_disconnect(client_addr)

    async def _broadcast_loop(self):
        interval = config.TICK_BATCH_BROADCAST_MS / 1000.0
        while not self._shutdown.is_set():
            try:
                await asyncio.sleep(interval)

                ticks = []
                while not self._tick_queue.empty():
                    try:
                        ticks.append(self._tick_queue.get_nowait())
                    except queue.Empty:
                        break

                if not ticks:
                    continue

                batch = []
                for snap in ticks:
                    info = self.connector.get_token_info(snap.token)
                    batch.append(self._snapshot_to_dict(snap, info))

                msg = json.dumps({"type": "ticks", "data": batch, "count": len(batch)}, default=str)

                with self._clients_lock:
                    clients = list(self._clients)

                if clients:
                    send_tasks = [self._safe_send(c, msg) for c in clients]
                    await asyncio.gather(*send_tasks, return_exceptions=True)

                self._broadcast_count += 1
                self._total_ticks_sent += len(ticks)
                if self.reporter:
                    self.reporter.update_ws_stats(self._broadcast_count, self._total_ticks_sent)

            except Exception as e:
                log.error(f"Broadcast loop error: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _health_loop(self):
        while not self._shutdown.is_set():
            try:
                await asyncio.sleep(5)
                health = self.connector.get_health_summary()
                health["type"] = "health"
                if self.reporter:
                    health["reporter"] = self.reporter.stats

                msg = json.dumps(health, default=str)

                with self._clients_lock:
                    clients = list(self._clients)

                if clients:
                    send_tasks = [self._safe_send(c, msg) for c in clients]
                    await asyncio.gather(*send_tasks, return_exceptions=True)

            except Exception as e:
                log.error(f"Health loop error: {e}")
                await asyncio.sleep(5)

    async def _safe_send(self, websocket, msg):
        try:
            await websocket.send(msg)
        except Exception:
            with self._clients_lock:
                self._clients.discard(websocket)

    def on_tick(self, snapshot):
        try:
            self._tick_queue.put_nowait(snapshot)
        except queue.Full:
            self._total_dropped += 1
            if self.reporter:
                self.reporter.record_ws_drop()
            now = time.monotonic()
            if now - self._last_drop_log_time >= 10:
                log.warning(f"WS queue full — dropped {self._total_dropped} ticks total (queue maxsize=50000)")
                self._last_drop_log_time = now

    def _snapshot_to_dict(self, snap, info=None) -> dict:
        result = {
            "token": snap.token,
            "ltp": snap.ltp,
            "ltp_r": round(snap.ltp / 100.0, 2),
            "mode": snap.mode,
            "open": snap.open,
            "high": snap.high,
            "low": snap.low,
            "close": snap.close,
            "volume": snap.volume,
            "ltq": snap.ltq,
            "avg_price": snap.avg_price,
            "total_buy_qty": snap.total_buy_qty,
            "total_sell_qty": snap.total_sell_qty,
            "oi": snap.oi,
            "oi_day_high": snap.oi_day_high,
            "oi_day_low": snap.oi_day_low,
            "upper_limit": snap.upper_limit,
            "lower_limit": snap.lower_limit,
            "bid_levels": len(snap.bids),
            "ask_levels": len(snap.asks),
            "bids": [{"price": b.get("price", 0), "qty": b.get("quantity", 0), "orders": b.get("orders", 0)} for b in snap.bids[:5]],
            "asks": [{"price": a.get("price", 0), "qty": a.get("quantity", 0), "orders": a.get("orders", 0)} for a in snap.asks[:5]],
            "ltt": snap.ltt,
            "exchange_time": snap.exchange_time,
            "ts": snap.receive_ist,
            "age_ms": round(snap.age_ms, 1),
            "gen": snap.generation,
        }
        if info:
            result["info"] = info
        return result

    def stop(self):
        log.info("WebSocket server shutting down...")
        self._shutdown.set()
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        log.info(f"WebSocket server stopped. Broadcasts={self._broadcast_count}, Ticks sent={self._total_ticks_sent}, Dropped={self._total_dropped}")

    @property
    def client_count(self) -> int:
        with self._clients_lock:
            return len(self._clients)
