"""
Adversarial / stress tests for TickValidator (Step 3 audit).
Temporary file -- NOT to be merged. Created for code audit on 2026-10-05.
"""
import sys
import threading
import time
import unittest

sys.path.insert(0, r"C:\Users\Ankit\Desktop\RS FOLDER\rollover-react\market_data_server")

from algo_engine.bridge import Tick
from algo_engine.validator import TickValidator


# ── FINDING 1: None timestamp PERMANENTLY disables backward checking ─────────

class TestNoneTimestamp(unittest.TestCase):
    """
    tick.ts=None is the Tick dataclass default for recv_mono_ns-only ticks.
    Line 26: if prev_ts is not None and tick.ts and tick.ts <= prev_ts
    Two guards: 'prev_ts is not None' and 'tick.ts' (truthy check).
    Neither crashes, but None stored as prev_ts DISABLES backward checking
    for that token FOREVER (until reset).
    """

    def test_none_ts_first_tick_passes(self):
        """First tick with None ts passes (short-circuit on falsy tick.ts)."""
        v = TickValidator()
        tick = Tick(token=100, ltp=100.0, ts=None, recv_mono_ns=0)
        ok, reason = v.check(tick)
        self.assertTrue(ok)

    def test_none_ts_stored_as_prev(self):
        """None gets stored in _prev_ts -- this is the seed of the logic bug."""
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts=None, recv_mono_ns=0))
        self.assertIsNone(v.get_prev_ts(100))

    def test_none_ts_permanently_disables_backward_check(self):
        """
        LOGIC BUG: After None ts is stored, prev_ts is None.
        Line 26: 'prev_ts is not None' is False -> backward check SKIPPED.
        This means ALL future ticks for this token bypass backward detection.
        No crash, but silent data quality failure in production.
        """
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts=None, recv_mono_ns=0))
        # This tick is clearly backward in time, but passes because prev_ts is None
        ok, reason = v.check(Tick(token=100, ltp=101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0))
        self.assertTrue(ok, "BUG: backward tick passed because prev_ts is None")
        self.assertIsNone(reason)
        # Now prev_ts is "2026-10-01 09:20:00.000"
        # But another None ts resets the problem
        v.check(Tick(token=100, ltp=102.0, ts=None, recv_mono_ns=0))
        # Again backward check disabled
        ok2, _ = v.check(Tick(token=100, ltp=103.0, ts="2026-10-01 09:19:00.000", recv_mono_ns=0))
        self.assertTrue(ok2, "BUG: clearly backward tick passes after None ts")

    def test_none_ts_no_crash_but_silent_failure(self):
        """
        The guard on line 26 prevents TypeError but creates a SILENT failure.
        In production, this means out-of-order ticks go undetected.
        """
        v = TickValidator()
        v.process_tick(Tick(token=100, ltp=100.0, ts=None, recv_mono_ns=0))
        # No crash -- but backward detection is now broken for token 100
        ok = v.process_tick(Tick(token=100, ltp=101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0))
        self.assertTrue(ok)

    def test_none_ts_multiple_tokens_independent(self):
        """None ts for token 100 doesn't affect token 200."""
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts=None, recv_mono_ns=0))
        # Different token works normally
        v.check(Tick(token=200, ltp=200.0, ts="2026-10-01 09:30:00.000", recv_mono_ns=0))
        ok, reason = v.check(Tick(token=200, ltp=201.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0))
        self.assertFalse(ok, "Token 200 backward detection still works")
        self.assertEqual(reason, "ts_backward")


# ── FINDING 2: Empty string timestamp silently disables all backward checking ─

