"""
Institutional Performance Analytics Engine.
Calculates risk-adjusted returns, drawdown distributions, and expectancy metrics
in alignment with Lesson 8 & 9 institutional protocols.
"""

import math
from typing import List, Dict, Any, Optional
import numpy as np
import polars as pl
from dataclasses import dataclass, asdict

from engine.core.types import TradeRecord


@dataclass
class PerformanceSummary:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    
    initial_balance: float
    final_equity: float
    net_profit: float
    net_profit_pct: float
    gross_profit: float
    gross_loss: float
    profit_factor: float
    expectancy_usd: float
    
    avg_win_usd: float
    avg_loss_usd: float
    win_loss_ratio: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    
    max_drawdown_usd: float
    max_drawdown_pct: float
    
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    
    total_commission_paid: float
    total_slippage_paid: float
    avg_duration_minutes: float


class PerformanceCalculator:
    """
    Computes institutional performance summary from a list of closed TradeRecords
    and equity history curve.
    """
    @staticmethod
    def calculate(
        trades: List[TradeRecord],
        equity_curve: List[Dict[str, Any]],
        initial_balance: float = 10000.0,
        risk_free_rate: float = 0.04
    ) -> PerformanceSummary:
        if not trades:
            return PerformanceSummary(
                total_trades=0, winning_trades=0, losing_trades=0, win_rate_pct=0.0,
                initial_balance=initial_balance, final_equity=initial_balance,
                net_profit=0.0, net_profit_pct=0.0, gross_profit=0.0, gross_loss=0.0,
                profit_factor=0.0, expectancy_usd=0.0, avg_win_usd=0.0, avg_loss_usd=0.0,
                win_loss_ratio=0.0, max_consecutive_wins=0, max_consecutive_losses=0,
                max_drawdown_usd=0.0, max_drawdown_pct=0.0, sharpe_ratio=0.0,
                sortino_ratio=0.0, calmar_ratio=0.0, total_commission_paid=0.0,
                total_slippage_paid=0.0, avg_duration_minutes=0.0
            )

        pnls = np.array([t.net_pnl for t in trades], dtype=np.float64)
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]

        total_trades = len(trades)
        winning_trades = len(wins)
        losing_trades = len(losses)
        win_rate_pct = round((winning_trades / total_trades) * 100.0, 2)

        gross_profit = float(np.sum(wins)) if len(wins) > 0 else 0.0
        gross_loss = abs(float(np.sum(losses))) if len(losses) > 0 else 0.0
        net_profit = gross_profit - gross_loss
        net_profit_pct = round((net_profit / initial_balance) * 100.0, 2)

        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
        expectancy_usd = round(float(np.mean(pnls)), 2)

        avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
        avg_loss = abs(float(np.mean(losses))) if len(losses) > 0 else 0.0
        win_loss_ratio = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0.0

        # Consecutive streaks
        max_cw = 0
        max_cl = 0
        cur_cw = 0
        cur_cl = 0
        for pnl in pnls:
            if pnl > 0:
                cur_cw += 1
                cur_cl = 0
                max_cw = max(max_cw, cur_cw)
            elif pnl < 0:
                cur_cl += 1
                cur_cw = 0
                max_cl = max(max_cl, cur_cl)
            else:
                cur_cw = 0
                cur_cl = 0

        # Drawdown calculation from equity curve
        equities = np.array([pt["equity"] for pt in equity_curve], dtype=np.float64) if equity_curve else np.array([initial_balance + np.cumsum(pnls)])
        if len(equities) == 0:
            equities = np.array([initial_balance])

        running_max = np.maximum.accumulate(equities)
        drawdowns = running_max - equities
        drawdown_pcts = (drawdowns / running_max) * 100.0

        max_dd_usd = round(float(np.max(drawdowns)), 2) if len(drawdowns) > 0 else 0.0
        max_dd_pct = round(float(np.max(drawdown_pcts)), 2) if len(drawdown_pcts) > 0 else 0.0

        final_equity = float(equities[-1])

        # Risk-adjusted ratios (Sharpe, Sortino)
        # Calculate returns based on trade returns
        trade_returns = pnls / initial_balance
        rf_per_trade = risk_free_rate / 252.0  # Approx daily risk free rate
        excess_returns = trade_returns - rf_per_trade

        mean_ret = np.mean(excess_returns)
        std_ret = np.std(trade_returns)
        sharpe_ratio = round(float((mean_ret / std_ret) * math.sqrt(252)), 2) if std_ret > 1e-6 else 0.0

        downside_returns = trade_returns[trade_returns < 0]
        downside_std = np.std(downside_returns) if len(downside_returns) > 1 else 0.0
        sortino_ratio = round(float((mean_ret / downside_std) * math.sqrt(252)), 2) if downside_std > 1e-6 else 0.0

        calmar_ratio = round(net_profit_pct / max_dd_pct, 2) if max_dd_pct > 0 else 0.0

        total_commission = round(float(sum(t.commission for t in trades)), 2)
        total_slippage = round(float(sum(t.slippage for t in trades)), 2)
        avg_duration = round(float(np.mean([t.duration_seconds for t in trades])) / 60.0, 2)

        return PerformanceSummary(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate_pct=win_rate_pct,
            initial_balance=initial_balance,
            final_equity=round(final_equity, 2),
            net_profit=round(net_profit, 2),
            net_profit_pct=net_profit_pct,
            gross_profit=round(gross_profit, 2),
            gross_loss=round(gross_loss, 2),
            profit_factor=profit_factor,
            expectancy_usd=expectancy_usd,
            avg_win_usd=round(avg_win, 2),
            avg_loss_usd=round(avg_loss, 2),
            win_loss_ratio=win_loss_ratio,
            max_consecutive_wins=max_cw,
            max_consecutive_losses=max_cl,
            max_drawdown_usd=max_dd_usd,
            max_drawdown_pct=max_dd_pct,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            calmar_ratio=calmar_ratio,
            total_commission_paid=total_commission,
            total_slippage_paid=total_slippage,
            avg_duration_minutes=avg_duration
        )
