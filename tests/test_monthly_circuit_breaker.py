import sys
from pathlib import Path
from collections import defaultdict
from datetime import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
import numpy as np


def run_monthly_circuit_breaker():
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

    for monthly_loss_cap in [300.0, 400.0, 500.0]:
        daily_pnl = defaultdict(float)
        daily_trades = defaultdict(int)
        daily_losses = defaultdict(int)
        daily_floor = defaultdict(lambda: -999.0)
        daily_stopped = defaultdict(bool)
        monthly_pnl = defaultdict(float)
        monthly_stopped = defaultdict(bool)
        trades = []
        in_pos = None
        last_exit_idx = -999

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
                    elif bars_held >= 45:
                        trade_pnl = (c - entry) * lots * 100 - (lots * 7.0)
                        trade_closed = True
                else:
                    if h >= stop:
                        trade_pnl = -abs(stop - entry) * lots * 100 - (lots * 7.0)
                        trade_closed = True
                        daily_losses[d] += 1
                    elif l <= tp:
                        trade_pnl = abs(entry - tp) * lots * 100 - (lots * 7.0)
                        trade_closed = True
                    elif bars_held >= 45:
                        trade_pnl = (entry - c) * lots * 100 - (lots * 7.0)
                        trade_closed = True

                if trade_closed:
                    daily_pnl[d] += trade_pnl
                    monthly_pnl[mo] += trade_pnl
                    trades.append(trade_pnl)
                    in_pos = None
                    last_exit_idx = i

                    # Check monthly circuit breaker
                    if monthly_pnl[mo] <= -monthly_loss_cap:
                        monthly_stopped[mo] = True

                    # Daily Ratchet Floor
                    curr_pnl_pct = (daily_pnl[d] / 10000.0) * 100.0
                    if daily_losses[d] >= 2 or curr_pnl_pct <= -1.0:
                        daily_stopped[d] = True
                    if curr_pnl_pct >= 2.5: daily_floor[d] = max(daily_floor[d], 200.0)
                    elif curr_pnl_pct >= 2.0: daily_floor[d] = max(daily_floor[d], 150.0)
                    elif curr_pnl_pct >= 1.25: daily_floor[d] = max(daily_floor[d], 100.0)
                    if daily_floor[d] > 0.0 and daily_pnl[d] <= daily_floor[d]:
                        daily_stopped[d] = True
                continue

            if monthly_stopped[mo] or daily_stopped[d]:
                continue
            if i - last_exit_idx < 20:
                continue
            if not ((8, 0) <= (t.hour, t.minute) <= (11, 0) or (13, 0) <= (t.hour, t.minute) <= (16, 0)):
                continue

            curr_pnl_pct = (daily_pnl[d] / 10000.0) * 100.0
            risk_dollars = 25.0 if curr_pnl_pct >= 1.0 else 50.0

            body = abs(c - o)
            rng = h - l
            if rng < 0.40 or (body / rng) < 0.60: continue

            sl_dist = round(max(1.80, atr * 1.1), 2)
            tp_dist = round(sl_dist * 2.5, 2)
            lots = round(max(0.01, min(5.0, risk_dollars / (sl_dist * 100))), 2)

            if c > o and c > ema:
                in_pos = ("BUY", c, round(c - sl_dist, 2), round(c + tp_dist, 2), lots, i)
                daily_trades[d] += 1
            elif c < o and c < ema:
                in_pos = ("SELL", c, round(c + sl_dist, 2), round(c - tp_dist, 2), lots, i)
                daily_trades[d] += 1

        total_net = sum(monthly_pnl.values())
        green_months = sum(1 for pnl in monthly_pnl.values() if pnl > 0)
        print(f"Monthly Loss Cap -${monthly_loss_cap:.0f} (-{monthly_loss_cap/100:.1f}%) -> Total Net: ${total_net:+,.2f} | Green Months: {green_months}/{len(monthly_pnl)} | Trades: {len(trades)}")
        for mo in sorted(monthly_pnl.keys()):
            print(f"   {mo}: ${monthly_pnl[mo]:>+9.2f}")
        print("-" * 75)

if __name__ == "__main__":
    run_monthly_circuit_breaker()
