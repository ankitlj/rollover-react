"""
Tests for algo_engine/algo_reporter.py
"""

import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime

from algo_engine.algo_reporter import AlgoReporter
from algo_engine.alerts import Alert
from algo_engine.config import IST


def _make_alert(stock="RELIANCE", discount_pct=40.0, threshold=35, spread=3.5,
                trigger_count=1, timestamp="2026-10-06 10:30:00.000"):
    return Alert(
        stock=stock,
        timestamp=timestamp,
        spread=spread,
        discount_pct=discount_pct,
        threshold=threshold,
        trigger_count=trigger_count,
        initial_spread=6.20,
        current_fut_ltp=100.0,
        next_fut_ltp=103.5,
    )


def _make_mock_orchestrator(phase="ACTIVE", cycle_count=100, alerts_fired=5,
                            stocks_computed=500, stocks_skipped=50,
                            validator_rejected=10, validator_passed=1000,
                            spread_skip_reasons=None):
    orch = MagicMock()
    orch.status.return_value = {
        "cycle_count": cycle_count,
        "alerts_fired": alerts_fired,
        "stocks_computed": stocks_computed,
        "stocks_skipped": stocks_skipped,
        "phase": phase,
        "session_summary": {},
        "spread_skip_reasons": spread_skip_reasons or {},
        "validator_rejected": validator_rejected,
        "validator_passed": validator_passed,
    }
    return orch


def _make_mock_bridge(connected=True, tick_count=5000):
    bridge = MagicMock()
    bridge.connected = connected
    bridge.tick_count = tick_count
    return bridge


class TestAlgoReporterBasic(unittest.TestCase):

    def test_creates_without_error(self):
        orch = _make_mock_orchestrator()
        bridge = _make_mock_bridge()
        reporter = AlgoReporter(orch, bridge)
        self.assertIsNotNone(reporter)

    def test_start_stop(self):
        orch = _make_mock_orchestrator()
        bridge = _make_mock_bridge()
        reporter = AlgoReporter(orch, bridge)
        reporter.start()
        reporter.stop()
        self.assertIsNotNone(reporter._start_time)
        self.assertIsNotNone(reporter._end_time)


class TestAlgoReporterAlerts(unittest.TestCase):

    def test_record_single_alert(self):
        orch = _make_mock_orchestrator()
        bridge = _make_mock_bridge()
        reporter = AlgoReporter(orch, bridge)
        
        alert = _make_alert()
        reporter.record_alert(alert)
        
        self.assertEqual(len(reporter._alerts), 1)
        self.assertEqual(reporter._alerts[0]["stock"], "RELIANCE")
        self.assertEqual(reporter._alerts[0]["discount_pct"], 40.0)

    def test_record_multiple_alerts(self):
        orch = _make_mock_orchestrator()
        bridge = _make_mock_bridge()
        reporter = AlgoReporter(orch, bridge)
        
        reporter.record_alert(_make_alert(stock="RELIANCE"))
        reporter.record_alert(_make_alert(stock="INFOSYS"))
        reporter.record_alert(_make_alert(stock="RELIANCE"))
        
        self.assertEqual(len(reporter._alerts), 3)
        self.assertEqual(len(reporter._alerts_by_stock["RELIANCE"]), 2)
        self.assertEqual(len(reporter._alerts_by_stock["INFOSYS"]), 1)

    def test_alert_details_preserved(self):
        orch = _make_mock_orchestrator()
        bridge = _make_mock_bridge()
        reporter = AlgoReporter(orch, bridge)
        
        alert = _make_alert(
            stock="TCS",
            discount_pct=45.5,
            threshold=40,
            spread=5.5,
            trigger_count=3,
            timestamp="2026-10-06 14:20:30.123",
        )
        reporter.record_alert(alert)
        
        stored = reporter._alerts[0]
        self.assertEqual(stored["stock"], "TCS")
        self.assertEqual(stored["discount_pct"], 45.5)
        self.assertEqual(stored["threshold"], 40)
        self.assertEqual(stored["spread"], 5.5)
        self.assertEqual(stored["trigger_count"], 3)
        self.assertEqual(stored["timestamp"], "2026-10-06 14:20:30.123")


