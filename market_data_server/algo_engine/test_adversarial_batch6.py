import sys
import unittest
import threading
import time
from datetime import datetime, timedelta

sys.path.insert(0, r"C:\Users\Ankit\Desktop\RS FOLDER\rollover-react\market_data_server")

from algo_engine.config import THRESHOLDS, IST
from algo_engine.spread import SpreadSnapshot
from algo_engine.alerts import AlertEngine, Alert


def _now_ist_str(offset_seconds=0):
    dt = datetime.now(IST) + timedelta(seconds=offset_seconds)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _make_snapshot(stock, spread, initial_spread, discount_pct=None, ts=None):
    if ts is None:
        ts = _now_ist_str()
    if discount_pct is None:
        discount_pct = max(0, (initial_spread - spread) / initial_spread * 100) if initial_spread > 0 else 0.0
    is_contango = spread > 0
    return SpreadSnapshot(
        stock=stock,
        spread=spread,
        discount_pct=discount_pct,
        initial_spread=initial_spread,
        current_fut_ltp=2850.0,
        next_fut_ltp=2850.0 + spread,
        timestamp=ts,
        is_contango=is_contango,
    )


class TestNoneSnapshot(unittest.TestCase):

    def test_none_snapshot_returns_none(self):
        engine = AlertEngine()
        result = engine.process_snapshot(None)
        self.assertIsNone(result)
        self.assertEqual(engine.get_alert_count(), 0)


