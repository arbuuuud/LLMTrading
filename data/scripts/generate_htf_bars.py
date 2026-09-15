import polars as pl
from pathlib import Path
import os

def generate_htf_bars(symbol: str = "XAUUSD", input_tf: str = "M1", output_tfs: list = None):
    if output_tfs is None:
        output_tfs = ["M5", "M15", "H1", "H4"]

    input_path = Path(f"data/processed/bars/{symbol}/{input_tf}/{symbol}_{input_tf}.parquet")
    output_dir = Path(f"data/processed/bars/{symbol}/HTF/")
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[HTF Generator] Loading {input_path}...")
    try:
        df_m1 = pl.read_parquet(input_path)
    except FileNotFoundError:
        print(f"Error: Input file {input_path} not found. Please ensure M1 data exists.")
        return
    
    # Ensure timestamp column is datetime and set as sorted
    df_m1 = df_m1.with_columns(pl.col("timestamp").cast(pl.Datetime).alias("timestamp"))
    df_m1 = df_m1.sort("timestamp")
    
    print(f"[HTF Generator] Loaded {len(df_m1):,} {input_tf} bars. Generating HTF bars...")

    for tf_str in output_tfs:
        print(f"[HTF Generator] Resampling to {tf_str}...")
        # Convert TF string to Polars duration string
        if tf_str == "M5":
            interval = "5m"
        elif tf_str == "M15":
            interval = "15m"
        elif tf_str == "H1":
            interval = "1h"
        elif tf_str == "H4":
            interval = "4h"
        else:
            print(f"Warning: Unsupported timeframe {tf_str}. Skipping.")
            continue

        # Resample logic
        # For each resampling group (defined by interval), aggregate OHLCV
        df_htf = df_m1.group_by_dynamic(
            index_column="timestamp",
            every=interval,
            offset="0s", # Ensure alignment from the start of the data
            closed="left", # Start of interval is inclusive
            label="left" # Label with the start of the interval
        ).agg([
            pl.col("open").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").last().alias("close"),
            pl.col("tick_volume").sum().alias("tick_volume"),
            pl.col("mean_spread").mean().alias("mean_spread"),
            pl.col("max_spread").max().alias("max_spread")
        ]).sort("timestamp")
        
        # Remove any rows with nulls from aggregation (e.g., if a group was empty)
        df_htf = df_htf.drop_nulls()

        output_path = output_dir / f"{symbol}_{tf_str}.parquet"
        df_htf.write_parquet(output_path)
        print(f"[HTF Generator] Generated {len(df_htf):,} {tf_str} bars to {output_path}")

    print("[HTF Generator] All HTF bars generated successfully.")

if __name__ == "__main__":
    generate_htf_bars()
