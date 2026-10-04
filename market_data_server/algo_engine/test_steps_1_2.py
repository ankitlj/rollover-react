import sys
import json
import time
import unittest
import threading

sys.path.insert(0, r"C:\Users\Ankit\Desktop\RS FOLDER\rollover-react\market_data_server")

from algo_engine.config import (
    STOCK_CONFIG, THRESHOLDS, INITIAL_SPREADS,
    STOCK_COUNT, TOTAL_TOKENS, FRESHNESS_WINDOW_MS,
    WARMUP_HOUR, WARMUP_MINUTE, CLOSE_HOUR, CLOSE_MINUTE,
    IST, WS_URI,
)
from algo_engine.bridge import TickBridge, Tick


# ── Step 1: Config Tests ────────────────────────────────────────────────────


class TestStockConfig(unittest.TestCase):

    def test_stock_count(self):
        self.assertEqual(STOCK_COUNT, 19)

    def test_total_tokens(self):
        self.assertEqual(TOTAL_TOKENS, 57)

    def test_all_stocks_have_lot_and_threshold(self):
        for sym, cfg in STOCK_CONFIG.items():
            self.assertIn("lot", cfg, f"{sym} missing lot")
            self.assertIn("threshold", cfg, f"{sym} missing threshold")
            self.assertIsInstance(cfg["lot"], int, f"{sym} lot not int")
            self.assertIsInstance(cfg["threshold"], (int, float), f"{sym} threshold not numeric")
            self.assertGreater(cfg["lot"], 0, f"{sym} lot <= 0")
            self.assertGreater(cfg["threshold"], 0, f"{sym} threshold <= 0")

    def test_known_stocks_present(self):
        expected = [
            "RELIANCE", "ADANIPORTS", "AMBUJACEM", "ASTRAL", "GRASIM",
            "HCLTECH", "HDFCBANK", "INFOSYS", "JSWSTEEL", "MARUTI",
            "TCS", "TATASTEEL", "BAJFINANCE", "SBIN", "LT",
            "HAL", "BANDHANBANK", "ADANIENT", "INDUSINDBK",
        ]
        for sym in expected:
            self.assertIn(sym, STOCK_CONFIG, f"{sym} not in STOCK_CONFIG")

    def test_lot_sizes(self):
        expected = {
            "RELIANCE": 500, "ADANIPORTS": 475, "AMBUJACEM": 1050,
            "ASTRAL": 425, "GRASIM": 250, "HCLTECH": 350,
            "HDFCBANK": 550, "INFOSYS": 400, "JSWSTEEL": 675,
            "MARUTI": 50, "TCS": 175, "TATASTEEL": 2750,
            "BAJFINANCE": 750, "SBIN": 750, "LT": 175,
            "HAL": 150, "BANDHANBANK": 3600, "ADANIENT": 309,
            "INDUSINDBK": 700,
        }
        for sym, lot in expected.items():
            self.assertEqual(STOCK_CONFIG[sym]["lot"], lot,
                             f"{sym} lot: expected {lot}, got {STOCK_CONFIG[sym]['lot']}")

    def test_threshold_35_stocks(self):
        for sym in ["ADANIPORTS", "RELIANCE", "AMBUJACEM"]:
            self.assertEqual(STOCK_CONFIG[sym]["threshold"], 35,
                             f"{sym} should have threshold 35")

    def test_threshold_40_stocks(self):
        expected_40 = [
            "ASTRAL", "GRASIM", "HCLTECH", "HDFCBANK", "INFOSYS",
            "JSWSTEEL", "MARUTI", "TCS", "TATASTEEL", "BAJFINANCE",
            "SBIN", "LT", "HAL", "BANDHANBANK", "ADANIENT", "INDUSINDBK",
        ]
        for sym in expected_40:
            self.assertEqual(STOCK_CONFIG[sym]["threshold"], 40,
                             f"{sym} should have threshold 40")

    def test_thresholds_dict(self):
        self.assertEqual(len(THRESHOLDS), 19)
        self.assertEqual(THRESHOLDS["RELIANCE"], 35)
        self.assertEqual(THRESHOLDS["ADANIPORTS"], 35)
        self.assertEqual(THRESHOLDS["AMBUJACEM"], 35)
        self.assertEqual(THRESHOLDS["ASTRAL"], 40)
        self.assertEqual(THRESHOLDS["TATASTEEL"], 40)

    def test_only_3_stocks_at_35(self):
        count_35 = sum(1 for t in THRESHOLDS.values() if t == 35)
        self.assertEqual(count_35, 3)

    def test_remaining_16_at_40(self):
        count_40 = sum(1 for t in THRESHOLDS.values() if t == 40)
        self.assertEqual(count_40, 16)

    def test_initial_spreads_are_set(self):
        self.assertEqual(len(INITIAL_SPREADS), 19)
        for sym, val in INITIAL_SPREADS.items():
            self.assertIsNotNone(val, f"{sym} initial_spread should not be None")
            self.assertIsInstance(val, (int, float), f"{sym} initial_spread not numeric")

    def test_freshness_window(self):
        self.assertEqual(FRESHNESS_WINDOW_MS, 500)

    def test_session_constants(self):
        self.assertEqual(WARMUP_HOUR, 9)
        self.assertEqual(WARMUP_MINUTE, 20)
        self.assertEqual(CLOSE_HOUR, 15)
        self.assertEqual(CLOSE_MINUTE, 0)

    def test_ist_offset(self):
        import datetime
        expected = datetime.timedelta(hours=5, minutes=30)
        self.assertEqual(IST.utcoffset(None), expected)

    def test_ws_uri(self):
        self.assertEqual(WS_URI, "ws://127.0.0.1:8765")