class TestUnknownStock(unittest.TestCase):

    def test_stock_not_in_thresholds(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        snap = _make_snapshot("UNKNOWN_STOCK", spread=1.0, initial_spread=6.20, discount_pct=83.87)
        result = engine.process_snapshot(snap)
        self.assertIsNone(result)
        self.assertEqual(engine.get_alert_count(), 0)

    def test_multiple_unknown_stocks_ignored(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        for sym in ["FAKE1", "FAKE2", "FAKE3"]:
            snap = _make_snapshot(sym, spread=1.0, initial_spread=6.20, discount_pct=99.0)
            result = engine.process_snapshot(snap)
            self.assertIsNone(result)
        self.assertEqual(engine.get_alert_count(), 0)


class TestRapidOscillation(unittest.TestCase):

    def test_100_oscillations(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        alert_count = 0
        for i in range(100):
            snap_above = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87)
            alert = engine.process_snapshot(snap_above)
            if alert is not None:
                alert_count += 1
                self.assertEqual(alert.trigger_count, alert_count)

            snap_below = _make_snapshot("RELIANCE", spread=5.0, initial_spread=6.20, discount_pct=19.35)
            result = engine.process_snapshot(snap_below)
            self.assertIsNone(result)

        self.assertEqual(alert_count, 100)
        self.assertEqual(engine.get_alert_count(), 100)
        self.assertEqual(engine.get_trigger_count("RELIANCE"), 100)


class TestVeryHighDiscount(unittest.TestCase):

    def test_discount_over_100_pct(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        snap_below = _make_snapshot("RELIANCE", spread=5.0, initial_spread=6.20, discount_pct=19.35)
        engine.process_snapshot(snap_below)

        snap = _make_snapshot("RELIANCE", spread=-10.0, initial_spread=6.20, discount_pct=261.29)
        alert = engine.process_snapshot(snap)
        self.assertIsNotNone(alert)
        self.assertAlmostEqual(alert.discount_pct, 261.29)


class TestNegativeAndZeroDiscount(unittest.TestCase):

    def test_zero_discount_no_alert(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        snap = _make_snapshot("RELIANCE", spread=6.20, initial_spread=6.20, discount_pct=0.0)
        result = engine.process_snapshot(snap)
        self.assertIsNone(result)

    def test_negative_discount_no_alert(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        snap = _make_snapshot("RELIANCE", spread=7.0, initial_spread=6.20, discount_pct=0.0, )
        result = engine.process_snapshot(snap)
        self.assertIsNone(result)


class TestConcurrentAccess(unittest.TestCase):

    def test_concurrent_process_snapshot(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        errors = []

        def writer():
            try:
                for i in range(200):
                    if i % 2 == 0:
                        snap = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87)
                    else:
                        snap = _make_snapshot("RELIANCE", spread=5.0, initial_spread=6.20, discount_pct=19.35)
                    engine.process_snapshot(snap)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(200):
                    _ = engine.get_alert_count()
                    _ = engine.get_all_alerts()
                    _ = engine.get_trigger_count("RELIANCE")
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)
        self.assertEqual(errors, [])

    def test_concurrent_multiple_stocks(self):
        thresholds = {f"STOCK{i}": 40 for i in range(19)}
        engine = AlertEngine(thresholds=thresholds)
        errors = []

        def worker(stock_name):
            try:
                for i in range(50):
                    if i % 2 == 0:
                        snap = _make_snapshot(stock_name, spread=1.0, initial_spread=10.0, discount_pct=90.0)
                    else:
                        snap = _make_snapshot(stock_name, spread=8.0, initial_spread=10.0, discount_pct=20.0)
                    engine.process_snapshot(snap)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(19):
            t = threading.Thread(target=worker, args=(f"STOCK{i}",))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [])


class TestDayBoundary(unittest.TestCase):

    def test_day_boundary_resets_count(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})

        for _ in range(3):
            snap_above = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87,
                                         ts="2026-10-04 10:00:00.000")
            engine.process_snapshot(snap_above)
            snap_below = _make_snapshot("RELIANCE", spread=5.0, initial_spread=6.20, discount_pct=19.35,
                                         ts="2026-10-04 10:01:00.000")
            engine.process_snapshot(snap_below)

        self.assertEqual(engine.get_trigger_count("RELIANCE"), 3)

        snap_new_day = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87,
                                       ts="2026-10-05 09:20:00.000")
        alert = engine.process_snapshot(snap_new_day)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.trigger_count, 1)

    def test_same_timestamp_does_not_double_fire(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        ts = "2026-10-04 10:00:00.000"

        snap1 = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87, ts=ts)
        alert1 = engine.process_snapshot(snap1)
        self.assertIsNotNone(alert1)

        snap2 = _make_snapshot("RELIANCE", spread=0.5, initial_spread=6.20, discount_pct=91.94, ts=ts)
        result = engine.process_snapshot(snap2)
        self.assertIsNone(result, "Same timestamp, still above → no second alert")
        self.assertEqual(engine.get_alert_count(), 1)


class TestBackwardationToContango(unittest.TestCase):

    def test_backwardation_then_contango_cross(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})

        snap_back = _make_snapshot("RELIANCE", spread=-2.0, initial_spread=6.20, discount_pct=0.0)
        result = engine.process_snapshot(snap_back)
        self.assertIsNone(result)

        snap_contango_below = _make_snapshot("RELIANCE", spread=5.0, initial_spread=6.20, discount_pct=19.35)
        result = engine.process_snapshot(snap_contango_below)
        self.assertIsNone(result)

        snap_contango_above = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87)
        alert = engine.process_snapshot(snap_contango_above)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.trigger_count, 1)


class TestCustomThresholdChange(unittest.TestCase):

    def test_different_thresholds_different_behavior(self):
        engine_35 = AlertEngine(thresholds={"RELIANCE": 35})
        engine_40 = AlertEngine(thresholds={"RELIANCE": 40})

        snap = _make_snapshot("RELIANCE", spread=4.0, initial_spread=6.20, discount_pct=35.48)

        alert_35 = engine_35.process_snapshot(snap)
        alert_40 = engine_40.process_snapshot(snap)

        self.assertIsNotNone(alert_35, "35.48% >= 35% should fire")
        self.assertIsNone(alert_40, "35.48% < 40% should not fire")


