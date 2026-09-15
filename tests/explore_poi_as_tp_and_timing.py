"""
Exploration of Scenario 3b & 4:
1. High-Resolution Session Time Window Analysis:
   Find the exact institutional sweet spot for XAUUSD Mean Reversion.
2. POI as Magnet / Dynamic TP:
   Instead of filtering entries, use HTF Inversion FVG / OB as Take Profit magnets.
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
from agents.risk_manager.monthly_ratchet_governor import MonthlyRatchetGovernor, RatchetApproval
from engine.core.strategy_base import BaseStrategy
from strategies.modules.setups.ifvg_detector import InversionFVGDetector


class DynamicWindowAndPOIStrategy(BaseStrategy):
    def __init__(
        self,
        start_hour: int = 8,
        start_min: int = 0,
        end_hour: int = 14,
        end_min: int = 30,
        band_multiplier: float = 1.8,
        sl_buffer: float = 0.50,
        use_poi_dynamic_tp: bool = False
    ):
        super().__init__(f"VWAP_{start_hour:02d}{start_min:02d}_{end_hour:02d}{end_min:02d}")
        self.start_time = (start_hour, start_min)
        self.end_time = (end_hour, end_min)
        self.band_multiplier = band_multiplier
        self.sl_buffer = sl_buffer
        self.use_poi_dynamic_tp = use_poi_dynamic_tp

        self.governor = MonthlyRatchetGovernor(
            base_risk_pct=0.5,
            greed_risk_pct=0.25,
            max_daily_loss_pct=1.0,
            monthly_loss_cap_pct=3.0,
            cooldown_bars=25
        )

        self.current_m15_bar = None
        self.ifvg_detector = InversionFVGDetector(min_fvg_size_dollars=0.40)
        self.active_ifvgs = []

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
        self.current_m15_bar = None
        self.active_ifvgs.clear()

    def on_trade_closed(self, trade_record):
        self.governor.on_trade_closed(trade_record.net_pnl)

    def _update_m15(self, m1_bar):
        dt = m1_bar["timestamp"]
        m15_minute = (dt.minute // 15) * 15
        m15_time = dt.replace(minute=m15_minute, second=0, microsecond=0)

        if self.current_m15_bar is None or self.current_m15_bar["timestamp"] != m15_time:
            if self.current_m15_bar is not None:
                self.ifvg_detector.update(self.current_m15_bar)
                self.active_ifvgs = self.ifvg_detector.get_active_ifvg_zones()

            self.current_m15_bar = {
                "timestamp": m15_time,
                "open": m1_bar["open"],
                "high": m1_bar["high"],
                "low": m1_bar["low"],
                "close": m1_bar["close"],
                "tick_volume": m1_bar.get("tick_volume", 1)
            }
        else:
            self.current_m15_bar["high"] = max(self.current_m15_bar["high"], m1_bar["high"])
            self.current_m15_bar["low"] = min(self.current_m15_bar["low"], m1_bar["low"])
            self.current_m15_bar["close"] = m1_bar["close"]
            self.current_m15_bar["tick_volume"] += m1_bar.get("tick_volume", 1)

    def on_bar(self, bar):
        dt = bar["timestamp"]
        d = dt.date()
        t = dt.time()

        gh, gl, gc, go = bar["high"], bar["low"], bar["close"], bar["open"]
        vol = max(1.0, float(bar.get("tick_volume", 1)))
        spread = bar.get("mean_spread", 0.20)

        self._update_m15(bar)

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

        is_window = self.start_time <= (t.hour, t.minute) <= self.end_time
        if not is_window or self.traded_today >= 2:
            return

        rng = gh - gl
        if rng < 0.35:
            return

        upper_wick = gh - max(go, gc)
        lower_wick = min(go, gc) - gl

        # BEARISH MEAN REVERSION
        if gh >= self.upper_band and (upper_wick / rng) >= 0.45 and gc < go:
            stop = round(gh + self.sl_buffer, 2)
            risk_dist = stop - gc
            if 0.80 <= risk_dist <= 5.00:
                # Default TP is VWAP mean or 2.0x RR
                tp = round(gc - (risk_dist * 2.0), 2)
                if self.current_vwap < gc and (gc - self.current_vwap) >= risk_dist * 1.5:
                    tp = round(self.current_vwap, 2)

                # If POI dynamic TP is active, check if there's a Bullish iFVG below as target magnet
                if self.use_poi_dynamic_tp:
                    targets = [z["top"] for z in self.active_ifvgs if z["top"] < gc and (gc - z["top"]) >= risk_dist * 1.8]
                    if targets:
                        tp = round(max(targets), 2)  # Nearest valid POI magnet below

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

        # BULLISH MEAN REVERSION
        if gl <= self.lower_band and (lower_wick / rng) >= 0.45 and gc > go:
            stop = round(gl - self.sl_buffer, 2)
            risk_dist = gc - stop
            if 0.80 <= risk_dist <= 5.00:
                tp = round(gc + (risk_dist * 2.0), 2)
                if self.current_vwap > gc and (self.current_vwap - gc) >= risk_dist * 1.5:
                    tp = round(self.current_vwap, 2)

                # If POI dynamic TP is active, check if there's a Bearish iFVG above as target magnet
                if self.use_poi_dynamic_tp:
                    targets = [z["bottom"] for z in self.active_ifvgs if z["bottom"] > gc and (z["bottom"] - gc) >= risk_dist * 1.8]
                    if targets:
                        tp = round(min(targets), 2)  # Nearest valid POI magnet above

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


def test_variations():
    df = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")

    experiments = [
        # (Label, start_h, start_m, end_h, end_m, poi_tp)
        ("Baseline (08:00-16:00, Standard TP)", 8, 0, 16, 0, False),
        ("Cut 15:00-16:00 (08:00-14:45, Standard TP)", 8, 0, 14, 45, False),
        ("Cut 15:00-16:00 + POI Magnet TP (08:00-14:45)", 8, 0, 14, 45, True),
        ("Pure London + Early NY (09:00-14:30, Standard TP)", 9, 0, 14, 30, False),
        ("Pure London + Early NY + POI Magnet TP", 9, 0, 14, 30, True),
        ("High-Volume Core Only (10:30-14:30, Standard TP)", 10, 30, 14, 30, False),
        ("High-Volume Core + POI Magnet TP", 10, 30, 14, 30, True),
    ]

    print(f"\n{'='*85}")
    print("🔬 TESTING TIME-WINDOW & POI DYNAMIC TP COMBINATIONS (300,440 BARS)")
    print(f"{'='*85}\n")

    results = []
    for label, sh, sm, eh, em, poi_tp in experiments:
        t0 = time.time()
        strat = DynamicWindowAndPOIStrategy(sh, sm, eh, em, band_multiplier=1.8, use_poi_dynamic_tp=poi_tp)
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

        elapsed = time.time() - t0
        print(f"[{label}] {elapsed:.1f}s -> {perf.total_trades} trades, Win: {perf.win_rate_pct:.1f}%, Payoff: {perf.win_loss_ratio:.2f}x, Net: ${perf.net_profit:+,.2f}, PF: {perf.profit_factor:.2f}, DD: {perf.max_drawdown_pct:.1f}%, Months: {pos_m}/{tot_m}")
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

    print(f"\n{'='*85}")
    print(f"{'Configuration':<46} | {'Trades':<6} | {'Win%':<6} | {'Payoff':<6} | {'Net PnL':<11} | {'PF':<5} | {'MaxDD':<6} | {'Months'}")
    print("-" * 85)
    for r in results:
        print(f"{r['label']:<46} | {r['trades']:<6} | {r['win_rate']:>5.1f}% | {r['payoff']:>5.2f}x | ${r['net_pnl']:>10,.2f} | {r['pf']:>4.2f} | {r['dd']:>5.1f}% | {r['months']}")
    print("="*85)


if __name__ == "__main__":
    test_variations()
