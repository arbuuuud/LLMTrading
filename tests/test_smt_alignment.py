import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from strategies.modules.context.smt_divergence import SMTDivergenceDetector, SMTType


def main():
    print("Loading XAUUSD, XAGUSD, and DXY Parquet datasets...")
    df_gold = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")
    df_silver = pl.read_parquet("data/processed/bars/XAGUSD/M1/XAGUSD_M1.parquet")
    df_dxy = pl.read_parquet("data/processed/bars/DXY/M1/DXY_M1.parquet")

    print(f"Gold: {len(df_gold):,} bars | Silver: {len(df_silver):,} bars | DXY: {len(df_dxy):,} bars")

    # Align timestamps using fast join
    aligned = df_gold.select([
        pl.col("timestamp"),
        pl.col("open").alias("gold_open"),
        pl.col("high").alias("gold_high"),
        pl.col("low").alias("gold_low"),
        pl.col("close").alias("gold_close"),
        pl.col("mean_spread").alias("gold_spread")
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
    ).join(
        df_dxy.select([
            pl.col("timestamp"),
            pl.col("open").alias("dxy_open"),
            pl.col("high").alias("dxy_high"),
            pl.col("low").alias("dxy_low"),
            pl.col("close").alias("dxy_close")
        ]),
        on="timestamp",
        how="inner"
    ).sort("timestamp")

    print(f"Fully Synchronized 3-Asset Bars: {len(aligned):,} bars from {aligned['timestamp'].min()} to {aligned['timestamp'].max()}!\n")

    # Run SMT Divergence Scan
    detector = SMTDivergenceDetector(lookback_bars=30)
    bearish_smt_count = 0
    bullish_smt_count = 0

    sample_smts = []

    for row in aligned.iter_rows(named=True):
        g_bar = {"timestamp": row["timestamp"], "open": row["gold_open"], "high": row["gold_high"], "low": row["gold_low"], "close": row["gold_close"]}
        s_bar = {"timestamp": row["timestamp"], "open": row["silver_open"], "high": row["silver_high"], "low": row["silver_low"], "close": row["silver_close"]}
        d_bar = {"timestamp": row["timestamp"], "open": row["dxy_open"], "high": row["dxy_high"], "low": row["dxy_low"], "close": row["dxy_close"]}

        report = detector.update(g_bar, s_bar, d_bar)
        if report.is_confirmed:
            if report.smt_type == SMTType.BEARISH_SMT_SWEEP:
                bearish_smt_count += 1
            elif report.smt_type == SMTType.BULLISH_SMT_SWEEP:
                bullish_smt_count += 1

            if len(sample_smts) < 5:
                sample_smts.append((row["timestamp"], report.smt_type.value, report.gold_price, report.silver_price, report.explanation))

    print(f"Total SMT Divergence Events Detected across {len(aligned):,} bars:")
    print(f"  • Bearish SMT Divergences (Gold Sweep High, Silver Failed): {bearish_smt_count:,}")
    print(f"  • Bullish SMT Divergences (Gold Sweep Low, Silver Failed):  {bullish_smt_count:,}")
    print(f"  • Total Institutional Traps Identified: {bearish_smt_count + bullish_smt_count:,}\n")

    print("Sample SMT Divergence Events:")
    for dt, smt_type, g_p, s_p, expl in sample_smts:
        print(f"  [{dt}] {smt_type} | Gold: ${g_p:.2f}, Silver: ${s_p:.3f}")
        print(f"    -> {expl}")


if __name__ == "__main__":
    main()
