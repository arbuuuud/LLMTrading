"""
Empirical Audit of Fibonacci Retracement (OTE Golden Pocket) & Extension Targets (1.272 / 1.618)
on 10.5 Months of Continuous XAUUSD M15 Data.
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
from engine.core.types import AccountConfig, ExitReason, OrderDirection
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from engine.metrics.performance import PerformanceCalculator
from strategies.incubator.strat_6_intraday_smc import IntradaySMCStrategy
from strategies.modules.setups.fibonacci_confluence import FibonacciCalculator, FiboSetup


class FiboIntradayStrategy(IntradaySMCStrategy):
    def __init__(
        self,
        use_fibo_entry_filter: bool = False,
        target_mode: str = "FIXED_3R",  # "FIXED_3R", "FIBO_1272", "FIBO_1618"
    ):
        super().__init__()
        self.use_fibo_entry_filter = use_fibo_entry_filter
        self.target_mode = target_mode
        self.latest_fibo: Optional[FiboSetup] = None

    def on_init(self):
        super().on_init()
        self.latest_fibo = None

    def _on_h1_bar_close(self, h1_bar):
        super()._on_h1_bar_close(h1_bar)

        # Calculate H1 Swing Low and Swing High over recent 20 bars
        if len(self.h1_history) >= 10:
            recent_highs = [b["high"] for b in self.h1_history[-20:]]
            recent_lows = [b["low"] for b in self.h1_history[-20:]]
            sh = max(recent_highs)
            sl = min(recent_lows)

            if self.h1_bias == 1:
                self.latest_fibo = FibonacciCalculator.compute_bullish_fibo(swing_low=sl, swing_high=sh)
            elif self.h1_bias == -1:
                self.latest_fibo = FibonacciCalculator.compute_bearish_fibo(swing_high=sh, swing_low=sl)

    def on_bar(self, bar):
        dt = bar["timestamp"]
        d = dt.date()
        t = dt.time()

        gh = bar["high"]
        gl = bar["low"]
        gc = bar["close"]
        go = bar["open"]
        spread = bar.get("mean_spread", 0.25)

        self._update_h1_bar(bar)

        if self.current_date != d:
            self.current_date = d
            self.traded_today = 0

        self.governor.on_new_bar(dt, self.engine.equity)

        if len(self.engine.positions) > 0:
            if t.hour >= 21 and t.minute >= 30:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
            return

        is_window = self.start_time <= (t.hour, t.minute) <= self.end_time
        if not is_window or self.traded_today >= 1 or self.h1_bias == 0:
            return

        rng = gh - gl
        if rng < 0.60:
            return

        upper_wick = gh - max(go, gc)
        lower_wick = min(go, gc) - gl

        # =====================================================================
        # BUY SETUP
        # =====================================================================
        if self.h1_bias == 1 and gc > go and (lower_wick / rng) >= 0.35:
            # Fibo OTE Filter: Must be in Golden Pocket (61.8% - 78.6%)
            if self.use_fibo_entry_filter and self.latest_fibo:
                if not FibonacciCalculator.is_in_golden_pocket(gl, self.latest_fibo, buffer=0.50):
                    return

            valid_pois = [p for p in self.active_pois if p.poi_type in ("BULLISH_OB", "BULLISH_IFVG") and (p.bottom - self.poi_tolerance) <= gl <= (p.top + self.poi_tolerance)]
            if valid_pois:
                best = valid_pois[-1]
                stop = round(best.bottom - self.sl_buffer, 2)
                risk = gc - stop

                if 1.50 <= risk <= 8.00:
                    approval = self.governor.evaluate_entry(gc, stop, spread, 0.35, len(self.engine.positions))
                    if approval.approved:
                        # Determine TP
                        if self.target_mode == "FIBO_1272" and self.latest_fibo:
                            tp = self.latest_fibo.ext_1272
                        elif self.target_mode == "FIBO_1618" and self.latest_fibo:
                            tp = self.latest_fibo.ext_1618
                        else:
                            tp = round(gc + risk * 3.0, 2)

                        # Sanity check TP must be at least 1.5R
                        if tp <= gc or (tp - gc) < risk * 1.2:
                            tp = round(gc + risk * 3.0, 2)

                        pid = self.engine.buy("XAUUSD", approval.lots, stop, tp, comment=f"Buy_{self.target_mode}")
                        if pid:
                            self.traded_today += 1
                            return

        # =====================================================================
        # SELL SETUP
        # =====================================================================
        if self.h1_bias == -1 and gc < go and (upper_wick / rng) >= 0.35:
            # Fibo OTE Filter: Must be in Golden Pocket (61.8% - 78.6%)
            if self.use_fibo_entry_filter and self.latest_fibo:
                if not FibonacciCalculator.is_in_golden_pocket(gh, self.latest_fibo, buffer=0.50):
                    return

            valid_pois = [p for p in self.active_pois if p.poi_type in ("BEARISH_OB", "BEARISH_IFVG") and (p.bottom - self.poi_tolerance) <= gh <= (p.top + self.poi_tolerance)]
            if valid_pois:
                best = valid_pois[-1]
                stop = round(best.top + self.sl_buffer, 2)
                risk = stop - gc

                if 1.50 <= risk <= 8.00:
                    approval = self.governor.evaluate_entry(gc, stop, spread, 0.35, len(self.engine.positions))
                    if approval.approved:
                        if self.target_mode == "FIBO_1272" and self.latest_fibo:
                            tp = self.latest_fibo.ext_1272
                        elif self.target_mode == "FIBO_1618" and self.latest_fibo:
                            tp = self.latest_fibo.ext_1618
                        else:
                            tp = round(gc - risk * 3.0, 2)

                        if tp >= gc or (gc - tp) < risk * 1.2:
                            tp = round(gc - risk * 3.0, 2)

                        pid = self.engine.sell("XAUUSD", approval.lots, stop, tp, comment=f"Sell_{self.target_mode}")
                        if pid:
                            self.traded_today += 1
                            return


def main():
    df_m15 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_M15.parquet")

    scenarios = [
        ("1. Baseline: POI Only + Fixed 3.0R TP", False, "FIXED_3R"),
        ("2. Fibo Extension 1.272 TP (No Entry Filter)", False, "FIBO_1272"),
        ("3. Fibo Extension 1.618 Golden TP (No Entry Filter)", False, "FIBO_1618"),
        ("4. Fibo OTE Golden Pocket Filter (61.8-78.6%) + Fixed 3.0R TP", True, "FIXED_3R"),
        ("5. Full Elliott-Fibo Confluence: OTE Filter + 1.618 Extension TP", True, "FIBO_1618"),
    ]

    print(f"\n{'='*98}")
    print("🔬 AUDIT FIBONACCI RETRACEMENT (GOLDEN POCKET) & EXTENSIONS (1.272 / 1.618)")
    print(f"{'='*98}\n")

    results = []
    for label, use_filter, tp_mode in scenarios:
        t0 = time.time()
        strat = FiboIntradayStrategy(use_fibo_entry_filter=use_filter, target_mode=tp_mode)
        config = AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0)
        engine = EventEngine(config=config, commission_model=CommissionModel(7.0), slippage_model=FixedSlippageModel(0.02))
        engine.reset()
        engine.current_strategy = strat
        strat.set_engine(engine)
        strat.on_init()

        for bar in df_m15.iter_rows(named=True):
            engine.current_time = bar["timestamp"]
            spread = bar.get("mean_spread", 0.25)
            engine.current_bid = bar["close"]
            engine.current_ask = round(engine.current_bid + spread, 3)
            engine.current_spread = spread
            engine._check_daily_circuit_breaker(engine.current_time)
            engine._update_positions_on_bar(bar)
            strat.on_bar(bar)
            engine.equity_curve.append({"timestamp": engine.current_time, "equity": round(engine.equity, 2), "balance": round(engine.balance, 2)})

        for pos_id in list(engine.positions.keys()):
            engine._close_position_internal(pos_id, ExitReason.END_OF_DATA)

        strat.on_finish()
        perf = PerformanceCalculator.calculate(engine.closed_trades, engine.equity_curve, config.initial_balance)
        elapsed = time.time() - t0

        print(f"[{label}] in {elapsed:.2f}s -> Trades: {perf.total_trades} | Win%: {perf.win_rate_pct:.1f}% | Payoff: {perf.win_loss_ratio:.2f}x | Net: ${perf.net_profit:+,.2f} | PF: {perf.profit_factor:.2f} | MaxDD: {perf.max_drawdown_pct:.1f}%")
        results.append({
            "label": label,
            "trades": perf.total_trades,
            "win_rate": perf.win_rate_pct,
            "payoff": perf.win_loss_ratio,
            "net_pnl": perf.net_profit,
            "pf": perf.profit_factor,
            "dd": perf.max_drawdown_pct
        })

    print(f"\n{'='*100}")
    print(f"{'Fibonacci Strategy Model':<55} | {'Trades':<6} | {'Win%':<6} | {'Payoff':<6} | {'Net PnL':<11} | {'PF':<5} | {'MaxDD':<6}")
    print("-" * 100)
    for r in results:
        print(f"{r['label']:<55} | {r['trades']:<6} | {r['win_rate']:>5.1f}% | {r['payoff']:>5.2f}x | ${r['net_pnl']:>10,.2f} | {r['pf']:>4.2f} | {r['dd']:>5.1f}%")
    print("="*100)


if __name__ == "__main__":
    main()
