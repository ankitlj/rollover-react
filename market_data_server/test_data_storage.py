import json
import requests
import time
from datetime import datetime

BASE_URL = "http://127.0.0.1:8767"

def test_data_endpoints():
    print("\n=== Testing Data Storage Endpoints ===\n")

    date_tag = datetime.now().strftime("%Y%m%d")

    print("1. Testing POST /data/save (active_opportunities)...")
    test_data = [
        {"id": "ws-REL", "sym": "REL", "status": "Available", "discount": 2.5},
        {"id": "ws-TCS", "sym": "TCS", "status": "Available", "discount": 3.1},
    ]
    resp = requests.post(f"{BASE_URL}/data/save", json={
        "table": f"active_opportunities_{date_tag}",
        "content": test_data
    })
    assert resp.status_code == 200, f"Save failed: {resp.text}"
    print("   ✓ Saved active_opportunities")

    print("\n2. Testing POST /data/save (daily_instruction_log)...")
    log_data = [
        {"id": "LOG-001", "sym": "REL", "lotsInstructed": 10, "status": "Awaiting EOD"},
    ]
    resp = requests.post(f"{BASE_URL}/data/save", json={
        "table": f"daily_instruction_log_{date_tag}",
        "content": log_data
    })
    assert resp.status_code == 200, f"Save failed: {resp.text}"
    print("   ✓ Saved daily_instruction_log")

    print("\n3. Testing POST /data/settings...")
    settings_data = {
        "settings": {"tradingDays": 20, "fyMonths": 12},
        "stockOverrides": {"REL": {"lot": 100, "lotsHeld": 5}}
    }
    resp = requests.post(f"{BASE_URL}/data/settings", json=settings_data)
    assert resp.status_code == 200, f"Settings save failed: {resp.text}"
    print("   ✓ Saved settings")

    print("\n4. Testing GET /data/load...")
    start = time.time()
    resp = requests.get(f"{BASE_URL}/data/load")
    elapsed = (time.time() - start) * 1000
    assert resp.status_code == 200, f"Load failed: {resp.text}"
    data = resp.json()
    print(f"   ✓ Loaded all data in {elapsed:.2f}ms")
    print(f"   ✓ Active opportunities: {len(data.get(f'active_opportunities_{date_tag}', []))} entries")
    print(f"   ✓ Daily instruction log: {len(data.get(f'daily_instruction_log_{date_tag}', []))} entries")
    print(f"   ✓ Settings: {data.get('settings', {})}")

    assert len(data.get(f"active_opportunities_{date_tag}", [])) == 2
    assert len(data.get(f"daily_instruction_log_{date_tag}", [])) == 1
    assert data.get("settings", {}).get("tradingDays") == 20

    print("\n5. Testing data persistence (load again)...")
    resp = requests.get(f"{BASE_URL}/data/load")
    data2 = resp.json()
    assert data2 == data, "Data not persistent!"
    print("   ✓ Data persists across loads")

    print("\n=== All Tests Passed ===\n")

if __name__ == "__main__":
    test_data_endpoints()
