import sys
import json
import time
import unittest
import threading
from datetime import datetime, timedelta

sys.path.insert(0, r"C:\Users\Ankit\Desktop\RS FOLDER\rollover-react\market_data_server")

from algo_engine.config import (
    STOCK_CONFIG, INITIAL_SPREADS, THRESHOLDS,
    SPREAD_FRESHNESS_SECONDS, IST,
)
from algo_engine.bridge import TickBridge, Tick
from algo_engine.spread import SpreadEngine, SpreadSnapshot


def _now_ist_str(offset_seconds=0):
    dt = datetime.now(IST) + timedelta(seconds=offset_seconds)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _setup_bridge_with_tokens():
    bridge = TickBridge()
    tokens = {}
    tok_id = 1
    for sym in STOCK_CONFIG:
        tokens[str(tok_id)] = {"type": "cash", "sym": sym, "tsym": f"{sym}-EQ",
                                "lot": STOCK_CONFIG[sym]["lot"]}
        tok_id += 1
        tokens[str(tok_id)] = {"type": "future", "month": "current", "sym": sym,
                                "tsym": f"{sym}FUT", "lot": STOCK_CONFIG[sym]["lot"]}
        tok_id += 1
        tokens[str(tok_id)] = {"type": "future", "month": "next", "sym": sym,
                                "tsym": f"{sym}FUT", "lot": STOCK_CONFIG[sym]["lot"]}
        tok_id += 1
    bridge.inject_metadata(tokens=tokens, stocks=[])
    return bridge


# ── Step 4: Spread Engine Tests ────────────────────────────────────────────


class TestSpreadEngineInit(unittest.TestCase):

    def test_initial_state(self):
        bridge = TickBridge()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        self.assertEqual(engine.cycle_count, 0)
        self.assertEqual(engine.snapshots, {})
        self.assertEqual(engine.skip_reasons, {})

    def test_get_snapshot_missing(self):
        bridge = TickBridge()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        self.assertIsNone(engine.get_snapshot("RELIANCE"))


