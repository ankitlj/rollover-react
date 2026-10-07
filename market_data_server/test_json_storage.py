"""
Comprehensive test for JSON storage system.
Tests all 6 daily JSONs + persistent settings.
Run this after starting the algo engine (which starts the HTTP server on port 8767).
"""
import json
import requests
import time
from datetime import datetime
from pathlib import Path

BASE_URL = "http://127.0.0.1:8767"
DATA_DIR = Path(__file__).parent / "data"

def test_all_tables():
    print("\n" + "="*60)
    print("COMPREHENSIVE JSON STORAGE TEST")
    print("="*60 + "\n")

    date_tag = datetime.now().strftime("%Y%m%d")
    
    # Test 1: Active Opportunities
    print("1. Testing Active Opportunities...")
    active_data = [
        {"id": "ws-REL", "sym": "REL", "status": "Available", "discount": 2.5, "current": 1.2},
        {"id": "ws-TCS", "sym": "TCS", "status": "Available", "discount": 3.1, "current": 0.8},
    ]
    resp = requests.post(f"{BASE_URL}/data/save", json={
        "table": f"active_opportunities_{date_tag}",
        "content": active_data
    })
    assert resp.status_code == 200, f"Save failed: {resp.text}"
    print("   OK Saved 2 active opportunities")

    # Test 2: Expired Opportunities
    print("\n2. Testing Expired Opportunities...")
    expired_data = [
        {"id": "ws-INFY", "sym": "INFY", "status": "Expired", "discount": 0, "current": 0.5},
    ]
    resp = requests.post(f"{BASE_URL}/data/save", json={
        "table": f"expired_opportunities_{date_tag}",
        "content": expired_data
    })
    assert resp.status_code == 200, f"Save failed: {resp.text}"
    print("   OK Saved 1 expired opportunity")

    # Test 3: Daily Instruction Log
    print("\n3. Testing Daily Instruction Log...")
    log_data = [
        {"id": "LOG-001", "sym": "REL", "lotsInstructed": 10, "lotsFilled": 0, "status": "Awaiting EOD", "finalised": False},
        {"id": "LOG-002", "sym": "TCS", "lotsInstructed": 5, "lotsFilled": 0, "status": "Awaiting EOD", "finalised": False},
    ]
    resp = requests.post(f"{BASE_URL}/data/save", json={
        "table": f"daily_instruction_log_{date_tag}",
        "content": log_data
    })
    assert resp.status_code == 200, f"Save failed: {resp.text}"
    print("   OK Saved 2 instruction log entries")

    # Test 4: Execution Details
    print("\n4. Testing Execution Details...")
    exec_data = [
        {"id": "LOG-003", "sym": "INFY", "lotsInstructed": 8, "lotsFilled": 8, "status": "Confirmed", "finalised": True},
    ]
    resp = requests.post(f"{BASE_URL}/data/save", json={
        "table": f"execution_details_{date_tag}",
        "content": exec_data
    })
    assert resp.status_code == 200, f"Save failed: {resp.text}"
    print("   OK Saved 1 execution detail entry")

    # Test 5: Correction History
    print("\n5. Testing Correction History...")
    corr_data = [
        {"id": "CORR-001", "entryId": "LOG-003", "stock": "INFY", "field": "lotsFilled", "oldValue": 6, "newValue": 8, "reason": "Dealer confirmed"},
    ]
    resp = requests.post(f"{BASE_URL}/data/save", json={
        "table": f"correction_history_{date_tag}",
        "content": corr_data
    })
    assert resp.status_code == 200, f"Save failed: {resp.text}"
    print("   OK Saved 1 correction entry")

    # Test 6: Daily Metrics (not implemented yet, but table exists)
    print("\n6. Testing Daily Metrics...")
    metrics_data = [
        {"date": datetime.now().strftime("%Y-%m-%d"), "totalInstructions": 3, "lotsInstructed": 23, "lotsFilled": 16, "dailySaving": 1250.50}
    ]
    resp = requests.post(f"{BASE_URL}/data/save", json={
        "table": f"daily_metrics_{date_tag}",
        "content": metrics_data
    })
    assert resp.status_code == 200, f"Save failed: {resp.text}"
    print("   OK Saved daily metrics")

    # Test 7: Settings (persistent)
    print("\n7. Testing Settings (persistent)...")
    settings_data = {
        "settings": {"tradingDays": 20, "fyMonths": 12, "refreshInterval": 10},
        "stockOverrides": {"REL": {"lot": 100, "lotsHeld": 5}, "TCS": {"lot": 50, "lotsHeld": 3}}
    }
    resp = requests.post(f"{BASE_URL}/data/settings", json=settings_data)
    assert resp.status_code == 200, f"Settings save failed: {resp.text}"
    print("   OK Saved settings")

    # Test 8: Load all data
    print("\n8. Testing GET /data/load (all tables)...")
    start = time.time()
    resp = requests.get(f"{BASE_URL}/data/load")
    elapsed = (time.time() - start) * 1000
    assert resp.status_code == 200, f"Load failed: {resp.text}"
    data = resp.json()
    print(f"   OK Loaded all data in {elapsed:.2f}ms")
    
    # Verify each table
    assert len(data.get(f"active_opportunities_{date_tag}", [])) == 2, "Active opportunities count mismatch"
    assert len(data.get(f"expired_opportunities_{date_tag}", [])) == 1, "Expired opportunities count mismatch"
    assert len(data.get(f"daily_instruction_log_{date_tag}", [])) == 2, "Daily instruction log count mismatch"
    assert len(data.get(f"execution_details_{date_tag}", [])) == 1, "Execution details count mismatch"
    assert len(data.get(f"correction_history_{date_tag}", [])) == 1, "Correction history count mismatch"
    assert len(data.get(f"daily_metrics_{date_tag}", [])) == 1, "Daily metrics count mismatch"
    assert data.get("settings", {}).get("settings", {}).get("tradingDays") == 20, "Settings mismatch"
    assert data.get("settings", {}).get("stockOverrides", {}).get("REL", {}).get("lot") == 100, "Stock overrides mismatch"
    print("   OK All tables verified")

    # Test 9: Verify physical files exist
    print("\n9. Verifying physical JSON files...")
    expected_files = [
        f"active_opportunities_{date_tag}.json",
        f"expired_opportunities_{date_tag}.json",
        f"daily_instruction_log_{date_tag}.json",
        f"execution_details_{date_tag}.json",
        f"correction_history_{date_tag}.json",
        f"daily_metrics_{date_tag}.json",
        "settings.json"
    ]
    for filename in expected_files:
        path = DATA_DIR / filename
        assert path.exists(), f"File not found: {path}"
        with open(path, 'r', encoding='utf-8') as f:
            content = json.load(f)
            print(f"   OK {filename} ({len(json.dumps(content))} bytes)")

    # Test 10: Simulate login/logout cycle
    print("\n10. Simulating login/logout cycle...")
    for i in range(3):
        resp = requests.get(f"{BASE_URL}/data/load")
        data = resp.json()
        assert len(data.get(f"active_opportunities_{date_tag}", [])) == 2
        assert len(data.get(f"daily_instruction_log_{date_tag}", [])) == 2
        print(f"   OK Login cycle {i+1}: data loaded successfully")

    print("\n" + "="*60)
    print("ALL TESTS PASSED!")
    print("="*60 + "\n")
    print(f"Data directory: {DATA_DIR}")
    print(f"Date tag: {date_tag}")
    print(f"Total files created: {len(expected_files)}")
    print(f"Load time: {elapsed:.2f}ms")

if __name__ == "__main__":
    try:
        test_all_tables()
    except requests.exceptions.ConnectionError:
        print("\nERROR: Cannot connect to backend server at", BASE_URL)
        print("Make sure the algo engine is running (it starts the HTTP server on port 8767)")
        print("\nTo start the algo engine:")
        print("  cd market_data_server")
        print("  python -m algo_engine.algo_run")
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
