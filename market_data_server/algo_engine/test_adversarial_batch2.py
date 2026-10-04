import sys
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, r"C:\Users\Ankit\Desktop\RS FOLDER\rollover-react\market_data_server")

from algo_engine.bridge import TickBridge, Tick
from algo_engine.spread import SpreadEngine
from algo_engine.config import INITIAL_SPREADS, SPREAD_FRESHNESS_SECONDS


# ── Batch 2 Adversarial Tests: Bugs 16 & 17 ────────────────────────────────


class TestBug16_MonotonicClockFreshness(unittest.TestCase):
    """Adversarial tests for Bug 16: Wall-clock vs monotonic clock freshness"""

    def _setup_bridge_with_tokens(self):
        bridge = TickBridge()
        tokens = {
            "256259": {"sym": "RELIANCE", "type": "future", "month": "current"},
            "256515": {"sym": "RELIANCE", "type": "future", "month": "next"},
        }
        bridge.inject_metadata(tokens, ["RELIANCE"])
        return bridge

    def test_ntp_time_jump_forward_doesnt_affect_freshness(self):
        """If NTP jumps clock forward 1 hour, fresh ticks should stay fresh"""
        bridge = self._setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tokens = bridge.get_tokens_for_stock("RELIANCE")

        current_mono = time.monotonic_ns()
        bridge.inject_tick(tokens["current"], 2850.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "RELIANCE", "type": "future", "month": "current"},
                          recv_mono_ns=current_mono)
        bridge.inject_tick(tokens["next"], 2854.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "RELIANCE", "type": "future", "month": "next"},
                          recv_mono_ns=current_mono)

        with patch('algo_engine.spread.datetime') as mock_dt:
            future_time = MagicMock()
            future_time.now.return_value.strftime.return_value = "2026-10-01 10:20:00.000"
            mock_dt.now.return_value = future_time.now()

            snap = engine.compute_for_stock("RELIANCE")
            self.assertIsNotNone(snap, "Tick should be fresh even if wall-clock jumped forward")

    def test_ntp_time_jump_backward_doesnt_affect_freshness(self):
        """If NTP jumps clock backward 1 hour, fresh ticks should stay fresh"""
        bridge = self._setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tokens = bridge.get_tokens_for_stock("RELIANCE")

        current_mono = time.monotonic_ns()
        bridge.inject_tick(tokens["current"], 2850.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "RELIANCE", "type": "future", "month": "current"},
                          recv_mono_ns=current_mono)
        bridge.inject_tick(tokens["next"], 2854.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "RELIANCE", "type": "future", "month": "next"},
                          recv_mono_ns=current_mono)

        with patch('algo_engine.spread.datetime') as mock_dt:
            past_time = MagicMock()
            past_time.now.return_value.strftime.return_value = "2026-10-01 08:20:00.000"
            mock_dt.now.return_value = past_time.now()

            snap = engine.compute_for_stock("RELIANCE")
            self.assertIsNotNone(snap, "Tick should be fresh even if wall-clock jumped backward")

    def test_system_clock_change_doesnt_cause_false_stale(self):
        """If system clock is set back, fresh ticks shouldn't become stale"""
        bridge = self._setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tokens = bridge.get_tokens_for_stock("RELIANCE")

        current_mono = time.monotonic_ns()
        bridge.inject_tick(tokens["current"], 2850.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "RELIANCE", "type": "future", "month": "current"},
                          recv_mono_ns=current_mono)
        bridge.inject_tick(tokens["next"], 2854.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "RELIANCE", "type": "future", "month": "next"},
                          recv_mono_ns=current_mono)

        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap, "Fresh tick should produce snapshot regardless of wall-clock")

    def test_actually_stale_tick_by_monotonic_time(self):
        """Tick older than SPREAD_FRESHNESS_SECONDS should be stale"""
        bridge = self._setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tokens = bridge.get_tokens_for_stock("RELIANCE")

        stale_mono = time.monotonic_ns() - int((SPREAD_FRESHNESS_SECONDS + 10) * 1e9)
        bridge.inject_tick(tokens["current"], 2850.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "RELIANCE", "type": "future", "month": "current"},
                          recv_mono_ns=stale_mono)
        bridge.inject_tick(tokens["next"], 2854.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "RELIANCE", "type": "future", "month": "next"},
                          recv_mono_ns=stale_mono)

        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNone(snap, "Old tick should be stale by monotonic time")

    def test_monotonic_time_is_actually_used(self):
        """Verify that recv_mono_ns is used, not wall-clock ts"""
        bridge = self._setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tokens = bridge.get_tokens_for_stock("RELIANCE")

        recent_mono = time.monotonic_ns() - int(5 * 1e9)
        old_wall_clock = "2020-01-01 09:20:00.000"

        bridge.inject_tick(tokens["current"], 2850.0, ts=old_wall_clock,
                          info={"sym": "RELIANCE", "type": "future", "month": "current"},
                          recv_mono_ns=recent_mono)
        bridge.inject_tick(tokens["next"], 2854.0, ts=old_wall_clock,
                          info={"sym": "RELIANCE", "type": "future", "month": "next"},
                          recv_mono_ns=recent_mono)

        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap, "Should use monotonic time, not wall-clock ts")

    def test_zero_recv_mono_ns_treated_as_stale(self):
        """Tick with recv_mono_ns=0 should be stale"""
        bridge = self._setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tokens = bridge.get_tokens_for_stock("RELIANCE")

        bridge.inject_tick(tokens["current"], 2850.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "RELIANCE", "type": "future", "month": "current"},
                          recv_mono_ns=0)
        bridge.inject_tick(tokens["next"], 2854.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "RELIANCE", "type": "future", "month": "next"},
                          recv_mono_ns=0)

        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNone(snap, "Zero recv_mono_ns should be stale")

    def test_boundary_exactly_at_freshness_limit(self):
        """Tick at exactly SPREAD_FRESHNESS_SECONDS should be stale (strict less-than)"""
        bridge = self._setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tokens = bridge.get_tokens_for_stock("RELIANCE")

        boundary_mono = time.monotonic_ns() - int(SPREAD_FRESHNESS_SECONDS * 1e9)
        bridge.inject_tick(tokens["current"], 2850.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "RELIANCE", "type": "future", "month": "current"},
                          recv_mono_ns=boundary_mono)
        bridge.inject_tick(tokens["next"], 2854.0, ts="2026-10-01 09:20:00.000",
                          info={"sym": "RELIANCE", "type": "future", "month": "next"},
                          recv_mono_ns=boundary_mono)

        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNone(snap, "Tick at exactly freshness limit should be stale")


