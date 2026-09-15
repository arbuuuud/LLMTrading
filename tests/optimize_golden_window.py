"""
Optimization of the Golden Institutional Window (10:30 - 14:30 UTC).
Fine-tunes:
- Band Multiplier (1.6, 1.8, 2.0, 2.2)
- Risk-Reward Ratio (1.8, 2.0, 2.5, 3.0)
- SL Buffer Dollars (0.35, 0.45, 0.55)
- Target Method (VWAP Mean vs Fixed RR)
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
from engine.core.types import AccountConfig, ExitReason
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from engine.metrics.performance import PerformanceCalculator
from agents.risk_manager.monthly_ratchet_governor import MonthlyRatchetGovernor
from engine.core.strategy_base import BaseStrategy


class GoldenWindowSniper(BaseStrategy):
    def __init__(
        self,
        band_multiplier: float = 1.8,
        sl_buffer: float = 0.50,
        risk_reward_ratio: float = 2.0,
        target_vwap_mean: bool = True
    ):
        super().__init__(f"Golden_{band_multiplier}s_RR{risk_reward_ratio}")
        self.band_multiplier = band_multiplier
        self.sl_buffer = sl_buffer
        self.risk_reward_ratio = risk_reward_ratio
        self.target_vwap_mean = target_vwap_mean

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

        if len(self.engine.positions) > 0:
            self.bars_in_trade += 1
            if self.bars_in_trade >= 60:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
                self.bars_in_trade = 0
            return
        else:
            self.bars_in_trade = 0

        # Golden Window: 10:30 - 14:30 UTC
        is_window = (10, 30) <= (t.hour, t.minute) <= (14, 30)
        if not is_window or self.traded_today >= 2:
            return

        rng = gh - gl
        if rng < 0.35:
            return

        upper_wick = gh - max(go, gc)
        lower_wick = min(go, gc) - gl

        # Short Reversion
        if gh >= self.upper_band and (upper_wick / rng) >= 0.45 and gc < go:
            stop = round(gh + self.sl_buffer, 2)
            risk_dist = stop - gc
            if 0.80 <= risk_dist <= 5.00:
                tp = round(gc - (risk_dist * self.risk_reward_ratio), 2)
                if self.target_vwap_mean and self.current_vwap < gc and (gc - self.current_vwap) >= risk_dist * 1.5:
                    tp = round(self.current_vwap, 2)

                approval = self.governor.evaluate_entry(
                    entry_price=gc,
                    stop_loss=stop,
                    current_spread=spread,
                    max_allowed_spread=0.25,
                    num_open_positions=len(self.engine.positions)
                )
                if approval.approved:
                    pos_id = self.engine.sell("XAUUSD", approval.lots, stop, tp, comment="Short")
                    if pos_id:
                        self.traded_today += 1
                        return

        # Long Reversion
        if gl <= self.lower_band and (lower_wick / rng) >= 0.45 and gc > go:
            stop = round(gl - self.sl_buffer, 2)
            risk_dist = gc - stop
            if 0.80 <= risk_dist <= 5.00:
                tp = round(gc + (risk_dist * self.risk_reward_ratio), 2)
                if self.target_vwap_mean and self.current_vwap > gc and (self.current_vwap - gc) >= risk_dist * 1.5:
                    tp = round(self.current_vwap, 2)

                approval = self.governor.evaluate_entry(
                    entry_price=gc,
                    stop_loss=stop,
                    current_spread=spread,
                    max_allowed_spread=0.25,
                    num_open_positions=len(self.engine.positions)
                )
                if approval.approved:
                    pos_id = self.engine.buy("XAUUSD", approval.lots, stop, tp, comment="Long")
                    if pos_id:
                        self.traded_today += 1
                        return


def main():
    df = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")

    grid = [
        # (band, buffer, rr, target_mean)
        (1.6, 0.45, 2.0, True),
        (1.8, 0.35, 2.0, True),
        (1.8, 0.45, 2.0, True),
        (1.8, 0.50, 2.0, True),
        (1.8, 0.50, 2.5, True),
        (2.0, 0.45, 2.0, True),
        (2.0, 0.50, 2.5, True),
        (2.2, 0.50, 2.0, True),
        (1.8, 0.50, 2.0, False),  # Pure fixed RR without VWAP mean cap
        (1.8, 0.50, 2.5, False),
    ]

    results = []
    print(f"\n{'='*85}")
    print("🎯 FINE-TUNING GOLDEN WINDOW (10:30-14:30 UTC) PARAMETERS")
    print(f"{'='*85}\n")

    for band, buf, rr, tgt_mean in grid:
        strat = GoldenWindowSniper(band_multiplier=band, sl_buffer=buf, risk_reward_ratio=rr, target_vwap_mean=tgt_mean)
        config = AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0)
        engine = EventEngine(config=config, commission_model=CommissionModel(7.0), slippage_model=FixedSlippageModel(0.02))
        engine.reset()
        engine.current_strategy = strat
        strat.set_engine(engine)
        strat.on_init()

        for bar in df.iter_rows(named=True):
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
        for t in engine.closed_trades:
            monthly_pnl[t.open_time.strftime("%Y-%m")] += t.net_pnl
        pos_m = sum(1 for v in monthly_pnl.values() if v > 0)
        tot_m = len(monthly_pnl) or 1

        label = f"Band {band}s | Buf ${buf:.2f} | RR {rr:.1f} | MeanTgt: {tgt_mean}"
        print(f"[{label}] -> {perf.total_trades} trades, Win: {perf.win_rate_pct:.1f}%, Payoff: {perf.win_loss_ratio:.2f}x, Net: ${perf.net_profit:+,.2f}, PF: {perf.profit_factor:.2f}, DD: {perf.max_drawdown_pct:.1f}%, Months: {pos_m}/{tot_m}")
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

    results.sort(key=lambda x: x["net_pnl"], reverse=True)

    print(f"\n{'='*88}")
    print(f"{'Configuration':<48} | {'Trades':<6} | {'Win%':<6} | {'Payoff':<6} | {'Net PnL':<11} | {'PF':<5} | {'MaxDD':<6} | {'Months'}")
    print("-" * 88)
    for r in results:
        print(f"{r['label']:<48} | {r['trades']:<6} | {r['win_rate']:>5.1f}% | {r['payoff']:>5.2f}x | ${r['net_pnl']:>10,.2f} | {r['pf']:>4.2f} | {r['dd']:>5.1f}% | {r['months']}")
    print("="*88)


if __name__ == "__main__":
    main()
