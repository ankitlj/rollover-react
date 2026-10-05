"""
Mock WS Broadcaster — simulates algo engine on port 8766 for frontend testing.

Usage:
    python mock_broadcaster.py                    # normal mode
    python mock_broadcaster.py --market-closed    # market_open=false
    python mock_broadcaster.py --partial          # only 10 of 19 stocks
    python mock_broadcaster.py --disconnect-loop  # rapid connect/disconnect
    python mock_broadcaster.py --malformed        # send bad JSON occasionally
    python mock_broadcaster.py --stale            # stop sending after 30s
    python mock_broadcaster.py --unknown-alert    # alert for unknown stock
"""

import asyncio
import json
import random
import sys
import io
import time
import threading
import argparse
from datetime import datetime, timedelta, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

IST = timezone(timedelta(hours=5, minutes=30))

STOCKS = {
    "RELIANCE":     {"initial": 6.20,  "threshold": 35, "fut_price": 1414.0},
    "ADANIPORTS":   {"initial": 14.20, "threshold": 35, "fut_price": 1255.0},
    "AMBUJACEM":    {"initial": 2.50,  "threshold": 35, "fut_price": 538.0},
    "ASTRAL":       {"initial": 1.70,  "threshold": 40, "fut_price": 1335.0},
    "GRASIM":       {"initial": 23.90, "threshold": 40, "fut_price": 2726.0},
    "HCLTECH":      {"initial": 7.50,  "threshold": 40, "fut_price": 1567.0},
    "HDFCBANK":     {"initial": 3.55,  "threshold": 40, "fut_price": 965.0},
    "INFOSYS":      {"initial": 5.30,  "threshold": 40, "fut_price": 1500.0},
    "JSWSTEEL":     {"initial": 5.00,  "threshold": 40, "fut_price": 1021.0},
    "MARUTI":       {"initial": 54.00, "threshold": 40, "fut_price": 12257.0},
    "TCS":          {"initial": 10.10, "threshold": 40, "fut_price": 3472.0},
    "TATASTEEL":    {"initial": 1.11,  "threshold": 40, "fut_price": 140.0},
    "BAJFINANCE":   {"initial": 6.40,  "threshold": 40, "fut_price": 8580.0},
    "SBIN":         {"initial": 4.70,  "threshold": 40, "fut_price": 790.0},
    "LT":           {"initial": 22.20, "threshold": 40, "fut_price": 3325.0},
    "HAL":          {"initial": 27.10, "threshold": 40, "fut_price": 4499.0},
    "BANDHANBANK":  {"initial": 1.19,  "threshold": 40, "fut_price": 169.0},
    "ADANIENT":     {"initial": 23.90, "threshold": 40, "fut_price": 2279.0},
    "INDUSINDBK":   {"initial": 3.50,  "threshold": 40, "fut_price": 835.0},
}

PORT = 8766
HOST = "127.0.0.1"