class TestBug17_MemoryLeakPrevention(unittest.TestCase):
    """Adversarial tests for Bug 17: No memory cleanup for stale tokens"""

    def test_purge_stale_removes_old_tokens(self):
        """purge_stale should remove tokens older than max_age_seconds"""
        bridge = TickBridge()

        old_mono = time.monotonic_ns() - int(600 * 1e9)
        bridge.inject_tick(100, 100.0, ts="2026-10-01 09:00:00.000", recv_mono_ns=old_mono)
        bridge.inject_tick(101, 101.0, ts="2026-10-01 09:00:00.000", recv_mono_ns=old_mono)

        purged = bridge.purge_stale(max_age_seconds=300)
        self.assertEqual(purged, 2, "Should purge 2 old tokens")
        self.assertIsNone(bridge.get_tick(100))
        self.assertIsNone(bridge.get_tick(101))

    def test_purge_stale_keeps_fresh_tokens(self):
        """purge_stale should keep tokens newer than max_age_seconds"""
        bridge = TickBridge()

        fresh_mono = time.monotonic_ns() - int(100 * 1e9)
        bridge.inject_tick(100, 100.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=fresh_mono)
        bridge.inject_tick(101, 101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=fresh_mono)

        purged = bridge.purge_stale(max_age_seconds=300)
        self.assertEqual(purged, 0, "Should purge 0 fresh tokens")
        self.assertIsNotNone(bridge.get_tick(100))
        self.assertIsNotNone(bridge.get_tick(101))

    def test_purge_stale_mixed_ages(self):
        """purge_stale should only remove old tokens, keep fresh ones"""
        bridge = TickBridge()

        old_mono = time.monotonic_ns() - int(600 * 1e9)
        fresh_mono = time.monotonic_ns() - int(100 * 1e9)

        bridge.inject_tick(100, 100.0, ts="2026-10-01 09:00:00.000", recv_mono_ns=old_mono)
        bridge.inject_tick(101, 101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=fresh_mono)
        bridge.inject_tick(102, 102.0, ts="2026-10-01 09:00:00.000", recv_mono_ns=old_mono)

        purged = bridge.purge_stale(max_age_seconds=300)
        self.assertEqual(purged, 2, "Should purge 2 old tokens")
        self.assertIsNone(bridge.get_tick(100))
        self.assertIsNotNone(bridge.get_tick(101))
        self.assertIsNone(bridge.get_tick(102))

    def test_purge_stale_returns_correct_count(self):
        """purge_stale should return the number of tokens purged"""
        bridge = TickBridge()

        old_mono = time.monotonic_ns() - int(600 * 1e9)
        for i in range(10):
            bridge.inject_tick(100 + i, 100.0 + i, ts="2026-10-01 09:00:00.000",
                              recv_mono_ns=old_mono)

        purged = bridge.purge_stale(max_age_seconds=300)
        self.assertEqual(purged, 10, "Should purge exactly 10 tokens")

    def test_purge_stale_empty_bridge(self):
        """purge_stale on empty bridge should return 0"""
        bridge = TickBridge()
        purged = bridge.purge_stale(max_age_seconds=300)
        self.assertEqual(purged, 0, "Empty bridge should purge 0 tokens")

    def test_purge_stale_boundary_exact_age(self):
        """Token at exactly max_age_seconds should NOT be purged (strict less-than)"""
        bridge = TickBridge()

        boundary_mono = time.monotonic_ns() - int(300 * 1e9)
        bridge.inject_tick(100, 100.0, ts="2026-10-01 09:00:00.000", recv_mono_ns=boundary_mono)

        purged = bridge.purge_stale(max_age_seconds=300)
        self.assertEqual(purged, 0, "Token at exactly max_age should NOT be purged")
        self.assertIsNotNone(bridge.get_tick(100), "Token at boundary should be kept")

    def test_purge_stale_prevents_memory_leak(self):
        """Simulate memory leak scenario: many old tokens should be purgable"""
        bridge = TickBridge()

        old_mono = time.monotonic_ns() - int(600 * 1e9)
        for i in range(1000):
            bridge.inject_tick(10000 + i, 100.0, ts="2026-10-01 09:00:00.000",
                              recv_mono_ns=old_mono)

        purged = bridge.purge_stale(max_age_seconds=300)
        self.assertEqual(purged, 1000, "Should purge all 1000 old tokens")

        for i in range(1000):
            self.assertIsNone(bridge.get_tick(10000 + i))

    def test_purge_stale_custom_max_age(self):
        """purge_stale should respect custom max_age_seconds parameter"""
        bridge = TickBridge()

        mono_100s = time.monotonic_ns() - int(100 * 1e9)
        mono_200s = time.monotonic_ns() - int(200 * 1e9)
        mono_300s = time.monotonic_ns() - int(300 * 1e9)

        bridge.inject_tick(100, 100.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=mono_100s)
        bridge.inject_tick(101, 101.0, ts="2026-10-01 09:18:00.000", recv_mono_ns=mono_200s)
        bridge.inject_tick(102, 102.0, ts="2026-10-01 09:16:00.000", recv_mono_ns=mono_300s)

        purged_150 = bridge.purge_stale(max_age_seconds=150)
        self.assertEqual(purged_150, 2, "Should purge tokens older than 150s")
        self.assertIsNotNone(bridge.get_tick(100))
        self.assertIsNone(bridge.get_tick(101))
        self.assertIsNone(bridge.get_tick(102))

    def test_purge_stale_idempotent(self):
        """Calling purge_stale twice should not double-count"""
        bridge = TickBridge()

        old_mono = time.monotonic_ns() - int(600 * 1e9)
        bridge.inject_tick(100, 100.0, ts="2026-10-01 09:00:00.000", recv_mono_ns=old_mono)

        purged1 = bridge.purge_stale(max_age_seconds=300)
        self.assertEqual(purged1, 1)

        purged2 = bridge.purge_stale(max_age_seconds=300)
        self.assertEqual(purged2, 0, "Second purge should find nothing to purge")


