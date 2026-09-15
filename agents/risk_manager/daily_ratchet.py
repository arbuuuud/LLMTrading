"""
Daily Ratchet Risk Governor and Dynamic Sizing Module.
Implements:
1. Dynamic Risk-Targeted Lot Sizing based on precise Stop Loss distance in points.
2. Kondisi 1 (Greed Mode Ratchet):
   - When daily profit >= +1.5% -> Lock floor at +1.0%, cut trade risk to 0.25% (House Money).
   - When daily profit >= +2.5% -> Lock floor at +2.0%, cut trade risk to 0.25%.
   - If profit drops back to the locked floor -> HARD STOP for the day.
3. Kondisi 2 (Discipline Cap):
   - Max 3 trades per day if daily profit is between 0% and +1.0%.
4. Kondisi 3 (2-Strike Loss Circuit Breaker):
   - 2 consecutive losses in a day (-0.5% each = -1.0% total) -> EMERGENCY STOP for the day.
5. Kondisi 4 (Post-Trade Cooldown):
   - Minimum 15 minutes rest between trades to avoid immediate zone whipsaws.
"""

from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass
from datetime import datetime, date


@dataclass
class SizingApproval:
    approved: bool
    reason: str
    lots: float
    risk_dollars: float
    risk_pct: float
    daily_pnl_pct: float
    locked_floor_pct: float
    is_greed_mode: bool