# ── Step 2: Bridge Tests ────────────────────────────────────────────────────


class TestTickDataclass(unittest.TestCase):

    def test_basic_creation(self):
        t = Tick(token=123, ltp=100.5, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        self.assertEqual(t.token, 123)
        self.assertEqual(t.ltp, 100.5)
        self.assertEqual(t.ts, "2026-10-01 09:20:00.000")

    def test_sym_from_info(self):
        t = Tick(token=1, ltp=1.0, ts="", recv_mono_ns=0,
                 info={"sym": "RELIANCE", "type": "future", "month": "current"})
        self.assertEqual(t.sym, "RELIANCE")
        self.assertEqual(t.fut_month, "current")
        self.assertEqual(t.inst_type, "future")

    def test_sym_none_when_no_info(self):
        t = Tick(token=1, ltp=1.0, ts="", recv_mono_ns=0)
        self.assertIsNone(t.sym)
        self.assertIsNone(t.fut_month)
        self.assertIsNone(t.inst_type)

    def test_default_values(self):
        t = Tick(token=1, ltp=1.0, ts="", recv_mono_ns=0)
        self.assertEqual(t.gen, 0)
        self.assertEqual(t.mode, 0)
        self.assertEqual(t.volume, 0)
        self.assertEqual(t.oi, 0)


class TestTickBridgeInit(unittest.TestCase):

    def test_initial_state(self):
        b = TickBridge()
        self.assertFalse(b.connected)
        self.assertEqual(b.tick_count, 0)
        self.assertEqual(b.token_count, 0)
        self.assertEqual(b.stocks, [])

    def test_custom_uri(self):
        b = TickBridge(uri="ws://10.0.0.1:9999")
        self.assertEqual(b.uri, "ws://10.0.0.1:9999")

    def test_default_uri(self):
        b = TickBridge()
        self.assertEqual(b.uri, "ws://127.0.0.1:8765")


class TestTickInjection(unittest.TestCase):

    def setUp(self):
        self.bridge = TickBridge()

    def test_inject_single_tick(self):
        self.bridge.inject_tick(123, 100.5, "2026-10-01 09:20:00.000")
        self.assertEqual(self.bridge.tick_count, 1)
        tick = self.bridge.get_tick(123)
        self.assertIsNotNone(tick)
        self.assertEqual(tick.token, 123)
        self.assertAlmostEqual(tick.ltp, 100.5)
        self.assertEqual(tick.ts, "2026-10-01 09:20:00.000")

    def test_inject_overwrites_previous(self):
        self.bridge.inject_tick(123, 100.0)
        self.bridge.inject_tick(123, 200.0)
        self.assertEqual(self.bridge.tick_count, 2)
        self.assertAlmostEqual(self.bridge.get_tick(123).ltp, 200.0)

    def test_inject_multiple_tokens(self):
        self.bridge.inject_tick(1, 10.0)
        self.bridge.inject_tick(2, 20.0)
        self.bridge.inject_tick(3, 30.0)
        self.assertEqual(self.bridge.tick_count, 3)
        self.assertAlmostEqual(self.bridge.get_tick(1).ltp, 10.0)
        self.assertAlmostEqual(self.bridge.get_tick(2).ltp, 20.0)
        self.assertAlmostEqual(self.bridge.get_tick(3).ltp, 30.0)

    def test_inject_with_info(self):
        info = {"sym": "RELIANCE", "type": "future", "month": "current"}
        self.bridge.inject_tick(123, 100.0, info=info)
        tick = self.bridge.get_tick(123)
        self.assertEqual(tick.sym, "RELIANCE")
        self.assertEqual(tick.fut_month, "current")
        self.assertEqual(tick.inst_type, "future")

    def test_inject_with_gen(self):
        self.bridge.inject_tick(123, 100.0, gen=5)
        self.assertEqual(self.bridge.get_tick(123).gen, 5)

    def test_get_tick_missing_returns_none(self):
        self.assertIsNone(self.bridge.get_tick(999))

    def test_get_all_ticks(self):
        self.bridge.inject_tick(1, 10.0)
        self.bridge.inject_tick(2, 20.0)
        all_ticks = self.bridge.get_all_ticks()
        self.assertEqual(len(all_ticks), 2)
        self.assertIn(1, all_ticks)
        self.assertIn(2, all_ticks)

    def test_get_all_ticks_returns_copy(self):
        self.bridge.inject_tick(1, 10.0)
        all_ticks = self.bridge.get_all_ticks()
        all_ticks.clear()
        self.assertEqual(self.bridge.tick_count, 1)


class TestTickMetadata(unittest.TestCase):

    def setUp(self):
        self.bridge = TickBridge()
        self.bridge.inject_metadata(
            tokens={
                "100": {"type": "cash", "sym": "RELIANCE", "tsym": "RELIANCE-EQ", "lot": 500},
                "200": {"type": "future", "month": "current", "sym": "RELIANCE",
                         "tsym": "RELIANCE28OCT26FUT", "expiry": "28-Oct-2026", "lot": 500},
                "300": {"type": "future", "month": "next", "sym": "RELIANCE",
                         "tsym": "RELIANCE26NOV26FUT", "expiry": "26-Nov-2026", "lot": 500},
                "400": {"type": "cash", "sym": "TCS", "tsym": "TCS-EQ", "lot": 175},
                "500": {"type": "future", "month": "current", "sym": "TCS",
                         "tsym": "TCS28OCT26FUT", "expiry": "28-Oct-2026", "lot": 175},
                "600": {"type": "future", "month": "next", "sym": "TCS",
                         "tsym": "TCS26NOV26FUT", "expiry": "26-Nov-2026", "lot": 175},
            },
            stocks=[{"sym": "RELIANCE", "lot": 500}, {"sym": "TCS", "lot": 175}],
        )

    def test_token_count(self):
        self.assertEqual(self.bridge.token_count, 6)

    def test_stocks_list(self):
        self.assertEqual(len(self.bridge.stocks), 2)

    def test_get_token_info(self):
        info = self.bridge.get_token_info(100)
        self.assertIsNotNone(info)
        self.assertEqual(info["sym"], "RELIANCE")
        self.assertEqual(info["type"], "cash")

    def test_get_token_info_missing(self):
        self.assertIsNone(self.bridge.get_token_info(999))

    def test_get_tokens_for_reliance(self):
        tokens = self.bridge.get_tokens_for_stock("RELIANCE")
        self.assertEqual(tokens["cash"], 100)
        self.assertEqual(tokens["current"], 200)
        self.assertEqual(tokens["next"], 300)

    def test_get_tokens_for_tcs(self):
        tokens = self.bridge.get_tokens_for_stock("TCS")
        self.assertEqual(tokens["cash"], 400)
        self.assertEqual(tokens["current"], 500)
        self.assertEqual(tokens["next"], 600)

    def test_get_tokens_unknown_stock(self):
        tokens = self.bridge.get_tokens_for_stock("UNKNOWN")
        self.assertIsNone(tokens["cash"])
        self.assertIsNone(tokens["current"])
        self.assertIsNone(tokens["next"])


class TestMessageParsing(unittest.TestCase):

    def setUp(self):
        self.bridge = TickBridge()

    def test_parse_ticks_message(self):
        msg = json.dumps({
            "type": "ticks",
            "count": 2,
            "data": [
                {"token": 100, "ltp_r": 2850.50, "ts": "2026-10-01 09:20:00.000",
                 "gen": 1, "mode": 2, "oi": 50000,
                 "info": {"type": "future", "month": "current", "sym": "RELIANCE"}},
                {"token": 200, "ltp_r": 2870.25, "ts": "2026-10-01 09:20:00.050",
                 "gen": 1, "mode": 2, "oi": 30000,
                 "info": {"type": "future", "month": "next", "sym": "RELIANCE"}},
            ],
        })
        self.bridge._on_message(msg)
        self.assertEqual(self.bridge.tick_count, 2)
        self.assertAlmostEqual(self.bridge.get_tick(100).ltp, 2850.50)
        self.assertAlmostEqual(self.bridge.get_tick(200).ltp, 2870.25)
        self.assertEqual(self.bridge.get_tick(100).sym, "RELIANCE")
        self.assertEqual(self.bridge.get_tick(100).fut_month, "current")
        self.assertEqual(self.bridge.get_tick(200).fut_month, "next")
        self.assertEqual(self.bridge.get_tick(100).oi, 50000)

    def test_parse_metadata_message(self):
        msg = json.dumps({
            "type": "metadata",
            "tokens": {
                "100": {"type": "cash", "sym": "RELIANCE", "tsym": "RELIANCE-EQ", "lot": 500},
                "200": {"type": "future", "month": "current", "sym": "RELIANCE",
                         "tsym": "RELIANCE28OCT26FUT", "lot": 500},
            },
            "stocks": [{"sym": "RELIANCE", "lot": 500}],
        })
        self.bridge._on_message(msg)
        self.assertEqual(self.bridge.token_count, 2)
        self.assertEqual(len(self.bridge.stocks), 1)

    def test_parse_health_message(self):
        msg = json.dumps({
            "type": "health",
            "state": "HEALTHY",
            "generation": 3,
            "tick_count": 50000,
        })
        self.bridge._on_message(msg)
        self.assertEqual(self.bridge._health["state"], "HEALTHY")
        self.assertEqual(self.bridge._health["generation"], 3)

    def test_invalid_json_no_crash(self):
        self.bridge._on_message("not json{{{")
        self.assertEqual(self.bridge.tick_count, 0)

    def test_unknown_type_ignored(self):
        self.bridge._on_message(json.dumps({"type": "unknown_type"}))
        self.assertEqual(self.bridge.tick_count, 0)

    def test_empty_ticks_batch(self):
        self.bridge._on_message(json.dumps({"type": "ticks", "count": 0, "data": []}))
        self.assertEqual(self.bridge.tick_count, 0)

    def test_tick_without_token_skipped(self):
        msg = json.dumps({
            "type": "ticks",
            "count": 1,
            "data": [{"ltp_r": 100.0}],
        })
        self.bridge._on_message(msg)
        self.assertEqual(self.bridge.tick_count, 0)

    def test_full_ohlc_fields_parsed_in_rupees(self):
        msg = json.dumps({
            "type": "ticks",
            "count": 1,
            "data": [{
                "token": 100, "ltp_r": 2850.0, "ts": "2026-10-01 09:20:00.000",
                "gen": 2, "mode": 2,
                "open": 284000, "high": 286500, "low": 283000, "close": 284500,
                "volume": 1250000, "ltq": 500,
                "oi": 2500000,
                "info": {"type": "future", "month": "current", "sym": "RELIANCE"},
            }],
        })
        self.bridge._on_message(msg)
        tick = self.bridge.get_tick(100)
        self.assertAlmostEqual(tick.open, 2840.0)
        self.assertAlmostEqual(tick.high, 2865.0)
        self.assertAlmostEqual(tick.low, 2830.0)
        self.assertAlmostEqual(tick.close, 2845.0)
        self.assertEqual(tick.volume, 1250000)
        self.assertEqual(tick.ltq, 500)
        self.assertEqual(tick.oi, 2500000)
        self.assertEqual(tick.gen, 2)


class TestFreshnessTracking(unittest.TestCase):

    def setUp(self):
        self.bridge = TickBridge()

    def test_tick_age_very_recent(self):
        self.bridge.inject_tick(100, 100.0)
        age = self.bridge.tick_age_ms(100)
        self.assertIsNotNone(age)
        self.assertLess(age, 100)

    def test_tick_age_missing_token(self):
        self.assertIsNone(self.bridge.tick_age_ms(999))

    def test_fresh_tokens_all_fresh(self):
        self.bridge.inject_tick(1, 10.0)
        self.bridge.inject_tick(2, 20.0)
        self.bridge.inject_tick(3, 30.0)
        fresh = self.bridge.fresh_tokens(max_age_ms=500)
        self.assertEqual(sorted(fresh), [1, 2, 3])

    def test_fresh_tokens_empty_bridge(self):
        fresh = self.bridge.fresh_tokens(max_age_ms=500)
        self.assertEqual(fresh, [])

    def test_fresh_tokens_custom_window(self):
        self.bridge.inject_tick(1, 10.0)
        fresh_500 = self.bridge.fresh_tokens(max_age_ms=500)
        fresh_1 = self.bridge.fresh_tokens(max_age_ms=1)
        self.assertIn(1, fresh_500)


class TestClearAndReset(unittest.TestCase):

    def test_clear(self):
        bridge = TickBridge()
        bridge.inject_tick(1, 10.0)
        bridge.inject_tick(2, 20.0)
        self.assertEqual(bridge.tick_count, 2)
        bridge.clear()
        self.assertEqual(bridge.tick_count, 0)
        self.assertIsNone(bridge.get_tick(1))
        self.assertIsNone(bridge.get_tick(2))
        self.assertEqual(bridge.fresh_tokens(), [])


class TestThreadSafety(unittest.TestCase):

    def test_concurrent_inject_and_read(self):
        bridge = TickBridge()
        errors = []

        def writer():
            try:
                for i in range(500):
                    bridge.inject_tick(1, float(i))
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(500):
                    bridge.get_tick(1)
                    bridge.get_all_ticks()
                    bridge.fresh_tokens()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        self.assertEqual(errors, [])


class TestRealTickDataReplay(unittest.TestCase):

    def test_replay_csv_ticks(self):
        import csv
        csv_path = r"C:\Users\Ankit\Desktop\RS FOLDER\rollover-react\market_data_server\tick_data\ticks_20260929.csv"
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except FileNotFoundError:
            self.skipTest("tick_data CSV not found")

        if not rows:
            self.skipTest("tick_data CSV is empty")

        bridge = TickBridge()
        for row in rows[:100]:
            token = int(row["token"])
            ltp = float(row["ltp"]) / 100.0
            bridge.inject_tick(
                token, ltp,
                ts=row.get("timestamp_ist", ""),
                info={"token": token},
            )

        self.assertEqual(bridge.tick_count, min(100, len(rows)))
        unique_tokens = set(int(r["token"]) for r in rows[:100])
        for tok in unique_tokens:
            self.assertIsNotNone(bridge.get_tick(tok))


class TestIntegrationConfigWithBridge(unittest.TestCase):

    def test_all_19_stocks_resolvable(self):
        bridge = TickBridge()
        tokens = {}
        tok_id = 1
        for sym in STOCK_CONFIG:
            tokens[str(tok_id)] = {"type": "cash", "sym": sym, "tsym": f"{sym}-EQ", "lot": STOCK_CONFIG[sym]["lot"]}
            tok_id += 1
            tokens[str(tok_id)] = {"type": "future", "month": "current", "sym": sym,
                                    "tsym": f"{sym}FUT", "lot": STOCK_CONFIG[sym]["lot"]}
            tok_id += 1
            tokens[str(tok_id)] = {"type": "future", "month": "next", "sym": sym,
                                    "tsym": f"{sym}FUT", "lot": STOCK_CONFIG[sym]["lot"]}
            tok_id += 1

        bridge.inject_metadata(tokens=tokens, stocks=[])
        self.assertEqual(bridge.token_count, 57)

        for sym in STOCK_CONFIG:
            result = bridge.get_tokens_for_stock(sym)
            self.assertIsNotNone(result["cash"], f"{sym} cash token missing")
            self.assertIsNotNone(result["current"], f"{sym} current fut token missing")
            self.assertIsNotNone(result["next"], f"{sym} next fut token missing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
