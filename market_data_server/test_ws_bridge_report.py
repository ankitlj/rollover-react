"""Test WS broadcaster report generation with dummy data."""
import sys
import os
import time
import asyncio
from pathlib import Path
from datetime import datetime

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


async def test_report_generation():
    print("Testing WS broadcaster report generation...")

    broadcaster = WSBroadcaster(
        spread_engine=MockSpreadEngine(),
        orchestrator=MockOrchestrator(),
        bridge=MockBridge(),
        session_engine=MockSessionEngine(),
    )

    broadcaster._start_time = datetime.now(broadcaster._start_time.tzinfo)

    broadcaster._connection_events = [
        {
            "event": "connect",
            "client": "127.0.0.1:50000",
            "timestamp": "2026-10-07 09:15:30",
        },
        {
            "event": "disconnect",
            "client": "127.0.0.1:50000",
            "timestamp": "2026-10-07 15:30:45",
            "duration_sec": 22515.0,
        },
        {
            "event": "connect",
            "client": "127.0.0.1:50001",
            "timestamp": "2026-10-07 10:00:00",
        },
    ]

    broadcaster._client_stats = {
        "127.0.0.1:50000": {
            "connected_at": "2026-10-07 09:15:30",
            "disconnected_at": "2026-10-07 15:30:45",
            "messages_sent": 1250,
            "duration_sec": 22515.0,
        },
        "127.0.0.1:50001": {
            "connected_at": "2026-10-07 10:00:00",
            "disconnected_at": None,
            "messages_sent": 850,
            "duration_sec": 0,
        },
    }

    broadcaster._messages_sent = 2100
    broadcaster._send_failures = 3

    report = broadcaster.generate_report()

    print("\n" + "=" * 60)
    print("REPORT GENERATED SUCCESSFULLY")
    print("=" * 60)
    print(f"Uptime: {report['uptime_sec']:.1f} seconds")
    print(f"Connection events: {report['total_connection_events']}")
    print(f"Unique clients: {report['unique_clients']}")
    print(f"Messages sent: {report['total_messages_sent']}")
    print(f"Send failures: {report['total_send_failures']}")
    print("=" * 60)

    report_dir = Path(__file__).parent / "reports"
    date_tag = broadcaster._start_time.strftime("%Y%m%d")
    txt_path = report_dir / f"ws_bridge_{date_tag}.txt"
    json_path = report_dir / f"ws_bridge_{date_tag}.json"

    print(f"\nTXT report: {txt_path}")
    print(f"JSON report: {json_path}")
    print(f"TXT exists: {os.path.exists(txt_path)}")
    print(f"JSON exists: {os.path.exists(json_path)}")

    if os.path.exists(txt_path):
        print("\n" + "=" * 60)
        print("TXT REPORT PREVIEW (first 30 lines):")
        print("=" * 60)
        with open(txt_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for i, line in enumerate(lines[:30]):
                print(line.rstrip())
        print(f"\n... ({len(lines)} total lines)")

    print("\n" + "=" * 60)
    print("TEST PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_report_generation())
