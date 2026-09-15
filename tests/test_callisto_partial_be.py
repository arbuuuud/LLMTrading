"""
Quantitative Evaluation of the Callisto Trade Management Technique:
(Partial Take Profit + Move Stop Loss to Breakeven).

Comparison on 10.5 Months of Real M1 XAUUSD (300,440 Bars):
1. Baseline: Standard Full Target (100% volume exits at VWAP Mean / 2.0x RR, fixed SL).
2. Callisto Twin 50/50 @ 1.0R:
   - Order A (50% lots): TP at 1.0R.
   - Order B (50% lots): When Order A hits TP, move Order B SL to Breakeven (Entry + spread/comm buffer).
     Order B TP targets VWAP Mean / 2.5x RR.
3. Callisto Twin 60/40 @ 1.0R:
   - Order A (60% lots): TP at 1.0R.
   - Order B (40% lots): SL to BE on TP1, TP targets 3.0x RR.
4. Callisto Twin 50/50 @ 1.5R:
   - Order A (50% lots): TP at 1.5R.
   - Order B (50% lots): SL to BE on TP1, TP targets 2.5x RR.
5. Pure Breakeven Trailing (No Partial Close):
   - 100% lots, when price reaches 1.0R in profit, move SL to Breakeven (+0.10 buffer), TP at 2.0x RR.
"""

import sys
import time
from pathlib import Path
from collections import defaultdict
import math

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from engine.core.event_engine import EventEngine
from engine.core.types import AccountConfig, ExitReason, OrderDirection
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from engine.metrics.performance import PerformanceCalculator
from agents.risk_manager.monthly_ratchet_governor import MonthlyRatchetGovernor
from engine.core.strategy_base import BaseStrategy


