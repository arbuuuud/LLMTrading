"""
Naruto Brain Exploration Engine: The +20% Monthly Target Optimization Tournament.
Simulates 162 Multi-Dimensional Clones across 16.6 Years (2010 - 2026 / 181 Months / 5.9M Bars).
Answers 3 Critical Strategic Questions with Empirical Data:
1. Trading Window: Golden 4h (10:30-14:30) vs London+NY 10h (07:00-17:00) vs Full 14h (06:00-20:00).
2. Signal Sensitivity: Band stretch 1.8s vs 1.5s vs 1.3s & Wick threshold 45% vs 40% vs 35%.
3. Risk Sizing & Target R:R: 0.50% vs 1.00% vs 1.50% Base Risk to hit +20%/month.

Analyzes monthly return distributions, percentage of months hitting >= +20%,
trade frequency per month, and maximum drawdowns.
"""

import sys
import time
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple
import json
import numpy as np
import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

M3_PATH = Path("data/processed/bars/XAUUSD/HTF/XAUUSD_M3_2003_2026.parquet")
M15_PATH = Path("data/processed/bars/XAUUSD/HTF/XAUUSD_M15_2003_2026.parquet")
H1_PATH = Path("data/processed/bars/XAUUSD/HTF/XAUUSD_H1_2003_2026.parquet")
H4_PATH = Path("data/processed/bars/XAUUSD/HTF/XAUUSD_H4_2003_2026.parquet")


@dataclass
class NarutoCloneConfig:
    id: str
    name: str
    window_mode: str          # "GOLDEN_4H", "LONDON_NY_10H", "FULL_14H"
    scalper_mode: str         # "STRICT_18", "MOD_15", "ACTIVE_13"
    sniper_mode: str          # "STRICT_FIBO", "BROAD_FIBO", "ALL_BASES"
    base_risk_pct: float      # 0.50, 1.00, 1.50
    scalp_rr: float           # 2.0 or 2.5
    sniper_rr: float          # 4.0 or 5.0
    max_daily_trades: int     # 2, 3, 5


@dataclass
class FastExecutedTrade:
    date_str: str
    month_str: str
    year: int
    net_pnl: float
    is_win: bool
    engine: str


