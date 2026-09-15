"""
Base class for all trading strategies in LLMTrading.
Provides a standardized event lifecycle for both Vectorized and Event-driven simulations.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseStrategy(ABC):
    def __init__(self, name: str, params: Optional[Dict[str, Any]] = None):
        self.name = name
        self.params = params or {}
        self.engine = None

    def set_engine(self, engine: Any):
        self.engine = engine

    def on_init(self):
        """Called once before backtest starts."""
        pass

    def on_tick(self, timestamp: Any, bid: float, ask: float, spread: float, flags: int):
        """Called on every incoming tick."""
        pass

    def on_bar(self, bar: Dict[str, Any]):
        """Called on every completed bar (M1, M5, etc.)."""
        pass

    def on_trade_closed(self, trade: Any):
        """Callback when a position is closed."""
        pass

    def on_finish(self):
        """Called once after backtest finishes."""
        pass
