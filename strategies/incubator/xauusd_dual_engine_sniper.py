"""
XAUUSD Institutional Dual-Engine Scalper.
Orchestrates two complementary alpha engines based on real-time Market Regime:
1. Engine A (Trend Pullback Sniper):
   - Active when Regime is TRENDING (Bullish or Bearish).
   - Trades fresh RBR Demand pullbacks in uptrend, and DBD Supply pullbacks in downtrend.
2. Engine B (Range Liquidity Sweep Scout):
   - Active when Regime is RANGING / CONSOLIDATION.
   - Fades false breakouts (wick sweeps) of Asia High (BSL) or Asia Low (SSL) back to range mean.
3. Unified Risk Governor:
   - Dynamic lot sizing (0.5% standard, 0.25% in Greed Mode).
   - Ratchet profit locking at +1.0% when profit reaches >= 1.5%.
   - 2-Strike loss circuit breaker (-1.0% max daily stop).
   - 15-minute post-trade cooldown.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from engine.core.types import OrderDirection, ExitReason
from engine.core.strategy_base import BaseStrategy
from strategies.modules.context.trend_filter import TrendBiasFilter
from strategies.modules.context.session_tracker import SessionTracker
from strategies.modules.setups.liquidity_sweep import LiquiditySweepDetector, SweepType, SweepSignal
from strategies.modules.triggers.candlestick_patterns import CandlestickPatternDetector, PatternType
from agents.market_regime.detector import MarketRegimeDetector, RegimeType, MarketRegimeReport
from agents.risk_manager.daily_ratchet import DailyRatchetRiskGovernor, SizingApproval


class XAUUSDDualEngineSniper(BaseStrategy):
    def __init__(
        self,
        risk_reward_ratio: float = 2.0,
        sl_buffer_dollars: float = 0.35,
        max_bars_hold: int = 25,
        base_risk_pct: float = 0.5,
        greed_risk_pct: float = 0.25,
        min_sweep_dollars: float = 0.15,
        max_sweep_dollars: float = 3.00
    ):
        super().__init__("XAUUSD_Dual_Engine_Sniper")
        self.risk_reward_ratio = risk_reward_ratio
        self.sl_buffer = sl_buffer_dollars
        self.max_bars_hold = max_bars_hold

        # Context & Regime Detectors
        self.session_tracker = SessionTracker()
        self.trend_filter = TrendBiasFilter(ema_period=50)
        self.regime_detector = MarketRegimeDetector(lookback_bars=40, atr_period=14)
        self.candle_detector = CandlestickPatternDetector()
        self.sweep_detector = LiquiditySweepDetector(
            min_sweep_dollars=min_sweep_dollars,
            max_sweep_dollars=max_sweep_dollars,
            require_close_inside=True
        )

        # Risk & Capital Protection Governor
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
        self.pending_sweep: Optional[SweepSignal] = None
        self.sweep_expiry_bars: int = 0

    def on_init(self):
        self.active_zones.clear()
        self.history.clear()
        self.bars_in_trade = 0
        self.pending_sweep = None
        self.sweep_expiry_bars = 0

    def on_trade_closed(self, trade_record):
        self.risk_governor.on_trade_closed(trade_record.net_pnl)

    def on_bar(self, bar: Dict[str, Any]):
        dt: datetime = bar["timestamp"]
        price = bar["close"]
        spread = bar.get("mean_spread", 0.20)

        # 1. Update Context Layers & Risk Governor
        self.session_tracker.update(bar)
        self.trend_filter.update(bar)
        regime: MarketRegimeReport = self.regime_detector.update(bar)
        candle = self.candle_detector.update(bar)
        self.risk_governor.on_bar_tick(dt, self.engine.equity)

        self.history.append(bar)
        if len(self.history) > 60:
            self.history.pop(0)

        # 2. Manage Active Position (Time Exit)
        if len(self.engine.positions) > 0:
            self.bars_in_trade += 1
            if self.bars_in_trade >= self.max_bars_hold:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
                self.bars_in_trade = 0
            return
        else:
            self.bars_in_trade = 0

        # 3. Detect Fresh Supply & Demand Zones
        self._detect_fresh_sd_zones()

        # 4. Check Liquidity Sweep of Asia Session
        if self.session_tracker.asia_complete:
            sweep = self.sweep_detector.check_sweep(
                bar,
                reference_high=self.session_tracker.asia_high,
                reference_low=self.session_tracker.asia_low
            )
            if sweep is not None:
                self.pending_sweep = sweep
                self.sweep_expiry_bars = 15
            elif self.pending_sweep is not None:
                self.sweep_expiry_bars -= 1
                if self.sweep_expiry_bars <= 0:
                    self.pending_sweep = None

        # 5. Golden Hours Session Filter
        # London Open: 07:00 - 11:00 UTC | NY Open: 12:30 - 16:00 UTC
        t = dt.time()
        is_london = (7, 0) <= (t.hour, t.minute) <= (11, 0)
        is_ny = (12, 30) <= (t.hour, t.minute) <= (16, 0)
        if not (is_london or is_ny):
            return

        # 6. DUAL ENGINE ROUTING
        # Stand aside if market is in low-liquidity chop or spread is abnormal
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
                    sl = round(bar["low"] - self.sl_buffer, 2)
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
                            comment="Trend_Sell",
                            tag="Trend_Engine"
                        )
                        if pos_id:
                            supply_zone["mitigated"] = True
                            return

        # =========================================================================
        # ENGINE B: RANGE LIQUIDITY SWEEP SCOUT (When market is RANGING)
        # =========================================================================
        elif regime.recommended_strategy_family == "LIQUIDITY_SWEEP" and self.pending_sweep is not None:
            # Bearish Fade on Buy-Side Liquidity Grab (High Swept)
            if self.pending_sweep.sweep_type == SweepType.BUY_SIDE_SWEEP:
                if candle in (PatternType.BEARISH_ENGULFING, PatternType.SHOOTING_STAR):
                    sl = round(self.pending_sweep.extremum_price + self.sl_buffer, 2)
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
                            comment="Range_BSL_Fade",
                            tag="Range_Engine"
                        )
                        if pos_id:
                            self.pending_sweep = None
                            return

            # Bullish Fade on Sell-Side Liquidity Grab (Low Swept)
            elif self.pending_sweep.sweep_type == SweepType.SELL_SIDE_SWEEP:
                if candle in (PatternType.BULLISH_ENGULFING, PatternType.BULLISH_HAMMER):
                    sl = round(self.pending_sweep.extremum_price - self.sl_buffer, 2)
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
                            comment="Range_SSL_Fade",
                            tag="Range_Engine"
                        )
                        if pos_id:
                            self.pending_sweep = None
                            return

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
