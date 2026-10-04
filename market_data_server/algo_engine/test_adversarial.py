"""
Adversarial / stress tests for Steps 1-2 (config.py + bridge.py)
Finds: race conditions, memory leaks, type errors, edge cases, crashes.
"""
import sys
import json
import time
import unittest
import threading
import gc

sys.path.insert(0, r"C:\Users\Ankit\Desktop\RS FOLDER\rollover-react\market_data_server")

from algo_engine.config import (
    STOCK_CONFIG, THRESHOLDS, INITIAL_SPREADS,
    STOCK_COUNT, TOTAL_TOKENS, IST,
)
from algo_engine.bridge import TickBridge, Tick


# ============================================================================
# 1. MALFORMED WEBSOCKET MESSAGES
# ============================================================================

class TestMalformedMessages(unittest.TestCase):
    """Try to crash _on_message with every kind of bad input."""

    def setUp(self):
        self.bridge = TickBridge()

    def test_none_message(self):
        """What if raw is None instead of str?"""
        # json.loads(None) raises TypeError in Python 3
        try:
            self.bridge._on_message(None)
        except TypeError:
            self.fail("_on_message crashes on None input - no guard")

    def test_empty_string(self):
        self.bridge._on_message("")
        self.assertEqual(self.bridge.tick_count, 0)

    def test_bytes_instead_of_str(self):
        """WebSocket can deliver bytes in some configs."""
        msg = json.dumps({"type": "ticks", "data": [{"token": 1, "ltp_r": 100.0}]}).encode()
        try:
            self.bridge._on_message(msg)
        except (TypeError, json.JSONDecodeError):
            self.fail("_on_message crashes on bytes input")

    def test_nested_json_string(self):
        """Double-encoded JSON - will the inner parse produce wrong types?"""
        inner = json.dumps({"token": 1, "ltp_r": 100.0})
        outer = json.dumps({"type": "ticks", "data": [inner]})
        self.bridge._on_message(outer)
        # The "data" item is a string, not a dict - snap.get("token") will crash
        # because strings don't have .get()

    def test_tick_with_null_ltp(self):
        """LTP is None - should not crash, but does it store None?"""
        msg = json.dumps({
            "type": "ticks",
            "data": [{"token": 100, "ltp_r": None, "ts": "2026-10-01 09:20:00.000"}],
        })
        self.bridge._on_message(msg)
        tick = self.bridge.get_tick(100)
        self.assertIsNotNone(tick)
        # BUG: tick.ltp is None, not 0.0. Downstream math will crash.
        self.assertIsNone(tick.ltp, "BUG CONFIRMED: ltp_r=None stored as None, not 0.0")

    def test_tick_with_string_ltp(self):
        """LTP is a string - will it be stored as string?"""
        msg = json.dumps({
            "type": "ticks",
            "data": [{"token": 100, "ltp_r": "2850.50", "ts": ""}],
        })
        self.bridge._on_message(msg)
        tick = self.bridge.get_tick(100)
        self.assertIsInstance(tick.ltp, str, "BUG: ltp stored as string, not float")

    def test_tick_with_null_open_high_low_close(self):
        """OHLC fields are None - division by None crashes."""
        msg = json.dumps({
            "type": "ticks",
            "data": [{
                "token": 100, "ltp_r": 100.0, "ts": "",
                "open": None, "high": None, "low": None, "close": None,
            }],
        })
        with self.assertRaises(TypeError, msg="BUG: None/100.0 crashes with TypeError"):
            self.bridge._on_message(msg)

    def test_tick_with_string_ohlc(self):
        """OHLC fields are strings - division crashes."""
        msg = json.dumps({
            "type": "ticks",
            "data": [{
                "token": 100, "ltp_r": 100.0, "ts": "",
                "open": "284000", "high": "286500", "low": "283000", "close": "284500",
            }],
        })
        with self.assertRaises(TypeError, msg="BUG: string/100.0 crashes"):
            self.bridge._on_message(msg)

    def test_tick_with_negative_token(self):
        msg = json.dumps({
            "type": "ticks",
            "data": [{"token": -1, "ltp_r": 100.0, "ts": ""}],
        })
        self.bridge._on_message(msg)
        self.assertIsNotNone(self.bridge.get_tick(-1))

    def test_tick_with_float_token(self):
        """Token is a float - dict key will be float, not int."""
        msg = json.dumps({
            "type": "ticks",
            "data": [{"token": 100.5, "ltp_r": 100.0, "ts": ""}],
        })
        self.bridge._on_message(msg)
        # Token stored as 100.5 (float key), but get_tick expects int
        self.assertIsNone(self.bridge.get_tick(100))  # won't find it
        self.assertIsNone(self.bridge.get_tick(101))
        # BUG: float token is stored but never retrievable via int lookup

    def test_tick_with_boolean_token(self):
        """Token is True (bool is subclass of int in Python)."""
        msg = json.dumps({
            "type": "ticks",
            "data": [{"token": True, "ltp_r": 100.0, "ts": ""}],
        })
        self.bridge._on_message(msg)
        # True == 1 in Python, so get_tick(1) would return it!
        tick = self.bridge.get_tick(1)
        self.assertIsNotNone(tick, "BUG: True token maps to int key 1")

    def test_tick_with_zero_volume(self):
        msg = json.dumps({
            "type": "ticks",
            "data": [{"token": 100, "ltp_r": 100.0, "ts": "", "volume": 0}],
        })
        self.bridge._on_message(msg)
        self.assertEqual(self.bridge.get_tick(100).volume, 0)

    def test_tick_with_negative_oi(self):
        """Negative OI - should be impossible but what if feed sends it?"""
        msg = json.dumps({
            "type": "ticks",
            "data": [{"token": 100, "ltp_r": 100.0, "ts": "", "oi": -500}],
        })
        self.bridge._on_message(msg)
        self.assertEqual(self.bridge.get_tick(100).oi, -500, "BUG: negative OI accepted")

    def test_metadata_with_non_dict_token_info(self):
        """Token info is a string instead of dict."""
        msg = json.dumps({
            "type": "metadata",
            "tokens": {"100": "not_a_dict"},
            "stocks": [],
        })
        self.bridge._on_message(msg)
        # Stored as-is; later .get("sym") on string will crash
        info = self.bridge.get_token_info(100)
        self.assertEqual(info, "not_a_dict")

    def test_metadata_with_null_tokens(self):
        msg = json.dumps({"type": "metadata", "tokens": None, "stocks": []})
        with self.assertRaises((TypeError, AttributeError)):
            self.bridge._on_message(msg)

    def test_metadata_with_list_tokens(self):
        """Tokens is a list instead of dict."""
        msg = json.dumps({
            "type": "metadata",
            "tokens": [1, 2, 3],
            "stocks": [],
        })
        # Iterating a list gives ints, then int.info will crash
        try:
            self.bridge._on_message(msg)
        except (TypeError, AttributeError):
            pass  # Expected crash

    def test_ticks_data_is_not_list(self):
        """data field is a dict instead of list."""
        msg = json.dumps({
            "type": "ticks",
            "data": {"token": 100, "ltp_r": 100.0},
        })
        # Iterating a dict yields keys (strings), then snap.get() crashes
        with self.assertRaises((TypeError, AttributeError)):
            self.bridge._on_message(msg)

    def test_ticks_data_is_null(self):
        msg = json.dumps({"type": "ticks", "data": None})
        with self.assertRaises(TypeError):
            self.bridge._on_message(msg)

    def test_ticks_data_is_string(self):
        msg = json.dumps({"type": "ticks", "data": "not_a_list"})
        # Iterating a string yields chars, then char.get() crashes
        with self.assertRaises((TypeError, AttributeError)):
            self.bridge._on_message(msg)

    def test_message_type_is_not_string(self):
        """type field is an int."""
        msg = json.dumps({"type": 42, "data": []})
        self.bridge._on_message(msg)  # Should not crash - none of the branches match

    def test_message_missing_type(self):
        msg = json.dumps({"data": [{"token": 1, "ltp_r": 100.0}]})
        self.bridge._on_message(msg)
        self.assertEqual(self.bridge.tick_count, 0)

    def test_huge_message(self):
        """10MB JSON payload - will it OOM or take forever?"""
        data = [{"token": i, "ltp_r": 100.0, "ts": ""} for i in range(100000)]
        msg = json.dumps({"type": "ticks", "data": data})
        self.assertGreater(len(msg), 5_000_000)
        start = time.monotonic()
        self.bridge._on_message(msg)
        elapsed = time.monotonic() - start
        # Should process but note the time
        self.assertEqual(self.bridge.tick_count, 100000)
        print(f"\n  [PERF] 100k ticks processed in {elapsed:.3f}s")

    def test_info_field_is_none(self):
        """info is None instead of dict - Tick.info will be None."""
        msg = json.dumps({
            "type": "ticks",
            "data": [{"token": 100, "ltp_r": 100.0, "ts": "", "info": None}],
        })
        self.bridge._on_message(msg)
        tick = self.bridge.get_tick(100)
        self.assertIsNone(tick.info)
        # Now accessing tick.sym will crash because None.get("sym") fails
        with self.assertRaises(AttributeError):
            _ = tick.sym

    def test_info_field_is_list(self):
        """info is a list instead of dict."""
        msg = json.dumps({
            "type": "ticks",
            "data": [{"token": 100, "ltp_r": 100.0, "ts": "", "info": [1, 2, 3]}],
        })
        self.bridge._on_message(msg)
        tick = self.bridge.get_tick(100)
        with self.assertRaises(AttributeError):
            _ = tick.sym  # list has no .get()


