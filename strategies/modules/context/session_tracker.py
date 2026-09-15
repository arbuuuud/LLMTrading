"""
Session Context Tracker.
Tracks trading sessions (Asia, London, New York) and records Session High/Low ranges
in UTC time for liquidity analysis.
"""

from typing import Optional, Dict, Any
from datetime import datetime, time, date


class SessionTracker:
    def __init__(
        self,
        asia_start: time = time(0, 0),
        asia_end: time = time(6, 0),
        london_start: time = time(7, 0),
        london_end: time = time(11, 0),
        ny_start: time = time(12, 0),
        ny_end: time = time(16, 0),
    ):
        self.asia_start = asia_start
        self.asia_end = asia_end
        self.london_start = london_start
        self.london_end = london_end
        self.ny_start = ny_start
        self.ny_end = ny_end

        self.current_date: Optional[date] = None
        self.asia_high: Optional[float] = None
        self.asia_low: Optional[float] = None
        self.asia_complete: bool = False

    def update(self, bar: Dict[str, Any]):
        dt: datetime = bar["timestamp"]
        d = dt.date()
        t = dt.time()
        high = bar["high"]
        low = bar["low"]

        # Reset session levels on new day
        if self.current_date != d:
            self.current_date = d
            self.asia_high = None
            self.asia_low = None
            self.asia_complete = False

        # Accumulate Asia session range
        if self.asia_start <= t < self.asia_end:
            if self.asia_high is None or high > self.asia_high:
                self.asia_high = high
            if self.asia_low is None or low < self.asia_low:
                self.asia_low = low
        elif t >= self.asia_end and self.asia_high is not None and not self.asia_complete:
            self.asia_complete = True

    def is_in_london(self, dt: datetime) -> bool:
        t = dt.time()
        return self.london_start <= t < self.london_end

    def is_in_ny(self, dt: datetime) -> bool:
        t = dt.time()
        return self.ny_start <= t < self.ny_end

    def is_in_trade_window(self, dt: datetime, allow_london: bool = True, allow_ny: bool = True) -> bool:
        if allow_london and self.is_in_london(dt):
            return True
        if allow_ny and self.is_in_ny(dt):
            return True
        return False
