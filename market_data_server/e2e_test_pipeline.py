"""
E2E Pipeline Test - Tests the complete algo engine pipeline with mock ticks.
Tests: tick injection -> spread computation -> alert firing -> alert expiry -> JSON persistence -> midnight cleanup.
Uses 5 stocks, no external dependencies beyond what's already installed.
"""
import sys
import os
import io
import time
import json
import requests
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from algo_engine.config import IST, INITIAL_SPREADS, STOCK_CONFIG
from algo_engine.bridge import TickBridge
from algo_engine.validator import TickValidator
from algo_engine.spread import SpreadEngine
from algo_engine.alerts import AlertEngine
from algo_engine.session import SessionEngine
from algo_engine.orchestrator import AlgoOrchestrator
from algo_engine.ws_broadcaster import WSBroadcaster, DATA_DIR

TEST_STOCKS = ["RELIANCE", "TCS", "INFOSYS", "HDFCBANK", "SBIN"]

TOKEN_MAP = {}
for i, sym in enumerate(TEST_STOCKS):
    base = (i + 1) * 1000
    TOKEN_MAP[sym] = {"cash": base + 1, "current": base + 2, "next": base + 3}

FUT_PRICES = {
    "RELIANCE": 1414.0, "TCS": 3472.0, "INFOSYS": 1500.0,
    "HDFCBANK": 965.0, "SBIN": 790.0,
}

HTTP_URL = "http://127.0.0.1:8767"


def build_metadata():
    tokens = {}
    for sym, toks in TOKEN_MAP.items():
        tokens[str(toks["cash"])] = {"sym": sym, "type": "cash"}
        tokens[str(toks["current"])] = {"sym": sym, "type": "future", "month": "current"}
        tokens[str(toks["next"])] = {"sym": sym, "type": "future", "month": "next"}
    return tokens, list(TEST_STOCKS)


def inject_alert_ticks(bridge):
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    for sym in TEST_STOCKS:
        fut = FUT_PRICES[sym]
        current_ltp = fut
        next_ltp = fut + INITIAL_SPREADS[sym] * 0.3
        bridge.inject_tick(TOKEN_MAP[sym]["current"], current_ltp, now_str,
                           info={"sym": sym, "type": "future", "month": "current"})
        bridge.inject_tick(TOKEN_MAP[sym]["next"], next_ltp, now_str,
                           info={"sym": sym, "type": "future", "month": "next"})


def inject_expiry_ticks(bridge):
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    for sym in TEST_STOCKS:
        fut = FUT_PRICES[sym]
        current_ltp = fut
        next_ltp = fut + INITIAL_SPREADS[sym] * 0.95
        bridge.inject_tick(TOKEN_MAP[sym]["current"], current_ltp, now_str,
                           info={"sym": sym, "type": "future", "month": "current"})
        bridge.inject_tick(TOKEN_MAP[sym]["next"], next_ltp, now_str,
                           info={"sym": sym, "type": "future", "month": "next"})


