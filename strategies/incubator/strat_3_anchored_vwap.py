"""
Strategy 3: Session Anchored VWAP +/- 2.0 Sigma Mean Reversion (Auction Market Theory).
Institutional Playbook:
- Session Anchored VWAP: Resets daily at 00:00 UTC, tracking the true institutional volume-weighted benchmark.
- Standard Deviation Bands (+/- 1.0 sigma, +/- 2.0 sigma):
  * 68.2% of normal volume distribution occurs within +/- 1.0 sigma (Value Area).
  * 95.4% occurs within +/- 2.0 sigma.
- Setup:
  * When price overextends to >= +2.0 sigma (Extreme Premium / Overbought) during London/NY trading hours:
    Look for exhaustion candle rejection to short mean-reversion back towards VWAP.
  * When price overextends to <= -2.0 sigma (Extreme Discount / Oversold):
    Look for exhaustion candle rejection to buy mean-reversion back towards VWAP.
- Stop Loss: Anchored beyond the 2.5 sigma extreme or recent rejection wick.
- Take Profit: Anchored at VWAP Mean (0.0 sigma) or 1.0 sigma target (minimum R:R 1:2.0).
- Governed by Monthly Ratchet Governor.
"""

from typing import Dict, Any, Optional
from datetime import datetime, time, date
import math

from engine.core.types import OrderDirection, ExitReason
from engine.core.strategy_base import BaseStrategy
from strategies.modules.triggers.candlestick_patterns import CandlestickPatternDetector
from agents.risk_manager.monthly_ratchet_governor import MonthlyRatchetGovernor, RatchetApproval


