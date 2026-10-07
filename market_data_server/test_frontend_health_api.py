"""Test frontend health API endpoint."""
import sys
import os
import json
import time
import threading
import requests
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algo_engine.ws_broadcaster import WSBroadcaster


class MockSpreadEngine:
    def __init__(self):
        self.snapshots = {}


class MockOrchestrator:
    def status(self):
        return {"phase": "ACTIVE"}


class MockBridge:
    def __init__(self):
        self.connected = True


class MockSessionEngine:
    def current_phase(self):
        return "ACTIVE"


def test_health_api():
    print("Starting WS broadcaster with health API...")

    broadcaster = WSBroadcaster(
        spread_engine=MockSpreadEngine(),
        orchestrator=MockOrchestrator(),
        bridge=MockBridge(),
        session_engine=MockSessionEngine(),
    )

    broadcaster_thread = threading.Thread(target=broadcaster.start, daemon=True)
    broadcaster_thread.start()

    print("Waiting for health API to start...")
    time.sleep(2)

    print("\nSending dummy health data to API...")
    dummy_data = {
        "events": [
            {"event": "connected", "timestamp": "2026-10-07T09:15:30.000Z"},
            {"event": "message_received", "timestamp": "2026-10-07T09:15:31.000Z", "details": {"type": "init"}},
            {"event": "message_received", "timestamp": "2026-10-07T09:15:35.000Z", "details": {"type": "snapshot"}},
            {"event": "disconnected", "timestamp": "2026-10-07T10:30:00.000Z"},
            {"event": "reconnecting", "timestamp": "2026-10-07T10:30:02.000Z", "details": {"attempt": 1, "delay_ms": 2000}},
            {"event": "connected", "timestamp": "2026-10-07T10:30:04.000Z"},
        ],
        "synced_at": "2026-10-07T15:30:00.000Z"
    }

    try:
        response = requests.post(
            "http://127.0.0.1:8767/health",
            json=dummy_data,
            timeout=5
        )
        print(f"Response status: {response.status_code}")
        print(f"Response body: {response.json()}")
    except Exception as e:
        print(f"ERROR: {e}")
        broadcaster.stop()
        return

    print("\nChecking if file was created...")
    report_dir = Path(__file__).parent / "reports"
    date_tag = time.strftime("%Y%m%d")
    file_path = report_dir / f"frontend_health_{date_tag}.json"

    print(f"Expected file: {file_path}")
    print(f"File exists: {file_path.exists()}")

    if file_path.exists():
        print("\n" + "=" * 70)
        print("FILE CONTENT:")
        print("=" * 70)
        with open(file_path, "r", encoding="utf-8") as f:
            content = json.load(f)
            print(json.dumps(content, indent=2))
        print("=" * 70)
        print("\nTEST PASSED")
    else:
        print("\nTEST FAILED - File not created")

    broadcaster.stop()


if __name__ == "__main__":
    test_health_api()