# ============================================================================
# 2. THREAD SAFETY / RACE CONDITIONS
# ============================================================================

class TestRaceConditions(unittest.TestCase):
    """Aggressive concurrency tests."""

    def test_concurrent_writes_same_token(self):
        """50 threads writing to the same token - any corruption?"""
        bridge = TickBridge()
        errors = []
        N = 200

        def writer(thread_id):
            try:
                for i in range(N):
                    bridge.inject_tick(1, float(thread_id * N + i))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertEqual(bridge.tick_count, 50 * N)
        tick = bridge.get_tick(1)
        self.assertIsNotNone(tick)

    def test_concurrent_inject_and_clear(self):
        """Clear while writers are active - can lose ticks or crash."""
        bridge = TickBridge()
        errors = []
        stop = threading.Event()

        def writer():
            try:
                i = 0
                while not stop.is_set():
                    bridge.inject_tick(i % 10, float(i))
                    i += 1
            except Exception as e:
                errors.append(e)

        def clearer():
            try:
                for _ in range(100):
                    bridge.clear()
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)
            finally:
                stop.set()

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=clearer)
        t1.start()
        t2.start()
        t2.join(timeout=10)
        stop.set()
        t1.join(timeout=5)
        self.assertEqual(errors, [])

    def test_concurrent_metadata_and_tick_reads(self):
        """Metadata update while ticks are being read."""
        bridge = TickBridge()
        errors = []

        bridge.inject_tick(100, 100.0, info={"sym": "RELIANCE", "type": "future", "month": "current"})

        def metadata_writer():
            try:
                for _ in range(200):
                    bridge.inject_metadata(
                        tokens={"100": {"type": "future", "month": "current", "sym": "RELIANCE"}},
                        stocks=["RELIANCE"],
                    )
            except Exception as e:
                errors.append(e)

        def token_reader():
            try:
                for _ in range(200):
                    bridge.get_tokens_for_stock("RELIANCE")
                    bridge.get_token_info(100)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=metadata_writer)
        t2 = threading.Thread(target=token_reader)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        self.assertEqual(errors, [])

    def test_stop_during_connection(self):
        """Call stop() while the bridge is trying to connect."""
        bridge = TickBridge(uri="ws://127.0.0.1:19999")  # nothing listening
        bridge.start()
        time.sleep(0.5)
        bridge.stop()
        # Should not hang or crash
        self.assertFalse(bridge.connected)

    def test_double_start(self):
        """Calling start() twice should not create two threads."""
        bridge = TickBridge(uri="ws://127.0.0.1:19999")
        bridge.start()
        bridge.start()  # Should be no-op
        time.sleep(0.3)
        bridge.stop()

    def test_double_stop(self):
        """Calling stop() twice should not crash."""
        bridge = TickBridge(uri="ws://127.0.0.1:19999")
        bridge.start()
        time.sleep(0.3)
        bridge.stop()
        try:
            bridge.stop()
        except Exception as e:
            self.fail(f"Double stop() crashed: {e}")

    def test_stop_without_start(self):
        """Calling stop() without start() should not crash."""
        bridge = TickBridge()
        try:
            bridge.stop()
        except Exception as e:
            self.fail(f"stop() without start() crashed: {e}")

    def test_fresh_tokens_during_rapid_injection(self):
        """fresh_tokens() iterates without full snapshot - can miss or double-count."""
        bridge = TickBridge()
        results = {"fresh": [], "errors": []}
        stop = threading.Event()

        def injector():
            try:
                for i in range(1000):
                    bridge.inject_tick(i % 57, float(i))
            except Exception as e:
                results["errors"].append(e)

        def reader():
            try:
                for _ in range(100):
                    f = bridge.fresh_tokens(max_age_ms=500)
                    results["fresh"].append(len(f))
            except Exception as e:
                results["errors"].append(e)

        t1 = threading.Thread(target=injector)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        self.assertEqual(results["errors"], [])


