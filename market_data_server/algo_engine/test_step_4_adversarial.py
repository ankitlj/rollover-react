"""
ADVERSARIAL TESTS FOR SPREAD ENGINE (Step 4)
=============================================
Critical code audit for production deployment on 2026-10-06.
These tests probe vulnerabilities, edge cases, and live deployment issues.
"""
import sys
import time
import unittest
import threading
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, r"C:\Users\Ankit\Desktop\RS FOLDER\rollover-react\market_data_server")

from algo_engine.config import (
    STOCK_CONFIG, INITIAL_SPREADS, SPREAD_FRESHNESS_SECONDS,
    SAMPLE_INTERVAL_SECONDS, IST,
)
from algo_engine.bridge import TickBridge, Tick
from algo_engine.spread import SpreadEngine, SpreadSnapshot


def _now_ist_str(offset_seconds=0):
    dt = datetime.now(IST) + timedelta(seconds=offset_seconds)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _setup_bridge_with_tokens():
    bridge = TickBridge()
    tokens = {}
    tok_id = 1
    for sym in STOCK_CONFIG:
        tokens[str(tok_id)] = {"type": "cash", "sym": sym, "tsym": f"{sym}-EQ",
                                "lot": STOCK_CONFIG[sym]["lot"]}
        tok_id += 1
        tokens[str(tok_id)] = {"type": "future", "month": "current", "sym": sym,
                                "tsym": f"{sym}FUT", "lot": STOCK_CONFIG[sym]["lot"]}
        tok_id += 1
        tokens[str(tok_id)] = {"type": "future", "month": "next", "sym": sym,
                                "tsym": f"{sym}FUT", "lot": STOCK_CONFIG[sym]["lot"]}
        tok_id += 1
    bridge.inject_metadata(tokens=tokens, stocks=[])
    return bridge


# ============================================================================
# FINDING 1: Division sensitivity with very small initial_spread
# ============================================================================

class TestTinyInitialSpread(unittest.TestCase):
    """
    VULNERABILITY: When initial_spread is very small (e.g., 0.01),
    the discount formula (initial - current) / initial * 100 becomes
    extremely sensitive to floating-point precision.
    """

    def setUp(self):
        self.bridge = _setup_bridge_with_tokens()

    def _inject(self, sym, cur_ltp, nxt_ltp, offset=0):
        tokens = self.bridge.get_tokens_for_stock(sym)
        ts = _now_ist_str(offset)
        self.bridge.inject_tick(tokens["current"], cur_ltp, ts=ts,
                                info={"sym": sym, "type": "future", "month": "current"})
        self.bridge.inject_tick(tokens["next"], nxt_ltp, ts=ts,
                                info={"sym": sym, "type": "future", "month": "next"})

    def test_initial_spread_0_01(self):
        """initial_spread=0.01, current_spread=0.005 -> discount = 50%"""
        spreads = {"RELIANCE": 0.01}
        engine = SpreadEngine(self.bridge, spreads)
        self._inject("RELIANCE", 100.0, 100.005)
        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap)
        # discount = (0.01 - 0.005) / 0.01 * 100 = 50.0
        self.assertAlmostEqual(snap.discount_pct, 50.0, places=2)

    def test_initial_spread_0_01_spread_exceeds_initial(self):
        """initial_spread=0.01, current_spread=0.02 -> discount = -100% (negative!)"""
        spreads = {"RELIANCE": 0.01}
        engine = SpreadEngine(self.bridge, spreads)
        self._inject("RELIANCE", 100.0, 100.02)
        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap)
        # discount = (0.01 - 0.02) / 0.01 * 100 = -100.0
        # NEGATIVE DISCOUNT means spread WIDENED - no guard against this!
        self.assertAlmostEqual(snap.discount_pct, -100.0, places=2)
        # BUG: No validation that discount_pct should be in [0, 100] range

    def test_initial_spread_0_001_extreme(self):
        """initial_spread=0.001 -> floating point precision issues"""
        spreads = {"RELIANCE": 0.001}
        engine = SpreadEngine(self.bridge, spreads)
        self._inject("RELIANCE", 100.0, 100.0005)
        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap)
        # discount = (0.001 - 0.0005) / 0.001 * 100 = 50.0
        # But with floating point: 0.0005/0.001 might not be exactly 0.5
        print(f"  Tiny spread discount: {snap.discount_pct}")
        # Should be ~50 but check if floating point causes drift
        self.assertAlmostEqual(snap.discount_pct, 50.0, places=1)

    def test_initial_spread_zero_division(self):
        """initial_spread=0.0 -> ZeroDivisionError!"""
        spreads = {"RELIANCE": 0.0}
        engine = SpreadEngine(self.bridge, spreads)
        self._inject("RELIANCE", 100.0, 100.5)
        # spread = 0.5 > 0, so it enters the discount formula
        # discount = (0.0 - 0.5) / 0.0 * 100 -> ZeroDivisionError!
        with self.assertRaises(ZeroDivisionError):
            engine.compute_for_stock("RELIANCE")

    def test_tatasteel_real_tiny_spread_sensitivity(self):
        """TATASTEEL initial_spread=1.11, a 0.50 move = 45% discount swing"""
        spreads = {"TATASTEEL": 1.11}
        engine = SpreadEngine(self.bridge, spreads)
        # A tiny 0.50 move in the spread
        self._inject("TATASTEEL", 190.0, 190.50)
        snap = engine.compute_for_stock("TATASTEEL")
        self.assertIsNotNone(snap)
        # discount = (1.11 - 0.50) / 1.11 * 100 = 54.95%
        expected = (1.11 - 0.50) / 1.11 * 100
        self.assertAlmostEqual(snap.discount_pct, expected, places=2)
        # A 0.50 LTP move causes 55% discount - extremely volatile signal!

    def test_bandhanbank_real_tiny_spread_sensitivity(self):
        """BANDHANBANK initial_spread=1.19, similar sensitivity"""
        spreads = {"BANDHANBANK": 1.19}
        engine = SpreadEngine(self.bridge, spreads)
        self._inject("BANDHANBANK", 186.0, 186.60)
        snap = engine.compute_for_stock("BANDHANBANK")
        self.assertIsNotNone(snap)
        # discount = (1.19 - 0.60) / 1.19 * 100 = 49.58%
        expected = (1.19 - 0.60) / 1.19 * 100
        self.assertAlmostEqual(snap.discount_pct, expected, places=2)


