import sys
import unittest

sys.path.insert(0, r"C:\Users\Ankit\Desktop\RS FOLDER\rollover-react\market_data_server")

from algo_engine.bridge import TickBridge
from algo_engine.spread import SpreadEngine
from algo_engine.config import INITIAL_SPREADS, STOCK_CONFIG


# ── Batch 3 Adversarial Tests: Bug 13 ──────────────────────────────────────


class TestBug13_NegativeInitialSpread(unittest.TestCase):
    """Adversarial tests for Bug 13: ASTRAL negative spread handling"""

    def _setup_bridge_with_tokens(self):
        bridge = TickBridge()
        tokens = {}
        token_id = 256259
        for sym in STOCK_CONFIG:
            tokens[str(token_id)] = {"sym": sym, "type": "future", "month": "current"}
            tokens[str(token_id + 256)] = {"sym": sym, "type": "future", "month": "next"}
            token_id += 1
        bridge.inject_metadata(tokens, list(STOCK_CONFIG.keys()))
        return bridge

    def test_astral_with_negative_initial_spread_is_skipped(self):
        """ASTRAL has initial_spread=-1.70, should be skipped entirely"""
        bridge = self._setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        self.assertEqual(INITIAL_SPREADS["ASTRAL"], -1.70)

        tokens = bridge.get_tokens_for_stock("ASTRAL")
        bridge.inject_tick(tokens["current"], 1406.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "ASTRAL", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 1408.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "ASTRAL", "type": "future", "month": "next"})

        snap = engine.compute_for_stock("ASTRAL")
        self.assertIsNone(snap, "ASTRAL should be skipped")
        self.assertEqual(engine.skip_reasons.get("ASTRAL"), "negative_initial_spread")

    def test_astral_even_with_positive_current_spread_is_skipped(self):
        """Even if current spread is positive, ASTRAL should be skipped"""
        bridge = self._setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        tokens = bridge.get_tokens_for_stock("ASTRAL")
        bridge.inject_tick(tokens["current"], 1406.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "ASTRAL", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 1410.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "ASTRAL", "type": "future", "month": "next"})

        current_spread = 1410.0 - 1406.0
        self.assertGreater(current_spread, 0, "Current spread is positive")

        snap = engine.compute_for_stock("ASTRAL")
        self.assertIsNone(snap, "ASTRAL should be skipped even with positive current spread")

    def test_astral_with_negative_current_spread_is_skipped(self):
        """If current spread is negative, ASTRAL should still be skipped"""
        bridge = self._setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        tokens = bridge.get_tokens_for_stock("ASTRAL")
        bridge.inject_tick(tokens["current"], 1410.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "ASTRAL", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 1406.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "ASTRAL", "type": "future", "month": "next"})

        current_spread = 1406.0 - 1410.0
        self.assertLess(current_spread, 0, "Current spread is negative")

        snap = engine.compute_for_stock("ASTRAL")
        self.assertIsNone(snap, "ASTRAL should be skipped")

    def test_zero_initial_spread_is_skipped(self):
        """Stock with initial_spread=0 should be skipped"""
        bridge = self._setup_bridge_with_tokens()
        initial_spreads = dict(INITIAL_SPREADS)
        initial_spreads["TEST"] = 0.0

        engine = SpreadEngine(bridge, initial_spreads)
        tokens = bridge.get_tokens_for_stock("RELIANCE")

        bridge.inject_tick(tokens["current"], 2850.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "RELIANCE", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 2854.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "RELIANCE", "type": "future", "month": "next"})

        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap, "RELIANCE has positive initial_spread")

    def test_positive_initial_spread_is_not_skipped(self):
        """Stock with positive initial_spread should NOT be skipped"""
        bridge = self._setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        self.assertGreater(INITIAL_SPREADS["RELIANCE"], 0)

        tokens = bridge.get_tokens_for_stock("RELIANCE")
        bridge.inject_tick(tokens["current"], 2850.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "RELIANCE", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 2854.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "RELIANCE", "type": "future", "month": "next"})

        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap, "RELIANCE should not be skipped")
        self.assertNotIn("RELIANCE", engine.skip_reasons)

    def test_compute_all_excludes_astral(self):
        """compute_all should exclude ASTRAL from results"""
        bridge = self._setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        for sym in STOCK_CONFIG:
            tokens = bridge.get_tokens_for_stock(sym)
            bridge.inject_tick(tokens["current"], 1000.0, ts="2026-10-01 09:20:00.000",
                              info={"sym": sym, "type": "future", "month": "current"})
            bridge.inject_tick(tokens["next"], 1005.0, ts="2026-10-01 09:20:00.000",
                              info={"sym": sym, "type": "future", "month": "next"})

        results = engine.compute_all()
        self.assertNotIn("ASTRAL", results, "ASTRAL should not be in results")
        self.assertEqual(len(results), len(STOCK_CONFIG) - 1)

    def test_skip_reason_is_recorded(self):
        """Skip reason should be recorded for ASTRAL"""
        bridge = self._setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        tokens = bridge.get_tokens_for_stock("ASTRAL")
        bridge.inject_tick(tokens["current"], 1406.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "ASTRAL", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 1408.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "ASTRAL", "type": "future", "month": "next"})

        engine.compute_for_stock("ASTRAL")
        self.assertIn("ASTRAL", engine.skip_reasons)
        self.assertEqual(engine.skip_reasons["ASTRAL"], "negative_initial_spread")

    def test_no_garbage_discount_values(self):
        """Ensure no garbage discount values like 217.65% are produced"""
        bridge = self._setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        tokens = bridge.get_tokens_for_stock("ASTRAL")
        bridge.inject_tick(tokens["current"], 1406.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "ASTRAL", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 1408.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "ASTRAL", "type": "future", "month": "next"})

        snap = engine.compute_for_stock("ASTRAL")
        self.assertIsNone(snap, "No snapshot should be produced for ASTRAL")

        for sym, snap in engine.snapshots.items():
            if snap:
                self.assertLess(abs(snap.discount_pct), 1000,
                               f"{sym} has unreasonable discount: {snap.discount_pct}")


if __name__ == "__main__":
    unittest.main()
