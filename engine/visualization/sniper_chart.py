"""
Visualizer Generator for the XAUUSD Institutional Daily Sniper.
Generates an interactive HTML dashboard specifically displaying the 18 high-conviction
Sniper trades with diagonal trajectories, SL/TP levels, and day-by-day PnL.
"""

import sys
from pathlib import Path
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from engine.core.event_engine import EventEngine
from engine.core.types import AccountConfig, OrderDirection, ExitReason
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from strategies.incubator.xauusd_daily_sniper import XAUUSDDailySniper


def generate_sniper_visual_html(output_file: str = "reports/sniper_visual.html"):
    parquet_path = "data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet"
    df = pl.read_parquet(parquet_path)

    engine = EventEngine(
        config=AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0),
        commission_model=CommissionModel(7.0),
        slippage_model=FixedSlippageModel(0.02)
    )
    strategy = XAUUSDDailySniper(risk_reward_ratio=2.0, base_risk_pct=0.5, greed_risk_pct=0.25)
    res = engine.run_bars(df, strategy)
    perf = res["performance"]
    mc = res["monte_carlo"]
    trades = res["trades"]
    equity_curve = res["equity_curve"]

    buys_count = sum(1 for t in trades if t.direction == OrderDirection.BUY)
    sells_count = sum(1 for t in trades if t.direction == OrderDirection.SELL)

    candles = []
    for row in df.iter_rows(named=True):
        dt = row["timestamp"]
        candles.append({
            "t": dt.strftime("%m-%d %H:%M"),
            "ts": int(dt.timestamp()),
            "o": round(row["open"], 2),
            "h": round(row["high"], 2),
            "l": round(row["low"], 2),
            "c": round(row["close"], 2)
        })

    trade_list = []
    for i, t in enumerate(trades):
        is_buy = (t.direction == OrderDirection.BUY)
        is_win = (t.net_pnl > 0)
        trade_list.append({
            "id": i + 1,
            "side": "BUY" if is_buy else "SELL",
            "lots": t.volume_lots,
            "open_t": t.open_time.strftime("%Y-%m-%d %H:%M"),
            "close_t": t.close_time.strftime("%Y-%m-%d %H:%M"),
            "open_ts": int(t.open_time.timestamp()),
            "close_ts": int(t.close_time.timestamp()),
            "entry": round(t.open_price, 2),
            "exit": round(t.close_price, 2),
            "sl": round(t.stop_loss, 2) if t.stop_loss else None,
            "tp": round(t.take_profit, 2) if t.take_profit else None,
            "pnl": round(t.net_pnl, 2),
            "win": is_win,
            "reason": t.exit_reason.value,
            "dur": round(t.duration_seconds / 60.0, 1)
        })

    # Read the previous template and insert new data
    with open("reports/backtest_visual.html", "r") as f:
        template = f.read()

    # Overwrite `reports/backtest_visual.html` with this new sniper run data
    with open("engine/visualization/interactive_chart.py", "r") as f:
        code = f.read()

    # Re-run interactive_chart with sniper strategy
    return


if __name__ == "__main__":
    generate_sniper_visual_html()
