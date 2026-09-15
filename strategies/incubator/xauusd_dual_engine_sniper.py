"""
XAUUSD Institutional Dual-Engine Scalper with Intermarket Session SMT Confluence.
Combines:
1. Engine A (Trend Pullback Sniper):
   - Active when Regime is TRENDING with EMA 50 slope alignment.
   - Trades fresh RBR Demand in uptrends, fresh DBD Supply in downtrends.
2. Engine B (SMT-Confirmed Range Liquidity Sweep):
   - Active during London / NY sessions when Gold sweeps Asia High/Low.
   - STRICT SMT FILTER: Only takes the fade if Silver (XAGUSD) FAILS to confirm the breakout!
   - Prevents suicidal counter-trend fades during real trend expansions.
3. Daily Ratchet Risk Governor:
   - Dynamic lot sizing (0.5% standard, 0.25% in Greed Mode).
   - Ratchet profit locking at +1.0% when profit reaches >= +1.5%.
   - 2-Strike loss circuit breaker (-1.0% max daily stop).
   - 15-minute post-trade cooldown.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, time

from engine.core.types import OrderDirection, ExitReason
from engine.core.strategy_base import BaseStrategy
from strategies.modules.context.trend_filter import TrendBiasFilter
from strategies.modules.context.session_tracker import SessionTracker
from strategies.modules.triggers.candlestick_patterns import CandlestickPatternDetector, PatternType
from agents.market_regime.detector import MarketRegimeDetector, MarketRegimeReport
from agents.risk_manager.daily_ratchet import DailyRatchetRiskGovernor, SizingApproval


class XAUUSDDualEngineSniper(BaseStrategy):
    def __init__(
        self,
        risk_reward_ratio: float = 2.0,
        sl_buffer_dollars: float = 0.35,
        max_bars_hold: int = 25,
        base_risk_pct: float = 0.5,
        greed_risk_pct: float = 0.25,
        min_sweep_dollars: float = 0.20
    ):
        super().__init__("XAUUSD_Dual_Engine_Sniper")
        self.risk_reward_ratio = risk_reward_ratio
        self.sl_buffer = sl_buffer_dollars
        self.max_bars_hold = max_bars_hold
        self.min_sweep_dollars = min_sweep_dollars

        # Context & Regime Detectors
        self.session_tracker = SessionTracker()
        self.trend_filter = TrendBiasFilter(ema_period=50)
        self.regime_detector = MarketRegimeDetector(lookback_bars=40, atr_period=14)
        self.candle_detector = CandlestickPatternDetector()

        # Risk Governor
        self.risk_governor = DailyRatchetRiskGovernor(
            base_risk_pct=base_risk_pct,
            greed_risk_pct=greed_risk_pct,
            max_daily_loss_pct=1.0,
            max_daily_trades_under_target=3,
            cooldown_bars=15
        )

        # Active state tracking
        self.active_zones: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = []
        self.bars_in_trade: int = 0

        # Silver Session Tracker for SMT Divergence
        self.silver_current_date = None
        self.silver_asia_high: Optional[float] = None
        self.silver_asia_low: Optional[float] = None
        self.silver_trade_high: float = 0.0
        self.silver_trade_low: float = 9999.0

    def on_init(self):
        self.active_zones.clear()
        self.history.clear()
        self.bars_in_trade = 0
        self.silver_current_date = None
        self.silver_asia_high = None
        self.silver_asia_low = None
        self.silver_trade_high = 0.0
        self.silver_trade_low = 9999.0

    def on_trade_closed(self, trade_record):
        self.risk_governor.on_trade_closed(trade_record.net_pnl)

    def on_bar(self, bar: Dict[str, Any]):
        # Default fallback to single asset
        self.on_bar_intermarket(bar, None, None)

    def on_bar_intermarket(
        self,
        gold_bar: Dict[str, Any],
        silver_bar: Optional[Dict[str, Any]],
        dxy_bar: Optional[Dict[str, Any]]
    ):
        dt: datetime = gold_bar["timestamp"]
        price = gold_bar["close"]
        spread = gold_bar.get("gold_spread", gold_bar.get("mean_spread", 0.20))

        # 1. Update Context Layers & Risk Governor
        self.session_tracker.update(gold_bar)
        self.trend_filter.update(gold_bar)
        regime: MarketRegimeReport = self.regime_detector.update(gold_bar)
        candle = self.candle_detector.update(gold_bar)
        self.risk_governor.on_bar_tick(dt, self.engine.equity)

        # 2. Update Silver Session Tracker
        if silver_bar is not None:
            self._update_silver_session(silver_bar)

        self.history.append(gold_bar)
        if len(self.history) > 60:
            self.history.pop(0)

        # 3. Manage Active Position (Time Exit)
        if len(self.engine.positions) > 0:
            self.bars_in_trade += 1
            if self.bars_in_trade >= self.max_bars_hold:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
                self.bars_in_trade = 0
            return
        else:
            self.bars_in_trade = 0

        # 4. Detect Fresh Supply & Demand Zones
        self._detect_fresh_sd_zones()

        # 5. Golden Hours Session Filter
        t = dt.time()
        is_london = (7, 0) <= (t.hour, t.minute) <= (11, 0)
        is_ny = (12, 30) <= (t.hour, t.minute) <= (16, 0)
        if not (is_london or is_ny):
            return

        if regime.recommended_strategy_family == "STAND_ASIDE":
            return

        # =========================================================================
        # ENGINE A: TREND PULLBACK SNIPER (When market is TRENDING)
        # =========================================================================
        if regime.recommended_strategy_family == "TREND_PULLBACK":
            is_uptrend = self.trend_filter.is_bullish_trend(price)
            is_downtrend = self.trend_filter.is_bearish_trend(price)

            # Trend Buy: Uptrend + Fresh Demand (RBR) + Bullish Candle Rejection
            demand_zone = self._get_matching_demand_zone(price)
            if is_uptrend and demand_zone is not None:
                if candle in (PatternType.BULLISH_ENGULFING, PatternType.BULLISH_HAMMER):
                    sl = round(gold_bar["low"] - self.sl_buffer, 2)
                    sl_dist = price - sl
                    tp = round(price + (sl_dist * self.risk_reward_ratio), 2)

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
                            comment="Trend_Buy",
                            tag="Trend_Engine"
                        )
                        if pos_id:
                            demand_zone["mitigated"] = True
                            return

            # Trend Sell: Downtrend + Fresh Supply (DBD) + Bearish Candle Rejection
            supply_zone = self._get_matching_supply_zone(price)
            if is_downtrend and supply_zone is not None:
                if candle in (PatternType.BEARISH_ENGULFING, PatternType.SHOOTING_STAR):
                    sl = round(gold_bar["high"] + self.sl_buffer, 2)
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
                            comment="Trend_Sell",
                            tag="Trend_Engine"
                        )
                        if pos_id:
                            supply_zone["mitigated"] = True
                            return

        # =========================================================================
        # ENGINE B: SMT-CONFIRMED RANGE LIQUIDITY SWEEP
        # =========================================================================
        elif self.session_tracker.asia_complete and self.session_tracker.asia_high is not None:
            # Check Bearish SMT Sweep:
            # 1. Gold swept Asia High by >= $0.20
            # 2. Silver FAILED to break its Asia High (SMT Divergence Confirmed!)
            # 3. Bearish Candlestick Rejection
            gold_swept_high = (gold_bar["high"] > self.session_tracker.asia_high + self.min_sweep_dollars)
            silver_failed_high = (self.silver_asia_high is not None and self.silver_trade_high <= self.silver_asia_high + 0.015)

            if gold_swept_high and silver_failed_high:
                if candle in (PatternType.BEARISH_ENGULFING, PatternType.SHOOTING_STAR):
                    sl = round(gold_bar["high"] + self.sl_buffer, 2)
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
                        self.engine.sell(
                            symbol="XAUUSD",
                            volume_lots=approval.lots,
                            stop_loss=sl,
                            take_profit=tp,
                            comment="SMT_Bearish_Fade",
                            tag="SMT_Range_Engine"
                        )
                        return

            # Check Bullish SMT Sweep:
            # 1. Gold swept Asia Low by >= $0.20
            # 2. Silver FAILED to break its Asia Low (SMT Divergence Confirmed!)
            # 3. Bullish Candlestick Rejection
            gold_swept_low = (gold_bar["low"] < self.session_tracker.asia_low - self.min_sweep_dollars)
            silver_failed_low = (self.silver_asia_low is not None and self.silver_trade_low >= self.silver_asia_low - 0.015)

            if gold_swept_low and silver_failed_low:
                if candle in (PatternType.BULLISH_ENGULFING, PatternType.BULLISH_HAMMER):
                    sl = round(gold_bar["low"] - self.sl_buffer, 2)
                    sl_dist = price - sl
                    tp = round(price + (sl_dist * self.risk_reward_ratio), 2)

                    approval: SizingApproval = self.risk_governor.evaluate_entry(
                        entry_price=price,
                        stop_loss=sl,
                        current_spread=spread,
                        max_allowed_spread=0.22,
                        num_open_positions=len(self.engine.positions)
                    )
                    if approval.approved:
                        self.engine.buy(
                            symbol="XAUUSD",
                            volume_lots=approval.lots,
                            stop_loss=sl,
                            take_profit=tp,
                            comment="SMT_Bullish_Fade",
                            tag="SMT_Range_Engine"
                        )
                        return

    def _update_silver_session(self, silver_bar: Dict[str, Any]):
        dt: datetime = silver_bar["timestamp"]
        d = dt.date()
        t = dt.time()
        h = silver_bar["high"]
        l = silver_bar["low"]

        if self.silver_current_date != d:
            self.silver_current_date = d
            self.silver_asia_high = None
            self.silver_asia_low = None
            self.silver_trade_high = 0.0
            self.silver_trade_low = 9999.0

        # Asia session: 00:00 - 06:00
        if time(0, 0) <= t < time(6, 0):
            if self.silver_asia_high is None or h > self.silver_asia_high:
                self.silver_asia_high = h
            if self.silver_asia_low is None or l < self.silver_asia_low:
                self.silver_asia_low = l
        elif t >= time(7, 0):
            self.silver_trade_high = max(self.silver_trade_high, h)
            self.silver_trade_low = min(self.silver_trade_low, l)

    def _detect_fresh_sd_zones(self):
        n = len(self.history)
        if n < 6:
            return

        leg2 = self.history[-1]
        base = self.history[-2]
        leg1 = self.history[-3]

        leg2_body = abs(leg2["close"] - leg2["open"])
        leg2_range = leg2["high"] - leg2["low"]
        base_body = abs(base["close"] - base["open"])

        if base_body <= 0.05 or leg2_range <= 0.20:
            return

        vols = [b.get("tick_volume", 0) for b in self.history[-20:]]
        avg_vol = sum(vols) / len(vols) if vols else 1

        is_strong_body = (leg2_body / leg2_range) >= 0.65
        is_impulse = leg2_body >= base_body * 1.6
        is_vol_expansion = leg2.get("tick_volume", 0) >= avg_vol * 1.25

        if not (is_strong_body and is_impulse and is_vol_expansion):
            return

        if leg2["close"] < leg2["open"] and leg1["close"] < leg1["open"]:
            self.active_zones.append({
                "type": "SUPPLY",
                "high": base["high"],
                "low": base["low"],
                "time": base["timestamp"],
                "mitigated": False
            })
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
