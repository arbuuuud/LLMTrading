"""
XAUUSD SMT Asia Sweep Sniper (Institutional Intermarket Strategy).
Trades high-conviction false breakouts of the Asia Session Range (00:00 - 06:00 UTC)
confirmed by Smart Money Technique (SMT) Divergence against Silver (XAGUSD):

1. Setup:
   - Asia Range (00:00 - 06:00 UTC) establishes Key Session High & Low.
   - During London / NY window (07:00 - 16:00 UTC):
     * Bearish SMT: Gold sweeps Asia High (>= Asia High + $0.80), but Silver FAILS to break its Asia High.
     * Bullish SMT: Gold sweeps Asia Low (<= Asia Low - $0.80), but Silver FAILS to break its Asia Low.

2. Risk & Execution:
   - Minimum SL Distance: $2.00 (20 pips) to prevent premature whipsaw shakeouts.
   - Take Profit: Target R:R 1:2.5 (or Asia Range Equilibrium).
   - Dynamic Risk Sizing: Exactly 0.5% risk ($50) standard, 0.25% ($25) in Greed Mode.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, time

from engine.core.types import OrderDirection, ExitReason
from engine.core.strategy_base import BaseStrategy
from agents.risk_manager.daily_ratchet import DailyRatchetRiskGovernor, SizingApproval


class XAUUSDSMTSweepSniper(BaseStrategy):
    def __init__(
        self,
        min_sweep_dollars: float = 0.80,
        min_sl_distance: float = 2.00,
        sl_buffer_dollars: float = 0.50,
        risk_reward_ratio: float = 2.5,
        base_risk_pct: float = 0.5,
        greed_risk_pct: float = 0.25,
        max_bars_hold: int = 150
    ):
        super().__init__("XAUUSD_SMT_Asia_Sweep_Sniper")
        self.min_sweep = min_sweep_dollars
        self.min_sl_distance = min_sl_distance
        self.sl_buffer = sl_buffer_dollars
        self.risk_reward_ratio = risk_reward_ratio
        self.max_bars_hold = max_bars_hold

        self.risk_governor = DailyRatchetRiskGovernor(
            base_risk_pct=base_risk_pct,
            greed_risk_pct=greed_risk_pct,
            max_daily_loss_pct=1.0,
            max_daily_trades_under_target=2,
            cooldown_bars=30
        )

        # State tracking
        self.current_date = None
        self.gold_asia_high: Optional[float] = None
        self.gold_asia_low: Optional[float] = None
        self.asia_complete = False

        self.silver_asia_high: Optional[float] = None
        self.silver_asia_low: Optional[float] = None
        self.silver_trade_high: float = 0.0
        self.silver_trade_low: float = 9999.0

        self.trade_today = False
        self.bars_in_trade = 0

    def on_init(self):
        self.current_date = None
        self.gold_asia_high = None
        self.gold_asia_low = None
        self.asia_complete = False
        self.silver_asia_high = None
        self.silver_asia_low = None
        self.silver_trade_high = 0.0
        self.silver_trade_low = 9999.0
        self.trade_today = False
        self.bars_in_trade = 0

    def on_trade_closed(self, trade_record):
        self.risk_governor.on_trade_closed(trade_record.net_pnl)

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
        spread = gold_bar.get("gold_spread", gold_bar.get("mean_spread", 0.20))

        # Reset state on new day
        if self.current_date != d:
            self.current_date = d
            self.gold_asia_high = None
            self.gold_asia_low = None
            self.asia_complete = False
            self.silver_asia_high = None
            self.silver_asia_low = None
            self.silver_trade_high = 0.0
            self.silver_trade_low = 9999.0
            self.trade_today = False
            self.bars_in_trade = 0
            self.risk_governor.on_new_day(d, self.engine.equity)

        self.risk_governor.on_bar_tick(dt, self.engine.equity)

        # Track Asia Session Range (00:00 - 06:00 UTC)
        if time(0, 0) <= t < time(6, 0):
            if self.gold_asia_high is None or gh > self.gold_asia_high:
                self.gold_asia_high = gh
            if self.gold_asia_low is None or gl < self.gold_asia_low:
                self.gold_asia_low = gl

            if silver_bar:
                sh = silver_bar["high"]
                sl = silver_bar["low"]
                if self.silver_asia_high is None or sh > self.silver_asia_high:
                    self.silver_asia_high = sh
                if self.silver_asia_low is None or sl < self.silver_asia_low:
                    self.silver_asia_low = sl
            return

        elif t >= time(6, 0) and self.gold_asia_high is not None and not self.asia_complete:
            self.asia_complete = True

        if not self.asia_complete or self.gold_asia_high is None or self.silver_asia_high is None:
            return

        # Track Silver running extremums from 07:00 onwards
        if silver_bar and t >= time(7, 0):
            self.silver_trade_high = max(self.silver_trade_high, silver_bar["high"])
            self.silver_trade_low = min(self.silver_trade_low, silver_bar["low"])

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

        # Trade window: London & NY (07:00 - 15:30 UTC)
        if not ((7, 0) <= (t.hour, t.minute) <= (15, 30)) or self.trade_today:
            return

        # =====================================================================
        # SETUP 1: BEARISH SMT ASIA HIGH SWEEP
        # =====================================================================
        # Gold swept Asia High by >= min_sweep, Silver failed to sweep its Asia High
        if gh >= self.gold_asia_high + self.min_sweep:
            silver_failed = (self.silver_trade_high <= self.silver_asia_high + 0.02)
            # Rejection confirmation: candle closes red back below Asia High + buffer
            if silver_failed and gc < go and gc < self.gold_asia_high + 0.30:
                stop = max(gh + self.sl_buffer, gc + self.min_sl_distance)
                risk_dist = stop - gc
                tp = round(gc - (risk_dist * self.risk_reward_ratio), 2)
                stop = round(stop, 2)

                approval: SizingApproval = self.risk_governor.evaluate_entry(
                    entry_price=gc,
                    stop_loss=stop,
                    current_spread=spread,
                    max_allowed_spread=0.22,
                    num_open_positions=len(self.engine.positions)
                )

                if approval.approved:
                    pos_id = self.engine.sell(
                        symbol="XAUUSD",
                        volume_lots=approval.lots,
                        stop_loss=stop,
                        take_profit=tp,
                        comment="Bearish_SMT_Sweep",
                        tag="SMT_Asia_Sweep"
                    )
                    if pos_id:
                        self.trade_today = True
                        return

        # =====================================================================
        # SETUP 2: BULLISH SMT ASIA LOW SWEEP
        # =====================================================================
        # Gold swept Asia Low by >= min_sweep, Silver failed to sweep its Asia Low
        if gl <= self.gold_asia_low - self.min_sweep:
            silver_failed = (self.silver_trade_low >= self.silver_asia_low - 0.02)
            # Rejection confirmation: candle closes green back above Asia Low - buffer
            if silver_failed and gc > go and gc > self.gold_asia_low - 0.30:
                stop = min(gl - self.sl_buffer, gc - self.min_sl_distance)
                risk_dist = gc - stop
                tp = round(gc + (risk_dist * self.risk_reward_ratio), 2)
                stop = round(stop, 2)

                approval: SizingApproval = self.risk_governor.evaluate_entry(
                    entry_price=gc,
                    stop_loss=stop,
                    current_spread=spread,
                    max_allowed_spread=0.22,
                    num_open_positions=len(self.engine.positions)
                )

                if approval.approved:
                    pos_id = self.engine.buy(
                        symbol="XAUUSD",
                        volume_lots=approval.lots,
                        stop_loss=stop,
                        take_profit=tp,
                        comment="Bullish_SMT_Sweep",
                        tag="SMT_Asia_Sweep"
                    )
                    if pos_id:
                        self.trade_today = True
                        return
