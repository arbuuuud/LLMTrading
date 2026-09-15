"""
Institutional Monthly 20% Ratchet Risk Governor.
Implements the multi-tiered Profit Bottoming Lock, Greed Mode House Money Sizing,
and Monthly Drawdown Circuit Breaker:

1. Daily Ratchet Tiers:
   - Starting state: 0% PnL, base risk 0.5% ($50 on $10k).
   - Tier 1: Daily Profit >= +1.5% -> Lock Floor at +1.0% ($100 guaranteed).
             Switch to Greed Mode (Risk cut to 0.25% = $25 "House Money").
   - Tier 2: Daily Profit >= +2.0% -> Lock Floor at +1.5% ($150 guaranteed).
   - Tier 3: Daily Profit >= +2.5% -> Lock Floor at +2.0% ($200 guaranteed).
   - Tier 4: Daily Profit >= +3.5% -> Lock Floor at +3.0% ($300 guaranteed).
   - Floor Breach: If PnL retreats to or below the locked floor -> IMMEDIATE SHUTDOWN FOR THE DAY.

2. Daily Loss Protection (2-Strike Circuit Breaker):
   - 2 consecutive losses in a day (-0.5% + -0.5% = -1.0%) -> IMMEDIATE SHUTDOWN FOR THE DAY.

3. Monthly Circuit Breaker (-3.0% Cap):
   - If cumulative monthly drawdown reaches -3.0% (-$300 on $10k) -> PAUSE TRADING FOR THE REST OF THE MONTH.
   - Preserves 97% of capital to protect previous profitable months.

4. Post-Trade Cooldown:
   - 20-minute minimum cooldown between trades to avoid immediate consolidation whipsaws.
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, date


@dataclass
class RatchetApproval:
    approved: bool
    reason: str
    lots: float
    risk_dollars: float
    risk_pct: float
    daily_pnl_pct: float
    locked_floor_pct: float
    monthly_pnl_pct: float
    is_greed_mode: bool


class MonthlyRatchetGovernor:
    def __init__(
        self,
        base_risk_pct: float = 0.5,        # 0.5% ($50) standard risk per trade
        greed_risk_pct: float = 0.25,      # 0.25% ($25) in Greed Mode (House Money)
        max_daily_loss_pct: float = 1.0,   # -1.0% daily hard stop (2-strike rule)
        monthly_loss_cap_pct: float = 3.0, # -3.0% monthly drawdown kill-switch
        cooldown_bars: int = 20,           # 20 M1 bars cooldown between trades
        contract_size: float = 100.0,
        min_lots: float = 0.01,
        max_lots: float = 5.0
    ):
        self.base_risk_pct = base_risk_pct
        self.greed_risk_pct = greed_risk_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.monthly_loss_cap_pct = monthly_loss_cap_pct
        self.cooldown_bars = cooldown_bars
        self.contract_size = contract_size
        self.min_lots = min_lots
        self.max_lots = max_lots

        # Tracking state
        self.current_date: Optional[date] = None
        self.current_month: Optional[str] = None
        self.month_start_equity: float = 10000.0
        self.day_start_equity: float = 10000.0

        self.daily_closed_pnl: float = 0.0
        self.monthly_closed_pnl: float = 0.0
        self.daily_consecutive_losses: int = 0
        self.daily_total_trades: int = 0
        self.locked_floor_pct: float = -999.0
        
        self.daily_stopped: bool = False
        self.monthly_stopped: bool = False
        self.bars_since_last_exit: int = 999

    def on_new_bar(self, dt: datetime, current_equity: float):
        d = dt.date()
        mo = d.strftime("%Y-%m")

        # Monthly rollover
        if self.current_month != mo:
            self.current_month = mo
            self.month_start_equity = current_equity
            self.monthly_closed_pnl = 0.0
            self.monthly_stopped = False

        # Daily rollover
        if self.current_date != d:
            self.current_date = d
            self.day_start_equity = current_equity
            self.daily_closed_pnl = 0.0
            self.daily_consecutive_losses = 0
            self.daily_total_trades = 0
            self.locked_floor_pct = -999.0
            self.daily_stopped = False
            self.bars_since_last_exit = 999
        else:
            self.bars_since_last_exit += 1

    def on_trade_closed(self, net_pnl: float):
        self.daily_closed_pnl += net_pnl
        self.monthly_closed_pnl += net_pnl
        self.daily_total_trades += 1
        self.bars_since_last_exit = 0

        if net_pnl < 0:
            self.daily_consecutive_losses += 1
        else:
            self.daily_consecutive_losses = 0

        curr_daily_pct = (self.daily_closed_pnl / self.day_start_equity) * 100.0
        curr_monthly_pct = (self.monthly_closed_pnl / self.month_start_equity) * 100.0

        # Check Monthly Circuit Breaker (-3.0%)
        if curr_monthly_pct <= -self.monthly_loss_cap_pct:
            self.monthly_stopped = True
            return

        # Check Daily 2-Strike Loss Stop (-1.0%)
        if self.daily_consecutive_losses >= 2 or curr_daily_pct <= -self.max_daily_loss_pct:
            self.daily_stopped = True
            return

        # === Dynamic Ratchet Profit Locking (Bottoming Lock) ===
        if curr_daily_pct >= 3.5:
            self.locked_floor_pct = max(self.locked_floor_pct, 3.0)
        elif curr_daily_pct >= 2.5:
            self.locked_floor_pct = max(self.locked_floor_pct, 2.0)
        elif curr_daily_pct >= 2.0:
            self.locked_floor_pct = max(self.locked_floor_pct, 1.5)
        elif curr_daily_pct >= 1.5:
            self.locked_floor_pct = max(self.locked_floor_pct, 1.0)

        # Bottoming Floor Breach Check
        if self.locked_floor_pct > 0.0 and curr_daily_pct <= self.locked_floor_pct:
            self.daily_stopped = True  # Profit locked for the day!

    def evaluate_entry(
        self,
        entry_price: float,
        stop_loss: float,
        current_spread: float,
        max_allowed_spread: float = 0.25,
        num_open_positions: int = 0
    ) -> RatchetApproval:
        curr_daily_pct = (self.daily_closed_pnl / self.day_start_equity) * 100.0
        curr_monthly_pct = (self.monthly_closed_pnl / self.month_start_equity) * 100.0

        # Gate 1: Monthly Circuit Breaker
        if self.monthly_stopped:
            return RatchetApproval(
                False, f"MONTHLY_CAP_REACHED: Month PnL ({curr_monthly_pct:.2f}%) hit -{self.monthly_loss_cap_pct}%. Paused until next month.",
                0.0, 0.0, 0.0, curr_daily_pct, self.locked_floor_pct, curr_monthly_pct, False
            )

        # Gate 2: Daily Shutdown
        if self.daily_stopped:
            reason = "DAILY_STOP_ACTIVE: Daily loss limit reached."
            if self.locked_floor_pct > 0.0:
                reason = f"BOTTOMING_FLOOR_LOCKED: Profit locked at +{self.locked_floor_pct:.1f}% for the day!"
            return RatchetApproval(
                False, reason, 0.0, 0.0, 0.0, curr_daily_pct, self.locked_floor_pct, curr_monthly_pct, False
            )

        # Gate 3: Position concurrency
        if num_open_positions > 0:
            return RatchetApproval(False, "ALREADY_IN_POSITION", 0.0, 0.0, 0.0, curr_daily_pct, self.locked_floor_pct, curr_monthly_pct, False)

        # Gate 4: Cooldown period
        if self.bars_since_last_exit < self.cooldown_bars:
            return RatchetApproval(
                False, f"COOLDOWN_ACTIVE: {self.bars_since_last_exit}/{self.cooldown_bars} bars elapsed.",
                0.0, 0.0, 0.0, curr_daily_pct, self.locked_floor_pct, curr_monthly_pct, False
            )

        # Gate 5: Spread filter
        if current_spread > max_allowed_spread:
            return RatchetApproval(
                False, f"SPREAD_GUARD: Spread ${current_spread:.2f} > max ${max_allowed_spread:.2f}.",
                0.0, 0.0, 0.0, curr_daily_pct, self.locked_floor_pct, curr_monthly_pct, False
            )

        # Gate 6: Stop loss distance sanity
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance < 0.50 or sl_distance > 5.00:
            return RatchetApproval(
                False, f"INVALID_SL_RANGE: SL distance ${sl_distance:.2f} outside [0.50, 5.00].",
                0.0, 0.0, 0.0, curr_daily_pct, self.locked_floor_pct, curr_monthly_pct, False
            )

        # === Dynamic Risk Selection (House Money vs Base) ===
        is_greed = (curr_daily_pct >= 1.5)
        active_risk_pct = self.greed_risk_pct if is_greed else self.base_risk_pct

        target_risk_dollars = self.day_start_equity * (active_risk_pct / 100.0)
        calculated_lots = target_risk_dollars / (sl_distance * self.contract_size)
        clamped_lots = round(max(self.min_lots, min(self.max_lots, calculated_lots)), 2)

        return RatchetApproval(
            approved=True,
            reason="TRADE_APPROVED",
            lots=clamped_lots,
            risk_dollars=round(clamped_lots * sl_distance * self.contract_size, 2),
            risk_pct=active_risk_pct,
            daily_pnl_pct=round(curr_daily_pct, 2),
            locked_floor_pct=round(self.locked_floor_pct, 2),
            monthly_pnl_pct=round(curr_monthly_pct, 2),
            is_greed_mode=is_greed
        )