# ============================================================================
# 3. MEMORY / UNBOUNDED GROWTH
# ============================================================================

class TestMemoryGrowth(unittest.TestCase):
    """Check for unbounded data structures."""

    def test_ticks_dict_never_shrinks(self):
        """Simulate a day of trading - tokens accumulate, never removed."""
        bridge = TickBridge()
        # Simulate 1000 different tokens over time (expired futures, new ones)
        for i in range(1000):
            bridge.inject_tick(i, 100.0)

        all_ticks = bridge.get_all_ticks()
        self.assertEqual(len(all_ticks), 1000)
        # Even though only 57 tokens are active at any time,
        # all 1000 are still in memory. _recv_times too.
        # After days of running, this grows unbounded.

    def test_recv_times_grows_with_ticks(self):
        """_recv_times is never cleaned up."""
        bridge = TickBridge()
        for i in range(500):
            bridge.inject_tick(i, 100.0)
        # Internal check: _recv_times has 500 entries
        self.assertEqual(len(bridge._recv_times), 500)
        # Even fresh_tokens only reads, never removes stale entries

    def test_token_info_never_removed(self):
        """_token_info grows when metadata is updated with new tokens."""
        bridge = TickBridge()
        for i in range(200):
            bridge.inject_metadata(
                tokens={str(1000 + i): {"type": "future", "sym": f"STOCK{i}", "month": "current"}},
                stocks=[],
            )
        self.assertEqual(bridge.token_count, 200)
        # Old expired tokens are never removed

    def test_tick_count_never_resets(self):
        """_tick_count only goes up, even after clear()."""
        bridge = TickBridge()
        bridge.inject_tick(1, 100.0)
        bridge.inject_tick(1, 200.0)
        self.assertEqual(bridge.tick_count, 2)
        bridge.clear()
        self.assertEqual(bridge.tick_count, 0)  # clear resets it
        bridge.inject_tick(1, 300.0)
        self.assertEqual(bridge.tick_count, 1)  # but it's a fresh count

    def test_sustained_load_memory(self):
        """Simulate sustained tick load and check dict sizes."""
        bridge = TickBridge()
        # Simulate 57 tokens getting ticks every 100ms for "1 hour"
        # (compressed: 1000 rounds)
        for round_num in range(1000):
            msg_data = []
            for tok in range(57):
                msg_data.append({
                    "token": tok,
                    "ltp_r": 100.0 + round_num * 0.01,
                    "ts": f"2026-10-06 09:{round_num % 60:02d}:00.000",
                    "info": {"sym": f"STOCK{tok % 19}", "type": "future", "month": "current"},
                })
            bridge._on_message(json.dumps({"type": "ticks", "data": msg_data}))

        # Only 57 unique tokens, so dicts should have 57 entries
        self.assertEqual(len(bridge._ticks), 57)
        self.assertEqual(len(bridge._recv_times), 57)
        # But tick_count is 57 * 1000 = 57000
        self.assertEqual(bridge.tick_count, 57000)


