"""
E2E Test Server - Combined mock WS broadcaster (8766) + HTTP data server (8767).
Runs in background for frontend E2E testing.
"""
import sys
import os
import io
import json
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from http import HTTPStatus

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

STOCKS_5 = ["RELIANCE", "TCS", "INFOSYS", "HDFCBANK", "SBIN"]
INITIAL_SPREADS = {"RELIANCE": 6.20, "TCS": 10.10, "INFOSYS": 5.30, "HDFCBANK": 3.55, "SBIN": 4.70}
FUT_PRICES = {"RELIANCE": 1414.0, "TCS": 3472.0, "INFOSYS": 1500.0, "HDFCBANK": 965.0, "SBIN": 790.0}


def _now_str():
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _date_tag():
    return datetime.now(IST).strftime("%Y%m%d")


class DataHTTPServer:
    def __init__(self, ws_server=None):
        self._lock = threading.Lock()
        self._ws_server = ws_server

    def _load_all_data(self):
        dt = _date_tag()
        result = {}
        for prefix in ["active_opportunities", "expired_opportunities", "daily_instruction_log",
                        "execution_details", "correction_history", "daily_metrics"]:
            key = f"{prefix}_{dt}"
            path = DATA_DIR / f"{key}.json"
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    result[key] = json.load(f)
            else:
                result[key] = []
        sp = DATA_DIR / "settings.json"
        if sp.exists():
            with open(sp, "r", encoding="utf-8") as f:
                result["settings"] = json.load(f)
        else:
            result["settings"] = {}
        return result

    def _save_table(self, table, content):
        path = DATA_DIR / f"{table}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(content, f, indent=2, default=str)

    def _save_settings(self, data):
        path = DATA_DIR / "settings.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def start(self, port=8767):
        ds = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/data/load":
                    data = ds._load_all_data()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps(data, default=str).encode("utf-8"))
                elif self.path == "/health":
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok"}')
                else:
                    self.send_response(HTTPStatus.NOT_FOUND)
                    self.end_headers()

            def do_POST(self):
                cl = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(cl)
                try:
                    req = json.loads(body.decode("utf-8"))
                except Exception:
                    self.send_response(HTTPStatus.BAD_REQUEST)
                    self.end_headers()
                    return

                if self.path == "/data/save":
                    table = req.get("table")
                    content = req.get("content")
                    if table and content is not None:
                        ds._save_table(table, content)
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok"}')
                elif self.path == "/data/settings":
                    ds._save_settings(req)
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok"}')
                elif self.path == "/health":
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok"}')
                elif self.path == "/test/expire":
                    stock = req.get("stock", "RELIANCE")
                    final_spread = req.get("final_spread", 5.80)
                    if ds._ws_server:
                        ds._ws_server.broadcast_expired(stock, final_spread)
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "expired", "stock": stock}).encode("utf-8"))
                else:
                    self.send_response(HTTPStatus.NOT_FOUND)
                    self.end_headers()

            def do_OPTIONS(self):
                self.send_response(HTTPStatus.OK)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def log_message(self, fmt, *args):
                pass

        server = HTTPServer(("127.0.0.1", port), Handler)
        t = threading.Thread(target=server.serve_forever, daemon=True, name="test-http")
        t.start()
        print(f"HTTP data server on http://127.0.0.1:{port}")
        return server


class MockWSServer:
    def __init__(self):
        import random
        self.spread_state = {}
        self.clients = set()
        self.loop = None
        for sym in STOCKS_5:
            init_sp = INITIAL_SPREADS[sym]
            cur_sp = init_sp * 0.3
            disc = (init_sp - cur_sp) / init_sp * 100
            self.spread_state[sym] = {
                "current_spread": round(cur_sp, 2),
                "discount_pct": round(disc, 2),
                "current_fut_ltp": round(FUT_PRICES[sym] * 1.0, 2),
                "next_fut_ltp": round(FUT_PRICES[sym] + cur_sp, 2),
            }

    def broadcast_expired(self, stock, final_spread):
        import asyncio
        if not self.loop or not self.clients:
            return
        msg = json.dumps({
            "type": "alert_expired",
            "stock": stock,
            "final_spread": final_spread,
            "timestamp": _now_str(),
        })
        for ws in list(self.clients):
            try:
                asyncio.run_coroutine_threadsafe(ws.send(msg), self.loop)
            except Exception:
                pass

    def _build_stock_data(self, sym):
        st = self.spread_state[sym]
        return {
            "stock": sym,
            "initial_spread": INITIAL_SPREADS[sym],
            "current_spread": st["current_spread"],
            "discount_pct": st["discount_pct"],
            "is_contango": True,
            "current_fut_ltp": st["current_fut_ltp"],
            "next_fut_ltp": st["next_fut_ltp"],
            "timestamp": _now_str(),
        }

    def _build_snapshot(self):
        stocks = [self._build_stock_data(sym) for sym in STOCKS_5]
        return {"type": "snapshot", "stocks": stocks, "timestamp": _now_str()}

    def _build_init(self):
        stocks = [self._build_stock_data(sym) for sym in STOCKS_5]
        status = {"phase": "ACTIVE", "is_connected": True, "market_open": True}
        return {"type": "init", "stocks": stocks, "status": status}

    def _build_status(self):
        return {
            "type": "status",
            "phase": "ACTIVE",
            "market_open": True,
            "stocks": len(STOCKS_5),
            "timestamp": _now_str(),
        }

    async def start(self, port=8766):
        import websockets
        import asyncio

        mock = self

        async def handler(ws):
            mock.clients.add(ws)
            try:
                await ws.send(json.dumps(self._build_init()))
                await ws.send(json.dumps(self._build_snapshot()))
                while True:
                    await asyncio.sleep(10)
                    await ws.send(json.dumps(self._build_snapshot()))
            except Exception:
                pass
            finally:
                mock.clients.discard(ws)

        server = await websockets.serve(handler, "127.0.0.1", port)
        print(f"Mock WS server on ws://127.0.0.1:{port}")
        return server


def run():
    import asyncio

    mock_ws = MockWSServer()
    http_server = DataHTTPServer(ws_server=mock_ws)
    http_server.start(8767)

    loop = asyncio.new_event_loop()
    mock_ws.loop = loop

    def run_ws():
        asyncio.set_event_loop(loop)
        ws_server = loop.run_until_complete(mock_ws.start(8766))
        loop.run_forever()

    t = threading.Thread(target=run_ws, daemon=True, name="test-ws")
    t.start()

    print("\nE2E Test Server running:")
    print("  WS:   ws://127.0.0.1:8766")
    print("  HTTP: http://127.0.0.1:8767")
    print("  Data: " + str(DATA_DIR))
    print("\nPress Ctrl+C to stop\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    run()
