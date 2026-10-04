import unittest
import time
import threading
from unittest.mock import Mock, patch
from algo_engine.spread import SpreadEngine
from algo_engine.bridge import TickBridge
from algo_engine.config import STOCK_CONFIG, INITIAL_SPREADS


def _now_ist_str():
    from algo_engine.config import IST
    from datetime import datetime
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


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


class TestBug22_PipelineHangDetection(unittest.TestCase):

    def test_is_healthy_true_when_no_computes_yet(self):
        """Pipeline is healthy before any compute (no baseline to compare)"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        self.assertTrue(engine.is_healthy(), "Should be healthy before any computes")

    def test_is_healthy_true_after_recent_success(self):
        """Pipeline is healthy right after successful compute"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tokens = bridge.get_tokens_for_stock("RELIANCE")
        ts = _now_ist_str()
        bridge.inject_tick(tokens["current"], 2850.0, ts=ts,
                          info={"sym": "RELIANCE", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 2854.0, ts=ts,
                          info={"sym": "RELIANCE", "type": "future", "month": "next"})
        engine.compute_for_stock("RELIANCE")
        self.assertTrue(engine.is_healthy(), "Should be healthy right after success")

    def test_is_healthy_false_after_stall(self):
        """Pipeline is unhealthy when no success for too long"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tokens = bridge.get_tokens_for_stock("RELIANCE")
        ts = _now_ist_str()
        bridge.inject_tick(tokens["current"], 2850.0, ts=ts,
                          info={"sym": "RELIANCE", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 2854.0, ts=ts,
                          info={"sym": "RELIANCE", "type": "future", "month": "next"})
        engine.compute_for_stock("RELIANCE")
        time.sleep(0.2)
        self.assertFalse(engine.is_healthy(max_stale_seconds=0.1),
                        "Should be unhealthy after stall")

    def test_pipeline_age_returns_negative_one_when_no_computes(self):
        """pipeline_age_seconds returns -1 before any compute"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        age = engine.pipeline_age_seconds()
        self.assertEqual(age, -1.0, "Should return -1 before any computes")

    def test_pipeline_age_returns_correct_age(self):
        """pipeline_age_seconds returns time since last success"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tokens = bridge.get_tokens_for_stock("RELIANCE")
        ts = _now_ist_str()
        bridge.inject_tick(tokens["current"], 2850.0, ts=ts,
                          info={"sym": "RELIANCE", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 2854.0, ts=ts,
                          info={"sym": "RELIANCE", "type": "future", "month": "next"})
        engine.compute_for_stock("RELIANCE")
        time.sleep(0.15)
        age = engine.pipeline_age_seconds()
        self.assertGreaterEqual(age, 0.10, "Age should be at least 0.10s")
        self.assertLess(age, 0.3, "Age should be less than 0.3s")

    def test_reset_clears_last_success_time(self):
        """reset() clears the last success timestamp"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tokens = bridge.get_tokens_for_stock("RELIANCE")
        ts = _now_ist_str()
        bridge.inject_tick(tokens["current"], 2850.0, ts=ts,
                          info={"sym": "RELIANCE", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 2854.0, ts=ts,
                          info={"sym": "RELIANCE", "type": "future", "month": "next"})
        engine.compute_for_stock("RELIANCE")
        time.sleep(0.05)
        self.assertGreater(engine.pipeline_age_seconds(), 0)
        engine.reset()
        self.assertEqual(engine.pipeline_age_seconds(), -1.0,
                        "reset should clear last success time")

    def test_health_check_with_custom_threshold(self):
        """is_healthy respects custom max_stale_seconds parameter"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tokens = bridge.get_tokens_for_stock("RELIANCE")
        ts = _now_ist_str()
        bridge.inject_tick(tokens["current"], 2850.0, ts=ts,
                          info={"sym": "RELIANCE", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 2854.0, ts=ts,
                          info={"sym": "RELIANCE", "type": "future", "month": "next"})
        engine.compute_for_stock("RELIANCE")
        time.sleep(0.15)
        self.assertTrue(engine.is_healthy(max_stale_seconds=0.2),
                       "Should be healthy with 0.2s threshold")
        self.assertFalse(engine.is_healthy(max_stale_seconds=0.1),
                        "Should be unhealthy with 0.1s threshold")

    def test_backwardation_snapshot_updates_last_success(self):
        """Backwardation (spread <= 0) also updates last success time"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tokens = bridge.get_tokens_for_stock("RELIANCE")
        ts = _now_ist_str()
        bridge.inject_tick(tokens["current"], 2854.0, ts=ts,
                          info={"sym": "RELIANCE", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 2850.0, ts=ts,
                          info={"sym": "RELIANCE", "type": "future", "month": "next"})
        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap, "Backwardation snapshot should be created")
        self.assertFalse(snap.is_contango)
        self.assertTrue(engine.is_healthy(),
                       "Backwardation should update last success time")

    def test_compute_all_updates_last_success_if_any_success(self):
        """compute_all updates last success if at least one stock succeeds"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tokens = bridge.get_tokens_for_stock("RELIANCE")
        ts = _now_ist_str()
        bridge.inject_tick(tokens["current"], 2850.0, ts=ts,
                          info={"sym": "RELIANCE", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 2854.0, ts=ts,
                          info={"sym": "RELIANCE", "type": "future", "month": "next"})
        engine.compute_all()
        self.assertTrue(engine.is_healthy(),
                       "compute_all should update last success time")

    def test_stale_ticks_dont_update_last_success(self):
        """Stale ticks don't update last success time"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tokens = bridge.get_tokens_for_stock("RELIANCE")
        old_mono = time.monotonic_ns() - int(120 * 1e9)
        ts = _now_ist_str()
        bridge.inject_tick(tokens["current"], 2850.0, ts=ts,
                          info={"sym": "RELIANCE", "type": "future", "month": "current"},
                          recv_mono_ns=old_mono)
        bridge.inject_tick(tokens["next"], 2854.0, ts=ts,
                          info={"sym": "RELIANCE", "type": "future", "month": "next"},
                          recv_mono_ns=old_mono)
        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNone(snap, "Stale ticks should not produce snapshot")
        self.assertEqual(engine.pipeline_age_seconds(), -1.0,
                        "Stale ticks should not update last success time")


if __name__ == "__main__":
    unittest.main()