# ============================================================================
# 4. CONFIG INTEGRITY / MISMATCHES
# ============================================================================

class TestConfigIntegrity(unittest.TestCase):
    """Cross-validate config dicts for inconsistencies."""

    def test_initial_spreads_keys_match_stock_config(self):
        """Every stock in STOCK_CONFIG must have an initial spread."""
        for sym in STOCK_CONFIG:
            self.assertIn(sym, INITIAL_SPREADS,
                          f"{sym} in STOCK_CONFIG but missing from INITIAL_SPREADS")

    def test_initial_spreads_no_extra_keys(self):
        """INITIAL_SPREADS should not have stocks not in STOCK_CONFIG."""
        for sym in INITIAL_SPREADS:
            self.assertIn(sym, STOCK_CONFIG,
                          f"{sym} in INITIAL_SPREADS but not in STOCK_CONFIG")

    def test_thresholds_keys_match_stock_config(self):
        for sym in STOCK_CONFIG:
            self.assertIn(sym, THRESHOLDS,
                          f"{sym} in STOCK_CONFIG but missing from THRESHOLDS")

    def test_negative_initial_spread(self):
        """ASTRAL has a negative initial spread (-1.70). Is this intentional?"""
        spread = INITIAL_SPREADS.get("ASTRAL", 0)
        if spread < 0:
            print(f"\n  [WARNING] ASTRAL has negative initial spread: {spread}")
            # This is a red flag - negative spread means future < cash
            # which is unusual but possible in contango/backwardation

    def test_all_initial_spreads_positive(self):
        """Check if any other spreads are negative or zero."""
        for sym, val in INITIAL_SPREADS.items():
            if val <= 0:
                print(f"\n  [WARNING] {sym} has non-positive initial spread: {val}")

    def test_lot_size_sanity(self):
        """Check lot sizes are within reasonable NSE range."""
        for sym, cfg in STOCK_CONFIG.items():
            lot = cfg["lot"]
            if lot < 50:
                print(f"\n  [WARNING] {sym} has unusually small lot size: {lot}")
            if lot > 5000:
                print(f"\n  [WARNING] {sym} has unusually large lot size: {lot}")

    def test_adanient_lot_size(self):
        """ADANIENT lot = 309. NSE lot sizes are usually round numbers.
        Verify this is the current NSE value."""
        lot = STOCK_CONFIG["ADANIENT"]["lot"]
        if lot % 100 != 0 and lot % 250 != 0:
            print(f"\n  [WARNING] ADANIENT lot={lot} is not a round number - verify with NSE circular")

    def test_bandhanbank_lot_size(self):
        """BANDHANBANK lot = 3600 - very large, verify."""
        lot = STOCK_CONFIG["BANDHANBANK"]["lot"]
        if lot > 3000:
            print(f"\n  [WARNING] BANDHANBANK lot={lot} is very large - capital requirement: ~{lot * 3 * 300} INR per stock (3 legs)")

    def test_total_tokens_calculation(self):
        """TOTAL_TOKENS should be STOCK_COUNT * 3 (cash + current fut + next fut)."""
        self.assertEqual(TOTAL_TOKENS, STOCK_COUNT * 3)

    def test_threshold_values_reasonable(self):
        """Thresholds should be reasonable for spread monitoring."""
        for sym, thresh in THRESHOLDS.items():
            self.assertGreater(thresh, 0, f"{sym} threshold <= 0")
            self.assertLess(thresh, 200, f"{sym} threshold suspiciously high: {thresh}")


