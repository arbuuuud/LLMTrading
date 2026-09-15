"""
Audit & Backtest for Priority 2: Strategy 6 - Intraday SMC Expansion Sniper.
Compares M15 vs M5 execution horizons on 10.5 months of data.
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
from strategies.incubator.strat_6_intraday_smc import IntradaySMCStrategy


def run_test(parquet_path: str, timeframe_label: str):
    print(f"\n--- Running on {timeframe_label} ({parquet_path}) ---")
    df = pl.read_parquet(parquet_path)

    t0 = time.time()
    strategy = IntradaySMCStrategy(
        base_risk_pct=0.50,
        tp1_r=1.5,
        tp2_r=4.0,
        sl_buffer_dollars=1.20,
        poi_tolerance_dollars=0.80
    )

    config = AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0)
    engine = EventEngine(
        config=config,
        commission_model=CommissionModel(7.0),
        slippage_model=FixedSlippageModel(0.02)
    )
    engine.reset()
    engine.current_strategy = strategy
    strategy.set_engine(engine)
    strategy.on_init()

    for bar in df.iter_rows(named=True):
        engine.current_time = bar["timestamp"]
        spread = bar.get("mean_spread", 0.25)
        engine.current_bid = bar["close"]
        engine.current_ask = round(engine.current_bid + spread, 3)
        engine.current_spread = spread

        engine._check_daily_circuit_breaker(engine.current_time)
        engine._update_positions_on_bar(bar)

        strategy.on_bar(bar)

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

    monthly_pnl = defaultdict(float)
    for tr in engine.closed_trades:
        monthly_pnl[tr.open_time.strftime("%Y-%m")] += tr.net_pnl

    pos_m = sum(1 for v in monthly_pnl.values() if v > 0)
    tot_m = len(monthly_pnl) or 1

    print(f"⏱ Time: {elapsed:.2f}s | Trades: {perf.total_trades} | Win: {perf.win_rate_pct:.1f}% | Payoff: {perf.win_loss_ratio:.2f}x | Net: ${perf.net_profit:+,.2f} | PF: {perf.profit_factor:.2f} | DD: {perf.max_drawdown_pct:.1f}% | Months: {pos_m}/{tot_m}")
    return perf


def main():
    run_test("data/processed/bars/XAUUSD/HTF/XAUUSD_M15.parquet", "M15 Horizon")
    run_test("data/processed/bars/XAUUSD/HTF/XAUUSD_M5.parquet", "M5 Horizon")


if __name__ == "__main__":
    main()
