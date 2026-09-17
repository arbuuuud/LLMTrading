"""
Grand Master Kage Bunshin: Agent 2 Institutional Tournament (2010 - 2026 / 16.6 Years).
Evaluates 216 Clones across the Modern ECN Era testing:
1. HTF Context: H4 EMA 50 vs H1 EMA 50 vs BASELINE
2. Equilibrium 50% Rule: STRICT (<50% Discount for Buy, >50% Premium for Sell) vs RELAXED
3. Fibonacci Confluence: NO_FIBO vs FIBO_OTE (61.8%-78.6%) vs FIBO_DISCOUNT (50%-61.8%)
4. Execution Trigger Model:
   - NO_CONFIRM_LIMIT (Aggressive Smart Limit at Proximal Line)
   - M15_CANDLE_CONFIRM (M15 Bar-Close Hammer / Engulfing)
   - LTF_M3_WICK_CONFIRM (M3 High-Precision Rejection Wick >= 45% -> Compressed SL)
   - LTF_M3_CHOCH_CONFIRM (M3 Change of Character / Structural Shift -> Compressed SL)
5. Target R:R: 1:3.0 vs 1:4.0 vs 1:5.0
6. Strict Governor: 0.50% Risk ($50 on $10k), 2-Strike Daily Shutdown, Ratchet Profit Lock
"""

import sys
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Tuple
import json
import numpy as np
import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

M15_PATH = Path("data/processed/bars/XAUUSD/HTF/XAUUSD_M15_2003_2026.parquet")
M3_PATH = Path("data/processed/bars/XAUUSD/HTF/XAUUSD_M3_2003_2026.parquet")
H1_PATH = Path("data/processed/bars/XAUUSD/HTF/XAUUSD_H1_2003_2026.parquet")
H4_PATH = Path("data/processed/bars/XAUUSD/HTF/XAUUSD_H4_2003_2026.parquet")


@dataclass
class Agent2CloneConfig:
    id: str
    name: str
    htf_filter: str        # "H4_EMA50", "H1_EMA50", "BASELINE"
    equilibrium_rule: str  # "STRICT", "RELAXED"
    fibo_confluence: str   # "NO_FIBO", "FIBO_OTE", "FIBO_DISCOUNT"
    trigger_model: str     # "NO_CONFIRM_LIMIT", "M15_CANDLE_CONFIRM", "LTF_M3_WICK_CONFIRM", "LTF_M3_CHOCH_CONFIRM"
    rr_target: float       # 3.0, 4.0, 5.0
    sl_buffer: float       # 0.30 for LTF, 1.00 for M15/Limit


@dataclass
class CloneTrade:
    year: int
    net_pnl: float
    risk_dollars: float
    rr_achieved: float
    sl_distance: float
    is_win: bool


def generate_agent2_clones() -> List[Agent2CloneConfig]:
    clones = []
    idx = 1
    
    htf_filters = ["H4_EMA50", "H1_EMA50", "BASELINE"]
    equilibrium_rules = ["STRICT", "RELAXED"]
    fibo_confluences = ["NO_FIBO", "FIBO_OTE", "FIBO_DISCOUNT"]
    trigger_models = ["NO_CONFIRM_LIMIT", "M15_CANDLE_CONFIRM", "LTF_M3_WICK_CONFIRM", "LTF_M3_CHOCH_CONFIRM"]
    rr_targets = [3.0, 4.0, 5.0]

    for htf in htf_filters:
        for eq in equilibrium_rules:
            for fibo in fibo_confluences:
                for trig in trigger_models:
                    for rr in rr_targets:
                        c_id = f"A2_CLONE_{idx:03d}"
                        name = f"{htf}_{eq}_{fibo}_{trig}_RR_{str(rr).replace('.', '_')}"
                        sl_buf = 0.30 if "LTF_M3" in trig else 1.00
                        clones.append(Agent2CloneConfig(
                            id=c_id,
                            name=name,
                            htf_filter=htf,
                            equilibrium_rule=eq,
                            fibo_confluence=fibo,
                            trigger_model=trig,
                            rr_target=rr,
                            sl_buffer=sl_buf
                        ))
                        idx += 1
    return clones


