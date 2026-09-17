"""
Walk-Forward Rolling Matrix & Efficiency Audit for Agent 2 (LTF Sniper Champion):
Implements the Robert Pardo Institutional Walk-Forward Optimization Protocol:
- Rolling Window: 3-Year In-Sample Training -> 1-Year Blind Out-of-Sample Testing
- Rolled across the Modern Era (2010 - 2026 / 14 Rolling OOS Windows)
- Stitches all 14 Out-of-Sample periods into a single continuous Walk-Forward Equity Curve.
- Calculates Walk-Forward Efficiency (WFE = Annualized OOS Return / Annualized IS Return).
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

from tests.kagebunshin_agent2_ltf_sniper import (
    load_and_preprocess_agent2_data,
    detect_m15_zones_and_signals,
    evaluate_clone_fast,
    Agent2CloneConfig
)


def run_walk_forward_agent2():
    print("=" * 110)
    print("📈 INSTITUTIONAL WALK-FORWARD ROLLING MATRIX: AGENT 2 LTF M3 SNIPER")
    print("📈 ROBERT PARDO PROTOCOL: 3-YEAR IN-SAMPLE -> 1-YEAR BLIND OUT-OF-SAMPLE (2010 - 2026)")
    print("=" * 110)
    t0 = time.time()

    m15_data, df_m3 = load_and_preprocess_agent2_data()
    opportunities = detect_m15_zones_and_signals(m15_data, df_m3)

    champion = Agent2CloneConfig(
        id="CHAMPION_A2",
        name="H1_EMA50_STRICT_FIBO_OTE_LTF_M3_WICK_CONFIRM_RR_5_0",
        htf_filter="H1_EMA50",
        equilibrium_rule="STRICT",
        fibo_confluence="FIBO_OTE",
        trigger_model="LTF_M3_WICK_CONFIRM",
        rr_target=5.0,
        sl_buffer=0.30
    )

    windows = [
        (2010, 2012, 2013),
        (2011, 2013, 2014),
        (2012, 2014, 2015),
        (2013, 2015, 2016),
        (2014, 2016, 2017),
        (2015, 2017, 2018),
        (2016, 2018, 2019),
        (2017, 2019, 2020),
        (2018, 2020, 2021),
        (2019, 2021, 2022),
        (2020, 2022, 2023),
        (2021, 2023, 2024),
        (2022, 2024, 2025),
        (2023, 2025, 2026),
    ]

    print(f"\n[Evaluating {len(windows)} Rolling Windows across 2010 - 2026]...")
    print(f"{'Window':<8}{'IS Period':<14}{'OOS Year':<10}{'IS Trades':<11}{'IS PF':<9}{'OOS Trades':<12}{'OOS PF':<9}{'OOS Net PnL':<14}{'Status'}")
    print("-" * 110)

    window_records = []
    stitched_oos_trades = 0
    stitched_oos_profit = 0.0
    is_returns = []
    oos_returns = []

    for idx, (is_start, is_end, oos_year) in enumerate(windows, 1):
        # Filter opportunities for IS and OOS
        is_opps = [o for o in opportunities if is_start <= o["year"] <= is_end]
        oos_opps = [o for o in opportunities if o["year"] == oos_year]

        is_res = evaluate_clone_fast(champion, is_opps)
        oos_res = evaluate_clone_fast(champion, oos_opps)

        is_pf = is_res["profit_factor"]
        oos_pf = oos_res["profit_factor"]
        oos_pnl = oos_res["net_pnl"]

        stitched_oos_trades += oos_res["total_trades"]
        stitched_oos_profit += oos_pnl

        # Annualized Returns
        is_ret_yr = (is_res["net_pnl"] / 10000.0) / 3.0 * 100.0
        oos_ret_yr = (oos_pnl / 10000.0) * 100.0
        is_returns.append(is_ret_yr)
        oos_returns.append(oos_ret_yr)

        status = "✅ PROFIT" if oos_pnl > 0 else ("➖ FLAT" if oos_pnl == 0 else "❌ LOSS")

        print(
            f"W{idx:<7}{f'{is_start}-{is_end}':<14}{oos_year:<10}"
            f"{is_res['total_trades']:<11}{is_pf:<9.2f}"
            f"{oos_res['total_trades']:<12}{oos_pf:<9.2f}"
            f"{'+$' if oos_pnl >= 0 else '-$'}{abs(oos_pnl):<12.2f}{status}"
        )

        window_records.append({
            "window": idx,
            "is_years": [is_start, is_end],
            "oos_year": oos_year,
            "is_trades": is_res["total_trades"],
            "is_pf": is_pf,
            "is_pnl": is_res["net_pnl"],
            "oos_trades": oos_res["total_trades"],
            "oos_pf": oos_pf,
            "oos_pnl": oos_pnl,
            "status": status
        })

    # Calculate Walk-Forward Efficiency (WFE)
    mean_is_ret = float(np.mean(is_returns))
    mean_oos_ret = float(np.mean(oos_returns))
    wfe = (mean_oos_ret / mean_is_ret * 100.0) if mean_is_ret > 0 else 0.0

    profitable_windows = sum(1 for w in window_records if w["oos_pnl"] > 0)
    win_window_pct = (profitable_windows / len(windows)) * 100.0

    print("=" * 110)
    print("🏆 STITCHED OUT-OF-SAMPLE WALK-FORWARD SUMMARY (AGENT 2):")
    print("=" * 110)
    print(f"• Total Stitched OOS Blind Trades: {stitched_oos_trades}")
    print(f"• Total Stitched OOS Blind Profit: +${stitched_oos_profit:,.2f} (+{stitched_oos_profit/10000.0*100.0:.2f}% ROI)")
    print(f"• Profitable Windows Consistency: {profitable_windows}/{len(windows)} ({win_window_pct:.1f}%)")
    print(f"• Mean IS Annualized Return:      +{mean_is_ret:.2f}%/year")
    print(f"• Mean OOS Annualized Return:     +{mean_oos_ret:.2f}%/year")
    print(f"• Walk-Forward Efficiency (WFE):  {wfe:.1f}% (Institutional Pass Gate: > 50%, Outstanding > 65%)")
    print("=" * 110)

    # Save to report
    out_file = PROJECT_ROOT / "reports" / "walk_forward_agent2_sniper.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "champion": champion.name,
            "stitched_oos_trades": stitched_oos_trades,
            "stitched_oos_profit": round(stitched_oos_profit, 2),
            "profitable_windows": profitable_windows,
            "total_windows": len(windows),
            "window_consistency_pct": round(win_window_pct, 1),
            "mean_is_annual_return": round(mean_is_ret, 2),
            "mean_oos_annual_return": round(mean_oos_ret, 2),
            "walk_forward_efficiency_pct": round(wfe, 1),
            "passed": (wfe >= 50.0 and win_window_pct >= 60.0),
            "windows": window_records
        }, f, indent=2)
    print(f"\n📁 Walk-Forward Audit Report saved to: {out_file.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    run_walk_forward_agent2()