class TestAlgoReporterErrors(unittest.TestCase):

    def test_record_error(self):
        orch = _make_mock_orchestrator()
        bridge = _make_mock_bridge()
        reporter = AlgoReporter(orch, bridge)
        
        reporter.record_error("test error", "test context")
        
        self.assertEqual(len(reporter._errors), 1)
        self.assertEqual(reporter._errors[0]["error"], "test error")
        self.assertEqual(reporter._errors[0]["context"], "test context")


class TestAlgoReporterVerdict(unittest.TestCase):

    def test_healthy_verdict(self):
        orch = _make_mock_orchestrator()
        bridge = _make_mock_bridge(connected=True, tick_count=5000)
        reporter = AlgoReporter(orch, bridge)
        reporter._bridge_connect_events = [{"time": "09:15:00"}]
        
        verdict, issues = reporter._compute_verdict()
        self.assertEqual(verdict, "HEALTHY")
        self.assertEqual(len(issues), 0)

    def test_degraded_verdict_few_disconnects(self):
        orch = _make_mock_orchestrator()
        bridge = _make_mock_bridge()
        reporter = AlgoReporter(orch, bridge)
        reporter._bridge_disconnect_events = [{"time": f"10:{i:02d}:00"} for i in range(6)]
        
        verdict, issues = reporter._compute_verdict()
        self.assertEqual(verdict, "DEGRADED")
        self.assertTrue(any("disconnected" in i for i in issues))

    def test_failed_verdict_never_connected(self):
        orch = _make_mock_orchestrator(validator_rejected=150)
        bridge = _make_mock_bridge(connected=False, tick_count=0)
        reporter = AlgoReporter(orch, bridge)
        reporter._snapshots = [{"time": "10:00:00", "phase": "ACTIVE"}]
        reporter._errors = [{"time": f"10:{i:02d}:00", "error": f"error{i}", "context": ""} for i in range(11)]
        
        verdict, issues = reporter._compute_verdict()
        self.assertEqual(verdict, "FAILED")
        self.assertTrue(any("never connected" in i for i in issues))

    def test_failed_verdict_no_alerts_during_active(self):
        orch = _make_mock_orchestrator(phase="ACTIVE", validator_rejected=150)
        bridge = _make_mock_bridge(connected=True, tick_count=5000)
        reporter = AlgoReporter(orch, bridge)
        reporter._bridge_connect_events = [{"time": "09:15:00"}]
        reporter._snapshots = [{"time": "10:00:00", "phase": "ACTIVE"}]
        reporter._errors = [{"time": f"10:{i:02d}:00", "error": f"error{i}", "context": ""} for i in range(11)]
        
        verdict, issues = reporter._compute_verdict()
        self.assertEqual(verdict, "FAILED")
        self.assertTrue(any("No alerts" in i for i in issues))

    def test_degraded_verdict_many_validator_rejections(self):
        orch = _make_mock_orchestrator(validator_rejected=150)
        bridge = _make_mock_bridge(connected=True, tick_count=5000)
        reporter = AlgoReporter(orch, bridge)
        reporter._bridge_connect_events = [{"time": "09:15:00"}]
        reporter._alerts = [_make_alert()]
        
        verdict, issues = reporter._compute_verdict()
        self.assertIn("DEGRADED", verdict)
        self.assertTrue(any("validator rejections" in i for i in issues))


