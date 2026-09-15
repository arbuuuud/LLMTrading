"""
Test Runner for the 20% Monthly Target Ratchet Strategy across 10.5 months.
"""

import sys
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from engine.core.event_engine import EventEngine
from engine.core.types import AccountConfig, ExitReason
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from engine.metrics.performance import PerformanceCalculator
from engine.monte_carlo.simulator import MonteCarloSimulator
from strategies.incubator.xauusd_monthly_20pct_ratchet import XAUUSDMonthly20PctRatchet


def main():
    print("Loading Full 10.5-Month Dataset (300,440 M1 bars)...")
    df = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")

    config = AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0)
    engine = EventEngine(
        config=config,
        commission_model=CommissionModel(7.0),
        slippage_model=FixedSlippageModel(0.02)
    )
    strategy = XAUUSDMonthly20PctRatchet(
        risk_reward_ratio=2.5,
        atr_sl_multiplier=1.2,
        base_risk_pct=0.5,
        greed_risk_pct=0.25,
        max_bars_hold=45
    )

    print("[Ratchet Engine] Simulating execution with Profit Bottoming Lock & Monthly Circuit Breaker...")
    res = engine.run_bars(df, strategy)
    perf = res["performance"]
    mc = res["monte_carlo"]
    trades = res["trades"]

    monthly_trades = defaultdict(list)
    for t in trades:
        mo_str = t.open_time.strftime("%Y-%m")
        monthly_trades[mo_str].append(t)

    print("\n" + "=" * 80)
    print("XAUUSD 20% MONTHLY TARGET RATCHET STRATEGY: 10.5-MONTH AUDIT")
    print("=" * 80)
    print(f"{'Month':<10} | {'Trades':<7} | {'Win %':<6} | {'Net PnL ($)':<12} | {'Monthly Return':<14} | {'Status'}")
    print("-" * 80)

    green_months = 0
    target_months = 0
    total_months = len(monthly_trades)

    for mo, tr_list in sorted(monthly_trades.items()):
        wins = sum(1 for t in tr_list if t.net_pnl > 0)
        tot = len(tr_list)
        wr = (wins / tot * 100) if tot > 0 else 0
        pnl = sum(t.net_pnl for t in tr_list)
        ret_pct = (pnl / 10000.0) * 100.0

        if ret_pct >= 10.0:
            status = "🚀 MASSIVE RETURN (>= +10%)"
            target_months += 1
            green_months += 1
        elif ret_pct >= 5.0:
            status = "🎯 HIGH RETURN (>= +5%)"
            target_months += 1
            green_months += 1
        elif ret_pct > 0.0:
            status = "🟢 PROFITABLE MONTH"
            green_months += 1
        elif ret_pct <= -3.0:
            status = "🛡️ MONTHLY CIRCUIT BREAKER (-3% CAP)"
        else:
            status = "⚪ CONTROLLED"

        print(f"{mo:<10} | {tot:<7} | {wr:>5.1f}% | {pnl:>+10.2f} $ | {ret_pct:>+12.2f} % | {status}")

    print("-" * 80)
    win_mo_pct = (green_months / total_months * 100) if total_months > 0 else 0
    print(f"Profitable Months: {green_months} of {total_months} months ({win_mo_pct:.1f}%)")
    print(f"Total Trades: {perf.total_trades} (Averaging {perf.total_trades/max(1, total_months):.1f} trades/month)")
    print(f"Win Rate: {perf.win_rate_pct:.1f}% | Profit Factor: {perf.profit_factor:.2f}")
    print(f"Total Net PnL: ${perf.net_profit:,.2f} | Max Drawdown: {perf.max_drawdown_pct:.2f}% | MC P95 DD: {mc.p95_max_drawdown_pct:.2f}%")
    print(f"Commissions Paid: ${perf.total_commission_paid:,.2f}")
    print("=" * 80)


if __name__ == "__main__":
    main()
