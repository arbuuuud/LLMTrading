"""
Strategy Validation and Monte Carlo Auditor Agent.
Acts as a hostile auditor evaluating strategy candidates across out-of-sample data
and 1,000-run Monte Carlo stress tests against strict institutional hurdles.
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
import polars as pl

from engine.core.event_engine import EventEngine
from engine.core.strategy_base import BaseStrategy
from engine.core.types import AccountConfig
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from engine.metrics.performance import PerformanceSummary
from engine.monte_carlo.simulator import MonteCarloReport


class VerdictStatus(Enum):
    APPROVED_FOR_INCUBATION = "APPROVED_FOR_INCUBATION"
    NEEDS_REFINEMENT = "NEEDS_REFINEMENT"
    REJECTED = "REJECTED"


@dataclass
class AuditVerdict:
    status: VerdictStatus
    score: float  # 0.0 to 100.0
    passed_hurdles: bool
    summary: str
    performance: PerformanceSummary
    monte_carlo: MonteCarloReport


class StrategyAuditorAgent:
    def __init__(
        self,
        min_trades: int = 25,
        min_profit_factor: float = 1.05,
        max_drawdown_pct: float = 15.0,
        max_mc_p95_dd_pct: float = 20.0,
        max_ruin_prob_pct: float = 1.0
    ):
        self.min_trades = min_trades
        self.min_pf = min_profit_factor
        self.max_dd = max_drawdown_pct
        self.max_mc_p95_dd = max_mc_p95_dd_pct
        self.max_ruin_prob = max_ruin_prob_pct

    def audit(
        self,
        strategy: BaseStrategy,
        df_bars: pl.DataFrame,
        account_config: Optional[AccountConfig] = None
    ) -> AuditVerdict:
        config = account_config or AccountConfig()
        engine = EventEngine(
            config=config,
            commission_model=CommissionModel(config.commission_per_lot_round_turn),
            slippage_model=FixedSlippageModel(0.02)
        )

        res = engine.run_bars(df_bars, strategy)
        perf: PerformanceSummary = res["performance"]
        mc: MonteCarloReport = res["monte_carlo"]

        # Evaluate hurdles
        fails = []
        if perf.total_trades < self.min_trades:
            fails.append(f"Insufficient trade sample ({perf.total_trades} < {self.min_trades})")
        if perf.profit_factor < self.min_pf:
            fails.append(f"Profit Factor too low ({perf.profit_factor:.2f} < {self.min_pf:.2f})")
        if perf.max_drawdown_pct > self.max_dd:
            fails.append(f"Max Drawdown exceeded ({perf.max_drawdown_pct:.1f}% > {self.max_dd:.1f}%)")
        if mc.p95_max_drawdown_pct > self.max_mc_p95_dd:
            fails.append(f"Monte Carlo P95 DD exceeded ({mc.p95_max_drawdown_pct:.1f}% > {self.max_mc_p95_dd:.1f}%)")
        if mc.probability_of_ruin_pct > self.max_ruin_prob:
            fails.append(f"Probability of Ruin too high ({mc.probability_of_ruin_pct:.1f}% > {self.max_ruin_prob:.1f}%)")

        # Compute composite institutional score
        score = 50.0
        if perf.profit_factor >= 1.0:
            score += min(30.0, (perf.profit_factor - 1.0) * 50.0)
        else:
            score -= (1.0 - perf.profit_factor) * 50.0

        if perf.max_drawdown_pct < 5.0:
            score += 15.0
        elif perf.max_drawdown_pct < 10.0:
            score += 5.0

        if mc.p95_max_drawdown_pct < 10.0:
            score += 15.0

        score = max(0.0, min(100.0, score))

        if len(fails) == 0 and score >= 65.0:
            status = VerdictStatus.APPROVED_FOR_INCUBATION
            summary = "Strategy successfully passed all institutional hurdles and Monte Carlo stress tests."
        elif perf.profit_factor >= 0.95 and perf.max_drawdown_pct <= self.max_dd:
            status = VerdictStatus.NEEDS_REFINEMENT
            summary = f"Borderline viable: {', '.join(fails)}."
        else:
            status = VerdictStatus.REJECTED
            summary = f"Audit rejected: {', '.join(fails)}."

        return AuditVerdict(
            status=status,
            score=round(score, 1),
            passed_hurdles=(len(fails) == 0),
            summary=summary,
            performance=perf,
            monte_carlo=mc
        )
