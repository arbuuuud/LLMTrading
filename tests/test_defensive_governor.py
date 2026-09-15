"""
Experiment: Eliminating Losing Months via Institutional Risk Refinements:
1. Cooldown Period (25m vs 60m vs 120m vs 1-loss-and-done for the day).
2. Dynamic Volatility Band (Expand band to 2.0s or 2.2s if daily ATR > average).
3. Directional Momentum Defense (Pause opposite trades if price broke 20-day high/low).
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


class DefensiveScalper(SessionAnchoredVWAPStrategy):
    def __init__(
        self,
        band_multiplier: float = 1.8,
        max_trades_per_day: int = 2,
        stop_day_on_first_loss: bool = False,
        cooldown_bars: int = 25,
        dynamic_atr_band: bool = False
    ):
        super().__init__(
            band_multiplier=band_multiplier,
            sl_buffer_dollars=0.50,
            risk_reward_ratio=2.0,
            base_risk_pct=0.5,
            greed_risk_pct=0.25,
            max_bars_hold=60,
            start_hour=10,
            start_minute=30,
            end_hour=14,
            end_minute=30
        )
        self.max_trades_per_day = max_trades_per_day
        self.stop_day_on_first_loss = stop_day_on_first_loss
        self.cooldown_limit = cooldown_bars
        self.dynamic_atr_band = dynamic_atr_band

        self.loss_today_count = 0
        self.bars_since_last_loss = 999

    def on_init(self):
        super().on_init()
        self.loss_today_count = 0
        self.bars_since_last_loss = 999

    def on_trade_closed(self, trade_record):
        super().on_trade_closed(trade_record)
        if trade_record.net_pnl < 0:
            self.loss_today_count += 1
            self.bars_since_last_loss = 0

    def on_bar(self, bar):
        dt = bar["timestamp"]
        d = dt.date()
        t = dt.time()

        gh, gl, gc, go = bar["high"], bar["low"], bar["close"], bar["open"]
        vol = max(1.0, float(bar.get("tick_volume", 1)))
        spread = bar.get("mean_spread", 0.20)

        self.bars_since_last_loss += 1

        if self.current_date != d:
            self.current_date = d
            self.cum_vol = 0.0
            self.cum_pv = 0.0
            self.cum_p2v = 0.0
            self.bars_in_trade = 0
            self.traded_today_count = 0
            self.loss_today_count = 0
            self.bars_since_last_loss = 999

        tp_price = (gh + gl + gc) / 3.0
        self.cum_vol += vol
        self.cum_pv += tp_price * vol
        self.cum_p2v += (tp_price ** 2) * vol

        self.current_vwap = self.cum_pv / self.cum_vol
        variance = max(0.0, (self.cum_p2v / self.cum_vol) - (self.current_vwap ** 2))
        self.current_std = math.sqrt(variance)

        # Dynamic Band expansion in high volatility
        eff_band = self.band_multiplier
        if self.dynamic_atr_band and self.current_std > 8.0:
            eff_band = self.band_multiplier + 0.3  # Expand to 2.1s in crazy volatility

        self.upper_band = self.current_vwap + (self.current_std * eff_band)
        self.lower_band = self.current_vwap - (self.current_std * eff_band)

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

        is_trade_window = self.start_time <= (t.hour, t.minute) <= self.end_time
        if not is_trade_window or self.traded_today_count >= self.max_trades_per_day:
            return

        if self.stop_day_on_first_loss and self.loss_today_count >= 1:
            return  # Stop trading for today on first strike!

        if self.bars_since_last_loss < self.cooldown_limit:
            return  # Still in cooling off period after loss

        rng = gh - gl
        if rng < 0.35:
            return

        upper_wick = gh - max(go, gc)
        lower_wick = min(go, gc) - gl

        # Short
        if gh >= self.upper_band and (upper_wick / rng) >= 0.45 and gc < go:
            stop = round(gh + self.sl_buffer, 2)
            risk = stop - gc
            if 0.80 <= risk <= 5.00:
                tp = round(gc - risk * self.risk_reward_ratio, 2)
                if self.current_vwap < gc and (gc - self.current_vwap) >= risk * 1.5:
                    tp = round(self.current_vwap, 2)
                approval = self.governor.evaluate_entry(gc, stop, spread, 0.25, len(self.engine.positions))
                if approval.approved:
                    pid = self.engine.sell("XAUUSD", approval.lots, stop, tp, comment="Short")
                    if pid:
                        self.traded_today_count += 1
                        return

        # Long
        if gl <= self.lower_band and (lower_wick / rng) >= 0.45 and gc > go:
            stop = round(gl - self.sl_buffer, 2)
            risk = gc - stop
            if 0.80 <= risk <= 5.00:
                tp = round(gc + risk * self.risk_reward_ratio, 2)
                if self.current_vwap > gc and (self.current_vwap - gc) >= risk * 1.5:
                    tp = round(self.current_vwap, 2)
                approval = self.governor.evaluate_entry(gc, stop, spread, 0.25, len(self.engine.positions))
                if approval.approved:
                    pid = self.engine.buy("XAUUSD", approval.lots, stop, tp, comment="Long")
                    if pid:
                        self.traded_today_count += 1
                        return


def run_test(label, strat):
    c = AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0)
    e = EventEngine(config=c, commission_model=CommissionModel(7.0), slippage_model=FixedSlippageModel(0.02))
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
    
    print(f"\n[{label}]")
    print(f"  Trades: {perf.total_trades} | Win: {perf.win_rate_pct:.1f}% | Payoff: {perf.win_loss_ratio:.2f}x | Net: ${perf.net_profit:+,.2f} | PF: {perf.profit_factor:.2f} | DD: {perf.max_drawdown_pct:.1f}% | Positive Months: {pos_m}/{tot_m}")
    for m in sorted(monthly.keys()):
        print(f"    {m}: ${monthly[m]:+8.2f}")


def main():
    experiments = [
        ("1. Baseline (2 trades/day, 25m cooldown)", DefensiveScalper(band_multiplier=1.8, max_trades_per_day=2, stop_day_on_first_loss=False, cooldown_bars=25)),
        ("2. One-Strike Rule (Stop day on 1st loss)", DefensiveScalper(band_multiplier=1.8, max_trades_per_day=2, stop_day_on_first_loss=True, cooldown_bars=25)),
        ("3. 60-Minute Cooldown after Loss", DefensiveScalper(band_multiplier=1.8, max_trades_per_day=2, stop_day_on_first_loss=False, cooldown_bars=60)),
        ("4. 90-Minute Cooldown after Loss", DefensiveScalper(band_multiplier=1.8, max_trades_per_day=2, stop_day_on_first_loss=False, cooldown_bars=90)),
        ("5. Dynamic ATR Volatility Band (Expand to 2.1s in storm)", DefensiveScalper(band_multiplier=1.8, max_trades_per_day=2, stop_day_on_first_loss=False, cooldown_bars=25, dynamic_atr_band=True)),
        ("6. 1 Trade Per Day Strictly", DefensiveScalper(band_multiplier=1.8, max_trades_per_day=1, stop_day_on_first_loss=False, cooldown_bars=25)),
    ]

    for label, strat in experiments:
        run_test(label, strat)


if __name__ == "__main__":
    main()
