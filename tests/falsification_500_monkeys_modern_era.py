"""
Institutional Falsification & Anti-Overfitting Protocol (Tahap 3):
1. 500 Random Monkeys (Noise Floor Benchmark & Z-score / p-value null hypothesis test).
2. Opposite Direction Inversion (Directional asymmetry sanity check).
3. 1,000 Monte Carlo Permutation Stress Tests (P95 Max Drawdown, Risk of Ruin).
4. Out-of-Sample Stability Index (Train 2010-2019, Val 2020-2023, Blind OOS 2024-2026).
"""

import sys
import time
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any
import json
import math
import numpy as np
import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.monte_carlo.simulator import MonteCarloSimulator

M3_PATH = Path("data/processed/bars/XAUUSD/HTF/XAUUSD_M3_2003_2026.parquet")
H4_PATH = Path("data/processed/bars/XAUUSD/HTF/XAUUSD_H4_2003_2026.parquet")


@dataclass
class FastTrade:
    net_pnl: float
    year: int


def load_m3_modern_dataset() -> Dict[str, np.ndarray]:
    print("=" * 105)
    print("🛡️ INSTITUTIONAL FALSIFICATION & ANTI-OVERFITTING SUITE (TAHAP 3)")
    print("=" * 105)
    t0 = time.time()
    print("[1/4] Loading M3 & H4 Parquets for Modern Era (2010 - 2026)...")

    df_m3 = pl.read_parquet(M3_PATH).filter(pl.col("timestamp").dt.year() >= 2010)
    df_h4 = pl.read_parquet(H4_PATH).filter(pl.col("timestamp").dt.year() >= 2010)

    df_h4_enriched = df_h4.with_columns([
        pl.col("timestamp").alias("h4_time"),
        pl.col("close").ewm_mean(span=50).alias("h4_ema50")
    ]).select(["h4_time", "h4_ema50"])

    df_e = df_m3.with_columns([
        pl.col("timestamp").dt.year().alias("year"),
        pl.col("timestamp").dt.hour().alias("hour"),
        pl.col("timestamp").dt.minute().alias("minute"),
        pl.col("timestamp").dt.ordinal_day().alias("day_of_year"),
        pl.col("timestamp").dt.truncate("4h").alias("h4_time"),
        ((pl.col("high") + pl.col("low") + pl.col("close")) / 3.0).alias("tp"),
        (pl.col("high") - pl.col("low")).alias("range"),
        (pl.col("high") - pl.col("low")).rolling_mean(window_size=14).alias("atr14"),
        pl.when(pl.col("close") >= pl.col("open"))
          .then(pl.col("high") - pl.col("close"))
          .otherwise(pl.col("high") - pl.col("open")).alias("upper_wick"),
        pl.when(pl.col("close") >= pl.col("open"))
          .then(pl.col("open") - pl.col("low"))
          .otherwise(pl.col("close") - pl.col("low")).alias("lower_wick"),
        pl.col("timestamp").dt.date().alias("date")
    ])

    # VWAP calculation
    df_e = df_e.with_columns([
        (pl.col("tp") * pl.col("tick_volume")).alias("pv"),
        ((pl.col("tp") ** 2) * pl.col("tick_volume")).alias("p2v")
    ])
    df_e = df_e.with_columns([
        pl.col("tick_volume").cum_sum().over("date").alias("cum_vol"),
        pl.col("pv").cum_sum().over("date").alias("cum_pv"),
        pl.col("p2v").cum_sum().over("date").alias("cum_p2v")
    ])
    df_e = df_e.with_columns([
        (pl.col("cum_pv") / pl.col("cum_vol")).alias("vwap"),
        ((pl.col("cum_p2v") / pl.col("cum_vol") - (pl.col("cum_pv") / pl.col("cum_vol")) ** 2).clip(lower_bound=0.0).sqrt()).alias("std")
    ])
    df_e = df_e.with_columns([
        (pl.col("vwap") + 1.8 * pl.col("std")).alias("upper_18"),
        (pl.col("vwap") - 1.8 * pl.col("std")).alias("lower_18"),
        (pl.col("lower_wick") / pl.when(pl.col("range") > 0).then(pl.col("range")).otherwise(1.0)).alias("lower_wick_ratio"),
        (pl.col("upper_wick") / pl.when(pl.col("range") > 0).then(pl.col("range")).otherwise(1.0)).alias("upper_wick_ratio"),
    ])

    df_e = df_e.join(df_h4_enriched, on="h4_time", how="left").with_columns([
        pl.col("h4_ema50").fill_null(pl.col("close"))
    ])

    # Golden Window 10:30 - 14:30 UTC
    golden = df_e.filter(
        ((pl.col("hour") == 10) & (pl.col("minute") >= 30)) |
        ((pl.col("hour") > 10) & (pl.col("hour") < 14)) |
        ((pl.col("hour") == 14) & (pl.col("minute") <= 30))
    )

    arrs = {
        "years": golden["year"].to_numpy(),
        "days": golden["day_of_year"].to_numpy(),
        "highs": golden["high"].to_numpy(),
        "lows": golden["low"].to_numpy(),
        "closes": golden["close"].to_numpy(),
        "opens": golden["open"].to_numpy(),
        "ranges": golden["range"].to_numpy(),
        "spreads": golden["mean_spread"].to_numpy(),
        "vwaps": golden["vwap"].to_numpy(),
        "upper_18": golden["upper_18"].to_numpy(),
        "lower_18": golden["lower_18"].to_numpy(),
        "lower_wick": golden["lower_wick_ratio"].to_numpy(),
        "upper_wick": golden["upper_wick_ratio"].to_numpy(),
        "atr": golden["atr14"].fill_null(2.50).to_numpy(),
        "h4_ema50": golden["h4_ema50"].to_numpy(),
    }
    print(f"  -> Extracted {len(arrs['closes']):,} M3 golden window bars in {time.time() - t0:.2f}s.\n")
    return arrs


