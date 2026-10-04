import sys
import unittest
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


class TestAlertEngineInit(unittest.TestCase):

    def test_default_thresholds_from_config(self):
        engine = AlertEngine()
        self.assertEqual(engine._thresholds["RELIANCE"], 35)
        self.assertEqual(engine._thresholds["HDFCBANK"], 40)

    def test_custom_thresholds(self):
        engine = AlertEngine(thresholds={"TEST": 50})
        self.assertEqual(engine._thresholds["TEST"], 50)

    def test_initial_state_empty(self):
        engine = AlertEngine()
        self.assertEqual(engine.get_alert_count(), 0)
        self.assertEqual(engine.get_all_alerts(), [])
        self.assertEqual(engine.get_trigger_count("RELIANCE"), 0)


class TestSingleAlert(unittest.TestCase):

    def test_alert_fires_on_below_to_above_transition(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        snap_below = _make_snapshot("RELIANCE", spread=5.0, initial_spread=6.20, discount_pct=19.35)
        result1 = engine.process_snapshot(snap_below)
        self.assertIsNone(result1)

        snap_above = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87)
        result2 = engine.process_snapshot(snap_above)
        self.assertIsNotNone(result2)
        self.assertIsInstance(result2, Alert)
        self.assertEqual(result2.stock, "RELIANCE")
        self.assertEqual(result2.threshold, 35)
        self.assertEqual(result2.trigger_count, 1)

    def test_no_alert_when_still_below(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        snap = _make_snapshot("RELIANCE", spread=5.0, initial_spread=6.20, discount_pct=19.35)
        result = engine.process_snapshot(snap)
        self.assertIsNone(result)
        self.assertEqual(engine.get_alert_count(), 0)

    def test_no_alert_when_still_above(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        snap1 = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87)
        engine.process_snapshot(snap1)
        self.assertEqual(engine.get_alert_count(), 1)

        snap2 = _make_snapshot("RELIANCE", spread=0.5, initial_spread=6.20, discount_pct=91.94)
        result = engine.process_snapshot(snap2)
        self.assertIsNone(result)
        self.assertEqual(engine.get_alert_count(), 1)

    def test_alert_fields_populated(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        ts = "2026-10-04 10:30:00.000"
        snap = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87, ts=ts)
        alert = engine.process_snapshot(snap)
        self.assertEqual(alert.stock, "RELIANCE")
        self.assertEqual(alert.timestamp, ts)
        self.assertAlmostEqual(alert.spread, 1.0)
        self.assertAlmostEqual(alert.discount_pct, 83.87)
        self.assertEqual(alert.threshold, 35)
        self.assertEqual(alert.trigger_count, 1)
        self.assertAlmostEqual(alert.initial_spread, 6.20)
        self.assertAlmostEqual(alert.current_fut_ltp, 2850.0)
        self.assertAlmostEqual(alert.next_fut_ltp, 2851.0)


class TestMultiShotOscillation(unittest.TestCase):

    def test_oscillation_fires_multiple_alerts(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})

        snap_above1 = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87)
        alert1 = engine.process_snapshot(snap_above1)
        self.assertIsNotNone(alert1)
        self.assertEqual(alert1.trigger_count, 1)

        snap_below = _make_snapshot("RELIANCE", spread=5.0, initial_spread=6.20, discount_pct=19.35)
        result = engine.process_snapshot(snap_below)
        self.assertIsNone(result)

        snap_above2 = _make_snapshot("RELIANCE", spread=0.5, initial_spread=6.20, discount_pct=91.94)
        alert2 = engine.process_snapshot(snap_above2)
        self.assertIsNotNone(alert2)
        self.assertEqual(alert2.trigger_count, 2)

        self.assertEqual(engine.get_alert_count(), 2)

    def test_three_oscillations(self):
        engine = AlertEngine(thresholds={"TCS": 40})
        for i in range(3):
            snap_above = _make_snapshot("TCS", spread=1.0, initial_spread=10.10, discount_pct=90.10)
            alert = engine.process_snapshot(snap_above)
            self.assertIsNotNone(alert)
            self.assertEqual(alert.trigger_count, i + 1)

            snap_below = _make_snapshot("TCS", spread=8.0, initial_spread=10.10, discount_pct=20.79)
            result = engine.process_snapshot(snap_below)
            self.assertIsNone(result)

        self.assertEqual(engine.get_alert_count(), 3)


class TestMultipleStocks(unittest.TestCase):

    def test_independent_tracking(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35, "TCS": 40})

        snap_rel_above = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87)
        alert_rel = engine.process_snapshot(snap_rel_above)
        self.assertIsNotNone(alert_rel)
        self.assertEqual(alert_rel.stock, "RELIANCE")

        snap_tcs_below = _make_snapshot("TCS", spread=8.0, initial_spread=10.10, discount_pct=20.79)
        result = engine.process_snapshot(snap_tcs_below)
        self.assertIsNone(result)

        self.assertEqual(engine.get_trigger_count("RELIANCE"), 1)
        self.assertEqual(engine.get_trigger_count("TCS"), 0)
        self.assertEqual(engine.get_alert_count(), 1)

    def test_both_stocks_alert(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35, "TCS": 40})

        snap1 = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87)
        snap2 = _make_snapshot("TCS", spread=1.0, initial_spread=10.10, discount_pct=90.10)

        alert1 = engine.process_snapshot(snap1)
        alert2 = engine.process_snapshot(snap2)

        self.assertIsNotNone(alert1)
        self.assertIsNotNone(alert2)
        self.assertEqual(engine.get_alert_count(), 2)


