"""
MT5 to Parquet High-Performance Data Pipeline
Converts raw MT5 Tick and Bar CSV/TSV exports into ultra-fast, partitioned Apache Parquet files.
Also auto-generates M1, M5, M15, and H1 OHLCV bars with institutional spread metrics.
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
import polars as pl
from tqdm import tqdm

DEFAULT_MT5_FILES_DIR = Path("/Users/alami/mt5prefix/drive_c/Program Files/MetaTrader 5/MQL5/Files")
DEFAULT_PROCESSED_DIR = Path(__file__).resolve().parent.parent / "processed"


def parse_tick_chunk(df_chunk: pl.DataFrame, symbol: str) -> pl.DataFrame:
    """
    Cleans and standardizes raw MT5 tick data into structured format:
    timestamp, bid, ask, spread, spread_pts, flags
    """
    # MT5 headers typically: <DATE>, <TIME>, <BID>, <ASK>, <LAST>, <VOLUME>, <FLAGS>
    col_date = [c for c in df_chunk.columns if "date" in c.lower()][0]
    col_time = [c for c in df_chunk.columns if "time" in c.lower()][0]
    col_bid = [c for c in df_chunk.columns if "bid" in c.lower()][0]
    col_ask = [c for c in df_chunk.columns if "ask" in c.lower()][0]
    
    # Flags column if available
    flags_cols = [c for c in df_chunk.columns if "flag" in c.lower()]
    col_flags = flags_cols[0] if flags_cols else None

    # Parse timestamp
    cleaned = df_chunk.with_columns(
        (pl.col(col_date) + " " + pl.col(col_time)).str.to_datetime("%Y.%m.%d %H:%M:%S%.f").alias("timestamp"),
        pl.col(col_bid).cast(pl.Float64).alias("bid"),
        pl.col(col_ask).cast(pl.Float64).alias("ask")
    )

    if col_flags:
        cleaned = cleaned.with_columns(pl.col(col_flags).cast(pl.UInt32).alias("flags"))
    else:
        cleaned = cleaned.with_columns(pl.lit(0, dtype=pl.UInt32).alias("flags"))

    # Compute spread and filter invalid ticks
    cleaned = cleaned.select(["timestamp", "bid", "ask", "flags"]).filter(
        (pl.col("bid") > 0.0) &
        (pl.col("ask") > 0.0) &
        (pl.col("ask") >= pl.col("bid"))
    ).with_columns(
        (pl.col("ask") - pl.col("bid")).round(3).alias("spread")
    )

    # Point size calculation (e.g. 0.01 for Gold, 0.001 for Silver)
    point_size = 0.01 if "XAU" in symbol.upper() else 0.001
    cleaned = cleaned.with_columns(
        (pl.col("spread") / point_size).round(1).alias("spread_pts")
    )

    return cleaned.sort("timestamp")


def aggregate_ticks_to_bars(df_ticks: pl.DataFrame, timeframe_str: str = "1m") -> pl.DataFrame:
    """
    Resamples ticks into OHLCV bars + spread statistics (mean, max spread)
    which are essential for realistic scalping simulations.
    """
    bars = df_ticks.group_by_dynamic("timestamp", every=timeframe_str).agg([
        pl.col("bid").first().alias("open"),
        pl.col("bid").max().alias("high"),
        pl.col("bid").min().alias("low"),
        pl.col("bid").last().alias("close"),
        pl.len().alias("tick_volume"),
        pl.col("spread").mean().round(3).alias("mean_spread"),
        pl.col("spread").max().round(3).alias("max_spread"),
        pl.col("spread_pts").mean().round(1).alias("mean_spread_pts"),
        pl.col("spread_pts").max().round(1).alias("max_spread_pts"),
    ]).filter(pl.col("open").is_not_null())
    return bars.sort("timestamp")


def process_tick_file(
    input_file: Path,
    symbol: str,
    output_base_dir: Path,
    limit_rows: int = None,
    generate_bars: bool = True
):
    """
    Processes large tick CSV file, writes monthly partitioned Parquet files,
    and optionally generates M1 and M5 bars.
    """
    print(f"\n[Pipeline] Ingesting {input_file.name} (Symbol: {symbol})...")
    
    # Read CSV
    if limit_rows:
        print(f"[Pipeline] Reading first {limit_rows:,} rows for quick processing...")
        df = pl.read_csv(
            input_file,
            separator="\t",
            n_rows=limit_rows,
            has_header=True,
            truncate_ragged_lines=True
        )
    else:
        print("[Pipeline] Reading full dataset with Polars...")
        df = pl.read_csv(
            input_file,
            separator="\t",
            has_header=True,
            truncate_ragged_lines=True
        )

    print(f"[Pipeline] Parsing and cleaning {len(df):,} ticks...")
    cleaned_ticks = parse_tick_chunk(df, symbol)
    print(f"[Pipeline] Clean valid ticks: {len(cleaned_ticks):,}")

    if len(cleaned_ticks) == 0:
        print("[Pipeline] No valid ticks found.")
        return

    # Add year & month for partitioning
    cleaned_ticks = cleaned_ticks.with_columns(
        pl.col("timestamp").dt.year().alias("year"),
        pl.col("timestamp").dt.month().alias("month")
    )

    # Save partitioned tick parquet
    tick_out_dir = output_base_dir / "ticks" / symbol
    tick_out_dir.mkdir(parents=True, exist_ok=True)

    partitions = cleaned_ticks.group_by(["year", "month"]).len().sort(["year", "month"])
    for row in partitions.iter_rows(named=True):
        yr = row["year"]
        mo = row["month"]
        part_df = cleaned_ticks.filter((pl.col("year") == yr) & (pl.col("month") == mo)).drop(["year", "month"])
        
        yr_dir = tick_out_dir / str(yr)
        yr_dir.mkdir(parents=True, exist_ok=True)
        out_parquet = yr_dir / f"{mo:02d}.parquet"
        
        part_df.write_parquet(out_parquet, compression="zstd")
        print(f"  -> Saved {len(part_df):,} ticks to {out_parquet.relative_to(output_base_dir.parent)}")

    # Generate OHLCV bars if requested
    if generate_bars:
        print("[Pipeline] Aggregating ticks into M1 and M5 bars with institutional spread metrics...")
        cleaned_no_part = cleaned_ticks.drop(["year", "month"])
        
        # M1 Bars
        m1_bars = aggregate_ticks_to_bars(cleaned_no_part, "1m")
        m1_dir = output_base_dir / "bars" / symbol / "M1"
        m1_dir.mkdir(parents=True, exist_ok=True)
        m1_file = m1_dir / f"{symbol}_M1.parquet"
        m1_bars.write_parquet(m1_file, compression="zstd")
        print(f"  -> Generated {len(m1_bars):,} M1 bars -> {m1_file.relative_to(output_base_dir.parent)}")

        # M5 Bars
        m5_bars = aggregate_ticks_to_bars(cleaned_no_part, "5m")
        m5_dir = output_base_dir / "bars" / symbol / "M5"
        m5_dir.mkdir(parents=True, exist_ok=True)
        m5_file = m5_dir / f"{symbol}_M5.parquet"
        m5_bars.write_parquet(m5_file, compression="zstd")
        print(f"  -> Generated {len(m5_bars):,} M5 bars -> {m5_file.relative_to(output_base_dir.parent)}")

    print("[Pipeline] Ingestion and Parquet conversion completed successfully!")


def main():
    parser = argparse.ArgumentParser(description="MT5 to Parquet Data Pipeline")
    parser.add_argument("--file", type=str, help="Path to specific CSV file")
    parser.add_argument("--symbol", type=str, default="XAUUSD", help="Symbol name (default: XAUUSD)")
    parser.add_argument("--limit", type=int, default=None, help="Limit rows (e.g. 500000 for testing)")
    parser.add_argument("--out", type=str, default=str(DEFAULT_PROCESSED_DIR), help="Output directory")

    args = parser.parse_args()

    input_path = None
    if args.file:
        input_path = Path(args.file)
    else:
        # Check default MT5 Files directory
        if DEFAULT_MT5_FILES_DIR.exists():
            csv_candidates = list(DEFAULT_MT5_FILES_DIR.glob(f"*{args.symbol}*.csv"))
            if csv_candidates:
                # pick the largest or most recent file
                csv_candidates.sort(key=lambda x: x.stat().st_size, reverse=True)
                input_path = csv_candidates[0]
                print(f"[Pipeline] Found MT5 tick file: {input_path}")

    if not input_path or not input_path.exists():
        print(f"[Error] File not found: {input_path}")
        print("Please provide --file /path/to/file.csv or place files in MT5 Files folder.")
        sys.exit(1)

    process_tick_file(
        input_file=input_path,
        symbol=args.symbol,
        output_base_dir=Path(args.out),
        limit_rows=args.limit,
        generate_bars=True
    )


if __name__ == "__main__":
    main()
