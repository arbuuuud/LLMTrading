import sys
from pathlib import Path
from collections import defaultdict
from datetime import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl


def main():
    print("Evaluating High-Conviction SMT Traps with Institutional Targets ($5 - $15 Move)...")
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

    for target_reward in [3.0, 5.0, 8.0, 12.0]:
        sl_risk = 2.0
        wins = 0
        losses = 0
        total_pnl = 0.0
        total_comm = 0.0

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
            in_pos = None

            for b in trade_bars:
                gh = b["gold_high"]
                gl = b["gold_low"]
                gc = b["gold_close"]
                sh = b["silver_high"]
                sl = b["silver_low"]
                silver_running_high = max(silver_running_high, sh)
                silver_running_low = min(silver_running_low, sl)

                # If in position, check exit
                if in_pos is not None:
                    side, entry, stop, tp = in_pos
                    if side == "SELL":
                        if gh >= stop:
                            losses += 1
                            loss_amt = abs(stop - entry) * 0.25 * 100
                            total_pnl -= (loss_amt + 1.75)
                            total_comm += 1.75
                            in_pos = None
                            break  # 1 trade per day
                        elif gl <= tp:
                            wins += 1
                            win_amt = abs(entry - tp) * 0.25 * 100
                            total_pnl += (win_amt - 1.75)
                            total_comm += 1.75
                            in_pos = None
                            break
                    elif side == "BUY":
                        if gl <= stop:
                            losses += 1
                            loss_amt = abs(entry - stop) * 0.25 * 100
                            total_pnl -= (loss_amt + 1.75)
                            total_comm += 1.75
                            in_pos = None
                            break
                        elif gh >= tp:
                            wins += 1
                            win_amt = abs(tp - entry) * 0.25 * 100
                            total_pnl += (win_amt - 1.75)
                            total_comm += 1.75
                            in_pos = None
                            break
                    continue

                # Check SMT trigger
                if gh > gold_asia_high + 0.25 and silver_running_high <= silver_asia_high + 0.015:
                    if gc < gh - 0.20:  # Wick rejection
                        in_pos = ("SELL", gc, gh + 0.50, gc - target_reward)
                elif gl < gold_asia_low - 0.25 and silver_running_low >= silver_asia_low - 0.015:
                    if gc > gl + 0.20:
                        in_pos = ("BUY", gc, gl - 0.50, gc + target_reward)

        total_trades = wins + losses
        wr = (wins / total_trades * 100) if total_trades > 0 else 0
        print(f"Target ${target_reward:.1f} (Risk $2.0) -> Trades: {total_trades} | Win: {wr:.1f}% | Net PnL: ${total_pnl:+,.2f} | Comm: ${total_comm:,.2f}")


if __name__ == "__main__":
    main()
