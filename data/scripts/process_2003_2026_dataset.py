"""
Institutional Data Ingestion & HTF Multi-Timeframe Resampler.
Processes 23.3 years (2003 - 2026) of raw XAUUSD M1 broker data (~7.93M bars)
into high-performance, compressed Parquet files (ZSTD) across all institutional timeframes:
- M1 (1-Minute Execution Core)
- M5 (5-Minute Structural Wave)
- M15 (15-Minute Base & Zone Detection)
- H1 (Hourly Macro Trend & EMA 50)
- H4 (4-Hour Swing Bias)
- D1 (Daily Institutional Range)
"""

import sys
import time
from pathlib import Path
import polars as pl

RAW_CSV = Path("data/raw/XAUUSD_icmarkets(2).csv")
BASE_DIR = Path("data/processed/bars/XAUUSD")
DIR_M1 = BASE_DIR / "M1"
DIR_HTF = BASE_DIR / "HTF"


def process_dataset():
    t_start = time.time()
    print("=" * 80)
    print("🚀 INSTITUTIONAL INGESTION: XAUUSD 2003 - 2026 (23.3 YEARS)")
    print(f"Source Raw CSV: {RAW_CSV} ({RAW_CSV.stat().st_size / (1024**2):.2f} MB)")
    print("=" * 80)

    DIR_M1.mkdir(parents=True, exist_ok=True)
    DIR_HTF.mkdir(parents=True, exist_ok=True)

    print("\n[Phase 1/6] Ingesting and validating raw M1 bars with Polars...")
    t0 = time.time()

    lf = pl.scan_csv(
        RAW_CSV,
        has_header=False,
        new_columns=["date", "time", "open", "high", "low", "close", "tick_volume", "real_volume", "spread_pts"],
        schema_overrides={
            "date": pl.String,
            "time": pl.String,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "tick_volume": pl.Float64,
            "real_volume": pl.Float64,
            "spread_pts": pl.Float64
        }
    )

    cleaned_m1 = lf.select([
        (pl.col("date") + " " + pl.col("time")).str.to_datetime("%Y.%m.%d %H:%M").alias("timestamp"),
        pl.col("open").round(2),
        pl.col("high").round(2),
        pl.col("low").round(2),
        pl.col("close").round(2),
        pl.col("tick_volume").cast(pl.UInt32).alias("tick_volume"),
        (pl.col("spread_pts") * 0.01).round(3).alias("mean_spread"),
        (pl.col("spread_pts") * 0.01).round(3).alias("max_spread"),
        pl.col("spread_pts").round(1).alias("mean_spread_pts"),
        pl.col("spread_pts").round(1).alias("max_spread_pts")
    ]).filter(
        (pl.col("open") > 0.0) &
        (pl.col("high") >= pl.col("low")) &
        (pl.col("close") > 0.0)
    ).sort("timestamp").unique(subset=["timestamp"], keep="last")

    df_m1 = cleaned_m1.collect()
    t_collect = time.time() - t0
    print(f"  -> Successfully parsed & validated {len(df_m1):,} M1 bars in {t_collect:.2f}s!")

    # Save M1 Parquet (2003 - 2026)
    out_m1_path = DIR_M1 / "XAUUSD_M1_2003_2026.parquet"
    df_m1.write_parquet(out_m1_path, compression="zstd")
    print(f"  -> Saved M1 dataset to: {out_m1_path} ({out_m1_path.stat().st_size / (1024**2):.2f} MB)")

    # HTF Resampling Matrix
    resample_specs = [
        ("M5", "5m", "Phase 2/6"),
        ("M15", "15m", "Phase 3/6"),
        ("H1", "1h", "Phase 4/6"),
        ("H4", "4h", "Phase 5/6"),
        ("D1", "1d", "Phase 6/6"),
    ]

    for tf_name, duration_str, phase_label in resample_specs:
        t_sub = time.time()
        print(f"\n[{phase_label}] Resampling M1 to {tf_name} ({duration_str} intervals)...")

        df_htf = df_m1.group_by_dynamic(
            index_column="timestamp",
            every=duration_str,
            closed="left",
            label="left"
        ).agg([
            pl.col("open").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").last().alias("close"),
            pl.col("tick_volume").sum().alias("tick_volume"),
            pl.col("mean_spread").mean().round(3).alias("mean_spread"),
            pl.col("max_spread").max().round(3).alias("max_spread"),
            pl.col("mean_spread_pts").mean().round(1).alias("mean_spread_pts"),
            pl.col("max_spread_pts").max().round(1).alias("max_spread_pts")
        ]).drop_nulls().sort("timestamp")

        out_htf_path = DIR_HTF / f"XAUUSD_{tf_name}_2003_2026.parquet"
        df_htf.write_parquet(out_htf_path, compression="zstd")
        elapsed_sub = time.time() - t_sub
        print(f"  -> Generated {len(df_htf):,} {tf_name} bars in {elapsed_sub:.2f}s -> {out_htf_path} ({out_htf_path.stat().st_size / (1024**2):.2f} MB)")

    total_duration = time.time() - t_start

    # Print Institutional Summary
    start_dt = df_m1["timestamp"].min()
    end_dt = df_m1["timestamp"].max()
    all_time_low = df_m1["low"].min()
    all_time_high = df_m1["high"].max()
    median_spread = df_m1["mean_spread"].median()
    p95_spread = df_m1["mean_spread"].quantile(0.95)

    print("\n" + "=" * 80)
    print("📊 23.3-YEAR XAUUSD INSTITUTIONAL DATASET SUMMARY")
    print("=" * 80)
    print(f"• Date Span:           {start_dt}  --->  {end_dt}")
    print(f"• Total Duration:      23 Years, 4 Months (8,534 Calendar Days)")
    print(f"• Total M1 Bars:       {len(df_m1):,} bars")
    print(f"• All-Time Price Range: ${all_time_low:.2f}  --->  ${all_time_high:.2f}")
    print(f"• Median Spread:       ${median_spread:.3f} ({median_spread*100:.1f} pts / {median_spread*10:.2f} pips)")
    print(f"• 95th Pct Spread:     ${p95_spread:.3f} ({p95_spread*100:.1f} pts / {p95_spread*10:.2f} pips)")
    print(f"• Processing Time:     {total_duration:.2f} seconds ({total_duration/60:.2f} minutes)")
    print("=" * 80)
    print("✅ All Parquet files successfully generated and ready for Naruto Shadow Clone Backtests!")


if __name__ == "__main__":
    process_dataset()
