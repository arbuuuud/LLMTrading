"""
XAUUSD Institutional Daily Sniper Scalper.
Combines:
1. High-Conviction A+ Setup:
   - Fresh unmitigated RBR/DBD zones with strong displacement (Body >= 1.6x base, Volume >= 1.25x avg).
   - M15 EMA 50 trend alignment with directional slope confirmation.
   - Strict Golden Hours window (London Open 07:00-09:30 UTC & NY Open 12:30-15:00 UTC).
2. Dynamic Risk-Targeted Lot Sizing:
   - Sizing dynamically calculated so each trade risks exactly 0.5% ($50) or 0.25% ($25).
3. Daily Ratchet Governor (Kondisi 1, 2, 3, 4):
   - Ratchet profit locking at +1.0% when profit >= 1.5%.
   - 2-Strike loss circuit breaker (-1.0% daily hard stop).
   - 15-bar post-trade cooldown.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from engine.core.types import OrderDirection, ExitReason
from engine.core.strategy_base import BaseStrategy
from strategies.modules.context.trend_filter import TrendBiasFilter
from strategies.modules.triggers.candlestick_patterns import CandlestickPatternDetector, PatternType
from agents.risk_manager.daily_ratchet import DailyRatchetRiskGovernor, SizingApproval


class XAUUSDDailySniper(BaseStrategy):
    def __init__(
        self,
        risk_reward_ratio: float = 2.0,
        sl_buffer_dollars: float = 0.35,
        max_bars_hold: int = 25,
        base_risk_pct: float = 0.5,
        greed_risk_pct: float = 0.25
    ):
        super().__init__("XAUUSD_Daily_Sniper")
        self.risk_reward_ratio = risk_reward_ratio
        self.sl_buffer = sl_buffer_dollars
        self.max_bars_hold = max_bars_hold

        # Institutional components
        self.trend_filter = TrendBiasFilter(ema_period=50)
        self.candle_detector = CandlestickPatternDetector()
        self.risk_governor = DailyRatchetRiskGovernor(
            base_risk_pct=base_risk_pct,
            greed_risk_pct=greed_risk_pct,
            max_daily_loss_pct=1.0,
            max_daily_trades_under_target=3,
            cooldown_bars=15
        )

        # Fresh Supply & Demand zones storage
        self.active_zones: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = []
        self.bars_in_trade: int = 0

    def on_init(self):
        self.active_zones.clear()
        self.history.clear()
        self.bars_in_trade = 0

    def on_trade_closed(self, trade_record):
        self.risk_governor.on_trade_closed(trade_record.net_pnl)

    def on_bar(self, bar: Dict[str, Any]):
        dt: datetime = bar["timestamp"]
        price = bar["close"]
        spread = bar.get("mean_spread", 0.20)

        # 1. Update indicators and daily governor state
        self.trend_filter.update(bar)
        candle = self.candle_detector.update(bar)
        self.risk_governor.on_bar_tick(dt, self.engine.equity)

        self.history.append(bar)
        if len(self.history) > 60:
            self.history.pop(0)

        # 2. Manage active trade holding period
        if len(self.engine.positions) > 0:
            self.bars_in_trade += 1
            if self.bars_in_trade >= self.max_bars_hold:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
                self.bars_in_trade = 0
            return
        else:
            self.bars_in_trade = 0

        # 3. Detect Fresh High-Conviction Supply & Demand Zones
        self._detect_fresh_sd_zones()

        # 4. Golden Hours Session Filter (London 07:00-09:30 UTC & NY 12:30-15:00 UTC)
        t = dt.time()
        is_london_golden = (7, 0) <= (t.hour, t.minute) <= (9, 30)
        is_ny_golden = (12, 30) <= (t.hour, t.minute) <= (15, 0)
        if not (is_london_golden or is_ny_golden):
            return

        is_uptrend = self.trend_filter.is_bullish_trend(price)
        is_downtrend = self.trend_filter.is_bearish_trend(price)

        # 5. Evaluate Long Setup (A+ Sniper Buy)
        # Uptrend + Inside Fresh Unmitigated Demand Zone + Bullish Candle Rejection
        demand_zone = self._get_matching_demand_zone(price)
        if is_uptrend and demand_zone is not None:
            if candle in (PatternType.BULLISH_ENGULFING, PatternType.BULLISH_HAMMER):
                sl = round(bar["low"] - self.sl_buffer, 2)
                sl_dist = price - sl
                tp = round(price + (sl_dist * self.risk_reward_ratio), 2)

                # Request dynamic risk sizing and approval
                approval: SizingApproval = self.risk_governor.evaluate_entry(
                    entry_price=price,
                    stop_loss=sl,
                    current_spread=spread,
                    max_allowed_spread=0.22,
                    num_open_positions=len(self.engine.positions)
                )

                if approval.approved:
                    pos_id = self.engine.buy(
                        symbol="XAUUSD",
                        volume_lots=approval.lots,
                        stop_loss=sl,
                        take_profit=tp,
                        comment=f"Sniper_Buy_Risk{approval.risk_pct}%",
                        tag="Sniper_A+"
                    )
                    if pos_id:
                        demand_zone["mitigated"] = True

        # 6. Evaluate Short Setup (A+ Sniper Sell)
        # Downtrend + Inside Fresh Unmitigated Supply Zone + Bearish Candle Rejection
        supply_zone = self._get_matching_supply_zone(price)
        if is_downtrend and supply_zone is not None:
            if candle in (PatternType.BEARISH_ENGULFING, PatternType.SHOOTING_STAR):
                sl = round(bar["high"] + self.sl_buffer, 2)
                sl_dist = sl - price
                tp = round(price - (sl_dist * self.risk_reward_ratio), 2)

                approval: SizingApproval = self.risk_governor.evaluate_entry(
                    entry_price=price,
                    stop_loss=sl,
                    current_spread=spread,
                    max_allowed_spread=0.22,
                    num_open_positions=len(self.engine.positions)
                )

                if approval.approved:
                    pos_id = self.engine.sell(
                        symbol="XAUUSD",
                        volume_lots=approval.lots,
                        stop_loss=sl,
                        take_profit=tp,
                        comment=f"Sniper_Sell_Risk{approval.risk_pct}%",
                        tag="Sniper_A+"
                    )
                    if pos_id:
                        supply_zone["mitigated"] = True

    def _detect_fresh_sd_zones(self):
        n = len(self.history)
        if n < 6:
            return

        # Leg 2 is last bar, Leg 1 is 3 bars ago, Base in between
        leg2 = self.history[-1]
        base = self.history[-2]
        leg1 = self.history[-3]

        leg2_body = abs(leg2["close"] - leg2["open"])
        leg2_range = leg2["high"] - leg2["low"]
        base_body = abs(base["close"] - base["open"])

        if base_body <= 0.05 or leg2_range <= 0.20:
            return

        # Calculate average volume over last 20 bars
        vols = [b.get("tick_volume", 0) for b in self.history[-20:]]
        avg_vol = sum(vols) / len(vols) if vols else 1

        is_strong_body = (leg2_body / leg2_range) >= 0.65
        is_impulse = leg2_body >= base_body * 1.6
        is_vol_expansion = leg2.get("tick_volume", 0) >= avg_vol * 1.25

        if not (is_strong_body and is_impulse and is_vol_expansion):
            return

        # DBD Supply
        if leg2["close"] < leg2["open"] and leg1["close"] < leg1["open"]:
            self.active_zones.append({
                "type": "SUPPLY",
                "high": base["high"],
                "low": base["low"],
                "time": base["timestamp"],
                "mitigated": False
            })

        # RBR Demand
        elif leg2["close"] > leg2["open"] and leg1["close"] > leg1["open"]:
            self.active_zones.append({
                "type": "DEMAND",
                "high": base["high"],
                "low": base["low"],
                "time": base["timestamp"],
                "mitigated": False
            })

        if len(self.active_zones) > 20:
            self.active_zones.pop(0)

    def _get_matching_demand_zone(self, price: float) -> Optional[Dict[str, Any]]:
        for z in reversed(self.active_zones):
            if z["type"] == "DEMAND" and not z["mitigated"]:
                if price >= z["low"] - 0.15 and price <= z["high"] + 0.05:
                    return z
        return None

    def _get_matching_supply_zone(self, price: float) -> Optional[Dict[str, Any]]:
        for z in reversed(self.active_zones):
            if z["type"] == "SUPPLY" and not z["mitigated"]:
                if price <= z["high"] + 0.15 and price >= z["low"] - 0.05:
                    return z
        return None
