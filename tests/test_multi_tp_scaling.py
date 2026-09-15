"""
Audit of Multi-Stage Take Profits (1 TP vs 2 TPs vs 3 TPs vs 4 TPs):
Quantifies the exact impact on:
- Win Rate
- Payoff Ratio
- Net Profit
- Profit Factor
- Commission Drag
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


class MultiStageTPStrategy(IntradaySMCStrategy):
    def __init__(self, splits):
        super().__init__()
        self.splits = splits  # list of (ratio, r_mult)
        self.active_groups = {}

    def on_init(self):
        super().on_init()
        self.active_groups.clear()

    def _manage_callisto_twins(self):
        for gid, g in list(self.active_groups.items()):
            remaining = [o for o in g["orders"] if o["id"] in self.engine.positions]
            if not remaining:
                self.active_groups.pop(gid, None)
                continue

            # Stage 1: Move to BE on TP1 hit
            tp1_closed = g["orders"][0]["id"] not in self.engine.positions
            if tp1_closed and not g["be_moved"]:
                for rem in remaining:
                    pos = self.engine.positions[rem["id"]]
                    if g["dir"] == OrderDirection.BUY:
                        new_sl = round(g["entry"] + 0.20, 2)
                        if pos.stop_loss < new_sl:
                            pos.stop_loss = new_sl
                    else:
                        new_sl = round(g["entry"] - 0.20, 2)
                        if pos.stop_loss > new_sl:
                            pos.stop_loss = new_sl
                g["be_moved"] = True

            # Stage 2: If 3+ TPs and TP2 hit, lock +1.0R on remaining
            if len(g["orders"]) >= 3 and not g.get("trail_moved", False):
                tp2_closed = g["orders"][1]["id"] not in self.engine.positions
                if tp2_closed:
                    for rem in remaining:
                        pos = self.engine.positions[rem["id"]]
                        if g["dir"] == OrderDirection.BUY:
                            new_sl = round(g["entry"] + g["risk"] * 1.0, 2)
                            if pos.stop_loss < new_sl:
                                pos.stop_loss = new_sl
                        else:
                            new_sl = round(g["entry"] - g["risk"] * 1.0, 2)
                            if pos.stop_loss > new_sl:
                                pos.stop_loss = new_sl
                    g["trail_moved"] = True

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
            self._manage_callisto_twins()
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

        # BUY
        if self.h1_bias == 1 and gc > go and (lower_wick / rng) >= 0.35:
            valid_pois = [p for p in self.active_pois if p.poi_type in ("BULLISH_OB", "BULLISH_IFVG") and (p.bottom - self.poi_tolerance) <= gl <= (p.top + self.poi_tolerance)]
            if valid_pois:
                best = valid_pois[-1]
                stop = round(best.bottom - self.sl_buffer, 2)
                risk = gc - stop
                if 1.50 <= risk <= 8.00:
                    approval = self.governor.evaluate_entry(gc, stop, spread, 0.35, len(self.engine.positions))
                    if approval.approved:
                        tot_lots = approval.lots
                        orders = []
                        gid = f"B_{dt}"
                        for idx, (ratio, r_mult) in enumerate(self.splits):
                            lots = round(max(0.01, tot_lots * ratio), 2)
                            tp = round(gc + risk * r_mult, 2)
                            pid = self.engine.buy("XAUUSD", lots, stop, tp, comment=f"TP{idx+1}")
                            if pid:
                                orders.append({"id": pid, "r": r_mult})
                        if orders:
                            self.active_groups[gid] = {"orders": orders, "entry": gc, "risk": risk, "dir": OrderDirection.BUY, "be_moved": False}
                            self.traded_today += 1
                            return

        # SELL
        if self.h1_bias == -1 and gc < go and (upper_wick / rng) >= 0.35:
            valid_pois = [p for p in self.active_pois if p.poi_type in ("BEARISH_OB", "BEARISH_IFVG") and (p.bottom - self.poi_tolerance) <= gh <= (p.top + self.poi_tolerance)]
            if valid_pois:
                best = valid_pois[-1]
                stop = round(best.top + self.sl_buffer, 2)
                risk = stop - gc
                if 1.50 <= risk <= 8.00:
                    approval = self.governor.evaluate_entry(gc, stop, spread, 0.35, len(self.engine.positions))
                    if approval.approved:
                        tot_lots = approval.lots
                        orders = []
                        gid = f"S_{dt}"
                        for idx, (ratio, r_mult) in enumerate(self.splits):
                            lots = round(max(0.01, tot_lots * ratio), 2)
                            tp = round(gc - risk * r_mult, 2)
                            pid = self.engine.sell("XAUUSD", lots, stop, tp, comment=f"TP{idx+1}")
                            if pid:
                                orders.append({"id": pid, "r": r_mult})
                        if orders:
                            self.active_groups[gid] = {"orders": orders, "entry": gc, "risk": risk, "dir": OrderDirection.SELL, "be_moved": False}
                            self.traded_today += 1
                            return


def main():
    df_m15 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_M15.parquet")

    experiments = [
        ("1 TP: 100% @ 3.0R (Single Target)", [(1.00, 3.0)]),
        ("2 TPs: 50% @ 1.5R + 50% @ 4.0R (Twin Callisto)", [(0.50, 1.5), (0.50, 4.0)]),
        ("3 TPs: 33% @ 1.5R + 33% @ 3.0R + 34% @ 5.0R", [(0.33, 1.5), (0.33, 3.0), (0.34, 5.0)]),
        ("3 TPs Asymmetric: 50% @ 1.5R + 30% @ 3.0R + 20% @ 6.0R", [(0.50, 1.5), (0.30, 3.0), (0.20, 6.0)]),
        ("4 TPs: 40% @ 1.0R + 20% @ 2.0R + 20% @ 3.5R + 20% @ 5.0R", [(0.40, 1.0), (0.20, 2.0), (0.20, 3.5), (0.20, 5.0)]),
        ("5 TPs: 20% @ 1.0R + 20% @ 2.0R + 20% @ 3.0R + 20% @ 4.0R + 20% @ 5.0R", [(0.20, 1.0), (0.20, 2.0), (0.20, 3.0), (0.20, 4.0), (0.20, 5.0)]),
    ]

    print(f"\n{'='*95}")
    print("🔬 QUANTITATIVE AUDIT: 1 TP vs 2 TPs vs 3 TPs vs 4 TPs vs 5 TPs (M15 XAUUSD)")
    print(f"{'='*95}\n")

    results = []
    for label, splits in experiments:
        t0 = time.time()
        strat = MultiStageTPStrategy(splits)
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

        print(f"[{label}] -> Trades: {perf.total_trades} | Win%: {perf.win_rate_pct:.1f}% | Payoff: {perf.win_loss_ratio:.2f}x | Net: ${perf.net_profit:+,.2f} | PF: {perf.profit_factor:.2f} | MaxDD: {perf.max_drawdown_pct:.1f}%")
        results.append({
            "label": label,
            "trades": perf.total_trades,
            "win_rate": perf.win_rate_pct,
            "payoff": perf.win_loss_ratio,
            "net_pnl": perf.net_profit,
            "pf": perf.profit_factor,
            "dd": perf.max_drawdown_pct
        })

    print(f"\n{'='*98}")
    print(f"{'Configuration':<52} | {'Trades':<6} | {'Win%':<6} | {'Payoff':<6} | {'Net PnL':<11} | {'PF':<5} | {'MaxDD':<6}")
    print("-" * 98)
    for r in results:
        print(f"{r['label']:<52} | {r['trades']:<6} | {r['win_rate']:>5.1f}% | {r['payoff']:>5.2f}x | ${r['net_pnl']:>10,.2f} | {r['pf']:>4.2f} | {r['dd']:>5.1f}%")
    print("="*98)


if __name__ == "__main__":
    main()
