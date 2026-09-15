"""
Quant Researcher and Strategy Mining Agent.
Automates hypothesis generation and parametric exploration across modular lego bricks,
ranking candidates to find robust, non-overfitted strategies.
"""

from typing import List, Dict, Any, Optional
import itertools
import polars as pl

from engine.core.types import AccountConfig
from strategies.incubator.xauusd_trend_pullback_scalper import XAUUSDTrendPullbackScalper
from agents.validator.auditor import StrategyAuditorAgent, AuditVerdict, VerdictStatus


class StrategyMinerAgent:
    def __init__(self, auditor: Optional[StrategyAuditorAgent] = None):
        self.auditor = auditor or StrategyAuditorAgent()

    def mine_trend_scalper(
        self,
        df_bars: pl.DataFrame,
        rr_candidates: Optional[List[float]] = None,
        max_bars_candidates: Optional[List[int]] = None,
        sl_buffer_candidates: Optional[List[float]] = None
    ) -> List[Dict[str, Any]]:
        rrs = rr_candidates or [1.5, 1.8, 2.0, 2.2, 2.5]
        holds = max_bars_candidates or [20, 25, 30]
        buffers = sl_buffer_candidates or [0.25, 0.35, 0.50]

        combinations = list(itertools.product(rrs, holds, buffers))
        print(f"[Researcher] Mining {len(combinations)} parameter combinations...")

        results = []
        for rr, max_hold, buf in combinations:
            strat = XAUUSDTrendPullbackScalper(
                risk_reward_ratio=rr,
                max_bars_hold=max_hold,
                sl_buffer_dollars=buf
            )
            verdict: AuditVerdict = self.auditor.audit(strat, df_bars)

            results.append({
                "params": {"rr": rr, "max_hold": max_hold, "sl_buffer": buf},
                "verdict": verdict.status.value,
                "score": verdict.score,
                "trades": verdict.performance.total_trades,
                "win_rate": verdict.performance.win_rate_pct,
                "profit_factor": verdict.performance.profit_factor,
                "net_pnl": verdict.performance.net_profit,
                "max_dd": verdict.performance.max_drawdown_pct,
                "mc_p95_dd": verdict.monte_carlo.p95_max_drawdown_pct
            })

        # Sort by institutional composite score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        return results
