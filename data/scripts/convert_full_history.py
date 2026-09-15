"""
Full MT5 Historical Tick to Parquet Converter.
Stream-processes the complete 77.3 million ticks (3.07 GB CSV) in memory-safe chunks
using Polars to produce the full 10.5-month M1 and M5 Parquet bar datasets.
"""

import sys
import time
from pathlib import Path
import polars as pl
from tqdm import tqdm

RAW_CSV_PATH = Path("/Users/alami/mt5prefix/drive_c/Program Files/MetaTrader 5/MQL5/Files/XAUUSD_202505271036_202604022259.csv")
OUT_DIR_M1 = Path("data/processed/bars/XAUUSD/M1")
OUT_DIR_M5 = Path("data/processed/bars/XAUUSD/M5")


def process_full_ticks(batch_size: int = 5_000_000, max_batches: int = None):
    print("=" * 75)
    print("STARTING FULL HISTORICAL TICK INGESTION (77.3M Ticks)")
    print(f"Source File: {RAW_CSV_PATH} ({RAW_CSV_PATH.stat().st_size / (1024**3):.2f} GB)")
    print(f"Batch Size: {batch_size:,} ticks per chunk")
    print("=" * 75)

    OUT_DIR_M1.mkdir(parents=True, exist_ok=True)
    OUT_DIR_M5.mkdir(parents=True, exist_ok=True)

    reader = pl.read_csv_batched(
        RAW_CSV_PATH,
        separator="\t",
        batch_size=batch_size,
        has_header=True,
        truncate_ragged_lines=True
    )

    m1_batches = []
    total_ticks = 0
    batch_idx = 0
    t_start = time.time()

    while True:
        batches = reader.next_batches(1)
        if not batches:
            break

        df_chunk = batches[0]
        n_rows = len(df_chunk)
        if n_rows == 0:
            break

        batch_idx += 1
        total_ticks += n_rows

        t0 = time.time()
        # MT5 headers: <DATE>, <TIME>, <BID>, <ASK>, <LAST>, <VOLUME>, <FLAGS>
        cleaned = df_chunk.select([
            (pl.col("<DATE>") + " " + pl.col("<TIME>")).str.to_datetime("%Y.%m.%d %H:%M:%S%.f").alias("timestamp"),
            pl.col("<BID>").cast(pl.Float64).alias("bid"),
            pl.col("<ASK>").cast(pl.Float64).alias("ask")
        ]).filter(
            (pl.col("bid") > 0.0) &
            (pl.col("ask") >= pl.col("bid"))
        ).with_columns(
            (pl.col("ask") - pl.col("bid")).round(3).alias("spread")
        )

        # Truncate timestamp to minute
        cleaned = cleaned.with_columns(
            pl.col("timestamp").dt.truncate("1m").alias("bar_time")
        )

        # Aggregate to M1 bars in this batch
        m1_chunk = cleaned.group_by("bar_time").agg([
            pl.col("bid").first().alias("open"),
            pl.col("bid").max().alias("high"),
            pl.col("bid").min().alias("low"),
            pl.col("bid").last().alias("close"),
            pl.len().alias("tick_volume"),
            pl.col("spread").mean().round(3).alias("mean_spread"),
            pl.col("spread").max().round(3).alias("max_spread")
        ]).sort("bar_time")

        m1_batches.append(m1_chunk)
        elapsed = time.time() - t0
        print(f"Batch #{batch_idx:02d}: Processed {n_rows:,} ticks in {elapsed:.2f}s -> {len(m1_chunk):,} M1 bars (Total ticks so far: {total_ticks:,})")

        if max_batches and batch_idx >= max_batches:
            print(f"[Notice] Reached max_batches={max_batches}, finishing early...")
            break

    print("\n[Pipeline] Concatenating and finalizing all M1 bars...")
    df_all_m1 = pl.concat(m1_batches)

    # In case minutes crossed batch boundaries, group once more
    final_m1 = df_all_m1.group_by("bar_time").agg([
        pl.col("open").first(),
        pl.col("high").max(),
        pl.col("low").min(),
        pl.col("close").last(),
        pl.col("tick_volume").sum(),
        pl.col("mean_spread").mean().round(3),
        pl.col("max_spread").max().round(3)
    ]).rename({"bar_time": "timestamp"}).sort("timestamp")

    final_m1 = final_m1.with_columns(
        (pl.col("mean_spread") / 0.01).round(1).alias("mean_spread_pts"),
        (pl.col("max_spread") / 0.01).round(1).alias("max_spread_pts")
    )

    out_m1_path = OUT_DIR_M1 / "XAUUSD_M1.parquet"
    final_m1.write_parquet(out_m1_path, compression="zstd")
    print(f"  -> Saved {len(final_m1):,} M1 bars to {out_m1_path} ({out_m1_path.stat().st_size / (1024**2):.2f} MB)")

    # Resample to M5
    print("[Pipeline] Resampling M1 to M5 bars...")
    final_m5 = final_m1.group_by_dynamic("timestamp", every="5m").agg([
        pl.col("open").first(),
        pl.col("high").max(),
        pl.col("low").min(),
        pl.col("close").last(),
        pl.col("tick_volume").sum(),
        pl.col("mean_spread").mean().round(3),
        pl.col("max_spread").max().round(3),
        pl.col("mean_spread_pts").mean().round(1),
        pl.col("max_spread_pts").max().round(1)
    ]).sort("timestamp")

    out_m5_path = OUT_DIR_M5 / "XAUUSD_M5.parquet"
    final_m5.write_parquet(out_m5_path, compression="zstd")
    print(f"  -> Saved {len(final_m5):,} M5 bars to {out_m5_path} ({out_m5_path.stat().st_size / (1024**2):.2f} MB)")

    total_time = time.time() - t_start
    print("=" * 75)
    print(f"FULL INGESTION COMPLETED in {total_time:.1f}s ({total_time/60:.1f} minutes)!")
    print(f"Total Ticks: {total_ticks:,}")
    print(f"Total M1 Bars: {len(final_m1):,} ({final_m1['timestamp'].min()} to {final_m1['timestamp'].max()})")
    print(f"Total M5 Bars: {len(final_m5):,}")
    print("=" * 75)


if __name__ == "__main__":
    process_full_ticks()
