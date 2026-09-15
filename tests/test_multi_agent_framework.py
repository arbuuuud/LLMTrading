"""
Integration tests for the Multi-Agent Framework.
Verifies Market Regime Agent, Risk Gatekeeper Agent, Strategy Miner,
Institutional Auditor, and Lifelong Learning Memory Agent.
"""

import unittest
import sys
from pathlib import Path
from datetime import datetime, date

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from engine.core.types import OrderDirection
from agents.market_regime.detector import MarketRegimeDetector, RegimeType
from agents.risk_manager.gatekeeper import RiskGatekeeperAgent
from agents.validator.auditor import StrategyAuditorAgent, VerdictStatus
from agents.researcher.strategy_miner import StrategyMinerAgent
from agents.lifelong_learner.memory_agent import LifelongLearnerAgent
from agents.orchestrator import MultiAgentOrchestrator
from strategies.incubator.xauusd_trend_pullback_scalper import XAUUSDTrendPullbackScalper


class TestMultiAgentFramework(unittest.TestCase):

    def setUp(self):
        self.orchestrator = MultiAgentOrchestrator()
        self.parquet_path = "data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet"
        self.df = pl.read_parquet(self.parquet_path)

    def test_market_regime_detector(self):
        detector = MarketRegimeDetector(lookback_bars=20, atr_period=10)
        # Feed 30 bars with increasing prices to simulate an uptrend
        for i in range(30):
            bar = {
                "timestamp": datetime(2025, 5, 27, 8, i),
                "open": 3300.0 + i * 0.5,
                "high": 3301.0 + i * 0.5,
                "low": 3299.8 + i * 0.5,
                "close": 3300.8 + i * 0.5,
                "mean_spread": 0.18
            }
            report = detector.update(bar)

        self.assertGreater(report.trend_strength, 0.2)
        self.assertEqual(report.recommended_strategy_family, "TREND_PULLBACK")
        self.assertTrue(report.is_spread_normal)

    def test_risk_gatekeeper(self):
        gatekeeper = RiskGatekeeperAgent(
            risk_per_trade_pct=1.0,
            max_daily_loss_pct=2.0,
            max_spread_dollars=0.25,
            contract_size=100.0
        )
        now = datetime.now()
        gatekeeper.on_new_bar(now, current_equity=10000.0)

        # 1. Normal valid order: entry 3300, SL 3298 (Risk $2.00)
        # Risk = 1% of $10,000 = $100.
        # Lots = $100 / ($2.00 * 100) = 0.50 lots.
        approval = gatekeeper.evaluate_order(
            symbol="XAUUSD",
            direction=OrderDirection.BUY,
            entry_price=3300.0,
            stop_loss=3298.0,
            current_spread=0.18,
            account_equity=10000.0,
            num_open_positions=0
        )
        self.assertTrue(approval.approved)
        self.assertEqual(approval.recommended_lots, 0.50)

        # 2. Spread spike veto: spread $0.35 > max $0.25
        veto_spread = gatekeeper.evaluate_order(
            symbol="XAUUSD",
            direction=OrderDirection.BUY,
            entry_price=3300.0,
            stop_loss=3298.0,
            current_spread=0.35,
            account_equity=10000.0,
            num_open_positions=0
        )
        self.assertFalse(veto_spread.approved)
        self.assertIn("SPREAD_GUARD", veto_spread.reason)

        # 3. Circuit breaker trip on consecutive losses
        for _ in range(4):
            gatekeeper.on_trade_closed(net_pnl=-50.0)
        self.assertTrue(gatekeeper.circuit_breaker_tripped)

        veto_cb = gatekeeper.evaluate_order(
            symbol="XAUUSD",
            direction=OrderDirection.BUY,
            entry_price=3300.0,
            stop_loss=3298.0,
            current_spread=0.18,
            account_equity=9800.0,
            num_open_positions=0
        )
        self.assertFalse(veto_cb.approved)
        self.assertIn("CIRCUIT_BREAKER", veto_cb.reason)

    def test_miner_and_auditor(self):
        # Test mining 6 fast candidate combinations on real M1 bars
        auditor = StrategyAuditorAgent()
        miner = StrategyMinerAgent(auditor)
        results = miner.mine_trend_scalper(
            self.df,
            rr_candidates=[1.8, 2.0, 2.5],
            max_bars_candidates=[25],
            sl_buffer_candidates=[0.35, 0.50]
        )
        self.assertEqual(len(results), 6)
        top = results[0]
        print(f"\n[Test Result] Top Mined Strategy: {top['params']}")
        print(f"  Verdict: {top['verdict']} | Score: {top['score']}/100")
        print(f"  PF: {top['profit_factor']} | Net PnL: ${top['net_pnl']} | Max DD: {top['max_dd']}%")
        self.assertGreater(top["profit_factor"], 1.0)

    def test_lifelong_learner_post_mortem(self):
        learner = LifelongLearnerAgent()
        strat = XAUUSDTrendPullbackScalper(risk_reward_ratio=2.0, max_bars_hold=25)
        auditor = StrategyAuditorAgent()
        verdict = auditor.audit(strat, self.df)

        audit = learner.evaluate_live_run(
            strategy_name="XAUUSD_Trend_Pullback_Scalper",
            trades=[],
            perf=verdict.performance,
            expected_mc=verdict.monte_carlo
        )
        self.assertEqual(audit.status_recommendation, "KEEP_ACTIVE")
        self.assertFalse(audit.is_drift_detected)
        self.assertGreater(len(audit.learnings), 0)
        print(f"\n[Test Result] Post-Mortem Status: {audit.status_recommendation}")
        print(f"  Learnings: {audit.learnings[0]}")


if __name__ == "__main__":
    unittest.main()