# ============================================================================
# FINDING 2: Negative initial_spread (ASTRAL) with positive current spread
# ============================================================================

class TestNegativeInitialSpread(unittest.TestCase):
    """
    VULNERABILITY: ASTRAL has initial_spread=-1.70 (backwardation).
    If market shifts to contango (spread > 0), the discount formula:
        discount = (-1.70 - current_spread) / (-1.70) * 100
    produces absurd results > 100%.
    """

    def setUp(self):
        self.bridge = _setup_bridge_with_tokens()

    def _inject(self, sym, cur_ltp, nxt_ltp, offset=0):
        tokens = self.bridge.get_tokens_for_stock(sym)
        ts = _now_ist_str(offset)
        self.bridge.inject_tick(tokens["current"], cur_ltp, ts=ts,
                                info={"sym": sym, "type": "future", "month": "current"})
        self.bridge.inject_tick(tokens["next"], nxt_ltp, ts=ts,
                                info={"sym": sym, "type": "future", "month": "next"})

    def test_astral_negative_initial_positive_current_spread(self):
        """
        ASTRAL initial=-1.70. If current spread becomes +2.0 (contango),
        discount = (-1.70 - 2.0) / (-1.70) * 100 = 217.65%
        This is ABSURD - discount > 100% makes no trading sense.
        """
        spreads = {"ASTRAL": -1.70}
        engine = SpreadEngine(self.bridge, spreads)
        self._inject("ASTRAL", 1406.0, 1408.0)  # spread = 2.0
        snap = engine.compute_for_stock("ASTRAL")
        self.assertIsNotNone(snap)
        self.assertTrue(snap.is_contango)
        expected = (-1.70 - 2.0) / (-1.70) * 100
        print(f"  ASTRAL absurd discount: {expected}%")
        self.assertAlmostEqual(snap.discount_pct, expected, places=2)
        # BUG: discount_pct = 217.65% - no clamping, no validation
        self.assertGreater(snap.discount_pct, 100.0)

    def test_astral_negative_initial_large_positive_spread(self):
        """
        ASTRAL initial=-1.70, current spread=10.0
        discount = (-1.70 - 10.0) / (-1.70) * 100 = 688.24%
        Completely meaningless number.
        """
        spreads = {"ASTRAL": -1.70}
        engine = SpreadEngine(self.bridge, spreads)
        self._inject("ASTRAL", 1400.0, 1410.0)  # spread = 10.0
        snap = engine.compute_for_stock("ASTRAL")
        self.assertIsNotNone(snap)
        expected = (-1.70 - 10.0) / (-1.70) * 100
        print(f"  ASTRAL extreme absurd discount: {expected}%")
        self.assertAlmostEqual(snap.discount_pct, expected, places=2)
        self.assertGreater(snap.discount_pct, 500.0)

    def test_astral_negative_initial_small_positive_spread(self):
        """
        ASTRAL initial=-1.70, current spread=0.01 (barely contango)
        discount = (-1.70 - 0.01) / (-1.70) * 100 = 100.59%
        Still > 100%, still absurd.
        """
        spreads = {"ASTRAL": -1.70}
        engine = SpreadEngine(self.bridge, spreads)
        self._inject("ASTRAL", 1406.0, 1406.01)  # spread = 0.01
        snap = engine.compute_for_stock("ASTRAL")
        self.assertIsNotNone(snap)
        expected = (-1.70 - 0.01) / (-1.70) * 100
        print(f"  ASTRAL barely-contango discount: {expected}%")
        self.assertAlmostEqual(snap.discount_pct, expected, places=2)
        self.assertGreater(snap.discount_pct, 100.0)

    def test_astral_stays_backwardation(self):
        """
        ASTRAL initial=-1.70, current spread=-3.0 (still backwardation)
        This is handled correctly: spread <= 0 -> discount=0, is_contango=False
        """
        spreads = {"ASTRAL": -1.70}
        engine = SpreadEngine(self.bridge, spreads)
        self._inject("ASTRAL", 1410.0, 1407.0)  # spread = -3.0
        snap = engine.compute_for_stock("ASTRAL")
        self.assertIsNotNone(snap)
        self.assertFalse(snap.is_contango)
        self.assertEqual(snap.discount_pct, 0.0)

    def test_any_negative_initial_spread_is_broken(self):
        """
        ANY stock with negative initial_spread will produce absurd
        discount_pct if market shifts to contango.
        """
        for initial in [-5.0, -1.0, -0.50, -0.01]:
            spreads = {"RELIANCE": initial}
            engine = SpreadEngine(self.bridge, spreads)
            self._inject("RELIANCE", 100.0, 102.0)  # spread = 2.0
            snap = engine.compute_for_stock("RELIANCE")
            self.assertIsNotNone(snap)
            # With negative initial, discount > 100%
            self.assertGreater(snap.discount_pct, 100.0,
                               f"initial_spread={initial} gives absurd discount {snap.discount_pct}%")


