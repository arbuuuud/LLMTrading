"""
Institutional 10.5-Month SMT Asia Sweep Sniper Audit.
Simulates XAUUSDSMTSweepSniper using aligned Gold and Silver data
across the entire dataset (297,946 synchronized M1 bars).
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
from strategies.incubator.xauusd_smt_asia_sweep import XAUUSDSMTSweepSniper


def main():
    print("Loading Synchronized Datasets...")
    df_gold = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")
    df_silver = pl.read_parquet("data/processed/bars/XAGUSD/M1/XAGUSD_M1.parquet")

    aligned = df_gold.select([
        pl.col("timestamp"),
        pl.col("open").alias("gold_open"),
        pl.col("high").alias("gold_high"),
        pl.col("low").alias("gold_low"),
        pl.col("close").alias("gold_close"),
        pl.col("mean_spread").alias("gold_spread")
    ]).join(
        df_silver.select([
            pl.col("timestamp"),
            pl.col("open").alias("silver_open"),
            pl.col("high").alias("silver_high"),
            pl.col("low").alias("silver_low"),
            pl.col("close").alias("silver_close")
        ]),
        on="timestamp",
        how="inner"
    ).sort("timestamp")

    print(f"Loaded {len(aligned):,} synchronized M1 bars ({aligned['timestamp'].min()} to {aligned['timestamp'].max()}).\n")

    config = AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0)
    engine = EventEngine(
        config=config,
        commission_model=CommissionModel(7.0),
        slippage_model=FixedSlippageModel(0.02)
    )
    strategy = XAUUSDSMTSweepSniper(
        min_sweep_dollars=0.80,
        min_sl_distance=2.00,
        sl_buffer_dollars=0.50,
        risk_reward_ratio=2.5,
        base_risk_pct=0.5,
        greed_risk_pct=0.25,
        max_bars_hold=150
    )

    engine.reset()
    engine.current_strategy = strategy
    strategy.set_engine(engine)
    strategy.on_init()

    print("[SMT Asia Sweep Engine] Simulating execution across 10.5 months...")
    for row in aligned.iter_rows(named=True):
        engine.current_time = row["timestamp"]
        spread = row.get("gold_spread", 0.20)
        engine.current_bid = row["gold_close"]
        engine.current_ask = round(engine.current_bid + spread, 3)
        engine.current_spread = spread

        engine._check_daily_circuit_breaker(engine.current_time)

        gold_bar = {
            "timestamp": row["timestamp"],
            "open": row["gold_open"],
            "high": row["gold_high"],
            "low": row["gold_low"],
            "close": row["gold_close"],
            "mean_spread": spread
        }
        engine._update_positions_on_bar(gold_bar)

        silver_bar = {
            "timestamp": row["timestamp"],
            "open": row["silver_open"],
            "high": row["silver_high"],
            "low": row["silver_low"],
            "close": row["silver_close"]
        }

        strategy.on_bar_intermarket(gold_bar, silver_bar, None)

        engine.equity_curve.append({
            "timestamp": engine.current_time,
            "equity": round(engine.equity, 2),
            "balance": round(engine.balance, 2)
        })

    for pos_id in list(engine.positions.keys()):
        engine._close_position_internal(pos_id, ExitReason.END_OF_DATA)

    strategy.on_finish()

    perf = PerformanceCalculator.calculate(engine.closed_trades, engine.equity_curve, config.initial_balance)
    mc_sim = MonteCarloSimulator(num_simulations=1000)
    mc = mc_sim.run(engine.closed_trades, config.initial_balance)

    daily_trades = defaultdict(list)
    for t in engine.closed_trades:
        day_str = t.open_time.strftime("%Y-%m-%d (%A)")
        daily_trades[day_str].append(t)

    print("\n" + "=" * 85)
    print("XAUUSD SMT ASIA SWEEP SNIPER: 10.5-MONTH AUDIT")
    print("=" * 85)
    days_hit = 0
    profitable_days = 0
    total_days = len(daily_trades)

    for day, tr_list in sorted(daily_trades.items()):
        wins = sum(1 for t in tr_list if t.net_pnl > 0)
        losses = sum(1 for t in tr_list if t.net_pnl <= 0)
        pnl = sum(t.net_pnl for t in tr_list)
        ret_pct = (pnl / 10000.0) * 100.0

        if ret_pct >= 1.0:
            status = "🎯 TARGET HIT (>= +1.0%)"
            days_hit += 1
            profitable_days += 1
        elif ret_pct > 0.0:
            status = "🟢 PROFITABLE DAY"
            profitable_days += 1
        elif ret_pct <= -1.0:
            status = "🛡️ 2-STRIKE CIRCUIT BREAKER"
        else:
            status = "⚪ NEUTRAL / CONTROLLED"

        print(f"{day:<24} | {len(tr_list):<6} | {wins}W/{losses}L   | {pnl:>+10.2f} $ | {ret_pct:>+7.2f} % | {status}")

    print("-" * 85)
    win_days_pct = (profitable_days / total_days * 100) if total_days > 0 else 0
    print(f"Total Active Trading Days: {total_days} days")
    print(f"Profitable Days: {profitable_days} of {total_days} ({win_days_pct:.1f}%)")
    print(f"Days Hitting >= +1.0%: {days_hit} of {total_days} ({days_hit/max(1, total_days)*100:.1f}%)")
    print(f"Total Trades: {perf.total_trades} (Averaging {perf.total_trades/max(1, total_days):.1f} trades/day)")
    print(f"Win Rate: {perf.win_rate_pct}% | Profit Factor: {perf.profit_factor:.2f}")
    print(f"Net Profit: ${perf.net_profit:,.2f} | Max DD: {perf.max_drawdown_pct:.2f}% | MC P95 DD: {mc.p95_max_drawdown_pct:.2f}%")
    print(f"Commissions Paid: ${perf.total_commission_paid:,.2f}")
    print("=" * 85)


if __name__ == "__main__":
    main()
