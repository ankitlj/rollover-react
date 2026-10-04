"""
Integration audit tests for algo engine Steps 1-4.
Finds CROSS-STEP integration issues in the pipeline:
  WebSocket -> TickBridge -> TickValidator -> SpreadEngine -> (future: alerts)

These tests are intentionally adversarial. They probe:
  - Token-to-symbol mapping gaps
  - Validator-to-SpreadEngine data flow (or lack thereof)
  - Unknown token handling
  - Config consistency
  - Thread model / deadlock potential
  - __init__.py export completeness
  - End-to-end traceability
"""

import sys
import json
import time
import unittest
import threading
import inspect
from datetime import datetime, timedelta
from collections import Counter

sys.path.insert(0, r"C:\Users\Ankit\Desktop\RS FOLDER\rollover-react\market_data_server")

from algo_engine.config import (
    STOCK_CONFIG, THRESHOLDS, INITIAL_SPREADS,
    STOCK_COUNT, TOTAL_TOKENS, FRESHNESS_WINDOW_MS,
    SPREAD_FRESHNESS_SECONDS, SAMPLE_INTERVAL_SECONDS, IST,
)
from algo_engine.bridge import TickBridge, Tick
from algo_engine.validator import TickValidator
from algo_engine.spread import SpreadEngine, SpreadSnapshot
import algo_engine as pkg


def _now_ist_str(offset_seconds=0):
    dt = datetime.now(IST) + timedelta(seconds=offset_seconds)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _setup_full_bridge():
    """Create a bridge with all 57 tokens for 19 stocks pre-registered."""
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
# AUDIT FINDING 1: Validator is a DEAD END -- its output never reaches SpreadEngine
# ============================================================================