class MockBroadcaster:
    def __init__(self, args):
        self.args = args
        self.clients = set()
        self.spread_state = {}
        self.alert_counts = {}
        self.running = True
        self.snapshot_count = 0
        self._init_spreads()

    def _init_spreads(self):
        for sym, cfg in STOCKS.items():
            init_spread = cfg["initial"]
            current_spread = init_spread * random.uniform(0.3, 0.9)
            discount_pct = (init_spread - current_spread) / init_spread * 100
            self.spread_state[sym] = {
                "current_spread": round(current_spread, 2),
                "discount_pct": round(discount_pct, 2),
                "current_fut_ltp": round(cfg["fut_price"] * random.uniform(0.98, 1.02), 2),
                "next_fut_ltp": round(cfg["fut_price"] * random.uniform(0.99, 1.03), 2),
            }
            self.alert_counts[sym] = 0

    def _now_str(self):
        return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    def _build_stock_entry(self, sym, include_data=True):
        cfg = STOCKS[sym]
        if not include_data:
            return {
                "stock": sym,
                "initial_spread": cfg["initial"],
                "current_spread": None,
                "discount_pct": None,
                "is_contango": None,
                "current_fut_ltp": None,
                "next_fut_ltp": None,
                "timestamp": None,
            }
        state = self.spread_state[sym]
        spread = state["current_spread"]
        return {
            "stock": sym,
            "initial_spread": cfg["initial"],
            "current_spread": spread,
            "discount_pct": state["discount_pct"],
            "is_contango": spread > 0,
            "current_fut_ltp": state["current_fut_ltp"],
            "next_fut_ltp": state["next_fut_ltp"],
            "timestamp": self._now_str(),
        }

    def build_init(self):
        stocks = []
        syms = list(STOCKS.keys())
        if self.args.partial:
            syms_with_data = random.sample(syms, 10)
        else:
            syms_with_data = syms

        for sym in syms:
            stocks.append(self._build_stock_entry(sym, include_data=(sym in syms_with_data)))

        msg = {
            "type": "init",
            "stocks": stocks,
            "status": {
                "phase": "ACTIVE" if not self.args.market_closed else "CLOSED",
                "is_connected": True,
                "market_open": not self.args.market_closed,
            },
        }
        return json.dumps(msg, default=str)

    def build_snapshot(self):
        self._evolve_spreads()
        self.snapshot_count += 1

        stocks = []
        for sym in STOCKS:
            if self.args.partial and random.random() < 0.3:
                continue
            stocks.append(self._build_stock_entry(sym))

        msg = {
            "type": "snapshot",
            "stocks": stocks,
            "timestamp": self._now_str(),
        }
        return json.dumps(msg, default=str)

    def _evolve_spreads(self):
        for sym, cfg in STOCKS.items():
            state = self.spread_state[sym]
            drift = random.uniform(-0.5, 0.5)
            new_spread = max(0.01, state["current_spread"] + drift)
            discount_pct = (cfg["initial"] - new_spread) / cfg["initial"] * 100
            state["current_spread"] = round(new_spread, 2)
            state["discount_pct"] = round(discount_pct, 2)
            state["current_fut_ltp"] = round(state["current_fut_ltp"] * random.uniform(0.999, 1.001), 2)
            state["next_fut_ltp"] = round(state["next_fut_ltp"] * random.uniform(0.999, 1.001), 2)

    def build_alert(self, sym=None):
        if sym is None:
            sym = random.choice(list(STOCKS.keys()))
        cfg = STOCKS[sym]
        state = self.spread_state[sym]
        self.alert_counts[sym] = self.alert_counts.get(sym, 0) + 1

        discount = max(cfg["threshold"], state["discount_pct"]) + random.uniform(0, 5)
        spread = cfg["initial"] * (1 - discount / 100)

        msg = {
            "type": "alert",
            "stock": sym,
            "discount_pct": round(discount, 2),
            "threshold": cfg["threshold"],
            "trigger_count": self.alert_counts[sym],
            "spread": round(spread, 2),
            "initial_spread": cfg["initial"],
            "current_fut_ltp": state["current_fut_ltp"],
            "next_fut_ltp": state["next_fut_ltp"],
            "timestamp": self._now_str(),
        }
        return json.dumps(msg, default=str)

    def build_status(self, market_open=None):
        mo = market_open if market_open is not None else (not self.args.market_closed)
        msg = {
            "type": "status",
            "phase": "ACTIVE" if mo else "CLOSED",
            "is_connected": True,
            "market_open": mo,
        }
        return json.dumps(msg, default=str)

    async def handle_client(self, websocket):
        addr = websocket.remote_address
        print(f"[MOCK] Client connected: {addr}")
        self.clients.add(websocket)
        try:
            await websocket.send(self.build_init())
            print(f"[MOCK] Sent init to {addr} ({len(STOCKS)} stocks)")

            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get("type") == "ping":
                        await websocket.send(json.dumps({"type": "pong"}))
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            print(f"[MOCK] Client error: {e}")
        finally:
            self.clients.discard(websocket)
            print(f"[MOCK] Client disconnected: {addr}")

    async def broadcast(self, msg):
        if not self.clients:
            return
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def snapshot_loop(self):
        while self.running:
            await asyncio.sleep(10)
            if not self.running:
                break

            if self.args.stale and self.snapshot_count >= 3:
                print("[MOCK] STALE MODE: stopped sending snapshots")
                continue

            if self.args.malformed and random.random() < 0.2:
                bad = "{this is not valid json,,,"
                await self.broadcast(bad)
                print("[MOCK] Sent MALFORMED message")
                continue

            msg = self.build_snapshot()
            await self.broadcast(msg)
            print(f"[MOCK] Snapshot #{self.snapshot_count} -> {len(self.clients)} clients")

    async def alert_loop(self):
        while self.running:
            await asyncio.sleep(30)
            if not self.running:
                break

            if self.args.unknown_alert:
                msg = self.build_alert(sym="FAKESTOCK")
                print("[MOCK] Sent alert for UNKNOWN stock FAKESTOCK")
            else:
                sym = random.choice(list(STOCKS.keys()))
                msg = self.build_alert(sym)
                print(f"[MOCK] Alert fired: {sym}")

            await self.broadcast(msg)

    async def status_toggle_loop(self):
        if not self.args.disconnect_loop:
            return
        while self.running:
            await asyncio.sleep(15)
            if not self.running:
                break
            msg = self.build_status(market_open=False)
            await self.broadcast(msg)
            print("[MOCK] Status: market CLOSED")
            await asyncio.sleep(5)
            msg = self.build_status(market_open=True)
            await self.broadcast(msg)
            print("[MOCK] Status: market OPEN")

    async def run(self):
        import websockets
        print(f"[MOCK] Starting mock broadcaster on ws://{HOST}:{PORT}")
        print(f"[MOCK] Options: market_closed={self.args.market_closed}, partial={self.args.partial}, "
              f"disconnect_loop={self.args.disconnect_loop}, malformed={self.args.malformed}, "
              f"stale={self.args.stale}, unknown_alert={self.args.unknown_alert}")

        async with websockets.serve(self.handle_client, HOST, PORT, ping_interval=20, ping_timeout=10):
            asyncio.create_task(self.snapshot_loop())
            asyncio.create_task(self.alert_loop())
            asyncio.create_task(self.status_toggle_loop())
            print(f"[MOCK] Ready. Waiting for clients...")
            await asyncio.Future()


def main():
    parser = argparse.ArgumentParser(description="Mock WS Broadcaster for frontend testing")
    parser.add_argument("--market-closed", action="store_true", help="Send market_open=false")
    parser.add_argument("--partial", action="store_true", help="Only send 10 of 19 stocks in init")
    parser.add_argument("--disconnect-loop", action="store_true", help="Toggle market open/closed every 15s")
    parser.add_argument("--malformed", action="store_true", help="Send malformed JSON occasionally")
    parser.add_argument("--stale", action="store_true", help="Stop sending snapshots after 3")
    parser.add_argument("--unknown-alert", action="store_true", help="Send alerts for unknown stock symbol")
    args = parser.parse_args()

    broadcaster = MockBroadcaster(args)

    try:
        asyncio.run(broadcaster.run())
    except KeyboardInterrupt:
        print("\n[MOCK] Shutting down...")
        broadcaster.running = False


if __name__ == "__main__":
    main()