class TestEmptyStringTimestamp(unittest.TestCase):
    """Empty string is falsy, so the backward check is skipped entirely."""

    def test_empty_ts_never_rejected_for_backward(self):
        """Even after a valid ts, empty ts always passes -- no backward check."""
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts="2026-10-01 09:30:00.000", recv_mono_ns=0))
        # Empty ts skips backward check (falsy short-circuit)
        ok, reason = v.check(Tick(token=100, ltp=101.0, ts="", recv_mono_ns=0))
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_empty_ts_stored_then_any_ts_passes(self):
        """
        After empty ts is stored as prev, ANY string is >= "" lexicographically,
        so backward detection is PERMANENTLY broken for this token.
        """
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts="", recv_mono_ns=0))
        # Even a clearly backward timestamp passes because "anything" > ""
        ok, _ = v.check(Tick(token=100, ltp=101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0))
        self.assertTrue(ok)

    def test_empty_ts_chain_blankets_over_valid_data(self):
        """
        Alternating empty and valid timestamps: every empty one resets
        the effective baseline, making backward detection unreliable.
        """
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts="2026-10-01 09:30:00.000", recv_mono_ns=0))
        v.check(Tick(token=100, ltp=101.0, ts="", recv_mono_ns=0))  # stored, skips check
        # This is clearly backward from 09:30 but prev is now ""
        ok, _ = v.check(Tick(token=100, ltp=102.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0))
        self.assertTrue(ok, "BUG: backward tick passed because prev_ts was empty string")


# ── FINDING 3: String comparison gives wrong results for non-ISO formats ─────

class TestMixedTimestampFormats(unittest.TestCase):
    """
    The validator uses raw string comparison (line 26: tick.ts <= prev_ts).
    This ONLY works correctly for fixed-width ISO-format timestamps.
    """

    def test_epoch_ms_vs_iso_string(self):
        """If bridge sends epoch ms as string, comparison with ISO is meaningless."""
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts="1696137000000", recv_mono_ns=0))
        # "1696..." < "2026..." lexicographically, so this looks "forward"
        ok, _ = v.check(Tick(token=100, ltp=101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0))
        self.assertTrue(ok, "Mixed formats: string comparison is meaningless")

    def test_different_length_timestamps(self):
        """Shorter string can be 'less' even if time is later."""
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts="2026-10-01 09:20:00", recv_mono_ns=0))
        # "2026-10-01 09:20:00.000" > "2026-10-01 09:20:00" (longer string)
        ok, _ = v.check(Tick(token=100, ltp=101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0))
        self.assertTrue(ok)

    def test_date_format_change_silent_failure(self):
        """
        If upstream changes from '2026-10-01 09:20:00.000' to '01/10/2026 09:20:00',
        string comparison silently breaks -- "01/10..." < "2026-..." so it looks backward.
        """
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0))
        ok, reason = v.check(Tick(token=100, ltp=101.0, ts="01/10/2026 09:21:00", recv_mono_ns=0))
        self.assertFalse(ok, "Format change causes false rejection")
        self.assertEqual(reason, "ts_backward")

    def test_single_char_timestamps(self):
        """Existing test uses 'T1', 'T2' etc. -- these work by coincidence."""
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts="T1", recv_mono_ns=0))
        ok, _ = v.check(Tick(token=100, ltp=101.0, ts="T2", recv_mono_ns=0))
        self.assertTrue(ok)
        # But "T10" < "T2" lexicographically!
        ok2, reason = v.check(Tick(token=100, ltp=102.0, ts="T10", recv_mono_ns=0))
        self.assertFalse(ok2, "BUG: T10 < T2 lexicographically, falsely flagged backward")
        self.assertEqual(reason, "ts_backward")


# ── FINDING 4: Concurrent access from 10+ threads ──────────────────────────

