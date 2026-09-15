"""
Market Structure Shift (MSS) & Change of Character (CHoCH) Detector on M1.
Tracks swing pivot highs and lows to confirm institutional momentum shifts.
"""

from typing import List, Dict, Any, Optional
from enum import Enum


class StructureEvent(Enum):
    BULLISH_CHOCH = "BULLISH_CHOCH"  # Broken Swing High to the upside
    BEARISH_CHOCH = "BEARISH_CHOCH"  # Broken Swing Low to the downside
    BULLISH_BOS = "BULLISH_BOS"      # Trend continuation breakout
    BEARISH_BOS = "BEARISH_BOS"


class MarketStructureDetector:
    def __init__(self, pivot_lookback: int = 3):
        self.pivot_lookback = pivot_lookback
        self.bars: List[Dict[str, Any]] = []
        
        self.recent_swing_high: Optional[float] = None
        self.recent_swing_low: Optional[float] = None
        self.trend_direction: int = 0  # 1 for bullish, -1 for bearish

    def update(self, bar: Dict[str, Any]) -> Optional[StructureEvent]:
        self.bars.append(bar)
        if len(self.bars) > 100:
            self.bars.pop(0)

        n = len(self.bars)
        req = self.pivot_lookback * 2 + 1
        if n < req:
            return None

        # Check pivot at index: -1 - pivot_lookback
        idx = n - 1 - self.pivot_lookback
        cand_high = self.bars[idx]["high"]
        cand_low = self.bars[idx]["low"]

        is_high = True
        is_low = True

        for i in range(idx - self.pivot_lookback, idx + self.pivot_lookback + 1):
            if i == idx:
                continue
            if self.bars[i]["high"] >= cand_high:
                is_high = False
            if self.bars[i]["low"] <= cand_low:
                is_low = False

        if is_high:
            self.recent_swing_high = cand_high
        if is_low:
            self.recent_swing_low = cand_low

        # Now check if current close breaks recent swing level
        c = bar["close"]
        event = None

        if self.recent_swing_high is not None and c > self.recent_swing_high:
            if self.trend_direction <= 0:
                event = StructureEvent.BULLISH_CHOCH
                self.trend_direction = 1
            else:
                event = StructureEvent.BULLISH_BOS
            self.recent_swing_high = None  # Consumed

        elif self.recent_swing_low is not None and c < self.recent_swing_low:
            if self.trend_direction >= 0:
                event = StructureEvent.BEARISH_CHOCH
                self.trend_direction = -1
            else:
                event = StructureEvent.BEARISH_BOS
            self.recent_swing_low = None  # Consumed

        return event
