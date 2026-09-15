"""
Hybrid Synthesis: Fadli NFC Unfilled Orders + Fibonacci Golden Pocket + Macro H1 EMA Filter.
Tests the confluence of Indonesian Institutional Setup with Quantitative Macro Filters.
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
from strategies.modules.setups.fibonacci_confluence import FibonacciCalculator

df_m15 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_M15.parquet")
df_h1 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_H1.parquet")

# Precompute H1 EMA 50
df_h1 = df_h1.with_columns([
    pl.col("close").ewm_mean(span=50).alias("ema50"),
    (pl.col("high") - pl.col("low")).rolling_mean(window_size=14).alias("atr14")
])
h1_map = {
    row["timestamp"]: {"close": row["close"], "ema50": row["ema50"], "atr14": row["atr14"] or 5.0}
    for row in df_h1.iter_rows(named=True)
}


class NFCFiboHybridStrategy(BaseStrategy):
    def __init__(self, rr_target=3.0, use_macro_ema=True, use_fibo_ote=True):
        super().__init__(f"NFC_Fibo_RR{rr_target}")
        self.rr_target = rr_target
        self.use_macro_ema = use_macro_ema
        self.use_fibo_ote = use_fibo_ote
        self.governor = MonthlyRatchetGovernor(base_risk_pct=0.5, greed_risk_pct=0.25, max_daily_loss_pct=1.0, monthly_loss_cap_pct=3.0, cooldown_bars=8)

        self.bars = []
        self.demand_zones = []
        self.supply_zones = []
        self.current_date = None
        self.traded_today = 0

    def on_init(self):
        self.bars.clear()
        self.demand_zones.clear()
        self.supply_zones.clear()
        self.current_date = None
        self.traded_today = 0

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
        if len(self.bars) > 60:
            self.bars.pop(0)

        if self.current_date != d:
            self.current_date = d
            self.traded_today = 0

        self.governor.on_new_bar(dt, self.engine.equity)

        # Detect DBR / RBD
        if len(self.bars) >= 5:
            b_drop = self.bars[-4]
            b_base = self.bars[-3]
            b_rally = self.bars[-1]

            # DBR
            if (b_drop["close"] < b_drop["open"]) and (b_rally["close"] > b_rally["open"]):
                rally_body = b_rally["close"] - b_rally["open"]
                base_range = b_base["high"] - b_base["low"]
                if rally_body > base_range * 1.5 and rally_body > 2.5:
                    self.demand_zones.append({
                        "top": b_base["high"], "bottom": b_base["low"],
                        "created_at": b_base["timestamp"], "mitigated": False
                    })

            # RBD
            if (b_drop["close"] > b_drop["open"]) and (b_rally["close"] < b_rally["open"]):
                drop_body = b_rally["open"] - b_rally["close"]
                base_range = b_base["high"] - b_base["low"]
                if drop_body > base_range * 1.5 and drop_body > 2.5:
                    self.supply_zones.append({
                        "top": b_base["high"], "bottom": b_base["low"],
                        "created_at": b_base["timestamp"], "mitigated": False
                    })

            if len(self.demand_zones) > 20: self.demand_zones = self.demand_zones[-20:]
            if len(self.supply_zones) > 20: self.supply_zones = self.supply_zones[-20:]

        if len(self.engine.positions) > 0:
            if t.hour >= 21 and t.minute >= 30:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
            return

        if not ((8, 0) <= (t.hour, t.minute) <= (16, 30)) or self.traded_today >= 1:
            return

        # Macro Context
        h1 = self._get_h1(dt)
        is_bull_macro = True
        is_bear_macro = True
        fibo = None

        if h1 is not None and self.use_macro_ema:
            c_h1 = h1["close"]
            ema_h1 = h1["ema50"]
            is_bull_macro = (c_h1 >= ema_h1)
            is_bear_macro = (c_h1 <= ema_h1)

        # Fibo on recent 20 M15 bars
        if len(self.bars) >= 20 and self.use_fibo_ote:
            recent_h = max(b["high"] for b in self.bars[-20:])
            recent_l = min(b["low"] for b in self.bars[-20:])
            if is_bull_macro:
                fibo = FibonacciCalculator.compute_bullish_fibo(recent_l, recent_h)
            elif is_bear_macro:
                fibo = FibonacciCalculator.compute_bearish_fibo(recent_h, recent_l)

        # Retest Demand (BUY)
        if is_bull_macro:
            for z in reversed(self.demand_zones):
                if not z["mitigated"] and (z["bottom"] - 0.5) <= gl <= (z["top"] + 0.5) and gc > go:
                    # Fibo check
                    if self.use_fibo_ote and fibo:
                        if not FibonacciCalculator.is_in_golden_pocket(gl, fibo, buffer=0.60):
                            continue

                    z["mitigated"] = True
                    sl = round(z["bottom"] - 1.20, 2)
                    risk = gc - sl
                    if 1.50 <= risk <= 6.50:
                        tp = round(gc + risk * self.rr_target, 2)
                        approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                        if approval.approved:
                            self.engine.buy("XAUUSD", approval.lots, sl, tp, comment="NFC_Fibo_Buy")
                            self.traded_today += 1
                            return

        # Retest Supply (SELL)
        if is_bear_macro:
            for z in reversed(self.supply_zones):
                if not z["mitigated"] and (z["bottom"] - 0.5) <= gh <= (z["top"] + 0.5) and gc < go:
                    if self.use_fibo_ote and fibo:
                        if not FibonacciCalculator.is_in_golden_pocket(gh, fibo, buffer=0.60):
                            continue

                    z["mitigated"] = True
                    sl = round(z["top"] + 1.20, 2)
                    risk = sl - gc
                    if 1.50 <= risk <= 6.50:
                        tp = round(gc - risk * self.rr_target, 2)
                        approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                        if approval.approved:
                            self.engine.sell("XAUUSD", approval.lots, sl, tp, comment="NFC_Fibo_Sell")
                            self.traded_today += 1
                            return


def main():
    print("=" * 105)
    print("🔬 TESTING HYBRID FADLI NFC + FIBONACCI GOLDEN POCKET + H1 EMA 50")
    print("=" * 105)

    experiments = [
        ("1. Pure Fadli NFC (Unfilled Base Only)", False, False, 2.5),
        ("2. Fadli NFC + H1 EMA 50 Macro Filter", True, False, 2.5),
        ("3. Fadli NFC + H1 EMA 50 + Fibo Golden Pocket (RR 2.5)", True, True, 2.5),
        ("4. Fadli NFC + H1 EMA 50 + Fibo Golden Pocket (RR 3.5)", True, True, 3.5),
        ("5. Fadli NFC + H1 EMA 50 + Fibo Golden Pocket (RR 4.0)", True, True, 4.0),
    ]

    results = []
    for label, use_ema, use_fibo, rr in experiments:
        t0 = time.time()
        strat = NFCFiboHybridStrategy(rr_target=rr, use_macro_ema=use_ema, use_fibo_ote=use_fibo)
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
        elapsed = time.time() - t0

        monthly = defaultdict(float)
        for tr in e.closed_trades:
            monthly[tr.open_time.strftime("%Y-%m")] += tr.net_pnl
        pos_m = sum(1 for v in monthly.values() if v > 0)
        tot_m = len(monthly) or 1

        print(f"[{label:<55}] in {elapsed:.1f}s -> Trades: {perf.total_trades:2d} | Win: {perf.win_rate_pct:>5.1f}% | Payoff: {perf.win_loss_ratio:>4.2f}x | Net: ${perf.net_profit:>10,.2f} | PF: {perf.profit_factor:>4.2f} | DD: {perf.max_drawdown_pct:>4.1f}% | Months: {pos_m}/{tot_m}")
        results.append({
            "name": label,
            "trades": perf.total_trades,
            "win_rate": round(perf.win_rate_pct, 1),
            "payoff": round(perf.win_loss_ratio, 2),
            "net_pnl": round(perf.net_profit, 2),
            "pf": round(perf.profit_factor, 2),
            "max_dd": round(perf.max_drawdown_pct, 1),
            "months": f"{pos_m}/{tot_m}"
        })

    print("\n" + "=" * 105)
    print("🏆 FINAL COMPARATIVE SCOREBOARD")
    print("=" * 105)
    for r in results:
        print(f"{r['name']:<55} | Trades: {r['trades']:<4} | Win: {r['win_rate']:>5.1f}% | Payoff: {r['payoff']:>4.2f}x | Net: ${r['net_pnl']:>10,.2f} | PF: {r['pf']:>4.2f} | DD: {r['max_dd']:>4.1f}%")


if __name__ == "__main__":
    main()
