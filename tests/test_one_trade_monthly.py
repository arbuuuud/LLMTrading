import polars as pl
import numpy as np
from collections import defaultdict
from datetime import time

def run_one_trade_month_breakdown():
    df = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")

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

    ema50 = np.zeros(n)
    ema50[49] = np.mean(closes[:50])
    alpha_ema = 2.0 / (50.0 + 1.0)
    for i in range(50, n):
        ema50[i] = alpha_ema * closes[i] + (1.0 - alpha_ema) * ema50[i-1]

    df_m15 = df_m15.with_columns([pl.Series("atr15", atr14), pl.Series("ema50", ema50)])
    df_with_ind = df.join_asof(df_m15.select(["timestamp", "atr15", "ema50"]), on="timestamp", strategy="backward").fill_null(strategy="forward").fill_null(2.0)

    rows = df_with_ind.select(["timestamp", "open", "high", "low", "close", "atr15", "ema50"]).to_dicts()

    daily_trades = defaultdict(int)
    monthly_pnl = defaultdict(float)
    monthly_wins = defaultdict(int)
    monthly_losses = defaultdict(int)
    in_pos = None

    for i in range(len(rows)):
        b = rows[i]
        dt = b["timestamp"]
        d = dt.date()
        mo = d.strftime("%Y-%m")
        t = dt.time()
        c = b["close"]
        h = b["high"]
        l = b["low"]
        o = b["open"]
        atr = max(1.5, b["atr15"])
        ema = b["ema50"]

        if in_pos is not None:
            side, entry, stop, tp, lots, open_idx = in_pos
            bars_held = i - open_idx
            closed = False
            pnl = 0.0

            if side == "BUY":
                if l <= stop:
                    pnl = -abs(entry - stop) * lots * 100 - (lots * 7.0)
                    closed = True
                    monthly_losses[mo] += 1
                elif h >= tp:
                    pnl = abs(tp - entry) * lots * 100 - (lots * 7.0)
                    closed = True
                    monthly_wins[mo] += 1
                elif bars_held >= 60:
                    pnl = (c - entry) * lots * 100 - (lots * 7.0)
                    closed = True
                    if pnl > 0: monthly_wins[mo] += 1
                    else: monthly_losses[mo] += 1
            else:
                if h >= stop:
                    pnl = -abs(stop - entry) * lots * 100 - (lots * 7.0)
                    closed = True
                    monthly_losses[mo] += 1
                elif l <= tp:
                    pnl = abs(entry - tp) * lots * 100 - (lots * 7.0)
                    closed = True
                    monthly_wins[mo] += 1
                elif bars_held >= 60:
                    pnl = (entry - c) * lots * 100 - (lots * 7.0)
                    closed = True
                    if pnl > 0: monthly_wins[mo] += 1
                    else: monthly_losses[mo] += 1

            if closed:
                monthly_pnl[mo] += pnl
                in_pos = None
            continue

        if daily_trades[d] >= 1:
            continue

        if not ((8, 0) <= (t.hour, t.minute) <= (10, 30) or (13, 0) <= (t.hour, t.minute) <= (15, 30)):
            continue

        body = abs(c - o)
        rng = h - l
        if rng < 0.50 or (body / rng) < 0.65:
            continue

        sl_dist = round(max(2.0, atr * 1.2), 2)
        tp_dist = round(sl_dist * 2.5, 2)
        lots = round(max(0.01, min(5.0, 50.0 / (sl_dist * 100))), 2)

        if c > o and c > ema:
            in_pos = ("BUY", c, round(c - sl_dist, 2), round(c + tp_dist, 2), lots, i)
            daily_trades[d] += 1
        elif c < o and c < ema:
            in_pos = ("SELL", c, round(c + sl_dist, 2), round(c - tp_dist, 2), lots, i)
            daily_trades[d] += 1

    print("\n" + "=" * 70)
    print("ONE-TRADE PER DAY SNIPER: MONTH-BY-MONTH AUDIT")
    print("=" * 70)
    total_pnl = sum(monthly_pnl.values())
    for mo in sorted(monthly_pnl.keys()):
        w = monthly_wins[mo]
        l = monthly_losses[mo]
        tot = w + l
        wr = (w / tot * 100) if tot else 0
        print(f"{mo}: ${monthly_pnl[mo]:>+8.2f} | {w}W / {l}L ({wr:.1f}%) | {tot} trades")
    print("-" * 70)
    print(f"Total Net Return: ${total_pnl:+,.2f} (+{total_pnl/100:.2f}%)")
    print("=" * 70)

if __name__ == "__main__":
    run_one_trade_month_breakdown()
