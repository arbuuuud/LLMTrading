"""
Liquidity Sweep Setup Detector (SMC / Institutional Liquidity Grab).
Detects false breakouts (wick sweeps) above Asia High (Buy-Side Liquidity Grab)
or below Asia Low (Sell-Side Liquidity Grab).
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum


class SweepType(Enum):
    BUY_SIDE_SWEEP = "BSL_SWEEP"   # Price swept above High (Bearish setup)
    SELL_SIDE_SWEEP = "SSL_SWEEP"  # Price swept below Low (Bullish setup)


@dataclass
class SweepSignal:
    sweep_type: SweepType
    sweep_level: float
    extremum_price: float
    sweep_depth_dollars: float
    bar_timestamp: Any


class LiquiditySweepDetector:
    def __init__(
        self,
        min_sweep_dollars: float = 0.15,  # Min sweep depth to be considered a grab
        max_sweep_dollars: float = 3.00,  # Max sweep depth (if exceeded, considered true breakout)
        require_close_inside: bool = True  # Candle must close back inside range
    ):
        self.min_sweep = min_sweep_dollars
        self.max_sweep = max_sweep_dollars
        self.require_close_inside = require_close_inside

    def check_sweep(
        self,
        bar: Dict[str, Any],
        reference_high: Optional[float],
        reference_low: Optional[float]
    ) -> Optional[SweepSignal]:
        if reference_high is None or reference_low is None:
            return None

        high = bar["high"]
        low = bar["low"]
        close = bar["close"]

        # Check BSL Sweep (High > reference_high)
        if high > reference_high:
            depth = high - reference_high
            if self.min_sweep <= depth <= self.max_sweep:
                if not self.require_close_inside or close <= reference_high + 0.10:
                    return SweepSignal(
                        sweep_type=SweepType.BUY_SIDE_SWEEP,
                        sweep_level=reference_high,
                        extremum_price=high,
                        sweep_depth_dollars=round(depth, 2),
                        bar_timestamp=bar["timestamp"]
                    )

        # Check SSL Sweep (Low < reference_low)
        if low < reference_low:
            depth = reference_low - low
            if self.min_sweep <= depth <= self.max_sweep:
                if not self.require_close_inside or close >= reference_low - 0.10:
                    return SweepSignal(
                        sweep_type=SweepType.SELL_SIDE_SWEEP,
                        sweep_level=reference_low,
                        extremum_price=low,
                        sweep_depth_dollars=round(depth, 2),
                        bar_timestamp=bar["timestamp"]
                    )

        return None
