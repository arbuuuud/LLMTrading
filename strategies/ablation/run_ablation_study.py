"""
Institutional Ablation Study & Delta Attribution Experiment.
Compares baseline strategy against incremental feature additions:
1. Baseline: Asia Sweep + M1 CHoCH
2. + Time-based Exit Guard
3. + Candlestick Rejection Pattern (Engulfing / Pinbar)
4. + Higher Timeframe (HTF M15) Point of Interest
5. Full Confluence (All active)
"""

import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from typing import Dict, Any, List
import polars as pl

from engine.core.event_engine import EventEngine
from engine.core.types import AccountConfig
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from strategies.incubator.xauusd_liquidity_smc_scout import XAUUSDLiquiditySMCScout


def run_single_test(
    df_bars: pl.DataFrame,
    name: str,
    strategy: XAUUSDLiquiditySMCScout
) -> Dict[str, Any]:
    config = AccountConfig(
        initial_balance=10000.0,
        commission_per_lot_round_turn=7.0,
        contract_size=100.0
    )
    engine = EventEngine(
        config=config,
        commission_model=CommissionModel(7.0),
        slippage_model=FixedSlippageModel(0.02)
    )

    res = engine.run_bars(df_bars, strategy)
    perf = res["performance"]
    mc = res["monte_carlo"]

    return {
        "name": name,
        "trades": perf.total_trades,
        "win_rate": perf.win_rate_pct,
        "profit_factor": perf.profit_factor,
        "net_pnl": perf.net_profit,
        "max_dd_pct": perf.max_drawdown_pct,
        "sharpe": perf.sharpe_ratio,
        "mc_p95_dd": mc.p95_max_drawdown_pct,
        "mc_ruin_prob": mc.probability_of_ruin_pct,
        "commissions": perf.total_commission_paid
    }


def main():
    parquet_path = "data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet"
    print(f"Loading data from {parquet_path}...")
    df = pl.read_parquet(parquet_path)
    print(f"Loaded {len(df):,} M1 bars ({df['timestamp'].min()} to {df['timestamp'].max()})\n")

    experiments = [
        (
            "1. Baseline (Sweep + FVG Trigger)",
            XAUUSDLiquiditySMCScout(
                use_htf_poi=False,
                use_candle_pattern=False,
                use_choch_confirmation=False,
                use_fvg_trigger=True,
                use_time_exit=False,
                risk_reward_ratio=1.5
            )
        ),
        (
            "2. Baseline + Time Exit (20 bars)",
            XAUUSDLiquiditySMCScout(
                use_htf_poi=False,
                use_candle_pattern=False,
                use_choch_confirmation=False,
                use_fvg_trigger=True,
                use_time_exit=True,
                max_bars_hold=20,
                risk_reward_ratio=1.5
            )
        ),
        (
            "3. Sweep + Candlestick (Engulf/Pinbar)",
            XAUUSDLiquiditySMCScout(
                use_htf_poi=False,
                use_candle_pattern=True,
                use_choch_confirmation=False,
                use_fvg_trigger=False,
                use_time_exit=True,
                max_bars_hold=20,
                risk_reward_ratio=1.5
            )
        ),
        (
            "4. Sweep + CHoCH Confirmation",
            XAUUSDLiquiditySMCScout(
                use_htf_poi=False,
                use_candle_pattern=False,
                use_choch_confirmation=True,
                use_fvg_trigger=False,
                use_time_exit=True,
                max_bars_hold=20,
                risk_reward_ratio=1.5
            )
        ),
        (
            "5. Dual Confluence (FVG + Candle)",
            XAUUSDLiquiditySMCScout(
                use_htf_poi=False,
                use_candle_pattern=True,
                use_choch_confirmation=False,
                use_fvg_trigger=True,
                use_time_exit=True,
                max_bars_hold=20,
                risk_reward_ratio=1.5
            )
        ),
    ]

    results: List[Dict[str, Any]] = []

    for name, strat in experiments:
        print(f"Running Experiment: {name}...")
        res = run_single_test(df, name, strat)
        results.append(res)

    baseline = results[0]

    print("\n" + "=" * 90)
    print("INSTITUTIONAL ABLATION STUDY RESULTS (XAUUSD M1)")
    print("=" * 90)
    header = f"{'Configuration':<38} | {'Trades':<6} | {'Win %':<6} | {'PF':<6} | {'Net PnL ($)':<11} | {'Max DD %':<8} | {'MC P95 DD':<9}"
    print(header)
    print("-" * 90)

    for r in results:
        line = (
            f"{r['name']:<38} | "
            f"{r['trades']:<6} | "
            f"{r['win_rate']:>5.1f}% | "
            f"{r['profit_factor']:>6.2f} | "
            f"{r['net_pnl']:>11.2f} | "
            f"{r['max_dd_pct']:>7.2f}% | "
            f"{r['mc_p95_dd']:>8.2f}%"
        )
        print(line)

    print("-" * 90)
    print("DELTA ATTRIBUTION (vs Baseline):")
    for r in results[1:]:
        delta_pf = r['profit_factor'] - baseline['profit_factor']
        delta_win = r['win_rate'] - baseline['win_rate']
        delta_dd = r['max_dd_pct'] - baseline['max_dd_pct']
        delta_pnl = r['net_pnl'] - baseline['net_pnl']
        print(f" • {r['name']:<35} -> ΔPF: {delta_pf:+.2f} | ΔWin: {delta_win:+.1f}% | ΔDD: {delta_dd:+.2f}% | ΔPnL: ${delta_pnl:+,.2f}")
    print("=" * 90)


if __name__ == "__main__":
    main()
