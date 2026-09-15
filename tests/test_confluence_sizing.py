"""
Test Confluence-Weighted Position Sizing:
When VWAP +/- 1.8s setup occurs:
- If NO HTF POI is present: Trade normal base risk (0.50%).
- If HTF POI (OB, FVG, or iFVG) IS present: Size up with High-Conviction (0.75% or 1.00% risk).
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
from strategies.modules.setups.ifvg_detector import InversionFVGDetector


class ConfluenceSizingStrategy(BaseStrategy):
    def __init__(
        self,
        base_risk_pct: float = 0.50,
        poi_boost_multiplier: float = 1.5,  # 0.50% * 1.5 = 0.75% risk on POI confluence
        poi_buffer_dollars: float = 1.50
    ):
        super().__init__(f"ConfluenceSizing_Boost_{poi_boost_multiplier}x")
        self.base_risk_pct = base_risk_pct
        self.poi_boost = poi_boost_multiplier
        self.poi_buffer = poi_buffer_dollars

        self.governor = MonthlyRatchetGovernor(
            base_risk_pct=base_risk_pct,
            greed_risk_pct=0.25,
            max_daily_loss_pct=1.0,
            monthly_loss_cap_pct=3.0,
            cooldown_bars=25
        )

        self.current_m15_bar = None
        self.m15_history = []
        self.ifvg_detector = InversionFVGDetector(min_fvg_size_dollars=0.40)
        self.active_ifvgs = []
        self.active_obs = []

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
        self.m15_history.clear()
        self.active_ifvgs.clear()
        self.active_obs.clear()

    def on_trade_closed(self, trade_record):
        self.governor.on_trade_closed(trade_record.net_pnl)

    def _update_m15(self, m1_bar):
        dt = m1_bar["timestamp"]
        m15_minute = (dt.minute // 15) * 15
        m15_time = dt.replace(minute=m15_minute, second=0, microsecond=0)

        if self.current_m15_bar is None or self.current_m15_bar["timestamp"] != m15_time:
            if self.current_m15_bar is not None:
                self.m15_history.append(self.current_m15_bar)
                if len(self.m15_history) > 60:
                    self.m15_history.pop(0)

                self.ifvg_detector.update(self.current_m15_bar)
                self.active_ifvgs = self.ifvg_detector.get_active_ifvg_zones()

                # Detect OB
                if len(self.m15_history) >= 5:
                    last = self.m15_history[-1]
                    prev_h = [b["high"] for b in self.m15_history[-5:-1]]
                    prev_l = [b["low"] for b in self.m15_history[-5:-1]]
                    if last["high"] > max(prev_h) and last["close"] > last["open"]:
                        for b in reversed(self.m15_history[-5:-1]):
                            if b["close"] < b["open"]:
                                self.active_obs.append({"type": "BULLISH_OB", "top": b["high"], "bottom": b["low"]})
                                break
                    if last["low"] < min(prev_l) and last["close"] < last["open"]:
                        for b in reversed(self.m15_history[-5:-1]):
                            if b["close"] > b["open"]:
                                self.active_obs.append({"type": "BEARISH_OB", "top": b["high"], "bottom": b["low"]})
                                break
                    if len(self.active_obs) > 20:
                        self.active_obs = self.active_obs[-20:]

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

    def _has_poi_confluence(self, price: float, direction: str) -> bool:
        buf = self.poi_buffer
        if direction == "SELL":
            # Check Bearish OB or Bearish iFVG
            ob_hit = any((ob["bottom"] - buf) <= price <= (ob["top"] + buf) for ob in self.active_obs if ob["type"] == "BEARISH_OB")
            ifvg_hit = any((z["bottom"] - buf) <= price <= (z["top"] + buf) for z in self.active_ifvgs if z["type"] == "BEARISH_IFVG")
            return ob_hit or ifvg_hit
        else:
            # Check Bullish OB or Bullish iFVG
            ob_hit = any((ob["bottom"] - buf) <= price <= (ob["top"] + buf) for ob in self.active_obs if ob["type"] == "BULLISH_OB")
            ifvg_hit = any((z["bottom"] - buf) <= price <= (z["top"] + buf) for z in self.active_ifvgs if z["type"] == "BULLISH_IFVG")
            return ob_hit or ifvg_hit

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

        self.upper_band = self.current_vwap + (self.current_std * 1.8)
        self.lower_band = self.current_vwap - (self.current_std * 1.8)

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
            stop = round(gh + 0.50, 2)
            risk_dist = stop - gc
            if 0.80 <= risk_dist <= 5.00:
                tp = round(gc - (risk_dist * 2.0), 2)
                if self.current_vwap < gc and (gc - self.current_vwap) >= risk_dist * 1.5:
                    tp = round(self.current_vwap, 2)

                has_poi = self._has_poi_confluence(gh, "SELL")
                # Dynamic lot sizing: boost if POI confluence
                risk_pct = self.base_risk_pct * (self.poi_boost if has_poi else 1.0)
                risk_amt = self.engine.equity * (risk_pct / 100.0)
                lots = round(max(0.01, risk_amt / (risk_dist * 100.0)), 2)

                pos_id = self.engine.sell("XAUUSD", lots, stop, tp, comment=f"Short_POI_{has_poi}")
                if pos_id:
                    self.traded_today += 1
                    return

        # Long Reversion
        if gl <= self.lower_band and (lower_wick / rng) >= 0.45 and gc > go:
            stop = round(gl - 0.50, 2)
            risk_dist = gc - stop
            if 0.80 <= risk_dist <= 5.00:
                tp = round(gc + (risk_dist * 2.0), 2)
                if self.current_vwap > gc and (self.current_vwap - gc) >= risk_dist * 1.5:
                    tp = round(self.current_vwap, 2)

                has_poi = self._has_poi_confluence(gl, "BUY")
                risk_pct = self.base_risk_pct * (self.poi_boost if has_poi else 1.0)
                risk_amt = self.engine.equity * (risk_pct / 100.0)
                lots = round(max(0.01, risk_amt / (risk_dist * 100.0)), 2)

                pos_id = self.engine.buy("XAUUSD", lots, stop, tp, comment=f"Long_POI_{has_poi}")
                if pos_id:
                    self.traded_today += 1
                    return


def main():
    df = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")

    boosts = [1.0, 1.25, 1.5, 1.75, 2.0]
    print(f"\n{'='*85}")
    print("💎 TESTING CONFLUENCE-WEIGHTED SIZING (POI BOOST) IN GOLDEN WINDOW")
    print(f"{'='*85}\n")

    results = []
    for b in boosts:
        strat = ConfluenceSizingStrategy(base_risk_pct=0.50, poi_boost_multiplier=b)
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

        label = f"Flat Sizing (1.0x)" if b == 1.0 else f"POI Boost {b:.2f}x ({0.50*b:.2f}% risk on POI)"
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

    print(f"\n{'='*85}")
    print(f"{'Sizing Strategy':<45} | {'Trades':<6} | {'Win%':<6} | {'Payoff':<6} | {'Net PnL':<11} | {'PF':<5} | {'MaxDD':<6} | {'Months'}")
    print("-" * 85)
    for r in results:
        print(f"{r['label']:<45} | {r['trades']:<6} | {r['win_rate']:>5.1f}% | {r['payoff']:>5.2f}x | ${r['net_pnl']:>10,.2f} | {r['pf']:>4.2f} | {r['dd']:>5.1f}% | {r['months']}")
    print("="*85)


if __name__ == "__main__":
    main()
