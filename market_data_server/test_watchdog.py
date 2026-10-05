"""
Tests for the no-data watchdog in arrow_connector.py.

Verifies:
  - Watchdog triggers full_recovery when WAITING_FOR_FRESH_BOOKS >60s with prior data
  - Watchdog triggers full_recovery when HEALTHY but no ticks >120s
  - Watchdog does NOT trigger when no prior data (tick_count=0)
  - Watchdog does NOT trigger when timers haven't expired
  - Watchdog stops cleanly on shutdown
"""

import time
import threading
import unittest
from unittest.mock import patch, MagicMock

from arrow_connector import ArrowConnector, FeedState


class TestWatchdogInit(unittest.TestCase):
    def test_watchdog_thread_starts(self):
        connector = ArrowConnector()
        self.assertIsNotNone(connector._watchdog_thread)
        self.assertTrue(connector._watchdog_thread.is_alive())
        connector._shutdown.set()

    def test_waiting_since_initially_zero(self):
        connector = ArrowConnector()
        self.assertEqual(connector._waiting_since_mono, 0.0)
        connector._shutdown.set()


class TestSetStateTracking(unittest.TestCase):
    def test_waiting_since_set_on_enter(self):
        connector = ArrowConnector()
        connector._set_state(FeedState.WAITING_FOR_FRESH_BOOKS, "test")
        self.assertGreater(connector._waiting_since_mono, 0)
        connector._shutdown.set()

    def test_waiting_since_cleared_on_exit(self):
        connector = ArrowConnector()
        connector._set_state(FeedState.WAITING_FOR_FRESH_BOOKS, "test")
        self.assertGreater(connector._waiting_since_mono, 0)
        connector._set_state(FeedState.HEALTHY, "test")
        self.assertEqual(connector._waiting_since_mono, 0.0)
        connector._shutdown.set()

    def test_waiting_since_not_set_for_other_states(self):
        connector = ArrowConnector()
        connector._set_state(FeedState.CONNECTING, "test")
        self.assertEqual(connector._waiting_since_mono, 0.0)
        connector._set_state(FeedState.DISCONNECTED, "test")
        self.assertEqual(connector._waiting_since_mono, 0.0)
        connector._shutdown.set()


class TestWatchdogWaitingForBooks(unittest.TestCase):
    @patch.object(ArrowConnector, 'full_recovery')
    def test_triggers_when_waiting_over_60s_with_prior_data(self, mock_recovery):
        connector = ArrowConnector()
        connector._set_state(FeedState.WAITING_FOR_FRESH_BOOKS, "test")
        connector._waiting_since_mono = time.monotonic() - 65
        with connector._tick_count_lock:
            connector._tick_count = 100

        connector._watchdog_check()

        mock_recovery.assert_called_once()
        connector._shutdown.set()

    @patch.object(ArrowConnector, 'full_recovery')
    def test_no_trigger_when_no_prior_data(self, mock_recovery):
        connector = ArrowConnector()
        connector._set_state(FeedState.WAITING_FOR_FRESH_BOOKS, "test")
        connector._waiting_since_mono = time.monotonic() - 65
        with connector._tick_count_lock:
            connector._tick_count = 0

        connector._watchdog_check()

        mock_recovery.assert_not_called()
        connector._shutdown.set()

    @patch.object(ArrowConnector, 'full_recovery')
    def test_no_trigger_when_under_60s(self, mock_recovery):
        connector = ArrowConnector()
        connector._set_state(FeedState.WAITING_FOR_FRESH_BOOKS, "test")
        connector._waiting_since_mono = time.monotonic() - 30
        with connector._tick_count_lock:
            connector._tick_count = 100

        connector._watchdog_check()

        mock_recovery.assert_not_called()
        connector._shutdown.set()


class TestWatchdogHealthyStale(unittest.TestCase):
    @patch.object(ArrowConnector, 'full_recovery')
    def test_triggers_when_healthy_no_ticks_over_120s(self, mock_recovery):
        connector = ArrowConnector()
        connector._set_state(FeedState.HEALTHY, "test")
        with connector._tick_count_lock:
            connector._tick_count = 100
            connector._last_tick_time = time.monotonic() - 130

        connector._watchdog_check()

        mock_recovery.assert_called_once()
        connector._shutdown.set()

    @patch.object(ArrowConnector, 'full_recovery')
    def test_no_trigger_when_healthy_recent_ticks(self, mock_recovery):
        connector = ArrowConnector()
        connector._set_state(FeedState.HEALTHY, "test")
        with connector._tick_count_lock:
            connector._tick_count = 100
            connector._last_tick_time = time.monotonic() - 10

        connector._watchdog_check()

        mock_recovery.assert_not_called()
        connector._shutdown.set()


class TestWatchdogShutdown(unittest.TestCase):
    def test_watchdog_stops_on_shutdown(self):
        connector = ArrowConnector()
        self.assertTrue(connector._watchdog_thread.is_alive())
        connector._shutdown.set()
        connector._watchdog_thread.join(timeout=3)
        self.assertFalse(connector._watchdog_thread.is_alive())

    def test_disconnect_stops_watchdog(self):
        connector = ArrowConnector()
        connector.streams = MagicMock()
        connector.disconnect()
        connector._watchdog_thread.join(timeout=3)
        self.assertFalse(connector._watchdog_thread.is_alive())


class TestWatchdogNoTriggerOnDisconnected(unittest.TestCase):
    @patch.object(ArrowConnector, 'full_recovery')
    def test_no_trigger_when_disconnected(self, mock_recovery):
        connector = ArrowConnector()
        connector._set_state(FeedState.DISCONNECTED, "test")

        connector._watchdog_check()

        mock_recovery.assert_not_called()
        connector._shutdown.set()


if __name__ == "__main__":
    unittest.main()
