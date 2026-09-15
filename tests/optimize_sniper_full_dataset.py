"""
Full 10.5-Month Parameter Stability Test for XAUUSD Daily Sniper.
Tests variations of Risk:Reward, Impulse Ratios, and Holding Periods across
the full 300,440 M1 bars (10.5 months).
"""

import sys
from pathlib import Path

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
    df = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")
    print(f"Loaded {len(df):,} M1 bars across 10.5 months.\n")

    experiments = [
        {"rr": 1.6, "hold": 25, "buf": 0.35},
        {"rr": 1.8, "hold": 25, "buf": 0.35},
        {"rr": 1.8, "hold": 30, "buf": 0.45},
        {"rr": 1.8, "hold": 30, "buf": 0.55},
        {"rr": 2.0, "hold": 30, "buf": 0.50},
        {"rr": 2.0, "hold": 35, "buf": 0.60},
    ]

    print(f"{'Config':<32} | {'Trades':<6} | {'Win %':<6} | {'PF':<6} | {'Net PnL ($)':<12} | {'Max DD %':<8} | {'MC P95 DD':<9}")
    print("-" * 88)

    for exp in experiments:
        engine = EventEngine(
            config=AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0),
            commission_model=CommissionModel(7.0),
            slippage_model=FixedSlippageModel(0.02)
        )
        strat = XAUUSDDailySniper(
            risk_reward_ratio=exp["rr"],
            sl_buffer_dollars=exp["buf"],
            max_bars_hold=exp["hold"],
            base_risk_pct=0.5,
            greed_risk_pct=0.25
        )
        res = engine.run_bars(df, strat)
        perf = res["performance"]
        mc = res["monte_carlo"]

        name = f"RR 1:{exp['rr']} (Hold {exp['hold']}b, Buf ${exp['buf']})"
        print(
            f"{name:<32} | {perf.total_trades:<6} | {perf.win_rate_pct:>5.1f}% | "
            f"{perf.profit_factor:>5.2f} | {perf.net_profit:>11.2f} $ | "
            f"{perf.max_drawdown_pct:>7.2f}% | {mc.p95_max_drawdown_pct:>8.2f}%"
        )


if __name__ == "__main__":
    main()