class TestTriggerCount(unittest.TestCase):

    def test_trigger_count_increments(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        self.assertEqual(engine.get_trigger_count("RELIANCE"), 0)

        snap_above = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87)
        engine.process_snapshot(snap_above)
        self.assertEqual(engine.get_trigger_count("RELIANCE"), 1)

        snap_below = _make_snapshot("RELIANCE", spread=5.0, initial_spread=6.20, discount_pct=19.35)
        engine.process_snapshot(snap_below)

        snap_above2 = _make_snapshot("RELIANCE", spread=0.5, initial_spread=6.20, discount_pct=91.94)
        engine.process_snapshot(snap_above2)
        self.assertEqual(engine.get_trigger_count("RELIANCE"), 2)

    def test_trigger_count_unknown_stock(self):
        engine = AlertEngine()
        self.assertEqual(engine.get_trigger_count("NONEXISTENT"), 0)


class TestBoundaryCondition(unittest.TestCase):

    def test_exact_threshold_fires_alert(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        snap_below = _make_snapshot("RELIANCE", spread=5.0, initial_spread=6.20, discount_pct=19.35)
        engine.process_snapshot(snap_below)

        snap_exact = _make_snapshot("RELIANCE", spread=4.03, initial_spread=6.20, discount_pct=35.0)
        alert = engine.process_snapshot(snap_exact)
        self.assertIsNotNone(alert, "discount_pct == threshold should fire alert (>=)")
        self.assertEqual(alert.trigger_count, 1)

    def test_just_below_threshold_no_alert(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        snap_below = _make_snapshot("RELIANCE", spread=5.0, initial_spread=6.20, discount_pct=19.35)
        engine.process_snapshot(snap_below)

        snap_just_below = _make_snapshot("RELIANCE", spread=4.04, initial_spread=6.20, discount_pct=34.99)
        result = engine.process_snapshot(snap_just_below)
        self.assertIsNone(result)


class TestBackwardationNoAlert(unittest.TestCase):

    def test_backwardation_zero_discount_no_alert(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        snap = _make_snapshot("RELIANCE", spread=-2.0, initial_spread=6.20, discount_pct=0.0)
        result = engine.process_snapshot(snap)
        self.assertIsNone(result)
        self.assertEqual(engine.get_alert_count(), 0)


class TestDailyReset(unittest.TestCase):

    def test_daily_reset_clears_trigger_counts(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})

        snap_above = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87,
                                     ts="2026-10-04 10:00:00.000")
        engine.process_snapshot(snap_above)
        self.assertEqual(engine.get_trigger_count("RELIANCE"), 1)

        engine.reset_daily()
        self.assertEqual(engine.get_trigger_count("RELIANCE"), 0)

    def test_new_day_resets_trigger_count(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})

        snap_day1 = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87,
                                    ts="2026-10-04 10:00:00.000")
        engine.process_snapshot(snap_day1)
        self.assertEqual(engine.get_trigger_count("RELIANCE"), 1)

        snap_below_day1 = _make_snapshot("RELIANCE", spread=5.0, initial_spread=6.20, discount_pct=19.35,
                                          ts="2026-10-04 11:00:00.000")
        engine.process_snapshot(snap_below_day1)

        snap_day2 = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87,
                                    ts="2026-10-05 09:20:00.000")
        alert = engine.process_snapshot(snap_day2)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.trigger_count, 1, "New day should reset trigger count to 1")


class TestGetAllAlerts(unittest.TestCase):

    def test_returns_copy(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        snap = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87)
        engine.process_snapshot(snap)

        alerts1 = engine.get_all_alerts()
        alerts2 = engine.get_all_alerts()
        self.assertEqual(len(alerts1), len(alerts2))
        self.assertIsNot(alerts1, alerts2)

    def test_alerts_accumulate(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})

        for i in range(5):
            snap_above = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87)
            engine.process_snapshot(snap_above)
            snap_below = _make_snapshot("RELIANCE", spread=5.0, initial_spread=6.20, discount_pct=19.35)
            engine.process_snapshot(snap_below)

        self.assertEqual(engine.get_alert_count(), 5)
        self.assertEqual(len(engine.get_all_alerts()), 5)


class TestReset(unittest.TestCase):

    def test_full_reset_clears_everything(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        snap = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87)
        engine.process_snapshot(snap)
        self.assertEqual(engine.get_alert_count(), 1)

        engine.reset()
        self.assertEqual(engine.get_alert_count(), 0)
        self.assertEqual(engine.get_trigger_count("RELIANCE"), 0)
        self.assertEqual(engine.get_all_alerts(), [])

    def test_after_reset_can_alert_again(self):
        engine = AlertEngine(thresholds={"RELIANCE": 35})
        snap = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87)
        engine.process_snapshot(snap)
        engine.reset()

        snap2 = _make_snapshot("RELIANCE", spread=1.0, initial_spread=6.20, discount_pct=83.87)
        alert = engine.process_snapshot(snap2)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.trigger_count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
