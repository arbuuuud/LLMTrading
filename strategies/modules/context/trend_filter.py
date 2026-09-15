"""
Macro Trend & Session Bias Filter (Context Layer).
Tracks higher timeframe trend alignment (e.g. M15 / H1 EMA or Daily Open slope)
to prevent counter-trend fading during strong expansion regimes.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime


class TrendBiasFilter:
    def __init__(self, ema_period: int = 50):
        self.ema_period = ema_period
        self.multiplier = 2.0 / (ema_period + 1)
        self.current_ema: Optional[float] = None
        self.m15_closes: List[float] = []
        self.current_m15_time: Optional[datetime] = None

    def update(self, m1_bar: Dict[str, Any]):
        dt: datetime = m1_bar["timestamp"]
        m15_minute = (dt.minute // 15) * 15
        m15_time = dt.replace(minute=m15_minute, second=0, microsecond=0)

        if self.current_m15_time != m15_time:
            # New M15 bar completed
            self.current_m15_time = m15_time
            close = m1_bar["close"]
            self.m15_closes.append(close)
            if len(self.m15_closes) > self.ema_period * 2:
                self.m15_closes.pop(0)

            # Update EMA
            if self.current_ema is None:
                if len(self.m15_closes) >= 5:
                    self.current_ema = sum(self.m15_closes) / len(self.m15_closes)
            else:
                self.current_ema = (close - self.current_ema) * self.multiplier + self.current_ema

    def is_bullish_trend(self, current_price: float) -> bool:
        if self.current_ema is None or len(self.m15_closes) < 5:
            return False
        # Calculate slope over the last 3 M15 bars
        slope = self.m15_closes[-1] - self.m15_closes[-4] if len(self.m15_closes) >= 4 else 0.0
        # True uptrend: price is above EMA AND EMA is sloping upwards
        return (current_price >= self.current_ema) and (slope > 0.15)

    def is_bearish_trend(self, current_price: float) -> bool:
        if self.current_ema is None or len(self.m15_closes) < 5:
            return False
        slope = self.m15_closes[-1] - self.m15_closes[-4] if len(self.m15_closes) >= 4 else 0.0
        # True downtrend: price is below EMA AND EMA is sloping downwards
        return (current_price <= self.current_ema) and (slope < -0.15)
