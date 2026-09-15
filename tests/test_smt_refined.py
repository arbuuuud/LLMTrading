import sys
from pathlib import Path
from collections import defaultdict
from datetime import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl


def test_refined_smt(min_sweep=1.0, min_sl=2.0, rr=2.5):
    df_gold = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")
    df_silver = pl.read_parquet("data/processed/bars/XAGUSD/M1/XAGUSD_M1.parquet")

    aligned = df_gold.select([
        pl.col("timestamp"),
        pl.col("open").alias("gold_open"),
        pl.col("high").alias("gold_high"),
        pl.col("low").alias("gold_low"),
        pl.col("close").alias("gold_close"),
    ]).join(
        df_silver.select([
            pl.col("timestamp"),
            pl.col("open").alias("silver_open"),
            pl.col("high").alias("silver_high"),
            pl.col("low").alias("silver_low"),
            pl.col("close").alias("silver_close")
        ]),
        on="timestamp",
        how="inner"
    ).sort("timestamp")

    daily_data = defaultdict(list)
    for row in aligned.iter_rows(named=True):
        daily_data[row["timestamp"].date()].append(row)

    wins = 0
    losses = 0
    total_net = 0.0
    trades = []

    for d, bars in sorted(daily_data.items()):
        asia_bars = [b for b in bars if time(0, 0) <= b["timestamp"].time() < time(6, 0)]
        trade_bars = [b for b in bars if time(7, 0) <= b["timestamp"].time() < time(16, 0)]
        if len(asia_bars) < 60 or len(trade_bars) < 60:
            continue

        gold_asia_high = max(b["gold_high"] for b in asia_bars)
        gold_asia_low = min(b["gold_low"] for b in asia_bars)
        silver_asia_high = max(b["silver_high"] for b in asia_bars)
        silver_asia_low = min(b["silver_low"] for b in asia_bars)

        silver_running_high = 0.0
        silver_running_low = 9999.0
        trade_today = False

        for idx, b in enumerate(trade_bars):
            if trade_today:
                break
            gh = b["gold_high"]
            gl = b["gold_low"]
            gc = b["gold_close"]
            go = b["gold_open"]
            sh = b["silver_high"]
            sl = b["silver_low"]

            silver_running_high = max(silver_running_high, sh)
            silver_running_low = min(silver_running_low, sl)

            # Bearish SMT: Gold swept Asia High by >= min_sweep, Silver failed, and Gold closed red back inside
            if gh >= gold_asia_high + min_sweep and silver_running_high <= silver_asia_high + 0.02:
                if gc < go and gc < gold_asia_high + 0.20:
                    entry = gc
                    stop = max(gh + 0.50, entry + min_sl)
                    risk_dist = stop - entry
                    tp = entry - (risk_dist * rr)
                    lots = round(50.0 / (risk_dist * 100), 2)  # $50 risk (0.5%)

                    # Simulate remaining bars of the day
                    hit_tp = False
                    hit_sl = False
                    for future_b in trade_bars[idx+1:]:
                        if future_b["gold_high"] >= stop:
                            hit_sl = True
                            break
                        elif future_b["gold_low"] <= tp:
                            hit_tp = True
                            break

                    trade_today = True
                    comm = lots * 7.0
                    if hit_tp:
                        wins += 1
                        pnl = (risk_dist * rr * lots * 100) - comm
                        total_net += pnl
                        trades.append((d, "SELL", entry, stop, tp, pnl, "WIN"))
                    elif hit_sl:
                        losses += 1
                        pnl = -(risk_dist * lots * 100) - comm
                        total_net += pnl
                        trades.append((d, "SELL", entry, stop, tp, pnl, "LOSS"))
                    else:
                        # End of day close
                        exit_p = trade_bars[-1]["gold_close"]
                        pnl = ((entry - exit_p) * lots * 100) - comm
                        total_net += pnl
                        if pnl > 0: wins += 1
                        else: losses += 1
                        trades.append((d, "SELL", entry, stop, tp, pnl, "EOD"))

            # Bullish SMT: Gold swept Asia Low by >= min_sweep, Silver failed, and Gold closed green back inside
            elif gl <= gold_asia_low - min_sweep and silver_running_low >= silver_asia_low - 0.02:
                if gc > go and gc > gold_asia_low - 0.20:
                    entry = gc
                    stop = min(gl - 0.50, entry - min_sl)
                    risk_dist = entry - stop
                    tp = entry + (risk_dist * rr)
                    lots = round(50.0 / (risk_dist * 100), 2)

                    hit_tp = False
                    hit_sl = False
                    for future_b in trade_bars[idx+1:]:
                        if future_b["gold_low"] <= stop:
                            hit_sl = True
                            break
                        elif future_b["gold_high"] >= tp:
                            hit_tp = True
                            break

                    trade_today = True
                    comm = lots * 7.0
                    if hit_tp:
                        wins += 1
                        pnl = (risk_dist * rr * lots * 100) - comm
                        total_net += pnl
                        trades.append((d, "BUY", entry, stop, tp, pnl, "WIN"))
                    elif hit_sl:
                        losses += 1
                        pnl = -(risk_dist * lots * 100) - comm
                        total_net += pnl
                        trades.append((d, "BUY", entry, stop, tp, pnl, "LOSS"))
                    else:
                        exit_p = trade_bars[-1]["gold_close"]
                        pnl = ((exit_p - entry) * lots * 100) - comm
                        total_net += pnl
                        if pnl > 0: wins += 1
                        else: losses += 1
                        trades.append((d, "BUY", entry, stop, tp, pnl, "EOD"))

    total = wins + losses
    wr = (wins / total * 100) if total > 0 else 0
    print(f"Sweep >= ${min_sweep:.2f} | Min SL ${min_sl:.2f} | RR 1:{rr} -> Trades: {total} | Win: {wr:.1f}% | Net PnL: ${total_net:+,.2f}")
    return trades


def main():
    print("Testing Refined SMT Sweep Parameters across 10.5 months:")
    for sweep_depth in [0.50, 1.00, 1.50, 2.00]:
        for sl_dist in [1.50, 2.00, 2.50]:
            for r in [1.8, 2.0, 2.5]:
                test_refined_smt(min_sweep=sweep_depth, min_sl=sl_dist, rr=r)


if __name__ == "__main__":
    main()
