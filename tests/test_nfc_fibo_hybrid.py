"""
Hybrid Synthesis: Fadli NFC Unfilled Orders + Fibonacci Golden Pocket + Macro H1 EMA Filter.
Tests the confluence of Indonesian Institutional Setup with Quantitative Macro Filters.
"""

import sys
import time
from pathlib import Path
from collections import defaultdict
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from engine.core.event_engine import EventEngine
from engine.core.types import AccountConfig, OrderDirection, ExitReason
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from engine.metrics.performance import PerformanceCalculator
from engine.core.strategy_base import BaseStrategy
from agents.risk_manager.monthly_ratchet_governor import MonthlyRatchetGovernor
from strategies.modules.setups.fibonacci_confluence import FibonacciCalculator
from strategies.modules.setups.skeptical_ufo_detector import SkepticalUFODetector, UFOType, ZoneQuality
from strategies.incubator.strat_nfc_fibo_hybrid import NFCFiboHybridStrategy


def main():
    m15_path = PROJECT_ROOT / "data" / "processed" / "bars" / "XAUUSD" / "HTF" / "XAUUSD_M15.parquet"
    h1_path = PROJECT_ROOT / "data" / "processed" / "bars" / "XAUUSD" / "HTF" / "XAUUSD_H1.parquet"

    if not m15_path.exists() or not h1_path.exists():
        print("⚠️ Parquet history data not found. Skipping offline backtest experiments.")
        return

    df_m15 = pl.read_parquet(m15_path)
    df_h1 = pl.read_parquet(h1_path)

    # Precompute H1 EMA 50
    df_h1 = df_h1.with_columns([
        pl.col("close").ewm_mean(span=50).alias("ema50"),
        (pl.col("high") - pl.col("low")).rolling_mean(window_size=14).alias("atr14")
    ])
    h1_map = {
        row["timestamp"]: {"close": row["close"], "ema50": row["ema50"], "atr14": row["atr14"] or 5.0}
        for row in df_h1.iter_rows(named=True)
    }

    print("=" * 105)
    print("🔬 TESTING HYBRID FADLI NFC + FIBONACCI GOLDEN POCKET + H1 EMA 50")
    print("=" * 105)

    experiments = [
        ("1. Pure Fadli NFC (Unfilled Base Only)", False, False, 2.5),
        ("2. Fadli NFC + H1 EMA 50 Macro Filter", True, False, 2.5),
        ("3. Fadli NFC + H1 EMA 50 + Fibo Golden Pocket (RR 2.5)", True, True, 2.5),
        ("4. Fadli NFC + H1 EMA 50 + Fibo Golden Pocket (RR 3.5)", True, True, 3.5),
        ("5. Fadli NFC + H1 EMA 50 + Fibo Golden Pocket (RR 4.0)", True, True, 4.0),
    ]

    results = []
    for label, use_ema, use_fibo, rr in experiments:
        t0 = time.time()
        strat = NFCFiboHybridStrategy(rr_target=rr, use_macro_ema=use_ema, use_fibo_ote=use_fibo)
        c = AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0)
        e = EventEngine(config=c, commission_model=CommissionModel(7.0), slippage_model=FixedSlippageModel(0.02))
        e.reset()
        e.current_strategy = strat
        strat.set_engine(e)
        strat.on_init()

        for bar in df_m15.iter_rows(named=True):
            e.current_time = bar["timestamp"]
            spread = bar.get("mean_spread", 0.25)
            e.current_bid = bar["close"]
            e.current_ask = round(e.current_bid + spread, 3)
            e.current_spread = spread
            e._check_daily_circuit_breaker(e.current_time)
            e._update_positions_on_bar(bar)
            strat.on_bar(bar)
            e.equity_curve.append({"timestamp": e.current_time, "equity": round(e.equity, 2), "balance": round(e.balance, 2)})

        for pos_id in list(e.positions.keys()):
            e._close_position_internal(pos_id, ExitReason.END_OF_DATA)

        strat.on_finish()
        perf = PerformanceCalculator.calculate(e.closed_trades, e.equity_curve, c.initial_balance)
        elapsed = time.time() - t0

        monthly = defaultdict(float)
        for tr in e.closed_trades:
            monthly[tr.open_time.strftime("%Y-%m")] += tr.net_pnl
        pos_m = sum(1 for v in monthly.values() if v > 0)
        tot_m = len(monthly) or 1

        print(f"[{label:<55}] in {elapsed:.1f}s -> Trades: {perf.total_trades:2d} | Win: {perf.win_rate_pct:>5.1f}% | Payoff: {perf.win_loss_ratio:>4.2f}x | Net: ${perf.net_profit:>10,.2f} | PF: {perf.profit_factor:>4.2f} | DD: {perf.max_drawdown_pct:>4.1f}% | Months: {pos_m}/{tot_m}")
        results.append({
            "name": label,
            "trades": perf.total_trades,
            "win_rate": round(perf.win_rate_pct, 1),
            "payoff": round(perf.win_loss_ratio, 2),
            "net_pnl": round(perf.net_profit, 2),
            "pf": round(perf.profit_factor, 2),
            "max_dd": round(perf.max_drawdown_pct, 1),
            "months": f"{pos_m}/{tot_m}"
        })

    print("\n" + "=" * 105)
    print("🏆 FINAL COMPARATIVE SCOREBOARD")
    print("=" * 105)
    for r in results:
        print(f"{r['name']:<55} | Trades: {r['trades']:<4} | Win: {r['win_rate']:>5.1f}% | Payoff: {r['payoff']:>4.2f}x | Net: ${r['net_pnl']:>10,.2f} | PF: {r['pf']:>4.2f} | DD: {r['max_dd']:>4.1f}%")


if __name__ == "__main__":
    main()
