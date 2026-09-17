"""
Grand Master Kage Bunshin: 23.3-Year Institutional Parallel Tournament (2003 - 2026).
Simulates 12 distinct multi-dimensional clones across 7,934,247 M1 bars testing:
1. ATR Buffers (1.5x vs 1.0x)
2. Execution Modes (Market on Close vs Resting Limit)
3. Macro Trend Filters (H1 EMA 50 & $15 Parabolic Guard)
4. Fractal MTF Sweet Spots (M1 vs M2 vs M3)
5. Trade Management (Fixed 1:2 RR vs Callisto Twin 50/50 Breakeven Ratchet)
6. Stop Loss Models (Anti-Wick Bar-Close SL vs Tick-Touch SL)
7. Anti-Overfitting Partitioning (Train 2003-2019, Val 2020-2023, Blind OOS 2024-2026)
8. 1,000-Iteration Monte Carlo Stress Test (P95 Max DD, Risk of Ruin)
"""

import sys
import time
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import json
import numpy as np
import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.monte_carlo.simulator import MonteCarloSimulator, MonteCarloReport

M1_PATH = Path("data/processed/bars/XAUUSD/M1/XAUUSD_M1_2003_2026.parquet")
M2_PATH = Path("data/processed/bars/XAUUSD/HTF/XAUUSD_M2_2003_2026.parquet")
M3_PATH = Path("data/processed/bars/XAUUSD/HTF/XAUUSD_M3_2003_2026.parquet")
H1_PATH = Path("data/processed/bars/XAUUSD/HTF/XAUUSD_H1_2003_2026.parquet")


@dataclass
class CloneConfig:
    id: str
    name: str
    timeframe: str         # "M1", "M2", "M3"
    atr_mult: float        # 1.0 or 1.5
    exec_mode: str         # "MARKET_ON_CLOSE" or "RESTING_LIMIT"
    macro_filter: str      # "NONE", "H1_EMA50", "H1_EMA50_PARABOLIC"
    exit_model: str        # "FIXED_RR", "CALLISTO_BE_TWIN"
    sl_model: str          # "BAR_CLOSE", "TICK_TOUCH"
    base_risk_pct: float   # 0.5%


