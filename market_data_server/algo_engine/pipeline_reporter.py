"""
Pipeline Reporter — aggregates all 4 components into single daily report.

Reads logs/reports from:
1. Market data server (run.py)
2. Algo engine (algo_run.py)
3. WS broadcaster (ws_broadcaster.py)
4. Frontend (localStorage - manual export)

Outputs:
- reports/pipeline_YYYYMMDD.txt
- reports/pipeline_YYYYMMDD.json
"""

import json
import os
import re
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

from .config import IST

log = logging.getLogger("pipeline_reporter")

REPORT_DIR = Path(__file__).parent.parent / "reports"
LOG_DIR = Path(__file__).parent.parent / "logs"


class PipelineReporter:
    def __init__(self):
        self._start_time = datetime.now(IST)

    def _parse_log_file(self, log_path: Path, component: str) -> Dict:
        if not log_path.exists():
            return {"status": "no_log_file", "path": str(log_path)}

        errors = []
        warnings = []
        line_count = 0

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line_count += 1
                    if "ERROR" in line or "Exception" in line:
                        errors.append(line.strip())
                    elif "WARNING" in line or "WARN" in line:
                        warnings.append(line.strip())
        except Exception as e:
            return {"status": "read_error", "error": str(e)}

        return {
            "status": "ok",
            "path": str(log_path),
            "line_count": line_count,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "last_5_errors": errors[-5:] if errors else [],
        }

    def _parse_algo_report_json(self, json_path: Path) -> Dict:
        if not json_path.exists():
            return {"status": "no_report_file"}

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "status": "ok",
                "cycles": data.get("cycle_count", 0),
                "alerts_fired": data.get("alerts_fired", 0),
                "stocks_computed": data.get("stocks_computed", 0),
                "validator_rejected": data.get("validator_rejected", 0),
            }
        except Exception as e:
            return {"status": "read_error", "error": str(e)}

    def _parse_ws_bridge_report_json(self, json_path: Path) -> Dict:
        if not json_path.exists():
            return {"status": "no_report_file"}

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "status": "ok",
                "unique_clients": data.get("unique_clients", 0),
                "messages_sent": data.get("total_messages_sent", 0),
                "send_failures": data.get("total_send_failures", 0),
                "connection_events": data.get("total_connection_events", 0),
            }
        except Exception as e:
            return {"status": "read_error", "error": str(e)}

    def generate_report(self) -> Dict:
        end_time = datetime.now(IST)
        date_tag = self._start_time.strftime("%Y%m%d")

        server_log = LOG_DIR / f"server_{date_tag}.log"
        algo_log = LOG_DIR / f"algo_{date_tag}.log"
        algo_report_json = REPORT_DIR / f"algo_report_{date_tag}.json"
        ws_bridge_json = REPORT_DIR / f"ws_bridge_{date_tag}.json"

        market_data = self._parse_log_file(server_log, "market_data_server")
        algo_log_data = self._parse_log_file(algo_log, "algo_engine")
        algo_report_data = self._parse_algo_report_json(algo_report_json)
        ws_bridge_data = self._parse_ws_bridge_report_json(ws_bridge_json)

        pipeline_status = "healthy"
        issues = []

        if market_data.get("error_count", 0) > 0:
            pipeline_status = "degraded"
            issues.append(f"Market data server: {market_data['error_count']} errors")

        if algo_log_data.get("error_count", 0) > 0:
            pipeline_status = "degraded"
            issues.append(f"Algo engine: {algo_log_data['error_count']} errors")

        if ws_bridge_data.get("send_failures", 0) > 0:
            pipeline_status = "degraded"
            issues.append(f"WS bridge: {ws_bridge_data['send_failures']} send failures")

        if market_data.get("status") == "no_log_file":
            pipeline_status = "critical"
            issues.append("Market data server log missing")

        if algo_log_data.get("status") == "no_log_file":
            pipeline_status = "critical"
            issues.append("Algo engine log missing")

        report_data = {
            "component": "pipeline_reporter",
            "date": self._start_time.strftime("%Y-%m-%d"),
            "generated_at": end_time.strftime("%Y-%m-%d %H:%M:%S"),
            "pipeline_status": pipeline_status,
            "issues": issues,
            "market_data_server": market_data,
            "algo_engine_log": algo_log_data,
            "algo_engine_report": algo_report_data,
            "ws_broadcaster": ws_bridge_data,
            "frontend": {
                "status": "check_browser_localstorage",
                "key": "rs-connection-health",
                "note": "Open browser DevTools > Application > Local Storage to view",
            },
        }

        REPORT_DIR.mkdir(parents=True, exist_ok=True)

        txt_path = REPORT_DIR / f"pipeline_{date_tag}.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("PIPELINE DAILY REPORT\n")
            f.write("=" * 70 + "\n\n")
            f.write(f"Date: {report_data['date']}\n")
            f.write(f"Generated: {report_data['generated_at']}\n")
            f.write(f"Pipeline Status: {pipeline_status.upper()}\n\n")

            if issues:
                f.write("ISSUES DETECTED\n")
                f.write("-" * 70 + "\n")
                for issue in issues:
                    f.write(f"  • {issue}\n")
                f.write("\n")

            f.write("COMPONENT STATUS\n")
            f.write("-" * 70 + "\n\n")

            f.write("1. MARKET DATA SERVER\n")
            f.write(f"   Log File: {market_data.get('path', 'N/A')}\n")
            f.write(f"   Status: {market_data.get('status', 'unknown')}\n")
            if market_data.get("status") == "ok":
                f.write(f"   Lines: {market_data.get('line_count', 0)}\n")
                f.write(f"   Errors: {market_data.get('error_count', 0)}\n")
                f.write(f"   Warnings: {market_data.get('warning_count', 0)}\n")
                if market_data.get("last_5_errors"):
                    f.write("   Last 5 Errors:\n")
                    for err in market_data["last_5_errors"]:
                        f.write(f"     {err[:100]}\n")
            f.write("\n")

            f.write("2. ALGO ENGINE\n")
            f.write(f"   Log File: {algo_log_data.get('path', 'N/A')}\n")
            f.write(f"   Log Status: {algo_log_data.get('status', 'unknown')}\n")
            if algo_log_data.get("status") == "ok":
                f.write(f"   Lines: {algo_log_data.get('line_count', 0)}\n")
                f.write(f"   Errors: {algo_log_data.get('error_count', 0)}\n")
                f.write(f"   Warnings: {algo_log_data.get('warning_count', 0)}\n")
            f.write(f"   Report Status: {algo_report_data.get('status', 'unknown')}\n")
            if algo_report_data.get("status") == "ok":
                f.write(f"   Cycles: {algo_report_data.get('cycles', 0)}\n")
                f.write(f"   Alerts Fired: {algo_report_data.get('alerts_fired', 0)}\n")
                f.write(f"   Stocks Computed: {algo_report_data.get('stocks_computed', 0)}\n")
                f.write(f"   Validator Rejected: {algo_report_data.get('validator_rejected', 0)}\n")
            f.write("\n")

            f.write("3. WS BROADCASTER\n")
            f.write(f"   Report Status: {ws_bridge_data.get('status', 'unknown')}\n")
            if ws_bridge_data.get("status") == "ok":
                f.write(f"   Unique Clients: {ws_bridge_data.get('unique_clients', 0)}\n")
                f.write(f"   Messages Sent: {ws_bridge_data.get('messages_sent', 0)}\n")
                f.write(f"   Send Failures: {ws_bridge_data.get('send_failures', 0)}\n")
                f.write(f"   Connection Events: {ws_bridge_data.get('connection_events', 0)}\n")
            f.write("\n")

            f.write("4. FRONTEND\n")
            f.write(f"   Status: {report_data['frontend']['status']}\n")
            f.write(f"   LocalStorage Key: {report_data['frontend']['key']}\n")
            f.write(f"   Note: {report_data['frontend']['note']}\n")
            f.write("\n")

            f.write("=" * 70 + "\n")
            f.write("END OF REPORT\n")

        json_path = REPORT_DIR / f"pipeline_{date_tag}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, default=str)

        log.info("Pipeline report generated: %s", txt_path)
        return report_data