class CallistoStrategy(BaseStrategy):
    def __init__(
        self,
        mode: str = "BASELINE",  # "BASELINE", "TWIN_50_50_1R", "TWIN_60_40_1R", "TWIN_50_50_15R", "PURE_BE_1R"
        band_multiplier: float = 1.8,
        sl_buffer: float = 0.50,
        start_hour: int = 10,
        start_minute: int = 30,
        end_hour: int = 14,
        end_minute: int = 30
    ):
        super().__init__(f"Callisto_{mode}")
        self.mode = mode
        self.band_multiplier = band_multiplier
        self.sl_buffer = sl_buffer
        self.start_time = (start_hour, start_minute)
        self.end_time = (end_hour, end_minute)

        self.governor = MonthlyRatchetGovernor(
            base_risk_pct=0.5,
            greed_risk_pct=0.25,
            max_daily_loss_pct=1.0,
            monthly_loss_cap_pct=3.0,
            cooldown_bars=25
        )

        self.current_date = None
        self.cum_vol = 0.0
        self.cum_pv = 0.0
        self.cum_p2v = 0.0
        self.current_vwap = 0.0
        self.current_std = 0.0
        self.upper_band = 0.0
        self.lower_band = 0.0
        self.bars_in_trade = 0
        self.traded_today = 0

        # Track twin orders for Callisto trade management
        # structure: { "master_pos_id": ..., "runner_pos_id": ..., "entry": ..., "risk_dist": ..., "dir": ..., "be_moved": False }
        self.active_twins = {}
        self.pure_be_orders = {}

    def on_init(self):
        self.current_date = None
        self.cum_vol = 0.0
        self.cum_pv = 0.0
        self.cum_p2v = 0.0
        self.current_vwap = 0.0
        self.current_std = 0.0
        self.upper_band = 0.0
        self.lower_band = 0.0
        self.bars_in_trade = 0
        self.traded_today = 0
        self.active_twins.clear()
        self.pure_be_orders.clear()

    def on_trade_closed(self, trade_record):
        self.governor.on_trade_closed(trade_record.net_pnl)

    def on_bar(self, bar):
        dt = bar["timestamp"]
        d = dt.date()
        t = dt.time()

        gh, gl, gc, go = bar["high"], bar["low"], bar["close"], bar["open"]
        vol = max(1.0, float(bar.get("tick_volume", 1)))
        spread = bar.get("mean_spread", 0.20)

        if self.current_date != d:
            self.current_date = d
            self.cum_vol = 0.0
            self.cum_pv = 0.0
            self.cum_p2v = 0.0
            self.bars_in_trade = 0
            self.traded_today = 0

        tp_price = (gh + gl + gc) / 3.0
        self.cum_vol += vol
        self.cum_pv += tp_price * vol
        self.cum_p2v += (tp_price ** 2) * vol

        self.current_vwap = self.cum_pv / self.cum_vol
        variance = max(0.0, (self.cum_p2v / self.cum_vol) - (self.current_vwap ** 2))
        self.current_std = math.sqrt(variance)

        self.upper_band = self.current_vwap + (self.current_std * self.band_multiplier)
        self.lower_band = self.current_vwap - (self.current_std * self.band_multiplier)

        self.governor.on_new_bar(dt, self.engine.equity)

        # -------------------------------------------------------------
        # 1. Active Position Trade Management (Callisto Logic)
        # -------------------------------------------------------------
        if len(self.engine.positions) > 0:
            self.bars_in_trade += 1

            # Check Twin Management (Move runner SL to BE when master hits TP or price reaches milestone)
            for key, twin in list(self.active_twins.items()):
                runner_id = twin["runner_pos_id"]
                master_id = twin["master_pos_id"]

                # If master closed (hit TP1) and runner is still open, move runner SL to BE
                if master_id not in self.engine.positions and runner_id in self.engine.positions:
                    runner_pos = self.engine.positions[runner_id]
                    if not twin["be_moved"]:
                        # Move SL to Breakeven (+0.10 buffer for spread/comm)
                        if twin["dir"] == OrderDirection.BUY:
                            new_sl = round(twin["entry"] + 0.10, 2)
                            if runner_pos.stop_loss < new_sl:
                                runner_pos.stop_loss = new_sl
                        else:
                            new_sl = round(twin["entry"] - 0.10, 2)
                            if runner_pos.stop_loss > new_sl:
                                runner_pos.stop_loss = new_sl
                        twin["be_moved"] = True

                # Clean up if runner is also closed
                if runner_id not in self.engine.positions and master_id not in self.engine.positions:
                    self.active_twins.pop(key, None)

            # Check Pure BE Orders
            for pos_id, order_info in list(self.pure_be_orders.items()):
                if pos_id in self.engine.positions:
                    pos = self.engine.positions[pos_id]
                    if not order_info["be_moved"]:
                        if order_info["dir"] == OrderDirection.BUY:
                            # If price reached 1.0R profit, move to BE
                            if gh >= (order_info["entry"] + order_info["risk"]):
                                pos.stop_loss = round(order_info["entry"] + 0.10, 2)
                                order_info["be_moved"] = True
                        else:
                            if gl <= (order_info["entry"] - order_info["risk"]):
                                pos.stop_loss = round(order_info["entry"] - 0.10, 2)
                                order_info["be_moved"] = True
                else:
                    self.pure_be_orders.pop(pos_id, None)

            # Timeout after 60 bars
            if self.bars_in_trade >= 60:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
                self.bars_in_trade = 0
            return
        else:
            self.bars_in_trade = 0

        # -------------------------------------------------------------
        # 2. Golden Window & Session Filters
        # -------------------------------------------------------------
        is_window = self.start_time <= (t.hour, t.minute) <= self.end_time
        if not is_window or self.traded_today >= 2:
            return

        rng = gh - gl
        if rng < 0.35:
            return

        upper_wick = gh - max(go, gc)
        lower_wick = min(go, gc) - gl

        # -------------------------------------------------------------
        # SETUP 1: SHORT MEAN REVERSION (+1.8 Sigma)
        # -------------------------------------------------------------
        if gh >= self.upper_band and (upper_wick / rng) >= 0.45 and gc < go:
            stop = round(gh + self.sl_buffer, 2)
            risk_dist = stop - gc
            if 0.80 <= risk_dist <= 5.00:
                approval = self.governor.evaluate_entry(
                    entry_price=gc,
                    stop_loss=stop,
                    current_spread=spread,
                    max_allowed_spread=0.25,
                    num_open_positions=len(self.engine.positions)
                )
                if approval.approved:
                    total_lots = approval.lots

                    if self.mode == "BASELINE":
                        tp = round(gc - (risk_dist * 2.0), 2)
                        if self.current_vwap < gc and (gc - self.current_vwap) >= risk_dist * 1.5:
                            tp = round(self.current_vwap, 2)
                        self.engine.sell("XAUUSD", total_lots, stop, tp, comment="Short_Base")
                        self.traded_today += 1

                    elif self.mode == "PURE_BE_1R":
                        tp = round(gc - (risk_dist * 2.0), 2)
                        if self.current_vwap < gc and (gc - self.current_vwap) >= risk_dist * 1.5:
                            tp = round(self.current_vwap, 2)
                        pid = self.engine.sell("XAUUSD", total_lots, stop, tp, comment="Short_PureBE")
                        if pid:
                            self.pure_be_orders[pid] = {
                                "entry": gc, "risk": risk_dist, "dir": OrderDirection.SELL, "be_moved": False
                            }
                            self.traded_today += 1

                    elif self.mode.startswith("TWIN"):
                        # Determine split ratios
                        if "50_50" in self.mode:
                            ratio_a = 0.50
                        elif "60_40" in self.mode:
                            ratio_a = 0.60
                        else:
                            ratio_a = 0.50

                        lots_a = round(max(0.01, total_lots * ratio_a), 2)
                        lots_b = round(max(0.01, total_lots - lots_a), 2)

                        # Determine TP1 and TP2
                        if "15R" in self.mode:
                            tp_a = round(gc - (risk_dist * 1.5), 2)
                        else:
                            tp_a = round(gc - (risk_dist * 1.0), 2)

                        if "3R" in self.mode:
                            tp_b = round(gc - (risk_dist * 3.0), 2)
                        else:
                            tp_b = round(gc - (risk_dist * 2.5), 2)
                            if self.current_vwap < gc and (gc - self.current_vwap) >= risk_dist * 1.5:
                                tp_b = round(self.current_vwap, 2)

                        pid_a = self.engine.sell("XAUUSD", lots_a, stop, tp_a, comment="Twin_A_Partial")
                        pid_b = self.engine.sell("XAUUSD", lots_b, stop, tp_b, comment="Twin_B_Runner")
                        if pid_a and pid_b:
                            pair_key = f"{pid_a}_{pid_b}"
                            self.active_twins[pair_key] = {
                                "master_pos_id": pid_a,
                                "runner_pos_id": pid_b,
                                "entry": gc,
                                "risk_dist": risk_dist,
                                "dir": OrderDirection.SELL,
                                "be_moved": False
                            }
                            self.traded_today += 1

        # -------------------------------------------------------------
        # SETUP 2: LONG MEAN REVERSION (-1.8 Sigma)
        # -------------------------------------------------------------
        if gl <= self.lower_band and (lower_wick / rng) >= 0.45 and gc > go:
            stop = round(gl - self.sl_buffer, 2)
            risk_dist = gc - stop
            if 0.80 <= risk_dist <= 5.00:
                approval = self.governor.evaluate_entry(
                    entry_price=gc,
                    stop_loss=stop,
                    current_spread=spread,
                    max_allowed_spread=0.25,
                    num_open_positions=len(self.engine.positions)
                )
                if approval.approved:
                    total_lots = approval.lots

                    if self.mode == "BASELINE":
                        tp = round(gc + (risk_dist * 2.0), 2)
                        if self.current_vwap > gc and (self.current_vwap - gc) >= risk_dist * 1.5:
                            tp = round(self.current_vwap, 2)
                        self.engine.buy("XAUUSD", total_lots, stop, tp, comment="Long_Base")
                        self.traded_today += 1

                    elif self.mode == "PURE_BE_1R":
                        tp = round(gc + (risk_dist * 2.0), 2)
                        if self.current_vwap > gc and (self.current_vwap - gc) >= risk_dist * 1.5:
                            tp = round(self.current_vwap, 2)
                        pid = self.engine.buy("XAUUSD", total_lots, stop, tp, comment="Long_PureBE")
                        if pid:
                            self.pure_be_orders[pid] = {
                                "entry": gc, "risk": risk_dist, "dir": OrderDirection.BUY, "be_moved": False
                            }
                            self.traded_today += 1

                    elif self.mode.startswith("TWIN"):
                        if "50_50" in self.mode:
                            ratio_a = 0.50
                        elif "60_40" in self.mode:
                            ratio_a = 0.60
                        else:
                            ratio_a = 0.50

                        lots_a = round(max(0.01, total_lots * ratio_a), 2)
                        lots_b = round(max(0.01, total_lots - lots_a), 2)

                        if "15R" in self.mode:
                            tp_a = round(gc + (risk_dist * 1.5), 2)
                        else:
                            tp_a = round(gc + (risk_dist * 1.0), 2)

                        if "3R" in self.mode:
                            tp_b = round(gc + (risk_dist * 3.0), 2)
                        else:
                            tp_b = round(gc + (risk_dist * 2.5), 2)
                            if self.current_vwap > gc and (self.current_vwap - gc) >= risk_dist * 1.5:
                                tp_b = round(self.current_vwap, 2)

                        pid_a = self.engine.buy("XAUUSD", lots_a, stop, tp_a, comment="Twin_A_Partial")
                        pid_b = self.engine.buy("XAUUSD", lots_b, stop, tp_b, comment="Twin_B_Runner")
                        if pid_a and pid_b:
                            pair_key = f"{pid_a}_{pid_b}"
                            self.active_twins[pair_key] = {
                                "master_pos_id": pid_a,
                                "runner_pos_id": pid_b,
                                "entry": gc,
                                "risk_dist": risk_dist,
                                "dir": OrderDirection.BUY,
                                "be_moved": False
                            }
                            self.traded_today += 1


