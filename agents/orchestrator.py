"""
Multi-Agent Orchestrator and Supervisor.
Coordinates Market Regime intelligence, Quant Research mining, Institutional Auditing,
Risk Gatekeeper veto enforcement, and Lifelong Learning reflection.
"""

from typing import Dict, Any, Optional
import polars as pl

from agents.market_regime.detector import MarketRegimeDetector, MarketRegimeReport
from agents.risk_manager.gatekeeper import RiskGatekeeperAgent, TradeApproval
from agents.validator.auditor import StrategyAuditorAgent, AuditVerdict
from agents.researcher.strategy_miner import StrategyMinerAgent
from agents.lifelong_learner.memory_agent import LifelongLearnerAgent, PostMortemAudit
from engine.core.types import OrderDirection


class MultiAgentOrchestrator:
    def __init__(
        self,
        regime_detector: Optional[MarketRegimeDetector] = None,
        risk_gatekeeper: Optional[RiskGatekeeperAgent] = None,
        auditor: Optional[StrategyAuditorAgent] = None,
        miner: Optional[StrategyMinerAgent] = None,
        learner: Optional[LifelongLearnerAgent] = None
    ):
        self.regime_detector = regime_detector or MarketRegimeDetector()
        self.risk_gatekeeper = risk_gatekeeper or RiskGatekeeperAgent()
        self.auditor = auditor or StrategyAuditorAgent()
        self.miner = miner or StrategyMinerAgent(self.auditor)
        self.learner = learner or LifelongLearnerAgent()

    def analyze_market(self, bar: Dict[str, Any]) -> MarketRegimeReport:
        """Step 1: Get market regime report from Market Regime Agent"""
        return self.regime_detector.update(bar)

    def screen_and_validate(self, df_bars: pl.DataFrame) -> Dict[str, Any]:
        """Step 2: Mine strategies and select the top institutional performer"""
        mined_results = self.miner.mine_trend_scalper(df_bars)
        top_candidate = mined_results[0] if mined_results else None
        return {
            "total_candidates_evaluated": len(mined_results),
            "top_candidate": top_candidate,
            "all_ranked_candidates": mined_results[:5]
        }

    def evaluate_trade_risk(
        self,
        symbol: str,
        direction: OrderDirection,
        entry_price: float,
        stop_loss: float,
        current_spread: float,
        account_equity: float,
        num_open_positions: int
    ) -> TradeApproval:
        """Step 3: Submit order to Risk Gatekeeper for approval/veto and dynamic sizing"""
        return self.risk_gatekeeper.evaluate_order(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            current_spread=current_spread,
            account_equity=account_equity,
            num_open_positions=num_open_positions
        )

    def post_mortem_review(
        self,
        strategy_name: str,
        trades: list,
        perf: Any,
        expected_mc: Any
    ) -> PostMortemAudit:
        """Step 4: Audit completed execution run and store learnings in long-life memory"""
        return self.learner.evaluate_live_run(
            strategy_name=strategy_name,
            trades=trades,
            perf=perf,
            expected_mc=expected_mc
        )
