"""
Grand Master Kage Bunshin: 23.3-Year Institutional Parallel Tournament (2003 - 2026).
Simulates 60+ distinct multi-dimensional clones across 7,934,247 M1 bars testing:
1. Timeframes (M1, M2, M3)
2. Macro Trend Mechanics (BASELINE, BINARY_VETO, ASYMMETRIC_SIZING, DYNAMIC_TARGET, ATR_BUFFER)
3. H1 EMA Periods (20, 50, 100, 200)
4. Stop Loss Styles (SSOT WICK_BUFFER vs ATR_DISTANCE)
5. Stop Loss Execution Models (BAR_CLOSE Anti-Wick vs TICK_TOUCH)
6. Order Types (MARKET_ON_CLOSE vs RESTING_LIMIT)
7. Trade Management (VWAP_OR_RR vs CALLISTO_BE_TWIN)
8. Anti-Overfitting Partitioning (Train 2003-2019, Val 2020-2023, Blind OOS 2024-2026)
9. 1,000-Iteration Monte Carlo Stress Test (P95 Max DD, Risk of Ruin)
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

from engine.monte_carlo.simulator import MonteCarloSimulator

M1_PATH = Path("data/processed/bars/XAUUSD/M1/XAUUSD_M1_2003_2026.parquet")
M2_PATH = Path("data/processed/bars/XAUUSD/HTF/XAUUSD_M2_2003_2026.parquet")
M3_PATH = Path("data/processed/bars/XAUUSD/HTF/XAUUSD_M3_2003_2026.parquet")
H1_PATH = Path("data/processed/bars/XAUUSD/HTF/XAUUSD_H1_2003_2026.parquet")


@dataclass
class CloneConfig:
    id: str
    name: str
    timeframe: str              # "M1", "M2", "M3"
    mechanic: str               # "BASELINE", "BINARY_VETO", "ASYMMETRIC_SIZING", "DYNAMIC_TARGET", "ATR_BUFFER"
    ema_period: int             # 0, 20, 50, 100, 200
    with_trend_risk: float      # 0.50 or 0.65
    counter_trend_risk: float   # 0.20, 0.35, or 0.50
    with_trend_rr: float        # 2.0, 2.5, 3.0
    counter_trend_rr: float     # 1.5, 1.8, 2.0
    sl_style: str               # "WICK_BUFFER" or "ATR_DISTANCE"
    sl_model: str               # "BAR_CLOSE" or "TICK_TOUCH"
    exec_mode: str              # "MARKET_ON_CLOSE" or "RESTING_LIMIT"
    exit_model: str             # "VWAP_OR_RR" or "CALLISTO_BE_TWIN"
    atr_mult: float             # 1.0 or 1.5


def load_and_preprocess_datasets() -> Dict[str, Dict[str, np.ndarray]]:
    print("=" * 100)
    print("⚡ GRAND MASTER KAGE BUNSHIN: 60+ SHADOW CLONES TOURNAMENT (2003 - 2026 / 23.3 YEARS)")
    print("=" * 100)
    t0 = time.time()

    print("[Phase 1/3] Loading M1, M2, M3, and H1 Parquets...")
    df_m1 = pl.read_parquet(M1_PATH)
    df_m2 = pl.read_parquet(M2_PATH)
    df_m3 = pl.read_parquet(M3_PATH)
    df_h1 = pl.read_parquet(H1_PATH)
    print(f"  -> Loaded {len(df_m1):,} M1 bars & HTF series in {time.time() - t0:.2f}s.")

    # Precompute Macro H1 EMAs (20, 50, 100, 200) & ATR(14)
    print("[Phase 2/3] Precomputing Macro H1 EMAs (20, 50, 100, 200) & ATR...")
    df_h1_enriched = df_h1.with_columns([
        pl.col("timestamp").alias("h1_time"),
        pl.col("close").ewm_mean(span=20).alias("h1_ema20"),
        pl.col("close").ewm_mean(span=50).alias("h1_ema50"),
        pl.col("close").ewm_mean(span=100).alias("h1_ema100"),
        pl.col("close").ewm_mean(span=200).alias("h1_ema200"),
        (pl.col("high") - pl.col("low")).rolling_mean(window_size=14).alias("h1_atr14")
    ]).select(["h1_time", "h1_ema20", "h1_ema50", "h1_ema100", "h1_ema200", "h1_atr14"])

    def enrich_and_extract_arrays(df: pl.DataFrame, name: str) -> Dict[str, np.ndarray]:
        t_sub = time.time()

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

        # Left join H1 EMAs and ATR
        df_e = df_e.join(df_h1_enriched, on="h1_time", how="left").with_columns([
            pl.col("h1_ema20").fill_null(pl.col("close")),
            pl.col("h1_ema50").fill_null(pl.col("close")),
            pl.col("h1_ema100").fill_null(pl.col("close")),
            pl.col("h1_ema200").fill_null(pl.col("close")),
            pl.col("h1_atr14").fill_null(5.0)
        ])

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
            "ranges": golden["range"].to_numpy(),
            "spreads": golden["mean_spread"].to_numpy(),
            "vwaps": golden["vwap"].to_numpy(),
            "upper_18": golden["upper_18"].to_numpy(),
            "lower_18": golden["lower_18"].to_numpy(),
            "lower_wick": golden["lower_wick_ratio"].to_numpy(),
            "upper_wick": golden["upper_wick_ratio"].to_numpy(),
            "atr": golden["atr14"].fill_null(2.50).to_numpy(),
            "h1_ema20": golden["h1_ema20"].to_numpy(),
            "h1_ema50": golden["h1_ema50"].to_numpy(),
            "h1_ema100": golden["h1_ema100"].to_numpy(),
            "h1_ema200": golden["h1_ema200"].to_numpy(),
            "h1_atr14": golden["h1_atr14"].to_numpy(),
        }
        print(f"     Golden window {name}: {len(arrs['closes']):,} bars prepared in {time.time() - t_sub:.2f}s.")
        return arrs

    print("[Phase 3/3] Building Contiguous NumPy Matrices for M1, M2, M3...")
    tf_arrays = {
        "M1": enrich_and_extract_arrays(df_m1, "M1"),
        "M2": enrich_and_extract_arrays(df_m2, "M2"),
        "M3": enrich_and_extract_arrays(df_m3, "M3"),
    }
    print("✅ Preprocessing complete! Ready for 60+ multi-clone simulation.")
    return tf_arrays


class FastTrade:
    __slots__ = ("net_pnl", "year")
    def __init__(self, net_pnl: float, year: int):
        self.net_pnl = net_pnl
        self.year = year


def simulate_clone(config: CloneConfig, tf_arrays: Dict[str, Dict[str, np.ndarray]]) -> Dict[str, Any]:
    arrs = tf_arrays[config.timeframe]

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
    h1_atr = arrs["h1_atr14"]

    # Select appropriate EMA array
    if config.ema_period == 20:
        macro_ema = arrs["h1_ema20"]
    elif config.ema_period == 100:
        macro_ema = arrs["h1_ema100"]
    elif config.ema_period == 200:
        macro_ema = arrs["h1_ema200"]
    else:
        macro_ema = arrs["h1_ema50"]

    n_bars = len(closes)

    trades: List[FastTrade] = []
    equity = 10000.0
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
    daily_trades = 0
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
            daily_trades = 0
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

        # Governor 2-Strike rule & daily loss cap
        if daily_trades >= 2 or daily_losses >= 2 or daily_pnl <= -100.0:
            continue

        # Spread & minimal range filters
        sp = spreads[i]
        vw = vwaps[i]
        at = atr[i]
        me = macro_ema[i]
        h_atr = h1_atr[i]
        low_18 = lower_18[i]
        up_18 = upper_18[i]
        rg = ranges[i]

        if sp > 0.45 or rg < 0.35 or vw <= 0:
            continue

        # Evaluate Macro Trend
        is_bull = (c > me)
        is_bear = (c < me)

        allow_buy = True
        allow_sell = True
        buy_risk = config.with_trend_risk
        sell_risk = config.with_trend_risk
        buy_rr = config.with_trend_rr
        sell_rr = config.with_trend_rr

        if config.mechanic == "BINARY_VETO":
            if is_bull:
                allow_sell = False
            elif is_bear:
                allow_buy = False

        elif config.mechanic == "ASYMMETRIC_SIZING":
            if is_bull:
                buy_risk = config.with_trend_risk
                sell_risk = config.counter_trend_risk
            else:
                buy_risk = config.counter_trend_risk
                sell_risk = config.with_trend_risk

        elif config.mechanic == "DYNAMIC_TARGET":
            if is_bull:
                buy_rr = config.with_trend_rr
                sell_rr = config.counter_trend_rr
            else:
                buy_rr = config.counter_trend_rr
                sell_rr = config.with_trend_rr

        elif config.mechanic == "ATR_BUFFER":
            if is_bear and (me - c) > (config.atr_mult * h_atr):
                allow_buy = False
            if is_bull and (c - me) > (config.atr_mult * h_atr):
                allow_sell = False

        # BUY trigger
        buy_signal = False
        sell_signal = False

        if config.exec_mode == "MARKET_ON_CLOSE":
            if l <= low_18 and lower_wick[i] >= 0.45 and c > o and allow_buy:
                buy_signal = True
            elif h >= up_18 and upper_wick[i] >= 0.45 and c < o and allow_sell:
                sell_signal = True
        elif config.exec_mode == "RESTING_LIMIT":
            if l <= low_18 and allow_buy:
                buy_signal = True
            elif h >= up_18 and allow_sell:
                sell_signal = True

        if buy_signal:
            pos_entry = low_18 if config.exec_mode == "RESTING_LIMIT" else c
            if config.sl_style == "WICK_BUFFER":
                pos_sl = round(l - 0.50, 2)
                risk = round(pos_entry - pos_sl, 2)
            else:
                risk = round(max(0.80, at * config.atr_mult), 2)
                pos_sl = round(pos_entry - risk, 2)

            if 0.80 <= risk <= 5.00:
                pos_tp = round(pos_entry + (risk * buy_rr), 2)
                if config.exit_model == "VWAP_OR_RR" and vw > pos_entry and (vw - pos_entry) >= risk * 1.5:
                    pos_tp = round(vw, 2)

                risk_dollars = equity * (buy_risk / 100.0)
                pos_lots = round(max(0.01, min(5.0, risk_dollars / (risk * 100.0))), 2)
                in_position = True
                pos_dir = 1
                bars_held = 0
                half_closed = False
                daily_trades += 1

        elif sell_signal:
            pos_entry = up_18 if config.exec_mode == "RESTING_LIMIT" else c
            if config.sl_style == "WICK_BUFFER":
                pos_sl = round(h + 0.50, 2)
                risk = round(pos_sl - pos_entry, 2)
            else:
                risk = round(max(0.80, at * config.atr_mult), 2)
                pos_sl = round(pos_entry + risk, 2)

            if 0.80 <= risk <= 5.00:
                pos_tp = round(pos_entry - (risk * sell_rr), 2)
                if config.exit_model == "VWAP_OR_RR" and vw < pos_entry and (pos_entry - vw) >= risk * 1.5:
                    pos_tp = round(vw, 2)

                risk_dollars = equity * (sell_risk / 100.0)
                pos_lots = round(max(0.01, min(5.0, risk_dollars / (risk * 100.0))), 2)
                in_position = True
                pos_dir = -1
                bars_held = 0
                half_closed = False
                daily_trades += 1

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


def generate_60_clone_specifications() -> List[CloneConfig]:
    configs = []
    c_idx = 1

    # 1. Baseline Benchmark across M1, M2, M3
    for tf in ["M1", "M2", "M3"]:
        configs.append(CloneConfig(
            f"C{c_idx:02d}", f"Baseline Pure VWAP 1.8s ({tf})", tf,
            "BASELINE", 0, 0.50, 0.50, 2.0, 2.0, "WICK_BUFFER", "BAR_CLOSE", "MARKET_ON_CLOSE", "VWAP_OR_RR", 1.5
        ))
        c_idx += 1

    # 2. Binary Veto across Timeframes & EMA periods (20, 50, 100, 200)
    for tf in ["M1", "M2", "M3"]:
        for ema in [20, 50, 100, 200]:
            configs.append(CloneConfig(
                f"C{c_idx:02d}", f"Binary Veto {tf} H1 EMA {ema}", tf,
                "BINARY_VETO", ema, 0.50, 0.50, 2.0, 2.0, "WICK_BUFFER", "BAR_CLOSE", "MARKET_ON_CLOSE", "VWAP_OR_RR", 1.5
            ))
            c_idx += 1

    # 3. Asymmetric Sizing: With-trend 0.65% vs Counter-trend 0.20% or 0.35%
    for tf in ["M1", "M2"]:
        for ema in [50, 100, 200]:
            for c_risk in [0.20, 0.35]:
                configs.append(CloneConfig(
                    f"C{c_idx:02d}", f"Asymm Sizing {tf} EMA {ema} (With 0.65% / Counter {int(c_risk*100)}%)", tf,
                    "ASYMMETRIC_SIZING", ema, 0.65, c_risk, 2.0, 2.0, "WICK_BUFFER", "BAR_CLOSE", "MARKET_ON_CLOSE", "VWAP_OR_RR", 1.5
                ))
                c_idx += 1

    # 4. Dynamic Target Expansion: With-trend 2.5R/3.0R vs Counter-trend 1.5R/VWAP
    for tf in ["M1", "M2"]:
        for ema in [20, 50, 200]:
            for w_rr in [2.5, 3.0]:
                configs.append(CloneConfig(
                    f"C{c_idx:02d}", f"Dynamic Target {tf} EMA {ema} (With {w_rr}R / Counter 1.5R)", tf,
                    "DYNAMIC_TARGET", ema, 0.50, 0.50, w_rr, 1.5, "WICK_BUFFER", "BAR_CLOSE", "MARKET_ON_CLOSE", "VWAP_OR_RR", 1.5
                ))
                c_idx += 1

    # 5. ATR Buffer Gate: Only veto counter-trend if distance > 1.0x or 1.5x ATR
    for tf in ["M1", "M2"]:
        for ema in [50, 200]:
            for mult in [1.0, 1.5, 2.0]:
                configs.append(CloneConfig(
                    f"C{c_idx:02d}", f"ATR Buffer {tf} EMA {ema} (Dist > {mult}x ATR)", tf,
                    "ATR_BUFFER", ema, 0.65, 0.35, 2.5, 1.8, "WICK_BUFFER", "BAR_CLOSE", "MARKET_ON_CLOSE", "VWAP_OR_RR", mult
                ))
                c_idx += 1

    # 6. Stop Loss Model Comparison: WICK_BUFFER vs ATR_DISTANCE vs TICK_TOUCH
    for sl_m in ["BAR_CLOSE", "TICK_TOUCH"]:
        for style in ["WICK_BUFFER", "ATR_DISTANCE"]:
            for mult in [1.0, 1.5]:
                configs.append(CloneConfig(
                    f"C{c_idx:02d}", f"SL Audit M1 ({style} {mult}x | {sl_m})", "M1",
                    "ATR_BUFFER", 50, 0.50, 0.35, 2.0, 1.8, style, sl_m, "MARKET_ON_CLOSE", "VWAP_OR_RR", mult
                ))
                c_idx += 1

    # 7. Order Execution Type: MARKET_ON_CLOSE vs RESTING_LIMIT
    for exec_m in ["MARKET_ON_CLOSE", "RESTING_LIMIT"]:
        for tf in ["M1", "M2"]:
            for exit_m in ["VWAP_OR_RR", "CALLISTO_BE_TWIN"]:
                configs.append(CloneConfig(
                    f"C{c_idx:02d}", f"Exec Mode {tf} {exec_m} ({exit_m})", tf,
                    "ATR_BUFFER", 50, 0.50, 0.35, 2.5, 1.8, "WICK_BUFFER", "BAR_CLOSE", exec_m, exit_m, 1.5
                ))
                c_idx += 1

    return configs


def run_tournament():
    tf_arrays = load_and_preprocess_datasets()
    configs = generate_60_clone_specifications()

    print(f"\n[Tournament] Launching {len(configs)} Grand Master Shadow Clones across 23.3 Years...")
    results = []
    t_start = time.time()

    for i, cfg in enumerate(configs, 1):
        t_sub = time.time()
        res = simulate_clone(cfg, tf_arrays)
        results.append(res)
        elapsed = time.time() - t_sub
        if i % 10 == 0 or i == 1 or i == len(configs) or res["net_pnl"] > 0:
            status_icon = "🟢" if res["net_pnl"] > 0 else "🔴"
            print(f"[{i:02d}/{len(configs):02d}] {status_icon} {cfg.name:<60} | PnL: ${res['net_pnl']:>10,.2f} | PF: {res['profit_factor']:>4.2f} | Win: {res['win_rate']:>4.1f}% | DD: {res['max_drawdown_pct']:>4.1f}% | MC P95: {res['mc_p95_dd']:>5.1f}% ({elapsed:.2f}s)")

    total_time = time.time() - t_start

    # Format Tournament Leaderboard
    print("\n" + "=" * 145)
    print(f"🏆 GRAND MASTER KAGE BUNSHIN TOURNAMENT LEADERBOARD ({len(configs)} CLONES / 2003 - 2026 / 23.3 YEARS)")
    print("   [RANKED BY NET PNL & PROFIT FACTOR | 70/15/15 ANTI-OVERFITTING & 1,000 MONTE CARLO RUNS]")
    print("=" * 145)
    header = f"{'Rank':<5} | {'ID':<4} | {'Clone Strategy Name':<42} | {'Trades':<6} | {'All PF':<6} | {'Net PnL':<12} | {'Max DD':<6} | {'Train PF':<8} | {'OOS PF':<6} | {'MC P95 DD':<9} | {'OOS Verdict':<20} | {'MC Pass':<7}"
    print(header)
    print("-" * 145)

    # Sort results primarily by Net PnL, then Profit Factor
    sorted_res = sorted(results, key=lambda x: (x["net_pnl"], x["profit_factor"]), reverse=True)

    for rank, r in enumerate(sorted_res[:25], 1):
        pass_str = "✅ YES" if r["mc_pass"] else "❌ NO"
        line = (
            f"#{rank:<4} | {r['id']:<4} | {r['name']:<42} | {r['total_trades']:<6} | {r['profit_factor']:<6.2f} | "
            f"${r['net_pnl']:>+11,.2f} | {r['max_drawdown_pct']:>5.1f}% | {r['pf_train']:<8.2f} | {r['pf_oos']:<6.2f} | "
            f"{r['mc_p95_dd']:>8.1f}% | {r['overfit_status']:<20} | {pass_str:<7}"
        )
        print(line)

    print("=" * 145)
    print(f"Grand Master Tournament completed in {total_time:.2f}s ({total_time/60:.2f} minutes)!")

    # Save results to reports
    out_json = Path("reports/grand_master_kagebunshin_23y.json")
    with open(out_json, "w") as f:
        json.dump(sorted_res, f, indent=2)
    print(f"Saved complete audit of all {len(results)} clones to: {out_json}")


if __name__ == "__main__":
    run_tournament()
