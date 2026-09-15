"""
Strategy 4: Hybrid Super-Alpha (Session Anchored VWAP + SMT Intermarket Confluence).
Combines:
1. Primary Trigger: Session Anchored VWAP +/- 1.8 Sigma Mean Reversion on XAUUSD.
2. Intermarket Confluence: SMT Non-Confirmation with Silver (XAGUSD):
   - Bearish Fade (Short): Gold stretches to >= +1.8 sigma, while Silver shows relative weakness
     (fails to confirm extreme overextension or is lagging below its own upper band).
   - Bullish Fade (Buy): Gold stretches to <= -1.8 sigma, while Silver shows relative strength
     (holds higher relative value, confirming a bear trap).
3. Monthly Ratchet Risk Governor:
   - Dynamic lot sizing (0.5% base, 0.25% in Greed Mode).
   - Multi-tiered profit locking (Floor +1.0% at +1.5%, Floor +1.5% at +2.0%, etc.).
   - 2-Strike loss daily shutdown (-1.0%).
   - Monthly drawdown circuit breaker (-3.0% cap).
"""

from typing import Dict, Any, Optional
from datetime import datetime, time, date
import math

from engine.core.types import OrderDirection, ExitReason
from engine.core.strategy_base import BaseStrategy
from strategies.modules.triggers.candlestick_patterns import CandlestickPatternDetector
from agents.risk_manager.monthly_ratchet_governor import MonthlyRatchetGovernor, RatchetApproval


