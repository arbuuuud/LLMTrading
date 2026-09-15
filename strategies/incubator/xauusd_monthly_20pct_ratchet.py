"""
XAUUSD 20% Monthly Target Ratchet Strategy.
Combines:
1. Dynamic Volatility-Scaled SL/TP:
   - Uses M15 ATR 14 to automatically expand stops during high-volatility regimes (e.g. 2026)
     and tighten during calm regimes (e.g. 2025).
2. Trend-Aligned Golden Hours Execution:
   - Evaluates M15 EMA 50 trend slope.
   - Executes during London Open (08:00 - 11:00 UTC) and NY Open (13:00 - 16:00 UTC).
3. Monthly Ratchet Governor:
   - Locks daily profit floor at +1.0%, +1.5%, +2.0%, +3.0%.
   - Reduces risk to 0.25% (House Money) during Greed Mode.
   - 2-Strike loss daily shutdown (-1.0%).
   - Monthly drawdown circuit breaker (-3.0%).
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from engine.core.types import OrderDirection, ExitReason
from engine.core.strategy_base import BaseStrategy
from strategies.modules.context.trend_filter import TrendBiasFilter
from strategies.modules.triggers.candlestick_patterns import CandlestickPatternDetector, PatternType
from agents.risk_manager.monthly_ratchet_governor import MonthlyRatchetGovernor, RatchetApproval


class XAUUSDMonthly20PctRatchet(BaseStrategy):
    def __init__(
        self,
        risk_reward_ratio: float = 2.5,
        atr_sl_multiplier: float = 1.2,
        base_risk_pct: float = 0.5,
        greed_risk_pct: float = 0.25,
        max_bars_hold: int = 45
    ):
        super().__init__("XAUUSD_Monthly_20Pct_Ratchet")
        self.risk_reward_ratio = risk_reward_ratio
        self.atr_sl_multiplier = atr_sl_multiplier
        self.max_bars_hold = max_bars_hold

        self.trend_filter = TrendBiasFilter(ema_period=50)
        self.candle_detector = CandlestickPatternDetector()
        self.governor = MonthlyRatchetGovernor(
            base_risk_pct=base_risk_pct,
            greed_risk_pct=greed_risk_pct,
            max_daily_loss_pct=1.0,
            monthly_loss_cap_pct=3.0,
            cooldown_bars=20
        )

        self.bars_in_trade: int = 0
        self.m15_tr_history: List[float] = []
        self.current_m15_time: Optional[datetime] = None
        self.current_atr: float = 2.0

    def on_init(self):
        self.bars_in_trade = 0
        self.m15_tr_history.clear()
        self.current_m15_time = None
        self.current_atr = 2.0

    def on_trade_closed(self, trade_record):
        self.governor.on_trade_closed(trade_record.net_pnl)

    def on_bar(self, bar: Dict[str, Any]):
        dt: datetime = bar["timestamp"]
        price = bar["close"]
        spread = bar.get("mean_spread", 0.20)

        # 1. Update M15 ATR dynamically
        self._update_m15_atr(bar)

        # 2. Update Trend & Governor state
        self.trend_filter.update(bar)
        candle = self.candle_detector.update(bar)
        self.governor.on_new_bar(dt, self.engine.equity)

        # 3. Manage active position (Time Exit)
        if len(self.engine.positions) > 0:
            self.bars_in_trade += 1
            if self.bars_in_trade >= self.max_bars_hold:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
                self.bars_in_trade = 0
            return
        else:
            self.bars_in_trade = 0

        # 4. Golden Hours Session Filter
        t = dt.time()
        is_london = (8, 0) <= (t.hour, t.minute) <= (11, 0)
        is_ny = (13, 0) <= (t.hour, t.minute) <= (16, 0)
        if not (is_london or is_ny):
            return

        # 5. High-Conviction Candle Filter
        body = abs(bar["close"] - bar["open"])
        rng = bar["high"] - bar["low"]
        if rng < 0.40 or (body / rng) < 0.60:
            return

        is_uptrend = self.trend_filter.is_bullish_trend(price)
        is_downtrend = self.trend_filter.is_bearish_trend(price)

        # Dynamic Stop Loss based on ATR
        sl_dist = round(max(1.80, self.current_atr * self.atr_sl_multiplier), 2)
        tp_dist = round(sl_dist * self.risk_reward_ratio, 2)

        # Buy Setup
        if is_uptrend and bar["close"] > bar["open"]:
            sl = round(price - sl_dist, 2)
            tp = round(price + tp_dist, 2)

            approval: RatchetApproval = self.governor.evaluate_entry(
                entry_price=price,
                stop_loss=sl,
                current_spread=spread,
                max_allowed_spread=0.25,
                num_open_positions=len(self.engine.positions)
            )

            if approval.approved:
                mode_str = "Greed" if approval.is_greed_mode else "Base"
                self.engine.buy(
                    symbol="XAUUSD",
                    volume_lots=approval.lots,
                    stop_loss=sl,
                    take_profit=tp,
                    comment=f"{mode_str}_Buy_{approval.risk_pct}%",
                    tag="Ratchet_Buy"
                )

        # Sell Setup
        elif is_downtrend and bar["close"] < bar["open"]:
            sl = round(price + sl_dist, 2)
            tp = round(price - tp_dist, 2)

            approval: RatchetApproval = self.governor.evaluate_entry(
                entry_price=price,
                stop_loss=sl,
                current_spread=spread,
                max_allowed_spread=0.25,
                num_open_positions=len(self.engine.positions)
            )

            if approval.approved:
                mode_str = "Greed" if approval.is_greed_mode else "Base"
                self.engine.sell(
                    symbol="XAUUSD",
                    volume_lots=approval.lots,
                    stop_loss=sl,
                    take_profit=tp,
                    comment=f"{mode_str}_Sell_{approval.risk_pct}%",
                    tag="Ratchet_Sell"
                )

    def _update_m15_atr(self, m1_bar: Dict[str, Any]):
        dt: datetime = m1_bar["timestamp"]
        m15_minute = (dt.minute // 15) * 15
        m15_time = dt.replace(minute=m15_minute, second=0, microsecond=0)

        if self.current_m15_time != m15_time:
            if self.current_m15_time is not None and hasattr(self, "m15_high"):
                tr = self.m15_high - self.m15_low
                self.m15_tr_history.append(tr)
                if len(self.m15_tr_history) > 60:
                    self.m15_tr_history.pop(0)

                if len(self.m15_tr_history) >= 14:
                    self.current_atr = sum(self.m15_tr_history[-14:]) / 14.0
                else:
                    self.current_atr = 2.5

            self.current_m15_time = m15_time
            self.m15_high = m1_bar["high"]
            self.m15_low = m1_bar["low"]
        else:
            if not hasattr(self, "m15_high"):
                self.m15_high = m1_bar["high"]
                self.m15_low = m1_bar["low"]
            else:
                self.m15_high = max(self.m15_high, m1_bar["high"])
                self.m15_low = min(self.m15_low, m1_bar["low"])
