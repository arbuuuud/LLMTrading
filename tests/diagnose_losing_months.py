"""
Diagnose Losing Months & Test Macro Regime Defense:
Why did July, September, and November 2025 lose money?
How can we eliminate or flip them to profit?
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
from engine.core.types import AccountConfig, OrderDirection, ExitReason
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from engine.metrics.performance import PerformanceCalculator
from strategies.incubator.strat_3_anchored_vwap import SessionAnchoredVWAPStrategy

df_m1 = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")
df_h4 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_H4.parquet")

# Precompute H4 EMA 50
df_h4 = df_h4.with_columns([
    pl.col("close").ewm_mean(span=50).alias("ema50")
])
h4_map = {row["timestamp"]: row["ema50"] for row in df_h4.iter_rows(named=True)}


class TrendFilteredScalper(SessionAnchoredVWAPStrategy):
    def __init__(self, mode="NO_FILTER"):
        super().__init__(band_multiplier=1.8, sl_buffer_dollars=0.50, risk_reward_ratio=2.0, max_bars_hold=60, start_hour=10, start_minute=30, end_hour=14, end_minute=30)
        self.mode = mode

    def _get_h4_ema(self, dt):
        b_hour = (dt.hour // 4) * 4
        b_time = dt.replace(hour=b_hour, minute=0, second=0, microsecond=0)
        return h4_map.get(b_time, None)

    def on_bar(self, bar):
        dt = bar["timestamp"]
        d = dt.date()
        t = dt.time()
        gh, gl, gc, go = bar["high"], bar["low"], bar["close"], bar["open"]
        vol = max(1.0, float(bar.get("tick_volume", 1)))
        spread = bar.get("mean_spread", 0.20)

        # Update VWAP
        if self.current_date != d:
            self.current_date = d
            self.cum_vol = 0.0
            self.cum_pv = 0.0
            self.cum_p2v = 0.0
            self.bars_in_trade = 0
            self.traded_today_count = 0

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

        if len(self.engine.positions) > 0:
            self.bars_in_trade += 1
            if self.bars_in_trade >= self.max_bars_hold:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
                self.bars_in_trade = 0
            return
        else:
            self.bars_in_trade = 0

        is_window = self.start_time <= (t.hour, t.minute) <= self.end_time
        if not is_window or self.traded_today_count >= 2:
            return

        rng = gh - gl
        if rng < 0.35:
            return

        upper_wick = gh - max(go, gc)
        lower_wick = min(go, gc) - gl

        h4_ema = self._get_h4_ema(dt)
        is_strong_bull = (h4_ema is not None and (gc - h4_ema) > 20.0)
        is_strong_bear = (h4_ema is not None and (h4_ema - gc) > 20.0)

        # SHORT
        if gh >= self.upper_band and (upper_wick / rng) >= 0.45 and gc < go:
            if self.mode == "PARABOLIC_FILTER" and is_strong_bull:
                return  # Skip shorting into parabolic runaway bull trend!

            stop = round(gh + self.sl_buffer, 2)
            risk = stop - gc
            if 0.80 <= risk <= 5.00:
                tp = round(gc - risk * 2.0, 2)
                if self.current_vwap < gc and (gc - self.current_vwap) >= risk * 1.5:
                    tp = round(self.current_vwap, 2)
                approval = self.governor.evaluate_entry(gc, stop, spread, 0.25, len(self.engine.positions))
                if approval.approved:
                    pid = self.engine.sell("XAUUSD", approval.lots, stop, tp, comment="Short")
                    if pid:
                        self.traded_today_count += 1
                        return

        # LONG
        if gl <= self.lower_band and (lower_wick / rng) >= 0.45 and gc > go:
            if self.mode == "PARABOLIC_FILTER" and is_strong_bear:
                return  # Skip buying into parabolic runaway bear trend!

            stop = round(gl - self.sl_buffer, 2)
            risk = gc - stop
            if 0.80 <= risk <= 5.00:
                tp = round(gc + risk * 2.0, 2)
                if self.current_vwap > gc and (self.current_vwap - gc) >= risk * 1.5:
                    tp = round(self.current_vwap, 2)
                approval = self.governor.evaluate_entry(gc, stop, spread, 0.25, len(self.engine.positions))
                if approval.approved:
                    pid = self.engine.buy("XAUUSD", approval.lots, stop, tp, comment="Long")
                    if pid:
                        self.traded_today_count += 1
                        return


def main():
    for mode in ["NO_FILTER", "PARABOLIC_FILTER"]:
        c = AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0)
        e = EventEngine(config=c, commission_model=CommissionModel(7.0), slippage_model=FixedSlippageModel(0.02))
        strat = TrendFilteredScalper(mode=mode)
        e.reset()
        e.current_strategy = strat
        strat.set_engine(e)
        strat.on_init()

        for bar in df_m1.iter_rows(named=True):
            e.current_time = bar["timestamp"]
            spread = bar.get("mean_spread", 0.20)
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
        for tr in e.closed_trades:
            monthly[tr.open_time.strftime("%Y-%m")] += tr.net_pnl
        pos_m = sum(1 for v in monthly.values() if v > 0)
        tot_m = len(monthly) or 1

        print(f"\n[{mode}] -> Trades: {perf.total_trades} | Win: {perf.win_rate_pct:.1f}% | Payoff: {perf.win_loss_ratio:.2f}x | Net: ${perf.net_profit:+,.2f} | PF: {perf.profit_factor:.2f} | DD: {perf.max_drawdown_pct:.1f}% | Months: {pos_m}/{tot_m}")
        for m in sorted(monthly.keys()):
            print(f"  {m}: ${monthly[m]:+8.2f}")


if __name__ == "__main__":
    main()
