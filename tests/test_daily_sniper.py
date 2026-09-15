"""
Daily Target Sniper Performance & Day-by-Day Audit.
Evaluates:
1. Daily Ratchet Governor execution (Kondisi 1, 2, 3, 4).
2. Daily return distribution: How many days hit >= 1.0% profit?
3. Trade selectivity: Filtered down from 135 trades to high-conviction sniper setups.
4. Total net profit, profit factor, and max drawdown.
"""

import sys
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from engine.core.event_engine import EventEngine
from engine.core.types import AccountConfig
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from strategies.incubator.xauusd_daily_sniper import XAUUSDDailySniper


def main():
    parquet_path = "data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet"
    df = pl.read_parquet(parquet_path)
    print(f"Loaded {len(df):,} M1 bars from {df['timestamp'].min()} to {df['timestamp'].max()}.")

    engine = EventEngine(
        config=AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0),
        commission_model=CommissionModel(7.0),
        slippage_model=FixedSlippageModel(0.02)
    )
    sniper = XAUUSDDailySniper(risk_reward_ratio=2.0, base_risk_pct=0.5, greed_risk_pct=0.25)

    res = engine.run_bars(df, sniper)
    perf = res["performance"]
    mc = res["monte_carlo"]
    trades = res["trades"]

    # Day-by-day analysis
    daily_trades = defaultdict(list)
    for t in trades:
        day_str = t.open_time.strftime("%Y-%m-%d (%A)")
        daily_trades[day_str].append(t)

    print("\n" + "=" * 85)
    print("XAUUSD DAILY SNIPER: DAY-BY-DAY INSTITUTIONAL AUDIT")
    print("=" * 85)
    print(f"{'Trading Day':<24} | {'Trades':<6} | {'W / L':<7} | {'Net PnL ($)':<12} | {'Return %':<10} | {'Status'}")
    print("-" * 85)

    days_hit_target = 0
    total_days = len(daily_trades)

    for day, tr_list in sorted(daily_trades.items()):
        wins = sum(1 for t in tr_list if t.net_pnl > 0)
        losses = sum(1 for t in tr_list if t.net_pnl <= 0)
        pnl = sum(t.net_pnl for t in tr_list)
        ret_pct = (pnl / 10000.0) * 100.0

        if ret_pct >= 1.0:
            status = "🎯 TARGET HIT (>= +1.0%)"
            days_hit_target += 1
        elif ret_pct > 0.0:
            status = "🟢 PROFITABLE DAY"
        elif ret_pct <= -1.0:
            status = "🛡️ 2-STRIKE CIRCUIT BREAKER"
        else:
            status = "⚪ NEUTRAL / CONTROLLED"

        print(f"{day:<24} | {len(tr_list):<6} | {wins}W/{losses}L   | {pnl:>+10.2f} $ | {ret_pct:>+7.2f} % | {status}")

    print("-" * 85)
    print(f"Overall Days Hitting >= 1.0%: {days_hit_target} of {total_days} days ({days_hit_target/total_days*100:.1f}%)" if total_days > 0 else "No trades")
    print(f"Total Trades: {perf.total_trades} (Averaging {perf.total_trades/max(1, total_days):.1f} trades/day)")
    print(f"Win Rate: {perf.win_rate_pct}% | Profit Factor: {perf.profit_factor:.2f}")
    print(f"Net Profit: ${perf.net_profit:,.2f} | Max DD: {perf.max_drawdown_pct:.2f}% | MC P95 DD: {mc.p95_max_drawdown_pct:.2f}%")
    print(f"Commissions Paid: ${perf.total_commission_paid:,.2f}")
    print("=" * 85)


if __name__ == "__main__":
    main()