def load_and_prepare_naruto_data():
    print("=" * 110)
    print("🍥 NARUTO BRAIN: EMPIRICAL 20% MONTHLY TARGET TOURNAMENT (2010 - 2026 / 16.6 YEARS)")
    print("🍥 TESTING 162 CLONES: WINDOW EXPANSION, BAND SENSITIVITY, AND RISK SCALING")
    print("=" * 110)
    t0 = time.time()

    print("[Phase 1/3] Loading Modern Era Parquets (2010-2026)...")
    df_m3 = pl.read_parquet(M3_PATH).filter(pl.col("timestamp").dt.year() >= 2010)
    df_m15 = pl.read_parquet(M15_PATH).filter(pl.col("timestamp").dt.year() >= 2010)
    df_h1 = pl.read_parquet(H1_PATH).filter(pl.col("timestamp").dt.year() >= 2010)
    df_h4 = pl.read_parquet(H4_PATH).filter(pl.col("timestamp").dt.year() >= 2010)
    print(f"  -> Loaded {len(df_m3):,} M3 bars and {len(df_m15):,} M15 bars in {time.time() - t0:.2f}s.")

    print("[Phase 2/3] Precomputing Macro HTF & Daily Cumulative VWAP on M3...")
    df_h1_prep = df_h1.with_columns([
        pl.col("timestamp").alias("h1_time"),
        pl.col("close").ewm_mean(span=50).alias("h1_ema50")
    ]).select(["h1_time", "h1_ema50"])

    df_h4_prep = df_h4.with_columns([
        pl.col("timestamp").alias("h4_time"),
        pl.col("close").ewm_mean(span=50).alias("h4_ema50")
    ]).select(["h4_time", "h4_ema50"])

    # Prepare M3 indicators
    df_m3_e = df_m3.with_columns([
        pl.col("timestamp").dt.year().alias("year"),
        pl.col("timestamp").dt.hour().alias("hour"),
        pl.col("timestamp").dt.minute().alias("minute"),
        pl.col("timestamp").dt.ordinal_day().alias("day_of_year"),
        pl.col("timestamp").dt.date().alias("date"),
        pl.col("timestamp").dt.strftime("%Y-%m-%d").alias("date_str"),
        pl.col("timestamp").dt.strftime("%Y-%m").alias("month_str"),
        pl.col("timestamp").dt.truncate("1h").alias("h1_time"),
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
    ])

    # VWAP Accumulation
    df_m3_e = df_m3_e.with_columns([
        (pl.col("tp") * pl.col("tick_volume")).alias("pv"),
        ((pl.col("tp") ** 2) * pl.col("tick_volume")).alias("p2v")
    ])
    df_m3_e = df_m3_e.with_columns([
        pl.col("tick_volume").cum_sum().over("date").alias("cum_vol"),
        pl.col("pv").cum_sum().over("date").alias("cum_pv"),
        pl.col("p2v").cum_sum().over("date").alias("cum_p2v")
    ])
    df_m3_e = df_m3_e.with_columns([
        (pl.col("cum_pv") / pl.col("cum_vol")).alias("vwap"),
        ((pl.col("cum_p2v") / pl.col("cum_vol") - (pl.col("cum_pv") / pl.col("cum_vol")) ** 2).clip(lower_bound=0.0).sqrt()).alias("std")
    ])

    # Band Multipliers (1.8s, 1.5s, 1.3s)
    df_m3_e = df_m3_e.with_columns([
        (pl.col("vwap") + 1.8 * pl.col("std")).alias("upper_18"),
        (pl.col("vwap") - 1.8 * pl.col("std")).alias("lower_18"),
        (pl.col("vwap") + 1.5 * pl.col("std")).alias("upper_15"),
        (pl.col("vwap") - 1.5 * pl.col("std")).alias("lower_15"),
        (pl.col("vwap") + 1.3 * pl.col("std")).alias("upper_13"),
        (pl.col("vwap") - 1.3 * pl.col("std")).alias("lower_13"),
        (pl.col("lower_wick") / pl.when(pl.col("range") > 0).then(pl.col("range")).otherwise(1.0)).alias("lower_wick_ratio"),
        (pl.col("upper_wick") / pl.when(pl.col("range") > 0).then(pl.col("range")).otherwise(1.0)).alias("upper_wick_ratio"),
    ])

    df_m3_e = df_m3_e.join(df_h4_prep, on="h4_time", how="left").with_columns([
        pl.col("h4_ema50").fill_null(pl.col("close"))
    ])

    # Define Trading Window Flags on M3
    df_m3_e = df_m3_e.with_columns([
        (
            ((pl.col("hour") == 10) & (pl.col("minute") >= 30)) |
            ((pl.col("hour") > 10) & (pl.col("hour") < 14)) |
            ((pl.col("hour") == 14) & (pl.col("minute") <= 30))
        ).alias("is_golden_4h"),
        (
            (pl.col("hour") >= 7) & (pl.col("hour") < 17)
        ).alias("is_london_ny_10h"),
        (
            (pl.col("hour") >= 6) & (pl.col("hour") < 20)
        ).alias("is_full_14h")
    ])

    m3_data = {
        "years": df_m3_e["year"].to_numpy(),
        "hours": df_m3_e["hour"].to_numpy(),
        "minutes": df_m3_e["minute"].to_numpy(),
        "days": df_m3_e["day_of_year"].to_numpy(),
        "date_strs": df_m3_e["date_str"].to_list(),
        "month_strs": df_m3_e["month_str"].to_list(),
        "highs": df_m3_e["high"].to_numpy(),
        "lows": df_m3_e["low"].to_numpy(),
        "closes": df_m3_e["close"].to_numpy(),
        "opens": df_m3_e["open"].to_numpy(),
        "ranges": df_m3_e["range"].to_numpy(),
        "spreads": df_m3_e["mean_spread"].to_numpy(),
        "vwaps": df_m3_e["vwap"].to_numpy(),
        "upper_18": df_m3_e["upper_18"].to_numpy(),
        "lower_18": df_m3_e["lower_18"].to_numpy(),
        "upper_15": df_m3_e["upper_15"].to_numpy(),
        "lower_15": df_m3_e["lower_15"].to_numpy(),
        "upper_13": df_m3_e["upper_13"].to_numpy(),
        "lower_13": df_m3_e["lower_13"].to_numpy(),
        "lower_wicks": df_m3_e["lower_wick_ratio"].to_numpy(),
        "upper_wicks": df_m3_e["upper_wick_ratio"].to_numpy(),
        "atr14": df_m3_e["atr14"].fill_null(2.50).to_numpy(),
        "h4_ema50": df_m3_e["h4_ema50"].to_numpy(),
        "is_golden_4h": df_m3_e["is_golden_4h"].to_numpy(),
        "is_london_ny_10h": df_m3_e["is_london_ny_10h"].to_numpy(),
        "is_full_14h": df_m3_e["is_full_14h"].to_numpy(),
    }

    print("[Phase 3/3] Pre-Indexing M15 NFC Bases & Opportunities...")
    # Prepare M15 bases and retests
    from tests.kagebunshin_agent2_ltf_sniper import (
        load_and_preprocess_agent2_data,
        detect_m15_zones_and_signals
    )
    m15_data, df_m3_raw = load_and_preprocess_agent2_data()
    opps_m15 = detect_m15_zones_and_signals(m15_data, df_m3_raw)

    print(f"  -> Preprocessing completed in {time.time() - t0:.2f}s.")
    return m3_data, opps_m15