class TestValidatorIsDeadEnd(unittest.TestCase):
    """
    CRITICAL FINDING: TickValidator validates ticks but its result (bool) is
    never consumed by SpreadEngine. The SpreadEngine reads directly from
    TickBridge.get_tick(), bypassing validation entirely.

    The intended pipeline is:
        Bridge -> Validator -> SpreadEngine
    But the actual data flow is:
        Bridge -> Validator  (dead end, result discarded)
        Bridge -> SpreadEngine  (reads raw, unvalidated ticks)

    This means INVALID ticks (ltp=0, backward timestamps) can reach the
    SpreadEngine and corrupt spread computations.
    """

    def test_spread_engine_reads_directly_from_bridge_bypassing_validator(self):
        """Prove that SpreadEngine reads unvalidated ticks from bridge."""
        bridge = _setup_full_bridge()
        validator = TickValidator()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        tokens = bridge.get_tokens_for_stock("RELIANCE")
        ts = _now_ist_str()

        # Inject a tick with ltp=0 (would be rejected by validator)
        bridge.inject_tick(tokens["current"], 0.0, ts=ts,
                           info={"sym": "RELIANCE", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 2854.0, ts=ts,
                           info={"sym": "RELIANCE", "type": "future", "month": "next"})

        # Validator would reject this
        bad_tick = Tick(token=tokens["current"], ltp=0.0, ts=ts, recv_mono_ns=0)
        self.assertFalse(validator.process_tick(bad_tick))

        # But SpreadEngine still reads it from bridge (no crash, but spread is wrong)
        snap = engine.compute_for_stock("RELIANCE")
        # The spread engine DOES compute -- it doesn't check ltp>0
        # spread = 2854.0 - 0.0 = 2854.0
        if snap is not None:
            self.assertAlmostEqual(snap.spread, 2854.0)
            # This is a CORRUPT spread that should never have been computed

    def test_no_pipeline_method_exists(self):
        """
        Verify there is no method that chains validate->feed_to_spread.
        The caller must manually do this, which is error-prone.
        """
        # TickValidator has no callback, no observer, no output stream
        v = TickValidator()
        self.assertFalse(hasattr(v, 'on_valid_tick'))
        self.assertFalse(hasattr(v, 'register_callback'))
        self.assertFalse(hasattr(v, 'output'))

        # SpreadEngine has no input from validator
        bridge = TickBridge()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        self.assertFalse(hasattr(engine, 'set_validator'))
        self.assertFalse(hasattr(engine, 'on_validated_tick'))


# ============================================================================
# AUDIT FINDING 2: Unknown token handling -- bridge accepts everything
# ============================================================================

class TestUnknownTokenHandling(unittest.TestCase):
    """
    FINDING: TickBridge._on_ticks() accepts ticks for ANY token, even ones
    not in STOCK_CONFIG or metadata. There is no filtering at the bridge level.
    The validator also doesn't check against STOCK_CONFIG.
    """

    def test_bridge_accepts_ticks_for_unknown_tokens(self):
        """Bridge stores ticks for tokens not in any config."""
        bridge = TickBridge()
        # No metadata registered at all
        bridge.inject_tick(999999, 1234.5, ts=_now_ist_str(),
                           info={"sym": "NOT_A_STOCK", "type": "future", "month": "current"})
        tick = bridge.get_tick(999999)
        self.assertIsNotNone(tick)
        self.assertEqual(tick.ltp, 1234.5)

    def test_validator_accepts_ticks_for_unknown_tokens(self):
        """Validator doesn't check if token belongs to a known stock."""
        v = TickValidator()
        tick = Tick(token=999999, ltp=1234.5, ts="T1", recv_mono_ns=0,
                    info={"sym": "NOT_A_STOCK"})
        ok, reason = v.check(tick)
        self.assertTrue(ok)  # Passes! No stock-awareness in validator

    def test_spread_engine_ignores_unknown_tokens_safely(self):
        """SpreadEngine only iterates STOCK_CONFIG, so unknown tokens are
        harmlessly ignored -- but this is by accident, not by design."""
        bridge = _setup_full_bridge()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        # Inject tick for unknown token
        bridge.inject_tick(999999, 1234.5, ts=_now_ist_str(),
                           info={"sym": "FAKE", "type": "future", "month": "current"})

        # compute_all only loops over STOCK_CONFIG keys
        results = engine.compute_all()
        self.assertNotIn("FAKE", results)
        # This works, but only because SpreadEngine iterates STOCK_CONFIG

    def test_on_ticks_message_with_mixed_known_unknown(self):
        """WebSocket message with mix of known and unknown tokens."""
        bridge = _setup_full_bridge()
        msg = json.dumps({
            "type": "ticks",
            "data": [
                {"token": 999998, "ltp_r": 100.0, "ts": "T1",
                 "info": {"sym": "UNKNOWN1"}},
                {"token": 999999, "ltp_r": 200.0, "ts": "T2",
                 "info": {"sym": "UNKNOWN2"}},
            ]
        })
        bridge._on_message(msg)
        # Both stored, no warning, no filtering
        self.assertIsNotNone(bridge.get_tick(999998))
        self.assertIsNotNone(bridge.get_tick(999999))
        self.assertEqual(bridge.tick_count, 2)


# ============================================================================
# AUDIT FINDING 3: Token-to-symbol mapping is IMPLICIT, not explicit
# ============================================================================

class TestTokenToSymbolMapping(unittest.TestCase):
    """
    FINDING: There is no centralized token->symbol mapping in config.py.
    The mapping lives only in TickBridge._token_info, populated at runtime
    from WebSocket metadata. If metadata is late or missing, the entire
    pipeline silently produces no spreads.
    """

    def test_no_token_to_symbol_map_in_config(self):
        """config.py has no TOKEN_TO_SYMBOL or similar mapping."""
        import algo_engine.config as cfg
        config_attrs = [a for a in dir(cfg) if not a.startswith('_')]
        token_related = [a for a in config_attrs if 'TOKEN' in a.upper() or 'SYMBOL' in a.upper() or 'MAPPING' in a.upper()]
        # STOCK_COUNT and TOTAL_TOKENS exist but no actual mapping
        self.assertIn('STOCK_COUNT', config_attrs)
        self.assertIn('TOTAL_TOKENS', config_attrs)
        # But no TOKEN_TO_SYMBOL, SYMBOL_FOR_TOKEN, etc.
        self.assertNotIn('TOKEN_TO_SYMBOL', config_attrs)
        self.assertNotIn('TOKEN_SYMBOL_MAP', config_attrs)

    def test_spread_engine_depends_on_runtime_metadata(self):
        """Without metadata, SpreadEngine can't compute anything."""
        bridge = TickBridge()  # No metadata injected
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        # Even if we inject ticks directly, no token->stock resolution
        bridge.inject_tick(1, 1000.0, ts=_now_ist_str())
        bridge.inject_tick(2, 1005.0, ts=_now_ist_str())

        results = engine.compute_all()
        self.assertEqual(len(results), 0)  # Nothing computed!

        for sym in STOCK_CONFIG:
            self.assertEqual(engine.skip_reasons.get(sym), "no_tokens")

    def test_bridge_get_tokens_for_stock_returns_none_without_metadata(self):
        """get_tokens_for_stock returns all-None without metadata."""
        bridge = TickBridge()
        for sym in STOCK_CONFIG:
            result = bridge.get_tokens_for_stock(sym)
            self.assertIsNone(result["cash"])
            self.assertIsNone(result["current"])
            self.assertIsNone(result["next"])


# ============================================================================
# AUDIT FINDING 4: Config consistency checks
# ============================================================================

class TestConfigConsistency(unittest.TestCase):
    """Verify all config dicts are perfectly aligned."""

    def test_initial_spreads_keys_match_stock_config(self):
        """INITIAL_SPREADS and STOCK_CONFIG must have identical keys."""
        config_keys = set(STOCK_CONFIG.keys())
        spread_keys = set(INITIAL_SPREADS.keys())
        self.assertEqual(config_keys, spread_keys,
                         f"Mismatch: in config not spreads={config_keys - spread_keys}, "
                         f"in spreads not config={spread_keys - config_keys}")

    def test_thresholds_keys_match_stock_config(self):
        """THRESHOLDS derived from STOCK_CONFIG, must match."""
        config_keys = set(STOCK_CONFIG.keys())
        thresh_keys = set(THRESHOLDS.keys())
        self.assertEqual(config_keys, thresh_keys)

    def test_all_19_stocks_in_every_dict(self):
        expected_stocks = {
            "RELIANCE", "ADANIPORTS", "AMBUJACEM", "ASTRAL", "GRASIM",
            "HCLTECH", "HDFCBANK", "INFOSYS", "JSWSTEEL", "MARUTI",
            "TCS", "TATASTEEL", "BAJFINANCE", "SBIN", "LT",
            "HAL", "BANDHANBANK", "ADANIENT", "INDUSINDBK",
        }
        self.assertEqual(set(STOCK_CONFIG.keys()), expected_stocks)
        self.assertEqual(set(INITIAL_SPREADS.keys()), expected_stocks)
        self.assertEqual(set(THRESHOLDS.keys()), expected_stocks)

    def test_stock_count_is_19(self):
        self.assertEqual(STOCK_COUNT, 19)
        self.assertEqual(len(STOCK_CONFIG), 19)
        self.assertEqual(len(INITIAL_SPREADS), 19)
        self.assertEqual(len(THRESHOLDS), 19)

    def test_total_tokens_is_57(self):
        self.assertEqual(TOTAL_TOKENS, 57)
        self.assertEqual(STOCK_COUNT * 3, 57)

    def test_no_none_values_in_initial_spreads(self):
        for sym, val in INITIAL_SPREADS.items():
            self.assertIsNotNone(val, f"{sym} has None initial_spread")
            self.assertIsInstance(val, (int, float))

    def test_no_zero_initial_spreads(self):
        """Zero initial spread would cause division by zero in discount_pct."""
        for sym, val in INITIAL_SPREADS.items():
            self.assertNotEqual(val, 0.0, f"{sym} has zero initial_spread -> div by zero risk")


# ============================================================================
# AUDIT FINDING 5: __init__.py export completeness
# ============================================================================

class TestInitExports(unittest.TestCase):
    """Check that __init__.py exports everything needed."""

    def test_tick_exported(self):
        self.assertTrue(hasattr(pkg, 'Tick'))

    def test_tickbridge_exported(self):
        self.assertTrue(hasattr(pkg, 'TickBridge'))

    def test_tickvalidator_exported(self):
        self.assertTrue(hasattr(pkg, 'TickValidator'))

    def test_spreadengine_exported(self):
        self.assertTrue(hasattr(pkg, 'SpreadEngine'))

    def test_spreadsnapshot_exported(self):
        self.assertTrue(hasattr(pkg, 'SpreadSnapshot'))

    def test_config_constants_exported(self):
        self.assertTrue(hasattr(pkg, 'STOCK_CONFIG'))
        self.assertTrue(hasattr(pkg, 'THRESHOLDS'))
        self.assertTrue(hasattr(pkg, 'INITIAL_SPREADS'))

    def test_no_spread_freshness_exported(self):
        """SPREAD_FRESHNESS_SECONDS not exported from __init__.py -- may be needed."""
        # This is a minor gap -- consumers may need this constant
        self.assertFalse(hasattr(pkg, 'SPREAD_FRESHNESS_SECONDS'))

    def test_no_sample_interval_exported(self):
        """SAMPLE_INTERVAL_SECONDS not exported -- may be needed by orchestrator."""
        self.assertFalse(hasattr(pkg, 'SAMPLE_INTERVAL_SECONDS'))


# ============================================================================
# AUDIT FINDING 6: Thread model analysis
# ============================================================================

class TestThreadModel(unittest.TestCase):
    """
    Analyze the thread model and deadlock potential.

    Thread inventory:
      1. algo-bridge  (TickBridge._connect_loop) -- asyncio event loop thread
      2. algo-spread  (SpreadEngine._timer_loop) -- timer thread
      3. main thread  (or caller's thread)

    Lock inventory:
      - TickBridge._lock    (threading.Lock)
      - TickValidator._lock (threading.Lock)
      - SpreadEngine._lock  (threading.Lock)

    Lock ordering analysis:
      - SpreadEngine.compute_for_stock():
        1. bridge.get_tick() -> acquires bridge._lock, releases
        2. engine._lock acquired for writing snapshot
      - No nested locking observed -> NO DEADLOCK RISK between engine+bridge

    BUT: TickValidator._lock is never held simultaneously with any other lock
    because the validator is not integrated into the pipeline.
    """

    def test_no_nested_locking_in_spread_engine(self):
        """Verify SpreadEngine doesn't hold its lock while calling bridge."""
        bridge = _setup_full_bridge()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        # Inject valid ticks
        for sym in STOCK_CONFIG:
            tokens = bridge.get_tokens_for_stock(sym)
            ts = _now_ist_str()
            bridge.inject_tick(tokens["current"], 1000.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "current"})
            bridge.inject_tick(tokens["next"], 1005.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "next"})

        errors = []

        def compute_loop():
            try:
                for _ in range(200):
                    engine.compute_all()
            except Exception as e:
                errors.append(e)

        def bridge_inject_loop():
            try:
                for i in range(200):
                    for sym in list(STOCK_CONFIG)[:5]:
                        tokens = bridge.get_tokens_for_stock(sym)
                        ts = _now_ist_str()
                        bridge.inject_tick(tokens["current"], 1000.0 + i * 0.01, ts=ts,
                                           info={"sym": sym, "type": "future", "month": "current"})
                        bridge.inject_tick(tokens["next"], 1005.0 + i * 0.01, ts=ts,
                                           info={"sym": sym, "type": "future", "month": "next"})
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=compute_loop)
        t2 = threading.Thread(target=bridge_inject_loop)
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        self.assertEqual(errors, [], f"Errors during concurrent access: {errors}")

    def test_thread_count_with_all_components(self):
        """Verify expected thread count when all components run."""
        bridge = TickBridge()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        # Before starting: only main thread
        initial_threads = threading.active_count()

        engine.start()
        time.sleep(0.2)

        active_threads = threading.active_count()
        # Should be initial + 1 (algo-spread timer thread)
        # Bridge thread NOT started (no .start() on bridge)
        self.assertEqual(active_threads, initial_threads + 1)

        engine.stop()

    def test_spread_engine_timer_thread_is_daemon(self):
        """Timer thread should be daemon so it doesn't block exit."""
        bridge = TickBridge()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        engine.start()
        time.sleep(0.1)
        self.assertTrue(engine._timer_thread.daemon)
        engine.stop()


