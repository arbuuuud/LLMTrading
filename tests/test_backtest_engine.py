"""
Unit tests and institutional verification for LLMTrading Custom Backtest Engine.
Verifies order execution, slippage models, Monte Carlo stress testing, and real dataset execution.
"""

import unittest
from datetime import datetime, timedelta
import polars as pl
import numpy as np

from engine.core.types import (
    OrderDirection, ExitReason, AccountConfig, TradeRecord
)
from engine.core.strategy_base import BaseStrategy
from engine.core.event_engine import EventEngine
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from engine.metrics.performance import PerformanceCalculator
from engine.monte_carlo.simulator import MonteCarloSimulator


class DummyScalpStrategy(BaseStrategy):
    """
    A simple baseline strategy that enters a scalp buy when price drops
    and exits with a 1.00 TP or 0.50 SL.
    """
    def __init__(self, step_bars: int = 10):
        super().__init__("DummyScalp")
        self.step_bars = step_bars
        self.bar_count = 0

    def on_bar(self, bar):
        self.bar_count += 1
        # Enter every N bars if no open position
        if len(self.engine.positions) == 0 and self.bar_count % self.step_bars == 0:
            price = bar["close"]
            sl = round(price - 1.50, 2)
            tp = round(price + 2.00, 2)
            self.engine.buy(
                symbol="XAUUSD",
                volume_lots=0.1,
                stop_loss=sl,
                take_profit=tp,
                comment="ScalpTest"
            )


class TestBacktestEngine(unittest.TestCase):

    def setUp(self):
        self.config = AccountConfig(
            initial_balance=10000.0,
            commission_per_lot_round_turn=7.0,
            contract_size=100.0
        )
        self.engine = EventEngine(
            config=self.config,
            slippage_model=FixedSlippageModel(0.02)
        )

    def test_commission_and_slippage(self):
        comm = CommissionModel(7.0)
        # 0.1 lot round turn commission should be 0.1 * 7.0 = 0.70 USD
        self.assertAlmostEqual(comm.calculate_commission(0.1), 0.70, places=2)
        # 1.0 lot round turn = 7.00 USD
        self.assertAlmostEqual(comm.calculate_commission(1.0), 7.00, places=2)

        slip = FixedSlippageModel(0.05)
        self.assertEqual(slip.apply_slippage(3000.0, OrderDirection.BUY, 0.2), 3000.05)
        self.assertEqual(slip.apply_slippage(3000.0, OrderDirection.SELL, 0.2), 2999.95)

    def test_monte_carlo_simulator(self):
        now = datetime.now()
        dummy_trades = []
        # Create 50 winning trades and 30 losing trades
        for i in range(50):
            dummy_trades.append(TradeRecord(
                trade_id=f"win_{i}", symbol="XAUUSD", direction=OrderDirection.BUY,
                volume_lots=0.1, open_time=now, close_time=now, open_price=3000.0, close_price=3002.0,
                gross_pnl=20.0, commission=0.70, slippage=0.20, net_pnl=19.10, return_pct=0.191,
                stop_loss=2998.5, take_profit=3002.0, exit_reason=ExitReason.TAKE_PROFIT, duration_seconds=60
            ))
        for i in range(30):
            dummy_trades.append(TradeRecord(
                trade_id=f"loss_{i}", symbol="XAUUSD", direction=OrderDirection.BUY,
                volume_lots=0.1, open_time=now, close_time=now, open_price=3000.0, close_price=2998.5,
                gross_pnl=-15.0, commission=0.70, slippage=0.20, net_pnl=-15.90, return_pct=-0.159,
                stop_loss=2998.5, take_profit=3002.0, exit_reason=ExitReason.STOP_LOSS, duration_seconds=60
            ))

        mc = MonteCarloSimulator(num_simulations=500, ruin_drawdown_threshold_pct=25.0)
        report = mc.run(dummy_trades, initial_balance=10000.0)

        self.assertEqual(report.total_simulations, 500)
        self.assertGreater(report.median_final_equity, 10000.0)
        self.assertLess(report.p95_max_drawdown_pct, 20.0)
        self.assertEqual(report.probability_of_ruin_pct, 0.0)
        self.assertTrue(report.passes_institutional_hurdle)

    def test_engine_run_with_parquet_m1(self):
        # Load the generated XAUUSD_M1.parquet dataset
        parquet_path = "data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet"
        df = pl.read_parquet(parquet_path)
        self.assertGreater(len(df), 1000)

        strat = DummyScalpStrategy(step_bars=20)
        res = self.engine.run_bars(df, strat)

        perf = res["performance"]
        mc = res["monte_carlo"]
        trades = res["trades"]

        self.assertGreater(len(trades), 50)
        self.assertIsInstance(perf.profit_factor, float)
        self.assertIsInstance(perf.max_drawdown_pct, float)
        self.assertEqual(mc.total_simulations, 1000)
        print(f"\n[Test Result] Generated {len(trades)} trades across {len(df)} M1 bars.")
        print(f"  Win Rate: {perf.win_rate_pct}% | Profit Factor: {perf.profit_factor}")
        print(f"  Net PnL: ${perf.net_profit:,.2f} | Max DD: {perf.max_drawdown_pct}%")
        print(f"  Commissions Paid: ${perf.total_commission_paid:,.2f}")
        print(f"  Monte Carlo P95 Max DD: {mc.p95_max_drawdown_pct}% | Hurdle Passed: {mc.passes_institutional_hurdle}")


if __name__ == "__main__":
    unittest.main()