# ============================================================================
# 5. TIMESTAMP EDGE CASES
# ============================================================================

class TestTimestampEdgeCases(unittest.TestCase):
    """Test timestamp handling and parsing issues."""

    def test_tick_ts_is_string_not_datetime(self):
        """ts is stored as raw string - no parsing, no validation."""
        bridge = TickBridge()
        bridge.inject_tick(100, 100.0, ts="not-a-timestamp")
        tick = bridge.get_tick(100)
        self.assertEqual(tick.ts, "not-a-timestamp")
        # No validation that ts is a valid timestamp at all

    def test_tick_ts_empty_string(self):
        bridge = TickBridge()
        bridge.inject_tick(100, 100.0, ts="")
        tick = bridge.get_tick(100)
        self.assertEqual(tick.ts, "")

    def test_ts_with_timezone_info(self):
        """What if feed sends ISO format with timezone?"""
        bridge = TickBridge()
        bridge.inject_tick(100, 100.0, ts="2026-10-06T09:20:00+05:30")
        tick = bridge.get_tick(100)
        # Stored as-is; string comparison with different format will break
        self.assertEqual(tick.ts, "2026-10-06T09:20:00+05:30")

    def test_ts_format_inconsistency(self):
        """If feed changes format mid-session, backward-ts detection breaks."""
        # validator.py compares strings: "2026-10-06 09:20:00.000" vs "2026-10-06T09:20:01"
        # The "T" format is lexicographically > " " format, so it would NOT
        # be detected as backward even if it IS backward in time
        ts1 = "2026-10-06 15:00:00.000"  # 3 PM space format
        ts2 = "2026-10-06T09:20:00"      # 9:20 AM T format (EARLIER in time)
        self.assertGreater(ts2, ts1, "BUG: T-format 9AM > space-format 3PM lexicographically")
        # This means a format change would defeat backward-timestamp detection

    def test_ist_timezone_object(self):
        """IST timezone offset is correct."""
        from datetime import timedelta, datetime
        offset = IST.utcoffset(None)
        self.assertEqual(offset, timedelta(hours=5, minutes=30))

    def test_recv_mono_ns_is_monotonic(self):
        """recv_mono_ns uses time.monotonic_ns - verify it's actually set."""
        bridge = TickBridge()
        before = time.monotonic_ns()
        bridge.inject_tick(100, 100.0)
        after = time.monotonic_ns()
        tick = bridge.get_tick(100)
        self.assertGreaterEqual(tick.recv_mono_ns, before)
        self.assertLessEqual(tick.recv_mono_ns, after)


