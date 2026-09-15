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
from strategies.incubator.xauusd_trend_pullback_scalper import XAUUSDTrendPullbackScalper


def main():
    df = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")
    print(f"Loaded {len(df):,} M1 bars.")

    for rr in [1.8, 2.0, 2.2, 2.5]:
        engine = EventEngine(
            config=AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0),
            commission_model=CommissionModel(7.0),
            slippage_model=FixedSlippageModel(0.02)
        )
        strat = XAUUSDTrendPullbackScalper(risk_reward_ratio=rr, max_bars_hold=25)
        res = engine.run_bars(df, strat)
        perf = res["performance"]
        mc = res["monte_carlo"]
        print(f"\n--- Strategy: XAUUSD Trend Pullback (R:R 1:{rr}) ---")
        print(f"Trades: {perf.total_trades} | Win Rate: {perf.win_rate_pct}% | Profit Factor: {perf.profit_factor}")
        print(f"Net PnL: ${perf.net_profit:,.2f} | Max DD: {perf.max_drawdown_pct}% | Sharpe: {perf.sharpe_ratio}")
        print(f"Commissions: ${perf.total_commission_paid:,.2f} | MC P95 Max DD: {mc.p95_max_drawdown_pct}%")


if __name__ == "__main__":
    main()