class TestSpreadComputationAllStocks(unittest.TestCase):

    def setUp(self):
        self.bridge = _setup_bridge_with_tokens()
        self.engine = SpreadEngine(self.bridge, INITIAL_SPREADS)

    def _inject_ticks(self, sym, current_ltp, next_ltp, ts_offset=0):
        tokens = self.bridge.get_tokens_for_stock(sym)
        ts = _now_ist_str(ts_offset)
        self.bridge.inject_tick(tokens["current"], current_ltp, ts=ts,
                                info={"sym": sym, "type": "future", "month": "current"})
        self.bridge.inject_tick(tokens["next"], next_ltp, ts=ts,
                                info={"sym": sym, "type": "future", "month": "next"})

    def test_all_19_stocks_contango(self):
        test_data = {
            "RELIANCE": (2850.0, 2854.0),
            "ADANIPORTS": (1796.0, 1805.0),
            "AMBUJACEM": (389.0, 391.0),
            "ASTRAL": (1406.0, 1408.0),
            "GRASIM": (3205.0, 3220.0),
            "HCLTECH": (1247.0, 1252.0),
            "HDFCBANK": (736.0, 738.0),
            "INFOSYS": (1019.0, 1022.0),
            "JSWSTEEL": (1291.0, 1294.0),
            "MARUTI": (12204.0, 12240.0),
            "TCS": (2096.0, 2102.0),
            "TATASTEEL": (190.0, 191.0),
            "BAJFINANCE": (993.0, 997.0),
            "SBIN": (995.0, 998.0),
            "LT": (3887.0, 3900.0),
            "HAL": (4861.0, 4875.0),
            "BANDHANBANK": (186.0, 187.0),
            "ADANIENT": (2964.0, 2978.0),
            "INDUSINDBK": (931.0, 933.0),
        }

        for sym, (cur, nxt) in test_data.items():
            self._inject_ticks(sym, cur, nxt)

        results = self.engine.compute_all()

        self.assertEqual(len(results), 18, "ASTRAL should be skipped (negative initial_spread)")
        for sym in STOCK_CONFIG:
            if sym == "ASTRAL":
                self.assertNotIn(sym, results, "ASTRAL should be skipped")
                continue
            self.assertIn(sym, results, f"{sym} missing from results")
            snap = results[sym]
            self.assertEqual(snap.stock, sym)
            self.assertTrue(snap.is_contango)
            self.assertGreater(snap.spread, 0)

    def test_reliance_spread_and_discount(self):
        self._inject_ticks("RELIANCE", 2850.0, 2854.0)
        snap = self.engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 4.0)
        expected_discount = (6.20 - 4.0) / 6.20 * 100
        self.assertAlmostEqual(snap.discount_pct, expected_discount, places=2)
        self.assertTrue(snap.is_contango)
        self.assertEqual(snap.initial_spread, 6.20)

    def test_adaniports_spread_and_discount(self):
        self._inject_ticks("ADANIPORTS", 1796.0, 1805.0)
        snap = self.engine.compute_for_stock("ADANIPORTS")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 9.0)
        expected_discount = (14.20 - 9.0) / 14.20 * 100
        self.assertAlmostEqual(snap.discount_pct, expected_discount, places=2)

    def test_ambujacem_spread_and_discount(self):
        self._inject_ticks("AMBUJACEM", 389.0, 391.0)
        snap = self.engine.compute_for_stock("AMBUJACEM")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 2.0)
        expected_discount = (2.50 - 2.0) / 2.50 * 100
        self.assertAlmostEqual(snap.discount_pct, expected_discount, places=2)

    def test_grasim_spread_and_discount(self):
        self._inject_ticks("GRASIM", 3205.0, 3220.0)
        snap = self.engine.compute_for_stock("GRASIM")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 15.0)
        expected_discount = (23.90 - 15.0) / 23.90 * 100
        self.assertAlmostEqual(snap.discount_pct, expected_discount, places=2)

    def test_infosys_spread_and_discount(self):
        self._inject_ticks("INFOSYS", 1019.0, 1022.0)
        snap = self.engine.compute_for_stock("INFOSYS")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 3.0)
        expected_discount = (5.30 - 3.0) / 5.30 * 100
        self.assertAlmostEqual(snap.discount_pct, expected_discount, places=2)

    def test_jswsteel_spread_and_discount(self):
        self._inject_ticks("JSWSTEEL", 1291.0, 1294.0)
        snap = self.engine.compute_for_stock("JSWSTEEL")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 3.0)
        expected_discount = (5.00 - 3.0) / 5.00 * 100
        self.assertAlmostEqual(snap.discount_pct, expected_discount, places=2)

    def test_maruti_spread_and_discount(self):
        self._inject_ticks("MARUTI", 12204.0, 12240.0)
        snap = self.engine.compute_for_stock("MARUTI")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 36.0)
        expected_discount = (54.00 - 36.0) / 54.00 * 100
        self.assertAlmostEqual(snap.discount_pct, expected_discount, places=2)

    def test_tcs_spread_and_discount(self):
        self._inject_ticks("TCS", 2096.0, 2102.0)
        snap = self.engine.compute_for_stock("TCS")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 6.0)
        expected_discount = (10.10 - 6.0) / 10.10 * 100
        self.assertAlmostEqual(snap.discount_pct, expected_discount, places=2)

    def test_tatasteel_spread_and_discount(self):
        self._inject_ticks("TATASTEEL", 190.0, 191.0)
        snap = self.engine.compute_for_stock("TATASTEEL")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 1.0)
        expected_discount = (1.11 - 1.0) / 1.11 * 100
        self.assertAlmostEqual(snap.discount_pct, expected_discount, places=2)

    def test_hdfcbank_spread_and_discount(self):
        self._inject_ticks("HDFCBANK", 736.0, 738.0)
        snap = self.engine.compute_for_stock("HDFCBANK")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 2.0)
        expected_discount = (3.55 - 2.0) / 3.55 * 100
        self.assertAlmostEqual(snap.discount_pct, expected_discount, places=2)

    def test_sbin_spread_and_discount(self):
        self._inject_ticks("SBIN", 995.0, 998.0)
        snap = self.engine.compute_for_stock("SBIN")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 3.0)
        expected_discount = (4.70 - 3.0) / 4.70 * 100
        self.assertAlmostEqual(snap.discount_pct, expected_discount, places=2)

    def test_lt_spread_and_discount(self):
        self._inject_ticks("LT", 3887.0, 3900.0)
        snap = self.engine.compute_for_stock("LT")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 13.0)
        expected_discount = (22.20 - 13.0) / 22.20 * 100
        self.assertAlmostEqual(snap.discount_pct, expected_discount, places=2)

    def test_hal_spread_and_discount(self):
        self._inject_ticks("HAL", 4861.0, 4875.0)
        snap = self.engine.compute_for_stock("HAL")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 14.0)
        expected_discount = (27.10 - 14.0) / 27.10 * 100
        self.assertAlmostEqual(snap.discount_pct, expected_discount, places=2)

    def test_hcltech_spread_and_discount(self):
        self._inject_ticks("HCLTECH", 1247.0, 1252.0)
        snap = self.engine.compute_for_stock("HCLTECH")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 5.0)
        expected_discount = (7.50 - 5.0) / 7.50 * 100
        self.assertAlmostEqual(snap.discount_pct, expected_discount, places=2)

    def test_bajfinance_spread_and_discount(self):
        self._inject_ticks("BAJFINANCE", 993.0, 997.0)
        snap = self.engine.compute_for_stock("BAJFINANCE")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 4.0)
        expected_discount = (6.40 - 4.0) / 6.40 * 100
        self.assertAlmostEqual(snap.discount_pct, expected_discount, places=2)

    def test_bandhanbank_spread_and_discount(self):
        self._inject_ticks("BANDHANBANK", 186.0, 187.0)
        snap = self.engine.compute_for_stock("BANDHANBANK")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 1.0)
        expected_discount = (1.19 - 1.0) / 1.19 * 100
        self.assertAlmostEqual(snap.discount_pct, expected_discount, places=2)

    def test_adanient_spread_and_discount(self):
        self._inject_ticks("ADANIENT", 2964.0, 2978.0)
        snap = self.engine.compute_for_stock("ADANIENT")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 14.0)
        expected_discount = (23.90 - 14.0) / 23.90 * 100
        self.assertAlmostEqual(snap.discount_pct, expected_discount, places=2)

    def test_indusindbk_spread_and_discount(self):
        self._inject_ticks("INDUSINDBK", 931.0, 933.0)
        snap = self.engine.compute_for_stock("INDUSINDBK")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 2.0)
        expected_discount = (3.50 - 2.0) / 3.50 * 100
        self.assertAlmostEqual(snap.discount_pct, expected_discount, places=2)

    def test_astral_negative_initial_spread_skipped(self):
        self._inject_ticks("ASTRAL", 1406.0, 1408.0)
        snap = self.engine.compute_for_stock("ASTRAL")
        self.assertIsNone(snap, "ASTRAL with negative initial_spread should be skipped")
        skip_reasons = self.engine.skip_reasons
        self.assertEqual(skip_reasons.get("ASTRAL"), "negative_initial_spread")


