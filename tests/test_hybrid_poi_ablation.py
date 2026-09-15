"""
Ablation Study: Hybrid Session Anchored VWAP + HTF POI Confluence.
Evaluates 6 strategic variations over the full 10.5-month (300,440 M1 bars) dataset:

1. Baseline: VWAP +/- 1.8 Sigma (No POI filter, 08:00-16:00 UTC)
2. Scenario 1: VWAP + Smart Time-Filter (08:00-14:45 UTC, eliminating 15:00-16:00 UTC sinkhole)
3. Scenario 2: VWAP + HTF Order Block (OB) Confluence
4. Scenario 3: VWAP + HTF Inversion FVG (iFVG) Confluence
5. Scenario 4: VWAP + HTF Market Structure Bias (BOS / CHoCH)
6. Scenario 5: Full Institutional Confluence (Time Filter + Structure Bias + POI)
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

from strategies.incubator.strat_5_hybrid_vwap_poi import HybridVWAPPOIScalper


def run_single_simulation(df: pl.DataFrame, name: str, strategy: HybridVWAPPOIScalper):
    print(f"\n{'='*70}")
    print(f"🚀 Running Simulation: {name}")
    print(f"{'='*70}")
    t0 = time.time()

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

    rows = df.iter_rows(named=True)
    for bar in rows:
        engine.current_time = bar["timestamp"]
        spread = bar.get("mean_spread", 0.20)
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
    
    # Monthly PnL aggregation
    monthly_pnl = defaultdict(float)
    daily_pnl = defaultdict(float)
    for t in engine.closed_trades:
        m_str = t.open_time.strftime("%Y-%m")
        d_str = t.open_time.strftime("%Y-%m-%d")
        monthly_pnl[m_str] += t.net_pnl
        daily_pnl[d_str] += t.net_pnl

    profitable_months = sum(1 for v in monthly_pnl.values() if v > 0)
    total_months = len(monthly_pnl) or 1
    monthly_win_rate = (profitable_months / total_months) * 100

    print(f"⏱ Completed in {elapsed:.1f}s")
    print(f"📊 Trades: {perf.total_trades} | Win Rate: {perf.win_rate_pct:.1f}% | Payoff: {perf.win_loss_ratio:.2f}x")
    print(f"💰 Net PnL: ${perf.net_profit:+,.2f} | PF: {perf.profit_factor:.2f} | Max DD: {perf.max_drawdown_pct:.1f}%")
    print(f"📅 Monthly Consistency: {profitable_months}/{total_months} months profitable ({monthly_win_rate:.0f}%)")

    return {
        "name": name,
        "trades": perf.total_trades,
        "win_rate": perf.win_rate_pct,
        "payoff_ratio": perf.win_loss_ratio,
        "net_pnl": perf.net_profit,
        "profit_factor": perf.profit_factor,
        "max_dd_pct": perf.max_drawdown_pct,
        "profitable_months": f"{profitable_months}/{total_months}",
        "monthly_pnl": dict(monthly_pnl),
        "engine": engine
    }


def main():
    m1_path = "data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet"
    print(f"Loading M1 bars from {m1_path}...")
    df_m1 = pl.read_parquet(m1_path)
    print(f"Loaded {len(df_m1):,} bars.")

    scenarios = [
        (
            "0. Baseline VWAP +/- 1.8s (No POI, 08-16 UTC)",
            HybridVWAPPOIScalper(
                band_multiplier=1.8,
                enable_time_filter=False,
                require_ob_confluence=False,
                require_ifvg_confluence=False,
                require_structure_bias=False
            )
        ),
        (
            "1. VWAP + Time Filter (08:00-14:45 UTC, No 15:00 Sinkhole)",
            HybridVWAPPOIScalper(
                band_multiplier=1.8,
                enable_time_filter=True,
                require_ob_confluence=False,
                require_ifvg_confluence=False,
                require_structure_bias=False
            )
        ),
        (
            "2. VWAP + HTF Structure Bias (BOS/CHoCH)",
            HybridVWAPPOIScalper(
                band_multiplier=1.8,
                enable_time_filter=False,
                require_ob_confluence=False,
                require_ifvg_confluence=False,
                require_structure_bias=True
            )
        ),
        (
            "3. VWAP + Time Filter + HTF Structure Bias",
            HybridVWAPPOIScalper(
                band_multiplier=1.8,
                enable_time_filter=True,
                require_ob_confluence=False,
                require_ifvg_confluence=False,
                require_structure_bias=True
            )
        ),
        (
            "4. VWAP + Time Filter + HTF Order Block (OB)",
            HybridVWAPPOIScalper(
                band_multiplier=1.8,
                enable_time_filter=True,
                require_ob_confluence=True,
                require_ifvg_confluence=False,
                require_structure_bias=False,
                poi_buffer_dollars=1.50
            )
        ),
        (
            "5. VWAP + Time Filter + HTF iFVG / FVG Confluence",
            HybridVWAPPOIScalper(
                band_multiplier=1.8,
                enable_time_filter=True,
                require_ob_confluence=False,
                require_ifvg_confluence=True,
                require_structure_bias=False,
                poi_buffer_dollars=1.50
            )
        ),
    ]

    results = []
    for name, strat in scenarios:
        res = run_single_simulation(df_m1, name, strat)
        results.append(res)

    print("\n" + "="*80)
    print("🏆 ABLATION STUDY COMPARATIVE SCOREBOARD (10.5 MONTHS XAUUSD M1)")
    print("="*80)
    header = f"{'Configuration':<45} | {'Trades':<6} | {'Win%':<6} | {'Payoff':<6} | {'Net PnL':<11} | {'PF':<5} | {'MaxDD':<6} | {'Months'}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(f"{r['name']:<45} | {r['trades']:<6} | {r['win_rate']:>5.1f}% | {r['payoff_ratio']:>5.2f}x | ${r['net_pnl']:>10,.2f} | {r['profit_factor']:>4.2f} | {r['max_dd_pct']:>5.1f}% | {r['profitable_months']}")
    print("="*80)


if __name__ == "__main__":
    main()