class DailyRatchetRiskGovernor:
    def __init__(
        self,
        base_risk_pct: float = 0.5,      # 0.5% risk per trade on standard conditions
        greed_risk_pct: float = 0.25,    # 0.25% risk per trade in Greed Mode (House Money)
        max_daily_loss_pct: float = 1.0, # 2 losses @ 0.5% = -1.0% max daily drawdown limit
        max_daily_trades_under_target: int = 3, # Cap at 3 trades if daily profit < 1%
        cooldown_bars: int = 15,         # 15 M1 bars cooldown between trades
        contract_size: float = 100.0,
        min_lots: float = 0.01,
        max_lots: float = 5.0
    ):
        self.base_risk_pct = base_risk_pct
        self.greed_risk_pct = greed_risk_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_trades_under_target = max_daily_trades_under_target
        self.cooldown_bars = cooldown_bars
        self.contract_size = contract_size
        self.min_lots = min_lots
        self.max_lots = max_lots

        # Daily state
        self.current_date: Optional[date] = None
        self.day_start_equity: float = 10000.0
        self.daily_closed_pnl: float = 0.0
        self.daily_consecutive_losses: int = 0
        self.daily_total_trades: int = 0
        self.daily_peak_pnl_pct: float = 0.0
        self.locked_floor_pct: float = -999.0  # Floor profit lock
        self.circuit_breaker_tripped: bool = False
        self.bars_since_last_exit: int = 999   # Cooldown counter

    def on_new_day(self, trade_date: date, starting_equity: float):
        self.current_date = trade_date
        self.day_start_equity = starting_equity
        self.daily_closed_pnl = 0.0
        self.daily_consecutive_losses = 0
        self.daily_total_trades = 0
        self.daily_peak_pnl_pct = 0.0
        self.locked_floor_pct = -999.0
        self.circuit_breaker_tripped = False
        self.bars_since_last_exit = 999

    def on_bar_tick(self, dt: datetime, current_equity: float):
        d = dt.date()
        if self.current_date != d:
            self.on_new_day(d, current_equity)
        else:
            self.bars_since_last_exit += 1

    def on_trade_closed(self, net_pnl: float):
        self.daily_closed_pnl += net_pnl
        self.daily_total_trades += 1
        self.bars_since_last_exit = 0  # Start 15-bar cooldown

        current_pnl_pct = (self.daily_closed_pnl / self.day_start_equity) * 100.0
        self.daily_peak_pnl_pct = max(self.daily_peak_pnl_pct, current_pnl_pct)

        if net_pnl < 0:
            self.daily_consecutive_losses += 1
        else:
            self.daily_consecutive_losses = 0

        # === KONDISI 3: 2-Strike Loss Circuit Breaker (-1.0% Max Loss) ===
        if self.daily_consecutive_losses >= 2 or current_pnl_pct <= -self.max_daily_loss_pct:
            self.circuit_breaker_tripped = True
            return

        # === KONDISI 1: Ratchet Daily Lock (Greed Mode) ===
        if current_pnl_pct >= 2.5:
            self.locked_floor_pct = max(self.locked_floor_pct, 2.0)
        elif current_pnl_pct >= 2.0:
            self.locked_floor_pct = max(self.locked_floor_pct, 1.5)
        elif current_pnl_pct >= 1.5:
            self.locked_floor_pct = max(self.locked_floor_pct, 1.0)

        # Check if profit retreated back into locked floor
        if self.locked_floor_pct > 0.0 and current_pnl_pct <= self.locked_floor_pct:
            self.circuit_breaker_tripped = True  # Profit locked for the day!

    def evaluate_entry(
        self,
        entry_price: float,
        stop_loss: float,
        current_spread: float,
        max_allowed_spread: float = 0.22,
        num_open_positions: int = 0
    ) -> SizingApproval:
        current_pnl_pct = (self.daily_closed_pnl / self.day_start_equity) * 100.0

        # Gate 1: Check circuit breaker
        if self.circuit_breaker_tripped:
            reason = "CIRCUIT_BREAKER_ACTIVE: Daily loss limit reached or Ratchet profit locked."
            if self.locked_floor_pct > 0.0:
                reason = f"RATCHET_LOCKED: Profit locked at +{self.locked_floor_pct:.1f}% for the day!"
            return SizingApproval(False, reason, 0.0, 0.0, 0.0, current_pnl_pct, self.locked_floor_pct, False)

        # Gate 2: Max open positions
        if num_open_positions > 0:
            return SizingApproval(False, "ALREADY_IN_POSITION", 0.0, 0.0, 0.0, current_pnl_pct, self.locked_floor_pct, False)

        # Gate 3: Cooldown period
        if self.bars_since_last_exit < self.cooldown_bars:
            return SizingApproval(
                False,
                f"COOLDOWN_ACTIVE: {self.bars_since_last_exit}/{self.cooldown_bars} bars elapsed.",
                0.0, 0.0, 0.0, current_pnl_pct, self.locked_floor_pct, False
            )

        # Gate 4: Spread filter
        if current_spread > max_allowed_spread:
            return SizingApproval(
                False,
                f"SPREAD_GUARD: Spread ${current_spread:.2f} > max ${max_allowed_spread:.2f}.",
                0.0, 0.0, 0.0, current_pnl_pct, self.locked_floor_pct, False
            )

        # Gate 5: Kondisi 2 (Discipline Cap under target)
        if current_pnl_pct < 1.0 and self.daily_total_trades >= self.max_trades_under_target:
            return SizingApproval(
                False,
                f"DISCIPLINE_CAP: Max {self.max_trades_under_target} trades under target reached.",
                0.0, 0.0, 0.0, current_pnl_pct, self.locked_floor_pct, False
            )

        # Gate 6: Stop loss distance sanity
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance < 0.40 or sl_distance > 3.50:
            return SizingApproval(
                False,
                f"INVALID_SL_RANGE: SL distance ${sl_distance:.2f} outside [0.40, 3.50].",
                0.0, 0.0, 0.0, current_pnl_pct, self.locked_floor_pct, False
            )

        # === Dynamic Risk Selection (House Money vs Standard) ===
        is_greed = (current_pnl_pct >= 1.5)
        active_risk_pct = self.greed_risk_pct if is_greed else self.base_risk_pct

        target_risk_dollars = self.day_start_equity * (active_risk_pct / 100.0)
        calculated_lots = target_risk_dollars / (sl_distance * self.contract_size)
        clamped_lots = round(max(self.min_lots, min(self.max_lots, calculated_lots)), 2)

        return SizingApproval(
            approved=True,
            reason="TRADE_APPROVED",
            lots=clamped_lots,
            risk_dollars=round(clamped_lots * sl_distance * self.contract_size, 2),
            risk_pct=active_risk_pct,
            daily_pnl_pct=round(current_pnl_pct, 2),
            locked_floor_pct=round(self.locked_floor_pct, 2),
            is_greed_mode=is_greed
        )
