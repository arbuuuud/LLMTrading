"""
Higher Timeframe Point of Interest (HTF POI) Tracker.
Aggregates incoming M1 bars into virtual M15 bars to detect macro Swing Highs,
Swing Lows, and institutional reaction zones.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime


class HTFPOITracker:
    def __init__(self, pivot_left_bars: int = 3, pivot_right_bars: int = 3, zone_buffer_dollars: float = 0.50):
        self.pivot_left = pivot_left_bars
        self.pivot_right = pivot_right_bars
        self.zone_buffer = zone_buffer_dollars

        self.current_m15_bar: Optional[Dict[str, Any]] = None
        self.m15_bars: List[Dict[str, Any]] = []
        
        self.swing_highs: List[float] = []
        self.swing_lows: List[float] = []

    def update(self, m1_bar: Dict[str, Any]):
        dt: datetime = m1_bar["timestamp"]
        m15_minute = (dt.minute // 15) * 15
        m15_time = dt.replace(minute=m15_minute, second=0, microsecond=0)

        if self.current_m15_bar is None or self.current_m15_bar["timestamp"] != m15_time:
            if self.current_m15_bar is not None:
                self.m15_bars.append(self.current_m15_bar)
                self._detect_pivots()
            # Start new M15 bar
            self.current_m15_bar = {
                "timestamp": m15_time,
                "open": m1_bar["open"],
                "high": m1_bar["high"],
                "low": m1_bar["low"],
                "close": m1_bar["close"],
                "volume": m1_bar.get("tick_volume", 0)
            }
        else:
            # Update current M15 bar
            self.current_m15_bar["high"] = max(self.current_m15_bar["high"], m1_bar["high"])
            self.current_m15_bar["low"] = min(self.current_m15_bar["low"], m1_bar["low"])
            self.current_m15_bar["close"] = m1_bar["close"]
            self.current_m15_bar["volume"] += m1_bar.get("tick_volume", 0)

    def _detect_pivots(self):
        n = len(self.m15_bars)
        req_bars = self.pivot_left + self.pivot_right + 1
        if n < req_bars:
            return

        idx = n - 1 - self.pivot_right
        candidate_high = self.m15_bars[idx]["high"]
        candidate_low = self.m15_bars[idx]["low"]

        is_high = True
        is_low = True

        for i in range(idx - self.pivot_left, idx + self.pivot_right + 1):
            if i == idx:
                continue
            if self.m15_bars[i]["high"] >= candidate_high:
                is_high = False
            if self.m15_bars[i]["low"] <= candidate_low:
                is_low = False

        if is_high and candidate_high not in self.swing_highs:
            self.swing_highs.append(candidate_high)
            if len(self.swing_highs) > 20:
                self.swing_highs.pop(0)

        if is_low and candidate_low not in self.swing_lows:
            self.swing_lows.append(candidate_low)
            if len(self.swing_lows) > 20:
                self.swing_lows.pop(0)

    def is_price_at_htf_supply_poi(self, price: float) -> bool:
        """Returns True if current price is within buffer of an M15 Swing High (Supply)"""
        for sh in self.swing_highs[-5:]:
            if abs(price - sh) <= self.zone_buffer or (price >= sh and price <= sh + self.zone_buffer * 2):
                return True
        return False

    def is_price_at_htf_demand_poi(self, price: float) -> bool:
        """Returns True if current price is within buffer of an M15 Swing Low (Demand)"""
        for sl in self.swing_lows[-5:]:
            if abs(price - sl) <= self.zone_buffer or (price <= sl and price >= sl - self.zone_buffer * 2):
                return True
        return False
