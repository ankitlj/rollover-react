import unittest
import time
from algo_engine.bridge import TickBridge
from algo_engine.config import STOCK_CONFIG


class TestBug23_TokenMappingValidation(unittest.TestCase):

    def test_unknown_tokens_detected(self):
        """Unknown tokens are correctly identified"""
        bridge = TickBridge()
        bridge.inject_tick(999999, 100.0, ts="2026-10-04 10:00:00.000")
        unknown = bridge.get_unknown_tokens()
        self.assertEqual(unknown, [999999], "Should detect unknown token")

    def test_known_tokens_not_flagged(self):
        """Known tokens are not flagged as unknown"""
        bridge = TickBridge()
        tokens = {
            "1": {"sym": "RELIANCE", "type": "future", "month": "current"},
            "2": {"sym": "RELIANCE", "type": "future", "month": "next"},
        }
        bridge.inject_metadata(tokens=tokens, stocks=[])
        bridge.inject_tick(1, 2850.0, ts="2026-10-04 10:00:00.000")
        bridge.inject_tick(2, 2854.0, ts="2026-10-04 10:00:00.000")
        unknown = bridge.get_unknown_tokens()
        self.assertEqual(unknown, [], "Known tokens should not be flagged")

    def test_mixed_known_and_unknown(self):
        """Mixed known and unknown tokens are handled correctly"""
        bridge = TickBridge()
        tokens = {"1": {"sym": "RELIANCE", "type": "future", "month": "current"}}
        bridge.inject_metadata(tokens=tokens, stocks=[])
        bridge.inject_tick(1, 2850.0, ts="2026-10-04 10:00:00.000")
        bridge.inject_tick(999, 100.0, ts="2026-10-04 10:00:00.000")
        unknown = bridge.get_unknown_tokens()
        self.assertEqual(unknown, [999], "Only unknown token should be flagged")

    def test_validate_token_mapping_returns_structure(self):
        """validate_token_mapping returns correct structure"""
        bridge = TickBridge()
        tokens = {"1": {"sym": "RELIANCE", "type": "future", "month": "current"}}
        bridge.inject_metadata(tokens=tokens, stocks=[])
        bridge.inject_tick(1, 2850.0, ts="2026-10-04 10:00:00.000")
        result = bridge.validate_token_mapping()
        self.assertIn("unknown_tokens", result)
        self.assertIn("missing_tokens", result)
        self.assertIn("known_count", result)
        self.assertIn("active_count", result)

    def test_validate_token_mapping_detects_missing(self):
        """validate_token_mapping detects missing tokens (in metadata but no ticks)"""
        bridge = TickBridge()
        tokens = {
            "1": {"sym": "RELIANCE", "type": "future", "month": "current"},
            "2": {"sym": "RELIANCE", "type": "future", "month": "next"},
        }
        bridge.inject_metadata(tokens=tokens, stocks=[])
        bridge.inject_tick(1, 2850.0, ts="2026-10-04 10:00:00.000")
        result = bridge.validate_token_mapping()
        self.assertEqual(result["missing_tokens"], [2], "Token 2 should be missing")
        self.assertEqual(result["known_count"], 2)
        self.assertEqual(result["active_count"], 1)

    def test_validate_token_mapping_detects_unknown(self):
        """validate_token_mapping detects unknown tokens (ticks but not in metadata)"""
        bridge = TickBridge()
        tokens = {"1": {"sym": "RELIANCE", "type": "future", "month": "current"}}
        bridge.inject_metadata(tokens=tokens, stocks=[])
        bridge.inject_tick(1, 2850.0, ts="2026-10-04 10:00:00.000")
        bridge.inject_tick(999, 100.0, ts="2026-10-04 10:00:00.000")
        result = bridge.validate_token_mapping()
        self.assertEqual(result["unknown_tokens"], [999], "Token 999 should be unknown")

    def test_validate_token_mapping_perfect_match(self):
        """validate_token_mapping with perfect match returns empty lists"""
        bridge = TickBridge()
        tokens = {
            "1": {"sym": "RELIANCE", "type": "future", "month": "current"},
            "2": {"sym": "RELIANCE", "type": "future", "month": "next"},
        }
        bridge.inject_metadata(tokens=tokens, stocks=[])
        bridge.inject_tick(1, 2850.0, ts="2026-10-04 10:00:00.000")
        bridge.inject_tick(2, 2854.0, ts="2026-10-04 10:00:00.000")
        result = bridge.validate_token_mapping()
        self.assertEqual(result["unknown_tokens"], [])
        self.assertEqual(result["missing_tokens"], [])
        self.assertEqual(result["known_count"], 2)
        self.assertEqual(result["active_count"], 2)

    def test_empty_bridge_validation(self):
        """Validation on empty bridge returns zeros"""
        bridge = TickBridge()
        result = bridge.validate_token_mapping()
        self.assertEqual(result["unknown_tokens"], [])
        self.assertEqual(result["missing_tokens"], [])
        self.assertEqual(result["known_count"], 0)
        self.assertEqual(result["active_count"], 0)

    def test_multiple_unknown_tokens(self):
        """Multiple unknown tokens are all detected"""
        bridge = TickBridge()
        bridge.inject_tick(999, 100.0, ts="2026-10-04 10:00:00.000")
        bridge.inject_tick(888, 200.0, ts="2026-10-04 10:00:00.000")
        bridge.inject_tick(777, 300.0, ts="2026-10-04 10:00:00.000")
        unknown = bridge.get_unknown_tokens()
        self.assertEqual(len(unknown), 3)
        self.assertIn(999, unknown)
        self.assertIn(888, unknown)
        self.assertIn(777, unknown)


if __name__ == "__main__":
    unittest.main()
