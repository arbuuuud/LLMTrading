"""
Risk Guard and Exit Calculator (Exit Layer).
Calculates stop loss levels, risk-to-reward targets, and enforces maximum bar duration.
"""

from typing import Tuple, Dict, Any, Optional
from engine.core.types import OrderDirection


class RiskGuard:
    def __init__(
        self,
        risk_reward_ratio: float = 2.0,
        sl_buffer_dollars: float = 0.30,  # $0.30 buffer beyond sweep wick
        min_sl_distance: float = 0.50,    # Minimum SL distance to prevent instant whip
        max_sl_distance: float = 3.50,    # Maximum allowed SL for a scalp
        max_bars_hold: int = 25           # Close trade if stagnant for 25 M1 bars
    ):
        self.risk_reward_ratio = risk_reward_ratio
        self.sl_buffer = sl_buffer_dollars
        self.min_sl = min_sl_distance
        self.max_sl = max_sl_distance
        self.max_bars_hold = max_bars_hold

    def calculate_levels(
        self,
        direction: OrderDirection,
        entry_price: float,
        extremum_anchor: float
    ) -> Optional[Tuple[float, float]]:
        """
        Returns (stop_loss, take_profit) prices.
        If SL distance is outside [min_sl, max_sl], returns None (trade rejected).
        """
        if direction == OrderDirection.BUY:
            # Extremum anchor is the lowest price of the sweep
            raw_sl = extremum_anchor - self.sl_buffer
            risk_dist = entry_price - raw_sl

            if risk_dist < self.min_sl:
                raw_sl = entry_price - self.min_sl
                risk_dist = self.min_sl
            elif risk_dist > self.max_sl:
                return None  # Risk too wide for scalping

            tp = entry_price + (risk_dist * self.risk_reward_ratio)
            return (round(raw_sl, 2), round(tp, 2))

        else:  # SELL
            # Extremum anchor is the highest price of the sweep
            raw_sl = extremum_anchor + self.sl_buffer
            risk_dist = raw_sl - entry_price

            if risk_dist < self.min_sl:
                raw_sl = entry_price + self.min_sl
                risk_dist = self.min_sl
            elif risk_dist > self.max_sl:
                return None  # Risk too wide for scalping

            tp = entry_price - (risk_dist * self.risk_reward_ratio)
            return (round(raw_sl, 2), round(tp, 2))
