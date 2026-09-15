import sys
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from datetime import time


def main():
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

    reversal_profits = []

    for d, bars in sorted(daily_data.items()):
        asia_bars = [b for b in bars if time(0, 0) <= b["timestamp"].time() < time(6, 0)]
        trade_bars = [b for b in bars if time(7, 0) <= b["timestamp"].time() < time(15, 0)]
        if len(asia_bars) < 60 or len(trade_bars) < 60:
            continue

        gold_asia_high = max(b["gold_high"] for b in asia_bars)
        gold_asia_low = min(b["gold_low"] for b in asia_bars)

        silver_asia_high = max(b["silver_high"] for b in asia_bars)
        silver_asia_low = min(b["silver_low"] for b in asia_bars)

        gold_trade_high = max(b["gold_high"] for b in trade_bars)
        gold_trade_low = min(b["gold_low"] for b in trade_bars)
        silver_trade_high = max(b["silver_high"] for b in trade_bars)
        silver_trade_low = min(b["silver_low"] for b in trade_bars)

        # Check Bearish SMT
        if (gold_trade_high > gold_asia_high + 0.20) and (silver_trade_high <= silver_asia_high + 0.01):
            post_sweep_low = min(b["gold_low"] for b in trade_bars)
            reversal_distance = gold_trade_high - post_sweep_low
            reversal_profits.append((d, "BEARISH_SMT", gold_trade_high, post_sweep_low, reversal_distance))

        # Check Bullish SMT
        if (gold_trade_low < gold_asia_low - 0.20) and (silver_trade_low >= silver_asia_low - 0.01):
            post_sweep_high = max(b["gold_high"] for b in trade_bars)
            reversal_distance = post_sweep_high - gold_trade_low
            reversal_profits.append((d, "BULLISH_SMT", gold_trade_low, post_sweep_high, reversal_distance))

    print(f"Total SMT Reversal Days Evaluated: {len(reversal_profits)}")
    avg_move = sum(r[4] for r in reversal_profits) / len(reversal_profits) if reversal_profits else 0
    print(f"Average Post-SMT Reversal Expansion: ${avg_move:.2f} ({avg_move*100:.0f} pips)!\n")

    for d, tag, entry_lvl, exit_lvl, move in reversal_profits[:12]:
        direction = "PLUNGE (Sell)" if tag == "BEARISH_SMT" else "RALLY (Buy)"
        print(f"  [{d}] {tag:<11} -> {direction}: ${move:.2f} ({move*100:.0f} pips!)")


if __name__ == "__main__":
    main()
