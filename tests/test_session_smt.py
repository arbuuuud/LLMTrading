import sys
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from datetime import time


def main():
    print("Testing Session-Level SMT Divergence (Asia Range High/Low Sweep)...")
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

    print(f"Loaded {len(aligned):,} bars.")

    # Group by date and calculate Asia Session (00:00 - 06:00 UTC) High & Low for both Gold and Silver
    daily_data = defaultdict(list)
    for row in aligned.iter_rows(named=True):
        daily_data[row["timestamp"].date()].append(row)

    total_days = len(daily_data)
    bearish_smt_days = []
    bullish_smt_days = []

    for d, bars in sorted(daily_data.items()):
        # Asia bars: 00:00 - 06:00
        asia_bars = [b for b in bars if time(0, 0) <= b["timestamp"].time() < time(6, 0)]
        if len(asia_bars) < 60:
            continue

        gold_asia_high = max(b["gold_high"] for b in asia_bars)
        gold_asia_low = min(b["gold_low"] for b in asia_bars)

        silver_asia_high = max(b["silver_high"] for b in asia_bars)
        silver_asia_low = min(b["silver_low"] for b in asia_bars)

        # London & NY trading window: 07:00 - 15:00
        trade_bars = [b for b in bars if time(7, 0) <= b["timestamp"].time() < time(15, 0)]

        gold_trade_high = max(b["gold_high"] for b in trade_bars) if trade_bars else 0
        gold_trade_low = min(b["gold_low"] for b in trade_bars) if trade_bars else 0

        silver_trade_high = max(b["silver_high"] for b in trade_bars) if trade_bars else 0
        silver_trade_low = min(b["silver_low"] for b in trade_bars) if trade_bars else 0

        # Check Bearish SMT: Gold broke Asia High, but Silver DID NOT break Asia High
        gold_broke_high = (gold_trade_high > gold_asia_high + 0.15)
        silver_broke_high = (silver_trade_high > silver_asia_high + 0.01)

        gold_broke_low = (gold_trade_low < gold_asia_low - 0.15)
        silver_broke_low = (silver_trade_low < silver_asia_low - 0.01)

        if gold_broke_high and not silver_broke_high:
            bearish_smt_days.append((d, gold_asia_high, gold_trade_high, silver_asia_high, silver_trade_high))

        if gold_broke_low and not silver_broke_low:
            bullish_smt_days.append((d, gold_asia_low, gold_trade_low, silver_asia_low, silver_trade_low))

    print(f"\nTotal Valid Trading Days Evaluated: {total_days}")
    print(f"Bearish SMT Days (Gold swept Asia High, Silver held below Asia High): {len(bearish_smt_days)} days ({len(bearish_smt_days)/total_days*100:.1f}%)")
    print(f"Bullish SMT Days (Gold swept Asia Low, Silver held above Asia Low):   {len(bullish_smt_days)} days ({len(bullish_smt_days)/total_days*100:.1f}%)")

    print("\nSample Bearish SMT Days:")
    for d, gah, gth, sah, sth in bearish_smt_days[:5]:
        print(f"  [{d}] Gold Asia H: ${gah:.2f} -> Swept to ${gth:.2f} (+${gth-gah:.2f}) | Silver Asia H: ${sah:.3f} -> Peak: ${sth:.3f} (Held below by ${sah-sth:.3f}!)")


if __name__ == "__main__":
    main()