class TestAlgoReporterGenerateReport(unittest.TestCase):

    def test_generate_report_contains_header(self):
        orch = _make_mock_orchestrator()
        bridge = _make_mock_bridge()
        reporter = AlgoReporter(orch, bridge)
        reporter._start_time = datetime(2026, 10, 6, 9, 0, 0, tzinfo=IST)
        reporter._end_time = datetime(2026, 10, 6, 15, 30, 0, tzinfo=IST)
        reporter.record_alert(_make_alert())
        
        with patch("pathlib.Path") as mock_path:
            mock_dir = MagicMock()
            mock_dir.mkdir = MagicMock()
            mock_path.return_value.parent.parent = mock_dir
            report_text = reporter.generate_report()
        
        self.assertIn("ALGO ENGINE DAILY REPORT", report_text)
        self.assertIn("RELIANCE", report_text)

    def test_report_contains_alert_details(self):
        orch = _make_mock_orchestrator()
        bridge = _make_mock_bridge()
        reporter = AlgoReporter(orch, bridge)
        reporter._start_time = datetime(2026, 10, 6, 9, 0, 0, tzinfo=IST)
        reporter._end_time = datetime(2026, 10, 6, 15, 30, 0, tzinfo=IST)
        
        reporter.record_alert(_make_alert(
            stock="INFOSYS",
            discount_pct=42.5,
            threshold=40,
            spread=3.1,
            trigger_count=2,
        ))
        
        with patch("pathlib.Path") as mock_path:
            mock_dir = MagicMock()
            mock_dir.mkdir = MagicMock()
            mock_path.return_value.parent.parent = mock_dir
            report_text = reporter.generate_report()
        
        self.assertIn("INFOSYS", report_text)
        self.assertIn("42.50", report_text)
        self.assertIn("40", report_text)

    def test_report_contains_verdict(self):
        orch = _make_mock_orchestrator()
        bridge = _make_mock_bridge(connected=True, tick_count=5000)
        reporter = AlgoReporter(orch, bridge)
        reporter._start_time = datetime(2026, 10, 6, 9, 0, 0, tzinfo=IST)
        reporter._end_time = datetime(2026, 10, 6, 15, 30, 0, tzinfo=IST)
        reporter._bridge_connect_events = [{"time": "09:15:00"}]
        
        with patch("pathlib.Path") as mock_path:
            mock_dir = MagicMock()
            mock_dir.mkdir = MagicMock()
            mock_path.return_value.parent.parent = mock_dir
            report_text = reporter.generate_report()
        
        self.assertIn("VERDICT: HEALTHY", report_text)


class TestAlgoReporterBridgeTracking(unittest.TestCase):

    def test_bridge_connect_tracked(self):
        orch = _make_mock_orchestrator()
        bridge = _make_mock_bridge(connected=True)
        reporter = AlgoReporter(orch, bridge)
        reporter._was_connected = False
        
        reporter._snapshot_loop = lambda: None
        reporter.start()
        
        with reporter._lock:
            reporter._bridge_connect_events.append({"time": "09:15:00"})
        
        reporter.stop()
        self.assertEqual(len(reporter._bridge_connect_events), 1)


class TestAlgoReporterPhaseTransitions(unittest.TestCase):

    def test_phase_transitions_tracked(self):
        orch = _make_mock_orchestrator()
        bridge = _make_mock_bridge()
        reporter = AlgoReporter(orch, bridge)
        
        reporter._phase_transitions.append({
            "time": "09:15:00",
            "from": "WAITING",
            "to": "WARMUP",
        })
        reporter._phase_transitions.append({
            "time": "09:20:00",
            "from": "WARMUP",
            "to": "ACTIVE",
        })
        
        self.assertEqual(len(reporter._phase_transitions), 2)
        self.assertEqual(reporter._phase_transitions[0]["from"], "WAITING")
        self.assertEqual(reporter._phase_transitions[1]["to"], "ACTIVE")


class TestAlgoReporterDurationTracking(unittest.TestCase):

    def test_alert_has_duration_fields(self):
        orch = _make_mock_orchestrator()
        bridge = _make_mock_bridge()
        reporter = AlgoReporter(orch, bridge)
        
        reporter.record_alert(_make_alert())
        
        self.assertIn("duration_seconds", reporter._alerts[0])
        self.assertIn("close_timestamp", reporter._alerts[0])
        self.assertIsNone(reporter._alerts[0]["duration_seconds"])

    def test_active_alert_tracked(self):
        orch = _make_mock_orchestrator()
        bridge = _make_mock_bridge()
        reporter = AlgoReporter(orch, bridge)
        
        reporter.record_alert(_make_alert(stock="RELIANCE"))
        
        self.assertIn("RELIANCE", reporter._active_alerts)

    def test_stop_closes_active_alerts(self):
        orch = _make_mock_orchestrator()
        bridge = _make_mock_bridge()
        reporter = AlgoReporter(orch, bridge)
        
        reporter.start()
        reporter.record_alert(_make_alert(stock="RELIANCE", timestamp="2026-10-06 10:00:00.000"))
        reporter.stop()
        
        self.assertEqual(len(reporter._active_alerts), 0)
        self.assertIsNotNone(reporter._alerts[0]["duration_seconds"])
        self.assertIsNotNone(reporter._alerts[0]["close_timestamp"])


if __name__ == "__main__":
    unittest.main()