# ============================================================================
# 6. STOP/LIFECYCLE EDGE CASES
# ============================================================================

class TestLifecycleEdgeCases(unittest.TestCase):
    """Test start/stop/restart scenarios."""

    def test_stop_race_with_loop(self):
        """stop() accesses self._loop which could be set to None by _run()."""
        bridge = TickBridge(uri="ws://127.0.0.1:19999")
        bridge.start()
        time.sleep(0.1)
        # Rapid stop - loop might be in various states
        bridge.stop()

    def test_restart_after_stop(self):
        """Can we restart after stopping?"""
        bridge = TickBridge(uri="ws://127.0.0.1:19999")
        bridge.start()
        time.sleep(0.3)
        bridge.stop()
        # Try restart
        bridge.start()
        time.sleep(0.3)
        bridge.stop()

    def test_get_tick_after_stop(self):
        """Data should still be readable after stop."""
        bridge = TickBridge()
        bridge.inject_tick(100, 100.0)
        bridge.stop()
        tick = bridge.get_tick(100)
        self.assertIsNotNone(tick)

    def test_inject_after_stop(self):
        """Can still inject after stop (no guard)."""
        bridge = TickBridge()
        bridge.stop()
        bridge.inject_tick(100, 100.0)
        self.assertIsNotNone(bridge.get_tick(100))


# ============================================================================
# 7. VALIDATOR INTEGRATION EDGE CASES
# ============================================================================

