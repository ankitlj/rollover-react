"""
Step 7 tests — AlgoOrchestrator integration.

Tests the full pipeline: bridge → validator → spread → alerts → session.
"""

import unittest
import time
import threading
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from algo_engine.config import (
    STOCK_CONFIG, INITIAL_SPREADS, IST, SAMPLE_INTERVAL_SECONDS,
)
from algo_engine.bridge import TickBridge, Tick
from algo_engine.validator import TickValidator
from algo_engine.spread import SpreadEngine, SpreadSnapshot
from algo_engine.alerts import AlertEngine, Alert
from algo_engine.session import SessionEngine, PHASE_ACTIVE, PHASE_WAITING, PHASE_WARMUP, PHASE_CLOSED
from algo_engine.orchestrator import AlgoOrchestrator

MONDAY = datetime(2026, 10, 6, tzinfo=IST)


def _ts(h, m, s=0, ms=0):
    return f"2026-10-06 {h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _fake_now(h, m, s=0):
    return MONDAY.replace(hour=h, minute=m, second=s)


def _fresh_ts():
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _setup_bridge_with_stock(stock, cur_ltp=100.0, nxt_ltp=106.0):
    bridge = TickBridge()
    bridge.inject_metadata(
        tokens={
            "1001": {"sym": stock, "type": "future", "month": "current"},
            "1002": {"sym": stock, "type": "future", "month": "next"},
            "1003": {"sym": stock, "type": "cash"},
        },
        stocks=[stock],
    )
    bridge.inject_tick(1001, cur_ltp, _fresh_ts())
    bridge.inject_tick(1002, nxt_ltp, _fresh_ts())
    return bridge


def _patched_session(fake_dt):
    session = SessionEngine()
    session.current_phase(fake_dt)
    return session


def _make_orchestrator(bridge=None, on_alert=None, fake_now=None):
    bridge = bridge or TickBridge()
    validator = TickValidator()
    spread = SpreadEngine(bridge, INITIAL_SPREADS)
    alerts = AlertEngine()
    session = SessionEngine()

    if fake_now is not None:
        session.current_phase(fake_now)

    orch = AlgoOrchestrator(
        bridge=bridge,
        validator=validator,
        spread=spread,
        alerts=alerts,
        session=session,
        on_alert=on_alert,
    )
    return orch, bridge, validator, spread, alerts, session


def _run_cycle_at(orch, session, fake_dt):
    with patch("algo_engine.session.datetime") as mock_dt:
        mock_dt.now.return_value = fake_dt
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        orch.cycle()


class TestOrchestratorBasic(unittest.TestCase):

    def test_creates_without_error(self):
        orch, *_ = _make_orchestrator()
        self.assertIsNotNone(orch)

    def test_initial_status(self):
        orch, *_ = _make_orchestrator()
        st = orch.status()
        self.assertEqual(st["cycle_count"], 0)
        self.assertEqual(st["alerts_fired"], 0)
        self.assertEqual(st["stocks_computed"], 0)
        self.assertEqual(st["stocks_skipped"], 0)

    def test_cycle_outside_session_does_nothing(self):
        stock = "RELIANCE"
        bridge = _setup_bridge_with_stock(stock)
        orch, b, v, s, a, session = _make_orchestrator(bridge=bridge)
        waiting_time = _fake_now(8, 0)
        _run_cycle_at(orch, session, waiting_time)
        st = orch.status()
        self.assertEqual(st["cycle_count"], 1)
        self.assertEqual(st["stocks_computed"], 0)

    def test_cycle_during_warmup_computes_but_no_alerts(self):
        stock = "RELIANCE"
        bridge = _setup_bridge_with_stock(stock, cur_ltp=100.0, nxt_ltp=106.0)
        orch, b, v, s, a, session = _make_orchestrator(bridge=bridge)
        _run_cycle_at(orch, session, _fake_now(9, 17))
        st = orch.status()
        self.assertGreaterEqual(st["stocks_computed"], 1)
        self.assertEqual(st["alerts_fired"], 0)


