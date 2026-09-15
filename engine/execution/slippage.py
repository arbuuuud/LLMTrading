"""
Slippage models for realistic execution simulation in scalping.
Models execution delay, market impact, and adverse price slippage.
"""

import numpy as np
from engine.core.types import OrderDirection


class SlippageModel:
    """
    Base Slippage Model interface.
    """
    def apply_slippage(self, price: float, direction: OrderDirection, current_spread: float) -> float:
        raise NotImplementedError


class FixedSlippageModel(SlippageModel):
    """
    Fixed slippage in price units (e.g. 0.05 for $0.05 on Gold).
    """
    def __init__(self, slippage_price: float = 0.05):
        self.slippage_price = slippage_price

    def apply_slippage(self, price: float, direction: OrderDirection, current_spread: float) -> float:
        # Long orders slip upward (higher price), Short orders slip downward (lower price)
        if direction == OrderDirection.BUY:
            return round(price + self.slippage_price, 3)
        else:
            return round(price - self.slippage_price, 3)


class VolatilitySlippageModel(SlippageModel):
    """
    Dynamic institutional slippage model where slippage expands with spread spikes
    and market volatility, drawn from an exponential/half-normal distribution.
    """
    def __init__(self, base_slippage: float = 0.02, spread_multiplier: float = 0.2, seed: int = 42):
        self.base_slippage = base_slippage
        self.spread_multiplier = spread_multiplier
        self.rng = np.random.default_rng(seed)

    def apply_slippage(self, price: float, direction: OrderDirection, current_spread: float) -> float:
        # Scale slippage with current spread
        scale = self.base_slippage + (current_spread * self.spread_multiplier)
        random_slip = float(self.rng.exponential(scale=scale))
        
        # Long orders fill higher, Short orders fill lower
        if direction == OrderDirection.BUY:
            return round(price + random_slip, 3)
        else:
            return round(price - random_slip, 3)
