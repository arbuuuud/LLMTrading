"""
Candlestick Pattern Detector (Trigger Layer).
Detects Bullish/Bearish Engulfing, Hammer / Shooting Star (Pinbar Rejection),
and Doji consolidation triggers.
"""

from typing import Dict, Any, Optional
from enum import Enum


class PatternType(Enum):
    BULLISH_ENGULFING = "BULLISH_ENGULFING"
    BEARISH_ENGULFING = "BEARISH_ENGULFING"
    BULLISH_HAMMER = "BULLISH_HAMMER"        # Long lower wick rejection
    SHOOTING_STAR = "SHOOTING_STAR"          # Long upper wick rejection
    DOJI = "DOJI"


class CandlestickPatternDetector:
    def __init__(self, min_wick_ratio: float = 0.55, max_body_ratio_for_pinbar: float = 0.35):
        self.min_wick_ratio = min_wick_ratio
        self.max_body_ratio_for_pinbar = max_body_ratio_for_pinbar
        self.prev_bar: Optional[Dict[str, Any]] = None

    def update(self, current_bar: Dict[str, Any]) -> Optional[PatternType]:
        pattern = None
        
        o = current_bar["open"]
        h = current_bar["high"]
        l = current_bar["low"]
        c = current_bar["close"]
        bar_range = h - l

        if bar_range < 0.10:  # Negligible price movement
            self.prev_bar = current_bar
            return None

        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l

        # 1. Shooting Star / Bearish Pinbar (Upper wick rejection)
        if upper_wick / bar_range >= self.min_wick_ratio and body / bar_range <= self.max_body_ratio_for_pinbar:
            pattern = PatternType.SHOOTING_STAR

        # 2. Bullish Hammer / Pinbar (Lower wick rejection)
        elif lower_wick / bar_range >= self.min_wick_ratio and body / bar_range <= self.max_body_ratio_for_pinbar:
            pattern = PatternType.BULLISH_HAMMER

        # 3. Engulfing Patterns (Requires prev_bar)
        elif self.prev_bar is not None:
            po = self.prev_bar["open"]
            pc = self.prev_bar["close"]
            prev_body = abs(pc - po)
            
            # Bearish Engulfing: prev was green, current is red & engulfs
            if pc > po and c < o:
                if o >= pc - 0.05 and c <= po + 0.05 and body > prev_body:
                    pattern = PatternType.BEARISH_ENGULFING

            # Bullish Engulfing: prev was red, current is green & engulfs
            elif pc < po and c > o:
                if o <= pc + 0.05 and c >= po - 0.05 and body > prev_body:
                    pattern = PatternType.BULLISH_ENGULFING

        self.prev_bar = current_bar
        return pattern
