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
from strategies.incubator.strat_3_anchored_vwap import SessionAnchoredVWAPStrategy


def main():
    df = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")
    print(f"Testing optimizations on Strategy 3 (Anchored VWAP)...\n")

    for mult in [1.8, 2.0, 2.2, 2.5]:
        for rr in [1.8, 2.0, 2.5]:
            config = AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0)
            engine = EventEngine(config=config, commission_model=CommissionModel(7.0), slippage_model=FixedSlippageModel(0.02))
            strat = SessionAnchoredVWAPStrategy(
                band_multiplier=mult,
                sl_buffer_dollars=0.40,
                risk_reward_ratio=rr,
                base_risk_pct=0.5,
                greed_risk_pct=0.25,
                max_bars_hold=60
            )
            res = engine.run_bars(df, strat)
            perf = res["performance"]
            print(f"Band {mult}σ | RR 1:{rr} -> Trades: {perf.total_trades:<4} | Win: {perf.win_rate_pct:>4.1f}% | PF: {perf.profit_factor:>4.2f} | Net PnL: ${perf.net_profit:>+9.2f} | Max DD: {perf.max_drawdown_pct:>5.2f}%")


if __name__ == "__main__":
    main()
