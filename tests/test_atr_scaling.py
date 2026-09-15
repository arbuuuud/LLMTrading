"""
Quantitative Diagnostic: Static SL vs Dynamic ATR-Scaled SL/TP across 10.5 months.
Compares fixed dollar stops ($0.35 / $0.50) against dynamic ATR volatility-adaptive stops.
"""

import sys
from pathlib import Path
from datetime import time
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
import numpy as np


def run_atr_dynamic_study():
    df = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")
    print(f"Loaded {len(df):,} bars.")

    # Calculate 14-period True Range on M15 bars
    # First resample to M15
    df_m15 = df.group_by_dynamic("timestamp", every="15m").agg([
        pl.col("open").first(),
        pl.col("high").max(),
        pl.col("low").min(),
        pl.col("close").last()
    ]).sort("timestamp")

    # Compute ATR on M15
    highs = df_m15["high"].to_numpy()
    lows = df_m15["low"].to_numpy()
    closes = df_m15["close"].to_numpy()
    n = len(df_m15)

    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))

    # 14-period exponential ATR
    atr14 = np.zeros(n)
    atr14[13] = np.mean(tr[:14])
    alpha = 1.0 / 14.0
    for i in range(14, n):
        atr14[i] = alpha * tr[i] + (1.0 - alpha) * atr14[i-1]

    df_m15 = df_m15.with_columns(pl.Series("atr15", atr14))

    # Join ATR back to M1
    df_with_atr = df.join_asof(
        df_m15.select(["timestamp", "atr15"]),
        on="timestamp",
        strategy="backward"
    ).fill_null(strategy="forward").fill_null(1.5)

    print(f"Joined M15 ATR. Min ATR: ${df_with_atr['atr15'].min():.2f}, Max ATR: ${df_with_atr['atr15'].max():.2f}, Mean: ${df_with_atr['atr15'].mean():.2f}")

    # Now let's test a clean Trend-Aligned Pullback with ATR-Dynamic SL and Target 1%
    # If SL = 1.2 * ATR, TP = 2.4 * ATR (RR 1:2.0)
    # Risk per trade = 0.5% ($50)
    # Target per win = 1.0% ($100)
    
    rows = df_with_atr.select(["timestamp", "open", "high", "low", "close", "atr15", "mean_spread"]).to_dicts()
    
    daily_pnl = defaultdict(float)
    daily_trades = defaultdict(int)
    daily_wins = defaultdict(int)
    daily_losses = defaultdict(int)

    trades = []
    in_pos = None
    last_exit_idx = -999

    # Simple M15 EMA 50 trend
    m15_ema = 0.0
    alpha_ema = 2.0 / (50.0 + 1.0)
    m15_closes = []

    for i in range(len(rows)):
        b = rows[i]
        dt = b["timestamp"]
        d = dt.date()
        t = dt.time()
        c = b["close"]
        h = b["high"]
        l = b["low"]
        o = b["open"]
        atr = max(1.0, b["atr15"])

        # Manage open trade
        if in_pos is not None:
            side, entry, stop, tp, lots, open_idx = in_pos
            bars_held = i - open_idx

            if side == "BUY":
                if l <= stop:
                    loss_amt = abs(entry - stop) * lots * 100 + (lots * 7.0)
                    daily_pnl[d] -= loss_amt
                    daily_losses[d] += 1
                    trades.append(("BUY", d, -loss_amt, "SL"))
                    in_pos = None
                    last_exit_idx = i
                elif h >= tp:
                    win_amt = abs(tp - entry) * lots * 100 - (lots * 7.0)
                    daily_pnl[d] += win_amt
                    daily_wins[d] += 1
                    trades.append(("BUY", d, win_amt, "TP"))
                    in_pos = None
                    last_exit_idx = i
                elif bars_held >= 30: # 30 min time exit
                    pnl = (c - entry) * lots * 100 - (lots * 7.0)
                    daily_pnl[d] += pnl
                    if pnl > 0: daily_wins[d] += 1
                    else: daily_losses[d] += 1
                    trades.append(("BUY", d, pnl, "TIME"))
                    in_pos = None
                    last_exit_idx = i
            else: # SELL
                if h >= stop:
                    loss_amt = abs(stop - entry) * lots * 100 + (lots * 7.0)
                    daily_pnl[d] -= loss_amt
                    daily_losses[d] += 1
                    trades.append(("SELL", d, -loss_amt, "SL"))
                    in_pos = None
                    last_exit_idx = i
                elif l <= tp:
                    win_amt = abs(entry - tp) * lots * 100 - (lots * 7.0)
                    daily_pnl[d] += win_amt
                    daily_wins[d] += 1
                    trades.append(("SELL", d, win_amt, "TP"))
                    in_pos = None
                    last_exit_idx = i
                elif bars_held >= 30:
                    pnl = (entry - c) * lots * 100 - (lots * 7.0)
                    daily_pnl[d] += pnl
                    if pnl > 0: daily_wins[d] += 1
                    else: daily_losses[d] += 1
                    trades.append(("SELL", d, pnl, "TIME"))
                    in_pos = None
                    last_exit_idx = i
            continue

        # Cooldown & Daily stop checks
        if i - last_exit_idx < 15:
            continue
        if daily_pnl[d] >= 100.0: # TARGET REACHED (+1.0%) -> STOP TRADING!
            continue
        if daily_losses[d] >= 2 or daily_pnl[d] <= -100.0: # 2 LOSSES -> STOP!
            continue
        if daily_trades[d] >= 3: # Max 3 trades
            continue

        # Session filter: London & NY Golden hours only
        if not ((7, 0) <= (t.hour, t.minute) <= (11, 0) or (13, 0) <= (t.hour, t.minute) <= (16, 0)):
            continue

        # Trend filter using 50 EMA on M1
        # Simple pullback trigger:
        # If in uptrend and candle has lower wick rejection > 50%
        body = abs(c - o)
        rng = h - l
        if rng < 0.20: continue

        lower_wick = min(o, c) - l
        upper_wick = h - max(o, c)

        sl_dist = round(atr * 1.2, 2) # DYNAMIC ATR STOP!
        tp_dist = round(sl_dist * 2.0, 2)
        target_risk = 50.0 # $50 (0.5%)
        lots = round(max(0.01, min(5.0, target_risk / (sl_dist * 100))), 2)

        # Bullish Pullback
        if lower_wick / rng >= 0.50 and c > o:
            in_pos = ("BUY", c, round(c - sl_dist, 2), round(c + tp_dist, 2), lots, i)
            daily_trades[d] += 1
        elif upper_wick / rng >= 0.50 and c < o:
            in_pos = ("SELL", c, round(c + sl_dist, 2), round(c - tp_dist, 2), lots, i)
            daily_trades[d] += 1

    total_net = sum(t[2] for t in trades)
    wins_count = sum(1 for t in trades if t[2] > 0)
    losses_count = sum(1 for t in trades if t[2] <= 0)
    total_tr = len(trades)
    wr = wins_count / total_tr * 100 if total_tr else 0
    days_target_hit = sum(1 for pnl in daily_pnl.values() if pnl >= 100.0)

    print("\n" + "=" * 75)
    print("RESULTS: ATR-DYNAMIC VOLATILITY SCALING (10.5 MONTHS)")
    print("=" * 75)
    print(f"Total Trades: {total_tr} ({total_tr/len(daily_pnl):.1f} trades/day)")
    print(f"Win Rate: {wr:.1f}% ({wins_count} W / {losses_count} L)")
    print(f"Total Net PnL: ${total_net:+,.2f} (+{total_net/10000*100:.2f}%)")
    print(f"Days Hitting Target (>= +1.0% / $100): {days_target_hit} of {len(daily_pnl)} days ({days_target_hit/len(daily_pnl)*100:.1f}%)")
    print("=" * 75)


if __name__ == "__main__":
    run_atr_dynamic_study()