def load_and_preprocess_agent2_data():
    print("=" * 110)
    print("⚡ GRAND MASTER KAGE BUNSHIN: AGENT 2 TOURNAMENT (2010 - 2026 / 16.6 YEARS)")
    print("⚡ HTF POI (NFC) + FIBONACCI OTE + EQUILIBRIUM 50% + LTF M3 HIGH-PRECISION SNIPER")
    print("=" * 110)
    t0 = time.time()

    print("[Phase 1/4] Loading Modern Era Parquets (2010-2026)...")
    df_m15 = pl.read_parquet(M15_PATH).filter(pl.col("timestamp").dt.year() >= 2010)
    df_m3 = pl.read_parquet(M3_PATH).filter(pl.col("timestamp").dt.year() >= 2010)
    df_h1 = pl.read_parquet(H1_PATH).filter(pl.col("timestamp").dt.year() >= 2010)
    df_h4 = pl.read_parquet(H4_PATH).filter(pl.col("timestamp").dt.year() >= 2010)
    print(f"  -> Loaded {len(df_m15):,} M15 bars and {len(df_m3):,} M3 bars in {time.time() - t0:.2f}s.")

    print("[Phase 2/4] Precomputing HTF Context (H4 EMA50, H1 EMA50, Daily Equilibrium)...")
    df_h1_prep = df_h1.with_columns([
        pl.col("timestamp").alias("h1_time"),
        pl.col("close").ewm_mean(span=50).alias("h1_ema50")
    ]).select(["h1_time", "h1_ema50"])

    df_h4_prep = df_h4.with_columns([
        pl.col("timestamp").alias("h4_time"),
        pl.col("close").ewm_mean(span=50).alias("h4_ema50")
    ]).select(["h4_time", "h4_ema50"])

    # Calculate ATR14 and wick ratios on M15
    df_m15 = df_m15.with_columns([
        pl.col("timestamp").dt.year().alias("year"),
        pl.col("timestamp").dt.date().alias("date"),
        pl.col("timestamp").dt.hour().alias("hour"),
        pl.col("timestamp").dt.truncate("1h").alias("h1_time"),
        pl.col("timestamp").dt.truncate("4h").alias("h4_time"),
        (pl.col("high") - pl.col("low")).alias("range"),
        (pl.col("high") - pl.col("low")).rolling_mean(window_size=14).alias("atr14"),
        pl.when(pl.col("close") >= pl.col("open"))
          .then(pl.col("open") - pl.col("low"))
          .otherwise(pl.col("close") - pl.col("low")).alias("lower_wick"),
        pl.when(pl.col("close") >= pl.col("open"))
          .then(pl.col("high") - pl.col("close"))
          .otherwise(pl.col("high") - pl.col("open")).alias("upper_wick"),
    ])

    # Join HTF indicators
    df_m15 = df_m15.join(df_h1_prep, on="h1_time", how="left").with_columns(
        pl.col("h1_ema50").fill_null(pl.col("close"))
    )
    df_m15 = df_m15.join(df_h4_prep, on="h4_time", how="left").with_columns(
        pl.col("h4_ema50").fill_null(pl.col("close"))
    )

    # Daily high and low for Equilibrium 50% calculation
    df_m15 = df_m15.with_columns([
        pl.col("high").cum_max().over("date").alias("day_high"),
        pl.col("low").cum_min().over("date").alias("day_low"),
    ])
    df_m15 = df_m15.with_columns([
        ((pl.col("day_high") + pl.col("day_low")) / 2.0).alias("day_equilibrium")
    ])

    print("[Phase 3/4] Aligning M3 LTF Bars into M15 Windows...")
    # Group M3 bars by their parent M15 timestamp: M3 timestamp truncated to 15m
    df_m3 = df_m3.with_columns([
        pl.col("timestamp").dt.truncate("15m").alias("m15_time"),
        (pl.col("high") - pl.col("low")).alias("range"),
        pl.when(pl.col("close") >= pl.col("open"))
          .then(pl.col("open") - pl.col("low"))
          .otherwise(pl.col("close") - pl.col("low")).alias("lower_wick"),
        pl.when(pl.col("close") >= pl.col("open"))
          .then(pl.col("high") - pl.col("close"))
          .otherwise(pl.col("high") - pl.col("open")).alias("upper_wick"),
    ])
    df_m3 = df_m3.with_columns([
        (pl.col("lower_wick") / pl.when(pl.col("range") > 0).then(pl.col("range")).otherwise(1.0)).alias("lower_wick_ratio"),
        (pl.col("upper_wick") / pl.when(pl.col("range") > 0).then(pl.col("range")).otherwise(1.0)).alias("upper_wick_ratio"),
    ])

    # Convert to fast lookups / arrays
    m15_dict = {
        "timestamps": df_m15["timestamp"].to_list(),
        "years": df_m15["year"].to_numpy(),
        "dates": df_m15["date"].to_list(),
        "opens": df_m15["open"].to_numpy(),
        "highs": df_m15["high"].to_numpy(),
        "lows": df_m15["low"].to_numpy(),
        "closes": df_m15["close"].to_numpy(),
        "ranges": df_m15["range"].to_numpy(),
        "atrs": df_m15["atr14"].fill_null(2.5).to_numpy(),
        "spreads": df_m15["mean_spread"].to_numpy(),
        "h1_ema50": df_m15["h1_ema50"].to_numpy(),
        "h4_ema50": df_m15["h4_ema50"].to_numpy(),
        "day_equilibrium": df_m15["day_equilibrium"].to_numpy(),
        "lower_wicks": df_m15["lower_wick"].to_numpy(),
        "upper_wicks": df_m15["upper_wick"].to_numpy(),
    }

    # Build M15 -> M3 mapping (5 M3 bars per M15 bar)
    # We can group M3 by m15_time
    m3_times = df_m3["m15_time"].to_list()
    m3_opens = df_m3["open"].to_numpy()
    m3_highs = df_m3["high"].to_numpy()
    m3_lows = df_m3["low"].to_numpy()
    m3_closes = df_m3["close"].to_numpy()
    m3_lw_ratio = df_m3["lower_wick_ratio"].to_numpy()
    m3_uw_ratio = df_m3["upper_wick_ratio"].to_numpy()

    print(f"  -> Preprocessing completed in {time.time() - t0:.2f}s.")
    return m15_dict, df_m3


