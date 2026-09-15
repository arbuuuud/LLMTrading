"""
Lifelong Learner and Post-Mortem Reflection Agent.
Audits trade records post-execution, detects anomalous drawdown drifts from Monte Carlo
expectations, and writes structured reflections to knowledge base for continuous learning.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json

from engine.core.types import TradeRecord, ExitReason
from engine.metrics.performance import PerformanceSummary
from engine.monte_carlo.simulator import MonteCarloReport


@dataclass
class PostMortemAudit:
    timestamp: str
    strategy_name: str
    total_trades_reviewed: int
    net_pnl: float
    actual_max_dd_pct: float
    expected_mc_p95_dd_pct: float
    is_drift_detected: bool
    status_recommendation: str  # "KEEP_ACTIVE", "REDUCE_SIZE", "QUARANTINE_RETIRED"
    learnings: List[str]


class LifelongLearnerAgent:
    def __init__(self, knowledge_dir: Optional[Path] = None):
        self.knowledge_dir = knowledge_dir or Path("knowledge/learnings")
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)

    def evaluate_live_run(
        self,
        strategy_name: str,
        trades: List[TradeRecord],
        perf: PerformanceSummary,
        expected_mc: MonteCarloReport
    ) -> PostMortemAudit:
        actual_dd = perf.max_drawdown_pct
        expected_dd = expected_mc.p95_max_drawdown_pct

        is_drift = actual_dd > expected_dd
        learnings = []

        if is_drift:
            rec = "QUARANTINE_RETIRED"
            learnings.append(
                f"Statistical drift detected: Actual Drawdown ({actual_dd:.2f}%) breached "
                f"Monte Carlo 95th percentile ({expected_dd:.2f}%). Capital preserved via kill-switch."
            )
        elif perf.profit_factor < 1.0:
            rec = "REDUCE_SIZE"
            learnings.append(
                f"Suboptimal performance: Profit factor ({perf.profit_factor:.2f}) dropped below 1.0. "
                f"Position size should be halved until market regime realigns."
            )
        else:
            rec = "KEEP_ACTIVE"
            learnings.append(
                f"Strategy performing in line with institutional expectations (PF: {perf.profit_factor:.2f}, "
                f"DD: {actual_dd:.2f}% vs MC P95: {expected_dd:.2f}%)."
            )

        # Audit commission burden
        if perf.total_commission_paid > abs(perf.net_profit) and perf.net_profit < 0:
            learnings.append(
                f"Commission drag warning: Paid ${perf.total_commission_paid:,.2f} in fees on {perf.total_trades} trades. "
                "Consider increasing minimum take-profit distance or tightening trade frequency."
            )

        audit = PostMortemAudit(
            timestamp=datetime.now().isoformat(),
            strategy_name=strategy_name,
            total_trades_reviewed=perf.total_trades,
            net_pnl=perf.net_profit,
            actual_max_dd_pct=actual_dd,
            expected_mc_p95_dd_pct=expected_dd,
            is_drift_detected=is_drift,
            status_recommendation=rec,
            learnings=learnings
        )

        # Save to episodic memory file
        filename = self.knowledge_dir / f"audit_{strategy_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, "w") as f:
            json.dump({
                "timestamp": audit.timestamp,
                "strategy": audit.strategy_name,
                "status_recommendation": audit.status_recommendation,
                "metrics": {
                    "total_trades": audit.total_trades_reviewed,
                    "net_pnl": audit.net_pnl,
                    "actual_max_dd": audit.actual_max_dd_pct,
                    "expected_mc_p95_dd": audit.expected_mc_p95_dd_pct,
                },
                "learnings": audit.learnings
            }, f, indent=2)

        return audit