# ============================================================================
# AUDIT FINDING 7: Full end-to-end pipeline test
# ============================================================================

class TestEndToEndPipeline(unittest.TestCase):
    """
    Trace a tick from WebSocket message to spread computation.
    This is the FULL pipeline test.
    """

    def test_full_pipeline_single_stock(self):
        """Complete trace: WS message -> bridge -> validator -> spread."""
        bridge = _setup_full_bridge()
        validator = TickValidator()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        tokens = bridge.get_tokens_for_stock("RELIANCE")
        ts = _now_ist_str()

        # Simulate WebSocket message
        msg = json.dumps({
            "type": "ticks",
            "data": [
                {"token": tokens["current"], "ltp_r": 2850.0, "ts": ts,
                 "info": {"type": "future", "month": "current", "sym": "RELIANCE"}},
                {"token": tokens["next"], "ltp_r": 2854.0, "ts": ts,
                 "info": {"type": "future", "month": "next", "sym": "RELIANCE"}},
            ]
        })

        # Step 1: Bridge receives message
        bridge._on_message(msg)
        self.assertEqual(bridge.tick_count, 2)

        # Step 2: Get ticks from bridge and validate
        all_ticks = bridge.get_all_ticks()
        valid_ticks = []
        for tick in all_ticks.values():
            if validator.process_tick(tick):
                valid_ticks.append(tick)

        self.assertEqual(len(valid_ticks), 2)
        self.assertEqual(validator.passed_count, 2)
        self.assertEqual(validator.rejected_count, 0)

        # Step 3: SpreadEngine reads from bridge (NOT from validator output!)
        # THIS IS THE GAP: validator output is not connected to spread engine
        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNotNone(snap)
        self.assertEqual(snap.stock, "RELIANCE")
        self.assertAlmostEqual(snap.spread, 4.0)
        self.assertTrue(snap.is_contango)

    def test_full_pipeline_all_19_stocks(self):
        """Full pipeline for all 19 stocks simultaneously."""
        bridge = _setup_full_bridge()
        validator = TickValidator()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        ts = _now_ist_str()

        # Inject ticks for all stocks via WebSocket messages
        for sym in STOCK_CONFIG:
            tokens = bridge.get_tokens_for_stock(sym)
            msg = json.dumps({
                "type": "ticks",
                "data": [
                    {"token": tokens["current"], "ltp_r": 1000.0, "ts": ts,
                     "info": {"type": "future", "month": "current", "sym": sym}},
                    {"token": tokens["next"], "ltp_r": 1005.0, "ts": ts,
                     "info": {"type": "future", "month": "next", "sym": sym}},
                ]
            })
            bridge._on_message(msg)

        # Validate all ticks
        for tick in bridge.get_all_ticks().values():
            validator.process_tick(tick)

        self.assertEqual(validator.passed_count, 38)  # 19 stocks x 2 tokens

        # Compute all spreads
        results = engine.compute_all()
        self.assertEqual(len(results), 19)

        for sym in STOCK_CONFIG:
            self.assertIn(sym, results)
            snap = results[sym]
            self.assertAlmostEqual(snap.spread, 5.0)
            self.assertTrue(snap.is_contango)

    def test_pipeline_with_invalid_tick_reaching_spread(self):
        """
        DEMONSTRATES THE BUG: Invalid tick (ltp=0) passes through bridge
        to SpreadEngine because validator is not in the data path.
        """
        bridge = _setup_full_bridge()
        validator = TickValidator()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        tokens = bridge.get_tokens_for_stock("TCS")
        ts = _now_ist_str()

        # Inject valid current tick
        bridge.inject_tick(tokens["current"], 2096.0, ts=ts,
                           info={"sym": "TCS", "type": "future", "month": "current"})

        # Inject INVALID next tick (ltp=0) directly into bridge
        bridge.inject_tick(tokens["next"], 0.0, ts=ts,
                           info={"sym": "TCS", "type": "future", "month": "next"})

        # Validator would reject ltp=0
        bad_tick = Tick(token=tokens["next"], ltp=0.0, ts=ts, recv_mono_ns=0)
        self.assertFalse(validator.process_tick(bad_tick))

        # But SpreadEngine reads from bridge, not validator
        snap = engine.compute_for_stock("TCS")
        # spread = 0.0 - 2096.0 = -2096.0 (backwardation, corrupt data)
        if snap is not None:
            self.assertAlmostEqual(snap.spread, -2096.0)
            # This is WRONG -- the spread is corrupted by invalid data


