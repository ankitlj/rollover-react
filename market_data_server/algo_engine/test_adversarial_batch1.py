import sys
import unittest

sys.path.insert(0, r"C:\Users\Ankit\Desktop\RS FOLDER\rollover-react\market_data_server")

from algo_engine.bridge import Tick
from algo_engine.validator import TickValidator


class TestBug11_TimestampFormatValidation(unittest.TestCase):
    """Bug 11: Old code accepted ANY string as timestamp — garbage, wrong formats, etc.
    New code enforces YYYY-MM-DD HH:MM:SS.mmm format."""

    def setUp(self):
        self.v = TickValidator()

    def test_garbage_timestamp_rejected(self):
        tick = Tick(token=100, ltp=100.0, ts="not_a_timestamp", recv_mono_ns=0)
        ok, reason = self.v.check(tick)
        self.assertFalse(ok)
        self.assertEqual(reason, "ts_format")

    def test_slash_format_rejected(self):
        tick = Tick(token=100, ltp=100.0, ts="2026/10/01 09:20:00", recv_mono_ns=0)
        ok, reason = self.v.check(tick)
        self.assertFalse(ok)
        self.assertEqual(reason, "ts_format")

    def test_iso_format_rejected(self):
        tick = Tick(token=100, ltp=100.0, ts="2026-10-01T09:20:00Z", recv_mono_ns=0)
        ok, reason = self.v.check(tick)
        self.assertFalse(ok)
        self.assertEqual(reason, "ts_format")

    def test_short_format_rejected(self):
        tick = Tick(token=100, ltp=100.0, ts="2026-10-01 09:20:00", recv_mono_ns=0)
        ok, reason = self.v.check(tick)
        self.assertFalse(ok)
        self.assertEqual(reason, "ts_format")

    def test_no_milliseconds_rejected(self):
        tick = Tick(token=100, ltp=100.0, ts="2026-10-01 09:20:00.", recv_mono_ns=0)
        ok, reason = self.v.check(tick)
        self.assertFalse(ok)
        self.assertEqual(reason, "ts_format")

    def test_correct_format_accepted(self):
        tick = Tick(token=100, ltp=100.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        ok, reason = self.v.check(tick)
        self.assertTrue(ok)

    def test_correct_format_with_millis_accepted(self):
        tick = Tick(token=100, ltp=100.0, ts="2026-10-01 09:20:00.123", recv_mono_ns=0)
        ok, reason = self.v.check(tick)
        self.assertTrue(ok)

    def test_empty_ts_accepted(self):
        tick = Tick(token=100, ltp=100.0, ts="", recv_mono_ns=0)
        ok, reason = self.v.check(tick)
        self.assertTrue(ok)

    def test_none_ts_accepted(self):
        tick = Tick(token=100, ltp=100.0, ts=None, recv_mono_ns=0)
        ok, reason = self.v.check(tick)
        self.assertTrue(ok)

    def test_format_rejection_increments_counter(self):
        for i in range(3):
            tick = Tick(token=100, ltp=100.0, ts=f"garbage_{i}", recv_mono_ns=0)
            self.v.check(tick)
        self.assertEqual(self.v.rejected_by_reason["ts_format"], 3)

    def test_backward_detection_not_defeated_by_format_change(self):
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts="2026-10-01 09:21:00.000", recv_mono_ns=0))
        ok, reason = v.check(Tick(token=100, ltp=101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0))
        self.assertFalse(ok)
        self.assertEqual(reason, "ts_backward")


class TestBug12_SameTimestampAccepted(unittest.TestCase):
    """Bug 12: Old code rejected same-timestamp ticks (<=). New code accepts them (<).
    In high-frequency feeds, multiple ticks can arrive with identical timestamps."""

    def setUp(self):
        self.v = TickValidator()

    def test_same_timestamp_accepted(self):
        t1 = Tick(token=100, ltp=100.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        t2 = Tick(token=100, ltp=101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        ok1, _ = self.v.check(t1)
        ok2, reason2 = self.v.check(t2)
        self.assertTrue(ok1)
        self.assertTrue(ok2)
        self.assertIsNone(reason2)

    def test_same_timestamp_different_tokens(self):
        t1 = Tick(token=100, ltp=100.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        t2 = Tick(token=200, ltp=200.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        ok1, _ = self.v.check(t1)
        ok2, _ = self.v.check(t2)
        self.assertTrue(ok1)
        self.assertTrue(ok2)

    def test_backward_still_rejected(self):
        t1 = Tick(token=100, ltp=100.0, ts="2026-10-01 09:21:00.000", recv_mono_ns=0)
        t2 = Tick(token=100, ltp=101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        self.v.check(t1)
        ok, reason = self.v.check(t2)
        self.assertFalse(ok)
        self.assertEqual(reason, "ts_backward")

    def test_multiple_same_timestamps_all_pass(self):
        for i in range(5):
            tick = Tick(token=100, ltp=100.0 + i, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
            ok, _ = self.v.check(tick)
            self.assertTrue(ok)
        self.assertEqual(self.v.passed_count, 5)

    def test_same_ts_does_not_update_prev_ts_to_different_value(self):
        self.v.check(Tick(token=100, ltp=100.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0))
        self.v.check(Tick(token=100, ltp=101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0))
        self.assertEqual(self.v.get_prev_ts(100), "2026-10-01 09:20:00.000")


if __name__ == "__main__":
    unittest.main()