class TestHeavyConcurrency(unittest.TestCase):
    """Stress test with many threads hitting the same validator."""

    def test_10_threads_same_token(self):
        """10 threads all writing to the same token -- lock should serialize."""
        v = TickValidator()
        errors = []
        results = {"passed": 0, "rejected": 0}
        lock = threading.Lock()

        def worker(thread_id):
            try:
                local_passed = 0
                local_rejected = 0
                for i in range(200):
                    ok, _ = v.check(Tick(
                        token=100, ltp=100.0 + i * 0.01,
                        ts=f"T{thread_id:02d}_{i:06d}", recv_mono_ns=0
                    ))
                    if ok:
                        local_passed += 1
                    else:
                        local_rejected += 1
                with lock:
                    results["passed"] += local_passed
                    results["rejected"] += local_rejected
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [])
        total = results["passed"] + results["rejected"]
        self.assertEqual(total, 2000)
        self.assertEqual(v.passed_count + v.rejected_count, 2000)

    def test_concurrent_read_write_properties(self):
        """Read properties while writes are happening -- no torn reads."""
        v = TickValidator()
        errors = []

        def writer():
            try:
                for i in range(1000):
                    v.check(Tick(token=100, ltp=100.0, ts=f"T{i:06d}", recv_mono_ns=0))
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(1000):
                    _ = v.passed_count
                    _ = v.rejected_count
                    _ = v.rejected_by_reason
                    _ = v.get_prev_ts(100)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(5)]
        threads += [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [])

    def test_concurrent_same_token_same_timestamp(self):
        """
        Race condition test: two threads send identical timestamps for same token.
        Only one should win; the other should be rejected as 'ts_backward' (equal).
        But which one wins is non-deterministic.
        """
        v = TickValidator()
        results = {"passed": 0, "rejected": 0}
        lock = threading.Lock()
        barrier = threading.Barrier(2)

        def worker(ltp_val):
            barrier.wait()
            ok, _ = v.check(Tick(token=100, ltp=ltp_val, ts="2026-10-01 09:20:00.000", recv_mono_ns=0))
            with lock:
                if ok:
                    results["passed"] += 1
                else:
                    results["rejected"] += 1

        t1 = threading.Thread(target=worker, args=(100.0,))
        t2 = threading.Thread(target=worker, args=(101.0,))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        # Exactly one should pass (first tick) and one should be rejected (same ts)
        self.assertEqual(results["passed"] + results["rejected"], 2)
        self.assertEqual(results["passed"], 1)
        self.assertEqual(results["rejected"], 1)


# ── FINDING 5: Token not in config ──────────────────────────────────────────

class TestUnknownToken(unittest.TestCase):
    """Validator has no concept of 'known' tokens -- any int is accepted."""

    def test_arbitrary_token_accepted(self):
        """Validator doesn't check against any config/token list."""
        v = TickValidator()
        ok, _ = v.check(Tick(token=999999999, ltp=100.0, ts="T1", recv_mono_ns=0))
        self.assertTrue(ok)

    def test_negative_token_accepted(self):
        """Even negative token IDs work -- no validation."""
        v = TickValidator()
        ok, _ = v.check(Tick(token=-1, ltp=100.0, ts="T1", recv_mono_ns=0))
        self.assertTrue(ok)

    def test_zero_token_accepted(self):
        v = TickValidator()
        ok, _ = v.check(Tick(token=0, ltp=100.0, ts="T1", recv_mono_ns=0))
        self.assertTrue(ok)

    def test_unknown_token_pollutes_prev_ts(self):
        """
        A stray token from a bad websocket message gets permanent state in _prev_ts.
        This is the memory leak vector.
        """
        v = TickValidator()
        for i in range(1000):
            v.check(Tick(token=i, ltp=100.0, ts=f"T{i}", recv_mono_ns=0))
        # All 1000 tokens now have entries in _prev_ts
        # There is no way to remove individual entries
        self.assertIsNotNone(v.get_prev_ts(500))


# ── FINDING 6: reset() during concurrent processing ────────────────────────

