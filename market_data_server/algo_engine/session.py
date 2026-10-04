import threading
import logging
from typing import Optional, List, Dict, Set
from datetime import datetime, time

from .config import WARMUP_HOUR, WARMUP_MINUTE, CLOSE_HOUR, CLOSE_MINUTE, IST

log = logging.getLogger("algo_session")

PHASE_WAITING = "WAITING"
PHASE_WARMUP = "WARMUP"
PHASE_ACTIVE = "ACTIVE"
PHASE_CLOSING = "CLOSING"
PHASE_CLOSED = "CLOSED"

MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15
CLOSING_HOUR = 14
CLOSING_MINUTE = 45


class SessionEngine:
    def __init__(self):
        self._lock = threading.Lock()
        self._alerts_fired: int = 0
        self._stocks_triggered: Set[str] = set()
        self._first_alert_time: Optional[str] = None
        self._last_alert_time: Optional[str] = None
        self._phase_transitions: List[Dict] = []
        self._current_phase: Optional[str] = None
        self._session_start_time: Optional[str] = None
    
    def current_phase(self, now: Optional[datetime] = None) -> str:
        if now is None:
            now = datetime.now(IST)
        
        if now.weekday() >= 5:
            phase = PHASE_CLOSED
        else:
            current_time = now.time()
            market_open = time(MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE)
            warmup_end = time(WARMUP_HOUR, WARMUP_MINUTE)
            closing_start = time(CLOSING_HOUR, CLOSING_MINUTE)
            market_close = time(CLOSE_HOUR, CLOSE_MINUTE)
            
            if current_time < market_open:
                phase = PHASE_WAITING
            elif current_time < warmup_end:
                phase = PHASE_WARMUP
            elif current_time < closing_start:
                phase = PHASE_ACTIVE
            elif current_time < market_close:
                phase = PHASE_CLOSING
            else:
                phase = PHASE_CLOSED
        
        with self._lock:
            if self._current_phase != phase:
                old_phase = self._current_phase
                self._current_phase = phase
                ts = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                self._phase_transitions.append({
                    "from": old_phase,
                    "to": phase,
                    "timestamp": ts,
                })
                if old_phase is not None:
                    log.info(f"Session phase: {old_phase} → {phase}")
                else:
                    log.info(f"Session phase: {phase}")
                
                if self._session_start_time is None:
                    self._session_start_time = ts
        
        return phase
    
    def is_active(self, now: Optional[datetime] = None) -> bool:
        return self.current_phase(now) == PHASE_ACTIVE
    
    def is_warmup(self, now: Optional[datetime] = None) -> bool:
        return self.current_phase(now) == PHASE_WARMUP
    
    def should_compute_spreads(self, now: Optional[datetime] = None) -> bool:
        phase = self.current_phase(now)
        return phase in (PHASE_WARMUP, PHASE_ACTIVE, PHASE_CLOSING)
    
    def should_fire_alerts(self, now: Optional[datetime] = None) -> bool:
        return self.current_phase(now) == PHASE_ACTIVE
    
    def is_market_day(self, now: Optional[datetime] = None) -> bool:
        if now is None:
            now = datetime.now(IST)
        return now.weekday() < 5
    
    def record_alert(self, alert, timestamp: Optional[str] = None):
        if timestamp is None:
            timestamp = getattr(alert, 'timestamp', None) or datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        with self._lock:
            self._alerts_fired += 1
            self._stocks_triggered.add(alert.stock)
            
            if self._first_alert_time is None:
                self._first_alert_time = timestamp
            self._last_alert_time = timestamp
            
            log.info(f"Session alert #{self._alerts_fired}: {alert.stock} at {timestamp}")
    
    def session_summary(self) -> Dict:
        with self._lock:
            now = datetime.now(IST)
            session_duration = 0.0
            if self._session_start_time:
                try:
                    start_dt = datetime.strptime(self._session_start_time, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=IST)
                    session_duration = (now - start_dt).total_seconds()
                except ValueError:
                    pass
            
            return {
                "current_phase": self._current_phase,
                "session_start_time": self._session_start_time,
                "session_duration_seconds": session_duration,
                "alerts_fired": self._alerts_fired,
                "stocks_triggered": list(self._stocks_triggered),
                "stocks_triggered_count": len(self._stocks_triggered),
                "first_alert_time": self._first_alert_time,
                "last_alert_time": self._last_alert_time,
                "phase_transitions": list(self._phase_transitions),
                "is_market_day": self.is_market_day(now),
            }
    
    def reset(self):
        with self._lock:
            self._alerts_fired = 0
            self._stocks_triggered.clear()
            self._first_alert_time = None
            self._last_alert_time = None
            self._phase_transitions.clear()
            self._current_phase = None
            self._session_start_time = None
            log.info("Session engine reset")
