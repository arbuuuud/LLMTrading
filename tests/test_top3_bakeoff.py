"""
Top 3 Institutional XAUUSD Strategies Bake-Off & Full 10.5-Month Comparative Audit.
Runs Strategy 1, Strategy 2, and Strategy 3 on the complete 300,440 M1 bar dataset
to empirically determine which one is the most consistently profitable:

1. Strategy 1: The London Open "Judas Swing" (London Trap Scalper)
2. Strategy 2: The ICT "Silver Bullet" (60-minute NY Killzone Sniper)
3. Strategy 3: Session Anchored VWAP +/- 2.0 Sigma Mean Reversion (Auction Market Theory)
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

from strategies.incubator.strat_1_judas_swing import LondonJudasSwingStrategy
from strategies.incubator.strat_2_silver_bullet import ICTSilverBulletStrategy
from strategies.incubator.strat_3_anchored_vwap import SessionAnchoredVWAPStrategy


def run_strategy_audit(df: pl.DataFrame, name: str, strategy):
    print(f"\n[Audit Engine] Running simulation for: {name}...")
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
    mc_sim = MonteCarloSimulator(num_simulations=500)
    mc = mc_sim.run(engine.closed_trades, config.initial_balance)

    # Day-by-day stats
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

    green_months = sum(1 for p in monthly_pnl.values() if p > 0)
    total_months = len(monthly_pnl)

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
        "green_months": green_months,
        "total_months": total_months,
        "monthly_pnl": dict(monthly_pnl)
    }


def main():
    parquet_path = "data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet"
    print(f"Loading full dataset: {parquet_path}...")
    df = pl.read_parquet(parquet_path)
    print(f"Loaded {len(df):,} M1 bars ({df['timestamp'].min()} to {df['timestamp'].max()})\n")

    strategies_to_test = [
        (
            "1. London Open 'Judas Swing'",
            LondonJudasSwingStrategy(
                min_sweep_dollars=0.50,
                max_sweep_dollars=3.50,
                sl_buffer_dollars=0.40,
                risk_reward_ratio=2.0,
                base_risk_pct=0.5,
                greed_risk_pct=0.25,
                max_bars_hold=90
            )
        ),
        (
            "2. ICT 'Silver Bullet' (60m Window)",
            ICTSilverBulletStrategy(
                fvg_min_size=0.25,
                sl_buffer_dollars=0.35,
                risk_reward_ratio=2.0,
                base_risk_pct=0.5,
                greed_risk_pct=0.25,
                max_bars_hold=40
            )
        ),
        (
            "3. Anchored VWAP +/- 2.0 Sigma Fade",
            SessionAnchoredVWAPStrategy(
                band_multiplier=2.0,
                sl_buffer_dollars=0.40,
                risk_reward_ratio=2.0,
                base_risk_pct=0.5,
                greed_risk_pct=0.25,
                max_bars_hold=60
            )
        )
    ]

    results = []
    for name, strat in strategies_to_test:
        res = run_strategy_audit(df, name, strat)
        results.append(res)

    print("\n" + "=" * 105)
    print("TOP 3 INSTITUTIONAL STRATEGIES: FULL 10.5-MONTH BAKE-OFF COMPARISON")
    print("=" * 105)
    header = f"{'Strategy Name':<35} | {'Trades':<6} | {'Win %':<6} | {'PF':<5} | {'Net PnL ($)':<12} | {'Max DD %':<8} | {'Green Days':<12} | {'Days >=1%'}"
    print(header)
    print("-" * 105)

    for r in results:
        day_ratio = f"{r['profitable_days']}/{r['active_days']} ({(r['profitable_days']/max(1, r['active_days'])*100):.1f}%)"
        line = (
            f"{r['name']:<35} | "
            f"{r['trades']:<6} | "
            f"{r['win_rate']:>5.1f}% | "
            f"{r['profit_factor']:>5.2f} | "
            f"{r['net_pnl']:>11.2f} $ | "
            f"{r['max_dd_pct']:>7.2f}% | "
            f"{day_ratio:<12} | "
            f"{r['target_1pct_days']}"
        )
        print(line)

    print("-" * 105)
    print("\nMONTHLY BREAKDOWN:")
    all_months = sorted(list(set(m for r in results for m in r['monthly_pnl'].keys())))
    print(f"{'Month':<10} | " + " | ".join(f"{r['name'][:22]:<22}" for r in results))
    print("-" * 85)
    for mo in all_months:
        cols = []
        for r in results:
            val = r['monthly_pnl'].get(mo, 0.0)
            cols.append(f"{val:>+10.2f} $ ({'+' if val>0 else ''}{(val/10000)*100:.1f}%)")
        print(f"{mo:<10} | " + " | ".join(cols))
    print("=" * 105)


if __name__ == "__main__":
    main()
