"""
Dual-Horizon Portfolio Simulation:
Combines Priority 1 (M1 Scalper) + Priority 2 (M15 Intraday SMC) running concurrently
under a unified MonthlyRatchetGovernor on the 10.5-month dataset.
"""

import sys
import time
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from engine.core.event_engine import EventEngine
from engine.core.types import AccountConfig, ExitReason
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from engine.metrics.performance import PerformanceCalculator
from strategies.incubator.strat_3_anchored_vwap import SessionAnchoredVWAPStrategy
from strategies.incubator.strat_6_intraday_smc import IntradaySMCStrategy


def test_dual_portfolio():
    print("\n" + "="*85)
    print("🚀 RUNNING DUAL-HORIZON PORTFOLIO (M1 SCALPER + M15 INTRADAY SMC)")
    print("="*85)

    m1_path = "data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet"
    print(f"Loading full M1 dataset from {m1_path}...")
    df_m1 = pl.read_parquet(m1_path)

    config = AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0)
    engine = EventEngine(
        config=config,
        commission_model=CommissionModel(7.0),
        slippage_model=FixedSlippageModel(0.02)
    )

    scalper = SessionAnchoredVWAPStrategy(
        band_multiplier=1.8,
        sl_buffer_dollars=0.50,
        risk_reward_ratio=2.0,
        base_risk_pct=0.5,
        greed_risk_pct=0.25,
        max_bars_hold=60
    )
    scalper.set_engine(engine)
    scalper.on_init()

    intraday = IntradaySMCStrategy(
        base_risk_pct=0.50,
        tp1_r=1.5,
        tp2_r=4.0,
        sl_buffer_dollars=1.50,
        poi_tolerance_dollars=1.00
    )
    intraday.set_engine(engine)
    intraday.on_init()

    # M15 bar aggregator for Intraday strategy while streaming M1 bars
    current_m15 = None
    t0 = time.time()

    for bar in df_m1.iter_rows(named=True):
        engine.current_time = bar["timestamp"]
        spread = bar.get("mean_spread", 0.20)
        engine.current_bid = bar["close"]
        engine.current_ask = round(engine.current_bid + spread, 3)
        engine.current_spread = spread

        engine._check_daily_circuit_breaker(engine.current_time)
        engine._update_positions_on_bar(bar)

        # 1. Feed Scalper M1 bar
        scalper.on_bar(bar)

        # 2. Aggregate and feed Intraday M15 bar on completion
        dt = bar["timestamp"]
        m15_minute = (dt.minute // 15) * 15
        m15_time = dt.replace(minute=m15_minute, second=0, microsecond=0)

        if current_m15 is None or current_m15["timestamp"] != m15_time:
            if current_m15 is not None:
                intraday.on_bar(current_m15)

            current_m15 = {
                "timestamp": m15_time,
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "mean_spread": spread,
                "tick_volume": bar.get("tick_volume", 1)
            }
        else:
            current_m15["high"] = max(current_m15["high"], bar["high"])
            current_m15["low"] = min(current_m15["low"], bar["low"])
            current_m15["close"] = bar["close"]
            current_m15["tick_volume"] += bar.get("tick_volume", 1)

        engine.equity_curve.append({
            "timestamp": engine.current_time,
            "equity": round(engine.equity, 2),
            "balance": round(engine.balance, 2)
        })

    if current_m15 is not None:
        intraday.on_bar(current_m15)

    for pos_id in list(engine.positions.keys()):
        engine._close_position_internal(pos_id, ExitReason.END_OF_DATA)

    scalper.on_finish()
    intraday.on_finish()
    elapsed = time.time() - t0

    perf = PerformanceCalculator.calculate(engine.closed_trades, engine.equity_curve, config.initial_balance)

    # Separate trade attribution
    scalp_trades = [t for t in engine.closed_trades if "VWAP" in (t.comment or "") or "VWAP" in (t.tag or "")]
    intra_trades = [t for t in engine.closed_trades if "Intra" in (t.comment or "")]

    scalp_pnl = sum(t.net_pnl for t in scalp_trades)
    intra_pnl = sum(t.net_pnl for t in intra_trades)

    monthly_pnl = defaultdict(float)
    for tr in engine.closed_trades:
        monthly_pnl[tr.open_time.strftime("%Y-%m")] += tr.net_pnl

    pos_m = sum(1 for v in monthly_pnl.values() if v > 0)
    tot_m = len(monthly_pnl) or 1

    print("\n" + "="*85)
    print("🏆 DUAL-HORIZON PORTFOLIO PERFORMANCE (10.5 MONTHS XAUUSD)")
    print("="*85)
    print(f"⏱ Time: {elapsed:.2f}s")
    print(f"📊 Total Combined Trades: {perf.total_trades}")
    print(f"   -> Scalper M1 Trades: {len(scalp_trades)} (Net: ${scalp_pnl:+,.2f})")
    print(f"   -> Intraday M15 Trades: {len(intra_trades)} (Net: ${intra_pnl:+,.2f})")
    print(f"💰 Combined Net Profit: ${perf.net_profit:+,.2f}")
    print(f"📈 Combined Profit Factor: {perf.profit_factor:.2f}")
    print(f"🛡 Combined Max Drawdown: {perf.max_drawdown_pct:.1f}%")
    print(f"🎯 Win Rate: {perf.win_rate_pct:.1f}%")
    print(f"⚖️ Payoff Ratio: {perf.win_loss_ratio:.2f}x")
    print(f"📆 Profitable Months: {pos_m} / {tot_m} ({pos_m/tot_m*100:.0f}%)")
    print("="*85)


if __name__ == "__main__":
    test_dual_portfolio()