class TestOrchestratorFullPipeline(unittest.TestCase):

    def _inject_alert_ticks(self, bridge, stock):
        initial = INITIAL_SPREADS[stock]
        threshold = STOCK_CONFIG[stock]["threshold"]
        needed_spread = initial * (1 - threshold / 100.0)
        bridge.inject_tick(1001, 100.0, _fresh_ts())
        bridge.inject_tick(1002, 100.0 + needed_spread - 0.01, _fresh_ts())

    def test_full_pipeline_fires_alert(self):
        stock = "RELIANCE"
        bridge = _setup_bridge_with_stock(stock, cur_ltp=100.0, nxt_ltp=106.0)

        alerts_received = []
        orch, b, v, s, a, session = _make_orchestrator(bridge=bridge, on_alert=lambda al: alerts_received.append(al))

        self._inject_alert_ticks(bridge, stock)
        _run_cycle_at(orch, session, _fake_now(10, 0))

        self.assertEqual(len(alerts_received), 1)
        self.assertEqual(alerts_received[0].stock, stock)
        threshold = STOCK_CONFIG[stock]["threshold"]
        self.assertGreaterEqual(alerts_received[0].discount_pct, threshold)

    def test_no_alert_below_threshold(self):
        stock = "RELIANCE"
        bridge = _setup_bridge_with_stock(stock, cur_ltp=100.0, nxt_ltp=106.0)

        alerts_received = []
        orch, b, v, s, a, session = _make_orchestrator(bridge=bridge, on_alert=lambda al: alerts_received.append(al))

        _run_cycle_at(orch, session, _fake_now(10, 0))
        self.assertEqual(len(alerts_received), 0)

    def test_negative_initial_spread_skipped(self):
        stock = "ASTRAL"
        bridge = _setup_bridge_with_stock(stock)
        orch, b, v, s, a, session = _make_orchestrator(bridge=bridge)
        _run_cycle_at(orch, session, _fake_now(10, 0))
        st = orch.status()
        self.assertEqual(st["stocks_computed"], 0)


class TestOrchestratorValidatorBlocking(unittest.TestCase):

    def test_zero_ltp_rejected(self):
        stock = "RELIANCE"
        bridge = _setup_bridge_with_stock(stock, cur_ltp=0.0, nxt_ltp=106.0)
        orch, b, v, s, a, session = _make_orchestrator(bridge=bridge)
        _run_cycle_at(orch, session, _fake_now(10, 0))
        st = orch.status()
        self.assertEqual(st["stocks_computed"], 0)

    def test_backward_timestamp_rejected(self):
        stock = "RELIANCE"
        bridge = TickBridge()
        bridge.inject_metadata(
            tokens={
                "1001": {"sym": stock, "type": "future", "month": "current"},
                "1002": {"sym": stock, "type": "future", "month": "next"},
            },
            stocks=[stock],
        )
        bridge.inject_tick(1001, 100.0, _fresh_ts())
        bridge.inject_tick(1002, 106.0, _fresh_ts())

        orch, b, validator, s, a, session = _make_orchestrator(bridge=bridge)

        validator.check(Tick(token=1002, ltp=106.0, ts=_ts(10, 5, 0), recv_mono_ns=time.monotonic_ns()))
        bridge.inject_tick(1002, 105.0, _ts(10, 3, 0))

        _run_cycle_at(orch, session, _fake_now(10, 10))
        st = orch.status()
        self.assertEqual(st["stocks_computed"], 0)


class TestOrchestratorMultipleStocks(unittest.TestCase):

    def test_multiple_stocks_computed(self):
        bridge = TickBridge()
        bridge.inject_metadata(
            tokens={
                "2001": {"sym": "RELIANCE", "type": "future", "month": "current"},
                "2002": {"sym": "RELIANCE", "type": "future", "month": "next"},
                "3001": {"sym": "INFOSYS", "type": "future", "month": "current"},
                "3002": {"sym": "INFOSYS", "type": "future", "month": "next"},
            },
            stocks=["RELIANCE", "INFOSYS"],
        )
        bridge.inject_tick(2001, 100.0, _fresh_ts())
        bridge.inject_tick(2002, 106.0, _fresh_ts())
        bridge.inject_tick(3001, 200.0, _fresh_ts())
        bridge.inject_tick(3002, 205.0, _fresh_ts())

        orch, b, v, s, a, session = _make_orchestrator(bridge=bridge)
        _run_cycle_at(orch, session, _fake_now(10, 0))
        st = orch.status()
        self.assertGreaterEqual(st["stocks_computed"], 2)