def main():
    m1_path = "data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet"
    print(f"Loading M1 bars from {m1_path}...")
    df_m1 = pl.read_parquet(m1_path)

    modes = [
        ("1. Baseline: Full Target (No Partial, No BE)", "BASELINE"),
        ("2. Pure Breakeven @ 1.0R (Lock BE on 1R, 100% Ride to 2R)", "PURE_BE_1R"),
        ("3. Callisto 50/50 @ 1.0R (50% TP1 @ 1R -> BE -> 50% Runner @ VWAP/2.5R)", "TWIN_50_50_1R"),
        ("4. Callisto 60/40 @ 1.0R (60% TP1 @ 1R -> BE -> 40% Runner @ 3.0R)", "TWIN_60_40_1R"),
        ("5. Callisto 50/50 @ 1.5R (50% TP1 @ 1.5R -> BE -> 50% Runner @ 2.5R)", "TWIN_50_50_15R"),
    ]

    results = []
    print(f"\n{'='*95}")
    print("🔬 QUANTITATIVE AUDIT: CALLISTO PARTIAL TP & BREAKEVEN ON 300,440 BARS")
    print(f"{'='*95}\n")

    for label, mode in modes:
        t0 = time.time()
        strat = CallistoStrategy(mode=mode, band_multiplier=1.8, sl_buffer=0.50)
        config = AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0)
        engine = EventEngine(config=config, commission_model=CommissionModel(7.0), slippage_model=FixedSlippageModel(0.02))
        engine.reset()
        engine.current_strategy = strat
        strat.set_engine(engine)
        strat.on_init()

        for bar in df_m1.iter_rows(named=True):
            engine.current_time = bar["timestamp"]
            spread = bar.get("mean_spread", 0.20)
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

        monthly_pnl = defaultdict(float)
        for tr in engine.closed_trades:
            monthly_pnl[tr.open_time.strftime("%Y-%m")] += tr.net_pnl
        pos_m = sum(1 for v in monthly_pnl.values() if v > 0)
        tot_m = len(monthly_pnl) or 1

        elapsed = time.time() - t0
        print(f"[{label}] in {elapsed:.1f}s -> Trades: {perf.total_trades}, Win: {perf.win_rate_pct:.1f}%, Payoff: {perf.win_loss_ratio:.2f}x, Net: ${perf.net_profit:+,.2f}, PF: {perf.profit_factor:.2f}, DD: {perf.max_drawdown_pct:.1f}%, Months: {pos_m}/{tot_m}")
        results.append({
            "label": label,
            "trades": perf.total_trades,
            "win_rate": perf.win_rate_pct,
            "payoff": perf.win_loss_ratio,
            "net_pnl": perf.net_profit,
            "pf": perf.profit_factor,
            "dd": perf.max_drawdown_pct,
            "months": f"{pos_m}/{tot_m}"
        })

    print(f"\n{'='*98}")
    print(f"{'Management Strategy':<52} | {'Trades':<6} | {'Win%':<6} | {'Payoff':<6} | {'Net PnL':<11} | {'PF':<5} | {'MaxDD':<6} | {'Months'}")
    print("-" * 98)
    for r in results:
        print(f"{r['label']:<52} | {r['trades']:<6} | {r['win_rate']:>5.1f}% | {r['payoff']:>5.2f}x | ${r['net_pnl']:>10,.2f} | {r['pf']:>4.2f} | {r['dd']:>5.1f}% | {r['months']}")
    print("="*98)


if __name__ == "__main__":
    main()
