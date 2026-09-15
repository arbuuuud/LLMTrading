import polars as pl
import numpy as np
from collections import defaultdict
from datetime import time

def run_directional_sniper():
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
    
    # 50 EMA on M15
    ema50 = np.zeros(n)
    ema50[49] = np.mean(closes[:50])
    alpha_ema = 2.0 / (50.0 + 1.0)
    for i in range(50, n):
        ema50[i] = alpha_ema * closes[i] + (1.0 - alpha_ema) * ema50[i-1]

    df_m15 = df_m15.with_columns([
        pl.Series("atr15", atr14),
        pl.Series("ema50", ema50)
    ])
    df_with_atr = df.join_asof(
        df_m15.select(["timestamp", "atr15", "ema50"]),
        on="timestamp",
        strategy="backward"
    ).fill_null(strategy="forward").fill_null(2.0)

    rows = df_with_atr.select(["timestamp", "open", "high", "low", "close", "atr15", "ema50"]).to_dicts()

    for target_rr in [2.0, 2.5, 3.0]:
        daily_pnl = defaultdict(float)
        daily_trades = defaultdict(int)
        trades = []
        in_pos = None

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

            if in_pos is not None:
                side, entry, stop, tp, lots, open_idx = in_pos
                bars_held = i - open_idx

                if side == "BUY":
                    if l <= stop:
                        loss_amt = abs(entry - stop) * lots * 100 + (lots * 7.0)
                        daily_pnl[d] -= loss_amt
                        trades.append(loss_amt * -1)
                        in_pos = None
                    elif h >= tp:
                        win_amt = abs(tp - entry) * lots * 100 - (lots * 7.0)
                        daily_pnl[d] += win_amt
                        trades.append(win_amt)
                        in_pos = None
                    elif bars_held >= 60:
                        pnl = (c - entry) * lots * 100 - (lots * 7.0)
                        daily_pnl[d] += pnl
                        trades.append(pnl)
                        in_pos = None
                else: # SELL
                    if h >= stop:
                        loss_amt = abs(stop - entry) * lots * 100 + (lots * 7.0)
                        daily_pnl[d] -= loss_amt
                        trades.append(loss_amt * -1)
                        in_pos = None
                    elif l <= tp:
                        win_amt = abs(entry - tp) * lots * 100 - (lots * 7.0)
                        daily_pnl[d] += win_amt
                        trades.append(win_amt)
                        in_pos = None
                    elif bars_held >= 60:
                        pnl = (entry - c) * lots * 100 - (lots * 7.0)
                        daily_pnl[d] += pnl
                        trades.append(pnl)
                        in_pos = None
                continue

            # Strict: Max 1 trade per day!
            if daily_trades[d] >= 1: continue

            # Golden Hours Only (London 08:00 - 10:30 UTC & NY 13:00 - 15:30 UTC)
            if not ((8, 0) <= (t.hour, t.minute) <= (10, 30) or (13, 0) <= (t.hour, t.minute) <= (15, 30)):
                continue

            body = abs(c - o)
            rng = h - l
            if rng < 0.50 or (body / rng) < 0.65: continue

            sl_dist = round(max(2.0, atr * 1.2), 2)
            tp_dist = round(sl_dist * target_rr, 2)
            lots = round(max(0.01, min(5.0, 50.0 / (sl_dist * 100))), 2)

            # Trend-Aligned Only: BUY if price > EMA50, SELL if price < EMA50
            if c > o and c > ema:
                in_pos = ("BUY", c, round(c - sl_dist, 2), round(c + tp_dist, 2), lots, i)
                daily_trades[d] += 1
            elif c < o and c < ema:
                in_pos = ("SELL", c, round(c + sl_dist, 2), round(c - tp_dist, 2), lots, i)
                daily_trades[d] += 1

        total_net = sum(trades)
        wins = sum(1 for t in trades if t > 0)
        n_tr = len(trades)
        wr = wins / n_tr * 100 if n_tr else 0
        gw = sum(t for t in trades if t > 0)
        gl = abs(sum(t for t in trades if t <= 0))
        pf = gw / gl if gl else 0
        target_days = sum(1 for p in daily_pnl.values() if p >= 100.0)
        green_days = sum(1 for p in daily_pnl.values() if p > 0.0)
        print(f"Target RR 1:{target_rr} -> Trades: {n_tr} | Win Rate: {wr:.1f}% | PF: {pf:.2f} | Net PnL: ${total_net:+,.2f} | Green Days: {green_days}/{len(daily_pnl)} ({green_days/len(daily_pnl)*100:.1f}%) | Days >= 1%: {target_days}")

if __name__ == "__main__":
    run_directional_sniper()