class TestOrchestratorSessionGating(unittest.TestCase):

    def test_waiting_phase_no_computation(self):
        stock = "RELIANCE"
        bridge = _setup_bridge_with_stock(stock)
        orch, b, v, s, a, session = _make_orchestrator(bridge=bridge)
        _run_cycle_at(orch, session, _fake_now(8, 0))
        self.assertEqual(orch.status()["stocks_computed"], 0)

    def test_closed_phase_no_computation(self):
        stock = "RELIANCE"
        bridge = _setup_bridge_with_stock(stock)
        orch, b, v, s, a, session = _make_orchestrator(bridge=bridge)
        _run_cycle_at(orch, session, _fake_now(16, 0))
        self.assertEqual(orch.status()["stocks_computed"], 0)

    def test_warmup_computes_no_alerts(self):
        stock = "RELIANCE"
        bridge = _setup_bridge_with_stock(stock, cur_ltp=100.0, nxt_ltp=106.0)

        alerts_received = []
        orch, b, v, s, a, session = _make_orchestrator(bridge=bridge, on_alert=lambda al: alerts_received.append(al))

        initial = INITIAL_SPREADS[stock]
        threshold = STOCK_CONFIG[stock]["threshold"]
        needed_spread = initial * (1 - threshold / 100.0)
        bridge.inject_tick(1001, 100.0, _fresh_ts())
        bridge.inject_tick(1002, 100.0 + needed_spread - 0.01, _fresh_ts())

        _run_cycle_at(orch, session, _fake_now(9, 17))
        self.assertEqual(len(alerts_received), 0)
        self.assertGreaterEqual(orch.status()["stocks_computed"], 1)

    def test_active_phase_fires_alerts(self):
        stock = "RELIANCE"
        bridge = _setup_bridge_with_stock(stock, cur_ltp=100.0, nxt_ltp=106.0)

        alerts_received = []
        orch, b, v, s, a, session = _make_orchestrator(bridge=bridge, on_alert=lambda al: alerts_received.append(al))

        initial = INITIAL_SPREADS[stock]
        threshold = STOCK_CONFIG[stock]["threshold"]
        needed_spread = initial * (1 - threshold / 100.0)
        bridge.inject_tick(1001, 100.0, _fresh_ts())
        bridge.inject_tick(1002, 100.0 + needed_spread - 0.01, _fresh_ts())

        _run_cycle_at(orch, session, _fake_now(10, 0))
        self.assertEqual(len(alerts_received), 1)


class TestOrchestratorStartStop(unittest.TestCase):

    def test_start_stop(self):
        orch, *_ = _make_orchestrator()
        orch.start()
        time.sleep(0.1)
        orch.stop()

    def test_double_start_is_safe(self):
        orch, *_ = _make_orchestrator()
        orch.start()
        orch.start()
        orch.stop()

    def test_double_stop_is_safe(self):
        orch, *_ = _make_orchestrator()
        orch.start()
        orch.stop()
        orch.stop()


class TestOrchestratorReset(unittest.TestCase):

    def test_reset_clears_counters(self):
        stock = "RELIANCE"
        bridge = _setup_bridge_with_stock(stock)
        orch, b, v, s, a, session = _make_orchestrator(bridge=bridge)
        _run_cycle_at(orch, session, _fake_now(10, 0))
        orch.reset()
        st = orch.status()
        self.assertEqual(st["cycle_count"], 0)
        self.assertEqual(st["alerts_fired"], 0)
        self.assertEqual(st["stocks_computed"], 0)
        self.assertEqual(st["stocks_skipped"], 0)