class TestValidatorEdgeCases(unittest.TestCase):
    """Test the validator with edge cases from bridge."""

    def setUp(self):
        from algo_engine.validator import TickValidator
        self.validator = TickValidator()

    def test_zero_ltp_rejected(self):
        tick = Tick(token=1, ltp=0.0, ts="2026-10-06 09:20:00.000", recv_mono_ns=0)
        valid, reason = self.validator.check(tick)
        self.assertFalse(valid)
        self.assertEqual(reason, "ltp_zero")

    def test_negative_ltp_rejected(self):
        tick = Tick(token=1, ltp=-100.0, ts="2026-10-06 09:20:00.000", recv_mono_ns=0)
        valid, reason = self.validator.check(tick)
        self.assertFalse(valid)
        self.assertEqual(reason, "ltp_zero")  # reason name is misleading for negative

    def test_none_ltp_crashes_validator(self):
        """If bridge stores None ltp, validator comparison tick.ltp <= 0 crashes."""
        tick = Tick(token=1, ltp=None, ts="2026-10-06 09:20:00.000", recv_mono_ns=0)
        with self.assertRaises(TypeError):
            self.validator.check(tick)

    def test_string_ltp_crashes_validator(self):
        """If bridge stores string ltp, comparison crashes."""
        tick = Tick(token=1, ltp="100.0", ts="2026-10-06 09:20:00.000", recv_mono_ns=0)
        with self.assertRaises(TypeError):
            self.validator.check(tick)

    def test_backward_ts_string_comparison(self):
        """String comparison works for same-format timestamps."""
        t1 = Tick(token=1, ltp=100.0, ts="2026-10-06 09:20:00.000", recv_mono_ns=0)
        t2 = Tick(token=1, ltp=100.0, ts="2026-10-06 09:19:59.000", recv_mono_ns=0)
        valid1, _ = self.validator.check(t1)
        valid2, reason = self.validator.check(t2)
        self.assertTrue(valid1)
        self.assertFalse(valid2)
        self.assertEqual(reason, "ts_backward")

    def test_same_ts_not_rejected(self):
        """Equal timestamps: tick.ts <= prev_ts means equal is ALSO rejected."""
        t1 = Tick(token=1, ltp=100.0, ts="2026-10-06 09:20:00.000", recv_mono_ns=0)
        t2 = Tick(token=1, ltp=100.0, ts="2026-10-06 09:20:00.000", recv_mono_ns=0)
        valid1, _ = self.validator.check(t1)
        valid2, reason = self.validator.check(t2)
        self.assertTrue(valid1)
        self.assertFalse(valid2, "BUG: same-timestamp tick rejected (may drop valid ticks)")
        self.assertEqual(reason, "ts_backward")

    def test_empty_ts_never_rejected_as_backward(self):
        """Empty string is <= any non-empty string, so second tick with empty ts is rejected."""
        t1 = Tick(token=1, ltp=100.0, ts="", recv_mono_ns=0)
        t2 = Tick(token=1, ltp=100.0, ts="", recv_mono_ns=0)
        valid1, _ = self.validator.check(t1)
        valid2, reason = self.validator.check(t2)
        self.assertTrue(valid1)
        # "" <= "" is True, so this gets rejected
        self.assertFalse(valid2, "BUG: empty ts ticks after first are rejected")

    def test_first_tick_with_empty_ts_accepted(self):
        t1 = Tick(token=1, ltp=100.0, ts="", recv_mono_ns=0)
        valid, _ = self.validator.check(t1)
        self.assertTrue(valid)

    def test_prev_ts_unbounded_growth(self):
        """_prev_ts dict grows forever - one entry per unique token."""
        for i in range(10000):
            tick = Tick(token=i, ltp=100.0, ts="2026-10-06 09:20:00.000", recv_mono_ns=0)
            self.validator.check(tick)
        # _prev_ts has 10000 entries, never cleaned
        self.assertEqual(len(self.validator._prev_ts), 10000)

    def test_different_tokens_independent(self):
        """Different tokens should not interfere with each other's ts tracking."""
        t1 = Tick(token=1, ltp=100.0, ts="2026-10-06 09:20:00.000", recv_mono_ns=0)
        t2 = Tick(token=2, ltp=200.0, ts="2026-10-06 09:19:00.000", recv_mono_ns=0)
        valid1, _ = self.validator.check(t1)
        valid2, _ = self.validator.check(t2)
        self.assertTrue(valid1)
        self.assertTrue(valid2)  # Different token, earlier ts is fine


# ============================================================================
# 8. TYPE SAFETY / EDGE CASES IN TICK DATACLASS
# ============================================================================

