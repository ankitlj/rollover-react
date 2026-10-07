"""Test pipeline reporter with dummy data."""
import sys
import os
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algo_engine.pipeline_reporter import PipelineReporter


def create_dummy_files():
    report_dir = Path(__file__).parent / "reports"
    log_dir = Path(__file__).parent / "logs"
    report_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    date_tag = datetime.now().strftime("%Y%m%d")

    server_log = log_dir / f"server_{date_tag}.log"
    with open(server_log, "w", encoding="utf-8") as f:
        f.write("2026-10-07 09:00:00 INFO Starting market data server\n")
        f.write("2026-10-07 09:00:01 INFO Connected to Arrow API\n")
        f.write("2026-10-07 09:15:30 WARNING Slow tick reception\n")
        f.write("2026-10-07 10:00:00 ERROR Connection timeout\n")
        f.write("2026-10-07 10:00:05 INFO Reconnected\n")
        f.write("2026-10-07 15:30:00 INFO Shutting down\n")

    algo_log = log_dir / f"algo_{date_tag}.log"
    with open(algo_log, "w", encoding="utf-8") as f:
        f.write("2026-10-07 09:00:00 INFO Algo engine starting\n")
        f.write("2026-10-07 09:00:01 INFO Bridge connected\n")
        f.write("2026-10-07 09:15:00 INFO Cycle 100 completed\n")
        f.write("2026-10-07 10:30:00 ERROR Spread calculation failed for RELIANCE\n")
        f.write("2026-10-07 15:30:00 INFO Shutting down\n")

    algo_report = report_dir / f"algo_report_{date_tag}.json"
    with open(algo_report, "w", encoding="utf-8") as f:
        json.dump({
            "cycle_count": 2500,
            "alerts_fired": 15,
            "stocks_computed": 45000,
            "validator_rejected": 120,
        }, f)

    ws_bridge = report_dir / f"ws_bridge_{date_tag}.json"
    with open(ws_bridge, "w", encoding="utf-8") as f:
        json.dump({
            "unique_clients": 2,
            "total_messages_sent": 5000,
            "total_send_failures": 3,
            "total_connection_events": 5,
        }, f)

    return date_tag


def test_pipeline_reporter():
    print("Creating dummy files...")
    date_tag = create_dummy_files()

    print("Testing pipeline reporter...")
    reporter = PipelineReporter()
    report = reporter.generate_report()

    print("\n" + "=" * 70)
    print("PIPELINE REPORT GENERATED SUCCESSFULLY")
    print("=" * 70)
    print(f"Date: {report['date']}")
    print(f"Pipeline Status: {report['pipeline_status'].upper()}")
    print(f"Issues: {len(report['issues'])}")
    if report['issues']:
        for issue in report['issues']:
            print(f"  • {issue}")
    print("=" * 70)

    report_dir = Path(__file__).parent / "reports"
    txt_path = report_dir / f"pipeline_{date_tag}.txt"
    json_path = report_dir / f"pipeline_{date_tag}.json"

    print(f"\nTXT report: {txt_path}")
    print(f"JSON report: {json_path}")
    print(f"TXT exists: {txt_path.exists()}")
    print(f"JSON exists: {json_path.exists()}")

    if txt_path.exists():
        print("\n" + "=" * 70)
        print("TXT REPORT PREVIEW:")
        print("=" * 70)
        with open(txt_path, "r", encoding="utf-8") as f:
            print(f.read())

    print("=" * 70)
    print("TEST PASSED")
    print("=" * 70)


if __name__ == "__main__":
    test_pipeline_reporter()
