"""
Strategy 2: The ICT "Silver Bullet" (60-Minute New York Killzone Sniper).
Institutional Playbook:
- Strict 60-Minute Execution Window: 14:00 - 15:00 UTC (10:00 - 11:00 AM NY Time).
- Setup:
  1. Internal Liquidity Sweep: Price sweeps the 15-minute rolling Swing High or Swing Low.
  2. Market Structure Shift with Displacement: A 3-candle sequence creates a clear Fair Value Gap (FVG)
     (Bar 0 High < Bar 2 Low for Bullish FVG, or Bar 0 Low > Bar 2 High for Bearish FVG).
  3. Entry: Triggered when price retraces back into the FVG zone.
  4. Stop Loss: Set at the swing high/low that created the displacement (+ $0.35 buffer).
  5. Take Profit: Fixed R:R 1:2.0 or 1:2.5 target.
  6. Strict Kill-Off: Hard cutoff at 15:00 UTC (maximum 1 trade per window, zero overnight risk).
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, time

from engine.core.types import OrderDirection, ExitReason
from engine.core.strategy_base import BaseStrategy
from strategies.modules.triggers.displacement_fvg import DisplacementFVGDetector, FVGType, FVGSignal
from agents.risk_manager.monthly_ratchet_governor import MonthlyRatchetGovernor, RatchetApproval


class ICTSilverBulletStrategy(BaseStrategy):
    def __init__(
        self,
        fvg_min_size: float = 0.20,
        sl_buffer_dollars: float = 0.35,
        risk_reward_ratio: float = 2.0,
        base_risk_pct: float = 0.5,
        greed_risk_pct: float = 0.25,
        max_bars_hold: int = 40  # Close before the 60-minute window expires
    ):
        super().__init__("ICT_Silver_Bullet")
        self.fvg_min_size = fvg_min_size
        self.sl_buffer = sl_buffer_dollars
        self.risk_reward_ratio = risk_reward_ratio
        self.max_bars_hold = max_bars_hold

        self.fvg_detector = DisplacementFVGDetector(min_fvg_size_dollars=fvg_min_size, min_body_ratio=0.60)
        self.governor = MonthlyRatchetGovernor(
            base_risk_pct=base_risk_pct,
            greed_risk_pct=greed_risk_pct,
            max_daily_loss_pct=1.0,
            monthly_loss_cap_pct=3.0,
            cooldown_bars=20
        )

        self.history: List[Dict[str, Any]] = []
        self.current_date = None
        self.bullet_traded_today = False
        self.active_fvg: Optional[FVGSignal] = None
        self.fvg_swing_anchor: float = 0.0
        self.fvg_expiry_bars: int = 0
        self.bars_in_trade = 0

    def on_init(self):
        self.history.clear()
        self.current_date = None
        self.bullet_traded_today = False
        self.active_fvg = None
        self.fvg_swing_anchor = 0.0
        self.fvg_expiry_bars = 0
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
        spread = bar.get("mean_spread", 0.20)

        if self.current_date != d:
            self.current_date = d
            self.bullet_traded_today = False
            self.active_fvg = None
            self.bars_in_trade = 0

        self.history.append(bar)
        if len(self.history) > 40:
            self.history.pop(0)

        self.governor.on_new_bar(dt, self.engine.equity)
        fvg = self.fvg_detector.update(bar)

        # Manage active position
        if len(self.engine.positions) > 0:
            self.bars_in_trade += 1
            if self.bars_in_trade >= self.max_bars_hold or t >= time(15, 10):
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
                self.bars_in_trade = 0
            return
        else:
            self.bars_in_trade = 0

        # Strict Silver Bullet Killzone: 14:00 - 15:00 UTC (10:00 - 11:00 AM NY Time)
        in_silver_bullet_window = (14, 0) <= (t.hour, t.minute) <= (15, 0)
        if not in_silver_bullet_window or self.bullet_traded_today:
            self.active_fvg = None
            return

        # 1. Update detected FVG
        if fvg is not None:
            self.active_fvg = fvg
            self.fvg_expiry_bars = 10  # Must tap within 10 bars
            if fvg.fvg_type == FVGType.BEARISH_FVG:
                self.fvg_swing_anchor = max(b["high"] for b in self.history[-6:])
            else:
                self.fvg_swing_anchor = min(b["low"] for b in self.history[-6:])
        elif self.active_fvg is not None:
            self.fvg_expiry_bars -= 1
            if self.fvg_expiry_bars <= 0:
                self.active_fvg = None

        if self.active_fvg is None:
            return

        # 2. Check FVG Retest & Entry
        # Bullish Silver Bullet: Price enters Bullish FVG [bottom, top]
        if self.active_fvg.fvg_type == FVGType.BULLISH_FVG:
            if gl <= self.active_fvg.top and gc >= self.active_fvg.bottom:
                sl = round(self.fvg_swing_anchor - self.sl_buffer, 2)
                risk_dist = gc - sl
                if 0.60 <= risk_dist <= 4.50:
                    tp = round(gc + (risk_dist * self.risk_reward_ratio), 2)

                    approval: RatchetApproval = self.governor.evaluate_entry(
                        entry_price=gc,
                        stop_loss=sl,
                        current_spread=spread,
                        max_allowed_spread=0.25,
                        num_open_positions=len(self.engine.positions)
                    )

                    if approval.approved:
                        pos_id = self.engine.buy(
                            symbol="XAUUSD",
                            volume_lots=approval.lots,
                            stop_loss=sl,
                            take_profit=tp,
                            comment="Silver_Bullet_Long",
                            tag="ICT_Silver_Bullet"
                        )
                        if pos_id:
                            self.bullet_traded_today = True
                            self.active_fvg = None
                            return

        # Bearish Silver Bullet: Price enters Bearish FVG [bottom, top]
        elif self.active_fvg.fvg_type == FVGType.BEARISH_FVG:
            if gh >= self.active_fvg.bottom and gc <= self.active_fvg.top:
                sl = round(self.fvg_swing_anchor + self.sl_buffer, 2)
                risk_dist = sl - gc
                if 0.60 <= risk_dist <= 4.50:
                    tp = round(gc - (risk_dist * self.risk_reward_ratio), 2)

                    approval: RatchetApproval = self.governor.evaluate_entry(
                        entry_price=gc,
                        stop_loss=sl,
                        current_spread=spread,
                        max_allowed_spread=0.25,
                        num_open_positions=len(self.engine.positions)
                    )

                    if approval.approved:
                        pos_id = self.engine.sell(
                            symbol="XAUUSD",
                            volume_lots=approval.lots,
                            stop_loss=sl,
                            take_profit=tp,
                            comment="Silver_Bullet_Short",
                            tag="ICT_Silver_Bullet"
                        )
                        if pos_id:
                            self.bullet_traded_today = True
                            self.active_fvg = None
                            return
