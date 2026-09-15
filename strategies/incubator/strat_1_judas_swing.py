"""
Strategy 1: The London Open "Judas Swing" (London Trap Scalper).
Institutional Playbook:
- Asia Session (00:00 - 06:00 UTC) builds liquidity pools above Asia High & below Asia Low.
- London Killzone (07:00 - 09:30 UTC):
  * "Judas Swing": Algorithmic false drive above Asia High (BSL) or below Asia Low (SSL).
  * Minimum sweep depth: $0.50 - $2.50.
  * Confirmation: Rapid rejection candle closing back inside the Asia Range with displacement.
  * Order Entry: Limit / Market retest of the rejection zone.
  * Stop Loss: Anchored beyond the Judas extreme wick (+ $0.40 buffer).
  * Take Profit: Asia Range Equilibrium (50% midpoint) or Opposite Session Extreme (R:R >= 1:2.0).
  * Discipline: Maximum 1 Judas Swing trade per day.
"""

from typing import Dict, Any, Optional
from datetime import datetime, time

from engine.core.types import OrderDirection, ExitReason
from engine.core.strategy_base import BaseStrategy
from strategies.modules.context.session_tracker import SessionTracker
from strategies.modules.triggers.candlestick_patterns import CandlestickPatternDetector, PatternType
from agents.risk_manager.monthly_ratchet_governor import MonthlyRatchetGovernor, RatchetApproval


class LondonJudasSwingStrategy(BaseStrategy):
    def __init__(
        self,
        min_sweep_dollars: float = 0.50,
        max_sweep_dollars: float = 3.50,
        sl_buffer_dollars: float = 0.40,
        risk_reward_ratio: float = 2.0,
        base_risk_pct: float = 0.5,
        greed_risk_pct: float = 0.25,
        max_bars_hold: int = 90  # Hold up to 1.5 hours in London
    ):
        super().__init__("London_Judas_Swing")
        self.min_sweep = min_sweep_dollars
        self.max_sweep = max_sweep_dollars
        self.sl_buffer = sl_buffer_dollars
        self.risk_reward_ratio = risk_reward_ratio
        self.max_bars_hold = max_bars_hold

        self.session_tracker = SessionTracker()
        self.candle_detector = CandlestickPatternDetector()
        self.governor = MonthlyRatchetGovernor(
            base_risk_pct=base_risk_pct,
            greed_risk_pct=greed_risk_pct,
            max_daily_loss_pct=1.0,
            monthly_loss_cap_pct=3.0,
            cooldown_bars=30
        )

        self.current_date = None
        self.judas_traded_today = False
        self.bars_in_trade = 0

    def on_init(self):
        self.current_date = None
        self.judas_traded_today = False
        self.bars_in_trade = 0

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
        spread = bar.get("mean_spread", 0.20)

        if self.current_date != d:
            self.current_date = d
            self.judas_traded_today = False
            self.bars_in_trade = 0

        self.session_tracker.update(bar)
        candle = self.candle_detector.update(bar)
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

        # Wait until Asia session is complete
        if not self.session_tracker.asia_complete or self.session_tracker.asia_high is None:
            return

        # London Killzone only: 07:00 - 09:30 UTC (14:00 - 16:30 WIB)
        in_london_killzone = (7, 0) <= (t.hour, t.minute) <= (9, 30)
        if not in_london_killzone or self.judas_traded_today:
            return

        asia_high = self.session_tracker.asia_high
        asia_low = self.session_tracker.asia_low
        asia_mid = (asia_high + asia_low) / 2.0

        # =====================================================================
        # SETUP 1: BEARISH JUDAS SWING (Engineered High Trap)
        # =====================================================================
        if gh >= asia_high + self.min_sweep and gh <= asia_high + self.max_sweep:
            # Rejection: closes back inside or creates upper wick rejection
            if gc < go and gc <= asia_high + 0.25:
                stop = round(gh + self.sl_buffer, 2)
                risk_dist = stop - gc
                if risk_dist >= 0.80 and risk_dist <= 5.00:
                    tp = round(gc - (risk_dist * self.risk_reward_ratio), 2)
                    if asia_mid < gc and (gc - asia_mid) >= risk_dist * 1.5:
                        tp = round(asia_mid, 2)

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
                            comment="Judas_Short",
                            tag="London_Judas"
                        )
                        if pos_id:
                            self.judas_traded_today = True
                            return

        # =====================================================================
        # SETUP 2: BULLISH JUDAS SWING (Engineered Low Trap)
        # =====================================================================
        if gl <= asia_low - self.min_sweep and gl >= asia_low - self.max_sweep:
            if gc > go and gc >= asia_low - 0.25:
                stop = round(gl - self.sl_buffer, 2)
                risk_dist = gc - stop
                if risk_dist >= 0.80 and risk_dist <= 5.00:
                    tp = round(gc + (risk_dist * self.risk_reward_ratio), 2)
                    if asia_mid > gc and (asia_mid - gc) >= risk_dist * 1.5:
                        tp = round(asia_mid, 2)

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
                            comment="Judas_Long",
                            tag="London_Judas"
                        )
                        if pos_id:
                            self.judas_traded_today = True
                            return
