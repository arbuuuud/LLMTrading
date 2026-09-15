"""
Institutional Comparison & Audit:
Anchored VWAP 1.8 Sigma Alone vs Hybrid Super-Alpha (VWAP + SMT Silver Confluence).
Runs across the complete 297,946 synchronized M1 bar dataset (10.5 months).
"""

import sys
import time
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

from strategies.incubator.strat_4_hybrid_vwap_smt import HybridVWAPSMTStrategy


def run_hybrid_test(aligned_df: pl.DataFrame, name: str, require_smt: bool):
    print(f"\n[Audit Engine] Running: {name} (Require SMT: {require_smt})...")
    t0 = time.time()

    config = AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0)
    engine = EventEngine(
        config=config,
        commission_model=CommissionModel(7.0),
        slippage_model=FixedSlippageModel(0.02)
    )
    strategy = HybridVWAPSMTStrategy(
        gold_band_mult=1.8,
        silver_band_mult=1.5,
        sl_buffer_dollars=0.40,
        risk_reward_ratio=2.0,
        base_risk_pct=0.5,
        greed_risk_pct=0.25,
        max_bars_hold=60,
        require_smt_confluence=require_smt
    )

    engine.reset()
    engine.current_strategy = strategy
    strategy.set_engine(engine)
    strategy.on_init()

    rows = aligned_df.iter_rows(named=True)
    for row in rows:
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
    elapsed = time.time() - t0

    perf = PerformanceCalculator.calculate(engine.closed_trades, engine.equity_curve, config.initial_balance)
    mc_sim = MonteCarloSimulator(num_simulations=500)
    mc = mc_sim.run(engine.closed_trades, config.initial_balance)

    daily_trades = defaultdict(list)
    monthly_pnl = defaultdict(float)

    for t in engine.closed_trades:
        day_str = t.open_time.strftime("%Y-%m-%d")
        daily_trades[day_str].append(t)
        mo_str = t.open_time.strftime("%Y-%m")
        monthly_pnl[mo_str] += t.net_pnl

    total_days = len(daily_trades)
    profitable_days = 0
    target_1pct_days = 0

    for d, trs in daily_trades.items():
        day_pnl = sum(t.net_pnl for t in trs)
        if day_pnl >= 100.0:
            target_1pct_days += 1
            profitable_days += 1
        elif day_pnl > 0.0:
            profitable_days += 1

    return {
        "name": name,
        "elapsed_sec": elapsed,
        "trades": perf.total_trades,
        "win_rate": perf.win_rate_pct,
        "profit_factor": perf.profit_factor,
        "net_pnl": perf.net_profit,
        "return_pct": (perf.net_profit / 10000.0) * 100.0,
        "max_dd_pct": perf.max_drawdown_pct,
        "mc_p95_dd": mc.p95_max_drawdown_pct,
        "commissions": perf.total_commission_paid,
        "active_days": total_days,
        "profitable_days": profitable_days,
        "target_1pct_days": target_1pct_days,
        "monthly_pnl": dict(monthly_pnl)
    }


def main():
    print("Loading Synchronized Gold & Silver Datasets...")
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

    print(f"Loaded {len(aligned):,} synchronized M1 bars ({aligned['timestamp'].min()} to {aligned['timestamp'].max()})\n")

    res_baseline = run_hybrid_test(aligned, "1. Anchored VWAP 1.8σ (Without SMT)", require_smt=False)
    res_hybrid = run_hybrid_test(aligned, "2. HYBRID SUPER-ALPHA (VWAP + SMT Silver)", require_smt=True)

    print("\n" + "=" * 105)
    print("HYBRID SUPER-ALPHA HEAD-TO-HEAD AUDIT (10.5 MONTHS / 297,946 BARS)")
    print("=" * 105)
    header = f"{'Configuration':<42} | {'Trades':<6} | {'Win %':<6} | {'PF':<5} | {'Net PnL ($)':<12} | {'Max DD %':<8} | {'Days >=1%'}"
    print(header)
    print("-" * 105)

    for r in [res_baseline, res_hybrid]:
        line = (
            f"{r['name']:<42} | "
            f"{r['trades']:<6} | "
            f"{r['win_rate']:>5.1f}% | "
            f"{r['profit_factor']:>5.2f} | "
            f"{r['net_pnl']:>11.2f} $ | "
            f"{r['max_dd_pct']:>7.2f}% | "
            f"{r['target_1pct_days']}"
        )
        print(line)

    print("-" * 105)
    delta_pnl = res_hybrid['net_pnl'] - res_baseline['net_pnl']
    delta_pf = res_hybrid['profit_factor'] - res_baseline['profit_factor']
    delta_dd = res_hybrid['max_dd_pct'] - res_baseline['max_dd_pct']
    print(f"DELTA ATTRIBUTION (Adding SMT Confluence to VWAP):")
    print(f"  • Δ Net Profit:   ${delta_pnl:+,.2f} ({'+' if delta_pnl > 0 else ''}{(delta_pnl/10000)*100:.2f}%)")
    print(f"  • Δ Profit Factor: {delta_pf:+.2f}")
    print(f"  • Δ Max Drawdown:  {delta_dd:+.2f}%")
    print("=" * 105)


if __name__ == "__main__":
    main()