class TestResetConcurrency(unittest.TestCase):
    """What happens when reset() is called while ticks are being processed?"""

    def test_reset_during_processing(self):
        """
        reset() clears _prev_ts. A tick in-flight after reset sees prev_ts=None,
        so it passes as 'first tick' even if it's actually a duplicate.
        """
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0))
        self.assertEqual(v.passed_count, 1)

        v.reset()

        # Same timestamp that was already seen -- passes because prev_ts was cleared
        ok, _ = v.check(Tick(token=100, ltp=101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0))
        self.assertTrue(ok, "After reset, previously-seen timestamp passes again")
        self.assertEqual(v.passed_count, 1)  # counter was also reset

    def test_reset_while_threads_active(self):
        """Reset in the middle of concurrent writes -- counters may be inconsistent."""
        v = TickValidator()
        errors = []
        barrier = threading.Barrier(3)  # 2 writers + 1 resetter

        def writer(tid):
            try:
                barrier.wait()
                for i in range(200):
                    v.check(Tick(token=tid, ltp=100.0, ts=f"T{tid}_{i:06d}", recv_mono_ns=0))
            except Exception as e:
                errors.append(e)

        def resetter():
            try:
                barrier.wait()
                time.sleep(0.001)  # let writers start
                v.reset()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=(100,)),
            threading.Thread(target=writer, args=(200,)),
            threading.Thread(target=resetter),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [])
        # After reset, counters may not add up to total ticks processed
        # This is a data integrity issue, not a crash
        total_accounted = v.passed_count + v.rejected_count
        # total_accounted may be < 400 because reset zeroed the counters mid-stream

    def test_double_reset(self):
        """Double reset is harmless but shows there's no guard."""
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts="T1", recv_mono_ns=0))
        v.reset()
        v.reset()  # no error
        self.assertEqual(v.passed_count, 0)


# ── FINDING 7: Memory growth with many unique tokens ────────────────────────

class TestMemoryGrowth(unittest.TestCase):
    """_prev_ts dict grows unbounded -- simulate expiry rollover scenario."""

    def test_unbounded_growth(self):
        """
        Simulate 57 tokens (19 stocks x 3) plus expired tokens accumulating.
        In production, expired fut tokens are never removed from _prev_ts.
        """
        v = TickValidator()
        # Simulate 3 months of daily token changes
        for day in range(60):
            for stock_id in range(19):
                for fut_type in range(3):
                    token = day * 1000 + stock_id * 10 + fut_type
                    v.check(Tick(token=token, ltp=100.0, ts=f"T{day}", recv_mono_ns=0))

        # _prev_ts has entries for ALL tokens ever seen, including expired ones
        # We can't directly check len(_prev_ts) but we can check individual tokens
        # Day 0 tokens should still be in there
        self.assertIsNotNone(v.get_prev_ts(0))     # day=0, stock=0, fut=0
        self.assertIsNotNone(v.get_prev_ts(59000 + 18 * 10 + 2))  # last token

    def test_memory_growth_with_random_tokens(self):
        """Simulate stray/malformed tokens from websocket polluting the dict."""
        v = TickValidator()
        for i in range(10000):
            v.check(Tick(token=i * 3, ltp=100.0, ts=f"T{i}", recv_mono_ns=0))

        # All 10000 tokens are now in _prev_ts with no eviction
        # In production this is a slow memory leak over trading days
        self.assertIsNotNone(v.get_prev_ts(9999 * 3))

    def test_no_eviction_mechanism(self):
        """Verify there is no way to remove individual token entries."""
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts="T1", recv_mono_ns=0))
        # The only way to clear is reset() which clears EVERYTHING
        # No remove_token() or evict() method exists
        self.assertFalse(hasattr(v, 'remove_token'))
        self.assertFalse(hasattr(v, 'evict'))
        # After reset, ALL state is lost including valid tokens
        v.reset()
        self.assertIsNone(v.get_prev_ts(100))


# ── FINDING 8: LTP edge cases with special float values ─────────────────────