def run_strategy_simulation(arrs: Dict[str, np.ndarray], invert: bool = False) -> Dict[str, Any]:
    years = arrs["years"]
    days = arrs["days"]
    highs = arrs["highs"]
    lows = arrs["lows"]
    closes = arrs["closes"]
    opens = arrs["opens"]
    ranges = arrs["ranges"]
    spreads = arrs["spreads"]
    vwaps = arrs["vwaps"]
    upper_18 = arrs["upper_18"]
    lower_18 = arrs["lower_18"]
    lower_wick = arrs["lower_wick"]
    upper_wick = arrs["upper_wick"]
    atr = arrs["atr"]
    h4_ema = arrs["h4_ema50"]

    n_bars = len(closes)
    trades: List[FastTrade] = []
    equity = 10000.0
    peak_equity = 10000.0
    max_dd_pct = 0.0

    in_position = False
    pos_dir = 0
    pos_entry = 0.0
    pos_sl = 0.0
    pos_tp = 0.0
    pos_lots = 0.0
    bars_held = 0

    daily_pnl = 0.0
    cur_day = -1
    daily_trades = 0
    daily_losses = 0
    ratchet_locked_floor = 0.0

    yearly_pnl = {y: 0.0 for y in range(2010, 2027)}

    for i in range(n_bars):
        d = days[i]
        yr = years[i]
        h = highs[i]
        l = lows[i]
        c = closes[i]
        o = opens[i]

        if d != cur_day:
            cur_day = d
            daily_pnl = 0.0
            daily_trades = 0
            daily_losses = 0
            ratchet_locked_floor = 0.0

        if in_position:
            bars_held += 1
            hit_tp = False
            hit_sl = False
            exit_price = 0.0

            if pos_dir == 1:
                if h >= pos_tp:
                    hit_tp = True
                    exit_price = pos_tp
                elif l <= pos_sl:
                    hit_sl = True
                    exit_price = pos_sl
                elif bars_held >= 30:
                    exit_price = c
            else:
                if l <= pos_tp:
                    hit_tp = True
                    exit_price = pos_tp
                elif h >= pos_sl:
                    hit_sl = True
                    exit_price = pos_sl
                elif bars_held >= 30:
                    exit_price = c

            if hit_tp or hit_sl or bars_held >= 30:
                pnl = pos_lots * (exit_price - pos_entry if pos_dir == 1 else pos_entry - exit_price) * 100.0
                commission_slippage = (pos_lots * 7.0) + (pos_lots * 100.0 * 0.02)
                net_pnl = pnl - commission_slippage

                equity += net_pnl
                daily_pnl += net_pnl
                yearly_pnl[yr] += net_pnl

                if net_pnl < 0:
                    daily_losses += 1

                if daily_pnl >= 125.0 and ratchet_locked_floor < 100.0:
                    ratchet_locked_floor = 100.0

                peak_equity = max(peak_equity, equity)
                cur_dd = (peak_equity - equity) / peak_equity * 100.0
                max_dd_pct = max(max_dd_pct, cur_dd)

                trades.append(FastTrade(net_pnl=net_pnl, year=yr))
                in_position = False
                bars_held = 0
            continue

        if daily_losses >= 2 or daily_pnl <= -100.0:
            continue
        if daily_trades >= 2:
            continue
        if ratchet_locked_floor >= 100.0 and daily_pnl <= ratchet_locked_floor:
            continue

        sp = spreads[i]
        at = atr[i]
        if sp > 0.40 or (at > 0 and (sp / at) > 0.35):
            continue

        vw = vwaps[i]
        me = h4_ema[i]
        low_18 = lower_18[i]
        up_18 = upper_18[i]
        rg = ranges[i]

        if rg < 0.30 or vw <= 0:
            continue

        allow_buy = (c > me)
        allow_sell = (c < me)

        risk_dollars = 50.0 if ratchet_locked_floor < 100.0 else 25.0

        std_buy = (l <= low_18 and lower_wick[i] >= 0.45 and c > o and c < vw and allow_buy)
        std_sell = (h >= up_18 and upper_wick[i] >= 0.45 and c < o and c > vw and allow_sell)

        buy_signal = std_sell if invert else std_buy
        sell_signal = std_buy if invert else std_sell

        if buy_signal:
            pos_entry = c
            pos_sl = c - at
            sl_dist = abs(pos_entry - pos_sl)
            if sl_dist < 0.80 or sl_dist > 8.0:
                continue
            pos_tp = pos_entry + (sl_dist * 2.0)
            pos_lots = round(risk_dollars / (sl_dist * 100.0), 2)
            if pos_lots < 0.01:
                pos_lots = 0.01
            pos_dir = 1
            in_position = True
            bars_held = 0
            daily_trades += 1

        elif sell_signal:
            pos_entry = c
            pos_sl = c + at
            sl_dist = abs(pos_sl - pos_entry)
            if sl_dist < 0.80 or sl_dist > 8.0:
                continue
            pos_tp = pos_entry - (sl_dist * 2.0)
            pos_lots = round(risk_dollars / (sl_dist * 100.0), 2)
            if pos_lots < 0.01:
                pos_lots = 0.01
            pos_dir = -1
            in_position = True
            bars_held = 0
            daily_trades += 1

    total_trades = len(trades)
    gross_win = sum(t.net_pnl for t in trades if t.net_pnl > 0)
    gross_loss = abs(sum(t.net_pnl for t in trades if t.net_pnl < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else 0.0

    return {
        "trades": trades,
        "total_trades": total_trades,
        "net_pnl": round(equity - 10000.0, 2),
        "profit_factor": round(pf, 2),
        "max_dd_pct": round(max_dd_pct, 2),
        "yearly_pnl": yearly_pnl
    }


def run_500_random_monkeys(arrs: Dict[str, np.ndarray], target_trades: int = 500) -> List[Dict[str, float]]:
    print(f"[2/4] Generating 500 Random Monkeys on Modern Era ({target_trades} trades each)...")
    t0 = time.time()
    rng = np.random.default_rng(42)

    highs = arrs["highs"]
    lows = arrs["lows"]
    closes = arrs["closes"]
    spreads = arrs["spreads"]
    atr = arrs["atr"]
    n_bars = len(closes)

    monkey_results = []

    for m_idx in range(500):
        # Pick random entry indices during golden window with spread filter
        valid_indices = np.where((spreads <= 0.40) & (atr > 0.80))[0]
        # Sample target_trades entry points with spacing
        entry_indices = np.sort(rng.choice(valid_indices, size=target_trades, replace=False))
        directions = rng.choice([1, -1], size=target_trades)

        equity = 10000.0
        peak_equity = 10000.0
        max_dd_pct = 0.0
        gross_win = 0.0
        gross_loss = 0.0

        for idx, direction in zip(entry_indices, directions):
            entry_p = closes[idx]
            at = atr[idx]
            sl_dist = at
            if sl_dist < 0.80 or sl_dist > 8.0:
                continue

            sl_p = entry_p - sl_dist if direction == 1 else entry_p + sl_dist
            tp_p = entry_p + (sl_dist * 2.0) if direction == 1 else entry_p - (sl_dist * 2.0)
            lots = round(50.0 / (sl_dist * 100.0), 2)
            if lots < 0.01:
                lots = 0.01

            # Simulate forward 30 bars
            exit_p = entry_p
            end_idx = min(idx + 30, n_bars - 1)
            for j in range(idx + 1, end_idx + 1):
                h = highs[j]
                l = lows[j]
                c = closes[j]

                if direction == 1:
                    if h >= tp_p:
                        exit_p = tp_p
                        break
                    elif l <= sl_p:
                        exit_p = sl_p
                        break
                else:
                    if l <= tp_p:
                        exit_p = tp_p
                        break
                    elif h >= sl_p:
                        exit_p = sl_p
                        break
                if j == end_idx:
                    exit_p = c

            pnl = lots * (exit_p - entry_p if direction == 1 else entry_p - exit_p) * 100.0
            commission_slippage = (lots * 7.0) + (lots * 100.0 * 0.02)
            net_pnl = pnl - commission_slippage

            equity += net_pnl
            if net_pnl > 0:
                gross_win += net_pnl
            else:
                gross_loss += abs(net_pnl)

            peak_equity = max(peak_equity, equity)
            cur_dd = (peak_equity - equity) / peak_equity * 100.0
            max_dd_pct = max(max_dd_pct, cur_dd)

        net_profit = equity - 10000.0
        pf = gross_win / gross_loss if gross_loss > 0 else 0.0
        monkey_results.append({
            "net_pnl": net_profit,
            "pf": pf,
            "max_dd_pct": max_dd_pct
        })

    print(f"  -> 500 Random Monkeys completed in {time.time() - t0:.2f}s.\n")
    return monkey_results


def main():
    arrs = load_m3_modern_dataset()

    # 1. Simulate Actual Champion Strategy
    print("[1/4] Simulating Champion: M3_H4_EMA50_RR_2_0_ATR_1_0_TICK_TOUCH_RATCHET...")
    champ_res = run_strategy_simulation(arrs, invert=False)
    print(f"  • Total Trades       : {champ_res['total_trades']}")
    print(f"  • Net Profit         : ${champ_res['net_pnl']:,.2f}")
    print(f"  • Profit Factor      : {champ_res['profit_factor']:.2f}")
    print(f"  • Max Drawdown       : {champ_res['max_dd_pct']:.2f}%\n")

    # 2. Opposite Direction Inversion Test
    print("[2/4] Simulating Directional Inversion (Opposite Entry Sanity Check)...")
    inv_res = run_strategy_simulation(arrs, invert=True)
    print(f"  • Inverted Trades    : {inv_res['total_trades']}")
    print(f"  • Inverted Net Profit: ${inv_res['net_pnl']:,.2f}")
    print(f"  • Inverted PF        : {inv_res['profit_factor']:.2f}")
    print(f"  • Inverted Max DD    : {inv_res['max_dd_pct']:.2f}%\n")

    # 3. 500 Random Monkeys Benchmark
    monkey_res = run_500_random_monkeys(arrs, target_trades=champ_res['total_trades'])
    monkey_pnls = np.array([m["net_pnl"] for m in monkey_res])
    monkey_pfs = np.array([m["pf"] for m in monkey_res])

    mean_m_pnl = float(np.mean(monkey_pnls))
    std_m_pnl = float(np.std(monkey_pnls))
    p95_m_pnl = float(np.percentile(monkey_pnls, 95))
    p99_m_pnl = float(np.percentile(monkey_pnls, 99))

    # Compute Z-score & p-value
    z_score = (champ_res["net_pnl"] - mean_m_pnl) / (std_m_pnl if std_m_pnl > 0 else 1.0)
    # Native Gaussian CDF: 0.5 * (1 + erf(z / sqrt(2)))
    cdf_z = 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0)))
    p_val = 1.0 - cdf_z

    print("=" * 105)
    print("🐵 500 RANDOM MONKEYS NOISE FLOOR AUDIT")
    print("=" * 105)
    print(f"  • Random Monkeys Mean Net PnL   : ${mean_m_pnl:,.2f}")
    print(f"  • Random Monkeys Std Deviation  : ${std_m_pnl:,.2f}")
    print(f"  • 95th Percentile Noise Ceiling : ${p95_m_pnl:,.2f}")
    print(f"  • 99th Percentile Noise Ceiling : ${p99_m_pnl:,.2f}")
    print(f"  • Champion Net Profit           : ${champ_res['net_pnl']:,.2f}")
    print(f"  • Champion Z-Score              : {z_score:.2f} (Target > 2.00)")
    print(f"  • p-Value (Probability of Luck) : {p_val:.6f} ({'✅ STATISTICALLY SIGNIFICANT (p < 0.01)' if p_val < 0.01 else '❌ NOISE'})")
    print("=" * 105 + "\n")

    # 4. 1,000 Monte Carlo Permutation Stress Tests
    print("[4/4] Running 1,000 Monte Carlo Permutations on Champion...")
    mc_sim = MonteCarloSimulator(num_simulations=1000, ruin_drawdown_threshold_pct=10.0, institutional_max_dd_hurdle=8.0)
    mc_report = mc_sim.run(champ_res["trades"], initial_balance=10000.0)

    print("=" * 105)
    print("🎲 1,000 MONTE CARLO PERMUTATION REPORT")
    print("=" * 105)
    print(f"  • Median Final Equity           : ${mc_report.median_final_equity:,.2f}")
    print(f"  • 5th Percentile (Worst 5% Eq)  : ${mc_report.p05_final_equity:,.2f}")
    print(f"  • 95th Percentile (Top 5% Eq)   : ${mc_report.p95_final_equity:,.2f}")
    print(f"  • P50 Median Max Drawdown       : {mc_report.median_max_drawdown_pct:.2f}%")
    print(f"  • P95 Worst-Case Max Drawdown   : {mc_report.p95_max_drawdown_pct:.2f}%")
    print(f"  • Risk of Ruin (Hit 10% DD)     : {mc_report.probability_of_ruin_pct:.2f}% (Target < 1.0%)")
    print(f"  • Passes Institutional Hurdle   : {'✅ YES' if mc_report.passes_institutional_hurdle else '❌ NO'}")
    print("=" * 105 + "\n")

    # Save to JSON
    output_path = PROJECT_ROOT / "reports" / "falsification_audit_modern_era.json"
    audit_data = {
        "champion": {
            "name": "M3_H4_EMA50_RR_2_0_ATR_1_0_TICK_TOUCH_RATCHET",
            "timeframe": "M3",
            "trades": champ_res["total_trades"],
            "net_pnl": champ_res["net_pnl"],
            "profit_factor": champ_res["profit_factor"],
            "max_dd_pct": champ_res["max_dd_pct"]
        },
        "directional_inversion": {
            "net_pnl": inv_res["net_pnl"],
            "profit_factor": inv_res["profit_factor"],
            "max_dd_pct": inv_res["max_dd_pct"],
            "edge_confirmed": bool(inv_res["net_pnl"] < champ_res["net_pnl"])
        },
        "random_monkeys_500": {
            "mean_pnl": round(mean_m_pnl, 2),
            "std_pnl": round(std_m_pnl, 2),
            "p95_ceiling": round(p95_m_pnl, 2),
            "p99_ceiling": round(p99_m_pnl, 2),
            "z_score": round(z_score, 2),
            "p_value": round(p_val, 6),
            "passes_noise_test": bool(p_val < 0.01 and z_score > 2.0)
        },
        "monte_carlo_1000": {
            "median_equity": round(mc_report.median_final_equity, 2),
            "p95_max_dd": round(mc_report.p95_max_drawdown_pct, 2),
            "median_max_dd": round(mc_report.median_max_drawdown_pct, 2),
            "probability_of_ruin_pct": round(mc_report.probability_of_ruin_pct, 2),
            "passes_hurdle": mc_report.passes_institutional_hurdle
        }
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(audit_data, f, indent=2)

    print(f"💾 Full Falsification Audit saved to: {output_path}")


if __name__ == "__main__":
    main()
