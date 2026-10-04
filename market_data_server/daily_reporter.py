"""
Daily Reporter — end-of-day operations report with root-cause diagnostics.

Tracks:
  - Per-token tick counts, data gaps, exchange-side latency
  - WS close codes (distinguishes Arrow-side vs network vs normal)
  - WS errors, reconnection exhaustion
  - Tick rate timeline (5-min buckets — shows degradation)
  - Per-token gap frequency (shows which instruments are problematic)
  - Client connections, WS queue drops
  - Generates VERDICT: HEALTHY / DEGRADED / FAILED
"""

import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

import config

log = logging.getLogger("daily_reporter")


class DailyReporter:
    def __init__(self):
        self._lock = threading.RLock()
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None

        self._token_tick_counts: dict[int, int] = {}
        self._token_first_tick: dict[int, datetime] = {}
        self._token_last_tick: dict[int, datetime] = {}
        self._token_last_monotonic: dict[int, float] = {}
        self._token_gap_counts: dict[int, int] = defaultdict(int)

        self._gaps: list = []
        self._gap_threshold_s = 10.0

        self._state_transitions: list = []
        self._ws_close_events: list = []
        self._ws_error_events: list = []
        self._ws_disconnect_events: list = []
        self._reconnect_events: list = []
        self._no_reconnect_fired = False
        self._generation_changes: list = []
        self._errors: list = []
        self._client_events: list = []
        self._peak_clients = 0

        self._ws_drops = 0
        self._ws_drop_timestamps: list = []
        self._ws_broadcasts = 0
        self._ws_ticks_sent = 0

        self._total_ticks = 0
        self._tick_buckets: dict[str, int] = {}

        self._latency_sum = 0.0
        self._latency_count = 0
        self._latency_min = float('inf')
        self._latency_max = 0.0

        self._gap_check_thread: Optional[threading.Thread] = None
        self._shutdown = threading.Event()

    def start(self):
        self._start_time = datetime.now(config.IST)
        self._shutdown.clear()
        self._gap_check_thread = threading.Thread(target=self._gap_check_loop, daemon=True, name="gap-checker")
        self._gap_check_thread.start()
        log.info("DailyReporter started")

    def stop(self):
        log.info("DailyReporter stopping...")
        self._shutdown.set()
        self._end_time = datetime.now(config.IST)
        if self._gap_check_thread and self._gap_check_thread.is_alive():
            self._gap_check_thread.join(timeout=3)

    def record_tick(self, snapshot):
        now = datetime.now(config.IST)
        now_mono = time.monotonic()
        bucket_key = now.strftime("%H:") + ("0" if now.minute < 30 else "3") + "0"

        with self._lock:
            self._total_ticks += 1
            token = snapshot.token
            self._token_tick_counts[token] = self._token_tick_counts.get(token, 0) + 1
            if token not in self._token_first_tick:
                self._token_first_tick[token] = now
            self._token_last_tick[token] = now
            self._token_last_monotonic[token] = now_mono

            self._tick_buckets[bucket_key] = self._tick_buckets.get(bucket_key, 0) + 1

            if hasattr(snapshot, 'ltt') and snapshot.ltt and snapshot.ltt > 0:
                latency_ms = snapshot.receive_epoch_ms - snapshot.ltt
                if 0 < latency_ms < 60000:
                    self._latency_sum += latency_ms
                    self._latency_count += 1
                    if latency_ms < self._latency_min:
                        self._latency_min = latency_ms
                    if latency_ms > self._latency_max:
                        self._latency_max = latency_ms

    def record_state_transition(self, old_state: str, new_state: str, reason: str = ""):
        with self._lock:
            self._state_transitions.append({
                "time": datetime.now(config.IST).strftime("%H:%M:%S"),
                "from": old_state,
                "to": new_state,
                "reason": reason,
            })

    def record_event(self, event_type: str, details: dict):
        with self._lock:
            ts = datetime.now(config.IST).strftime("%H:%M:%S")
            if event_type == "ws_close":
                self._ws_close_events.append({"time": ts, **details})
            elif event_type == "ws_error":
                self._ws_error_events.append({"time": ts, **details})
            elif event_type == "ws_disconnect":
                self._ws_disconnect_events.append({"time": ts})
            elif event_type == "ws_reconnect":
                self._reconnect_events.append({"time": ts, **details})
                gen = details.get("generation")
                if gen is not None:
                    self._generation_changes.append({"time": ts, "generation": gen})
            elif event_type == "ws_no_reconnect":
                self._no_reconnect_fired = True
                self._errors.append({"time": ts, "error": "MAX RECONNECTION ATTEMPTS EXHAUSTED", "context": "Arrow SDK gave up"})

    def record_error(self, error: str, context: str = ""):
        with self._lock:
            self._errors.append({
                "time": datetime.now(config.IST).strftime("%H:%M:%S"),
                "error": error,
                "context": context,
            })

    def record_client_connect(self, addr):
        with self._lock:
            self._client_events.append({
                "time": datetime.now(config.IST).strftime("%H:%M:%S"),
                "event": "connect",
                "addr": str(addr),
            })
            current = sum(1 for e in self._client_events if e["event"] == "connect") - \
                      sum(1 for e in self._client_events if e["event"] == "disconnect")
            if current > self._peak_clients:
                self._peak_clients = current

    def record_client_disconnect(self, addr):
        with self._lock:
            self._client_events.append({
                "time": datetime.now(config.IST).strftime("%H:%M:%S"),
                "event": "disconnect",
                "addr": str(addr),
            })

    def record_ws_drop(self):
        with self._lock:
            self._ws_drops += 1
            self._ws_drop_timestamps.append(datetime.now(config.IST).strftime("%H:%M:%S"))

    def update_ws_stats(self, broadcasts: int, ticks_sent: int):
        with self._lock:
            self._ws_broadcasts = broadcasts
            self._ws_ticks_sent = ticks_sent

    def _gap_check_loop(self):
        while not self._shutdown.is_set():
            self._shutdown.wait(timeout=30)
            if self._shutdown.is_set():
                break
            now_mono = time.monotonic()
            with self._lock:
                silent_tokens = []
                for token, last_mono in self._token_last_monotonic.items():
                    silence = now_mono - last_mono
                    if silence > self._gap_threshold_s:
                        silent_tokens.append((token, silence))
                        self._token_gap_counts[token] += 1
                if silent_tokens:
                    self._gaps.append({
                        "time": datetime.now(config.IST).strftime("%H:%M:%S"),
                        "tokens_affected": len(silent_tokens),
                        "max_silence_s": round(max(s for _, s in silent_tokens), 1),
                        "tokens": [t for t, _ in silent_tokens[:10]],
                    })

    def _compute_verdict(self) -> tuple[str, list[str]]:
        issues = []

        if self._no_reconnect_fired:
            return "FAILED", ["Arrow feed connection lost permanently (max reconnect exhausted)"]

        total_disconnects = len(self._ws_close_events) + len(self._ws_disconnect_events)
        if total_disconnects > 5:
            issues.append(f"Feed disconnected {total_disconnects} times — unstable connection")

        if self._ws_error_events:
            issues.append(f"{len(self._ws_error_events)} WebSocket error(s) from Arrow SDK")

        long_gaps = [g for g in self._gaps if g["max_silence_s"] > 60]
        if long_gaps:
            worst = max(long_gaps, key=lambda g: g["max_silence_s"])
            issues.append(f"{len(long_gaps)} long data gap(s) >60s (worst: {worst['max_silence_s']}s at {worst['time']})")

        if self._gaps:
            issues.append(f"{len(self._gaps)} data gap(s) >{self._gap_threshold_s:.0f}s detected")

        if self._ws_drops > 100:
            issues.append(f"{self._ws_drops} WS queue drops — broadcast can't keep up with feed")

        avg_latency = (self._latency_sum / self._latency_count) if self._latency_count > 0 else 0
        if avg_latency > 5000:
            issues.append(f"High average exchange latency: {avg_latency:.0f}ms (Arrow delivery lag)")

        if not issues:
            return "HEALTHY", []
        elif len(issues) <= 2 and not self._no_reconnect_fired:
            return "DEGRADED", issues
        else:
            return "FAILED", issues

    def generate_report(self, connector=None) -> str:
        if not self._end_time:
            self._end_time = datetime.now(config.IST)
        date_str = self._start_time.strftime("%Y-%m-%d") if self._start_time else "unknown"
        duration = self._end_time - self._start_time if self._start_time else timedelta(0)
        hours, remainder = divmod(int(duration.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        duration_str = f"{hours}h {minutes}m {seconds}s"

        verdict, verdict_issues = self._compute_verdict()

        lines = []
        lines.append("=" * 60)
        lines.append(f"  DAILY OPERATIONS REPORT — {date_str}")
        lines.append("=" * 60)
        lines.append("")

        lines.append(f"VERDICT: {verdict}")
        if verdict_issues:
            for issue in verdict_issues:
                lines.append(f"  !! {issue}")
        elif verdict == "HEALTHY":
            lines.append("  All systems nominal. No issues detected.")
        lines.append("")

        lines.append("SESSION")
        lines.append(f"  Start:     {self._start_time.strftime('%Y-%m-%d %H:%M:%S') if self._start_time else '?'} IST")
        lines.append(f"  End:       {self._end_time.strftime('%Y-%m-%d %H:%M:%S') if self._end_time else '?'} IST")
        lines.append(f"  Duration:  {duration_str}")
        lines.append(f"  Total ticks received: {self._total_ticks:,}")
        lines.append("")

        lines.append("FEED HEALTH")
        final_state = self._state_transitions[-1]["to"] if self._state_transitions else "UNKNOWN"
        lines.append(f"  Final state:        {final_state}")
        lines.append(f"  State transitions:  {len(self._state_transitions)}")
        lines.append(f"  WS close events:    {len(self._ws_close_events)}")
        lines.append(f"  WS disconnects:     {len(self._ws_disconnect_events)}")
        lines.append(f"  WS errors:          {len(self._ws_error_events)}")
        lines.append(f"  Reconnections:      {len(self._reconnect_events)}")
        lines.append(f"  Reconnect exhausted: {'YES — CRITICAL' if self._no_reconnect_fired else 'No'}")
        lines.append(f"  Generation changes: {len(self._generation_changes)}")
        lines.append("")

        if self._ws_close_events:
            lines.append("WS CLOSE EVENTS (why Arrow disconnected us)")
            for ev in self._ws_close_events:
                code = ev.get("code", "?")
                msg = ev.get("msg", "?")
                code_meaning = self._explain_close_code(code)
                lines.append(f"  [{ev['time']}] code={code} ({code_meaning}) — {msg}")
            lines.append("")

        if self._ws_error_events:
            lines.append("WS ERRORS (Arrow SDK errors)")
            for ev in self._ws_error_events:
                lines.append(f"  [{ev['time']}] {ev.get('error', '?')}")
            lines.append("")

        if self._state_transitions:
            lines.append("STATE TRANSITIONS")
            for t in self._state_transitions:
                lines.append(f"  [{t['time']}] {t['from']} -> {t['to']}  ({t['reason']})")
            lines.append("")

        if self._reconnect_events:
            lines.append("RECONNECTIONS")
            for r in self._reconnect_events:
                lines.append(f"  [{r['time']}] attempt={r.get('attempt', '?')}, delay={r.get('delay', '?')}s, gen={r.get('generation', '?')}")
            lines.append("")

        lines.append("DATA GAPS")
        if self._gaps:
            lines.append(f"  Total gap events: {len(self._gaps)}")
            long_gaps = [g for g in self._gaps if g["max_silence_s"] > 30]
            if long_gaps:
                lines.append(f"  Significant (>30s): {len(long_gaps)}")
                for g in long_gaps[-10:]:
                    lines.append(f"    [{g['time']}] {g['max_silence_s']}s silence — {g['tokens_affected']} tokens")
            lines.append(f"  All gap events (>{self._gap_threshold_s:.0f}s):")
            for g in self._gaps[-20:]:
                lines.append(f"    [{g['time']}] {g['max_silence_s']}s — {g['tokens_affected']} tokens")
        else:
            lines.append("  None — clean feed throughout the session")
        lines.append("")

        if self._token_gap_counts:
            lines.append("PER-TOKEN GAP FREQUENCY (which instruments had issues)")
            sorted_gap_tokens = sorted(self._token_gap_counts.items(), key=lambda x: x[1], reverse=True)
            token_info = connector.get_token_to_info() if connector else {}
            for token, count in sorted_gap_tokens[:10]:
                info = token_info.get(token, {})
                sym = info.get("sym", "?")
                typ = info.get("type", "?")
                month = info.get("month", "")
                label = f"{sym} {typ}" + (f" {month}" if month else "")
                lines.append(f"  {token} ({label}): {count} gap events")
            lines.append("")

        if self._latency_count > 0:
            avg_lat = self._latency_sum / self._latency_count
            lines.append("EXCHANGE LATENCY (receive_time - exchange_time)")
            lines.append(f"  Samples: {self._latency_count:,}")
            lines.append(f"  Min:     {self._latency_min:.0f}ms")
            lines.append(f"  Avg:     {avg_lat:.0f}ms")
            lines.append(f"  Max:     {self._latency_max:.0f}ms")
            if avg_lat > 3000:
                lines.append(f"  WARNING: Avg latency >3s suggests Arrow is delivering stale data")
            lines.append("")

        lines.append("TICK RATE (5-min buckets)")
        if self._tick_buckets:
            sorted_buckets = sorted(self._tick_buckets.items())
            for bucket, count in sorted_buckets:
                bar = "#" * min(count // 500, 50)
                lines.append(f"  {bucket}  {count:>8,} ticks  {bar}")
            total_duration_min = duration.total_seconds() / 60
            if total_duration_min > 0:
                avg_rate = self._total_ticks / total_duration_min
                lines.append(f"  Avg rate: {avg_rate:.0f} ticks/min")
        lines.append("")

        if self._errors:
            lines.append("ERRORS")
            lines.append(f"  Count: {len(self._errors)}")
            for e in self._errors[-50:]:
                ctx = f" ({e['context']})" if e["context"] else ""
                lines.append(f"  [{e['time']}] {e['error']}{ctx}")
            lines.append("")
        else:
            lines.append("ERRORS")
            lines.append("  None")
            lines.append("")

        lines.append("CLIENT CONNECTIONS")
        connects = sum(1 for e in self._client_events if e["event"] == "connect")
        disconnects = sum(1 for e in self._client_events if e["event"] == "disconnect")
        lines.append(f"  Total connections:     {connects}")
        lines.append(f"  Total disconnections:  {disconnects}")
        lines.append(f"  Peak concurrent:       {self._peak_clients}")
        lines.append("")

        lines.append("WS BROADCAST")
        lines.append(f"  Broadcasts:    {self._ws_broadcasts:,}")
        lines.append(f"  Ticks sent:    {self._ws_ticks_sent:,}")
        lines.append(f"  Queue drops:   {self._ws_drops:,}")
        if self._ws_drop_timestamps:
            lines.append(f"  Drop times:    {', '.join(self._ws_drop_timestamps[-10:])}")
        lines.append("")

        if connector:
            lines.append("TOKEN COVERAGE")
            token_info_map = connector.get_token_to_info()
            with self._lock:
                counts = dict(self._token_tick_counts)
            sorted_tokens = sorted(counts.items(), key=lambda x: x[1])
            lines.append(f"  Tokens with data: {len(counts)}")
            expected = len(connector.get_all_tokens()) if hasattr(connector, 'get_all_tokens') else 57
            if len(counts) < expected:
                missing_tokens = set(connector.get_all_tokens()) - set(counts.keys())
                lines.append(f"  WARNING: {expected - len(counts)} tokens NEVER received data:")
                for t in list(missing_tokens)[:10]:
                    info = token_info_map.get(t, {})
                    sym = info.get("sym", "?")
                    typ = info.get("type", "?")
                    lines.append(f"    {t} ({sym} {typ})")
            if sorted_tokens:
                lines.append(f"  Fewest ticks:")
                for token, count in sorted_tokens[:5]:
                    info = token_info_map.get(token, {})
                    sym = info.get("sym", "?")
                    typ = info.get("type", "?")
                    month = info.get("month", "")
                    label = f"{sym} {typ}" + (f" {month}" if month else "")
                    lines.append(f"    {token} ({label}): {count:,} ticks")
                lines.append(f"  Most ticks:")
                for token, count in sorted_tokens[-3:]:
                    info = token_info_map.get(token, {})
                    sym = info.get("sym", "?")
                    typ = info.get("type", "?")
                    month = info.get("month", "")
                    label = f"{sym} {typ}" + (f" {month}" if month else "")
                    lines.append(f"    {token} ({label}): {count:,} ticks")
            lines.append("")

        report_text = "\n".join(lines)

        config.REPORT_DIR.mkdir(parents=True, exist_ok=True)

        report_path = config.REPORT_DIR / f"report_{self._start_time.strftime('%Y%m%d') if self._start_time else 'unknown'}.txt"
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report_text)
            log.info(f"Daily report saved: {report_path}")
        except Exception as e:
            log.error(f"Failed to save report: {e}")

        json_path = config.REPORT_DIR / f"report_{self._start_time.strftime('%Y%m%d') if self._start_time else 'unknown'}.json"
        try:
            json_data = {
                "date": date_str,
                "verdict": verdict,
                "verdict_issues": verdict_issues,
                "start": self._start_time.isoformat() if self._start_time else None,
                "end": self._end_time.isoformat() if self._end_time else None,
                "duration_s": duration.total_seconds(),
                "total_ticks": self._total_ticks,
                "state_transitions": self._state_transitions,
                "ws_close_events": self._ws_close_events,
                "ws_error_events": self._ws_error_events,
                "ws_disconnect_events": self._ws_disconnect_events,
                "reconnections": self._reconnect_events,
                "no_reconnect_fired": self._no_reconnect_fired,
                "generation_changes": self._generation_changes,
                "gaps": self._gaps,
                "token_gap_counts": {str(k): v for k, v in self._token_gap_counts.items()},
                "errors": self._errors,
                "client_events": self._client_events,
                "peak_clients": self._peak_clients,
                "ws_broadcasts": self._ws_broadcasts,
                "ws_ticks_sent": self._ws_ticks_sent,
                "ws_drops": self._ws_drops,
                "ws_drop_timestamps": self._ws_drop_timestamps,
                "tick_rate_buckets": self._tick_buckets,
                "latency": {
                    "min_ms": self._latency_min if self._latency_count > 0 else None,
                    "avg_ms": round(self._latency_sum / self._latency_count, 1) if self._latency_count > 0 else None,
                    "max_ms": self._latency_max if self._latency_count > 0 else None,
                    "samples": self._latency_count,
                },
                "token_tick_counts": {str(k): v for k, v in self._token_tick_counts.items()},
            }
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(json_data, f, indent=2, default=str)
            log.info(f"Daily report JSON saved: {json_path}")
        except Exception as e:
            log.error(f"Failed to save report JSON: {e}")

        return report_text

    @staticmethod
    def _explain_close_code(code) -> str:
        if code is None or code == "None":
            return "no code — abnormal termination"
        try:
            code_int = int(code)
        except (ValueError, TypeError):
            return f"non-standard: {code}"
        if code_int == 1000:
            return "normal closure"
        elif code_int == 1001:
            return "endpoint going away (server shutdown)"
        elif code_int == 1002:
            return "protocol error"
        elif code_int == 1006:
            return "abnormal closure (no close frame) — network drop"
        elif code_int == 1011:
            return "unexpected server error"
        elif code_int == 1012:
            return "server restarting"
        elif code_int == 1013:
            return "server overloaded — try again later"
        elif code_int >= 4000:
            return f"Arrow custom code {code_int}"
        else:
            return f"code {code_int}"

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "total_ticks": self._total_ticks,
                "tokens_with_data": len(self._token_tick_counts),
                "gaps": len(self._gaps),
                "errors": len(self._errors),
                "reconnections": len(self._reconnect_events),
                "ws_drops": self._ws_drops,
            }
