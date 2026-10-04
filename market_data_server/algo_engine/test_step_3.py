import sys
import json
import csv
import unittest
import threading

sys.path.insert(0, r"C:\Users\Ankit\Desktop\RS FOLDER\rollover-react\market_data_server")

from algo_engine.bridge import Tick, TickBridge
from algo_engine.validator import TickValidator


def ts(minute: int) -> str:
    return f"2026-10-01 09:{minute:02d}:00.000"


# ── Step 3: Validator Tests ────────────────────────────────────────────────


class TestValidatorInit(unittest.TestCase):

    def test_initial_state(self):
        v = TickValidator()
        self.assertEqual(v.passed_count, 0)
        self.assertEqual(v.rejected_count, 0)
        self.assertEqual(v.rejected_by_reason, {"ltp_zero": 0, "ts_backward": 0, "ts_format": 0})

    def test_no_prev_ts_initially(self):
        v = TickValidator()
        self.assertIsNone(v.get_prev_ts(100))


class TestLTPValidation(unittest.TestCase):

    def setUp(self):
        self.v = TickValidator()

    def test_positive_ltp_passes(self):
        t = Tick(token=100, ltp=2850.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        ok, reason = self.v.check(t)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_zero_ltp_rejected(self):
        t = Tick(token=100, ltp=0.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        ok, reason = self.v.check(t)
        self.assertFalse(ok)
        self.assertEqual(reason, "ltp_zero")

    def test_negative_ltp_rejected(self):
        t = Tick(token=100, ltp=-5.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        ok, reason = self.v.check(t)
        self.assertFalse(ok)
        self.assertEqual(reason, "ltp_zero")

    def test_very_small_positive_passes(self):
        t = Tick(token=100, ltp=0.01, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        ok, reason = self.v.check(t)
        self.assertTrue(ok)

    def test_ltp_zero_increments_counter(self):
        for _ in range(3):
            t = Tick(token=100, ltp=0.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
            self.v.check(t)
        self.assertEqual(self.v.rejected_count, 3)
        self.assertEqual(self.v.rejected_by_reason["ltp_zero"], 3)


class TestTimestampValidation(unittest.TestCase):

    def setUp(self):
        self.v = TickValidator()

    def test_first_tick_always_passes(self):
        t = Tick(token=100, ltp=100.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        ok, reason = self.v.check(t)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_forward_timestamp_passes(self):
        t1 = Tick(token=100, ltp=100.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        t2 = Tick(token=100, ltp=101.0, ts="2026-10-01 09:21:00.000", recv_mono_ns=0)
        self.v.check(t1)
        ok, reason = self.v.check(t2)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_same_timestamp_accepted(self):
        t1 = Tick(token=100, ltp=100.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        t2 = Tick(token=100, ltp=101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        self.v.check(t1)
        ok, reason = self.v.check(t2)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_backward_timestamp_rejected(self):
        t1 = Tick(token=100, ltp=100.0, ts="2026-10-01 09:21:00.000", recv_mono_ns=0)
        t2 = Tick(token=100, ltp=101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        self.v.check(t1)
        ok, reason = self.v.check(t2)
        self.assertFalse(ok)
        self.assertEqual(reason, "ts_backward")

    def test_empty_ts_on_first_tick_passes(self):
        t = Tick(token=100, ltp=100.0, ts="", recv_mono_ns=0)
        ok, reason = self.v.check(t)
        self.assertTrue(ok)

    def test_empty_ts_on_subsequent_tick_passes(self):
        t1 = Tick(token=100, ltp=100.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        t2 = Tick(token=100, ltp=101.0, ts="", recv_mono_ns=0)
        self.v.check(t1)
        ok, reason = self.v.check(t2)
        self.assertTrue(ok)

    def test_ts_backward_increments_counter(self):
        t1 = Tick(token=100, ltp=100.0, ts="2026-10-01 09:21:00.000", recv_mono_ns=0)
        self.v.check(t1)
        for ts in ["2026-10-01 09:20:00.000", "2026-10-01 09:19:00.000"]:
            self.v.check(Tick(token=100, ltp=100.0, ts=ts, recv_mono_ns=0))
        self.assertEqual(self.v.rejected_count, 2)
        self.assertEqual(self.v.rejected_by_reason["ts_backward"], 2)


class TestMultipleTokens(unittest.TestCase):

    def setUp(self):
        self.v = TickValidator()

    def test_independent_tracking(self):
        t100 = Tick(token=100, ltp=100.0, ts="2026-10-01 09:21:00.000", recv_mono_ns=0)
        t200 = Tick(token=200, ltp=200.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0)
        ok1, _ = self.v.check(t100)
        ok2, _ = self.v.check(t200)
        self.assertTrue(ok1)
        self.assertTrue(ok2)

    def test_backward_on_one_doesnt_affect_other(self):
        self.v.check(Tick(token=100, ltp=100.0, ts="2026-10-01 09:21:00.000", recv_mono_ns=0))
        self.v.check(Tick(token=200, ltp=200.0, ts="2026-10-01 09:21:00.000", recv_mono_ns=0))
        ok, reason = self.v.check(Tick(token=100, ltp=101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0))
        self.assertFalse(ok)
        self.assertEqual(reason, "ts_backward")
        ok2, _ = self.v.check(Tick(token=200, ltp=201.0, ts="2026-10-01 09:22:00.000", recv_mono_ns=0))
        self.assertTrue(ok2)

    def test_prev_ts_tracked_per_token(self):
        self.v.check(Tick(token=100, ltp=100.0, ts=ts(20), recv_mono_ns=0))
        self.v.check(Tick(token=200, ltp=200.0, ts=ts(21), recv_mono_ns=0))
        self.assertEqual(self.v.get_prev_ts(100), ts(20))
        self.assertEqual(self.v.get_prev_ts(200), ts(21))
        self.assertIsNone(self.v.get_prev_ts(300))


class TestProcessTick(unittest.TestCase):

    def test_returns_bool(self):
        v = TickValidator()
        t_good = Tick(token=100, ltp=100.0, ts=ts(20), recv_mono_ns=0)
        t_bad = Tick(token=100, ltp=0.0, ts=ts(21), recv_mono_ns=0)
        self.assertTrue(v.process_tick(t_good))
        self.assertFalse(v.process_tick(t_bad))

    def test_process_tick_updates_state(self):
        v = TickValidator()
        v.process_tick(Tick(token=100, ltp=100.0, ts=ts(20), recv_mono_ns=0))
        v.process_tick(Tick(token=100, ltp=0.0, ts=ts(21), recv_mono_ns=0))
        self.assertEqual(v.passed_count, 1)
        self.assertEqual(v.rejected_count, 1)


class TestCounters(unittest.TestCase):

    def setUp(self):
        self.v = TickValidator()

    def test_passed_count(self):
        for i in range(5):
            self.v.check(Tick(token=100, ltp=100.0 + i, ts=ts(20 + i), recv_mono_ns=0))
        self.assertEqual(self.v.passed_count, 5)

    def test_mixed_counts(self):
        self.v.check(Tick(token=100, ltp=100.0, ts=ts(20), recv_mono_ns=0))
        self.v.check(Tick(token=100, ltp=0.0, ts=ts(21), recv_mono_ns=0))
        self.v.check(Tick(token=100, ltp=101.0, ts=ts(19), recv_mono_ns=0))
        self.assertEqual(self.v.passed_count, 1)
        self.assertEqual(self.v.rejected_count, 2)

    def test_rejected_by_reason_returns_copy(self):
        self.v.check(Tick(token=100, ltp=0.0, ts="T1", recv_mono_ns=0))
        reasons = self.v.rejected_by_reason
        reasons["ltp_zero"] = 999
        self.assertEqual(self.v.rejected_by_reason["ltp_zero"], 1)

    def test_rejected_by_reason_both(self):
        self.v.check(Tick(token=100, ltp=100.0, ts=ts(22), recv_mono_ns=0))
        self.v.check(Tick(token=100, ltp=0.0, ts=ts(23), recv_mono_ns=0))
        self.v.check(Tick(token=100, ltp=101.0, ts=ts(21), recv_mono_ns=0))
        reasons = self.v.rejected_by_reason
        self.assertEqual(reasons["ltp_zero"], 1)
        self.assertEqual(reasons["ts_backward"], 1)


class TestReset(unittest.TestCase):

    def test_reset_clears_all(self):
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts=ts(20), recv_mono_ns=0))
        v.check(Tick(token=100, ltp=0.0, ts=ts(21), recv_mono_ns=0))
        v.check(Tick(token=100, ltp=101.0, ts=ts(19), recv_mono_ns=0))
        v.reset()
        self.assertEqual(v.passed_count, 0)
        self.assertEqual(v.rejected_count, 0)
        self.assertEqual(v.rejected_by_reason, {"ltp_zero": 0, "ts_backward": 0, "ts_format": 0})
        self.assertIsNone(v.get_prev_ts(100))

    def test_works_after_reset(self):
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts=ts(20), recv_mono_ns=0))
        v.reset()
        ok, _ = v.check(Tick(token=100, ltp=101.0, ts=ts(20), recv_mono_ns=0))
        self.assertTrue(ok)
        self.assertEqual(v.passed_count, 1)


class TestValidatorWithBridge(unittest.TestCase):

    def test_bridge_ticks_through_validator(self):
        bridge = TickBridge()
        validator = TickValidator()

        msg = json.dumps({
            "type": "ticks",
            "count": 3,
            "data": [
                {"token": 100, "ltp_r": 2850.0, "ts": "2026-10-01 09:20:00.000",
                 "info": {"type": "future", "month": "current", "sym": "RELIANCE"}},
                {"token": 100, "ltp_r": 2851.0, "ts": "2026-10-01 09:21:00.000",
                 "info": {"type": "future", "month": "current", "sym": "RELIANCE"}},
                {"token": 100, "ltp_r": 2852.0, "ts": "2026-10-01 09:22:00.000",
                 "info": {"type": "future", "month": "current", "sym": "RELIANCE"}},
            ],
        })
        bridge._on_message(msg)

        for tick in bridge.get_all_ticks().values():
            validator.process_tick(tick)

        self.assertEqual(validator.passed_count, 1)

    def test_zero_ltp_from_bridge_rejected(self):
        bridge = TickBridge()
        validator = TickValidator()

        msg = json.dumps({
            "type": "ticks",
            "count": 1,
            "data": [
                {"token": 100, "ltp_r": 0.0, "ts": "2026-10-01 09:20:00.000",
                 "info": {"type": "future", "month": "current", "sym": "RELIANCE"}},
            ],
        })
        bridge._on_message(msg)

        for tick in bridge.get_all_ticks().values():
            result = validator.process_tick(tick)
        self.assertFalse(result)
        self.assertEqual(validator.rejected_count, 1)
        self.assertEqual(validator.rejected_by_reason["ltp_zero"], 1)


class TestValidatorThreadSafety(unittest.TestCase):

    def test_concurrent_check(self):
        v = TickValidator()
        errors = []

        def writer_a():
            try:
                for i in range(500):
                    v.check(Tick(token=100, ltp=100.0 + i * 0.01,
                                 ts=f"T{i:06d}", recv_mono_ns=0))
            except Exception as e:
                errors.append(e)

        def writer_b():
            try:
                for i in range(500):
                    v.check(Tick(token=200, ltp=200.0 + i * 0.01,
                                 ts=f"T{i:06d}", recv_mono_ns=0))
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(500):
                    _ = v.passed_count
                    _ = v.rejected_count
                    _ = v.rejected_by_reason
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer_a),
            threading.Thread(target=writer_b),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(errors, [])
        self.assertEqual(v.passed_count + v.rejected_count, 1000)


class TestRealCSVValidation(unittest.TestCase):

    def test_csv_ticks_validation(self):
        csv_path = r"C:\Users\Ankit\Desktop\RS FOLDER\rollover-react\market_data_server\tick_data\ticks_20260929.csv"
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except FileNotFoundError:
            self.skipTest("tick_data CSV not found")

        if not rows:
            self.skipTest("tick_data CSV is empty")

        v = TickValidator()
        for row in rows[:200]:
            token = int(row["token"])
            ltp = float(row["ltp"]) / 100.0
            ts = row.get("timestamp_ist", "")
            tick = Tick(token=token, ltp=ltp, ts=ts, recv_mono_ns=0)
            v.process_tick(tick)

        total = v.passed_count + v.rejected_count
        self.assertEqual(total, min(200, len(rows)))
        self.assertGreater(v.passed_count, 0)


class TestEdgeCases(unittest.TestCase):

    def test_ltp_exactly_zero(self):
        v = TickValidator()
        tick = Tick(token=100, ltp=0.0, ts="T1", recv_mono_ns=0)
        ok, reason = v.check(tick)
        self.assertFalse(ok)
        self.assertEqual(reason, "ltp_zero")

    def test_ltp_negative_zero(self):
        v = TickValidator()
        tick = Tick(token=100, ltp=-0.0, ts="T1", recv_mono_ns=0)
        ok, reason = v.check(tick)
        self.assertFalse(ok)
        self.assertEqual(reason, "ltp_zero")

    def test_large_ltp_passes(self):
        v = TickValidator()
        tick = Tick(token=100, ltp=999999.99, ts=ts(20), recv_mono_ns=0)
        ok, reason = v.check(tick)
        self.assertTrue(ok)

    def test_lexicographic_ts_comparison(self):
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts="2026-10-01 09:21:00.000", recv_mono_ns=0))
        ok, reason = v.check(Tick(token=100, ltp=101.0, ts="2026-10-01 09:20:59.999", recv_mono_ns=0))
        self.assertFalse(ok)
        self.assertEqual(reason, "ts_backward")

    def test_rejected_tick_does_not_update_prev_ts(self):
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts=ts(22), recv_mono_ns=0))
        v.check(Tick(token=100, ltp=0.0, ts=ts(21), recv_mono_ns=0))
        self.assertEqual(v.get_prev_ts(100), ts(22))

    def test_rejected_backward_does_not_update_prev_ts(self):
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts=ts(23), recv_mono_ns=0))
        v.check(Tick(token=100, ltp=101.0, ts=ts(21), recv_mono_ns=0))
        ok, _ = v.check(Tick(token=100, ltp=102.0, ts=ts(22), recv_mono_ns=0))
        self.assertFalse(ok)
        self.assertEqual(v.get_prev_ts(100), ts(23))


if __name__ == "__main__":
    unittest.main(verbosity=2)
