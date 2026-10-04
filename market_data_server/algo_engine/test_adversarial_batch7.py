import sys
import unittest
import threading
from datetime import datetime

sys.path.insert(0, r"C:\Users\Ankit\Desktop\RS FOLDER\rollover-react\market_data_server")

from algo_engine.config import IST
from algo_engine.session import (
    SessionEngine,
    PHASE_WAITING, PHASE_WARMUP, PHASE_ACTIVE, PHASE_CLOSING, PHASE_CLOSED,
)
from algo_engine.alerts import Alert as RealAlert


def _dt(hour, minute, second=0, weekday=0):
    return datetime(2026, 10, 5 + weekday, hour, minute, second, tzinfo=IST)


def _make_alert(stock="RELIANCE", ts="2026-10-05 10:00:00.000"):
    return RealAlert(
        stock=stock, timestamp=ts,
        spread=1.0, discount_pct=83.87, threshold=35,
        trigger_count=1, initial_spread=6.20,
        current_fut_ltp=2850.0, next_fut_ltp=2851.0,
    )


class TestExactBoundaryTimes(unittest.TestCase):

    def test_exactly_915_is_warmup(self):
        engine = SessionEngine()
        self.assertEqual(engine.current_phase(_dt(9, 15, 0)), PHASE_WARMUP)

    def test_exactly_920_is_active(self):
        engine = SessionEngine()
        self.assertEqual(engine.current_phase(_dt(9, 20, 0)), PHASE_ACTIVE)

    def test_exactly_1445_is_closing(self):
        engine = SessionEngine()
        self.assertEqual(engine.current_phase(_dt(14, 45, 0)), PHASE_CLOSING)

    def test_exactly_1500_is_closed(self):
        engine = SessionEngine()
        self.assertEqual(engine.current_phase(_dt(15, 0, 0)), PHASE_CLOSED)

    def test_one_second_before_920_is_warmup(self):
        engine = SessionEngine()
        self.assertEqual(engine.current_phase(_dt(9, 19, 59)), PHASE_WARMUP)

    def test_one_second_before_1445_is_active(self):
        engine = SessionEngine()
        self.assertEqual(engine.current_phase(_dt(14, 44, 59)), PHASE_ACTIVE)

    def test_one_second_before_1500_is_closing(self):
        engine = SessionEngine()
        self.assertEqual(engine.current_phase(_dt(14, 59, 59)), PHASE_CLOSING)


class TestRapidPhaseQueries(unittest.TestCase):

    def test_1000_rapid_queries_no_crash(self):
        engine = SessionEngine()
        t = _dt(10, 0)
        for _ in range(1000):
            phase = engine.current_phase(t)
            self.assertEqual(phase, PHASE_ACTIVE)

    def test_rapid_queries_dont_duplicate_transitions(self):
        engine = SessionEngine()
        t = _dt(10, 0)
        for _ in range(100):
            engine.current_phase(t)
        summary = engine.session_summary()
        self.assertEqual(len(summary["phase_transitions"]), 1)


class TestConcurrentAccess(unittest.TestCase):

    def test_concurrent_phase_queries(self):
        engine = SessionEngine()
        errors = []

        def worker():
            try:
                for _ in range(200):
                    engine.current_phase(_dt(10, 0))
                    engine.is_active(_dt(10, 0))
                    engine.should_fire_alerts(_dt(10, 0))
                    engine.session_summary()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(errors, [])

    def test_concurrent_record_alert_and_summary(self):
        engine = SessionEngine()
        errors = []

        def writer():
            try:
                for i in range(200):
                    alert = _make_alert(stock=f"STOCK{i % 19}")
                    engine.record_alert(alert)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(200):
                    engine.session_summary()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)
        self.assertEqual(errors, [])

    def test_concurrent_record_and_reset(self):
        engine = SessionEngine()
        errors = []

        def writer():
            try:
                for i in range(100):
                    alert = _make_alert()
                    engine.record_alert(alert)
            except Exception as e:
                errors.append(e)

        def resetter():
            try:
                for _ in range(10):
                    engine.reset()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=resetter)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)
        self.assertEqual(errors, [])