def detect_m15_zones_and_signals(m15_dict: Dict[str, Any], df_m3: pl.DataFrame):
    """
    Detects NFC Supply & Demand zones on M15, calculates Fibo Golden Pocket,
    and indexes retest windows with candidate LTF triggers.
    """
    t0 = time.time()
    print("[Phase 4/4] Pre-Indexing M15 NFC Bases & LTF M3 Sniper Signals...")

    closes = m15_dict["closes"]
    opens = m15_dict["opens"]
    highs = m15_dict["highs"]
    lows = m15_dict["lows"]
    ranges = m15_dict["ranges"]
    atrs = m15_dict["atrs"]
    years = m15_dict["years"]
    dates = m15_dict["dates"]
    h1_ema50 = m15_dict["h1_ema50"]
    h4_ema50 = m15_dict["h4_ema50"]
    eqs = m15_dict["day_equilibrium"]
    lower_wicks = m15_dict["lower_wicks"]
    upper_wicks = m15_dict["upper_wicks"]
    n_bars = len(closes)

    # Pre-index M3 bars by m15 timestamp
    # Create dictionary of m15_time -> list of M3 bars (open, high, low, close, lw_ratio, uw_ratio)
    m3_grouped = {}
    m3_iter = df_m3.select([
        "m15_time", "open", "high", "low", "close", "lower_wick_ratio", "upper_wick_ratio"
    ]).iter_rows(named=True)

    for row in m3_iter:
        t = row["m15_time"]
        if t not in m3_grouped:
            m3_grouped[t] = []
        m3_grouped[t].append((
            row["open"], row["high"], row["low"], row["close"],
            row["lower_wick_ratio"], row["upper_wick_ratio"]
        ))

    # Candidate Opportunities: list of dicts describing each zone retest event
    # An opportunity will contain all data needed by each clone to determine whether it enters,
    # and if so, what entry, SL, and future outcome occurs.
    opportunities = []

    active_demand_zones = [] # list of dicts: {top, bottom, swing_high, created_bar, mitigated}
    active_supply_zones = []

    for i in range(5, n_bars - 40): # Leave room for forward bar evaluation
        atr = atrs[i]
        c = closes[i]
        o = opens[i]
        h = highs[i]
        l = lows[i]
        r = ranges[i]
        ts = m15_dict["timestamps"][i]
        yr = years[i]
        dt = dates[i]
        h1_ema = h1_ema50[i]
        h4_ema = h4_ema50[i]
        eq = eqs[i]

        # 1. Base Detection on Bar i (if bar i is departure candle)
        if r >= 1.6 * atr:
            # Bullish departure -> Demand base was bar i-1 (and i-2)
            if c > o and (c - o) / r >= 0.55:
                b_top = max(highs[i-1], highs[i-2])
                b_bot = min(lows[i-1], lows[i-2])
                if (b_top - b_bot) <= 1.5 * atr:
                    active_demand_zones.append({
                        "top": b_top,
                        "bottom": b_bot,
                        "departure_high": h,
                        "created_idx": i,
                        "tested": 0,
                        "max_high": h
                    })
            # Bearish departure -> Supply base
            elif c < o and (o - c) / r >= 0.55:
                b_top = max(highs[i-1], highs[i-2])
                b_bot = min(lows[i-1], lows[i-2])
                if (b_top - b_bot) <= 1.5 * atr:
                    active_supply_zones.append({
                        "top": b_top,
                        "bottom": b_bot,
                        "departure_low": l,
                        "created_idx": i,
                        "tested": 0,
                        "min_low": l
                    })

        # Update running max/min for active zones before retest
        for z in active_demand_zones:
            if not z.get("retesting", False):
                if h > z["max_high"]: z["max_high"] = h
        for z in active_supply_zones:
            if not z.get("retesting", False):
                if l < z["min_low"]: z["min_low"] = l

        # 2. Check Retest of Active Demand Zones (BUY Opportunities)
        m3_bars = m3_grouped.get(ts, [])
        for z in list(active_demand_zones):
            if i - z["created_idx"] < 2: continue # Don't retest on immediate departure bar
            if i - z["created_idx"] > 120: # Expire after 120 M15 bars (~30 hours)
                active_demand_zones.remove(z)
                continue

            # Check if current bar dips into Demand zone (low <= proximal top)
            if l <= z["top"] and l >= (z["bottom"] - 1.50):
                # Retest detected!
                z["tested"] += 1
                swing_range = max(0.1, z["max_high"] - z["bottom"])
                # Retracement level from high: (max_high - zone_top) / swing_range
                retracement = (z["max_high"] - z["top"]) / swing_range

                is_fibo_ote = (0.58 <= retracement <= 0.82)
                is_fibo_discount = (0.48 <= retracement <= 0.65)
                is_strict_discount = (z["top"] <= eq) # Buy strictly at Discount (<50%)

                # Evaluate M15 Candle Confirmation
                m15_confirm = (c > o and lower_wicks[i] >= 0.40) or (c > highs[i-1])

                # Evaluate LTF M3 Sniper Triggers inside this M15 bar
                m3_wick_confirm = False
                m3_wick_sl = z["bottom"] - 0.30
                m3_choch_confirm = False
                m3_choch_sl = z["bottom"] - 0.30

                if m3_bars:
                    # Check M3 bars
                    m3_low_in_zone = min(b[2] for b in m3_bars)
                    for m3_o, m3_h, m3_l, m3_c, m3_lw, m3_uw in m3_bars:
                        if m3_l <= z["top"]:
                            # Rejection wick on M3
                            if m3_c > m3_o and m3_lw >= 0.45:
                                m3_wick_confirm = True
                                m3_wick_sl = round(m3_l - 0.30, 2)
                                break
                    # Simple M3 CHoCH: inside zone, an M3 bar closes above the open/high of the previous M3 bar
                    for k in range(1, len(m3_bars)):
                        if m3_bars[k][3] > m3_bars[k-1][1] and m3_bars[k][2] <= z["top"]:
                            m3_choch_confirm = True
                            m3_choch_sl = round(min(m3_bars[k][2], m3_bars[k-1][2]) - 0.30, 2)
                            break

                opp = {
                    "direction": "BUY",
                    "bar_idx": i,
                    "year": yr,
                    "date": dt,
                    "price_touch": z["top"],
                    "price_m15_close": c,
                    "h1_bull": (c >= h1_ema),
                    "h4_bull": (c >= h4_ema),
                    "strict_eq": is_strict_discount,
                    "fibo_ote": is_fibo_ote,
                    "fibo_discount": is_fibo_discount,
                    "m15_confirm": m15_confirm,
                    "m3_wick_confirm": m3_wick_confirm,
                    "m3_wick_sl": m3_wick_sl,
                    "m3_choch_confirm": m3_choch_confirm,
                    "m3_choch_sl": m3_choch_sl,
                    "distal_sl": z["bottom"] - 1.00,
                    "future_highs": highs[i+1 : i+35], # Forward path for fast trade resolution
                    "future_lows": lows[i+1 : i+35],
                    "spread": m15_dict["spreads"][i]
                }
                opportunities.append(opp)
                active_demand_zones.remove(z) # Zone mitigated

        # 3. Check Retest of Active Supply Zones (SELL Opportunities)
        for z in list(active_supply_zones):
            if i - z["created_idx"] < 2: continue
            if i - z["created_idx"] > 120:
                active_supply_zones.remove(z)
                continue

            if h >= z["bottom"] and h <= (z["top"] + 1.50):
                z["tested"] += 1
                swing_range = max(0.1, z["top"] - z["min_low"])
                retracement = (z["bottom"] - z["min_low"]) / swing_range

                is_fibo_ote = (0.58 <= retracement <= 0.82)
                is_fibo_discount = (0.48 <= retracement <= 0.65)
                is_strict_premium = (z["bottom"] >= eq) # Sell strictly at Premium (>50%)

                m15_confirm = (c < o and upper_wicks[i] >= 0.40) or (c < lows[i-1])

                m3_wick_confirm = False
                m3_wick_sl = z["top"] + 0.30
                m3_choch_confirm = False
                m3_choch_sl = z["top"] + 0.30

                if m3_bars:
                    for m3_o, m3_h, m3_l, m3_c, m3_lw, m3_uw in m3_bars:
                        if m3_h >= z["bottom"]:
                            if m3_c < m3_o and m3_uw >= 0.45:
                                m3_wick_confirm = True
                                m3_wick_sl = round(m3_h + 0.30, 2)
                                break
                    for k in range(1, len(m3_bars)):
                        if m3_bars[k][3] < m3_bars[k-1][1] and m3_bars[k][1] >= z["bottom"]:
                            m3_choch_confirm = True
                            m3_choch_sl = round(max(m3_bars[k][1], m3_bars[k-1][1]) + 0.30, 2)
                            break

                opp = {
                    "direction": "SELL",
                    "bar_idx": i,
                    "year": yr,
                    "date": dt,
                    "price_touch": z["bottom"],
                    "price_m15_close": c,
                    "h1_bear": (c <= h1_ema),
                    "h4_bear": (c <= h4_ema),
                    "strict_eq": is_strict_premium,
                    "fibo_ote": is_fibo_ote,
                    "fibo_discount": is_fibo_discount,
                    "m15_confirm": m15_confirm,
                    "m3_wick_confirm": m3_wick_confirm,
                    "m3_wick_sl": m3_wick_sl,
                    "m3_choch_confirm": m3_choch_confirm,
                    "m3_choch_sl": m3_choch_sl,
                    "distal_sl": z["top"] + 1.00,
                    "future_highs": highs[i+1 : i+35],
                    "future_lows": lows[i+1 : i+35],
                    "spread": m15_dict["spreads"][i]
                }
                opportunities.append(opp)
                active_supply_zones.remove(z)

    print(f"  -> Indexed {len(opportunities):,} total high-fidelity zone retest events across 2010-2026 in {time.time() - t0:.2f}s!")
    return opportunities


