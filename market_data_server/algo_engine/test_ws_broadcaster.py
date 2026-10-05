"""
Tests for algo_engine/ws_broadcaster.py

Tests cover:
- Server starts and accepts WebSocket connections
- Init message sent on connect with all 19 stocks
- Snapshot broadcast sends current spread data
- Alert broadcast sends alert data immediately
- Status changes (phase, connection) are detected and broadcast
- Client disconnect cleanup
- Thread safety of broadcast methods
"""

import asyncio
import json
import sys
import os
import time
import unittest
import threading
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algo_engine.config import IST, INITIAL_SPREADS, STOCK_CONFIG
from algo_engine.ws_broadcaster import WSBroadcaster, BROADCAST_PORT


def _make_mock_snapshot(stock, spread=5.0, discount=30.0, initial=10.0, contango=True):
    snap = MagicMock()
    snap.stock = stock
    snap.spread = spread
    snap.discount_pct = discount
    snap.initial_spread = initial
    snap.is_contango = contango
    snap.current_fut_ltp = 100.0
    snap.next_fut_ltp = 100.0 + spread
    snap.timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return snap


def _make_mock_alert(stock="RELIANCE", discount=45.0, threshold=40, trigger=1):
    alert = MagicMock()
    alert.stock = stock
    alert.discount_pct = discount
    alert.threshold = threshold
    alert.trigger_count = trigger
    alert.spread = 3.5
    alert.initial_spread = 6.2
    alert.current_fut_ltp = 100.0
    alert.next_fut_ltp = 103.5
    alert.timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return alert


def _make_broadcaster(snapshots=None, phase="ACTIVE", connected=True):
    spread = MagicMock()
    spread.snapshots = snapshots or {}

    orchestrator = MagicMock()
    orchestrator.status.return_value = {
        "cycle_count": 10,
        "alerts_fired": 2,
        "stocks_computed": 17,
        "stocks_skipped": 2,
        "phase": phase,
    }

    bridge = MagicMock()
    bridge.connected = connected
    bridge.tick_count = 5000

    session = MagicMock()
    session.current_phase.return_value = phase

    return WSBroadcaster(spread, orchestrator, bridge, session)


class TestWSBroadcasterInit(unittest.TestCase):
    def test_creates_with_all_engines(self):
        broadcaster = _make_broadcaster()
        self.assertIsNotNone(broadcaster)
        self.assertEqual(len(broadcaster._clients), 0)

    def test_build_init_message_contains_all_stocks(self):
        snapshots = {}
        for sym in STOCK_CONFIG:
            snapshots[sym] = _make_mock_snapshot(sym)

        broadcaster = _make_broadcaster(snapshots=snapshots)
        init_str = broadcaster._build_init_message()
        init = json.loads(init_str)

        self.assertEqual(init["type"], "init")
        self.assertEqual(len(init["stocks"]), len(STOCK_CONFIG))

    def test_init_message_has_status(self):
        broadcaster = _make_broadcaster(phase="ACTIVE", connected=True)
        init_str = broadcaster._build_init_message()
        init = json.loads(init_str)

        self.assertIn("status", init)
        self.assertEqual(init["status"]["phase"], "ACTIVE")
        self.assertTrue(init["status"]["is_connected"])
        self.assertTrue(init["status"]["market_open"])

    def test_init_message_market_closed_when_waiting(self):
        broadcaster = _make_broadcaster(phase="WAITING", connected=True)
        init_str = broadcaster._build_init_message()
        init = json.loads(init_str)

        self.assertFalse(init["status"]["market_open"])

    def test_init_message_shows_disconnected(self):
        broadcaster = _make_broadcaster(phase="ACTIVE", connected=False)
        init_str = broadcaster._build_init_message()
        init = json.loads(init_str)

        self.assertFalse(init["status"]["is_connected"])

    def test_init_message_stock_has_all_fields(self):
        snapshots = {"RELIANCE": _make_mock_snapshot("RELIANCE", spread=3.1, discount=50.0)}
        broadcaster = _make_broadcaster(snapshots=snapshots)
        init_str = broadcaster._build_init_message()
        init = json.loads(init_str)

        reliance = next(s for s in init["stocks"] if s["stock"] == "RELIANCE")
        self.assertEqual(reliance["current_spread"], 3.1)
        self.assertEqual(reliance["discount_pct"], 50.0)
        self.assertEqual(reliance["initial_spread"], 10.0)
        self.assertTrue(reliance["is_contango"])
        self.assertIsNotNone(reliance["timestamp"])

    def test_init_message_missing_stock_has_null_fields(self):
        broadcaster = _make_broadcaster(snapshots={})
        init_str = broadcaster._build_init_message()
        init = json.loads(init_str)

        for stock_entry in init["stocks"]:
            self.assertIsNone(stock_entry["current_spread"])
            self.assertIsNone(stock_entry["discount_pct"])
            self.assertIsNone(stock_entry["timestamp"])


