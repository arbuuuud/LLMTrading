"""
XAUUSD Trend-Aligned Institutional Scalper.
Trades exclusively in the direction of the macro trend (M15 EMA bias):
- Uptrend: Buys on pullbacks to M1 Demand / RBR zones with Bullish Candlestick/FVG confirmation.
- Downtrend: Sells on pullbacks to M1 Supply / DBD zones with Bearish Candlestick/FVG confirmation.
Strictly avoids counter-trend fading during strong trend expansions.
"""

from typing import Dict, Any, Optional
from datetime import datetime

from engine.core.types import OrderDirection, ExitReason
from engine.core.strategy_base import BaseStrategy
from strategies.modules.context.trend_filter import TrendBiasFilter
from strategies.modules.context.session_tracker import SessionTracker
from strategies.modules.setups.supply_demand import SupplyDemandDetector
from strategies.modules.triggers.candlestick_patterns import CandlestickPatternDetector, PatternType
from strategies.modules.triggers.displacement_fvg import DisplacementFVGDetector, FVGType
from strategies.modules.exits.risk_guard import RiskGuard


class XAUUSDTrendPullbackScalper(BaseStrategy):
    def __init__(
        self,
        ema_period: int = 50,
        risk_reward_ratio: float = 1.5,
        sl_buffer_dollars: float = 0.35,
        max_bars_hold: int = 30,
        lot_size: float = 0.1,
        use_fvg: bool = True,
        use_candle: bool = True
    ):
        super().__init__("XAUUSD_Trend_Pullback_Scalper")
        self.trend_filter = TrendBiasFilter(ema_period=ema_period)
        self.session_tracker = SessionTracker()
        self.sd_detector = SupplyDemandDetector(max_base_bars=3, min_impulse_ratio=1.3)
        self.candle_detector = CandlestickPatternDetector()
        self.fvg_detector = DisplacementFVGDetector(min_fvg_size_dollars=0.15)
        self.risk_guard = RiskGuard(
            risk_reward_ratio=risk_reward_ratio,
            sl_buffer_dollars=sl_buffer_dollars,
            min_sl_distance=0.40,
            max_sl_distance=3.50,
            max_bars_hold=max_bars_hold
        )

        self.lot_size = lot_size
        self.use_fvg = use_fvg
        self.use_candle = use_candle
        self.max_bars_hold = max_bars_hold
        self.bars_in_trade = 0

    def on_init(self):
        self.bars_in_trade = 0

    def on_bar(self, bar: Dict[str, Any]):
        dt: datetime = bar["timestamp"]
        price = bar["close"]

        # Update indicators
        self.trend_filter.update(bar)
        self.session_tracker.update(bar)
        self.sd_detector.update(bar)
        candle = self.candle_detector.update(bar)
        fvg = self.fvg_detector.update(bar)

        # Handle active position
        if len(self.engine.positions) > 0:
            self.bars_in_trade += 1
            if self.bars_in_trade >= self.max_bars_hold:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
                self.bars_in_trade = 0
            return
        else:
            self.bars_in_trade = 0

        # Session filter: Prime hours only (London Open 07:00-09:30 UTC & NY Open 12:30-15:00 UTC)
        t = dt.time()
        is_prime_london = (7, 0) <= (t.hour, t.minute) <= (9, 30)
        is_prime_ny = (12, 30) <= (t.hour, t.minute) <= (15, 0)
        if not (is_prime_london or is_prime_ny):
            return

        # Spread filter: avoid trading if spread is above $0.22
        if bar.get("mean_spread", 0.20) > 0.22:
            return

        is_bullish = self.trend_filter.is_bullish_trend(price)
        is_bearish = self.trend_filter.is_bearish_trend(price)

        # 1. Bullish Setup: Uptrend + In Demand Zone (RBR) + Bullish Confirmation
        if is_bullish and self.sd_detector.is_price_in_demand_zone(price):
            candle_ok = not self.use_candle or (candle in (PatternType.BULLISH_ENGULFING, PatternType.BULLISH_HAMMER))
            fvg_ok = not self.use_fvg or (fvg is not None and fvg.fvg_type == FVGType.BULLISH_FVG)

            if candle_ok or fvg_ok:
                levels = self.risk_guard.calculate_levels(
                    OrderDirection.BUY,
                    entry_price=price,
                    extremum_anchor=bar["low"]
                )
                if levels:
                    sl, tp = levels
                    self.engine.buy(
                        symbol="XAUUSD",
                        volume_lots=self.lot_size,
                        stop_loss=sl,
                        take_profit=tp,
                        comment="Trend_Demand_Pullback",
                        tag="M1_Scalp"
                    )

        # 2. Bearish Setup: Downtrend + In Supply Zone (DBD) + Bearish Confirmation
        elif is_bearish and self.sd_detector.is_price_in_supply_zone(price):
            candle_ok = not self.use_candle or (candle in (PatternType.BEARISH_ENGULFING, PatternType.SHOOTING_STAR))
            fvg_ok = not self.use_fvg or (fvg is not None and fvg.fvg_type == FVGType.BEARISH_FVG)

            if candle_ok or fvg_ok:
                levels = self.risk_guard.calculate_levels(
                    OrderDirection.SELL,
                    entry_price=price,
                    extremum_anchor=bar["high"]
                )
                if levels:
                    sl, tp = levels
                    self.engine.sell(
                        symbol="XAUUSD",
                        volume_lots=self.lot_size,
                        stop_loss=sl,
                        take_profit=tp,
                        comment="Trend_Supply_Pullback",
                        tag="M1_Scalp"
                    )
