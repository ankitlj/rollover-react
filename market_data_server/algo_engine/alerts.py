import threading
import logging
from dataclasses import dataclass
from typing import Dict, Optional, List
from datetime import datetime

from .config import THRESHOLDS, IST
from .spread import SpreadSnapshot

log = logging.getLogger("algo_alerts")


@dataclass
class Alert:
    stock: str
    timestamp: str
    spread: float
    discount_pct: float
    threshold: int
    trigger_count: int
    initial_spread: float
    current_fut_ltp: float
    next_fut_ltp: float


class AlertEngine:
    def __init__(self, thresholds: Dict[str, int] = None):
        self._thresholds = thresholds if thresholds is not None else dict(THRESHOLDS)
        self._lock = threading.Lock()
        
        self._prev_above_threshold: Dict[str, bool] = {}
        self._trigger_counts: Dict[str, int] = {}
        self._last_alert_date: Dict[str, str] = {}
        
        self._alerts: List[Alert] = []
    
    def process_snapshot(self, snapshot: SpreadSnapshot) -> Optional[Alert]:
        if snapshot is None:
            return None
        
        stock = snapshot.stock
        threshold = self._thresholds.get(stock)
        if threshold is None:
            return None
        
        currently_above = snapshot.discount_pct >= threshold
        
        with self._lock:
            today = snapshot.timestamp[:10]
            if self._last_alert_date.get(stock) != today:
                self._trigger_counts[stock] = 0
                self._last_alert_date[stock] = today
            
            prev_above = self._prev_above_threshold.get(stock, False)
            
            if currently_above and not prev_above:
                self._trigger_counts[stock] += 1
                alert = Alert(
                    stock=stock,
                    timestamp=snapshot.timestamp,
                    spread=snapshot.spread,
                    discount_pct=snapshot.discount_pct,
                    threshold=threshold,
                    trigger_count=self._trigger_counts[stock],
                    initial_spread=snapshot.initial_spread,
                    current_fut_ltp=snapshot.current_fut_ltp,
                    next_fut_ltp=snapshot.next_fut_ltp,
                )
                self._alerts.append(alert)
                self._prev_above_threshold[stock] = True
                log.info(
                    f"ALERT: {stock} | discount={snapshot.discount_pct:.2f}% >= {threshold}% | "
                    f"spread={snapshot.spread:.2f} | trigger#{self._trigger_counts[stock]}"
                )
                return alert
            
            self._prev_above_threshold[stock] = currently_above
            return None
    
    def get_trigger_count(self, stock: str) -> int:
        with self._lock:
            return self._trigger_counts.get(stock, 0)
    
    def get_all_alerts(self) -> List[Alert]:
        with self._lock:
            return list(self._alerts)
    
    def get_alert_count(self) -> int:
        with self._lock:
            return len(self._alerts)
    
    def reset(self):
        with self._lock:
            self._prev_above_threshold.clear()
            self._trigger_counts.clear()
            self._last_alert_date.clear()
            self._alerts.clear()
    
    def reset_daily(self):
        with self._lock:
            self._trigger_counts.clear()
            self._last_alert_date.clear()