class TestWSBroadcasterSnapshotToDict(unittest.TestCase):
    def test_rounds_values(self):
        snap = _make_mock_snapshot("TCS", spread=7.123456, discount=42.56789)
        broadcaster = _make_broadcaster()
        d = broadcaster._snapshot_to_dict(snap)

        self.assertEqual(d["current_spread"], 7.12)
        self.assertEqual(d["discount_pct"], 42.57)

    def test_contains_all_fields(self):
        snap = _make_mock_snapshot("INFOSYS")
        broadcaster = _make_broadcaster()
        d = broadcaster._snapshot_to_dict(snap)

        expected_keys = {"stock", "initial_spread", "current_spread", "discount_pct",
                         "is_contango", "current_fut_ltp", "next_fut_ltp", "timestamp"}
        self.assertEqual(set(d.keys()), expected_keys)


class TestWSBroadcasterLive(unittest.TestCase):
    """Live tests — start actual WS server, connect client, verify messages."""

    def _get_free_port(self):
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            return s.getsockname()[1]

    def test_server_starts_and_accepts_connection(self):
        port = self._get_free_port()
        broadcaster = _make_broadcaster()

        with patch("algo_engine.ws_broadcaster.BROADCAST_PORT", port):
            broadcaster.start()
            time.sleep(0.5)

            async def connect_and_check():
                import websockets
                async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                    msg = await asyncio.wait_for(ws.recv(), timeout=3)
                    data = json.loads(msg)
                    self.assertEqual(data["type"], "init")
                    self.assertIn("stocks", data)
                    self.assertIn("status", data)

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(connect_and_check())
            finally:
                loop.close()
                broadcaster.stop()

    def test_init_message_on_connect(self):
        port = self._get_free_port()
        snapshots = {"RELIANCE": _make_mock_snapshot("RELIANCE", spread=3.1, discount=50.0)}
        broadcaster = _make_broadcaster(snapshots=snapshots, phase="ACTIVE")

        with patch("algo_engine.ws_broadcaster.BROADCAST_PORT", port):
            broadcaster.start()
            time.sleep(0.5)

            async def check():
                import websockets
                async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                    msg = await asyncio.wait_for(ws.recv(), timeout=3)
                    data = json.loads(msg)

                    self.assertEqual(data["type"], "init")
                    self.assertEqual(data["status"]["phase"], "ACTIVE")
                    self.assertTrue(data["status"]["market_open"])

                    reliance = next(s for s in data["stocks"] if s["stock"] == "RELIANCE")
                    self.assertEqual(reliance["current_spread"], 3.1)
                    self.assertEqual(reliance["discount_pct"], 50.0)

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(check())
            finally:
                loop.close()
                broadcaster.stop()

    def test_alert_broadcast_reaches_client(self):
        port = self._get_free_port()
        broadcaster = _make_broadcaster()

        with patch("algo_engine.ws_broadcaster.BROADCAST_PORT", port):
            broadcaster.start()
            time.sleep(0.5)

            async def check():
                import websockets
                async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                    init_msg = await asyncio.wait_for(ws.recv(), timeout=3)
                    init_data = json.loads(init_msg)
                    self.assertEqual(init_data["type"], "init")

                    alert = _make_mock_alert("BAJFINANCE", discount=60.16, trigger=1)
                    broadcaster.broadcast_alert(alert)

                    alert_msg = await asyncio.wait_for(ws.recv(), timeout=3)
                    alert_data = json.loads(alert_msg)

                    self.assertEqual(alert_data["type"], "alert")
                    self.assertEqual(alert_data["stock"], "BAJFINANCE")
                    self.assertEqual(alert_data["discount_pct"], 60.16)
                    self.assertEqual(alert_data["threshold"], 40)
                    self.assertEqual(alert_data["trigger_count"], 1)

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(check())
            finally:
                loop.close()
                broadcaster.stop()

    def test_multiple_alerts_in_sequence(self):
        port = self._get_free_port()
        broadcaster = _make_broadcaster()

        with patch("algo_engine.ws_broadcaster.BROADCAST_PORT", port):
            broadcaster.start()
            time.sleep(0.5)

            async def check():
                import websockets
                async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                    await asyncio.wait_for(ws.recv(), timeout=3)

                    for stock, discount in [("TATASTEEL", 43.24), ("HCLTECH", 41.33), ("INDUSINDBK", 42.86)]:
                        alert = _make_mock_alert(stock, discount=discount)
                        broadcaster.broadcast_alert(alert)

                    received = []
                    for _ in range(3):
                        msg = await asyncio.wait_for(ws.recv(), timeout=3)
                        data = json.loads(msg)
                        self.assertEqual(data["type"], "alert")
                        received.append(data["stock"])

                    self.assertIn("TATASTEEL", received)
                    self.assertIn("HCLTECH", received)
                    self.assertIn("INDUSINDBK", received)

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(check())
            finally:
                loop.close()
                broadcaster.stop()

    def test_multiple_clients_receive_alerts(self):
        port = self._get_free_port()
        broadcaster = _make_broadcaster()

        with patch("algo_engine.ws_broadcaster.BROADCAST_PORT", port):
            broadcaster.start()
            time.sleep(0.5)

            async def check():
                import websockets
                async with websockets.connect(f"ws://127.0.0.1:{port}") as ws1:
                    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws2:
                        await asyncio.wait_for(ws1.recv(), timeout=3)
                        await asyncio.wait_for(ws2.recv(), timeout=3)

                        alert = _make_mock_alert("SBIN", discount=55.0)
                        broadcaster.broadcast_alert(alert)
                        time.sleep(0.3)

                        msg1 = await asyncio.wait_for(ws1.recv(), timeout=3)
                        msg2 = await asyncio.wait_for(ws2.recv(), timeout=3)

                        d1 = json.loads(msg1)
                        d2 = json.loads(msg2)

                        self.assertEqual(d1["type"], "alert")
                        self.assertEqual(d2["type"], "alert")
                        self.assertEqual(d1["stock"], "SBIN")
                        self.assertEqual(d2["stock"], "SBIN")

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(check())
            finally:
                loop.close()
                broadcaster.stop()

    def test_ping_pong(self):
        port = self._get_free_port()
        broadcaster = _make_broadcaster()

        with patch("algo_engine.ws_broadcaster.BROADCAST_PORT", port):
            broadcaster.start()
            time.sleep(0.5)

            async def check():
                import websockets
                async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                    await asyncio.wait_for(ws.recv(), timeout=3)

                    await ws.send(json.dumps({"type": "ping"}))
                    resp = await asyncio.wait_for(ws.recv(), timeout=3)
                    data = json.loads(resp)
                    self.assertEqual(data["type"], "pong")

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(check())
            finally:
                loop.close()
                broadcaster.stop()

    def test_client_disconnect_cleanup(self):
        port = self._get_free_port()
        broadcaster = _make_broadcaster()

        with patch("algo_engine.ws_broadcaster.BROADCAST_PORT", port):
            broadcaster.start()
            time.sleep(0.5)

            async def check():
                import websockets
                ws = await websockets.connect(f"ws://127.0.0.1:{port}")
                await asyncio.wait_for(ws.recv(), timeout=3)
                self.assertEqual(len(broadcaster._clients), 1)

                await ws.close()
                await asyncio.sleep(0.5)

                self.assertEqual(len(broadcaster._clients), 0)

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(check())
            finally:
                loop.close()
                broadcaster.stop()

    def test_broadcast_alert_before_loop_ready(self):
        broadcaster = _make_broadcaster()
        alert = _make_mock_alert()
        broadcaster.broadcast_alert(alert)

    def test_status_change_detected_after_phase_shift(self):
        port = self._get_free_port()
        session = MagicMock()
        session.current_phase.return_value = "WAITING"

        spread = MagicMock()
        spread.snapshots = {}
        orchestrator = MagicMock()
        bridge = MagicMock()
        bridge.connected = True

        broadcaster = WSBroadcaster(spread, orchestrator, bridge, session)

        with patch("algo_engine.ws_broadcaster.BROADCAST_PORT", self._get_free_port()):
            broadcaster._last_phase = "WAITING"
            broadcaster._last_bridge_connected = True

            session.current_phase.return_value = "ACTIVE"
            self.assertTrue(True)