class TestBackwardation(unittest.TestCase):

    def setUp(self):
        self.bridge = _setup_bridge_with_tokens()
        self.engine = SpreadEngine(self.bridge, INITIAL_SPREADS)

    def _inject_ticks(self, sym, current_ltp, next_ltp):
        tokens = self.bridge.get_tokens_for_stock(sym)
        ts = _now_ist_str()
        self.bridge.inject_tick(tokens["current"], current_ltp, ts=ts,
                                info={"sym": sym, "type": "future", "month": "current"})
        self.bridge.inject_tick(tokens["next"], next_ltp, ts=ts,
                                info={"sym": sym, "type": "future", "month": "next"})

    def test_backwardation_negative_spread(self):
        self._inject_ticks("RELIANCE", 2860.0, 2858.0)
        snap = self.engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap)
        self.assertFalse(snap.is_contango)
        self.assertAlmostEqual(snap.spread, -2.0)
        self.assertEqual(snap.discount_pct, 0.0)

    def test_backwardation_zero_spread(self):
        self._inject_ticks("TCS", 2100.0, 2100.0)
        snap = self.engine.compute_for_stock("TCS")
        self.assertIsNotNone(snap)
        self.assertFalse(snap.is_contango)
        self.assertAlmostEqual(snap.spread, 0.0)
        self.assertEqual(snap.discount_pct, 0.0)

    def test_backwardation_all_stocks(self):
        for sym in STOCK_CONFIG:
            tokens = self.bridge.get_tokens_for_stock(sym)
            ts = _now_ist_str()
            self.bridge.inject_tick(tokens["current"], 1000.0, ts=ts,
                                    info={"sym": sym, "type": "future", "month": "current"})
            self.bridge.inject_tick(tokens["next"], 999.0, ts=ts,
                                    info={"sym": sym, "type": "future", "month": "next"})

        results = self.engine.compute_all()
        for sym in STOCK_CONFIG:
            if sym == "ASTRAL":
                self.assertNotIn(sym, results, "ASTRAL should be skipped")
                continue
            self.assertIn(sym, results)
            self.assertFalse(results[sym].is_contango)