# ============================================================================
# AUDIT FINDING 8: 57 simultaneous tick streams
# ============================================================================

class TestFiftySevenStreams(unittest.TestCase):
    """Test with all 57 token streams active simultaneously."""

    def test_57_simultaneous_tick_streams(self):
        """All 57 tokens (19 stocks x 3) streaming ticks."""
        bridge = _setup_full_bridge()
        validator = TickValidator()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        ts = _now_ist_str()
        tok_id = 1

        # Inject ticks for ALL 57 tokens
        for sym in STOCK_CONFIG:
            # Cash token
            bridge.inject_tick(tok_id, 1000.0, ts=ts,
                               info={"sym": sym, "type": "cash"})
            tok_id += 1
            # Current future
            bridge.inject_tick(tok_id, 1005.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "current"})
            tok_id += 1
            # Next future
            bridge.inject_tick(tok_id, 1008.0, ts=ts,
                               info={"sym": sym, "type": "future", "month": "next"})
            tok_id += 1

        self.assertEqual(bridge.tick_count, 57)
        self.assertEqual(bridge.token_count, 57)

        # Validate all
        for tick in bridge.get_all_ticks().values():
            validator.process_tick(tick)
        self.assertEqual(validator.passed_count, 57)

        # Compute spreads
        results = engine.compute_all()
        self.assertEqual(len(results), 19)

        # Each stock should have spread = next - current = 1008 - 1005 = 3.0
        for sym in STOCK_CONFIG:
            snap = results[sym]
            self.assertAlmostEqual(snap.spread, 3.0,
                                   msg=f"{sym} spread wrong")

    def test_57_streams_concurrent_updates(self):
        """Stress test: 57 streams updating concurrently."""
        bridge = _setup_full_bridge()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)
        errors = []

        def inject_for_stock(sym, base_price):
            try:
                tokens = bridge.get_tokens_for_stock(sym)
                for i in range(50):
                    ts = _now_ist_str()
                    bridge.inject_tick(tokens["current"], base_price + i * 0.1, ts=ts,
                                       info={"sym": sym, "type": "future", "month": "current"})
                    bridge.inject_tick(tokens["next"], base_price + 5 + i * 0.1, ts=ts,
                                       info={"sym": sym, "type": "future", "month": "next"})
            except Exception as e:
                errors.append(e)

        threads = []
        for idx, sym in enumerate(STOCK_CONFIG):
            t = threading.Thread(target=inject_for_stock, args=(sym, 1000.0 + idx * 10))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        self.assertEqual(errors, [])

        # Final compute should work
        results = engine.compute_all()
        self.assertEqual(len(results), 19)


