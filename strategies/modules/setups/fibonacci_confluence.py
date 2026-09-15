"""
Fibonacci Retracement & Extension Confluence Engine.
Based on Elliott Wave & ICT Optimal Trade Entry (OTE) Principles:
1. Fibonacci Retracement Levels:
   - 0.500: Equilibrium (Discount / Premium Divider)
   - 0.618: The Golden Ratio
   - 0.705: Sweet Spot (Midpoint of Golden Pocket)
   - 0.786: Deep Retracement / ICT OTE (Square root of 0.618)
   - 0.886: Extreme Harmonic Retracement
2. Fibonacci Extension Targets (Take Profit):
   - 1.000: Measured Move (AB = CD)
   - 1.272: Wave 5 / Reversal Target (Square root of 1.618)
   - 1.618: Golden Wave 3 Expansion (True Institutional Target)
   - 2.000: Extended Wave 3
"""

from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass


@dataclass
class FiboSetup:
    direction: str       # "BULLISH" or "BEARISH"
    swing_origin: float  # Low for bull, High for bear
    swing_extreme: float # High for bull, Low for bear
    range_dollars: float
    # Retracement levels
    eq_500: float
    fibo_618: float
    ote_705: float
    fibo_786: float
    fibo_886: float
    # Extension targets
    ext_1272: float
    ext_1618: float
    ext_2000: float


class FibonacciCalculator:
    @staticmethod
    def compute_bullish_fibo(swing_low: float, swing_high: float) -> Optional[FiboSetup]:
        rng = swing_high - swing_low
        if rng < 1.0:
            return None
        return FiboSetup(
            direction="BULLISH",
            swing_origin=swing_low,
            swing_extreme=swing_high,
            range_dollars=rng,
            eq_500=round(swing_high - 0.500 * rng, 2),
            fibo_618=round(swing_high - 0.618 * rng, 2),
            ote_705=round(swing_high - 0.705 * rng, 2),
            fibo_786=round(swing_high - 0.786 * rng, 2),
            fibo_886=round(swing_high - 0.886 * rng, 2),
            ext_1272=round(swing_low + 1.272 * rng, 2),
            ext_1618=round(swing_low + 1.618 * rng, 2),
            ext_2000=round(swing_low + 2.000 * rng, 2),
        )

    @staticmethod
    def compute_bearish_fibo(swing_high: float, swing_low: float) -> Optional[FiboSetup]:
        rng = swing_high - swing_low
        if rng < 1.0:
            return None
        return FiboSetup(
            direction="BEARISH",
            swing_origin=swing_high,
            swing_extreme=swing_low,
            range_dollars=rng,
            eq_500=round(swing_low + 0.500 * rng, 2),
            fibo_618=round(swing_low + 0.618 * rng, 2),
            ote_705=round(swing_low + 0.705 * rng, 2),
            fibo_786=round(swing_low + 0.786 * rng, 2),
            fibo_886=round(swing_low + 0.886 * rng, 2),
            ext_1272=round(swing_high - 1.272 * rng, 2),
            ext_1618=round(swing_high - 1.618 * rng, 2),
            ext_2000=round(swing_high - 2.000 * rng, 2),
        )

    @staticmethod
    def is_in_golden_pocket(price: float, fibo: FiboSetup, buffer: float = 0.30) -> bool:
        """
        Returns True if price is inside the 61.8% - 78.6% Golden Pocket / OTE zone.
        """
        if fibo.direction == "BULLISH":
            # For bullish, 61.8% is higher, 78.6% is lower
            top_bound = fibo.fibo_618 + buffer
            bot_bound = fibo.fibo_786 - buffer
            return bot_bound <= price <= top_bound
        else:
            # For bearish, 61.8% is lower, 78.6% is higher
            bot_bound = fibo.fibo_618 - buffer
            top_bound = fibo.fibo_786 + buffer
            return bot_bound <= price <= top_bound