class HybridVWAPSMTStrategy(BaseStrategy):
    def __init__(
        self,
        gold_band_mult: float = 1.8,
        silver_band_mult: float = 1.5,
        sl_buffer_dollars: float = 0.40,
        risk_reward_ratio: float = 2.0,
        base_risk_pct: float = 0.5,
        greed_risk_pct: float = 0.25,
        max_bars_hold: int = 60,
        require_smt_confluence: bool = True
    ):
        super().__init__("Hybrid_VWAP_SMT_SuperAlpha")
        self.gold_band_mult = gold_band_mult
        self.silver_band_mult = silver_band_mult
        self.sl_buffer = sl_buffer_dollars
        self.risk_reward_ratio = risk_reward_ratio
        self.max_bars_hold = max_bars_hold
        self.require_smt = require_smt_confluence

        self.candle_detector = CandlestickPatternDetector()
        self.governor = MonthlyRatchetGovernor(
            base_risk_pct=base_risk_pct,
            greed_risk_pct=greed_risk_pct,
            max_daily_loss_pct=1.0,
            monthly_loss_cap_pct=3.0,
            cooldown_bars=20
        )

        # Gold VWAP Accumulators
        self.current_date: Optional[date] = None
        self.gold_cum_vol: float = 0.0
        self.gold_cum_pv: float = 0.0
        self.gold_cum_p2v: float = 0.0
        self.gold_vwap: float = 0.0
        self.gold_upper: float = 0.0
        self.gold_lower: float = 0.0

        # Silver VWAP Accumulators
        self.silver_cum_vol: float = 0.0
        self.silver_cum_pv: float = 0.0
        self.silver_cum_p2v: float = 0.0
        self.silver_vwap: float = 0.0
        self.silver_upper: float = 0.0
        self.silver_lower: float = 0.0

        self.bars_in_trade: int = 0
        self.traded_today_count: int = 0

    def on_init(self):
        self.current_date = None
        self.gold_cum_vol = 0.0
        self.gold_cum_pv = 0.0
        self.gold_cum_p2v = 0.0
        self.gold_vwap = 0.0
        self.gold_upper = 0.0
        self.gold_lower = 0.0

        self.silver_cum_vol = 0.0
        self.silver_cum_pv = 0.0
        self.silver_cum_p2v = 0.0
        self.silver_vwap = 0.0
        self.silver_upper = 0.0
        self.silver_lower = 0.0

        self.bars_in_trade = 0
        self.traded_today_count = 0

    def on_trade_closed(self, trade_record):
        self.governor.on_trade_closed(trade_record.net_pnl)

    def on_bar(self, bar: Dict[str, Any]):
        self.on_bar_intermarket(bar, None, None)

    def on_bar_intermarket(
        self,
        gold_bar: Dict[str, Any],
        silver_bar: Optional[Dict[str, Any]],
        dxy_bar: Optional[Dict[str, Any]]
    ):
        dt: datetime = gold_bar["timestamp"]
        d = dt.date()
        t = dt.time()

        gh = gold_bar["high"]
        gl = gold_bar["low"]
        gc = gold_bar["close"]
        go = gold_bar["open"]
        g_vol = max(1.0, float(gold_bar.get("tick_volume", 1)))
        spread = gold_bar.get("gold_spread", gold_bar.get("mean_spread", 0.20))

        # Reset daily accumulators at 00:00 UTC
        if self.current_date != d:
            self.current_date = d
            self.gold_cum_vol = 0.0
            self.gold_cum_pv = 0.0
            self.gold_cum_p2v = 0.0
            self.silver_cum_vol = 0.0
            self.silver_cum_pv = 0.0
            self.silver_cum_p2v = 0.0
            self.bars_in_trade = 0
            self.traded_today_count = 0

        # Update Gold VWAP & Variance
        g_tp = (gh + gl + gc) / 3.0
        self.gold_cum_vol += g_vol
        self.gold_cum_pv += g_tp * g_vol
        self.gold_cum_p2v += (g_tp ** 2) * g_vol

        self.gold_vwap = self.gold_cum_pv / self.gold_cum_vol
        g_var = max(0.0, (self.gold_cum_p2v / self.gold_cum_vol) - (self.gold_vwap ** 2))
        g_std = math.sqrt(g_var)
        self.gold_upper = self.gold_vwap + (g_std * self.gold_band_mult)
        self.gold_lower = self.gold_vwap - (g_std * self.gold_band_mult)

        # Update Silver VWAP & Variance (if available)
        silver_overbought = False
        silver_oversold = False
        if silver_bar is not None:
            sh = silver_bar["high"]
            sl = silver_bar["low"]
            sc = silver_bar["close"]
            s_vol = max(1.0, float(silver_bar.get("tick_volume", 1)))
            s_tp = (sh + sl + sc) / 3.0

            self.silver_cum_vol += s_vol
            self.silver_cum_pv += s_tp * s_vol
            self.silver_cum_p2v += (s_tp ** 2) * s_vol

            self.silver_vwap = self.silver_cum_pv / self.silver_cum_vol
            s_var = max(0.0, (self.silver_cum_p2v / self.silver_cum_vol) - (self.silver_vwap ** 2))
            s_std = math.sqrt(s_var)
            self.silver_upper = self.silver_vwap + (s_std * self.silver_band_mult)
            self.silver_lower = self.silver_vwap - (s_std * self.silver_band_mult)

            # Silver status
            silver_overbought = (sh >= self.silver_upper)
            silver_oversold = (sl <= self.silver_lower)

        self.governor.on_new_bar(dt, self.engine.equity)

        # Manage active position
        if len(self.engine.positions) > 0:
            self.bars_in_trade += 1
            if self.bars_in_trade >= self.max_bars_hold:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
                self.bars_in_trade = 0
            return
        else:
            self.bars_in_trade = 0

        # Golden Trading Window: 08:00 - 16:00 UTC (London & NY Overlap)
        if not ((8, 0) <= (t.hour, t.minute) <= (16, 0)) or self.traded_today_count >= 2:
            return

        body = abs(gc - go)
        rng = gh - gl
        if rng < 0.35:
            return

        upper_wick = gh - max(go, gc)
        lower_wick = min(go, gc) - gl

        # =====================================================================
        # SETUP 1: BEARISH HYBRID FADE (Gold at Upper Band + SMT Divergence)
        # =====================================================================
        # 1. Gold stretches to >= +1.8 sigma upper band
        # 2. Candle rejection: upper wick >= 40% of range and candle closes red (gc < go)
        # 3. SMT Filter: Silver is NOT confirming the extreme overbought extension (relative weakness)
        if gh >= self.gold_upper and (upper_wick / rng) >= 0.40 and gc < go:
            smt_ok = not self.require_smt or (silver_bar is None) or (not silver_overbought)
            if smt_ok:
                stop = round(gh + self.sl_buffer, 2)
                risk_dist = stop - gc
                if 0.80 <= risk_dist <= 5.00:
                    tp = round(gc - (risk_dist * self.risk_reward_ratio), 2)
                    if self.gold_vwap < gc and (gc - self.gold_vwap) >= risk_dist * 1.5:
                        tp = round(self.gold_vwap, 2)

                    approval: RatchetApproval = self.governor.evaluate_entry(
                        entry_price=gc,
                        stop_loss=stop,
                        current_spread=spread,
                        max_allowed_spread=0.25,
                        num_open_positions=len(self.engine.positions)
                    )

                    if approval.approved:
                        pos_id = self.engine.sell(
                            symbol="XAUUSD",
                            volume_lots=approval.lots,
                            stop_loss=stop,
                            take_profit=tp,
                            comment="Hybrid_Bearish_Fade",
                            tag="Hybrid_SuperAlpha"
                        )
                        if pos_id:
                            self.traded_today_count += 1
                            return

        # =====================================================================
        # SETUP 2: BULLISH HYBRID FADE (Gold at Lower Band + SMT Divergence)
        # =====================================================================
        # 1. Gold stretches to <= -1.8 sigma lower band
        # 2. Candle rejection: lower wick >= 40% of range and candle closes green (gc > go)
        # 3. SMT Filter: Silver is NOT confirming extreme oversold (relative strength / bear trap)
        if gl <= self.gold_lower and (lower_wick / rng) >= 0.40 and gc > go:
            smt_ok = not self.require_smt or (silver_bar is None) or (not silver_oversold)
            if smt_ok:
                stop = round(gl - self.sl_buffer, 2)
                risk_dist = gc - stop
                if 0.80 <= risk_dist <= 5.00:
                    tp = round(gc + (risk_dist * self.risk_reward_ratio), 2)
                    if self.gold_vwap > gc and (self.gold_vwap - gc) >= risk_dist * 1.5:
                        tp = round(self.gold_vwap, 2)

                    approval: RatchetApproval = self.governor.evaluate_entry(
                        entry_price=gc,
                        stop_loss=stop,
                        current_spread=spread,
                        max_allowed_spread=0.25,
                        num_open_positions=len(self.engine.positions)
                    )

                    if approval.approved:
                        pos_id = self.engine.buy(
                            symbol="XAUUSD",
                            volume_lots=approval.lots,
                            stop_loss=stop,
                            take_profit=tp,
                            comment="Hybrid_Bullish_Fade",
                            tag="Hybrid_SuperAlpha"
                        )
                        if pos_id:
                            self.traded_today_count += 1
                            return