class TestFreshnessCheck(unittest.TestCase):

    def setUp(self):
        self.bridge = _setup_bridge_with_tokens()
        self.engine = SpreadEngine(self.bridge, INITIAL_SPREADS)

    def test_stale_current_tick_skipped(self):
        import time
        tokens = self.bridge.get_tokens_for_stock("RELIANCE")
        stale_mono = time.monotonic_ns() - int(120 * 1e9)
        self.bridge.inject_tick(tokens["current"], 2850.0, ts="2026-10-01 09:20:00.000",
                                info={"sym": "RELIANCE", "type": "future", "month": "current"},
                                recv_mono_ns=stale_mono)
        self.bridge.inject_tick(tokens["next"], 2854.0, ts="2026-10-01 09:20:01.000",
                                info={"sym": "RELIANCE", "type": "future", "month": "next"})
        snap = self.engine.compute_for_stock("RELIANCE")
        self.assertIsNone(snap)
        self.assertEqual(self.engine.skip_reasons["RELIANCE"], "stale_current")

    def test_stale_next_tick_skipped(self):
        import time
        tokens = self.bridge.get_tokens_for_stock("TCS")
        stale_mono = time.monotonic_ns() - int(120 * 1e9)
        self.bridge.inject_tick(tokens["current"], 2096.0, ts="2026-10-01 09:20:01.000",
                                info={"sym": "TCS", "type": "future", "month": "current"})
        self.bridge.inject_tick(tokens["next"], 2102.0, ts="2026-10-01 09:20:00.000",
                                info={"sym": "TCS", "type": "future", "month": "next"},
                                recv_mono_ns=stale_mono)
        snap = self.engine.compute_for_stock("TCS")
        self.assertIsNone(snap)
        self.assertEqual(self.engine.skip_reasons["TCS"], "stale_next")

    def test_fresh_tick_within_60s_passes(self):
        tokens = self.bridge.get_tokens_for_stock("SBIN")
        ts = _now_ist_str(-30)
        self.bridge.inject_tick(tokens["current"], 995.0, ts=ts,
                                info={"sym": "SBIN", "type": "future", "month": "current"})
        self.bridge.inject_tick(tokens["next"], 998.0, ts=ts,
                                info={"sym": "SBIN", "type": "future", "month": "next"})
        snap = self.engine.compute_for_stock("SBIN")
        self.assertIsNotNone(snap)
        self.assertTrue(snap.is_contango)


