"""
Market Regime and Intermarket Intelligence Agent.
Classifies macro and micro market states (Trending, Ranging, High Volatility, Session Open)
to dynamically activate or deactivate strategy families.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
import math
import numpy as np


class RegimeType(Enum):
    TRENDING_BULLISH = "TRENDING_BULLISH"
    TRENDING_BEARISH = "TRENDING_BEARISH"
    RANGING_CONSOLIDATION = "RANGING_CONSOLIDATION"
    HIGH_VOLATILITY_EXPANSION = "HIGH_VOLATILITY_EXPANSION"
    LOW_LIQUIDITY_CHOP = "LOW_LIQUIDITY_CHOP"


@dataclass
class MarketRegimeReport:
    regime: RegimeType
    realized_volatility: float
    atr: float
    hurst_proxy: float
    trend_strength: float  # -1.0 (Strong Bearish) to +1.0 (Strong Bullish)
    is_spread_normal: bool
    current_spread: float
    recommended_strategy_family: str  # "TREND_PULLBACK" or "LIQUIDITY_SWEEP" or "STAND_ASIDE"


class MarketRegimeDetector:
    def __init__(
        self,
        lookback_bars: int = 50,
        atr_period: int = 14,
        spread_max_threshold: float = 0.25
    ):
        self.lookback = lookback_bars
        self.atr_period = atr_period
        self.spread_threshold = spread_max_threshold
        self.bars: List[Dict[str, Any]] = []

    def update(self, bar: Dict[str, Any]) -> MarketRegimeReport:
        self.bars.append(bar)
        if len(self.bars) > self.lookback * 2:
            self.bars.pop(0)

        n = len(self.bars)
        price = bar["close"]
        spread = bar.get("mean_spread", 0.20)
        is_spread_ok = spread <= self.spread_threshold

        if n < self.atr_period + 5:
            # Cold start fallback
            return MarketRegimeReport(
                regime=RegimeType.RANGING_CONSOLIDATION,
                realized_volatility=0.0,
                atr=0.50,
                hurst_proxy=0.50,
                trend_strength=0.0,
                is_spread_normal=is_spread_ok,
                current_spread=spread,
                recommended_strategy_family="STAND_ASIDE"
            )

        # 1. Calculate Average True Range (ATR)
        tr_list = []
        for i in range(n - self.atr_period, n):
            h = self.bars[i]["high"]
            l = self.bars[i]["low"]
            pc = self.bars[i - 1]["close"]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            tr_list.append(tr)
        atr = sum(tr_list) / len(tr_list)

        # 2. Calculate Realized Volatility (Standard Deviation of M1 Log Returns)
        closes = np.array([b["close"] for b in self.bars[-self.lookback:]])
        log_returns = np.diff(np.log(closes))
        realized_vol = float(np.std(log_returns) * np.sqrt(1440))  # Annualized to daily scale

        # 3. Directional Trend Strength (Linear Regression Slope / Normalized)
        x = np.arange(len(closes))
        y = closes
        slope, _ = np.polyfit(x, y, 1)
        normalized_slope = (slope * len(closes)) / atr if atr > 0 else 0.0
        trend_strength = max(-1.0, min(1.0, normalized_slope / 3.0))

        # 4. Hurst Exponent Proxy (Rescaled Range R/S)
        # H > 0.55 indicates trending/persistent; H < 0.45 indicates mean-reverting
        mean_ret = np.mean(log_returns)
        dev = log_returns - mean_ret
        cum_dev = np.cumsum(dev)
        r = np.max(cum_dev) - np.min(cum_dev)
        s = np.std(log_returns)
        rs = r / s if s > 1e-8 else 1.0
        hurst_proxy = math.log(rs) / math.log(len(log_returns)) if len(log_returns) > 1 and rs > 0 else 0.50

        # 5. Classify Regime
        # Spread spike safety gate
        if not is_spread_ok:
            regime = RegimeType.LOW_LIQUIDITY_CHOP
            recommended = "STAND_ASIDE"
        elif atr > 1.80:
            regime = RegimeType.HIGH_VOLATILITY_EXPANSION
            recommended = "TREND_PULLBACK" if abs(trend_strength) > 0.3 else "STAND_ASIDE"
        elif hurst_proxy > 0.52 and trend_strength > 0.25:
            regime = RegimeType.TRENDING_BULLISH
            recommended = "TREND_PULLBACK"
        elif hurst_proxy > 0.52 and trend_strength < -0.25:
            regime = RegimeType.TRENDING_BEARISH
            recommended = "TREND_PULLBACK"
        elif hurst_proxy < 0.48:
            regime = RegimeType.RANGING_CONSOLIDATION
            recommended = "LIQUIDITY_SWEEP"
        else:
            regime = RegimeType.RANGING_CONSOLIDATION
            recommended = "LIQUIDITY_SWEEP"

        return MarketRegimeReport(
            regime=regime,
            realized_volatility=round(realized_vol, 4),
            atr=round(atr, 2),
            hurst_proxy=round(hurst_proxy, 3),
            trend_strength=round(trend_strength, 2),
            is_spread_normal=is_spread_ok,
            current_spread=round(spread, 3),
            recommended_strategy_family=recommended
        )
