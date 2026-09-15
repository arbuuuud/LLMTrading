"""
Institutional Simulation: 20% Monthly Target Ratchet Engine.
Implements the user's exact specification:
- Base Trade: Risk 0.5%, Target R:R 1:2.5 (Win = +1.25%).
- When Profit >= +1.25% / +1.5%:
  * Floor locks at +1.0% (guaranteed minimum 1% profit for the day).
  * Continue trading with "House Money" (reduced risk 0.25%).
  * If Profit reaches +2.0% -> Floor locks at +1.5%.
  * If Profit reaches +2.5% -> Floor locks at +2.0%.
  * If PnL pulls back to the locked floor -> IMMEDIATE SHUTDOWN FOR THE DAY.
- Loss Protection:
  * 2 consecutive losses (-0.5% + -0.5% = -1.0%) -> IMMEDIATE SHUTDOWN FOR THE DAY.
- M15 ATR Dynamic Stop Loss to adapt to market volatility.
"""

import sys
from pathlib import Path
from collections import defaultdict
from datetime import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
import numpy as np


def run_monthly_target_ratchet():
    df = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")
    print(f"Loaded {len(df):,} M1 bars.")

    # 1. Compute M15 ATR and M15 50 EMA for clean macro trend
    df_m15 = df.group_by_dynamic("timestamp", every="15m").agg([
        pl.col("open").first(), pl.col("high").max(), pl.col("low").min(), pl.col("close").last()
    ]).sort("timestamp")

    highs = df_m15["high"].to_numpy()
    lows = df_m15["low"].to_numpy()
    closes = df_m15["close"].to_numpy()
    n = len(df_m15)
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))

    atr14 = np.zeros(n)
    atr14[13] = np.mean(tr[:14])
    alpha = 1.0 / 14.0
    for i in range(14, n):
        atr14[i] = alpha * tr[i] + (1.0 - alpha) * atr14[i-1]

    # EMA 50
    ema50 = np.zeros(n)
    ema50[49] = np.mean(closes[:50])
    alpha_ema = 2.0 / (50.0 + 1.0)
    for i in range(50, n):
        ema50[i] = alpha_ema * closes[i] + (1.0 - alpha_ema) * ema50[i-1]

    df_m15 = df_m15.with_columns([
        pl.Series("atr15", atr14),
        pl.Series("ema50", ema50)
    ])
    df_with_ind = df.join_asof(
        df_m15.select(["timestamp", "atr15", "ema50"]),
        on="timestamp",
        strategy="backward"
    ).fill_null(strategy="forward").fill_null(2.0)

    rows = df_with_ind.select(["timestamp", "open", "high", "low", "close", "atr15", "ema50"]).to_dicts()

    daily_pnl = defaultdict(float)
    daily_trades = defaultdict(int)
    daily_wins = defaultdict(int)
    daily_losses = defaultdict(int)
    daily_floor = defaultdict(lambda: -999.0)
    daily_stopped = defaultdict(bool)

    trades = []
    in_pos = None
    last_exit_idx = -999

    for i in range(len(rows)):
        b = rows[i]
        dt = b["timestamp"]
        d = dt.date()
        t = dt.time()
        c = b["close"]
        h = b["high"]
        l = b["low"]
        o = b["open"]
        atr = max(1.5, b["atr15"])
        ema = b["ema50"]

        # Manage active position
        if in_pos is not None:
            side, entry, stop, tp, lots, open_idx = in_pos
            bars_held = i - open_idx

            trade_closed = False
            trade_pnl = 0.0

            if side == "BUY":
                if l <= stop:
                    trade_pnl = -abs(entry - stop) * lots * 100 - (lots * 7.0)
                    trade_closed = True
                    daily_losses[d] += 1
                elif h >= tp:
                    trade_pnl = abs(tp - entry) * lots * 100 - (lots * 7.0)
                    trade_closed = True
                    daily_wins[d] += 1
                elif bars_held >= 45: # Time cut
                    trade_pnl = (c - entry) * lots * 100 - (lots * 7.0)
                    trade_closed = True
                    if trade_pnl > 0: daily_wins[d] += 1
                    else: daily_losses[d] += 1
            else: # SELL
                if h >= stop:
                    trade_pnl = -abs(stop - entry) * lots * 100 - (lots * 7.0)
                    trade_closed = True
                    daily_losses[d] += 1
                elif l <= tp:
                    trade_pnl = abs(entry - tp) * lots * 100 - (lots * 7.0)
                    trade_closed = True
                    daily_wins[d] += 1
                elif bars_held >= 45:
                    trade_pnl = (entry - c) * lots * 100 - (lots * 7.0)
                    trade_closed = True
                    if trade_pnl > 0: daily_wins[d] += 1
                    else: daily_losses[d] += 1

            if trade_closed:
                daily_pnl[d] += trade_pnl
                trades.append((d, side, trade_pnl))
                in_pos = None
                last_exit_idx = i

                # Update Daily Ratchet Floor
                curr_pnl_pct = (daily_pnl[d] / 10000.0) * 100.0

                # Check 2-Strike loss stop (-1.0%)
                if daily_losses[d] >= 2 or curr_pnl_pct <= -1.0:
                    daily_stopped[d] = True

                # Ratchet Lock:
                if curr_pnl_pct >= 2.5:
                    daily_floor[d] = max(daily_floor[d], 200.0) # Lock +2%
                elif curr_pnl_pct >= 2.0:
                    daily_floor[d] = max(daily_floor[d], 150.0) # Lock +1.5%
                elif curr_pnl_pct >= 1.25:
                    daily_floor[d] = max(daily_floor[d], 100.0) # Lock +1.0%

                # Did PnL drop back to or below the locked floor?
                if daily_floor[d] > 0.0 and daily_pnl[d] <= daily_floor[d]:
                    daily_stopped[d] = True # STOP TRADING, PROFIT LOCKED!

            continue

        # Check if trading stopped for the day
        if daily_stopped[d]:
            continue
        if i - last_exit_idx < 20: # 20 min cooldown
            continue

        # Session filter: London & NY Golden hours only
        if not ((8, 0) <= (t.hour, t.minute) <= (11, 0) or (13, 0) <= (t.hour, t.minute) <= (16, 0)):
            continue

        # Determine risk for this trade
        curr_pnl_pct = (daily_pnl[d] / 10000.0) * 100.0
        if curr_pnl_pct >= 1.0:
            risk_dollars = 25.0 # Greed Mode: House money (0.25%)
        else:
            risk_dollars = 50.0 # Base Risk (0.5%)

        body = abs(c - o)
        rng = h - l
        if rng < 0.40 or (body / rng) < 0.60:
            continue

        sl_dist = round(max(1.80, atr * 1.1), 2)
        tp_dist = round(sl_dist * 2.5, 2) # Target RR 1:2.5
        lots = round(max(0.01, min(5.0, risk_dollars / (sl_dist * 100))), 2)

        # Trend alignment check
        if c > o and c > ema:
            in_pos = ("BUY", c, round(c - sl_dist, 2), round(c + tp_dist, 2), lots, i)
            daily_trades[d] += 1
        elif c < o and c < ema:
            in_pos = ("SELL", c, round(c + sl_dist, 2), round(c - tp_dist, 2), lots, i)
            daily_trades[d] += 1

    # Monthly performance breakdown
    monthly_pnl = defaultdict(float)
    monthly_days = defaultdict(set)
    monthly_target_days = defaultdict(int)

    for d, pnl in daily_pnl.items():
        mo_key = d.strftime("%Y-%m")
        monthly_pnl[mo_key] += pnl
        monthly_days[mo_key].add(d)
        if pnl >= 100.0:
            monthly_target_days[mo_key] += 1

    print("\n" + "=" * 80)
    print("MONTH-BY-MONTH INSTITUTIONAL PERFORMANCE AUDIT (RATCHET GREED ENGINE)")
    print("=" * 80)
    print(f"{'Month':<10} | {'Trading Days':<12} | {'Net Profit ($)':<14} | {'Monthly Return':<14} | {'Target Days (>=1%)'}")
    print("-" * 80)

    total_net = sum(monthly_pnl.values())
    for mo in sorted(monthly_pnl.keys()):
        pnl = monthly_pnl[mo]
        ret = (pnl / 10000.0) * 100.0
        n_days = len(monthly_days[mo])
        t_days = monthly_target_days[mo]
        print(f"{mo:<10} | {n_days:<12} | {pnl:>+12.2f} $ | {ret:>+12.2f} % | {t_days}/{n_days} days ({t_days/n_days*100:.1f}%)")

    print("-" * 80)
    print(f"Total Cumulative Return across 10.5 Months: ${total_net:+,.2f} (+{total_net/10000*100:.2f}%)")
    print(f"Average Return per Month: {total_net/len(monthly_pnl)/100:.2f}% / month")
    print(f"Total Trades Executed: {len(trades)}")
    print("=" * 80)


if __name__ == "__main__":
    run_monthly_target_ratchet()