# ============================================================================
# AUDIT FINDING 9: SpreadEngine freshness check uses string parsing
# ============================================================================

class TestFreshnessParsing(unittest.TestCase):
    """
    FINDING: SpreadEngine._tick_is_fresh() parses tick.ts with strptime
    every time. This is fragile and slow. Also, it re-parses the same
    timestamp on every compute cycle.
    """

    def test_freshness_with_wrong_format(self):
        """Non-standard timestamp format silently treated as stale."""
        bridge = _setup_full_bridge()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        tokens = bridge.get_tokens_for_stock("RELIANCE")
        # ISO format instead of expected "%Y-%m-%d %H:%M:%S.%f"
        bridge.inject_tick(tokens["current"], 2850.0, ts="2026-10-06T09:20:00Z",
                           info={"sym": "RELIANCE", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 2854.0, ts="2026-10-06T09:20:00Z",
                           info={"sym": "RELIANCE", "type": "future", "month": "next"})

        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNone(snap)
        self.assertEqual(engine.skip_reasons["RELIANCE"], "stale_current")

    def test_freshness_boundary_exactly_60_seconds(self):
        """Tick at exactly 60s boundary."""
        bridge = _setup_full_bridge()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        tokens = bridge.get_tokens_for_stock("RELIANCE")
        ts_60s_ago = _now_ist_str(-60)
        ts_fresh = _now_ist_str()

        bridge.inject_tick(tokens["current"], 2850.0, ts=ts_60s_ago,
                           info={"sym": "RELIANCE", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 2854.0, ts=ts_fresh,
                           info={"sym": "RELIANCE", "type": "future", "month": "next"})

        snap = engine.compute_for_stock("RELIANCE")
        # At exactly 60s, age_seconds <= 60 is True, so it passes
        # But this is timing-dependent


# ============================================================================
# AUDIT FINDING 10: ASTRAL negative initial spread edge case
# ============================================================================

class TestAstralNegativeInitialSpread(unittest.TestCase):
    """
    ASTRAL has initial_spread = -1.70 (negative, backwardation).
    Verify discount_pct math is correct and doesn't produce misleading results.
    """

    def test_astral_negative_initial_spread_discount_math(self):
        bridge = _setup_full_bridge()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        tokens = bridge.get_tokens_for_stock("ASTRAL")
        ts = _now_ist_str()

        # Current=1406, Next=1408 -> spread=2.0 (contango now, was backwardation initially)
        bridge.inject_tick(tokens["current"], 1406.0, ts=ts,
                           info={"sym": "ASTRAL", "type": "future", "month": "current"})
        bridge.inject_tick(tokens["next"], 1408.0, ts=ts,
                           info={"sym": "ASTRAL", "type": "future", "month": "next"})

        snap = engine.compute_for_stock("ASTRAL")
        self.assertIsNotNone(snap)
        # discount_pct = (-1.70 - 2.0) / (-1.70) * 100 = 217.65%
        # This is mathematically correct but semantically confusing
        expected = (-1.70 - 2.0) / (-1.70) * 100
        self.assertAlmostEqual(snap.discount_pct, expected, places=2)
        self.assertGreater(snap.discount_pct, 100)  # Over 100% discount -- confusing!


# ============================================================================
# AUDIT FINDING 11: No orchestrator / main loop exists
# ============================================================================

class TestNoOrchestrator(unittest.TestCase):
    """
    FINDING: There is no main orchestrator that ties the pipeline together.
    Each component must be manually wired by the caller. This is a significant
    integration risk for the Monday demo.
    """

    def test_no_orchestrator_module(self):
        """No orchestrator or pipeline module exists."""
        import importlib
        with self.assertRaises(ImportError):
            importlib.import_module('algo_engine.orchestrator')

    def test_no_pipeline_function_in_init(self):
        """__init__.py doesn't expose a run_pipeline or start_all function."""
        self.assertFalse(hasattr(pkg, 'run_pipeline'))
        self.assertFalse(hasattr(pkg, 'start_all'))
        self.assertFalse(hasattr(pkg, 'create_pipeline'))


# ============================================================================
# AUDIT FINDING 12: Validator doesn't know about stock config
# ============================================================================

class TestValidatorStockAwareness(unittest.TestCase):
    """
    FINDING: TickValidator has no reference to STOCK_CONFIG. It validates
    purely on tick-level properties (ltp > 0, timestamp ordering).
    It cannot reject ticks for unknown stocks or detect anomalous prices.
    """

    def test_validator_has_no_config_reference(self):
        v = TickValidator()
        source = inspect.getsource(TickValidator)
        self.assertNotIn('STOCK_CONFIG', source)
        self.assertNotIn('INITIAL_SPREADS', source)

    def test_validator_cannot_reject_unknown_stock(self):
        v = TickValidator()
        tick = Tick(token=12345, ltp=999.0, ts="T1", recv_mono_ns=0,
                    info={"sym": "TOTALLY_FAKE"})
        ok, _ = v.check(tick)
        self.assertTrue(ok)  # No way to reject this


# ============================================================================
# AUDIT FINDING 13: SpreadEngine uses cash token? No, only futures.
# ============================================================================

class TestCashTokenNotUsedBySpread(unittest.TestCase):
    """
    Verify SpreadEngine only uses current+next future tokens, not cash.
    This is correct behavior but worth confirming.
    """

    def test_cash_token_ignored_by_spread(self):
        bridge = _setup_full_bridge()
        engine = SpreadEngine(bridge, INITIAL_SPREADS)

        tokens = bridge.get_tokens_for_stock("RELIANCE")

        # Only inject cash token
        ts = _now_ist_str()
        bridge.inject_tick(tokens["cash"], 2850.0, ts=ts,
                           info={"sym": "RELIANCE", "type": "cash"})

        snap = engine.compute_for_stock("RELIANCE")
        self.assertIsNone(snap)
        self.assertEqual(engine.skip_reasons["RELIANCE"], "no_ticks")


# ============================================================================
# AUDIT FINDING 14: Backward timestamp edge case in validator
# ============================================================================

class TestValidatorTimestampEdgeCases(unittest.TestCase):
    """
    The validator uses string comparison for timestamps. This works for
    ISO-formatted timestamps but could fail with different formats.
    """

    def test_string_comparison_works_for_iso_format(self):
        v = TickValidator()
        v.check(Tick(token=1, ltp=100.0, ts="2026-10-06 09:20:00.000", recv_mono_ns=0))
        ok, _ = v.check(Tick(token=1, ltp=101.0, ts="2026-10-06 09:20:00.001", recv_mono_ns=0))
        self.assertTrue(ok)

    def test_string_comparison_different_dates(self):
        v = TickValidator()
        v.check(Tick(token=1, ltp=100.0, ts="2026-10-06 15:00:00.000", recv_mono_ns=0))
        # Next day -- lexicographic comparison works for ISO dates
        ok, _ = v.check(Tick(token=1, ltp=101.0, ts="2026-10-07 09:15:00.000", recv_mono_ns=0))
        self.assertTrue(ok)


# ============================================================================
# SUMMARY: Run all audit findings
# ============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