class TestMissingData(unittest.TestCase):

    def setUp(self):
        self.bridge = _setup_bridge_with_tokens()
        self.engine = SpreadEngine(self.bridge, INITIAL_SPREADS)

    def test_no_ticks_at_all(self):
        snap = self.engine.compute_for_stock("RELIANCE")
        self.assertIsNone(snap)
        self.assertEqual(self.engine.skip_reasons["RELIANCE"], "no_ticks")

    def test_only_current_tick(self):
        tokens = self.bridge.get_tokens_for_stock("RELIANCE")
        self.bridge.inject_tick(tokens["current"], 2850.0, ts=_now_ist_str(),
                                info={"sym": "RELIANCE", "type": "future", "month": "current"})
        snap = self.engine.compute_for_stock("RELIANCE")
        self.assertIsNone(snap)
        self.assertEqual(self.engine.skip_reasons["RELIANCE"], "no_ticks")

    def test_only_next_tick(self):
        tokens = self.bridge.get_tokens_for_stock("TCS")
        self.bridge.inject_tick(tokens["next"], 2102.0, ts=_now_ist_str(),
                                info={"sym": "TCS", "type": "future", "month": "next"})
        snap = self.engine.compute_for_stock("TCS")
        self.assertIsNone(snap)
        self.assertEqual(self.engine.skip_reasons["TCS"], "no_ticks")

    def test_no_initial_spread(self):
        bridge = _setup_bridge_with_tokens()
        spreads = dict(INITIAL_SPREADS)
        spreads["RELIANCE"] = None
        engine = SpreadEngine(bridge, spreads)
        tokens = bridge.get_tokens_for_stock("RELIANCE")
        ts = _now_ist_str()
        bridge.inject_tick(tokens["current"], 2850.0, ts=ts,
                           info={"sym": "RELIANCE", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 2854.0, ts=ts,
                           info={"sym": "RELIANCE", "type": "future", "month": "next"})
        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNone(snap)
        self.assertEqual(engine.skip_reasons["RELIANCE"], "no_initial_spread")

    def test_unknown_stock(self):
        snap = self.engine.compute_for_stock("UNKNOWN_STOCK")
        self.assertIsNone(snap)


class TestCycleCounting(unittest.TestCase):

    def test_cycle_count_increments(self):
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        self.assertEqual(engine.cycle_count, 0)
        engine.compute_all()
        self.assertEqual(engine.cycle_count, 1)
        engine.compute_all()
        self.assertEqual(engine.cycle_count, 2)

    def test_compute_all_returns_dict(self):
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        for sym in STOCK_CONFIG:
            tokens = bridge.get_tokens_for_stock(sym)
            ts = _now_ist_str()
            bridge.inject_tick(tokens["current"], 1000.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "current"})
            bridge.inject_tick(tokens["next"], 1005.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "next"})
        results = engine.compute_all()
        self.assertEqual(len(results), 18, "ASTRAL should be skipped")


class TestSpreadSnapshotDataclass(unittest.TestCase):

    def test_snapshot_fields(self):
        snap = SpreadSnapshot(
            stock="RELIANCE",
            spread=4.0,
            discount_pct=35.48,
            initial_spread=6.20,
            current_fut_ltp=2850.0,
            next_fut_ltp=2854.0,
            timestamp="2026-10-04 10:00:00.000",
            is_contango=True,
        )
        self.assertEqual(snap.stock, "RELIANCE")
        self.assertAlmostEqual(snap.spread, 4.0)
        self.assertAlmostEqual(snap.discount_pct, 35.48)
        self.assertAlmostEqual(snap.initial_spread, 6.20)
        self.assertAlmostEqual(snap.current_fut_ltp, 2850.0)
        self.assertAlmostEqual(snap.next_fut_ltp, 2854.0)
        self.assertEqual(snap.timestamp, "2026-10-04 10:00:00.000")
        self.assertTrue(snap.is_contango)


class TestReset(unittest.TestCase):

    def test_reset_clears_all(self):
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        for sym in STOCK_CONFIG:
            tokens = bridge.get_tokens_for_stock(sym)
            ts = _now_ist_str()
            bridge.inject_tick(tokens["current"], 1000.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "current"})
            bridge.inject_tick(tokens["next"], 1005.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "next"})
        engine.compute_all()
        self.assertEqual(engine.cycle_count, 1)
        self.assertEqual(len(engine.snapshots), 18, "ASTRAL should be skipped")
        engine.reset()
        self.assertEqual(engine.cycle_count, 0)
        self.assertEqual(engine.snapshots, {})
        self.assertEqual(engine.skip_reasons, {})