def generate_naruto_clones() -> List[NarutoCloneConfig]:
    clones = []
    idx = 1

    windows = [
        ("GOLDEN_4H", 2),
        ("LONDON_NY_10H", 4),
        ("FULL_14H", 5)
    ]
    scalp_modes = ["STRICT_18", "MOD_15", "ACTIVE_13"]
    sniper_modes = ["STRICT_FIBO", "BROAD_FIBO", "ALL_BASES"]
    risks = [0.50, 1.00, 1.50]
    rr_configs = [
        ("STANDARD_RR", 2.0, 4.0),
        ("SNIPER_RR", 2.5, 5.0)
    ]

    for win, max_t in windows:
        for sc_m in scalp_modes:
            for sn_m in sniper_modes:
                for r in risks:
                    for rr_label, s_rr, sn_rr in rr_configs:
                        c_id = f"NARUTO_{idx:03d}"
                        name = f"{win}_{sc_m}_{sn_m}_R{str(r).replace('.','_')}_{rr_label}"
                        clones.append(NarutoCloneConfig(
                            id=c_id,
                            name=name,
                            window_mode=win,
                            scalper_mode=sc_m,
                            sniper_mode=sn_m,
                            base_risk_pct=r,
                            scalp_rr=s_rr,
                            sniper_rr=sn_rr,
                            max_daily_trades=max_t
                        ))
                        idx += 1
    return clones