# ============================================================================
# FINDING 3: Timer drift analysis
# ============================================================================

class TestTimerDrift(unittest.TestCase):
    """
    VULNERABILITY: The _timer_loop uses Event.wait(60) which means:
    actual_interval = 60 + compute_all_execution_time
    Over hours, this drift accumulates. After 8 hours of trading,
    the timer could be significantly off from the intended 60s cadence.
    """

    def test_timer_loop_drifts_with_compute_time(self):
        """
        Simulate that compute_all() takes 2 seconds.
        Over 10 cycles, actual elapsed should be ~620s not ~600s.
        """
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        call_times = []
        original_compute_all = engine.compute_all

        def slow_compute_all():
            call_times.append(time.monotonic())
            time.sleep(0.05)  # Simulate 50ms compute time
            return original_compute_all()

        engine.compute_all = slow_compute_all

        # Run for a short time with short interval
        original_interval = SAMPLE_INTERVAL_SECONDS
        import algo_engine.spread as spread_module
        spread_module.SAMPLE_INTERVAL_SECONDS = 0.1  # 100ms for fast testing

        engine._stop_event = threading.Event()
        engine._timer_thread = None

        start = time.monotonic()
        engine.start()
        time.sleep(1.0)  # Let it run for ~1 second
        engine.stop()

        spread_module.SAMPLE_INTERVAL_SECONDS = original_interval

        if len(call_times) >= 3:
            intervals = [call_times[i+1] - call_times[i] for i in range(len(call_times)-1)]
            avg_interval = sum(intervals) / len(intervals)
            print(f"  Average actual interval: {avg_interval:.4f}s (intended: 0.15s)")
            # Each interval should be ~0.1 (wait) + 0.05 (compute) = 0.15s
            # This proves drift exists
            self.assertGreater(avg_interval, 0.1,
                               "Interval should include compute time (drift)")

    def test_event_wait_vs_timer_accumulation(self):
        """
        threading.Event.wait() does NOT perfectly sleep for the timeout.
        It can overshoot due to OS scheduling. Over many cycles, this adds up.
        """
        engine = SpreadEngine(TickBridge(), INITIAL_SPREADS)
        engine._stop_event = threading.Event()

        # Measure actual wait times
        actual_waits = []
        for _ in range(20):
            start = time.monotonic()
            engine._stop_event.wait(timeout=0.05)
            elapsed = time.monotonic() - start
            actual_waits.append(elapsed)

        avg_wait = sum(actual_waits) / len(actual_waits)
        max_wait = max(actual_waits)
        print(f"  Avg wait: {avg_wait:.6f}s, Max wait: {max_wait:.6f}s (intended: 0.05s)")
        # On Windows, Event.wait can overshoot by 1-15ms
        self.assertGreaterEqual(avg_wait, 0.04)


# ============================================================================
# FINDING 4: Race condition between compute_all() and bridge tick updates
# ============================================================================

class TestRaceConditions(unittest.TestCase):
    """
    VULNERABILITY: compute_for_stock() calls bridge.get_tick() twice
    (current and next). Between these two calls, the bridge could receive
    a new tick for either token, resulting in a spread computed from
    mismatched point-in-time data.
    """

    def test_concurrent_bridge_updates_during_compute(self):
        """
        Hammer the bridge with tick updates while compute_all() runs.
        Check for inconsistent state or crashes.
        """
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        errors = []
        stop = threading.Event()

        # Inject initial valid ticks
        for sym in STOCK_CONFIG:
            tokens = bridge.get_tokens_for_stock(sym)
            ts = _now_ist_str()
            bridge.inject_tick(tokens["current"], 1000.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "current"})
            bridge.inject_tick(tokens["next"], 1005.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "next"})

        def bridge_updater():
            """Rapidly update ticks for all stocks"""
            counter = 0
            while not stop.is_set():
                for sym in STOCK_CONFIG:
                    tokens = bridge.get_tokens_for_stock(sym)
                    ts = _now_ist_str()
                    ltp = 1000.0 + (counter % 100) * 0.1
                    bridge.inject_tick(tokens["current"], ltp, ts=ts,
                                       info={"sym": sym, "type": "future", "month": "current"})
                    bridge.inject_tick(tokens["next"], ltp + 5.0, ts=ts,
                                       info={"sym": sym, "type": "future", "month": "next"})
                counter += 1
                time.sleep(0.001)

        def computer():
            """Rapidly compute spreads"""
            while not stop.is_set():
                try:
                    results = engine.compute_all()
                    # Verify no crashes, results should be dict
                    assert isinstance(results, dict)
                except Exception as e:
                    errors.append(e)
                time.sleep(0.001)

        t1 = threading.Thread(target=bridge_updater)
        t2 = threading.Thread(target=computer)
        t1.start()
        t2.start()
        time.sleep(1.0)
        stop.set()
        t1.join(timeout=5)
        t2.join(timeout=5)

        self.assertEqual(errors, [], f"Errors during concurrent access: {errors}")

    def test_non_atomic_tick_read_pair(self):
        """
        PROOF: get_tick(current) and get_tick(next) are not atomic.
        Between the two calls, the next tick could update.
        This means spread = next_new - current_old (mismatched pair).
        """
        bridge = TickBridge()
        # Set up a single stock
        tokens_meta = {
            "1": {"type": "future", "month": "current", "sym": "TEST", "tsym": "TESTFUT"},
            "2": {"type": "future", "month": "next", "sym": "TEST", "tsym": "TESTFUT"},
        }
        bridge.inject_metadata(tokens=tokens_meta, stocks=["TEST"])

        ts = _now_ist_str()
        bridge.inject_tick(1, 100.0, ts=ts, info={"sym": "TEST", "type": "future", "month": "current"})
        bridge.inject_tick(2, 105.0, ts=ts, info={"sym": "TEST", "type": "future", "month": "next"})

        # This demonstrates the non-atomic read
        # In production, between get_tick(1) and get_tick(2), tick 2 could change
        tick1 = bridge.get_tick(1)
        # SIMULATE: bridge receives new tick for token 2 here
        bridge.inject_tick(2, 200.0, ts=_now_ist_str(),
                           info={"sym": "TEST", "type": "future", "month": "next"})
        tick2 = bridge.get_tick(2)

        # spread would be: 200.0 - 100.0 = 100.0 (WRONG! should be 5.0)
        spread = tick2.ltp - tick1.ltp
        print(f"  Non-atomic spread: {spread} (expected 5.0, got 100.0)")
        self.assertAlmostEqual(spread, 100.0)  # This is the BUG - mismatched pair