class TestBug17_ValidatorPurgeUnknownTokens(unittest.TestCase):
    """Adversarial tests for Bug 17: Validator purge_unknown_tokens"""

    def test_purge_unknown_tokens_removes_them(self):
        """purge_unknown_tokens should remove tokens not in known set"""
        from algo_engine.validator import TickValidator

        validator = TickValidator()
        tick1 = Tick(token=100, ltp=100.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        tick2 = Tick(token=101, ltp=101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        tick3 = Tick(token=102, ltp=102.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)

        validator.check(tick1)
        validator.check(tick2)
        validator.check(tick3)

        purged = validator.purge_unknown_tokens(known_tokens={100, 101})
        self.assertEqual(purged, 1, "Should purge 1 unknown token")
        self.assertIsNotNone(validator.get_prev_ts(100))
        self.assertIsNotNone(validator.get_prev_ts(101))
        self.assertIsNone(validator.get_prev_ts(102))

    def test_purge_unknown_tokens_keeps_known(self):
        """purge_unknown_tokens should keep all known tokens"""
        from algo_engine.validator import TickValidator

        validator = TickValidator()
        tick1 = Tick(token=100, ltp=100.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        tick2 = Tick(token=101, ltp=101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)

        validator.check(tick1)
        validator.check(tick2)

        purged = validator.purge_unknown_tokens(known_tokens={100, 101, 102})
        self.assertEqual(purged, 0, "Should purge 0 known tokens")
        self.assertIsNotNone(validator.get_prev_ts(100))
        self.assertIsNotNone(validator.get_prev_ts(101))

    def test_purge_unknown_tokens_empty_validator(self):
        """purge_unknown_tokens on empty validator should return 0"""
        from algo_engine.validator import TickValidator

        validator = TickValidator()
        purged = validator.purge_unknown_tokens(known_tokens={100, 101})
        self.assertEqual(purged, 0, "Empty validator should purge 0 tokens")

    def test_purge_unknown_tokens_empty_known_set(self):
        """purge_unknown_tokens with empty known set should purge all"""
        from algo_engine.validator import TickValidator

        validator = TickValidator()
        tick1 = Tick(token=100, ltp=100.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        tick2 = Tick(token=101, ltp=101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)

        validator.check(tick1)
        validator.check(tick2)

        purged = validator.purge_unknown_tokens(known_tokens=set())
        self.assertEqual(purged, 2, "Empty known set should purge all tokens")
        self.assertIsNone(validator.get_prev_ts(100))
        self.assertIsNone(validator.get_prev_ts(101))


if __name__ == "__main__":
    unittest.main()