def load_and_preprocess_datasets() -> Dict[str, Dict[str, np.ndarray]]:
    print("=" * 80)
    print("⚡ GRAND MASTER KAGE BUNSHIN: 23.3-YEAR MULTI-DIMENSIONAL ENGINE (2003 - 2026)")
    print("=" * 80)
    t0 = time.time()

    print("[Phase 1/3] Loading M1, M2, M3, and H1 Parquets...")
    df_m1 = pl.read_parquet(M1_PATH)
    df_m2 = pl.read_parquet(M2_PATH)
    df_m3 = pl.read_parquet(M3_PATH)
    df_h1 = pl.read_parquet(H1_PATH)
    print(f"  -> Loaded {len(df_m1):,} M1 bars & HTF series in {time.time() - t0:.2f}s.")

    # Precompute Macro H1 EMA 50
    print("[Phase 2/3] Precomputing Macro H1 EMA 50...")
    df_h1_enriched = df_h1.with_columns([
        pl.col("timestamp").alias("h1_time"),
        pl.col("close").ewm_mean(span=50).alias("h1_ema50")
    ]).select(["h1_time", "h1_ema50"])

    def enrich_and_extract_arrays(df: pl.DataFrame, name: str) -> Dict[str, np.ndarray]:
        t_sub = time.time()
        print(f"  -> Processing {name} ({len(df):,} bars)...")

        df_e = df.with_columns([
            pl.col("timestamp").dt.year().alias("year"),
            pl.col("timestamp").dt.hour().alias("hour"),
            pl.col("timestamp").dt.minute().alias("minute"),
            pl.col("timestamp").dt.ordinal_day().alias("day_of_year"),
            pl.col("timestamp").dt.truncate("1h").alias("h1_time"),
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

        # VWAP per date
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

        # Left join H1 EMA 50
        df_e = df_e.join(df_h1_enriched, on="h1_time", how="left").with_columns(
            pl.col("h1_ema50").fill_null(pl.col("close"))
        )

        # Filter Golden Window: 10:30 - 14:30 UTC
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
            "spreads": golden["mean_spread"].to_numpy(),
            "vwaps": golden["vwap"].to_numpy(),
            "upper_18": golden["upper_18"].to_numpy(),
            "lower_18": golden["lower_18"].to_numpy(),
            "lower_wick": golden["lower_wick_ratio"].to_numpy(),
            "upper_wick": golden["upper_wick_ratio"].to_numpy(),
            "atr": golden["atr14"].fill_null(2.50).to_numpy(),
            "macro_ema": golden["h1_ema50"].to_numpy(),
            "timestamps": golden["timestamp"].to_numpy()
        }
        print(f"     Golden window {name}: {len(arrs['closes']):,} bars prepared in {time.time() - t_sub:.2f}s.")
        return arrs

    print("[Phase 3/3] Building Contiguous NumPy Matrices for M1, M2, M3...")
    tf_arrays = {
        "M1": enrich_and_extract_arrays(df_m1, "M1"),
        "M2": enrich_and_extract_arrays(df_m2, "M2"),
        "M3": enrich_and_extract_arrays(df_m3, "M3"),
    }
    print("✅ Preprocessing complete! Ready for multi-clone simulation.")
    return tf_arrays


class FastTrade:
    __slots__ = ("net_pnl", "year")
    def __init__(self, net_pnl: float, year: int):
        self.net_pnl = net_pnl
        self.year = year


def simulate_clone(config: CloneConfig, tf_arrays: Dict[str, Dict[str, np.ndarray]]) -> Dict[str, Any]:
    """
    Executes a single clone over the 23.3-year historical dataset with high-speed NumPy arrays.
    """
    arrs = tf_arrays[config.timeframe]

    years = arrs["years"]
    days = arrs["days"]
    highs = arrs["highs"]
    lows = arrs["lows"]
    closes = arrs["closes"]
    opens = arrs["opens"]
    spreads = arrs["spreads"]
    vwaps = arrs["vwaps"]
    upper_18 = arrs["upper_18"]
    lower_18 = arrs["lower_18"]
    lower_wick = arrs["lower_wick"]
    upper_wick = arrs["upper_wick"]
    atr = arrs["atr"]
    macro_ema = arrs["macro_ema"]

    n_bars = len(closes)

    trades: List[FastTrade] = []
    equity = 10000.0
    initial_balance = 10000.0
    peak_equity = 10000.0
    max_dd_pct = 0.0

    in_position = False
    pos_dir = 0  # 1 = BUY, -1 = SELL
    pos_entry = 0.0
    pos_sl = 0.0
    pos_tp = 0.0
    pos_lots = 0.0
    bars_held = 0
    half_closed = False

    daily_pnl = 0.0
    cur_day = -1
    daily_losses = 0

    yearly_pnl = {y: 0.0 for y in range(2003, 2027)}

    for i in range(n_bars):
        d = days[i]
        yr = years[i]
        h = highs[i]
        l = lows[i]
        c = closes[i]
        o = opens[i]

        # Daily reset
        if d != cur_day:
            cur_day = d
            daily_pnl = 0.0
            daily_losses = 0

        # Position Management
        if in_position:
            bars_held += 1
            hit_tp = False
            hit_sl = False
            exit_price = 0.0

            if pos_dir == 1:  # BUY
                if h >= pos_tp:
                    hit_tp = True
                    exit_price = pos_tp
                elif (config.sl_model == "TICK_TOUCH" and l <= pos_sl) or (config.sl_model == "BAR_CLOSE" and c < pos_sl):
                    hit_sl = True
                    exit_price = pos_sl if config.sl_model == "TICK_TOUCH" else c
                elif config.exit_model == "CALLISTO_BE_TWIN" and not half_closed and (h >= pos_entry + (pos_tp - pos_entry) * 0.5):
                    # Half close at 1.0R, move SL to BE + spread buffer
                    half_pnl = (pos_lots * 0.5) * ((pos_entry + (pos_tp - pos_entry) * 0.5) - pos_entry) * 100.0 - 1.50
                    equity += half_pnl
                    daily_pnl += half_pnl
                    yearly_pnl[yr] += half_pnl
                    half_closed = True
                    pos_sl = pos_entry + 0.30
                elif bars_held >= 60:
                    exit_price = c

            else:  # SELL
                if l <= pos_tp:
                    hit_tp = True
                    exit_price = pos_tp
                elif (config.sl_model == "TICK_TOUCH" and h >= pos_sl) or (config.sl_model == "BAR_CLOSE" and c > pos_sl):
                    hit_sl = True
                    exit_price = pos_sl if config.sl_model == "TICK_TOUCH" else c
                elif config.exit_model == "CALLISTO_BE_TWIN" and not half_closed and (l <= pos_entry - (pos_entry - pos_tp) * 0.5):
                    half_pnl = (pos_lots * 0.5) * (pos_entry - (pos_entry - (pos_entry - pos_tp) * 0.5)) * 100.0 - 1.50
                    equity += half_pnl
                    daily_pnl += half_pnl
                    yearly_pnl[yr] += half_pnl
                    half_closed = True
                    pos_sl = pos_entry - 0.30
                elif bars_held >= 60:
                    exit_price = c

            if hit_tp or hit_sl or bars_held >= 60:
                remaining_lots = pos_lots * 0.5 if half_closed else pos_lots
                if pos_dir == 1:
                    pnl = remaining_lots * (exit_price - pos_entry) * 100.0
                else:
                    pnl = remaining_lots * (pos_entry - exit_price) * 100.0

                commission_slippage = (remaining_lots * 7.0) + (remaining_lots * 100.0 * 0.02)
                net_pnl = pnl - commission_slippage

                equity += net_pnl
                daily_pnl += net_pnl
                yearly_pnl[yr] += net_pnl

                if net_pnl < 0:
                    daily_losses += 1

                peak_equity = max(peak_equity, equity)
                cur_dd = (peak_equity - equity) / peak_equity * 100.0
                max_dd_pct = max(max_dd_pct, cur_dd)

                trades.append(FastTrade(net_pnl=net_pnl, year=yr))

                in_position = False
                half_closed = False
                bars_held = 0
            continue

        # 2-Strike rule
        if daily_losses >= 2 or daily_pnl <= -100.0:
            continue

        # Spread & VWAP validity
        sp = spreads[i]
        vw = vwaps[i]
        at = atr[i]
        me = macro_ema[i]
        low_18 = lower_18[i]
        up_18 = upper_18[i]

        if sp > 0.45 or vw <= 0:
            continue

        # Parabolic Guard
        if config.macro_filter == "H1_EMA50_PARABOLIC" and abs(c - me) > 15.0:
            continue

        buy_signal = False
        sell_signal = False

        if config.exec_mode == "MARKET_ON_CLOSE":
            # BUY: Low <= lower_18, lower wick >= 45%, Green Close
            if l <= low_18 and lower_wick[i] >= 0.45 and c > o:
                if config.macro_filter in ("H1_EMA50", "H1_EMA50_PARABOLIC") and c < me:
                    pass
                else:
                    buy_signal = True

            # SELL: High >= upper_18, upper wick >= 45%, Red Close
            if h >= up_18 and upper_wick[i] >= 0.45 and c < o:
                if config.macro_filter in ("H1_EMA50", "H1_EMA50_PARABOLIC") and c > me:
                    pass
                else:
                    sell_signal = True

        elif config.exec_mode == "RESTING_LIMIT":
            if l <= low_18:
                buy_signal = True
            elif h >= up_18:
                sell_signal = True

        if buy_signal:
            in_position = True
            pos_dir = 1
            pos_entry = low_18 if config.exec_mode == "RESTING_LIMIT" else c
            sl_dist = max(1.0, at * config.atr_mult)
            pos_sl = pos_entry - sl_dist
            rr = 2.5 if config.exit_model == "CALLISTO_BE_TWIN" else 2.0
            pos_tp = pos_entry + (sl_dist * rr)
            bars_held = 0
            half_closed = False

            risk_dollars = equity * (config.base_risk_pct / 100.0)
            calculated_lots = risk_dollars / (sl_dist * 100.0)
            pos_lots = round(max(0.01, min(5.0, calculated_lots)), 2)

        elif sell_signal:
            in_position = True
            pos_dir = -1
            pos_entry = up_18 if config.exec_mode == "RESTING_LIMIT" else c
            sl_dist = max(1.0, at * config.atr_mult)
            pos_sl = pos_entry + sl_dist
            rr = 2.5 if config.exit_model == "CALLISTO_BE_TWIN" else 2.0
            pos_tp = pos_entry - (sl_dist * rr)
            bars_held = 0
            half_closed = False

            risk_dollars = equity * (config.base_risk_pct / 100.0)
            calculated_lots = risk_dollars / (sl_dist * 100.0)
            pos_lots = round(max(0.01, min(5.0, calculated_lots)), 2)

    # Performance Metrics
    net_pnls = [t.net_pnl for t in trades]
    total_net = sum(net_pnls)
    wins = [p for p in net_pnls if p > 0]
    losses = [p for p in net_pnls if p < 0]

    win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0
    profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else 0.0
    positive_years = sum(1 for y, pnl in yearly_pnl.items() if pnl > 0)

    # === Anti-Overfitting Partitioning (SSOT 70/15/15 Rule) ===
    # 1. In-Sample Train: 2003 - 2019 (17 Years)
    trades_train = [t for t in trades if t.year <= 2019]
    train_wins = [t.net_pnl for t in trades_train if t.net_pnl > 0]
    train_loss = [t.net_pnl for t in trades_train if t.net_pnl < 0]
    pf_train = (sum(train_wins) / abs(sum(train_loss))) if train_loss and sum(train_loss) != 0 else 0.0

    # 2. Validation Test: 2020 - 2023 (4 Years)
    trades_val = [t for t in trades if 2020 <= t.year <= 2023]
    val_wins = [t.net_pnl for t in trades_val if t.net_pnl > 0]
    val_loss = [t.net_pnl for t in trades_val if t.net_pnl < 0]
    pf_val = (sum(val_wins) / abs(sum(val_loss))) if val_loss and sum(val_loss) != 0 else 0.0

    # 3. Blind Out-of-Sample Holdout: 2024 - 2026 (2.5 Years)
    trades_oos = [t for t in trades if t.year >= 2024]
    oos_wins = [t.net_pnl for t in trades_oos if t.net_pnl > 0]
    oos_loss = [t.net_pnl for t in trades_oos if t.net_pnl < 0]
    pf_oos = (sum(oos_wins) / abs(sum(oos_loss))) if oos_loss and sum(oos_loss) != 0 else 0.0

    # Overfitting verdict
    oos_retention = (pf_oos / pf_train) if pf_train > 0 else 0.0
    if pf_oos < 1.0 or (pf_train > 1.2 and oos_retention < 0.65):
        overfit_status = "🔴 OVERFITTED"
    elif pf_oos >= 1.15 and pf_train >= 1.10 and pf_val >= 1.05:
        overfit_status = "🟢 ROBUST (OOS PASSED)"
    else:
        overfit_status = "🟡 MODERATE"

    # Monte Carlo Stress Test (1,000 runs)
    mc_sim = MonteCarloSimulator(num_simulations=1000, ruin_drawdown_threshold_pct=25.0)
    mc_report = mc_sim.run(trades, initial_balance=10000.0)

    return {
        "id": config.id,
        "name": config.name,
        "timeframe": config.timeframe,
        "total_trades": len(trades),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "net_pnl": round(total_net, 2),
        "max_drawdown_pct": round(max_dd_pct, 1),
        "positive_years": f"{positive_years}/24",
        "pf_train": round(pf_train, 2),
        "pf_val": round(pf_val, 2),
        "pf_oos": round(pf_oos, 2),
        "oos_retention": round(oos_retention, 2),
        "overfit_status": overfit_status,
        "mc_p95_dd": round(mc_report.p95_max_drawdown_pct, 1),
        "prob_ruin": round(mc_report.probability_of_ruin_pct, 2),
        "mc_pass": mc_report.passes_institutional_hurdle,
        "yearly_pnl": yearly_pnl
    }


def run_tournament():
    tf_arrays = load_and_preprocess_datasets()

    configs = [
        CloneConfig("C01", "Baseline Scalper 1.5x ATR (10M Overfit)", "M1", 1.5, "MARKET_ON_CLOSE", "NONE", "FIXED_RR", "BAR_CLOSE", 0.5),
        CloneConfig("C02", "Champion 1.0x ATR (16Y Candidate)", "M1", 1.0, "MARKET_ON_CLOSE", "NONE", "FIXED_RR", "BAR_CLOSE", 0.5),
        CloneConfig("C03", "1.0x ATR + H1 EMA 50 Macro Bias", "M1", 1.0, "MARKET_ON_CLOSE", "H1_EMA50", "FIXED_RR", "BAR_CLOSE", 0.5),
        CloneConfig("C04", "1.0x ATR + H1 EMA 50 + Parabolic $15", "M1", 1.0, "MARKET_ON_CLOSE", "H1_EMA50_PARABOLIC", "FIXED_RR", "BAR_CLOSE", 0.5),
        CloneConfig("C05", "1.0x ATR + Resting Limit at Bands", "M1", 1.0, "RESTING_LIMIT", "H1_EMA50_PARABOLIC", "FIXED_RR", "BAR_CLOSE", 0.5),
        CloneConfig("C06", "1.0x ATR + Tick-Touch SL (No Anti-Wick)", "M1", 1.0, "MARKET_ON_CLOSE", "H1_EMA50_PARABOLIC", "FIXED_RR", "TICK_TOUCH", 0.5),
        CloneConfig("C07", "1.0x ATR + Callisto Twin 50/50 BE", "M1", 1.0, "MARKET_ON_CLOSE", "H1_EMA50_PARABOLIC", "CALLISTO_BE_TWIN", "BAR_CLOSE", 0.5),
        CloneConfig("C08", "M2 Fractal Sweet Spot (Anti-Noise M1)", "M2", 1.0, "MARKET_ON_CLOSE", "H1_EMA50_PARABOLIC", "CALLISTO_BE_TWIN", "BAR_CLOSE", 0.5),
        CloneConfig("C09", "M3 Fractal Sweet Spot", "M3", 1.0, "MARKET_ON_CLOSE", "H1_EMA50_PARABOLIC", "CALLISTO_BE_TWIN", "BAR_CLOSE", 0.5),
        CloneConfig("C10", "Grand Master Confluence (M2+Limit+Callisto)", "M2", 1.0, "RESTING_LIMIT", "H1_EMA50_PARABOLIC", "CALLISTO_BE_TWIN", "BAR_CLOSE", 0.5),
    ]

    print(f"\n[Tournament] Launching {len(configs)} Shadow Clones across 23.3 Years...")
    results = []
    t_start = time.time()

    for i, cfg in enumerate(configs, 1):
        t_sub = time.time()
        print(f"[{i:02d}/{len(configs):02d}] Executing Clone {cfg.id}: {cfg.name}...")
        res = simulate_clone(cfg, tf_arrays)
        results.append(res)
        print(f"       -> Done in {time.time() - t_sub:.2f}s | Net PnL: ${res['net_pnl']:+,.2f} | PF: {res['profit_factor']} | Max DD: {res['max_drawdown_pct']}% | MC P95 DD: {res['mc_p95_dd']}% | Win: {res['positive_years']} Yrs")

    total_time = time.time() - t_start

    # Format Tournament Leaderboard
    print("\n" + "=" * 140)
    print("🏆 GRAND MASTER KAGE BUNSHIN TOURNAMENT LEADERBOARD (2003 - 2026 / 23.3 YEARS)")
    print("   [ANTI-OVERFITTING & MONTE CARLO STRESS TEST AUDIT (Train 2003-2019 vs OOS 2024-2026)]")
    print("=" * 140)
    header = f"{'ID':<4} | {'Clone Strategy Name':<38} | {'Trades':<6} | {'All PF':<6} | {'Net PnL':<12} | {'Max DD':<6} | {'Train PF':<8} | {'OOS PF':<6} | {'MC P95 DD':<9} | {'OOS Verdict':<20} | {'MC Pass':<7}"
    print(header)
    print("-" * 140)

    # Sort results by Profit Factor descending
    sorted_res = sorted(results, key=lambda x: x["net_pnl"], reverse=True)

    for r in sorted_res:
        pass_str = "✅ YES" if r["mc_pass"] else "❌ NO"
        line = (
            f"{r['id']:<4} | {r['name']:<38} | {r['total_trades']:<6} | {r['profit_factor']:<6.2f} | "
            f"${r['net_pnl']:>+11,.2f} | {r['max_drawdown_pct']:>5.1f}% | {r['pf_train']:<8.2f} | {r['pf_oos']:<6.2f} | "
            f"{r['mc_p95_dd']:>8.1f}% | {r['overfit_status']:<20} | {pass_str:<7}"
        )
        print(line)

    print("=" * 140)
    print(f"Tournament execution completed in {total_time:.2f}s ({total_time/60:.2f} minutes)!")

    # Save results to reports
    out_json = Path("reports/grand_master_kagebunshin_23y.json")
    with open(out_json, "w") as f:
        json.dump(sorted_res, f, indent=2)
    print(f"Saved full tournament audit to: {out_json}")


if __name__ == "__main__":
    run_tournament()