# ============================================================================
# FINDING 5: Freshness boundary conditions
# ============================================================================

class TestFreshnessBoundary(unittest.TestCase):
    """
    VULNERABILITY: The freshness check uses wall-clock time comparison.
    Boundary conditions at exactly 60s are critical.
    """

    def setUp(self):
        self.bridge = _setup_bridge_with_tokens()
        self.engine = SpreadEngine(self.bridge, INITIAL_SPREADS)

    def _inject(self, sym, cur_ltp, nxt_ltp, offset=0):
        tokens = self.bridge.get_tokens_for_stock(sym)
        ts = _now_ist_str(offset)
        self.bridge.inject_tick(tokens["current"], cur_ltp, ts=ts,
                                info={"sym": sym, "type": "future", "month": "current"})
        self.bridge.inject_tick(tokens["next"], nxt_ltp, ts=ts,
                                info={"sym": sym, "type": "future", "month": "next"})

    def test_tick_at_exactly_59_seconds_is_fresh(self):
        """59s old tick should be fresh (<=60s)"""
        self._inject("RELIANCE", 2850.0, 2854.0, offset=-59)
        snap = self.engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap, "59s old tick should be fresh")

    def test_tick_at_exactly_60_seconds_is_fresh(self):
        """60s old tick should be fresh (<=60s, boundary inclusive)"""
        self._inject("RELIANCE", 2850.0, 2854.0, offset=-60)
        snap = self.engine.compute_for_stock("RELIANCE")
        # age_seconds <= SPREAD_FRESHNESS_SECONDS (60 <= 60 = True)
        self.assertIsNotNone(snap, "60s old tick should be fresh (boundary inclusive)")

    def test_tick_at_61_seconds_is_stale(self):
        """61s old tick should be stale"""
        self._inject("RELIANCE", 2850.0, 2854.0, offset=-61)
        snap = self.engine.compute_for_stock("RELIANCE")
        self.assertIsNone(snap, "61s old tick should be stale")
        self.assertIn("RELIANCE", self.engine.skip_reasons)

    def test_tick_at_60_5_seconds_boundary(self):
        """
        60.5s old tick - depends on timing precision.
        The _now_ist_str function truncates to milliseconds, so there
        could be race conditions at the boundary.
        """
        self._inject("RELIANCE", 2850.0, 2854.0, offset=-60)
        # Add a tiny extra delay to push it just past 60s
        time.sleep(0.6)
        snap = self.engine.compute_for_stock("RELIANCE")
        # This SHOULD be stale now (60.6s), but timing is not guaranteed
        # On a loaded system, the sleep could be shorter or longer
        print(f"  60.5s boundary test: snap is {snap}")

    def test_previous_day_stale_ticks(self):
        """
        At market open (9:15), ticks from previous day (15:30) are
        ~64800 seconds old. These should be rejected as stale.
        """
        tokens = self.bridge.get_tokens_for_stock("RELIANCE")
        # Simulate a tick from yesterday
        yesterday = datetime.now(IST) - timedelta(days=1)
        yesterday_str = yesterday.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.bridge.inject_tick(tokens["current"], 2850.0, ts=yesterday_str,
                                info={"sym": "RELIANCE", "type": "future", "month": "current"})
        self.bridge.inject_tick(tokens["next"], 2854.0, ts=yesterday_str,
                                info={"sym": "RELIANCE", "type": "future", "month": "next"})
        snap = self.engine.compute_for_stock("RELIANCE")
        self.assertIsNone(snap, "Previous day ticks must be rejected")
        self.assertEqual(self.engine.skip_reasons["RELIANCE"], "stale_current")

    def test_malformed_timestamp(self):
        """What if tick.ts is garbage?"""
        tokens = self.bridge.get_tokens_for_stock("RELIANCE")
        self.bridge.inject_tick(tokens["current"], 2850.0, ts="not-a-date",
                                info={"sym": "RELIANCE", "type": "future", "month": "current"})
        self.bridge.inject_tick(tokens["next"], 2854.0, ts="2026-10-06 09:15:00.000",
                                info={"sym": "RELIANCE", "type": "future", "month": "next"})
        snap = self.engine.compute_for_stock("RELIANCE")
        self.assertIsNone(snap, "Malformed timestamp should be treated as stale")
        self.assertEqual(self.engine.skip_reasons["RELIANCE"], "stale_current")


# ============================================================================
# FINDING 6: Clock change vulnerability (NTP sync, DST)
# ============================================================================

