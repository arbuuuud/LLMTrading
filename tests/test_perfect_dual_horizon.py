"""
Corrected Dual-Horizon Portfolio Simulation:
Strategies isolate their own position tracking using position tags:
- Scalper tracks `p.tag == 'VWAP_Mean_Reversion'`
- Intraday tracks `p.tag == 'Intraday_SMC'`
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
from engine.core.types import AccountConfig, ExitReason
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from engine.metrics.performance import PerformanceCalculator
from strategies.incubator.strat_3_anchored_vwap import SessionAnchoredVWAPStrategy
from strategies.incubator.strat_6_intraday_smc import IntradaySMCStrategy


class IsolatedScalper(SessionAnchoredVWAPStrategy):
    def on_bar(self, bar):
        # Override to check only own positions
        my_positions = [p for p in self.engine.positions.values() if p.tag == "VWAP_Mean_Reversion"]
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
            self.traded_today_count = 0

        tp_price = (gh + gl + gc) / 3.0
        self.cum_vol += vol
        self.cum_pv += tp_price * vol
        self.cum_p2v += (tp_price ** 2) * vol

        self.current_vwap = self.cum_pv / self.cum_vol
        variance = max(0.0, (self.cum_p2v / self.cum_vol) - (self.current_vwap ** 2))
        import math
        self.current_std = math.sqrt(variance)

        self.upper_band = self.current_vwap + (self.current_std * self.band_multiplier)
        self.lower_band = self.current_vwap - (self.current_std * self.band_multiplier)

        self.governor.on_new_bar(dt, self.engine.equity)

        if len(my_positions) > 0:
            self.bars_in_trade += 1
            if self.bars_in_trade >= self.max_bars_hold:
                for p in my_positions:
                    self.engine.close_position(p.position_id, ExitReason.TIME_EXPIRED)
                self.bars_in_trade = 0
            return
        else:
            self.bars_in_trade = 0

        is_trade_window = self.start_time <= (t.hour, t.minute) <= self.end_time
        if not is_trade_window or self.traded_today_count >= 2:
            return

        rng = gh - gl
        if rng < 0.35:
            return

        upper_wick = gh - max(go, gc)
        lower_wick = min(go, gc) - gl

        # Short
        if gh >= self.upper_band and (upper_wick / rng) >= 0.45 and gc < go:
            stop = round(gh + self.sl_buffer, 2)
            risk_dist = stop - gc
            if 0.80 <= risk_dist <= 5.00:
                tp = round(gc - (risk_dist * self.risk_reward_ratio), 2)
                if self.current_vwap < gc and (gc - self.current_vwap) >= risk_dist * 1.5:
                    tp = round(self.current_vwap, 2)

                approval = self.governor.evaluate_entry(gc, stop, spread, 0.25, len(my_positions))
                if approval.approved:
                    pid = self.engine.sell("XAUUSD", approval.lots, stop, tp, comment="VWAP_Upper_Fade", tag="VWAP_Mean_Reversion")
                    if pid:
                        self.traded_today_count += 1
                        return

        # Long
        if gl <= self.lower_band and (lower_wick / rng) >= 0.45 and gc > go:
            stop = round(gl - self.sl_buffer, 2)
            risk_dist = gc - stop
            if 0.80 <= risk_dist <= 5.00:
                tp = round(gc + (risk_dist * self.risk_reward_ratio), 2)
                if self.current_vwap > gc and (self.current_vwap - gc) >= risk_dist * 1.5:
                    tp = round(self.current_vwap, 2)

                approval = self.governor.evaluate_entry(gc, stop, spread, 0.25, len(my_positions))
                if approval.approved:
                    pid = self.engine.buy("XAUUSD", approval.lots, stop, tp, comment="VWAP_Lower_Fade", tag="VWAP_Mean_Reversion")
                    if pid:
                        self.traded_today_count += 1
                        return


def main():
    print("\n" + "="*85)
    print("🚀 RUNNING ISOLATED DUAL-HORIZON PORTFOLIO (ZERO CROSS-COLLISION)")
    print("="*85)

    df_m1 = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")

    config = AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0)
    engine = EventEngine(config=config, commission_model=CommissionModel(7.0), slippage_model=FixedSlippageModel(0.02))

    scalper = IsolatedScalper(
        band_multiplier=1.8,
        sl_buffer_dollars=0.50,
        risk_reward_ratio=2.0,
        start_hour=10,
        start_minute=30,
        end_hour=14,
        end_minute=30
    )
    scalper.set_engine(engine)
    scalper.on_init()

    intraday = IntradaySMCStrategy(base_risk_pct=0.50, tp1_r=1.5, tp2_r=4.0)
    intraday.set_engine(engine)
    intraday.on_init()

    current_m15 = None
    t0 = time.time()

    for bar in df_m1.iter_rows(named=True):
        engine.current_time = bar["timestamp"]
        spread = bar.get("mean_spread", 0.20)
        engine.current_bid = bar["close"]
        engine.current_ask = round(engine.current_bid + spread, 3)
        engine.current_spread = spread

        engine._check_daily_circuit_breaker(engine.current_time)
        engine._update_positions_on_bar(bar)

        scalper.on_bar(bar)

        dt = bar["timestamp"]
        m15_minute = (dt.minute // 15) * 15
        m15_time = dt.replace(minute=m15_minute, second=0, microsecond=0)

        if current_m15 is None or current_m15["timestamp"] != m15_time:
            if current_m15 is not None:
                intraday.on_bar(current_m15)
            current_m15 = {
                "timestamp": m15_time,
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "mean_spread": spread,
                "tick_volume": bar.get("tick_volume", 1)
            }
        else:
            current_m15["high"] = max(current_m15["high"], bar["high"])
            current_m15["low"] = min(current_m15["low"], bar["low"])
            current_m15["close"] = bar["close"]
            current_m15["tick_volume"] += bar.get("tick_volume", 1)

        engine.equity_curve.append({
            "timestamp": engine.current_time,
            "equity": round(engine.equity, 2),
            "balance": round(engine.balance, 2)
        })

    if current_m15 is not None:
        intraday.on_bar(current_m15)

    for pos_id in list(engine.positions.keys()):
        engine._close_position_internal(pos_id, ExitReason.END_OF_DATA)

    scalper.on_finish()
    intraday.on_finish()
    elapsed = time.time() - t0

    perf = PerformanceCalculator.calculate(engine.closed_trades, engine.equity_curve, config.initial_balance)

    scalp_trades = [t for t in engine.closed_trades if "VWAP" in (t.comment or "") or "VWAP" in (t.tag or "")]
    intra_trades = [t for t in engine.closed_trades if "Intra" in (t.comment or "")]

    scalp_pnl = sum(t.net_pnl for t in scalp_trades)
    intra_pnl = sum(t.net_pnl for t in intra_trades)

    monthly_pnl = defaultdict(float)
    for tr in engine.closed_trades:
        monthly_pnl[tr.open_time.strftime("%Y-%m")] += tr.net_pnl

    pos_m = sum(1 for v in monthly_pnl.values() if v > 0)
    tot_m = len(monthly_pnl) or 1

    print("\n" + "="*85)
    print("🏆 PERFECT DUAL-HORIZON PORTFOLIO RESULTS (10.5 MONTHS XAUUSD)")
    print("="*85)
    print(f"⏱ Simulation Time: {elapsed:.2f}s")
    print(f"📊 Total Combined Trades: {perf.total_trades}")
    print(f"   -> 🎯 Scalper M1 Trades: {len(scalp_trades)} (Net PnL: ${scalp_pnl:+,.2f})")
    print(f"   -> 🏹 Intraday M15 Trades: {len(intra_trades)} (Net PnL: ${intra_pnl:+,.2f})")
    print(f"💰 Combined Net Profit: ${perf.net_profit:+,.2f}")
    print(f"📈 Combined Profit Factor: {perf.profit_factor:.2f}")
    print(f"🛡 Combined Max Drawdown: {perf.max_drawdown_pct:.1f}%")
    print(f"🎯 Win Rate: {perf.win_rate_pct:.1f}%")
    print(f"⚖️ Payoff Ratio: {perf.win_loss_ratio:.2f}x")
    print(f"📆 Profitable Months: {pos_m} / {tot_m} ({pos_m/tot_m*100:.0f}%)")
    print("="*85)

    print("\nMonthly PnL Breakdown (Combined Portfolio):")
    for m in sorted(monthly_pnl.keys()):
        print(f"  {m}: ${monthly_pnl[m]:+8.2f}")


if __name__ == "__main__":
    main()
