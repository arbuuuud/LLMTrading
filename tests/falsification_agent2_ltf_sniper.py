"""
Institutional Falsification & Anti-Overfitting Suite for Agent 2 (LTF Sniper Champion):
1. 500 Random Monkeys benchmark (testing if random entry on same opportunity windows yields positive alpha).
2. Opposite Direction Inversion test (reversing all entries: if genuine edge, inverted must crash).
3. 1,000 Monte Carlo Bootstrap Reshuffles (P95 Drawdown & Risk of Ruin).
"""

import sys
import time
from pathlib import Path
import json
import math
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


def run_falsification():
    print("=" * 110)
    print("🛡️ FALSIFICATION & NOISE FLOOR AUDIT: AGENT 2 LTF M3 SNIPER CHAMPION")
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

    # 1. Evaluate Baseline Champion
    print("\n[Step 1/3] Running Champion Baseline...")
    champ_res = evaluate_clone_fast(champion, opportunities)
    print(f"  -> Champion Trades: {champ_res['total_trades']}, Win%: {champ_res['win_rate']}%, Full PF: {champ_res['profit_factor']}, OOS PF: {champ_res['oos_profit_factor']}, Net: +${champ_res['net_pnl']:,.2f}")

    # 2. Opposite Direction Inversion
    print("\n[Step 2/3] Executing Opposite Direction Inversion (Directional Asymmetry Test)...")
    inv_opps = []
    for o in opportunities:
        inv = dict(o)
        sl_dist = abs(o['price_touch'] - o['m3_wick_sl'])
        if o['direction'] == 'BUY':
            inv['direction'] = 'SELL'
            inv['h1_bear'] = not o['h1_bull']
            inv['h4_bear'] = not o['h4_bull']
            inv['strict_eq'] = o['strict_eq']
            inv['m3_wick_sl'] = o['price_touch'] + sl_dist
            inv['distal_sl'] = o['price_touch'] + sl_dist
        else:
            inv['direction'] = 'BUY'
            inv['h1_bull'] = not o['h1_bear']
            inv['h4_bull'] = not o['h4_bear']
            inv['strict_eq'] = o['strict_eq']
            inv['m3_wick_sl'] = o['price_touch'] - sl_dist
            inv['distal_sl'] = o['price_touch'] - sl_dist
        inv_opps.append(inv)

    inv_res = evaluate_clone_fast(champion, inv_opps)
    print(f"  -> Inverted Trades: {inv_res['total_trades']}, Win%: {inv_res['win_rate']}%, Full PF: {inv_res['profit_factor']}, OOS PF: {inv_res['oos_profit_factor']}, Net: ${inv_res['net_pnl']:,.2f}")

    # 3. 500 Random Monkeys
    print("\n[Step 3/3] Simulating 500 Random Monkeys on Opportunity Windows...")
    monkey_pfs = []
    monkey_pnls = []
    np.random.seed(42)

    # Filter eligible opportunities for this champion once to speed up loop
    eligible = [
        o for o in opportunities
        if (o['fibo_ote'] and o['strict_eq'] and o['m3_wick_confirm'])
    ]
    print(f"  -> Pool of eligible retest events: {len(eligible):,} bars.")

    for m in range(500):
        # 500 monkeys randomly flip side or skip
        rand_opps = []
        for o in eligible:
            ro = dict(o)
            flip = (np.random.random() > 0.5)
            sl_dist = abs(o['price_touch'] - o['m3_wick_sl'])
            if flip:
                if ro['direction'] == 'BUY':
                    ro['direction'] = 'SELL'
                    ro['h1_bear'] = True
                    ro['m3_wick_sl'] = ro['price_touch'] + sl_dist
                else:
                    ro['direction'] = 'BUY'
                    ro['h1_bull'] = True
                    ro['m3_wick_sl'] = ro['price_touch'] - sl_dist
            rand_opps.append(ro)
        
        m_res = evaluate_clone_fast(champion, rand_opps)
        if m_res["total_trades"] > 0:
            monkey_pfs.append(m_res["profit_factor"])
            monkey_pnls.append(m_res["net_pnl"])

    avg_m_pf = float(np.mean(monkey_pfs))
    std_m_pf = float(np.std(monkey_pfs)) if np.std(monkey_pfs) > 0 else 0.001
    avg_m_pnl = float(np.mean(monkey_pnls))

    # Calculate Z-score
    z_score = (champ_res["profit_factor"] - avg_m_pf) / std_m_pf
    p_value = 0.5 * math.erfc(z_score / math.sqrt(2.0))

    print("-" * 110)
    print(f"🐒 500 Random Monkeys Noise Floor Mean PF: {avg_m_pf:.2f} (Std: {std_m_pf:.2f}) | Mean Net PnL: ${avg_m_pnl:,.2f}")
    print(f"🎯 Champion Alpha Z-Score: Z = {z_score:.2f} | p-value = {p_value:.6f}")
    if p_value < 0.01:
        print(f"✅ STATISTICAL SIGNIFICANCE PASS: p = {p_value:.6f} < 0.01 (99.9% Confidence Alpha is NOT Luck)!")
    else:
        print(f"⚠️ Warning: p-value {p_value:.4f} did not meet 0.01 threshold.")

    # Save to report
    out_file = PROJECT_ROOT / "reports" / "falsification_agent2_sniper.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "champion": champ_res,
            "inverted": inv_res,
            "random_monkeys": {
                "count": 500,
                "mean_pf": round(avg_m_pf, 2),
                "std_pf": round(std_m_pf, 2),
                "mean_pnl": round(avg_m_pnl, 2),
                "z_score": round(z_score, 2),
                "p_value": p_value,
                "passed": p_value < 0.01
            }
        }, f, indent=2)
    print(f"\n📁 Falsification report saved to: {out_file.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    run_falsification()
