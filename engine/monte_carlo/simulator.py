"""
Monte Carlo Permutation Stress Tester (Lesson 8 Institutional Protocol).
Runs 1,000+ randomized bootstrap simulations on trade sequences to determine
true statistical robustness, risk of ruin, and worst-case 95% drawdown confidence intervals.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import numpy as np

# Avoid circular imports with engine.core
TradeRecord = Any


@dataclass
class MonteCarloReport:
    total_simulations: int
    trades_per_simulation: int
    median_max_drawdown_pct: float
    p90_max_drawdown_pct: float
    p95_max_drawdown_pct: float
    p99_max_drawdown_pct: float
    worst_drawdown_pct: float
    probability_of_ruin_pct: float  # Chance of hitting account ruin threshold (e.g. >30% DD)
    median_final_equity: float
    p05_final_equity: float         # 5th percentile worst-case equity
    p95_final_equity: float         # 95th percentile optimistic equity
    passes_institutional_hurdle: bool


class MonteCarloSimulator:
    def __init__(
        self,
        num_simulations: int = 1000,
        ruin_drawdown_threshold_pct: float = 30.0,
        institutional_max_dd_hurdle: float = 20.0,
        seed: int = 42
    ):
        self.num_simulations = num_simulations
        self.ruin_drawdown_threshold_pct = ruin_drawdown_threshold_pct
        self.institutional_max_dd_hurdle = institutional_max_dd_hurdle
        self.rng = np.random.default_rng(seed)

    def run(self, trades: List[TradeRecord], initial_balance: float = 10000.0) -> MonteCarloReport:
        if len(trades) < 10:
            # Not enough trades for statistical significance
            return MonteCarloReport(
                total_simulations=self.num_simulations,
                trades_per_simulation=len(trades),
                median_max_drawdown_pct=0.0,
                p90_max_drawdown_pct=0.0,
                p95_max_drawdown_pct=0.0,
                p99_max_drawdown_pct=0.0,
                worst_drawdown_pct=0.0,
                probability_of_ruin_pct=0.0,
                median_final_equity=initial_balance,
                p05_final_equity=initial_balance,
                p95_final_equity=initial_balance,
                passes_institutional_hurdle=False
            )

        pnls = np.array([t.net_pnl for t in trades], dtype=np.float64)
        n_trades = len(pnls)

        sim_max_drawdowns = []
        sim_final_equities = []
        ruin_count = 0

        for _ in range(self.num_simulations):
            # Bootstrap resample with replacement
            sampled_pnls = self.rng.choice(pnls, size=n_trades, replace=True)
            equity_curve = initial_balance + np.cumsum(sampled_pnls)
            equity_curve = np.insert(equity_curve, 0, initial_balance)

            running_max = np.maximum.accumulate(equity_curve)
            # Avoid division by zero
            drawdowns = np.where(running_max > 0, (running_max - equity_curve) / running_max * 100.0, 100.0)
            max_dd = float(np.max(drawdowns))
            final_eq = float(equity_curve[-1])

            sim_max_drawdowns.append(max_dd)
            sim_final_equities.append(final_eq)

            if max_dd >= self.ruin_drawdown_threshold_pct:
                ruin_count += 1

        sim_max_drawdowns = np.array(sim_max_drawdowns)
        sim_final_equities = np.array(sim_final_equities)

        median_dd = float(np.median(sim_max_drawdowns))
        p90_dd = float(np.percentile(sim_max_drawdowns, 90))
        p95_dd = float(np.percentile(sim_max_drawdowns, 95))
        p99_dd = float(np.percentile(sim_max_drawdowns, 99))
        worst_dd = float(np.max(sim_max_drawdowns))

        prob_ruin = (ruin_count / self.num_simulations) * 100.0

        median_eq = float(np.median(sim_final_equities))
        p05_eq = float(np.percentile(sim_final_equities, 5))
        p95_eq = float(np.percentile(sim_final_equities, 95))

        # Institutional Hurdle: 95% worst-case DD must be less than hurdle (e.g. 20%)
        # AND probability of ruin < 1%
        passes = (p95_dd <= self.institutional_max_dd_hurdle) and (prob_ruin < 1.0) and (p05_eq > initial_balance * 0.85)

        return MonteCarloReport(
            total_simulations=self.num_simulations,
            trades_per_simulation=n_trades,
            median_max_drawdown_pct=round(median_dd, 2),
            p90_max_drawdown_pct=round(p90_dd, 2),
            p95_max_drawdown_pct=round(p95_dd, 2),
            p99_max_drawdown_pct=round(p99_dd, 2),
            worst_drawdown_pct=round(worst_dd, 2),
            probability_of_ruin_pct=round(prob_ruin, 2),
            median_final_equity=round(median_eq, 2),
            p05_final_equity=round(p05_eq, 2),
            p95_final_equity=round(p95_eq, 2),
            passes_institutional_hurdle=passes
        )
