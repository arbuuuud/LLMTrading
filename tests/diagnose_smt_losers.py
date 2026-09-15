import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from engine.core.event_engine import EventEngine
from engine.core.types import AccountConfig, ExitReason
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from strategies.incubator.xauusd_smt_asia_sweep import XAUUSDSMTSweepSniper


def main():
    df_gold = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")
    df_silver = pl.read_parquet("data/processed/bars/XAGUSD/M1/XAGUSD_M1.parquet")

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
    ).sort("timestamp")

    engine = EventEngine(config=AccountConfig(), commission_model=CommissionModel(7.0), slippage_model=FixedSlippageModel(0.02))
    strat = XAUUSDSMTSweepSniper()
    engine.reset()
    engine.current_strategy = strat
    strat.set_engine(engine)
    strat.on_init()

    for row in aligned.iter_rows(named=True):
        engine.current_time = row["timestamp"]
        spread = row.get("gold_spread", 0.20)
        engine.current_bid = row["gold_close"]
        engine.current_ask = round(engine.current_bid + spread, 3)
        engine.current_spread = spread

        engine._check_daily_circuit_breaker(engine.current_time)

        gold_bar = {"timestamp": row["timestamp"], "open": row["gold_open"], "high": row["gold_high"], "low": row["gold_low"], "close": row["gold_close"], "mean_spread": spread}
        engine._update_positions_on_bar(gold_bar)

        silver_bar = {"timestamp": row["timestamp"], "open": row["silver_open"], "high": row["silver_high"], "low": row["silver_low"], "close": row["silver_close"]}
        strat.on_bar_intermarket(gold_bar, silver_bar, None)

    for pos_id in list(engine.positions.keys()):
        engine._close_position_internal(pos_id, ExitReason.END_OF_DATA)

    losers = [t for t in engine.closed_trades if t.net_pnl < 0]
    print(f"Total Losers: {len(losers)}")
    for t in losers[:10]:
        print(f"Trade #{t.trade_id} [{t.direction.value}] {t.open_time} -> {t.close_time} | Entry: {t.open_price} SL: {t.stop_loss} Exit: {t.close_price} PnL: ${t.net_pnl} Reason: {t.exit_reason.value} Dur: {t.duration_seconds/60:.0f}m")


if __name__ == "__main__":
    main()
