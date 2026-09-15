"""
Super-Clone Synthesis: Al Brooks High 2 / Low 2 + Macro H1 EMA 50 + Volume Confirmation.
Can Al Brooks' High 2 / Low 2 beat our current Fadli NFC record (+713)?
"""

import sys
import time
from pathlib import Path
from collections import defaultdict
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from engine.core.event_engine import EventEngine
from engine.core.types import AccountConfig, OrderDirection, ExitReason
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from engine.metrics.performance import PerformanceCalculator
from engine.core.strategy_base import BaseStrategy
from agents.risk_manager.monthly_ratchet_governor import MonthlyRatchetGovernor

df_m15 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_M15.parquet")
df_h1 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_H1.parquet")

df_h1 = df_h1.with_columns([
    pl.col("close").ewm_mean(span=50).alias("ema50"),
    (pl.col("high") - pl.col("low")).rolling_mean(window_size=14).alias("atr14")
])
h1_map = {row["timestamp"]: {"close": row["close"], "ema50": row["ema50"], "atr14": row["atr14"] or 5.0} for row in df_h1.iter_rows(named=True)}


class BrooksMacroHybrid(BaseStrategy):
    def __init__(self, rr_target=3.0, use_macro=True):
        super().__init__(f"Brooks_Macro_RR{rr_target}")
        self.rr_target = rr_target
        self.use_macro = use_macro
        self.governor = MonthlyRatchetGovernor(base_risk_pct=0.5, greed_risk_pct=0.25, max_daily_loss_pct=1.0, monthly_loss_cap_pct=3.0, cooldown_bars=8)
        self.bars = []
        self.current_date = None
        self.traded_today = 0

    def on_init(self):
        self.bars.clear()
        self.current_date = None
        self.traded_today = 0

    def _calc_ema20(self):
        if len(self.bars) < 20: return None
        closes = [b["close"] for b in self.bars]
        alpha = 2.0 / (20.0 + 1.0)
        ema = closes[0]
        for c in closes[1:]:
            ema = (c * alpha) + (ema * (1.0 - alpha))
        return ema

    def _get_h1(self, dt):
        t = dt.replace(minute=0, second=0, microsecond=0)
        return h1_map.get(t, None)

    def on_bar(self, bar):
        dt = bar["timestamp"]
        d = dt.date()
        t = dt.time()
        gh, gl, gc, go = bar["high"], bar["low"], bar["close"], bar["open"]
        spread = bar.get("mean_spread", 0.25)

        self.bars.append(bar)
        if len(self.bars) > 40: self.bars.pop(0)

        if self.current_date != d:
            self.current_date = d
            self.traded_today = 0

        self.governor.on_new_bar(dt, self.engine.equity)

        if len(self.engine.positions) > 0:
            if t.hour >= 21 and t.minute >= 30:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
            return

        if not ((8, 0) <= (t.hour, t.minute) <= (16, 30)) or self.traded_today >= 1:
            return

        ema20 = self._calc_ema20()
        if ema20 is None or len(self.bars) < 6:
            return

        h1 = self._get_h1(dt)
        is_bull_macro = True
        is_bear_macro = True
        if h1 is not None and self.use_macro:
            is_bull_macro = (h1["close"] >= h1["ema50"])
            is_bear_macro = (h1["close"] <= h1["ema50"])

        b1 = self.bars[-1]
        b2 = self.bars[-2]
        b3 = self.bars[-3]

        # HIGH 2 (Bullish)
        if gc > ema20 and is_bull_macro:
            is_near_ema = abs(gl - ema20) <= 2.00 or (gl <= ema20 <= gh)
            if is_near_ema and gc > go:
                if b3["close"] < b3["open"] or b2["close"] < b2["open"]:
                    sl = round(min(gl, b2["low"]) - 1.20, 2)
                    risk = gc - sl
                    if 1.50 <= risk <= 6.50:
                        tp = round(gc + risk * self.rr_target, 2)
                        approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                        if approval.approved:
                            self.engine.buy("XAUUSD", approval.lots, sl, tp, comment="Brooks_High2_Buy")
                            self.traded_today += 1
                            return

        # LOW 2 (Bearish)
        elif gc < ema20 and is_bear_macro:
            is_near_ema = abs(gh - ema20) <= 2.00 or (gl <= ema20 <= gh)
            if is_near_ema and gc < go:
                if b3["close"] > b3["open"] or b2["close"] > b2["open"]:
                    sl = round(max(gh, b2["high"]) + 1.20, 2)
                    risk = sl - gc
                    if 1.50 <= risk <= 6.50:
                        tp = round(gc - risk * self.rr_target, 2)
                        approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                        if approval.approved:
                            self.engine.sell("XAUUSD", approval.lots, sl, tp, comment="Brooks_Low2_Sell")
                            self.traded_today += 1
                            return


def main():
    experiments = [
        ("1. Al Brooks High 2 / Low 2 Murni (RR 3.0)", False, 3.0),
        ("2. Al Brooks H2/L2 + H1 EMA 50 Macro Filter (RR 2.5)", True, 2.5),
        ("3. Al Brooks H2/L2 + H1 EMA 50 Macro Filter (RR 3.0)", True, 3.0),
        ("4. Al Brooks H2/L2 + H1 EMA 50 Macro Filter (RR 3.5)", True, 3.5),
    ]
    for label, use_m, rr in experiments:
        t0 = time.time()
        strat = BrooksMacroHybrid(rr_target=rr, use_macro=use_m)
        c = AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0)
        e = EventEngine(config=c, commission_model=CommissionModel(7.0), slippage_model=FixedSlippageModel(0.02))
        e.reset()
        e.current_strategy = strat
        strat.set_engine(e)
        strat.on_init()

        for bar in df_m15.iter_rows(named=True):
            e.current_time = bar["timestamp"]
            spread = bar.get("mean_spread", 0.25)
            e.current_bid = bar["close"]
            e.current_ask = round(e.current_bid + spread, 3)
            e.current_spread = spread
            e._check_daily_circuit_breaker(e.current_time)
            e._update_positions_on_bar(bar)
            strat.on_bar(bar)
            e.equity_curve.append({"timestamp": e.current_time, "equity": round(e.equity, 2), "balance": round(e.balance, 2)})

        for pos_id in list(e.positions.keys()):
            e._close_position_internal(pos_id, ExitReason.END_OF_DATA)

        strat.on_finish()
        perf = PerformanceCalculator.calculate(e.closed_trades, e.equity_curve, c.initial_balance)
        monthly = defaultdict(float)
        for tr in e.closed_trades: monthly[tr.open_time.strftime("%Y-%m")] += tr.net_pnl
        pos_m = sum(1 for v in monthly.values() if v > 0)
        tot_m = len(monthly) or 1
        print(f"[{label:<55}] -> Trades: {perf.total_trades:3d} | Win: {perf.win_rate_pct:>5.1f}% | Payoff: {perf.win_loss_ratio:>4.2f}x | Net: ${perf.net_profit:>10,.2f} | PF: {perf.profit_factor:>4.2f} | DD: {perf.max_drawdown_pct:>4.1f}% | Months: {pos_m}/{tot_m}")


if __name__ == "__main__":
    main()