class TestClockChange(unittest.TestCase):
    """
    VULNERABILITY: _tick_is_fresh() uses datetime.now(IST) which is wall-clock.
    If NTP sync jumps the clock forward by 5 minutes, all existing ticks
    suddenly become stale. If clock jumps backward, stale ticks become fresh.
    """

    def setUp(self):
        self.bridge = _setup_bridge_with_tokens()
        self.engine = SpreadEngine(self.bridge, INITIAL_SPREADS)

    def _inject(self, sym, cur_ltp, nxt_ltp, offset=0):
        tokens = self.bridge.get_tokens_for_stock(sym)
        ts = _now_ist_str(offset)
        self.bridge.inject_tick(tokens["current"], cur_ltp, ts=ts,
                                info={"sym": sym, "type": "future", "month": "current"})
        self.bridge.inject_tick(tokens["next"], nxt_ltp, ts=ts,
                                info={"sym": sym, "type": "future", "month": "next"})

    def test_clock_jump_forward_makes_fresh_ticks_stale(self):
        """
        Simulate NTP jumping clock forward by 5 minutes.
        A tick that was fresh 1 second ago is now 301s old -> stale.
        """
        self._inject("RELIANCE", 2850.0, 2854.0, offset=-5)  # 5s old = fresh

        # Verify it's fresh now
        snap = self.engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap, "Should be fresh before clock jump")

        # Simulate clock jumping forward by patching datetime.now
        original_now = datetime.now

        def jumped_now(tz=None):
            return original_now(tz) + timedelta(minutes=5)

        with patch('algo_engine.spread.datetime') as mock_dt:
            mock_dt.now = lambda tz=None: original_now(tz) + timedelta(minutes=5)
            mock_dt.strptime = datetime.strptime
            snap = self.engine.compute_for_stock("RELIANCE")

        # The tick is now 305s old -> stale
        self.assertIsNone(snap, "Clock jump forward should make fresh ticks stale")

    def test_clock_jump_backward_makes_stale_ticks_fresh(self):
        """
        Simulate NTP jumping clock backward by 5 minutes.
        A tick that was 120s old (stale) is now considered -180s old (future!) -> fresh.
        This is DANGEROUS: stale data treated as fresh.
        """
        # Inject a tick that's 120s old (stale)
        self._inject("RELIANCE", 2850.0, 2854.0, offset=-120)

        # Verify it's stale
        snap = self.engine.compute_for_stock("RELIANCE")
        self.assertIsNone(snap, "120s old tick should be stale")

        # Simulate clock jumping backward
        with patch('algo_engine.spread.datetime') as mock_dt:
            mock_dt.now = lambda tz=None: datetime.now(tz) - timedelta(minutes=5)
            mock_dt.strptime = datetime.strptime
            snap = self.engine.compute_for_stock("RELIANCE")

        # Now the tick appears to be from the future (-180s old) -> "fresh"
        self.assertIsNotNone(snap,
            "BUG: Clock jump backward makes stale ticks appear fresh!")


# ============================================================================
# FINDING 7: stop() + start() lifecycle issues
# ============================================================================