class TestMemoryLeakPrevention(unittest.TestCase):

    def test_alerts_list_grows_bounded_by_transitions(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        for _ in range(1000):
            snap_above = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87)
            engine.process_snapshot(snap_above)
            snap_below = _make_snapshot("RELIANCE", spread=5.0, initial_spread=6.20, discount_pct=19.35)
            engine.process_snapshot(snap_below)

        self.assertEqual(engine.get_alert_count(), 1000)

    def test_reset_clears_alerts_list(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        snap = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87)
        engine.process_snapshot(snap)
        self.assertEqual(engine.get_alert_count(), 1)

        engine.reset()
        self.assertEqual(engine.get_alert_count(), 0)
        self.assertEqual(len(engine._alerts), 0)


class TestExactThresholdOscillation(unittest.TestCase):

    def test_exact_threshold_then_below_then_exact_again(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})

        snap_exact = _make_snapshot("RELIANCE", spread=4.03, initial_spread=6.20, discount_pct=35.0)
        alert1 = engine.process_snapshot(snap_exact)
        self.assertIsNotNone(alert1)

        snap_below = _make_snapshot("RELIANCE", spread=4.04, initial_spread=6.20, discount_pct=34.99)
        result = engine.process_snapshot(snap_below)
        self.assertIsNone(result)

        snap_exact2 = _make_snapshot("RELIANCE", spread=4.03, initial_spread=6.20, discount_pct=35.0)
        alert2 = engine.process_snapshot(snap_exact2)
        self.assertIsNotNone(alert2)
        self.assertEqual(alert2.trigger_count, 2)


class TestFloatingPointPrecision(unittest.TestCase):

    def test_very_small_discount_below_threshold(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        snap = _make_snapshot("RELIANCE", spread=4.030001, initial_spread=6.20, discount_pct=34.9999)
        result = engine.process_snapshot(snap)
        self.assertIsNone(result)

    def test_very_small_discount_above_threshold(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        snap_below = _make_snapshot("RELIANCE", spread=5.0, initial_spread=6.20, discount_pct=19.35)
        engine.process_snapshot(snap_below)

        snap_above = _make_snapshot("RELIANCE", spread=4.029999, initial_spread=6.20, discount_pct=35.0001)
        alert = engine.process_snapshot(snap_above)
        self.assertIsNotNone(alert)


class TestASTRALHandling(unittest.TestCase):

    def test_astral_in_thresholds_but_skipped_by_spread_engine(self):
        engine = AlertEngine()
        self.assertIn("ASTRAL", engine._thresholds,
                       "ASTRAL is in THRESHOLDS — SpreadEngine filters it before AlertEngine sees it")

    def test_astral_snapshot_processed_if_it_arrives(self):
        engine = AlertEngine()
        snap = _make_snapshot("ASTRAL", spread=1.0, initial_spread=-1.70, discount_pct=99.0)
        alert = engine.process_snapshot(snap)
        self.assertIsNotNone(alert,
                              "If a snapshot somehow reaches AlertEngine, it processes it — "
                              "protection is at SpreadEngine level (negative initial_spread skip)")


class TestResetDailyVsFull(unittest.TestCase):

    def test_reset_daily_preserves_alerts_list(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        snap = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87)
        engine.process_snapshot(snap)
        self.assertEqual(engine.get_alert_count(), 1)

        engine.reset_daily()
        self.assertEqual(engine.get_alert_count(), 1, "reset_daily should NOT clear alerts list")
        self.assertEqual(engine.get_trigger_count("RELIANCE"), 0, "reset_daily should clear trigger counts")

    def test_full_reset_clears_alerts_list(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        snap = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87)
        engine.process_snapshot(snap)

        engine.reset()
        self.assertEqual(engine.get_alert_count(), 0)
        self.assertEqual(engine.get_trigger_count("RELIANCE"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
