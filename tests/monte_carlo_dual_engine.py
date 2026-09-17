"""
1,000-Iteration Monte Carlo Bootstrap Stress Test for:
1. Engine 1 Champion (Scalper M3 VWAP)
2. Engine 2 Champion (Intraday LTF M3 Sniper)
3. Combined Dual-Engine Portfolio (736 Trades across 2010 - 2026)
Calculates:
- Median, P90, P95, P99, and Worst-Case Max Drawdowns
- Risk of Ruin (>25% or >30% DD)
- P05 (Conservative Worst-Case), Median, and P95 Final Equity
- Institutional Pass Gate (P95 Max DD <= 20.0%)
"""

import sys
import time
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any
import json
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.monte_carlo.simulator import MonteCarloSimulator
from tests.falsification_500_monkeys_modern_era import (
    load_m3_modern_dataset,
    run_strategy_simulation,
    FastTrade
)
from tests.kagebunshin_agent2_ltf_sniper import (
    load_and_preprocess_agent2_data,
    detect_m15_zones_and_signals,
    evaluate_clone_fast,
    Agent2CloneConfig
)


def run_monte_carlo_dual_engine():
    print("=" * 110)
    print("🎲 1,000 MONTE CARLO BOOTSTRAP RESHUFFLES & RISK-OF-RUIN STRESS TEST")
    print("🎲 EVALUATING ENGINE 1, ENGINE 2, AND COMBINED DUAL-ENGINE PORTFOLIO (2010 - 2026)")
    print("=" * 110)
    t0 = time.time()

    # 1. Gather Engine 1 Trades
    print("\n[Step 1/4] Generating Engine 1 Champion Trades...")
    m3_arrs = load_m3_modern_dataset()
    e1_sim = run_strategy_simulation(m3_arrs, invert=False)
    trades_e1 = e1_sim["trades"]
    print(f"  -> Engine 1 Trades: {len(trades_e1)} | Net PnL: +${e1_sim['net_pnl']:,.2f} | PF: {e1_sim['profit_factor']}")

    # 2. Gather Engine 2 Trades
    print("\n[Step 2/4] Generating Engine 2 Champion Trades...")
    m15_data, df_m3 = load_and_preprocess_agent2_data()
    opps_e2 = detect_m15_zones_and_signals(m15_data, df_m3)
    
    trades_e2: List[FastTrade] = []
    for opp in opps_e2:
        if not (opp["fibo_ote"] and opp["strict_eq"] and opp["m3_wick_confirm"]):
            continue
        c = opp["price_m15_close"]
        if opp["direction"] == "BUY" and not opp["h1_bull"]: continue
        if opp["direction"] == "SELL" and not opp["h1_bear"]: continue
        
        entry = opp["price_touch"]
        sl = opp["m3_wick_sl"]
        sl_dist = abs(entry - sl)
        if sl_dist < 0.60 or sl_dist > 10.0: continue
        
        tp_dist = sl_dist * 5.0
        tp = entry + tp_dist if opp["direction"] == "BUY" else entry - tp_dist
        
        f_highs = opp["future_highs"]
        f_lows = opp["future_lows"]
        is_win = False
        is_loss = False
        
        if opp["direction"] == "BUY":
            for fh, fl in zip(f_highs, f_lows):
                if fl <= sl: is_loss = True; break
                if fh >= tp: is_win = True; break
        else:
            for fh, fl in zip(f_highs, f_lows):
                if fh >= sl: is_loss = True; break
                if fl <= tp: is_win = True; break
                
        if is_win:
            trades_e2.append(FastTrade(net_pnl=50.0 * 5.0, year=opp["year"]))
        elif is_loss:
            trades_e2.append(FastTrade(net_pnl=-50.0, year=opp["year"]))

    net_e2 = sum(t.net_pnl for t in trades_e2)
    print(f"  -> Engine 2 Trades: {len(trades_e2)} | Net PnL: +${net_e2:,.2f}")

    # 3. Combined Trades
    trades_comb = trades_e1 + trades_e2
    print(f"\n[Step 3/4] Combined Portfolio Trades: {len(trades_comb)} trades")

    # 4. Run 1,000 Monte Carlo Simulations
    print("\n[Step 4/4] Executing 1,000 Reshuffles per Component...")
    mc_sim = MonteCarloSimulator(
        num_simulations=1000,
        ruin_drawdown_threshold_pct=25.0,
        institutional_max_dd_hurdle=20.0,
        seed=42
    )

    mc_e1 = mc_sim.run(trades_e1)
    mc_e2 = mc_sim.run(trades_e2)
    mc_comb = mc_sim.run(trades_comb)

    print("=" * 110)
    print("🏆 1,000 MONTE CARLO STRESS TEST RESULTS (16.6 YEARS BOOTSTRAP)")
    print("=" * 110)
    print(f"{'Metric':<30}{'Engine 1 (Scalper)':<25}{'Engine 2 (Sniper)':<25}{'Combined Portfolio':<25}")
    print("-" * 110)
    print(f"{'Total Trades':<30}{mc_e1.trades_per_simulation:<25}{mc_e2.trades_per_simulation:<25}{mc_comb.trades_per_simulation:<25}")
    print(f"{'Median Final Equity':<30}${mc_e1.median_final_equity:<24,.2f}${mc_e2.median_final_equity:<24,.2f}${mc_comb.median_final_equity:<24,.2f}")
    print(f"{'P05 Worst-Case Equity':<30}${mc_e1.p05_final_equity:<24,.2f}${mc_e2.p05_final_equity:<24,.2f}${mc_comb.p05_final_equity:<24,.2f}")
    print(f"{'P95 Best-Case Equity':<30}${mc_e1.p95_final_equity:<24,.2f}${mc_e2.p95_final_equity:<24,.2f}${mc_comb.p95_final_equity:<24,.2f}")
    print(f"{'Median Max Drawdown':<30}{mc_e1.median_max_drawdown_pct:<24.2f}%{mc_e2.median_max_drawdown_pct:<24.2f}%{mc_comb.median_max_drawdown_pct:<24.2f}%")
    print(f"{'P95 Max Drawdown':<30}{mc_e1.p95_max_drawdown_pct:<24.2f}%{mc_e2.p95_max_drawdown_pct:<24.2f}%{mc_comb.p95_max_drawdown_pct:<24.2f}%")
    print(f"{'Worst-Case Drawdown':<30}{mc_e1.worst_drawdown_pct:<24.2f}%{mc_e2.worst_drawdown_pct:<24.2f}%{mc_comb.worst_drawdown_pct:<24.2f}%")
    print(f"{'Probability of Ruin (>25%)':<30}{mc_e1.probability_of_ruin_pct:<24.1f}%{mc_e2.probability_of_ruin_pct:<24.1f}%{mc_comb.probability_of_ruin_pct:<24.1f}%")
    print(f"{'Institutional Pass Gate':<30}{'✅ PASS' if mc_e1.passes_institutional_hurdle else '⚠️ REVIEW':<25}{'✅ PASS' if mc_e2.passes_institutional_hurdle else '⚠️ REVIEW':<25}{'✅ PASS' if mc_comb.passes_institutional_hurdle else '⚠️ REVIEW':<25}")
    print("=" * 110)

    # Save to report
    out_file = PROJECT_ROOT / "reports" / "monte_carlo_dual_engine_audit.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "simulations": 1000,
            "engine_1": {
                "trades": mc_e1.trades_per_simulation,
                "median_final_equity": round(mc_e1.median_final_equity, 2),
                "p05_worst_equity": round(mc_e1.p05_final_equity, 2),
                "p95_best_equity": round(mc_e1.p95_final_equity, 2),
                "median_max_dd": round(mc_e1.median_max_drawdown_pct, 2),
                "p95_max_dd": round(mc_e1.p95_max_drawdown_pct, 2),
                "ruin_probability_pct": round(mc_e1.probability_of_ruin_pct, 2),
                "passed": mc_e1.passes_institutional_hurdle
            },
            "engine_2": {
                "trades": mc_e2.trades_per_simulation,
                "median_final_equity": round(mc_e2.median_final_equity, 2),
                "p05_worst_equity": round(mc_e2.p05_final_equity, 2),
                "p95_best_equity": round(mc_e2.p95_final_equity, 2),
                "median_max_dd": round(mc_e2.median_max_drawdown_pct, 2),
                "p95_max_dd": round(mc_e2.p95_max_drawdown_pct, 2),
                "ruin_probability_pct": round(mc_e2.probability_of_ruin_pct, 2),
                "passed": mc_e2.passes_institutional_hurdle
            },
            "combined_portfolio": {
                "trades": mc_comb.trades_per_simulation,
                "median_final_equity": round(mc_comb.median_final_equity, 2),
                "p05_worst_equity": round(mc_comb.p05_final_equity, 2),
                "p95_best_equity": round(mc_comb.p95_final_equity, 2),
                "median_max_dd": round(mc_comb.median_max_drawdown_pct, 2),
                "p95_max_dd": round(mc_comb.p95_max_drawdown_pct, 2),
                "ruin_probability_pct": round(mc_comb.probability_of_ruin_pct, 2),
                "passed": mc_comb.passes_institutional_hurdle
            }
        }, f, indent=2)
    print(f"\n📁 Monte Carlo Dual-Engine Audit Report saved to: {out_file.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    run_monte_carlo_dual_engine()
