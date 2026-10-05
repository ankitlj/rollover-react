"""
Algo Engine Daily Reporter — end-of-day operations report with diagnostics.

Tracks:
  - Every alert with full details (stock, time, discount, spread, threshold, LTPs)
  - Per-stock alert counts and trigger frequencies
  - Session phase transitions (WAITING → WARMUP → ACTIVE → CLOSING → CLOSED)
  - Bridge connection state changes
  - Validator rejections (by reason: ltp_zero, ts_backward, ts_format)
  - Spread skip reasons (no_ticks, stale, negative_initial_spread, etc.)
  - Cycle counts and stocks computed/skipped
  - Errors and exceptions
  - Generates VERDICT: HEALTHY / DEGRADED / FAILED
"""

import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict

from .config import IST, STOCK_CONFIG
from .alerts import Alert
from .bridge import TickBridge
from .orchestrator import AlgoOrchestrator

log = logging.getLogger("algo_reporter")


class AlgoReporter:
    def __init__(self, orchestrator: AlgoOrchestrator, bridge: TickBridge):
        self._orchestrator = orchestrator
        self._bridge = bridge
        self._lock = threading.RLock()
        
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None
        
        # Alert tracking
        self._alerts: List[Dict] = []
        self._alerts_by_stock: Dict[str, List[Dict]] = defaultdict(list)
        self._active_alerts: Dict[str, Dict] = {}  # stock -> alert data while active
        
        # Session phase transitions
        self._phase_transitions: List[Dict] = []
        self._last_phase: Optional[str] = None
        
        # Bridge connection events
        self._bridge_connect_events: List[Dict] = []
        self._bridge_disconnect_events: List[Dict] = []
        self._was_connected: bool = False
        
        # Error tracking
        self._errors: List[Dict] = []
        
        # Periodic snapshots
        self._snapshots: List[Dict] = []
        self._snapshot_thread: Optional[threading.Thread] = None
        self._shutdown = threading.Event()
    
    def start(self):
        self._start_time = datetime.now(IST)
        self._shutdown.clear()
        self._snapshot_thread = threading.Thread(
            target=self._snapshot_loop, daemon=True, name="algo-reporter"
        )
        self._snapshot_thread.start()
        log.info("AlgoReporter started")
    
    def stop(self):
        log.info("AlgoReporter stopping...")
        self._shutdown.set()
        self._end_time = datetime.now(IST)
        if self._snapshot_thread and self._snapshot_thread.is_alive():
            self._snapshot_thread.join(timeout=3)
        
        with self._lock:
            end_ts = self._end_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            for stock, alert_dict in list(self._active_alerts.items()):
                start_dt = datetime.strptime(alert_dict["timestamp"], "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=IST)
                end_dt = self._end_time
                duration = (end_dt - start_dt).total_seconds()
                alert_dict["duration_seconds"] = duration
                alert_dict["close_timestamp"] = end_ts
            self._active_alerts.clear()
    
    def record_alert(self, alert: Alert):
        with self._lock:
            alert_dict = {
                "stock": alert.stock,
                "timestamp": alert.timestamp,
                "spread": alert.spread,
                "discount_pct": alert.discount_pct,
                "threshold": alert.threshold,
                "trigger_count": alert.trigger_count,
                "initial_spread": alert.initial_spread,
                "current_fut_ltp": alert.current_fut_ltp,
                "next_fut_ltp": alert.next_fut_ltp,
                "duration_seconds": None,  # Will be set when alert closes
                "close_timestamp": None,
            }
            self._alerts.append(alert_dict)
            self._alerts_by_stock[alert.stock].append(alert_dict)
            self._active_alerts[alert.stock] = alert_dict
    
    def record_error(self, error: str, context: str = ""):
        with self._lock:
            self._errors.append({
                "time": datetime.now(IST).strftime("%H:%M:%S"),
                "error": error,
                "context": context,
            })
    
    def _snapshot_loop(self):
        while not self._shutdown.is_set():
            self._shutdown.wait(timeout=60)
            if self._shutdown.is_set():
                break
            
            now = datetime.now(IST)
            ts = now.strftime("%H:%M:%S")
            
            with self._lock:
                # Check bridge connection state
                connected = self._bridge.connected
                if connected and not self._was_connected:
                    self._bridge_connect_events.append({"time": ts})
                elif not connected and self._was_connected:
                    self._bridge_disconnect_events.append({"time": ts})
                self._was_connected = connected
                
                # Check session phase transitions
                phase = self._orchestrator.status()["phase"]
                if self._last_phase is not None and phase != self._last_phase:
                    self._phase_transitions.append({
                        "time": ts,
                        "from": self._last_phase,
                        "to": phase,
                    })
                self._last_phase = phase
                
                # Check active alerts for duration tracking
                self._check_alert_durations(now)
                
                # Take snapshot of orchestrator status
                status = self._orchestrator.status()
                self._snapshots.append({
                    "time": ts,
                    "cycle_count": status["cycle_count"],
                    "alerts_fired": status["alerts_fired"],
                    "stocks_computed": status["stocks_computed"],
                    "stocks_skipped": status["stocks_skipped"],
                    "validator_rejected": status["validator_rejected"],
                    "validator_passed": status["validator_passed"],
                    "bridge_connected": connected,
                    "bridge_ticks": self._bridge.tick_count,
                })
    
    def _check_alert_durations(self, now: datetime):
        """Check if any active alerts have dropped below threshold and calculate duration."""
        from .config import THRESHOLDS
        
        stocks_to_close = []
        for stock, alert_dict in self._active_alerts.items():
            snapshot = self._orchestrator._spread.get_snapshot(stock)
            if snapshot is None:
                continue
            
            threshold = THRESHOLDS.get(stock)
            if threshold is None:
                continue
            
            if snapshot.discount_pct < threshold:
                stocks_to_close.append((stock, snapshot.timestamp))
        
        for stock, close_ts in stocks_to_close:
            alert_dict = self._active_alerts.pop(stock)
            start_dt = datetime.strptime(alert_dict["timestamp"], "%Y-%m-%d %H:%M:%S.%f")
            end_dt = datetime.strptime(close_ts, "%Y-%m-%d %H:%M:%S.%f")
            duration = (end_dt - start_dt).total_seconds()
            alert_dict["duration_seconds"] = duration
            alert_dict["close_timestamp"] = close_ts
    
    def _compute_verdict(self) -> tuple[str, List[str]]:
        issues = []
        
        # Check bridge connection stability
        disconnect_count = len(self._bridge_disconnect_events)
        if disconnect_count > 5:
            issues.append(f"Bridge disconnected {disconnect_count} times — unstable connection")
        
        # Check if bridge ever connected
        if not self._bridge_connect_events and self._bridge.tick_count == 0:
            issues.append("Bridge never connected — no data received")
        
        # Check validator rejections
        status = self._orchestrator.status()
        validator_rejected = status["validator_rejected"]
        validator_passed = status["validator_passed"]
        if validator_rejected > 100:
            issues.append(f"{validator_rejected} validator rejections — data quality issues")
        
        # Check if any alerts fired during active session
        alerts_fired = len(self._alerts)
        active_snapshots = [s for s in self._snapshots if s.get("phase") == "ACTIVE"]
        if active_snapshots and alerts_fired == 0:
            issues.append("No alerts fired during ACTIVE session — possible data or logic issue")
        
        # Check for errors
        if len(self._errors) > 10:
            issues.append(f"{len(self._errors)} errors logged — check error section")
        
        # Check spread skip reasons
        skip_reasons = status.get("spread_skip_reasons", {})
        no_ticks_count = sum(1 for r in skip_reasons.values() if r == "no_ticks")
        if no_ticks_count > 10:
            issues.append(f"{no_ticks_count} stocks had no ticks for extended periods")
        
        # Determine verdict
        if not issues:
            return "HEALTHY", []
        elif len(issues) <= 2:
            return "DEGRADED", issues
        else:
            return "FAILED", issues
    
    def generate_report(self) -> str:
        if not self._end_time:
            self._end_time = datetime.now(IST)
        
        date_str = self._start_time.strftime("%Y-%m-%d") if self._start_time else "unknown"
        duration = self._end_time - self._start_time if self._start_time else timedelta(0)
        hours, remainder = divmod(int(duration.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        duration_str = f"{hours}h {minutes}m {seconds}s"
        
        verdict, verdict_issues = self._compute_verdict()
        status = self._orchestrator.status()
        
        lines = []
        lines.append("=" * 60)
        lines.append(f"  ALGO ENGINE DAILY REPORT — {date_str}")
        lines.append("=" * 60)
        lines.append("")
        
        lines.append(f"VERDICT: {verdict}")
        if verdict_issues:
            for issue in verdict_issues:
                lines.append(f"  !! {issue}")
        elif verdict == "HEALTHY":
            lines.append("  All systems nominal. No issues detected.")
        lines.append("")
        
        # Session info
        lines.append("SESSION")
        lines.append(f"  Start:     {self._start_time.strftime('%Y-%m-%d %H:%M:%S') if self._start_time else '?'} IST")
        lines.append(f"  End:       {self._end_time.strftime('%Y-%m-%d %H:%M:%S') if self._end_time else '?'} IST")
        lines.append(f"  Duration:  {duration_str}")
        lines.append(f"  Total cycles: {status['cycle_count']}")
        lines.append(f"  Stocks computed: {status['stocks_computed']}")
        lines.append(f"  Stocks skipped: {status['stocks_skipped']}")
        lines.append("")
        
        # Alerts summary
        lines.append("ALERTS SUMMARY")
        lines.append(f"  Total alerts fired: {len(self._alerts)}")
        if self._alerts:
            first_alert = self._alerts[0]["timestamp"]
            last_alert = self._alerts[-1]["timestamp"]
            lines.append(f"  First alert: {first_alert}")
            lines.append(f"  Last alert:  {last_alert}")
            
            # Per-stock breakdown
            lines.append(f"  Stocks with alerts: {len(self._alerts_by_stock)}")
            sorted_stocks = sorted(self._alerts_by_stock.items(), key=lambda x: len(x[1]), reverse=True)
            for stock, alerts in sorted_stocks[:10]:
                lines.append(f"    {stock}: {len(alerts)} alert(s)")
        else:
            lines.append("  No alerts fired")
        lines.append("")
        
        # Detailed alerts
        if self._alerts:
            lines.append("ALL ALERTS (chronological)")
            lines.append(f"  {'Time':<12} {'Stock':<15} {'Discount':<10} {'Threshold':<10} {'Spread':<10} {'Trigger#':<10} {'Duration':<12}")
            lines.append("  " + "-" * 82)
            for alert in self._alerts:
                time_str = alert["timestamp"][11:19] if len(alert["timestamp"]) > 11 else alert["timestamp"]
                duration_str = f"{alert['duration_seconds']:.0f}s" if alert['duration_seconds'] is not None else "active"
                lines.append(
                    f"  {time_str:<12} {alert['stock']:<15} {alert['discount_pct']:<10.2f} "
                    f"{alert['threshold']:<10} {alert['spread']:<10.2f} #{alert['trigger_count']:<9} {duration_str:<12}"
                )
            lines.append("")
        
        # Session phase transitions
        if self._phase_transitions:
            lines.append("SESSION PHASE TRANSITIONS")
            for transition in self._phase_transitions:
                lines.append(f"  [{transition['time']}] {transition['from']} → {transition['to']}")
            lines.append("")
        
        # Bridge health
        lines.append("BRIDGE HEALTH")
        lines.append(f"  Total ticks received: {self._bridge.tick_count:,}")
        lines.append(f"  Connection events: {len(self._bridge_connect_events)}")
        lines.append(f"  Disconnection events: {len(self._bridge_disconnect_events)}")
        if self._bridge_disconnect_events:
            lines.append(f"  Disconnect times: {', '.join(e['time'] for e in self._bridge_disconnect_events[-10:])}")
        lines.append("")
        
        # Validator stats
        lines.append("VALIDATOR STATS")
        lines.append(f"  Ticks passed: {status['validator_passed']:,}")
        lines.append(f"  Ticks rejected: {status['validator_rejected']:,}")
        if status['validator_rejected'] > 0:
            lines.append(f"  Rejection rate: {100 * status['validator_rejected'] / (status['validator_passed'] + status['validator_rejected']):.2f}%")
        lines.append("")
        
        # Spread skip reasons
        skip_reasons = status.get("spread_skip_reasons", {})
        if skip_reasons:
            lines.append("SPREAD SKIP REASONS (stocks that couldn't be computed)")
            sorted_reasons = sorted(skip_reasons.items(), key=lambda x: x[1] if isinstance(x[1], int) else 0, reverse=True)
            for stock, reason in sorted_reasons[:20]:
                lines.append(f"  {stock}: {reason}")
            lines.append("")
        
        # Errors
        if self._errors:
            lines.append("ERRORS")
            lines.append(f"  Count: {len(self._errors)}")
            for error in self._errors[-50:]:
                ctx = f" ({error['context']})" if error["context"] else ""
                lines.append(f"  [{error['time']}] {error['error']}{ctx}")
            lines.append("")
        else:
            lines.append("ERRORS")
            lines.append("  None")
            lines.append("")
        
        report_text = "\n".join(lines)
        
        report_dir = Path(__file__).parent.parent / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        
        date_tag = self._start_time.strftime("%Y%m%d") if self._start_time else "unknown"
        
        # Save .txt
        txt_path = report_dir / f"algo_report_{date_tag}.txt"
        try:
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(report_text)
            log.info(f"Algo report saved: {txt_path}")
        except Exception as e:
            log.error(f"Failed to save txt report: {e}")
        
        # Save .json
        json_path = report_dir / f"algo_report_{date_tag}.json"
        try:
            json_data = {
                "date": date_str,
                "verdict": verdict,
                "verdict_issues": verdict_issues,
                "start": self._start_time.isoformat() if self._start_time else None,
                "end": self._end_time.isoformat() if self._end_time else None,
                "duration_s": duration.total_seconds(),
                "total_cycles": status["cycle_count"],
                "stocks_computed": status["stocks_computed"],
                "stocks_skipped": status["stocks_skipped"],
                "total_alerts": len(self._alerts),
                "alerts": self._alerts,
                "alerts_by_stock": {k: len(v) for k, v in self._alerts_by_stock.items()},
                "phase_transitions": self._phase_transitions,
                "bridge_connect_events": self._bridge_connect_events,
                "bridge_disconnect_events": self._bridge_disconnect_events,
                "bridge_ticks": self._bridge.tick_count,
                "validator_passed": status["validator_passed"],
                "validator_rejected": status["validator_rejected"],
                "spread_skip_reasons": skip_reasons,
                "errors": self._errors,
                "snapshots": self._snapshots,
            }
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(json_data, f, indent=2)
            log.info(f"Algo report JSON saved: {json_path}")
        except Exception as e:
            log.error(f"Failed to save json report: {e}")
        
        return report_text