class TestEmptyState(unittest.TestCase):

    def test_summary_before_any_phase_query(self):
        engine = SessionEngine()
        summary = engine.session_summary()
        self.assertIsNone(summary["current_phase"])
        self.assertIsNone(summary["session_start_time"])
        self.assertEqual(summary["alerts_fired"], 0)

    def test_summary_before_any_alerts(self):
        engine = SessionEngine()
        engine.current_phase(_dt(10, 0))
        summary = engine.session_summary()
        self.assertEqual(summary["alerts_fired"], 0)
        self.assertEqual(summary["stocks_triggered_count"], 0)
        self.assertIsNone(summary["first_alert_time"])
        self.assertIsNone(summary["last_alert_time"])


class TestPhaseTransitionTracking(unittest.TestCase):

    def test_full_day_transitions(self):
        engine = SessionEngine()
        engine.current_phase(_dt(8, 0))
        engine.current_phase(_dt(9, 15))
        engine.current_phase(_dt(9, 20))
        engine.current_phase(_dt(14, 45))
        engine.current_phase(_dt(15, 0))

        summary = engine.session_summary()
        transitions = summary["phase_transitions"]
        phases = [t["to"] for t in transitions]
        self.assertEqual(phases, [PHASE_WAITING, PHASE_WARMUP, PHASE_ACTIVE, PHASE_CLOSING, PHASE_CLOSED])

    def test_transition_has_from_field(self):
        engine = SessionEngine()
        engine.current_phase(_dt(9, 15))
        engine.current_phase(_dt(9, 20))
        summary = engine.session_summary()
        transitions = summary["phase_transitions"]
        self.assertEqual(transitions[0]["from"], None)
        self.assertEqual(transitions[0]["to"], PHASE_WARMUP)
        self.assertEqual(transitions[1]["from"], PHASE_WARMUP)
        self.assertEqual(transitions[1]["to"], PHASE_ACTIVE)

    def test_transition_has_timestamp(self):
        engine = SessionEngine()
        engine.current_phase(_dt(10, 0))
        summary = engine.session_summary()
        self.assertIn("timestamp", summary["phase_transitions"][0])
        self.assertTrue(len(summary["phase_transitions"][0]["timestamp"]) > 0)


class TestWeekendEdgeCases(unittest.TestCase):

    def test_weekend_no_compute(self):
        engine = SessionEngine()
        self.assertFalse(engine.should_compute_spreads(_dt(10, 0, weekday=5)))
        self.assertFalse(engine.should_compute_spreads(_dt(10, 0, weekday=6)))

    def test_weekend_no_alerts(self):
        engine = SessionEngine()
        self.assertFalse(engine.should_fire_alerts(_dt(10, 0, weekday=5)))

    def test_weekend_is_not_market_day(self):
        engine = SessionEngine()
        self.assertFalse(engine.is_market_day(_dt(10, 0, weekday=5)))
        self.assertFalse(engine.is_market_day(_dt(10, 0, weekday=6)))


class TestSessionDuration(unittest.TestCase):

    def test_duration_zero_before_first_query(self):
        engine = SessionEngine()
        summary = engine.session_summary()
        self.assertEqual(summary["session_duration_seconds"], 0.0)

    def test_duration_positive_after_first_query(self):
        engine = SessionEngine()
        engine.current_phase(_dt(9, 20, weekday=-4))
        summary = engine.session_summary()
        self.assertGreater(summary["session_duration_seconds"], 0)


class TestResetMidSession(unittest.TestCase):

    def test_reset_then_continue(self):
        engine = SessionEngine()
        engine.current_phase(_dt(10, 0))
        alert = _make_alert()
        engine.record_alert(alert)
        self.assertEqual(engine.session_summary()["alerts_fired"], 1)

        engine.reset()
        self.assertEqual(engine.session_summary()["alerts_fired"], 0)

        alert2 = _make_alert(stock="TCS")
        engine.record_alert(alert2)
        self.assertEqual(engine.session_summary()["alerts_fired"], 1)
        self.assertIn("TCS", engine.session_summary()["stocks_triggered"])
        self.assertNotIn("RELIANCE", engine.session_summary()["stocks_triggered"])


class TestAll19Stocks(unittest.TestCase):

    def test_all_stocks_can_trigger(self):
        from algo_engine.config import STOCK_CONFIG
        engine = SessionEngine()
        for sym in STOCK_CONFIG:
            alert = _make_alert(stock=sym)
            engine.record_alert(alert)
        summary = engine.session_summary()
        self.assertEqual(summary["stocks_triggered_count"], 19)
        self.assertEqual(summary["alerts_fired"], 19)


if __name__ == "__main__":
    unittest.main(verbosity=2)
