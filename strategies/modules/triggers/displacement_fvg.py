"""
Displacement and Fair Value Gap (FVG) Detector (Trigger Layer).
Identifies institutional impulse candles (Displacement) and imbalances (FVG)
created immediately after a liquidity sweep.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum


class FVGType(Enum):
    BEARISH_FVG = "BEARISH_FVG"  # Bar 0 Low > Bar 2 High
    BULLISH_FVG = "BULLISH_FVG"  # Bar 0 High < Bar 2 Low


@dataclass
class FVGSignal:
    fvg_type: FVGType
    top: float
    bottom: float
    mid: float
    size_dollars: float
    timestamp: Any


class DisplacementFVGDetector:
    def __init__(self, min_fvg_size_dollars: float = 0.20, min_body_ratio: float = 0.60):
        self.min_fvg_size = min_fvg_size_dollars
        self.min_body_ratio = min_body_ratio
        self.bars: List[Dict[str, Any]] = []

    def update(self, bar: Dict[str, Any]) -> Optional[FVGSignal]:
        self.bars.append(bar)
        if len(self.bars) > 10:
            self.bars.pop(0)

        if len(self.bars) < 3:
            return None

        # Check 3-candle sequence: [b0, b1, b2]
        # b1 is the displacement candle
        b0 = self.bars[-3]
        b1 = self.bars[-2]
        b2 = self.bars[-1]

        # Check Bearish FVG (Displacement downwards)
        # b0 Low must be strictly higher than b2 High
        if b0["low"] > b2["high"]:
            gap_size = b0["low"] - b2["high"]
            # b1 must be a bearish candle with strong body
            b1_range = b1["high"] - b1["low"]
            b1_body = b1["open"] - b1["close"]
            if gap_size >= self.min_fvg_size and b1_range > 0 and (b1_body / b1_range) >= self.min_body_ratio:
                return FVGSignal(
                    fvg_type=FVGType.BEARISH_FVG,
                    top=b0["low"],
                    bottom=b2["high"],
                    mid=(b0["low"] + b2["high"]) / 2.0,
                    size_dollars=round(gap_size, 2),
                    timestamp=b1["timestamp"]
                )

        # Check Bullish FVG (Displacement upwards)
        # b2 Low must be strictly higher than b0 High
        elif b2["low"] > b0["high"]:
            gap_size = b2["low"] - b0["high"]
            b1_range = b1["high"] - b1["low"]
            b1_body = b1["close"] - b1["open"]
            if gap_size >= self.min_fvg_size and b1_range > 0 and (b1_body / b1_range) >= self.min_body_ratio:
                return FVGSignal(
                    fvg_type=FVGType.BULLISH_FVG,
                    top=b2["low"],
                    bottom=b0["high"],
                    mid=(b2["low"] + b0["high"]) / 2.0,
                    size_dollars=round(gap_size, 2),
                    timestamp=b1["timestamp"]
                )

        return None
