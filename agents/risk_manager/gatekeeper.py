"""
Risk Management and Circuit Breaker Agent (The Gatekeeper).
Enforces hard institutional risk limits, dynamic volatility sizing,
spread filters, and absolute veto power over all strategy orders.
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, date
from engine.core.types import OrderDirection


@dataclass
class TradeApproval:
    approved: bool
    reason: str
    recommended_lots: float
    risk_dollars: float


class RiskGatekeeperAgent:
    def __init__(
        self,
        risk_per_trade_pct: float = 1.0,
        max_daily_loss_pct: float = 2.0,
        max_consecutive_losses: int = 4,
        max_spread_dollars: float = 0.25,
        min_lots: float = 0.01,
        max_lots: float = 5.0,
        contract_size: float = 100.0
    ):
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_consecutive_losses = max_consecutive_losses
        self.max_spread = max_spread_dollars
        self.min_lots = min_lots
        self.max_lots = max_lots
        self.contract_size = contract_size

        # Internal tracking state
        self.current_date: Optional[date] = None
        self.day_start_equity: float = 10000.0
        self.current_daily_loss_pct: float = 0.0
        self.consecutive_losses: int = 0
        self.circuit_breaker_tripped: bool = False

    def on_new_bar(self, dt: datetime, current_equity: float):
        d = dt.date()
        if self.current_date != d:
            self.current_date = d
            self.day_start_equity = current_equity
            self.current_daily_loss_pct = 0.0
            self.consecutive_losses = 0
            self.circuit_breaker_tripped = False
        else:
            if self.day_start_equity > 0:
                dd_dollars = self.day_start_equity - current_equity
                self.current_daily_loss_pct = max(0.0, (dd_dollars / self.day_start_equity) * 100.0)
                if self.current_daily_loss_pct >= self.max_daily_loss_pct:
                    self.circuit_breaker_tripped = True

    def on_trade_closed(self, net_pnl: float):
        if net_pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_consecutive_losses:
                self.circuit_breaker_tripped = True
        else:
            self.consecutive_losses = 0

    def evaluate_order(
        self,
        symbol: str,
        direction: OrderDirection,
        entry_price: float,
        stop_loss: float,
        current_spread: float,
        account_equity: float,
        num_open_positions: int
    ) -> TradeApproval:
        # Gate 1: Circuit breaker check
        if self.circuit_breaker_tripped:
            return TradeApproval(
                approved=False,
                reason=f"CIRCUIT_BREAKER: Daily DD ({self.current_daily_loss_pct:.1f}%) or Consec Losses ({self.consecutive_losses}) exceeded limit.",
                recommended_lots=0.0,
                risk_dollars=0.0
            )

        # Gate 2: Max open positions (Scalping = 1 active position at a time)
        if num_open_positions >= 1:
            return TradeApproval(
                approved=False,
                reason="CONCURRENCY_LIMIT: Position already open.",
                recommended_lots=0.0,
                risk_dollars=0.0
            )

        # Gate 3: Spread Guardian
        if current_spread > self.max_spread:
            return TradeApproval(
                approved=False,
                reason=f"SPREAD_GUARD: Spread ${current_spread:.2f} > max allowed ${self.max_spread:.2f}.",
                recommended_lots=0.0,
                risk_dollars=0.0
            )

        # Gate 4: Stop loss distance sanity check
        sl_dist = abs(entry_price - stop_loss)
        if sl_dist <= 0.10:
            return TradeApproval(
                approved=False,
                reason=f"INVALID_SL: Stop loss distance ${sl_dist:.2f} too tight.",
                recommended_lots=0.0,
                risk_dollars=0.0
            )

        # Gate 5: Volatility-targeted sizing
        target_risk_dollars = account_equity * (self.risk_per_trade_pct / 100.0)
        # Risk = Lots * sl_dist * contract_size
        calculated_lots = target_risk_dollars / (sl_dist * self.contract_size)
        
        # Clamp to bounds and round to 2 decimals
        clamped_lots = round(max(self.min_lots, min(self.max_lots, calculated_lots)), 2)

        return TradeApproval(
            approved=True,
            reason="RISK_APPROVED",
            recommended_lots=clamped_lots,
            risk_dollars=round(clamped_lots * sl_dist * self.contract_size, 2)
        )