class TestLTPSpecialFloats(unittest.TestCase):
    """Test special float values that could slip through from JSON parsing."""

    def test_nan_ltp_passes(self):
        """
        float('nan') > 0 is False, float('nan') <= 0 is also False.
        So NaN LTP PASSES the ltp<=0 check! This is a silent data corruption.
        """
        v = TickValidator()
        tick = Tick(token=100, ltp=float('nan'), ts="T1", recv_mono_ns=0)
        ok, reason = v.check(tick)
        self.assertTrue(ok, "BUG: NaN LTP passes validation because NaN <= 0 is False")

    def test_infinity_ltp_passes(self):
        """float('inf') > 0, so it passes. May come from bad division in upstream."""
        v = TickValidator()
        tick = Tick(token=100, ltp=float('inf'), ts="T1", recv_mono_ns=0)
        ok, _ = v.check(tick)
        self.assertTrue(ok)

    def test_negative_infinity_rejected(self):
        v = TickValidator()
        tick = Tick(token=100, ltp=float('-inf'), ts="T1", recv_mono_ns=0)
        ok, reason = v.check(tick)
        self.assertFalse(ok)
        self.assertEqual(reason, "ltp_zero")

    def test_subnormal_ltp_passes(self):
        """Extremely small subnormal float passes."""
        v = TickValidator()
        tick = Tick(token=100, ltp=5e-324, ts="T1", recv_mono_ns=0)
        ok, _ = v.check(tick)
        self.assertTrue(ok)


# ── FINDING 9: rejected_by_reason dict mutation risk ────────────────────────

class TestRejectedByReasonIntegrity(unittest.TestCase):
    """
    The _rejected_by_reason dict has fixed keys. But what if someone adds a key?
    The reset() method iterates `for k in self._rejected_by_reason` -- so new keys
    would be reset too. The rejected_by_reason property returns a copy. Safe.
    But there's no protection against external code adding keys via _rejected_by_reason.
    """

    def test_internal_dict_not_exposed(self):
        """rejected_by_reason returns a copy -- mutation doesn't affect internal."""
        v = TickValidator()
        reasons = v.rejected_by_reason
        reasons["new_reason"] = 999
        # Internal dict should not have "new_reason"
        internal = v.rejected_by_reason
        self.assertNotIn("new_reason", internal)

    def test_reset_with_extra_key_in_dict(self):
        """
        If somehow a new key gets into _rejected_by_reason, reset() will
        iterate it and reset it to 0 -- but won't remove it.
        """
        v = TickValidator()
        # Simulate internal corruption (shouldn't happen but defense-in-depth matters)
        v._rejected_by_reason["injected_key"] = 5
        v.reset()
        # The injected key still exists but is zeroed
        self.assertEqual(v._rejected_by_reason["injected_key"], 0)
        self.assertIn("injected_key", v.rejected_by_reason)


# ── FINDING 10: Tick dataclass type mismatches ──────────────────────────────

class TestTickTypeMismatches(unittest.TestCase):
    """The Tick dataclass doesn't enforce types -- what if fields are wrong type?"""

    def test_string_ltp(self):
        """If ltp is a string (bad JSON parse), comparison ltp <= 0 crashes."""
        v = TickValidator()
        tick = Tick(token=100, ltp="2850.0", ts="T1", recv_mono_ns=0)
        with self.assertRaises(TypeError):
            v.check(tick)

    def test_string_token(self):
        """Token as string -- used as dict key, works but semantically wrong."""
        v = TickValidator()
        tick = Tick(token="100", ltp=100.0, ts="T1", recv_mono_ns=0)
        ok, _ = v.check(tick)
        self.assertTrue(ok)
        # Now "100" and 100 are DIFFERENT keys in _prev_ts
        self.assertIsNotNone(v.get_prev_ts("100"))
        self.assertIsNone(v.get_prev_ts(100))


# ── FINDING 11: Timestamp comparison is not transitive across formats ───────