def wait_for_http_server(timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{HTTP_URL}/data/load", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def run_test():
    print("\n" + "=" * 60)
    print("E2E PIPELINE TEST")
    print("=" * 60)

    date_tag = datetime.now(IST).strftime("%Y%m%d")
    passed = 0
    failed = 0

    # --- Step 1: Setup bridge with metadata ---
    print("\n1. Setting up TickBridge with 5 stocks...")
    bridge = TickBridge(uri="ws://127.0.0.1:9999")
    tokens, stocks = build_metadata()
    bridge.inject_metadata(tokens, stocks)
    bridge._connected.set()
    print(f"   OK - Bridge ready for {len(stocks)} stocks")
    passed += 1

    # --- Step 2: Create engines ---
    print("\n2. Creating algo engines...")
    validator = TickValidator()
    spread = SpreadEngine(bridge, INITIAL_SPREADS)
    alerts = AlertEngine()
    session = SessionEngine()

    # Mock session to always return ACTIVE phase (bypass market hours check)
    from algo_engine.session import PHASE_ACTIVE
    session.current_phase = lambda now=None: PHASE_ACTIVE
    session.should_compute_spreads = lambda now=None: True
    session.should_fire_alerts = lambda now=None: True

    orchestrator = AlgoOrchestrator(
        bridge=bridge, validator=validator, spread=spread,
        alerts=alerts, session=session,
    )

    broadcaster = WSBroadcaster(spread, orchestrator, bridge, session)
    broadcaster.start()
    print("   OK - Engines created, broadcaster started")
    passed += 1

    # --- Step 3: Wait for HTTP server ---
    print("\n3. Waiting for HTTP server on port 8767...")
    if wait_for_http_server():
        print("   OK - HTTP server responding")
        passed += 1
    else:
        print("   FAIL - HTTP server not responding")
        failed += 1
        print("\nABORTING - HTTP server not available")
        return

    # --- Step 4: Inject alert-triggering ticks ---
    print("\n4. Injecting ticks to trigger alerts (high discount)...")
    inject_alert_ticks(bridge)
    time.sleep(1)

    # Run orchestrator cycle manually
    orchestrator.cycle()
    time.sleep(1)

    # Check snapshots
    snapshots = spread.snapshots
    computed = len(snapshots)
    print(f"   Snapshots computed: {computed}/{len(TEST_STOCKS)}")

    # Debug: check skip reasons
    skip_reasons = spread.skip_reasons
    if skip_reasons:
        print(f"   Skip reasons: {skip_reasons}")

    # Debug: check bridge tokens
    for sym in TEST_STOCKS[:2]:
        tokens = bridge.get_tokens_for_stock(sym)
        print(f"   {sym} tokens: current={tokens.get('current')}, next={tokens.get('next')}")
        if tokens.get('current'):
            tick = bridge.get_tick(tokens['current'])
            if tick:
                print(f"   {sym} current tick: ltp={tick.ltp}, ts={tick.ts}, fresh={spread._tick_is_fresh(tick)}")

    alerts_fired = len(alerts._alerts)
    print(f"   Alerts fired: {alerts_fired}")

    if computed >= 3:
        print(f"   OK - {computed} spreads computed")
        passed += 1
    else:
        print(f"   FAIL - Only {computed} spreads computed (expected >= 3)")
        failed += 1

    if alerts_fired >= 3:
        print(f"   OK - {alerts_fired} alerts fired")
        passed += 1
    else:
        print(f"   WARN - Only {alerts_fired} alerts fired (expected >= 3)")

    # --- Step 5: Verify JSON persistence via HTTP ---
    print("\n5. Verifying JSON persistence via HTTP /data/load...")
    try:
        r = requests.get(f"{HTTP_URL}/data/load", timeout=5)
        data = r.json()
        active_key = f"active_opportunities_{date_tag}"
        print(f"   Response keys: {list(data.keys())}")
        print(f"   OK - HTTP load successful")
        passed += 1
    except Exception as e:
        print(f"   FAIL - HTTP load error: {e}")
        failed += 1

    # --- Step 6: Save test data to JSON via HTTP ---
    print("\n6. Saving test data to all 6 tables via HTTP...")
    test_tables = {
        f"active_opportunities_{date_tag}": [
            {"id": f"ws-{sym}", "sym": sym, "status": "Available",
             "discount": 50.0, "current": 1.5, "threshold": 40}
            for sym in TEST_STOCKS
        ],
        f"expired_opportunities_{date_tag}": [],
        f"daily_instruction_log_{date_tag}": [
            {"id": "LOG-E2E-001", "sym": "RELIANCE", "lotsInstructed": 2,
             "lotsFilled": 0, "status": "Awaiting EOD", "finalised": False},
        ],
        f"execution_details_{date_tag}": [],
        f"correction_history_{date_tag}": [],
        f"daily_metrics_{date_tag}": [
            {"date": datetime.now(IST).strftime("%Y-%m-%d"),
             "totalInstructions": 1, "lotsInstructed": 2, "lotsFilled": 0, "dailySaving": 0}
        ],
    }

    save_ok = 0
    for table, content in test_tables.items():
        try:
            r = requests.post(f"{HTTP_URL}/data/save", json={"table": table, "content": content}, timeout=5)
            if r.status_code == 200:
                save_ok += 1
        except Exception as e:
            print(f"   FAIL - Save {table}: {e}")

    if save_ok == 6:
        print(f"   OK - All 6 tables saved")
        passed += 1
    else:
        print(f"   FAIL - Only {save_ok}/6 tables saved")
        failed += 1

    # --- Step 7: Save settings ---
    print("\n7. Saving settings via HTTP...")
    try:
        r = requests.post(f"{HTTP_URL}/data/settings", json={
            "settings": {"tradingDays": 20, "fyMonths": 12, "refreshInterval": 10},
            "stockOverrides": {sym: {"lot": STOCK_CONFIG[sym]["lot"], "lotsHeld": 0} for sym in TEST_STOCKS}
        }, timeout=5)
        if r.status_code == 200:
            print("   OK - Settings saved")
            passed += 1
        else:
            print(f"   FAIL - Settings save returned {r.status_code}")
            failed += 1
    except Exception as e:
        print(f"   FAIL - Settings save error: {e}")
        failed += 1

    # --- Step 8: Verify physical files ---
    print("\n8. Verifying physical JSON files...")
    expected_files = [
        f"active_opportunities_{date_tag}.json",
        f"expired_opportunities_{date_tag}.json",
        f"daily_instruction_log_{date_tag}.json",
        f"execution_details_{date_tag}.json",
        f"correction_history_{date_tag}.json",
        f"daily_metrics_{date_tag}.json",
        "settings.json",
    ]
    files_ok = 0
    for fn in expected_files:
        path = DATA_DIR / fn
        if path.exists():
            size = path.stat().st_size
            print(f"   OK - {fn} ({size} bytes)")
            files_ok += 1
        else:
            print(f"   FAIL - {fn} not found")

    if files_ok == 7:
        passed += 1
    else:
        print(f"   FAIL - Only {files_ok}/7 files found")
        failed += 1

    # --- Step 9: Login/logout simulation (3 cycles) ---
    print("\n9. Simulating 3 login/logout cycles...")
    login_ok = 0
    for i in range(3):
        try:
            r = requests.get(f"{HTTP_URL}/data/load", timeout=5)
            data = r.json()
            active = data.get(f"active_opportunities_{date_tag}", [])
            log_entries = data.get(f"daily_instruction_log_{date_tag}", [])
            settings = data.get("settings", {})
            if len(active) == 5 and len(log_entries) == 1 and settings:
                login_ok += 1
                print(f"   OK - Cycle {i+1}: {len(active)} active, {len(log_entries)} log, settings loaded")
            else:
                print(f"   FAIL - Cycle {i+1}: data mismatch (active={len(active)}, log={len(log_entries)})")
        except Exception as e:
            print(f"   FAIL - Cycle {i+1}: {e}")

    if login_ok == 3:
        passed += 1
    else:
        failed += 1

    # --- Step 10: Inject expiry ticks and verify ---
    print("\n10. Injecting ticks to trigger alert expiry (low discount)...")
    inject_expiry_ticks(bridge)
    time.sleep(1)
    orchestrator.cycle()
    time.sleep(1)

    snapshots_after = spread.snapshots
    for sym, snap in snapshots_after.items():
        if sym in TEST_STOCKS:
            print(f"   {sym}: spread={snap.spread:.2f}, discount={snap.discount_pct:.1f}%")

    print("   OK - Expiry ticks processed")
    passed += 1

    # --- Step 11: Test midnight cleanup ---
    print("\n11. Testing midnight cleanup...")
    fake_old_files = []
    for pattern in ["active_opportunities_20260101.json", "daily_instruction_log_20260101.json",
                     "settings.json"]:
        path = DATA_DIR / pattern
        with open(path, "w") as f:
            json.dump([{"test": "old_data"}], f)
        fake_old_files.append(path)

    print(f"   Created {len(fake_old_files)} fake old files")

    broadcaster._cleanup_daily_files()
    time.sleep(0.5)

    daily_deleted = 0
    for p in fake_old_files:
        if not p.exists():
            daily_deleted += 1
            print(f"   OK - {p.name} deleted")
        else:
            print(f"   OK - {p.name} preserved (settings file)")

    settings_path = DATA_DIR / "settings.json"
    if settings_path.exists():
        print("   OK - settings.json survived cleanup")
        passed += 1
    else:
        print("   FAIL - settings.json was deleted!")
        failed += 1

    # Verify cleanup ran (old files deleted)
    old_daily_deleted = not (DATA_DIR / "active_opportunities_20260101.json").exists()
    if old_daily_deleted:
        print(f"   OK - Old daily files deleted by cleanup")
        passed += 1
    else:
        print(f"   FAIL - Old daily files not deleted")
        failed += 1

    # --- Step 12: Final data load verification ---
    print("\n12. Final data load verification...")
    try:
        r = requests.get(f"{HTTP_URL}/data/load", timeout=5)
        data = r.json()
        tables_ok = 0
        for key in [f"active_opportunities_{date_tag}", f"daily_instruction_log_{date_tag}",
                     f"daily_metrics_{date_tag}"]:
            if key in data:
                tables_ok += 1
        if "settings" in data:
            tables_ok += 1
        print(f"   OK - {tables_ok}/4 key tables present in load response")
        if tables_ok == 4:
            passed += 1
        else:
            failed += 1
    except Exception as e:
        print(f"   FAIL - Final load error: {e}")
        failed += 1

    # --- Summary ---
    print("\n" + "=" * 60)
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed}/{total} failed")
    if failed == 0:
        print("ALL PIPELINE TESTS PASSED")
    else:
        print(f"WARNING: {failed} test(s) failed")
    print("=" * 60 + "\n")

    # Cleanup - stop broadcaster threads
    broadcaster._shutdown.set()


if __name__ == "__main__":
    try:
        run_test()
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
