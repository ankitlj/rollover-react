import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, r"C:\Users\Ankit\Desktop\RS FOLDER\rollover-react\market_data_server")

from algo_engine.config import IST
from algo_engine.session import (
    SessionEngine,
    PHASE_WAITING, PHASE_WARMUP, PHASE_ACTIVE, PHASE_CLOSING, PHASE_CLOSED,
)
from algo_engine.alerts import Alert


def _dt(hour, minute, second=0, weekday=0):
    base = datetime(2026, 10, 5 + weekday, hour, minute, second, tzinfo=IST)
    return base


class TestPhaseTransitions(unittest.TestCase):

    def test_waiting_before_market_open(self):
        engine = SessionEngine()
        self.assertEqual(engine.current_phase(_dt(8, 0)), PHASE_WAITING)
        self.assertEqual(engine.current_phase(_dt(9, 0)), PHASE_WAITING)
        self.assertEqual(engine.current_phase(_dt(9, 14)), PHASE_WAITING)

    def test_warmup_915_to_920(self):
        engine = SessionEngine()
        self.assertEqual(engine.current_phase(_dt(9, 15)), PHASE_WARMUP)
        self.assertEqual(engine.current_phase(_dt(9, 17)), PHASE_WARMUP)
        self.assertEqual(engine.current_phase(_dt(9, 19, 59)), PHASE_WARMUP)

    def test_active_920_to_1445(self):
        engine = SessionEngine()
        self.assertEqual(engine.current_phase(_dt(9, 20)), PHASE_ACTIVE)
        self.assertEqual(engine.current_phase(_dt(10, 0)), PHASE_ACTIVE)
        self.assertEqual(engine.current_phase(_dt(12, 30)), PHASE_ACTIVE)
        self.assertEqual(engine.current_phase(_dt(14, 44, 59)), PHASE_ACTIVE)

    def test_closing_1445_to_1500(self):
        engine = SessionEngine()
        self.assertEqual(engine.current_phase(_dt(14, 45)), PHASE_CLOSING)
        self.assertEqual(engine.current_phase(_dt(14, 50)), PHASE_CLOSING)
        self.assertEqual(engine.current_phase(_dt(14, 59, 59)), PHASE_CLOSING)

    def test_closed_after_1500(self):
        engine = SessionEngine()
        self.assertEqual(engine.current_phase(_dt(15, 0)), PHASE_CLOSED)
        self.assertEqual(engine.current_phase(_dt(15, 30)), PHASE_CLOSED)
        self.assertEqual(engine.current_phase(_dt(16, 0)), PHASE_CLOSED)


class TestWeekend(unittest.TestCase):

    def test_saturday_closed(self):
        engine = SessionEngine()
        self.assertEqual(engine.current_phase(_dt(10, 0, weekday=5)), PHASE_CLOSED)

    def test_sunday_closed(self):
        engine = SessionEngine()
        self.assertEqual(engine.current_phase(_dt(10, 0, weekday=6)), PHASE_CLOSED)

    def test_friday_active(self):
        engine = SessionEngine()
        self.assertEqual(engine.current_phase(_dt(10, 0, weekday=4)), PHASE_ACTIVE)

    def test_monday_active(self):
        engine = SessionEngine()
        self.assertEqual(engine.current_phase(_dt(10, 0, weekday=0)), PHASE_ACTIVE)


class TestBooleanQueries(unittest.TestCase):

    def test_is_active_only_in_active(self):
        engine = SessionEngine()
        self.assertFalse(engine.is_active(_dt(9, 15)))
        self.assertTrue(engine.is_active(_dt(10, 0)))
        self.assertFalse(engine.is_active(_dt(14, 50)))
        self.assertFalse(engine.is_active(_dt(8, 0)))

    def test_is_warmup_only_in_warmup(self):
        engine = SessionEngine()
        self.assertTrue(engine.is_warmup(_dt(9, 15)))
        self.assertTrue(engine.is_warmup(_dt(9, 19)))
        self.assertFalse(engine.is_warmup(_dt(9, 20)))
        self.assertFalse(engine.is_warmup(_dt(10, 0)))

    def test_should_compute_spreads(self):
        engine = SessionEngine()
        self.assertFalse(engine.should_compute_spreads(_dt(8, 0)))
        self.assertTrue(engine.should_compute_spreads(_dt(9, 15)))
        self.assertTrue(engine.should_compute_spreads(_dt(10, 0)))
        self.assertTrue(engine.should_compute_spreads(_dt(14, 50)))
        self.assertFalse(engine.should_compute_spreads(_dt(15, 0)))

    def test_should_fire_alerts_only_active(self):
        engine = SessionEngine()
        self.assertFalse(engine.should_fire_alerts(_dt(9, 15)))
        self.assertTrue(engine.should_fire_alerts(_dt(10, 0)))
        self.assertFalse(engine.should_fire_alerts(_dt(14, 50)))
        self.assertFalse(engine.should_fire_alerts(_dt(8, 0)))

    def test_is_market_day(self):
        engine = SessionEngine()
        self.assertTrue(engine.is_market_day(_dt(10, 0, weekday=0)))
        self.assertTrue(engine.is_market_day(_dt(10, 0, weekday=4)))
        self.assertFalse(engine.is_market_day(_dt(10, 0, weekday=5)))
        self.assertFalse(engine.is_market_day(_dt(10, 0, weekday=6)))


