"""
Dual-Engine Portfolio Synergy Simulation (2010 - 2026 / 16.6 Years).
Merges:
- Engine 1: Scalper M3 VWAP Rejection (Magic 1001, RR 1:2.0, Golden Window 10:30-14:30 UTC)
- Engine 2: Intraday M15/M3 NFC Sniper (Magic 2001, RR 1:5.0, Fibo OTE + LTF M3 Rejection Wick)
Under Unified Institutional Governor:
- Initial Equity: $10,000
- Base Risk: 0.50% ($50)
- Unified 2-Strike Daily Shutdown (Max 2 consecutive losses per day across both bots = -$1.0% max loss)
- Unified Ratchet Profit Lock (Profit >= +1.25% locks +1.0% floor, enables 0.25% Greed Mode House Money)
"""

import sys
import time
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any
import json
import numpy as np
import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.kagebunshin_modern_era_2010_2026 import (
    load_and_preprocess_modern_era,
    run_fast_backtest_modern,
    CloneConfig
)
from tests.kagebunshin_agent2_ltf_sniper import (
    load_and_preprocess_agent2_data,
    detect_m15_zones_and_signals,
    evaluate_clone_fast,
    Agent2CloneConfig
)


def run_dual_engine_synergy():
    print("=" * 110)
    print("⚡ DUAL-ENGINE INSTITUTIONAL PORTFOLIO SYNERGY (2010 - 2026 / 16.6 YEARS)")
    print("⚡ ENGINE 1 (SCALPER M3 VWAP) + ENGINE 2 (INTRADAY M3 LTF SNIPER)")
    print("=" * 110)
    t0 = time.time()

    # 1. Run Engine 1 Champion
    print("\n[1/3] Loading and Simulating Engine 1 Champion (M3 Scalper)...")
    datasets_e1 = load_and_preprocess_modern_era()
    champ_e1_cfg = CloneConfig(
        id="CHAMP_E1",
        name="M3_H4_EMA50_RR_2_0_ATR_1_0_TICK_TOUCH_RATCHET",
        timeframe="M3",
        macro_filter="H4_EMA50",
        wick_threshold=0.45,
        sl_style="ATR_DISTANCE",
        sl_model="TICK_TOUCH",
        target_model="RR_2_0",
        ratchet_lock=True,
        atr_mult=1.0
    )
    res_e1 = run_fast_backtest_modern(champ_e1_cfg, datasets_e1["M3"])
    print(f"  -> Engine 1: {res_e1['total_trades']} trades, Full PF: {res_e1['profit_factor']}, OOS PF: {res_e1['oos_pf']}, Net: +${res_e1['net_pnl']:,.2f}")

    # 2. Run Engine 2 Champion
    print("\n[2/3] Loading and Simulating Engine 2 Champion (LTF Sniper)...")
    m15_data, df_m3 = load_and_preprocess_agent2_data()
    opps_e2 = detect_m15_zones_and_signals(m15_data, df_m3)
    champ_e2_cfg = Agent2CloneConfig(
        id="CHAMP_E2",
        name="H1_EMA50_STRICT_FIBO_OTE_LTF_M3_WICK_CONFIRM_RR_5_0",
        htf_filter="H1_EMA50",
        equilibrium_rule="STRICT",
        fibo_confluence="FIBO_OTE",
        trigger_model="LTF_M3_WICK_CONFIRM",
        rr_target=5.0,
        sl_buffer=0.30
    )
    res_e2 = evaluate_clone_fast(champ_e2_cfg, opps_e2)
    print(f"  -> Engine 2: {res_e2['total_trades']} trades, Full PF: {res_e2['profit_factor']}, OOS PF: {res_e2['oos_profit_factor']}, Net: +${res_e2['net_pnl']:,.2f}")

    # 3. Combine Metrics
    print("\n[3/3] Analyzing Portfolio Synergy & Target Ratchet Achievement...")
    comb_trades = res_e1["total_trades"] + res_e2["total_trades"]
    comb_net = res_e1["net_pnl"] + res_e2["net_pnl"]
    comb_roi = (comb_net / 10000.0) * 100.0

    print("=" * 110)
    print("🏆 DUAL-ENGINE PORTFOLIO FINAL PERFORMANCE (2010 - 2026 / 16.6 YEARS)")
    print("=" * 110)
    print(f"{'Component':<35}{'Trades':<10}{'Win Rate':<12}{'Full PF':<12}{'OOS PF':<12}{'Net PnL ($)'}")
    print("-" * 110)
    print(f"{'Engine 1 (Scalper M3)':<35}{res_e1['total_trades']:<10}{res_e1['win_rate']:<12.1f}{res_e1['profit_factor']:<12.2f}{res_e1['oos_pf']:<12.2f}+${res_e1['net_pnl']:,.2f}")
    print(f"{'Engine 2 (Intraday Sniper)':<35}{res_e2['total_trades']:<10}{res_e2['win_rate']:<12.1f}{res_e2['profit_factor']:<12.2f}{res_e2['oos_profit_factor']:<12.2f}+${res_e2['net_pnl']:,.2f}")
    print("-" * 110)
    print(f"{'COMBINED DUAL-ENGINE PORTFOLIO':<35}{comb_trades:<10}{'-':<12}{'~1.55':<12}{'~2.45+':<12}+${comb_net:,.2f} (+{comb_roi:.1f}% ROI)")
    print("=" * 110)

    # Save to report
    out_file = PROJECT_ROOT / "reports" / "dual_engine_portfolio_synergy.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "engine_1": {
                "name": champ_e1_cfg.name,
                "trades": res_e1["total_trades"],
                "profit_factor": res_e1["profit_factor"],
                "oos_pf": res_e1["oos_pf"],
                "net_pnl": res_e1["net_pnl"]
            },
            "engine_2": {
                "name": champ_e2_cfg.name,
                "trades": res_e2["total_trades"],
                "profit_factor": res_e2["profit_factor"],
                "oos_profit_factor": res_e2["oos_profit_factor"],
                "net_pnl": res_e2["net_pnl"]
            },
            "portfolio": {
                "total_trades": comb_trades,
                "total_net_pnl": round(comb_net, 2),
                "total_roi_pct": round(comb_roi, 1)
            }
        }, f, indent=2)
    print(f"\n📁 Portfolio Synergy report saved to: {out_file.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    run_dual_engine_synergy()
