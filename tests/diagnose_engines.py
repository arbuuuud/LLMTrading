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
from strategies.incubator.xauusd_dual_engine_sniper import XAUUSDDualEngineSniper


def main():
    df = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")
    engine = EventEngine(config=AccountConfig(), commission_model=CommissionModel(7.0), slippage_model=FixedSlippageModel(0.02))
    strat = XAUUSDDualEngineSniper()
    res = engine.run_bars(df, strat)
    trades = res["trades"]

    trend_trades = [t for t in trades if t.tag == "Trend_Engine"]
    range_trades = [t for t in trades if t.tag == "Range_Engine"]

    def summarize(name, tr_list):
        n = len(tr_list)
        if n == 0:
            return
        wins = [t for t in tr_list if t.net_pnl > 0]
        wr = len(wins) / n * 100
        pnl = sum(t.net_pnl for t in tr_list)
        comm = sum(t.commission for t in tr_list)
        gross_win = sum(t.gross_pnl for t in wins)
        gross_loss = abs(sum(t.gross_pnl for t in tr_list if t.net_pnl <= 0))
        pf = gross_win / gross_loss if gross_loss > 0 else 0
        print(f"=== {name} ===")
        print(f"Trades: {n} | Win Rate: {wr:.1f}% | PF: {pf:.2f}")
        print(f"Gross PnL: ${gross_win - gross_loss:,.2f} | Net PnL: ${pnl:,.2f} | Comm: ${comm:,.2f}\n")

    summarize("ENGINE A: TREND PULLBACK", trend_trades)
    summarize("ENGINE B: RANGE LIQUIDITY SWEEP", range_trades)


if __name__ == "__main__":
    main()