class TestRecordAlert(unittest.TestCase):

    def test_record_single_alert(self):
        engine = SessionEngine()
        alert = Alert(
            stock="RELIANCE", timestamp="2026-10-05 10:00:00.000",
            spread=1.0, discount_pct=83.87, threshold=35,
            trigger_count=1, initial_spread=6.20,
            current_fut_ltp=2850.0, next_fut_ltp=2851.0,
        )
        engine.record_alert(alert)
        summary = engine.session_summary()
        self.assertEqual(summary["alerts_fired"], 1)
        self.assertIn("RELIANCE", summary["stocks_triggered"])
        self.assertEqual(summary["first_alert_time"], "2026-10-05 10:00:00.000")
        self.assertEqual(summary["last_alert_time"], "2026-10-05 10:00:00.000")

    def test_record_multiple_alerts_same_stock(self):
        engine = SessionEngine()
        for i in range(3):
            alert = Alert(
                stock="RELIANCE", timestamp=f"2026-10-05 10:{i:02d}:00.000",
                spread=1.0, discount_pct=83.87, threshold=35,
                trigger_count=i + 1, initial_spread=6.20,
                current_fut_ltp=2850.0, next_fut_ltp=2851.0,
            )
            engine.record_alert(alert)
        summary = engine.session_summary()
        self.assertEqual(summary["alerts_fired"], 3)
        self.assertEqual(summary["stocks_triggered_count"], 1)

    def test_record_alerts_multiple_stocks(self):
        engine = SessionEngine()
        for sym in ["RELIANCE", "TCS", "HDFCBANK"]:
            alert = Alert(
                stock=sym, timestamp="2026-10-05 10:00:00.000",
                spread=1.0, discount_pct=83.87, threshold=35,
                trigger_count=1, initial_spread=6.20,
                current_fut_ltp=2850.0, next_fut_ltp=2851.0,
            )
            engine.record_alert(alert)
        summary = engine.session_summary()
        self.assertEqual(summary["alerts_fired"], 3)
        self.assertEqual(summary["stocks_triggered_count"], 3)
        self.assertIn("RELIANCE", summary["stocks_triggered"])
        self.assertIn("TCS", summary["stocks_triggered"])
        self.assertIn("HDFCBANK", summary["stocks_triggered"])


class TestSessionSummary(unittest.TestCase):

    def test_empty_session_summary(self):
        engine = SessionEngine()
        summary = engine.session_summary()
        self.assertEqual(summary["alerts_fired"], 0)
        self.assertEqual(summary["stocks_triggered"], [])
        self.assertEqual(summary["stocks_triggered_count"], 0)
        self.assertIsNone(summary["first_alert_time"])
        self.assertIsNone(summary["last_alert_time"])

    def test_summary_has_phase_after_query(self):
        engine = SessionEngine()
        engine.current_phase(_dt(10, 0))
        summary = engine.session_summary()
        self.assertEqual(summary["current_phase"], PHASE_ACTIVE)

    def test_summary_phase_transitions_recorded(self):
        engine = SessionEngine()
        engine.current_phase(_dt(9, 15))
        engine.current_phase(_dt(9, 20))
        engine.current_phase(_dt(14, 45))
        summary = engine.session_summary()
        transitions = summary["phase_transitions"]
        self.assertEqual(len(transitions), 3)
        self.assertEqual(transitions[0]["to"], PHASE_WARMUP)
        self.assertEqual(transitions[1]["to"], PHASE_ACTIVE)
        self.assertEqual(transitions[2]["to"], PHASE_CLOSING)

    def test_summary_returns_copies(self):
        engine = SessionEngine()
        alert = Alert(
            stock="RELIANCE", timestamp="2026-10-05 10:00:00.000",
            spread=1.0, discount_pct=83.87, threshold=35,
            trigger_count=1, initial_spread=6.20,
            current_fut_ltp=2850.0, next_fut_ltp=2851.0,
        )
        engine.record_alert(alert)
        s1 = engine.session_summary()
        s2 = engine.session_summary()
        self.assertIsNot(s1["stocks_triggered"], s2["stocks_triggered"])
        self.assertIsNot(s1["phase_transitions"], s2["phase_transitions"])


class TestReset(unittest.TestCase):

    def test_reset_clears_everything(self):
        engine = SessionEngine()
        engine.current_phase(_dt(10, 0))
        alert = Alert(
            stock="RELIANCE", timestamp="2026-10-05 10:00:00.000",
            spread=1.0, discount_pct=83.87, threshold=35,
            trigger_count=1, initial_spread=6.20,
            current_fut_ltp=2850.0, next_fut_ltp=2851.0,
        )
        engine.record_alert(alert)

        engine.reset()
        summary = engine.session_summary()
        self.assertEqual(summary["alerts_fired"], 0)
        self.assertEqual(summary["stocks_triggered"], [])
        self.assertIsNone(summary["first_alert_time"])
        self.assertIsNone(summary["last_alert_time"])
        self.assertEqual(summary["phase_transitions"], [])
        self.assertIsNone(summary["current_phase"])

    def test_after_reset_phase_tracking_resumes(self):
        engine = SessionEngine()
        engine.current_phase(_dt(10, 0))
        engine.reset()
        phase = engine.current_phase(_dt(10, 0))
        self.assertEqual(phase, PHASE_ACTIVE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
