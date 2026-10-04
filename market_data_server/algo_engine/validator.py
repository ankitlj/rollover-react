import threading
from typing import Optional, Tuple, Dict
from .bridge import Tick


class TickValidator:
    def __init__(self):
        self._lock = threading.Lock()
        self._prev_ts: Dict[int, str] = {}
        self._rejected_count: int = 0
        self._passed_count: int = 0
        self._rejected_by_reason: Dict[str, int] = {
            "ltp_zero": 0,
            "ts_backward": 0,
        }

    def check(self, tick: Tick) -> Tuple[bool, Optional[str]]:
        with self._lock:
            prev_ts = self._prev_ts.get(tick.token)

            if not (tick.ltp > 0):
                self._rejected_count += 1
                self._rejected_by_reason["ltp_zero"] += 1
                return False, "ltp_zero"

            if prev_ts is not None and tick.ts and tick.ts <= prev_ts:
                self._rejected_count += 1
                self._rejected_by_reason["ts_backward"] += 1
                return False, "ts_backward"

            self._prev_ts[tick.token] = tick.ts
            self._passed_count += 1
            return True, None

    def process_tick(self, tick: Tick) -> bool:
        valid, _ = self.check(tick)
        return valid

    @property
    def rejected_count(self) -> int:
        with self._lock:
            return self._rejected_count

    @property
    def passed_count(self) -> int:
        with self._lock:
            return self._passed_count

    @property
    def rejected_by_reason(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._rejected_by_reason)

    def get_prev_ts(self, token: int) -> Optional[str]:
        with self._lock:
            return self._prev_ts.get(token)

    def reset(self):
        with self._lock:
            self._prev_ts.clear()
            self._rejected_count = 0
            self._passed_count = 0
            for k in self._rejected_by_reason:
                self._rejected_by_reason[k] = 0