class SessionAnchoredVWAPStrategy(BaseStrategy):
    def __init__(
        self,
        band_multiplier: float = 1.8,      # Fade at 1.8 standard deviations (Empirically verified)
        sl_buffer_dollars: float = 0.50,
        risk_reward_ratio: float = 2.0,
        base_risk_pct: float = 0.5,
        greed_risk_pct: float = 0.25,
        max_bars_hold: int = 60,           # 1-hour maximum hold for mean reversion
        start_hour: int = 10,
        start_minute: int = 30,
        end_hour: int = 14,
        end_minute: int = 30,
        enable_macro_filter: bool = True,  # H1 EMA 50 Parabolic Protection
        macro_ema_period: int = 50,
        parabolic_buffer_dollars: float = 15.0
    ):
        super().__init__("Anchored_VWAP_Mean_Reversion")
        self.band_multiplier = band_multiplier
        self.sl_buffer = sl_buffer_dollars
        self.risk_reward_ratio = risk_reward_ratio
        self.max_bars_hold = max_bars_hold
        self.start_time = (start_hour, start_minute)
        self.end_time = (end_hour, end_minute)
        self.enable_macro_filter = enable_macro_filter
        self.macro_ema_period = macro_ema_period
        self.parabolic_buffer_dollars = parabolic_buffer_dollars

        self.candle_detector = CandlestickPatternDetector()
        self.governor = MonthlyRatchetGovernor(
            base_risk_pct=base_risk_pct,
            greed_risk_pct=greed_risk_pct,
            max_daily_loss_pct=1.0,
            monthly_loss_cap_pct=3.0,
            cooldown_bars=25
        )

        # Macro EMA Tracking
        self.current_h1_bar: Optional[Dict[str, Any]] = None
        self.current_macro_ema: Optional[float] = None

        # VWAP accumulators
        self.current_date: Optional[date] = None
        self.cum_vol: float = 0.0
        self.cum_pv: float = 0.0
        self.cum_p2v: float = 0.0

        self.current_vwap: float = 0.0
        self.current_std: float = 0.0
        self.upper_band: float = 0.0
        self.lower_band: float = 0.0

        self.bars_in_trade: int = 0
        self.traded_today_count: int = 0

    def on_init(self):
        self.current_date = None
        self.cum_vol = 0.0
        self.cum_pv = 0.0
        self.cum_p2v = 0.0
        self.current_vwap = 0.0
        self.current_std = 0.0
        self.upper_band = 0.0
        self.lower_band = 0.0
        self.bars_in_trade = 0
        self.traded_today_count = 0
        self.current_h1_bar = None
        self.current_macro_ema = None

    def _update_macro_h1(self, bar: Dict[str, Any]):
        dt: datetime = bar["timestamp"]
        h1_time = dt.replace(minute=0, second=0, microsecond=0)
        if self.current_h1_bar is None or self.current_h1_bar["timestamp"] != h1_time:
            if self.current_h1_bar is not None:
                c = self.current_h1_bar["close"]
                alpha = 2.0 / (self.macro_ema_period + 1.0)
                if self.current_macro_ema is None:
                    self.current_macro_ema = c
                else:
                    self.current_macro_ema = (c * alpha) + (self.current_macro_ema * (1.0 - alpha))
            self.current_h1_bar = {
                "timestamp": h1_time,
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"]
            }
        else:
            self.current_h1_bar["high"] = max(self.current_h1_bar["high"], bar["high"])
            self.current_h1_bar["low"] = min(self.current_h1_bar["low"], bar["low"])
            self.current_h1_bar["close"] = bar["close"]

    def on_trade_closed(self, trade_record):
        self.governor.on_trade_closed(trade_record.net_pnl)

    def on_bar(self, bar: Dict[str, Any]):
        dt: datetime = bar["timestamp"]
        d = dt.date()
        t = dt.time()

        gh = bar["high"]
        gl = bar["low"]
        gc = bar["close"]
        go = bar["open"]
        vol = max(1.0, float(bar.get("tick_volume", 1)))
        spread = bar.get("mean_spread", 0.20)

        # Update Macro H1 EMA
        self._update_macro_h1(bar)

        # Reset accumulators on new trading day
        if self.current_date != d:
            self.current_date = d
            self.cum_vol = 0.0
            self.cum_pv = 0.0
            self.cum_p2v = 0.0
            self.bars_in_trade = 0
            self.traded_today_count = 0

        # Typical Price = (High + Low + Close) / 3
        tp_price = (gh + gl + gc) / 3.0
        self.cum_vol += vol
        self.cum_pv += tp_price * vol
        self.cum_p2v += (tp_price ** 2) * vol

        # Compute VWAP and Variance
        self.current_vwap = self.cum_pv / self.cum_vol
        variance = max(0.0, (self.cum_p2v / self.cum_vol) - (self.current_vwap ** 2))
        self.current_std = math.sqrt(variance)

        self.upper_band = self.current_vwap + (self.current_std * self.band_multiplier)
        self.lower_band = self.current_vwap - (self.current_std * self.band_multiplier)

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

        # Golden Institutional Window: High-Volume Auction Core (Default: 10:30 - 14:30 UTC)
        # Eliminates 08:00-10:00 manipulation & 15:00-16:00 whipsaw sinkhole
        is_trade_window = self.start_time <= (t.hour, t.minute) <= self.end_time
        if not is_trade_window or self.traded_today_count >= 2:
            return

        # Candle rejection metrics
        body = abs(gc - go)
        rng = gh - gl
        if rng < 0.35:
            return

        upper_wick = gh - max(go, gc)
        lower_wick = min(go, gc) - gl

        # Evaluate Macro Trend Protection
        allow_buy = True
        allow_sell = True
        if self.enable_macro_filter and self.current_macro_ema is not None:
            # If price is extended parabolically above H1 EMA 50, do NOT short into runaway bull rally!
            if (gc - self.current_macro_ema) > self.parabolic_buffer_dollars:
                allow_sell = False
            # If price is extended parabolically below H1 EMA 50, do NOT buy into freefall drop!
            elif (self.current_macro_ema - gc) > self.parabolic_buffer_dollars:
                allow_buy = False

        # =====================================================================
        # SETUP 1: BEARISH MEAN REVERSION (+2.0 Sigma Overextension)
        # =====================================================================
        if gh >= self.upper_band and (upper_wick / rng) >= 0.45 and gc < go and allow_sell:
            stop = round(gh + self.sl_buffer, 2)
            risk_dist = stop - gc
            if 0.80 <= risk_dist <= 5.00:
                # Target is VWAP mean or fixed R:R
                tp = round(gc - (risk_dist * self.risk_reward_ratio), 2)
                if self.current_vwap < gc and (gc - self.current_vwap) >= risk_dist * 1.5:
                    tp = round(self.current_vwap, 2)

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
                        comment="VWAP_Upper_Fade",
                        tag="VWAP_Mean_Reversion"
                    )
                    if pos_id:
                        self.traded_today_count += 1
                        return

        # =====================================================================
        # SETUP 2: BULLISH MEAN REVERSION (-2.0 Sigma Overextension)
        # =====================================================================
        if gl <= self.lower_band and (lower_wick / rng) >= 0.45 and gc > go and allow_buy:
            stop = round(gl - self.sl_buffer, 2)
            risk_dist = gc - stop
            if 0.80 <= risk_dist <= 5.00:
                tp = round(gc + (risk_dist * self.risk_reward_ratio), 2)
                if self.current_vwap > gc and (self.current_vwap - gc) >= risk_dist * 1.5:
                    tp = round(self.current_vwap, 2)

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
                        comment="VWAP_Lower_Fade",
                        tag="VWAP_Mean_Reversion"
                    )
                    if pos_id:
                        self.traded_today_count += 1
                        return