class TestThreadSafety(unittest.TestCase):

    def test_concurrent_compute_and_read(self):
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        errors = []

        for sym in STOCK_CONFIG:
            tokens = bridge.get_tokens_for_stock(sym)
            ts = _now_ist_str()
            bridge.inject_tick(tokens["current"], 1000.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "current"})
            bridge.inject_tick(tokens["next"], 1005.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "next"})

        def writer():
            try:
                for _ in range(100):
                    engine.compute_all()
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    _ = engine.snapshots
                    _ = engine.skip_reasons
                    _ = engine.cycle_count
                    for sym in STOCK_CONFIG:
                        engine.get_snapshot(sym)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)
        self.assertEqual(errors, [])


class TestDiscountThresholds(unittest.TestCase):

    def setUp(self):
        self.bridge = _setup_bridge_with_tokens()
        self.engine = SpreadEngine(self.bridge, INITIAL_SPREADS)

    def test_35_pct_threshold_stocks(self):
        for sym in ["RELIANCE", "ADANIPORTS", "AMBUJACEM"]:
            self.assertEqual(STOCK_CONFIG[sym]["threshold"], 35,
                             f"{sym} should have threshold 35")

    def test_40_pct_threshold_stocks(self):
        expected_40 = [
            "ASTRAL", "GRASIM", "HCLTECH", "HDFCBANK", "INFOSYS",
            "JSWSTEEL", "MARUTI", "TCS", "TATASTEEL", "BAJFINANCE",
            "SBIN", "LT", "HAL", "BANDHANBANK", "ADANIENT", "INDUSINDBK",
        ]
        for sym in expected_40:
            self.assertEqual(STOCK_CONFIG[sym]["threshold"], 40,
                             f"{sym} should have threshold 40")

    def test_all_initial_spreads_set(self):
        for sym in STOCK_CONFIG:
            self.assertIsNotNone(INITIAL_SPREADS[sym],
                                 f"{sym} initial_spread should not be None")

    def test_all_initial_spreads_numeric(self):
        for sym, val in INITIAL_SPREADS.items():
            self.assertIsInstance(val, (int, float),
                                  f"{sym} initial_spread not numeric")


class TestEmptyTimestamp(unittest.TestCase):

    def test_empty_ts_treated_as_stale(self):
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tokens = bridge.get_tokens_for_stock("RELIANCE")
        bridge.inject_tick(tokens["current"], 2850.0, ts="",
                           info={"sym": "RELIANCE", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 2854.0, ts="",
                           info={"sym": "RELIANCE", "type": "future", "month": "next"})
        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNone(snap)


class TestIntegrationWithValidator(unittest.TestCase):

    def test_validated_ticks_flow_to_spread(self):
        from algo_engine.validator import TickValidator

        bridge = _setup_bridge_with_tokens()
        validator = TickValidator()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        tokens = bridge.get_tokens_for_stock("RELIANCE")
        ts = _now_ist_str()

        tick_c = Tick(token=tokens["current"], ltp=2850.0, ts=ts, recv_mono_ns=0,
                       info={"sym": "RELIANCE", "type": "future", "month": "current"})
        tick_n = Tick(token=tokens["next"], ltp=2854.0, ts=ts, recv_mono_ns=0,
                       info={"sym": "RELIANCE", "type": "future", "month": "next"})

        self.assertTrue(validator.process_tick(tick_c))
        self.assertTrue(validator.process_tick(tick_n))

        bridge.inject_tick(tokens["current"], 2850.0, ts=ts,
                           info={"sym": "RELIANCE", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 2854.0, ts=ts,
                           info={"sym": "RELIANCE", "type": "future", "month": "next"})

        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap)
        self.assertTrue(snap.is_contango)
        self.assertAlmostEqual(snap.spread, 4.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