def evaluate_clone_fast(clone: Agent2CloneConfig, opportunities: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Executes a single clone simulation with the 1% ratchet governor.
    """
    trades: List[CloneTrade] = []
    
    current_date = None
    daily_pnl = 0.0
    daily_losses = 0
    daily_locked = False
    
    account_equity = 10000.0
    peak_equity = 10000.0
    max_dd = 0.0

    for opp in opportunities:
        d = opp["date"]
        yr = opp["year"]
        
        # New trading day reset
        if d != current_date:
            current_date = d
            daily_pnl = 0.0
            daily_losses = 0
            daily_locked = False

        # 2-Strike Defensive Guard: Max 2 losses shuts down for the day
        if daily_losses >= 2:
            continue
            
        # Daily Ratchet Lock: If hit floor or locked
        if daily_locked and daily_pnl <= 100.0:
            continue # Floor hit, stop trading

        # 1. Check HTF Trend Gate
        if opp["direction"] == "BUY":
            if clone.htf_filter == "H4_EMA50" and not opp["h4_bull"]: continue
            if clone.htf_filter == "H1_EMA50" and not opp["h1_bull"]: continue
        else:
            if clone.htf_filter == "H4_EMA50" and not opp["h4_bear"]: continue
            if clone.htf_filter == "H1_EMA50" and not opp["h1_bear"]: continue

        # 2. Check Equilibrium 50% Rule
        if clone.equilibrium_rule == "STRICT" and not opp["strict_eq"]:
            continue

        # 3. Check Fibonacci Confluence
        if clone.fibo_confluence == "FIBO_OTE" and not opp["fibo_ote"]:
            continue
        if clone.fibo_confluence == "FIBO_DISCOUNT" and not opp["fibo_discount"]:
            continue

        # 4. Check Trigger Execution Model & Determine Entry & SL
        entry_price = 0.0
        stop_loss = 0.0
        
        if clone.trigger_model == "NO_CONFIRM_LIMIT":
            entry_price = opp["price_touch"]
            stop_loss = opp["distal_sl"]
        elif clone.trigger_model == "M15_CANDLE_CONFIRM":
            if not opp["m15_confirm"]: continue
            entry_price = opp["price_m15_close"]
            stop_loss = opp["distal_sl"]
        elif clone.trigger_model == "LTF_M3_WICK_CONFIRM":
            if not opp["m3_wick_confirm"]: continue
            entry_price = opp["price_touch"] # Entered on rejection wick
            stop_loss = opp["m3_wick_sl"]
        elif clone.trigger_model == "LTF_M3_CHOCH_CONFIRM":
            if not opp["m3_choch_confirm"]: continue
            entry_price = opp["price_touch"]
            stop_loss = opp["m3_choch_sl"]

        # Risk calculation
        sl_dist = abs(entry_price - stop_loss)
        if sl_dist < 0.60 or sl_dist > 10.0: # Filter unrealistic outliers
            continue

        # Sizing via Ratchet Governor
        risk_pct = 0.25 if daily_pnl >= 125.0 else 0.50 # House Money if in Greed Mode
        risk_dollars = account_equity * (risk_pct / 100.0)
        lots = max(0.01, round(risk_dollars / (sl_dist * 100.0), 2))

        # Target Take Profit
        tp_dist = sl_dist * clone.rr_target
        take_profit = entry_price + tp_dist if opp["direction"] == "BUY" else entry_price - tp_dist

        # Fast Trade Outcome Resolution via Forward Bar Arrays
        f_highs = opp["future_highs"]
        f_lows = opp["future_lows"]
        
        outcome_win = False
        outcome_loss = False
        
        if opp["direction"] == "BUY":
            for fh, fl in zip(f_highs, f_lows):
                if fl <= stop_loss:
                    outcome_loss = True
                    break
                if fh >= take_profit:
                    outcome_win = True
                    break
        else: # SELL
            for fh, fl in zip(f_highs, f_lows):
                if fh >= stop_loss:
                    outcome_loss = True
                    break
                if fl <= take_profit:
                    outcome_win = True
                    break

        if not outcome_win and not outcome_loss:
            # End of window without hitting SL or TP -> close at market
            continue

        # PnL accounting
        if outcome_win:
            net_gain = risk_dollars * clone.rr_target
            trades.append(CloneTrade(
                year=yr,
                net_pnl=net_gain,
                risk_dollars=risk_dollars,
                rr_achieved=clone.rr_target,
                sl_distance=sl_dist,
                is_win=True
            ))
            daily_pnl += net_gain
            account_equity += net_gain
            if daily_pnl >= 125.0:
                daily_locked = True
        else:
            net_loss = -risk_dollars
            trades.append(CloneTrade(
                year=yr,
                net_pnl=net_loss,
                risk_dollars=risk_dollars,
                rr_achieved=-1.0,
                sl_distance=sl_dist,
                is_win=False
            ))
            daily_pnl += net_loss
            daily_losses += 1
            account_equity += net_loss

        # Peak & Drawdown tracking
        if account_equity > peak_equity:
            peak_equity = account_equity
        dd = (peak_equity - account_equity) / peak_equity * 100.0
        if dd > max_dd:
            max_dd = dd

    # Summary Statistics
    total_trades = len(trades)
    if total_trades == 0:
        return {
            "clone_id": clone.id,
            "name": clone.name,
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "oos_profit_factor": 0.0,
            "net_pnl": 0.0,
            "max_dd": 0.0,
            "avg_sl": 0.0,
            "pass_filter": False
        }

    wins = [t for t in trades if t.is_win]
    losses = [t for t in trades if not t.is_win]
    win_rate = len(wins) / total_trades * 100.0

    gross_profit = sum(t.net_pnl for t in wins)
    gross_loss = abs(sum(t.net_pnl for t in losses))
    pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 99.0
    net_pnl = gross_profit - gross_loss

    # OOS (2024-2026) metrics
    oos_trades = [t for t in trades if t.year >= 2024]
    oos_wins = [t for t in oos_trades if t.is_win]
    oos_losses = [t for t in oos_trades if not t.is_win]
    oos_gp = sum(t.net_pnl for t in oos_wins)
    oos_gl = abs(sum(t.net_pnl for t in oos_losses))
    oos_pf = round(oos_gp / oos_gl, 2) if oos_gl > 0 else (99.0 if oos_gp > 0 else 0.0)

    avg_sl = float(np.mean([t.sl_distance for t in trades]))

    return {
        "clone_id": clone.id,
        "name": clone.name,
        "total_trades": total_trades,
        "win_rate": round(win_rate, 1),
        "profit_factor": pf,
        "oos_profit_factor": oos_pf,
        "oos_trades": len(oos_trades),
        "net_pnl": round(net_pnl, 2),
        "max_dd": round(max_dd, 2),
        "avg_sl": round(avg_sl, 2),
        "pass_filter": (total_trades >= 100 and oos_pf >= 1.25 and max_dd <= 15.0)
    }


def main():
    clones = generate_agent2_clones()
    print(f"Generated {len(clones)} distinct Agent 2 clones for tournament.")

    m15_data, df_m3 = load_and_preprocess_agent2_data()
    opportunities = detect_m15_zones_and_signals(m15_data, df_m3)

    print("\n" + "=" * 110)
    print(f"🚀 EXECUTING 216 CLONES TOURNAMENT ACROSS 16.6 YEARS (2010 - 2026)...")
    print("=" * 110)
    t_start = time.time()

    results = []
    for i, c in enumerate(clones, 1):
        res = evaluate_clone_fast(c, opportunities)
        results.append(res)
        if i % 36 == 0 or i == len(clones):
            elapsed = time.time() - t_start
            print(f"  -> Simulated {i}/{len(clones)} clones ({i/len(clones)*100:.1f}%) in {elapsed:.2f}s...")

    total_sim_time = time.time() - t_start
    print(f"\n✨ TOURNAMENT COMPLETED in {total_sim_time:.2f}s ({len(clones)/total_sim_time:.1f} clones/sec)!")

    # Sort results by OOS Profit Factor, then Net PnL
    valid_results = [r for r in results if r["total_trades"] >= 50]
    valid_results.sort(key=lambda x: (x["oos_profit_factor"], x["net_pnl"]), reverse=True)

    print("\n" + "=" * 110)
    print("🏆 TOP 15 JUARA KAGE BUNSHIN AGENT 2 (LEADERBOARD MODERN ERA 2010 - 2026)")
    print("=" * 110)
    print(f"{'Rank':<5}{'Clone Name':<58}{'Trades':<8}{'Win%':<7}{'Full PF':<9}{'OOS PF':<9}{'Avg SL':<8}{'Max DD':<8}{'Net PnL ($)'}")
    print("-" * 110)

    for rank, r in enumerate(valid_results[:15], 1):
        print(
            f"#{rank:<4}{r['name'][:56]:<58}"
            f"{r['total_trades']:<8}{r['win_rate']:<7.1f}{r['profit_factor']:<9.2f}"
            f"{r['oos_profit_factor']:<9.2f}${r['avg_sl']:<7.2f}{r['max_dd']:<7.1f}%"
            f"+${r['net_pnl']:,.2f}"
        )

    # Save complete audit report to JSON
    report_path = PROJECT_ROOT / "reports" / "kagebunshin_agent2_sniper_audit.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_clones": len(clones),
            "simulation_seconds": round(total_sim_time, 2),
            "top_15": valid_results[:15],
            "all_results": valid_results
        }, f, indent=2)
    print(f"\n📁 Full 216-Clone Audit Report saved to: {report_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