class TestTimestampTransitivity(unittest.TestCase):
    """String comparison can violate transitivity with mixed formats."""

    def test_transitivity_break(self):
        """
        If timestamps come in different formats, A > B and B > C doesn't imply A > C.
        """
        v = TickValidator()
        # A: ISO format
        v.check(Tick(token=100, ltp=100.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0))
        # B: epoch string that is > A lexicographically
        ok_b, _ = v.check(Tick(token=100, ltp=101.0, ts="9999-99-99", recv_mono_ns=0))
        self.assertTrue(ok_b)
        # C: ISO format that is > B lexicographically but actually earlier in time
        ok_c, _ = v.check(Tick(token=100, ltp=102.0, ts="9999-99-99.001", recv_mono_ns=0))
        self.assertTrue(ok_c)


# ── FINDING 12: Bridge sends ts="" by default ───────────────────────────────

class TestBridgeDefaultTimestamp(unittest.TestCase):
    """
    bridge.py line 112: ts=snap.get("ts", "")
    If the websocket message has no "ts" field, the Tick gets ts="".
    This means ALL backward detection is disabled for that tick.
    """

    def test_bridge_no_ts_field_produces_empty_string(self):
        """Simulate bridge behavior when 'ts' is missing from websocket data."""
        import json
        from algo_engine.bridge import TickBridge
        bridge = TickBridge()
        msg = json.dumps({
            "type": "ticks",
            "data": [
                {"token": 100, "ltp_r": 2850.0,
                 "info": {"type": "future", "month": "current", "sym": "RELIANCE"}},
            ],
        })
        bridge._on_message(msg)
        tick = bridge.get_tick(100)
        self.assertEqual(tick.ts, "")

    def test_bridge_empty_ts_disables_backward_check(self):
        """End-to-end: bridge produces empty ts, validator can't detect backward."""
        import json
        from algo_engine.bridge import TickBridge
        bridge = TickBridge()
        validator = TickValidator()

        # First tick with valid ts
        msg1 = json.dumps({
            "type": "ticks",
            "data": [
                {"token": 100, "ltp_r": 2850.0, "ts": "2026-10-01 09:30:00.000",
                 "info": {"type": "future", "month": "current", "sym": "RELIANCE"}},
            ],
        })
        bridge._on_message(msg1)
        tick1 = bridge.get_tick(100)
        validator.process_tick(tick1)

        # Second tick WITHOUT ts field (bridge defaults to "")
        msg2 = json.dumps({
            "type": "ticks",
            "data": [
                {"token": 100, "ltp_r": 2851.0,
                 "info": {"type": "future", "month": "current", "sym": "RELIANCE"}},
            ],
        })
        bridge._on_message(msg2)
        tick2 = bridge.get_tick(100)
        self.assertEqual(tick2.ts, "")

        # This passes because empty ts skips backward check
        ok = validator.process_tick(tick2)
        self.assertTrue(ok)
        # And now prev_ts for token 100 is "" -- future backward detection broken
        self.assertEqual(validator.get_prev_ts(100), "")


# ── FINDING 13: No timestamp validation at all ──────────────────────────────

class TestGarbageTimestamps(unittest.TestCase):
    """Validator accepts any string as timestamp -- no format validation."""

    def test_garbage_ts_passes(self):
        v = TickValidator()
        ok, _ = v.check(Tick(token=100, ltp=100.0, ts="not-a-timestamp", recv_mono_ns=0))
        self.assertTrue(ok)

    def test_unicode_ts_passes(self):
        v = TickValidator()
        ok, _ = v.check(Tick(token=100, ltp=100.0, ts="\u0000\u0001\u0002", recv_mono_ns=0))
        self.assertTrue(ok)

    def test_whitespace_ts_passes(self):
        """Whitespace is truthy, so it gets stored and compared."""
        v = TickValidator()
        v.check(Tick(token=100, ltp=100.0, ts="   ", recv_mono_ns=0))
        # "   " is stored. Next tick: "2026..." > "   " so it passes
        ok, _ = v.check(Tick(token=100, ltp=101.0, ts="2026-10-01 09:20:00.000", recv_mono_ns=0))
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