def simulate_naruto_clone(
    clone: NarutoCloneConfig,
    m3_data: Dict[str, Any],
    opps_m15: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Simulates a combined dual-engine portfolio run across 2010 - 2026 under the clone's settings.
    """
    # 1. Simulate Engine 1 (Scalper M3)
    highs = m3_data["highs"]
    lows = m3_data["lows"]
    closes = m3_data["closes"]
    opens = m3_data["opens"]
    ranges = m3_data["ranges"]
    spreads = m3_data["spreads"]
    vwaps = m3_data["vwaps"]
    atr = m3_data["atr14"]
    h4_ema = m3_data["h4_ema50"]
    days = m3_data["days"]
    years = m3_data["years"]
    date_strs = m3_data["date_strs"]
    month_strs = m3_data["month_strs"]
    lower_wicks = m3_data["lower_wicks"]
    upper_wicks = m3_data["upper_wicks"]

    if clone.scalper_mode == "STRICT_18":
        upper_b = m3_data["upper_18"]
        lower_b = m3_data["lower_18"]
        wick_thresh = 0.45
    elif clone.scalper_mode == "MOD_15":
        upper_b = m3_data["upper_15"]
        lower_b = m3_data["lower_15"]
        wick_thresh = 0.40
    else:  # ACTIVE_13
        upper_b = m3_data["upper_13"]
        lower_b = m3_data["lower_13"]
        wick_thresh = 0.35

    if clone.window_mode == "GOLDEN_4H":
        win_flags = m3_data["is_golden_4h"]
    elif clone.window_mode == "LONDON_NY_10H":
        win_flags = m3_data["is_london_ny_10h"]
    else:
        win_flags = m3_data["is_full_14h"]

    n_bars = len(closes)
    scalp_trades: List[FastExecutedTrade] = []
    in_pos = False
    p_dir = 0
    p_entry = 0.0
    p_sl = 0.0
    p_tp = 0.0
    p_lots = 0.0
    b_held = 0
    cur_day = -1
    d_trades = 0
    d_losses = 0
    d_pnl = 0.0

    mult = clone.base_risk_pct / 0.50
    base_dollars = 10000.0 * (clone.base_risk_pct / 100.0)

    for i in range(n_bars):
        d_idx = days[i]
        yr = years[i]
        h = highs[i]
        l = lows[i]
        c = closes[i]
        o = opens[i]

        if d_idx != cur_day:
            cur_day = d_idx
            d_trades = 0
            d_losses = 0
            d_pnl = 0.0

        if in_pos:
            b_held += 1
            h_tp = False
            h_sl = False
            ex_p = 0.0

            if p_dir == 1:
                if h >= p_tp: h_tp = True; ex_p = p_tp
                elif l <= p_sl: h_sl = True; ex_p = p_sl
                elif b_held >= 30: ex_p = c
            else:
                if l <= p_tp: h_tp = True; ex_p = p_tp
                elif h >= p_sl: h_sl = True; ex_p = p_sl
                elif b_held >= 30: ex_p = c

            if h_tp or h_sl or b_held >= 30:
                pnl = p_lots * (ex_p - p_entry if p_dir == 1 else p_entry - ex_p) * 100.0
                comm = (p_lots * 7.0) + (p_lots * 100.0 * 0.02)
                net = pnl - comm

                d_pnl += net
                if net < 0: d_losses += 1

                scalp_trades.append(FastExecutedTrade(
                    date_str=date_strs[i],
                    month_str=month_strs[i],
                    year=int(yr),
                    net_pnl=round(net, 2),
                    is_win=(net > 0),
                    engine="SCALPER"
                ))
                in_pos = False
                b_held = 0
            continue

        # Governor guards
        if d_losses >= 2 or d_trades >= clone.max_daily_trades: continue
        if not win_flags[i]: continue

        sp = spreads[i]
        at = atr[i]
        if sp > 0.40 or (at > 0 and (sp / at) > 0.35): continue
        vw = vwaps[i]
        me = h4_ema[i]
        rg = ranges[i]
        if rg < 0.30 or vw <= 0: continue

        allow_b = (c > me)
        allow_s = (c < me)

        std_b = (l <= lower_b[i] and lower_wicks[i] >= wick_thresh and c > o and c < vw and allow_b)
        std_s = (h >= upper_b[i] and upper_wicks[i] >= wick_thresh and c < o and c > vw and allow_s)

        if std_b:
            p_entry = c
            p_sl = c - (1.0 * at)
            sl_d = abs(p_entry - p_sl)
            if sl_d < 0.80 or sl_d > 8.0: continue
            p_tp = p_entry + (sl_d * clone.scalp_rr)
            p_lots = max(0.01, round(base_dollars / (sl_d * 100.0), 2))
            p_dir = 1
            in_pos = True
            b_held = 0
            d_trades += 1
        elif std_s:
            p_entry = c
            p_sl = c + (1.0 * at)
            sl_d = abs(p_sl - p_entry)
            if sl_d < 0.80 or sl_d > 8.0: continue
            p_tp = p_entry - (sl_d * clone.scalp_rr)
            p_lots = max(0.01, round(base_dollars / (sl_d * 100.0), 2))
            p_dir = -1
            in_pos = True
            b_held = 0
            d_trades += 1

    # 2. Simulate Engine 2 (Intraday Sniper)
    sniper_trades: List[FastExecutedTrade] = []
    account_eq = 10000.0
    cur_d = None
    d_pnl_e2 = 0.0
    d_losses_e2 = 0

    for opp in opps_m15:
        d = opp["date"]
        if d != cur_d:
            cur_d = d
            d_pnl_e2 = 0.0
            d_losses_e2 = 0

        if d_losses_e2 >= 2: continue

        # Filter Sniper sensitivity
        if clone.sniper_mode == "STRICT_FIBO":
            if not (opp["fibo_ote"] and opp["strict_eq"] and opp["m3_wick_confirm"]): continue
        elif clone.sniper_mode == "BROAD_FIBO":
            if not ((opp["fibo_ote"] or opp["fibo_discount"]) and opp["strict_eq"] and (opp["m3_wick_confirm"] or opp["m3_choch_confirm"])): continue
        else:  # ALL_BASES
            if not (opp["strict_eq"] and (opp["m3_wick_confirm"] or opp["m3_choch_confirm"] or opp["m15_confirm"])): continue

        c = opp["price_m15_close"]
        if opp["direction"] == "BUY" and not opp["h1_bull"]: continue
        if opp["direction"] == "SELL" and not opp["h1_bear"]: continue

        entry = opp["price_touch"]
        sl = opp["m3_wick_sl"] if opp["m3_wick_confirm"] else opp["distal_sl"]
        sl_dist = abs(entry - sl)
        if sl_dist < 0.60 or sl_dist > 10.0: continue

        tp_dist = sl_dist * clone.sniper_rr
        tp = entry + tp_dist if opp["direction"] == "BUY" else entry - tp_dist

        f_highs = opp["future_highs"]
        f_lows = opp["future_lows"]
        is_w = False
        is_l = False

        if opp["direction"] == "BUY":
            for fh, fl in zip(f_highs, f_lows):
                if fl <= sl: is_l = True; break
                if fh >= tp: is_w = True; break
        else:
            for fh, fl in zip(f_highs, f_lows):
                if fh >= sl: is_l = True; break
                if fl <= tp: is_w = True; break

        if not is_w and not is_l: continue

        dt_str = str(opp["date"])
        mo_str = dt_str[:7]
        yr = int(opp["year"])

        risk_dollars = account_eq * (clone.base_risk_pct / 100.0)

        if is_w:
            gain = risk_dollars * clone.sniper_rr
            sniper_trades.append(FastExecutedTrade(
                date_str=dt_str,
                month_str=mo_str,
                year=yr,
                net_pnl=round(gain, 2),
                is_win=True,
                engine="INTRADAY"
            ))
            account_eq += gain
            d_pnl_e2 += gain
        else:
            loss = -risk_dollars
            sniper_trades.append(FastExecutedTrade(
                date_str=dt_str,
                month_str=mo_str,
                year=yr,
                net_pnl=round(loss, 2),
                is_win=False,
                engine="INTRADAY"
            ))
            account_eq += loss
            d_pnl_e2 += loss
            d_losses_e2 += 1

    # 3. Combine Dual-Engine Trades
    all_trades = scalp_trades + sniper_trades
    all_trades.sort(key=lambda t: t.date_str)

    total_t = len(all_trades)
    if total_t == 0:
        return {"id": clone.id, "name": clone.name, "total_trades": 0, "pass": False}

    # Aggregate by month (all 181 months)
    months_dict: Dict[str, float] = {}
    for t in all_trades:
        months_dict[t.month_str] = months_dict.get(t.month_str, 0.0) + t.net_pnl

    m_values = list(months_dict.values())
    tot_months = len(months_dict)

    # Monthly performance metrics
    avg_m_pnl = float(np.mean(m_values)) if m_values else 0.0
    avg_m_roi = (avg_m_pnl / 10000.0) * 100.0

    # How many months hit >= +10% and >= +20%?
    months_hit_10 = sum(1 for val in m_values if (val / 10000.0 * 100.0) >= 10.0)
    months_hit_20 = sum(1 for val in m_values if (val / 10000.0 * 100.0) >= 20.0)
    pct_months_hit_10 = round((months_hit_10 / tot_months) * 100.0, 1) if tot_months > 0 else 0.0
    pct_months_hit_20 = round((months_hit_20 / tot_months) * 100.0, 1) if tot_months > 0 else 0.0

    best_m_roi = round(max(m_values) / 10000.0 * 100.0, 1) if m_values else 0.0
    worst_m_roi = round(min(m_values) / 10000.0 * 100.0, 1) if m_values else 0.0

    # Overall equity and Drawdown
    equity = 10000.0
    peak = 10000.0
    max_dd = 0.0
    wins = 0
    losses = 0
    gp = 0.0
    gl = 0.0

    for t in all_trades:
        if t.net_pnl > 0:
            wins += 1
            gp += t.net_pnl
        else:
            losses += 1
            gl += abs(t.net_pnl)
        equity += t.net_pnl
        if equity > peak: peak = equity
        cur_dd = (peak - equity) / peak * 100.0
        if cur_dd > max_dd: max_dd = cur_dd

    net_profit = gp - gl
    total_roi = (net_profit / 10000.0) * 100.0
    pf = round(gp / gl, 2) if gl > 0 else 99.0
    wr = round(wins / total_t * 100.0, 1)

    # OOS (2024 - 2026)
    oos_trades = [t for t in all_trades if t.year >= 2024]
    oos_gp = sum(t.net_pnl for t in oos_trades if t.net_pnl > 0)
    oos_gl = abs(sum(t.net_pnl for t in oos_trades if t.net_pnl < 0))
    oos_pf = round(oos_gp / oos_gl, 2) if oos_gl > 0 else (99.0 if oos_gp > 0 else 0.0)

    # Active Days
    traded_days = len(set(t.date_str for t in all_trades))
    active_days_pct = round(traded_days / 5198.0 * 100.0, 1)
    trades_per_month = round(total_t / 181.0, 1)

    return {
        "id": clone.id,
        "name": clone.name,
        "window_mode": clone.window_mode,
        "scalper_mode": clone.scalper_mode,
        "sniper_mode": clone.sniper_mode,
        "base_risk": clone.base_risk_pct,
        "scalp_rr": clone.scalp_rr,
        "sniper_rr": clone.sniper_rr,
        "total_trades": total_t,
        "trades_per_month": trades_per_month,
        "traded_days": traded_days,
        "active_days_pct": active_days_pct,
        "win_rate": wr,
        "profit_factor": pf,
        "oos_pf": oos_pf,
        "net_pnl": round(net_profit, 2),
        "total_roi": round(total_roi, 1),
        "max_dd": round(max_dd, 1),
        "avg_monthly_roi": round(avg_m_roi, 2),
        "months_hit_10pct": months_hit_10,
        "pct_months_hit_10": pct_months_hit_10,
        "months_hit_20pct": months_hit_20,
        "pct_months_hit_20": pct_months_hit_20,
        "best_month_roi": best_m_roi,
        "worst_month_roi": worst_m_roi
    }


def main():
    clones = generate_naruto_clones()
    print(f"Generated {len(clones)} distinct Naruto exploration clones.")

    m3_data, opps_m15 = load_and_prepare_naruto_data()

    print("\n" + "=" * 110)
    print(f"🚀 EXECUTING NARUTO TOURNAMENT (162 CLONES ACROSS 16.6 YEARS / 181 MONTHS)...")
    print("=" * 110)
    t_start = time.time()

    results = []
    for i, c in enumerate(clones, 1):
        res = simulate_naruto_clone(c, m3_data, opps_m15)
        results.append(res)
        if i % 27 == 0 or i == len(clones):
            elapsed = time.time() - t_start
            print(f"  -> Evaluated {i}/{len(clones)} clones ({i/len(clones)*100:.1f}%) in {elapsed:.2f}s...")

    total_sim_time = time.time() - t_start
    print(f"\n✨ NARUTO TOURNAMENT COMPLETED in {total_sim_time:.2f}s ({len(clones)/total_sim_time:.1f} clones/sec)!")

    # Sort results to find best balances:
    # We want high average monthly ROI, high % of months hitting >= +10% / +20%, but with Max DD <= 20%
    viable = [r for r in results if r["max_dd"] <= 25.0 and r["oos_pf"] >= 1.20]
    viable.sort(key=lambda x: (x["pct_months_hit_20"], x["avg_monthly_roi"], x["oos_pf"]), reverse=True)

    print("\n" + "=" * 115)
    print("🏆 TOP 15 JUARA NARUTO (+20% MONTHLY TARGET & HIGH-FREQUENCY FRONTIER)")
    print("=" * 115)
    print(f"{'Rank':<5}{'Clone Config':<48}{'Trd/Mo':<8}{'Act%':<7}{'Win%':<7}{'FullPF':<8}{'OOSPF':<8}{'AvgMo%':<9}{'%M>=20%':<9}{'MaxDD':<8}{'Net PnL ($)'}")
    print("-" * 115)

    for rank, r in enumerate(viable[:15], 1):
        print(
            f"#{rank:<4}{r['name'][:46]:<48}"
            f"{r['trades_per_month']:<8}{r['active_days_pct']:<7.1f}%"
            f"{r['win_rate']:<7.1f}{r['profit_factor']:<8.2f}{r['oos_pf']:<8.2f}"
            f"+{r['avg_monthly_roi']:<8.2f}%{r['pct_months_hit_20']:<8.1f}%"
            f"{r['max_dd']:<7.1f}%+${r['net_pnl']:,.2f}"
        )

    # Save to report
    out_file = PROJECT_ROOT / "reports" / "naruto_20pct_monthly_tournament.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_clones": len(clones),
            "sim_seconds": round(total_sim_time, 2),
            "top_15_viable": viable[:15],
            "all_clones": results
        }, f, indent=2)

    print(f"\n📁 Full Naruto Tournament Audit Report saved to: {out_file.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