class TestOrchestratorRunOnce(unittest.TestCase):

    def test_run_once_single_cycle(self):
        stock = "RELIANCE"
        bridge = _setup_bridge_with_stock(stock)
        orch, b, v, s, a, session = _make_orchestrator(bridge=bridge)
        _run_cycle_at(orch, session, _fake_now(10, 0))
        self.assertEqual(orch.status()["cycle_count"], 1)


class TestOrchestratorOnAlertCallback(unittest.TestCase):

    def _inject_alert_ticks(self, bridge, stock):
        initial = INITIAL_SPREADS[stock]
        threshold = STOCK_CONFIG[stock]["threshold"]
        needed = initial * (1 - threshold / 100.0)
        bridge.inject_tick(1001, 100.0, _fresh_ts())
        bridge.inject_tick(1002, 100.0 + needed - 0.01, _fresh_ts())

    def test_callback_receives_alert(self):
        stock = "RELIANCE"
        bridge = _setup_bridge_with_stock(stock, cur_ltp=100.0, nxt_ltp=106.0)

        received = []
        orch, b, v, s, a, session = _make_orchestrator(bridge=bridge, on_alert=lambda al: received.append(al))

        self._inject_alert_ticks(bridge, stock)
        _run_cycle_at(orch, session, _fake_now(10, 0))
        self.assertEqual(len(received), 1)
        self.assertIsInstance(received[0], Alert)

    def test_callback_exception_doesnt_crash(self):
        stock = "RELIANCE"
        bridge = _setup_bridge_with_stock(stock, cur_ltp=100.0, nxt_ltp=106.0)

        def bad_callback(alert):
            raise RuntimeError("boom")

        orch, b, v, s, a, session = _make_orchestrator(bridge=bridge, on_alert=bad_callback)

        initial = INITIAL_SPREADS[stock]
        threshold = STOCK_CONFIG[stock]["threshold"]
        needed = initial * (1 - threshold / 100.0)
        bridge.inject_tick(1001, 100.0, _fresh_ts())
        bridge.inject_tick(1002, 100.0 + needed - 0.01, _fresh_ts())

        _run_cycle_at(orch, session, _fake_now(10, 0))
        self.assertEqual(orch.status()["alerts_fired"], 1)

    def test_no_callback_is_safe(self):
        stock = "RELIANCE"
        bridge = _setup_bridge_with_stock(stock, cur_ltp=100.0, nxt_ltp=106.0)
        orch, b, v, s, a, session = _make_orchestrator(bridge=bridge, on_alert=None)

        initial = INITIAL_SPREADS[stock]
        threshold = STOCK_CONFIG[stock]["threshold"]
        needed = initial * (1 - threshold / 100.0)
        bridge.inject_tick(1001, 100.0, _fresh_ts())
        bridge.inject_tick(1002, 100.0 + needed - 0.01, _fresh_ts())

        _run_cycle_at(orch, session, _fake_now(10, 0))
        self.assertEqual(orch.status()["alerts_fired"], 1)


class TestOrchestratorStatusDict(unittest.TestCase):

    def test_status_has_all_keys(self):
        orch, *_ = _make_orchestrator()
        st = orch.status()
        expected_keys = {
            "cycle_count", "alerts_fired", "stocks_computed", "stocks_skipped",
            "phase", "session_summary", "spread_skip_reasons",
            "validator_rejected", "validator_passed",
        }
        self.assertEqual(set(st.keys()), expected_keys)

    def test_status_reflects_work(self):
        stock = "RELIANCE"
        bridge = _setup_bridge_with_stock(stock)
        orch, b, v, s, a, session = _make_orchestrator(bridge=bridge)
        _run_cycle_at(orch, session, _fake_now(10, 0))
        st = orch.status()
        self.assertEqual(st["cycle_count"], 1)
        self.assertIsNotNone(st["phase"])
        self.assertIsInstance(st["session_summary"], dict)
        self.assertIsInstance(st["spread_skip_reasons"], dict)


if __name__ == "__main__":
    unittest.main()