class TestStartStopLifecycle(unittest.TestCase):
    """
    VULNERABILITY: Repeated start/stop cycles could leak threads or
    leave the engine in an inconsistent state.
    """

    def test_rapid_start_stop_cycles(self):
        """Start and stop 50 times rapidly - check for thread leaks"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        initial_threads = threading.active_count()

        for i in range(50):
            engine.start()
            engine.stop()

        final_threads = threading.active_count()
        print(f"  Threads before: {initial_threads}, after: {final_threads}")
        # Allow for 1 thread variance due to timing
        self.assertLessEqual(final_threads, initial_threads + 2,
                             "Thread leak detected after 50 start/stop cycles")

    def test_double_start_is_idempotent(self):
        """Calling start() twice should not create two timer threads"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        engine.start()
        thread1 = engine._timer_thread
        engine.start()  # Should be no-op
        thread2 = engine._timer_thread

        self.assertIs(thread1, thread2, "Double start should not create new thread")
        engine.stop()

    def test_stop_without_start(self):
        """Calling stop() when engine was never started should not crash"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        # Should not raise
        engine.stop()

    def test_stop_idempotent(self):
        """Calling stop() twice should not crash"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        engine.start()
        engine.stop()
        engine.stop()  # Should not crash

    def test_start_after_stop_resumes(self):
        """After stop(), start() should create a fresh timer thread"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        engine.start()
        thread1 = engine._timer_thread
        engine.stop()
        self.assertIsNone(engine._timer_thread)

        engine.start()
        thread2 = engine._timer_thread
        self.assertIsNotNone(thread2)
        self.assertIsNot(thread1, thread2)
        engine.stop()

    def test_stop_during_compute(self):
        """
        If stop() is called while compute_all() is running,
        the thread should still terminate cleanly.
        """
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        # Inject ticks so compute has work to do
        for sym in STOCK_CONFIG:
            tokens = bridge.get_tokens_for_stock(sym)
            ts = _now_ist_str()
            bridge.inject_tick(tokens["current"], 1000.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "current"})
            bridge.inject_tick(tokens["next"], 1005.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "next"})

        engine.start()
        time.sleep(0.1)
        engine.stop()

        # Thread should be cleaned up
        self.assertIsNone(engine._timer_thread)


# ============================================================================
# FINDING 8: Missing stock in _initial_spreads
# ============================================================================

class TestMissingStockData(unittest.TestCase):
    """
    VULNERABILITY: What if a stock is in STOCK_CONFIG but not in
    _initial_spreads? Or vice versa?
    """

    def test_stock_in_config_but_not_in_initial_spreads(self):
        """Stock exists in config but has no initial spread entry"""
        bridge = _setup_bridge_with_tokens()
        spreads = {"RELIANCE": 6.20}  # Only RELIANCE has initial spread
        engine = SpreadEngine(bridge, spreads)

        # Inject ticks for TCS (not in spreads)
        tokens = bridge.get_tokens_for_stock("TCS")
        ts = _now_ist_str()
        bridge.inject_tick(tokens["current"], 2096.0, ts=ts,
                           info={"sym": "TCS", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 2102.0, ts=ts,
                           info={"sym": "TCS", "type": "future", "month": "next"})

        snap = engine.compute_for_stock("TCS")
        self.assertIsNone(snap)
        self.assertEqual(engine.skip_reasons["TCS"], "no_initial_spread")

    def test_compute_all_with_partial_spreads(self):
        """compute_all() should handle missing spreads gracefully"""
        bridge = _setup_bridge_with_tokens()
        spreads = {"RELIANCE": 6.20}  # Only 1 of 19 stocks
        engine = SpreadEngine(bridge, spreads)

        # Inject ticks for ALL stocks
        for sym in STOCK_CONFIG:
            tokens = bridge.get_tokens_for_stock(sym)
            ts = _now_ist_str()
            bridge.inject_tick(tokens["current"], 1000.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "current"})
            bridge.inject_tick(tokens["next"], 1005.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "next"})

        results = engine.compute_all()
        # Only RELIANCE should have a result
        self.assertEqual(len(results), 1)
        self.assertIn("RELIANCE", results)
        # 18 stocks should have skip reasons
        self.assertEqual(len(engine.skip_reasons), 18)


# ============================================================================
# FINDING 9: Spread computation edge cases
# ============================================================================

class TestSpreadComputationEdgeCases(unittest.TestCase):
    """Additional edge cases in spread computation"""

    def setUp(self):
        self.bridge = _setup_bridge_with_tokens()

    def _inject(self, sym, cur_ltp, nxt_ltp, offset=0):
        tokens = self.bridge.get_tokens_for_stock(sym)
        ts = _now_ist_str(offset)
        self.bridge.inject_tick(tokens["current"], cur_ltp, ts=ts,
                                info={"sym": sym, "type": "future", "month": "current"})
        self.bridge.inject_tick(tokens["next"], nxt_ltp, ts=ts,
                                info={"sym": sym, "type": "future", "month": "next"})

    def test_very_large_ltp_values(self):
        """Test with very large LTP values (e.g., 999999.99)"""
        spreads = {"MARUTI": 54.0}
        engine = SpreadEngine(self.bridge, spreads)
        self._inject("MARUTI", 999999.99, 1000053.99)
        snap = engine.compute_for_stock("MARUTI")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.spread, 54.0, places=2)

    def test_negative_ltp_values(self):
        """
        Can LTP be negative? In futures, theoretically not, but
        what if bad data arrives?
        """
        spreads = {"RELIANCE": 6.20}
        engine = SpreadEngine(self.bridge, spreads)
        self._inject("RELIANCE", -100.0, -96.0)  # spread = 4.0
        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap)
        # spread = -96 - (-100) = 4.0 > 0 -> contango
        self.assertAlmostEqual(snap.spread, 4.0)
        # discount = (6.20 - 4.0) / 6.20 * 100 = 35.48%
        # But with negative prices, this is meaningless!

    def test_zero_ltp_values(self):
        """What if LTP is 0? (market data error)"""
        spreads = {"RELIANCE": 6.20}
        engine = SpreadEngine(self.bridge, spreads)
        self._inject("RELIANCE", 0.0, 0.0)
        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap)
        self.assertFalse(snap.is_contango)  # spread = 0 -> backwardation path

    def test_spread_exactly_equal_to_initial(self):
        """When current_spread == initial_spread, discount should be 0%"""
        spreads = {"RELIANCE": 6.20}
        engine = SpreadEngine(self.bridge, spreads)
        self._inject("RELIANCE", 100.0, 106.20)  # spread = 6.20 = initial
        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.discount_pct, 0.0, places=5)

    def test_floating_point_precision_in_discount(self):
        """
        Floating point: (6.20 - 4.0) / 6.20 might not be exactly 0.354838...
        due to IEEE 754 representation.
        """
        spreads = {"RELIANCE": 6.20}
        engine = SpreadEngine(self.bridge, spreads)
        self._inject("RELIANCE", 100.0, 104.0)
        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap)
        # Check the raw float
        raw_discount = (6.20 - 4.0) / 6.20 * 100
        print(f"  Raw discount float: {raw_discount!r}")
        print(f"  Snap discount:      {snap.discount_pct!r}")
        self.assertEqual(snap.discount_pct, raw_discount)

    def test_discount_can_exceed_100_percent(self):
        """
        If spread shrinks to near-zero, discount approaches 100%.
        If spread goes negative (backwardation), we skip discount calc.
        But what about spread = 0.001 with initial = 100?
        discount = (100 - 0.001) / 100 * 100 = 99.999%
        """
        spreads = {"MARUTI": 54.0}
        engine = SpreadEngine(self.bridge, spreads)
        self._inject("MARUTI", 1000.0, 1000.001)  # spread = 0.001
        snap = engine.compute_for_stock("MARUTI")
        self.assertIsNotNone(snap)
        expected = (54.0 - 0.001) / 54.0 * 100
        self.assertAlmostEqual(snap.discount_pct, expected, places=4)
        self.assertGreater(snap.discount_pct, 99.0)

    def test_discount_negative_when_spread_widens(self):
        """
        If current_spread > initial_spread, discount is NEGATIVE.
        This means the spread WIDENED. No guard against this.
        A negative discount could confuse downstream consumers.
        """
        spreads = {"RELIANCE": 6.20}
        engine = SpreadEngine(self.bridge, spreads)
        self._inject("RELIANCE", 100.0, 110.0)  # spread = 10.0 > initial 6.20
        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap)
        expected = (6.20 - 10.0) / 6.20 * 100
        self.assertAlmostEqual(snap.discount_pct, expected, places=2)
        self.assertLess(snap.discount_pct, 0)
        print(f"  Negative discount (spread widened): {snap.discount_pct:.2f}%")


# ============================================================================
# FINDING 10: Test gaps in existing 44 tests
# ============================================================================

class TestExistingTestGaps(unittest.TestCase):
    """
    Document what the existing 44 tests DO NOT cover.
    These are critical gaps for production deployment.
    """

    def test_no_test_for_stop_method(self):
        """Existing tests never call engine.stop() - timer thread not tested"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        engine.start()
        self.assertIsNotNone(engine._timer_thread)
        engine.stop()
        self.assertIsNone(engine._timer_thread)
        # No existing test verifies this lifecycle!

    def test_no_test_for_backwardation_to_contango_transition(self):
        """
        Existing tests test backwardation and contango separately.
        No test for the ASTRAL case where initial is negative but
        current market is in contango.
        """
        bridge = _setup_bridge_with_tokens()
        spreads = {"ASTRAL": -1.70}
        engine = SpreadEngine(bridge, spreads)
        tokens = bridge.get_tokens_for_stock("ASTRAL")
        ts = _now_ist_str()
        bridge.inject_tick(tokens["current"], 1406.0, ts=ts,
                           info={"sym": "ASTRAL", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 1408.0, ts=ts,
                           info={"sym": "ASTRAL", "type": "future", "month": "next"})
        snap = engine.compute_for_stock("ASTRAL")
        # This produces discount_pct = 217.65% - ABSURD!
        print(f"  ASTRAL backwardation->contango discount: {snap.discount_pct}%")
        self.assertGreater(snap.discount_pct, 100)

    def test_no_test_for_timestamp_parsing_edge_cases(self):
        """Existing tests only use well-formed timestamps"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tokens = bridge.get_tokens_for_stock("RELIANCE")

        # Test with None timestamp
        bridge.inject_tick(tokens["current"], 2850.0, ts=None,
                           info={"sym": "RELIANCE", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 2854.0, ts=_now_ist_str(),
                           info={"sym": "RELIANCE", "type": "future", "month": "next"})
        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNone(snap, "None timestamp should be treated as stale")

    def test_no_test_for_compute_all_partial_results(self):
        """
        Existing tests always have all ticks available.
        No test for compute_all() when some stocks have ticks and others don't.
        """
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        # Only inject ticks for 5 of 19 stocks
        for i, sym in enumerate(list(STOCK_CONFIG.keys())[:5]):
            tokens = bridge.get_tokens_for_stock(sym)
            ts = _now_ist_str()
            bridge.inject_tick(tokens["current"], 1000.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "current"})
            bridge.inject_tick(tokens["next"], 1005.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "next"})

        results = engine.compute_all()
        self.assertEqual(len(results), 5)
        self.assertEqual(len(engine.skip_reasons), 14)

    def test_no_test_for_snapshot_overwrite(self):
        """
        Existing tests don't verify that a new snapshot overwrites the old one.
        What if a stock goes from contango to backwardation between cycles?
        """
        bridge = _setup_bridge_with_tokens()
        spreads = {"RELIANCE": 6.20}
        engine = SpreadEngine(bridge, spreads)
        tokens = bridge.get_tokens_for_stock("RELIANCE")

        # Cycle 1: contango
        ts = _now_ist_str()
        bridge.inject_tick(tokens["current"], 100.0, ts=ts,
                           info={"sym": "RELIANCE", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 106.0, ts=ts,
                           info={"sym": "RELIANCE", "type": "future", "month": "next"})
        engine.compute_for_stock("RELIANCE")
        snap1 = engine.get_snapshot("RELIANCE")
        self.assertTrue(snap1.is_contango)

        # Cycle 2: backwardation (spread goes negative)
        ts2 = _now_ist_str()
        bridge.inject_tick(tokens["current"], 110.0, ts=ts2,
                           info={"sym": "RELIANCE", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 105.0, ts=ts2,
                           info={"sym": "RELIANCE", "type": "future", "month": "next"})
        engine.compute_for_stock("RELIANCE")
        snap2 = engine.get_snapshot("RELIANCE")
        self.assertFalse(snap2.is_contango)
        # Snapshot was overwritten - the old contango snapshot is gone


# ============================================================================
# FINDING 11: Thread safety of _tick_is_fresh
# ============================================================================

class TestTickIsFreshThreadSafety(unittest.TestCase):
    """
    VULNERABILITY: _tick_is_fresh() calls datetime.now(IST) and then
    parses tick.ts. If the tick object is being modified concurrently
    (unlikely with immutable dataclass, but the bridge could return
    a tick that's about to be replaced), there's a TOCTOU issue.
    """

    def test_tick_ts_none_handling(self):
        """tick.ts = None should not crash"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tick = Tick(token=1, ltp=100.0, ts=None, recv_mono_ns=0)
        result = engine._tick_is_fresh(tick)
        self.assertFalse(result)

    def test_tick_ts_empty_string(self):
        """tick.ts = '' should not crash"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tick = Tick(token=1, ltp=100.0, ts="", recv_mono_ns=0)
        result = engine._tick_is_fresh(tick)
        self.assertFalse(result)

    def test_tick_ts_garbage(self):
        """tick.ts = 'garbage' should not crash"""
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        tick = Tick(token=1, ltp=100.0, ts="garbage", recv_mono_ns=0)
        result = engine._tick_is_fresh(tick)
        self.assertFalse(result)

    def test_tick_ts_future_timestamp(self):
        """
        A tick with a timestamp in the future should be considered fresh.
        But this is suspicious - could indicate clock issues.
        """
        bridge = _setup_bridge_with_tokens()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        future_ts = _now_ist_str(offset_seconds=3600)  # 1 hour in future
        tick = Tick(token=1, ltp=100.0, ts=future_ts, recv_mono_ns=0)
        result = engine._tick_is_fresh(tick)
        self.assertTrue(result)
        # BUG: age_seconds would be NEGATIVE, which is <= 60 -> "fresh"
        # A tick from the future is always "fresh" - no sanity check


# ============================================================================
# FINDING 12: Production-specific issues
# ============================================================================

class TestProductionIssues(unittest.TestCase):
    """
    Issues that would manifest in live production on 2026-10-06.
    """

    def setUp(self):
        self.bridge = _setup_bridge_with_tokens()

    def _inject(self, sym, cur_ltp, nxt_ltp, offset=0):
        tokens = self.bridge.get_tokens_for_stock(sym)
        ts = _now_ist_str(offset)
        self.bridge.inject_tick(tokens["current"], cur_ltp, ts=ts,
                                info={"sym": sym, "type": "future", "month": "current"})
        self.bridge.inject_tick(tokens["next"], nxt_ltp, ts=ts,
                                info={"sym": sym, "type": "future", "month": "next"})

    def test_all_19_stocks_with_real_initial_spreads(self):
        """
        Use the ACTUAL INITIAL_SPREADS from config. Verify no crashes.
        Some stocks have very small spreads (TATASTEEL=1.11, BANDHANBANK=1.19)
        and ASTRAL has negative spread (-1.70).
        """
        engine = SpreadEngine(self.bridge, INITIAL_SPREADS)

        # Inject realistic contango ticks for all stocks
        for sym in STOCK_CONFIG:
            tok = self.bridge.get_tokens_for_stock(sym)
            ts = _now_ist_str()
            self.bridge.inject_tick(tok["current"], 1000.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "current"})
            self.bridge.inject_tick(tok["next"], 1010.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "next"})

        results = engine.compute_all()
        for sym, snap in results.items():
            print(f"  {sym}: spread={snap.spread:.2f}, discount={snap.discount_pct:.2f}%, "
                  f"initial={snap.initial_spread}")
            # All should be contango (spread=10 > 0)
            self.assertTrue(snap.is_contango)

        # ASTRAL will have absurd discount because initial=-1.70
        astral = results.get("ASTRAL")
        if astral:
            self.assertGreater(astral.discount_pct, 100,
                               "ASTRAL with negative initial_spread produces >100% discount")

    def test_freshness_window_interaction_with_sample_interval(self):
        """
        SAMPLE_INTERVAL_SECONDS = 60 and SPREAD_FRESHNESS_SECONDS = 60.
        If a tick arrives right at the start of a cycle, by the NEXT cycle
        (60s later), it's exactly at the boundary. Any compute delay
        pushes it to stale. This means stocks with low-frequency ticks
        could flicker between fresh and stale every other cycle.
        """
        engine = SpreadEngine(self.bridge, INITIAL_SPREADS)
        tokens = self.bridge.get_tokens_for_stock("RELIANCE")

        # Inject a tick right now
        ts = _now_ist_str()
        self.bridge.inject_tick(tokens["current"], 2850.0, ts=ts,
                                info={"sym": "RELIANCE", "type": "future", "month": "current"})
        self.bridge.inject_tick(tokens["next"], 2854.0, ts=ts,
                                info={"sym": "RELIANCE", "type": "future", "month": "next"})

        # Fresh now
        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap)

        # After 55 seconds, still fresh
        with patch('algo_engine.spread.datetime') as mock_dt:
            mock_dt.now = lambda tz=None: datetime.now(tz) + timedelta(seconds=55)
            mock_dt.strptime = datetime.strptime
            snap = engine.compute_for_stock("RELIANCE")
            self.assertIsNotNone(snap, "55s old tick should be fresh")

        # After 61 seconds, stale
        with patch('algo_engine.spread.datetime') as mock_dt:
            mock_dt.now = lambda tz=None: datetime.now(tz) + timedelta(seconds=61)
            mock_dt.strptime = datetime.strptime
            snap = engine.compute_for_stock("RELIANCE")
            self.assertIsNone(snap, "61s old tick should be stale")

    def test_skip_reasons_cleared_on_recovery(self):
        """
        When a stock recovers from stale/no_ticks to fresh ticks,
        the skip_reason should be cleared.
        """
        engine = SpreadEngine(self.bridge, INITIAL_SPREADS)
        tokens = self.bridge.get_tokens_for_stock("RELIANCE")

        # No ticks -> skip reason
        engine.compute_for_stock("RELIANCE")
        self.assertEqual(engine.skip_reasons["RELIANCE"], "no_ticks")

        # Inject ticks -> should clear skip reason
        ts = _now_ist_str()
        self.bridge.inject_tick(tokens["current"], 2850.0, ts=ts,
                                info={"sym": "RELIANCE", "type": "future", "month": "current"})
        self.bridge.inject_tick(tokens["next"], 2854.0, ts=ts,
                                info={"sym": "RELIANCE", "type": "future", "month": "next"})
        engine.compute_for_stock("RELIANCE")
        self.assertNotIn("RELIANCE", engine.skip_reasons,
                         "Skip reason should be cleared after recovery")


if __name__ == "__main__":
    unittest.main(verbosity=2)