class TestTickDataclassEdgeCases(unittest.TestCase):
    """Test Tick dataclass boundary conditions."""

    def test_tick_with_nan_ltp(self):
        """NaN passes through - not caught by ltp <= 0 check."""
        import math
        tick = Tick(token=1, ltp=float('nan'), ts="", recv_mono_ns=0)
        self.assertTrue(math.isnan(tick.ltp))
        # NaN <= 0 is False, so validator would PASS this tick!
        from algo_engine.validator import TickValidator
        v = TickValidator()
        valid, reason = v.check(tick)
        self.assertTrue(valid, "BUG: NaN LTP passes validator (NaN <= 0 is False)")

    def test_tick_with_inf_ltp(self):
        """Infinity passes through."""
        tick = Tick(token=1, ltp=float('inf'), ts="", recv_mono_ns=0)
        from algo_engine.validator import TickValidator
        v = TickValidator()
        valid, _ = v.check(tick)
        self.assertTrue(valid, "BUG: inf LTP passes validator")

    def test_tick_with_very_large_ltp(self):
        tick = Tick(token=1, ltp=1e308, ts="", recv_mono_ns=0)
        self.assertEqual(tick.ltp, 1e308)

    def test_tick_info_default_factory(self):
        """Each Tick should get its own dict, not share a default."""
        t1 = Tick(token=1, ltp=1.0, ts="", recv_mono_ns=0)
        t2 = Tick(token=2, ltp=2.0, ts="", recv_mono_ns=0)
        t1.info["key"] = "value"
        self.assertNotIn("key", t2.info, "BUG: shared default dict between instances")

    def test_ohlc_division_precision(self):
        """OHLC is divided by 100 - check precision for large values."""
        bridge = TickBridge()
        msg = json.dumps({
            "type": "ticks",
            "data": [{
                "token": 100, "ltp_r": 2850.55, "ts": "",
                "open": 284055, "high": 286599, "low": 283001, "close": 284550,
            }],
        })
        bridge._on_message(msg)
        tick = bridge.get_tick(100)
        self.assertAlmostEqual(tick.open, 2840.55, places=2)
        self.assertAlmostEqual(tick.high, 2865.99, places=2)
        self.assertAlmostEqual(tick.low, 2830.01, places=2)
        self.assertAlmostEqual(tick.close, 2845.50, places=2)


# ============================================================================
# 9. WEBSOCKET RECONNECTION SCENARIOS
# ============================================================================

class TestWebSocketReconnection(unittest.TestCase):
    """Test connection failure and recovery behavior."""

    def test_connect_to_invalid_port(self):
        """Should not crash, should keep retrying."""
        bridge = TickBridge(uri="ws://127.0.0.1:1")  # invalid port
        bridge.start()
        time.sleep(3)  # Let it retry a couple times
        self.assertFalse(bridge.connected)
        bridge.stop()

    def test_data_survives_reconnect(self):
        """Data in bridge should survive a disconnect/reconnect cycle."""
        bridge = TickBridge()
        bridge.inject_tick(100, 100.0)
        # Simulate reconnect - data should still be there
        tick = bridge.get_tick(100)
        self.assertIsNotNone(tick)
        self.assertAlmostEqual(tick.ltp, 100.0)

    def test_no_backoff_on_reconnect(self):
        """Verify there's no exponential backoff - just fixed 2s.
        This is a production risk: if server is down, we spam it."""
        bridge = TickBridge(uri="ws://127.0.0.1:19999")
        bridge.start()
        # The connect loop retries every 2s with no backoff
        # This is by design but worth noting
        time.sleep(0.5)
        bridge.stop()


# ============================================================================
# 10. SPREAD AND FRESHNESS EDGE CASES
# ============================================================================

class TestSpreadFreshnessEdgeCases(unittest.TestCase):
    """Test freshness window edge cases."""

    def test_freshness_window_exactly_at_boundary(self):
        """Token at exactly 500ms - is it fresh or stale?"""
        bridge = TickBridge()
        bridge.inject_tick(100, 100.0)
        # Manually set recv_time to exactly 500ms ago
        bridge._recv_times[100] = time.monotonic_ns() - 500_000_000
        fresh = bridge.fresh_tokens(max_age_ms=500)
        # Boundary: (now - recv) / 1e6 <= 500
        # This is timing-dependent, just check it doesn't crash
        self.assertIsInstance(fresh, list)

    def test_tick_age_returns_negative(self):
        """Can tick_age_ms ever return negative? (clock adjustment)"""
        bridge = TickBridge()
        # Set recv_time to the future
        bridge._recv_times[100] = time.monotonic_ns() + 1_000_000_000
        age = bridge.tick_age_ms(100)
        # age would be negative since recv is in the future
        if age is not None and age < 0:
            print(f"\n  [BUG] tick_age_ms returned negative: {age}")

    def test_spread_freshness_constant_unused(self):
        """SPREAD_FRESHNESS_SECONDS is defined but is it used anywhere in bridge?"""
        from algo_engine.config import SPREAD_FRESHNESS_SECONDS
        self.assertEqual(SPREAD_FRESHNESS_SECONDS, 60)
        # This constant is defined but bridge.py doesn't reference it
        # It must be used in a later step - verify it's not dead code


if __name__ == "__main__":
    unittest.main(verbosity=2)