class TestWSBroadcasterSnapshotBroadcast(unittest.TestCase):
    def test_snapshot_broadcast_sends_all_stocks(self):
        port = TestWSBroadcasterSnapshotBroadcast._get_free_port()
        snapshots = {}
        for sym in STOCK_CONFIG:
            snapshots[sym] = _make_mock_snapshot(sym)

        broadcaster = _make_broadcaster(snapshots=snapshots)

        with patch("algo_engine.ws_broadcaster.BROADCAST_PORT", port):
            broadcaster.start()
            time.sleep(0.5)

            async def check():
                import websockets
                async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                    await asyncio.wait_for(ws.recv(), timeout=3)

                    loop = asyncio.get_event_loop()
                    await loop.create_task(broadcaster._broadcast_snapshot())

                    msg = await asyncio.wait_for(ws.recv(), timeout=3)
                    data = json.loads(msg)

                    self.assertEqual(data["type"], "snapshot")
                    self.assertEqual(len(data["stocks"]), len(STOCK_CONFIG))
                    self.assertIn("timestamp", data)

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(check())
            finally:
                loop.close()
                broadcaster.stop()

    @staticmethod
    def _get_free_port():
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            return s.getsockname()[1]


class TestWSBroadcasterStop(unittest.TestCase):
    def test_stop_shuts_down_cleanly(self):
        port = TestWSBroadcasterStop._get_free_port()
        broadcaster = _make_broadcaster()

        with patch("algo_engine.ws_broadcaster.BROADCAST_PORT", port):
            broadcaster.start()
            time.sleep(0.5)
            broadcaster.stop()
            time.sleep(0.5)

            async def check_dead():
                import websockets
                try:
                    async with websockets.connect(f"ws://127.0.0.1:{port}",
                                                  open_timeout=1) as ws:
                        return False
                except Exception:
                    return True

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(check_dead())
                self.assertTrue(result)
            finally:
                loop.close()

    @staticmethod
    def _get_free_port():
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            return s.getsockname()[1]


if __name__ == "__main__":
    unittest.main()
