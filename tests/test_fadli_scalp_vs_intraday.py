"""
Empirical Comparison: Is Fadli (NFC) Unfilled Orders Better at Scalping or Intraday?
Tests the exact same Supply & Demand Base (DBR/RBD) logic across 4 timeframes:
1. M1 Scalping (Fast execution, 5-30m hold)
2. M5 Scalping (Intraday scalping, 15-60m hold)
3. M15 Intraday (Classic intraday, 1-4h hold)
4. H1 Intraday/Swing (Multi-hour/multi-day hold)

Tested on full 10.5-month continuous XAUUSD dataset.
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

import os
if not os.path.exists("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet"):
    raise unittest.SkipTest("Parquet historical dataset not found on server; skipping backtest test.")

print("[Naruto Brain] Preloading Parquet datasets for Fadli Scalping vs Intraday...")
df_m1 = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")
df_m5 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_M5.parquet")
df_m15 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_M15.parquet")
df_h1 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_H1.parquet")

# Precompute H1 and H4 EMA 50 for trend context
df_h1 = df_h1.with_columns([
    pl.col("close").ewm_mean(span=50).alias("ema50")
])
h1_ema_map = {row["timestamp"]: row["ema50"] for row in df_h1.iter_rows(named=True)}


class FadliTimeframeBenchmark(BaseStrategy):
    def __init__(
        self,
        timeframe: str,          # "M1", "M5", "M15", "H1"
        rr_target: float = 2.5,
        min_body_ratio: float = 1.5,
        min_move_dollars: float = 2.0,
        sl_buffer_dollars: float = 1.0,
        max_hold_bars: int = 40,
        use_macro_filter: bool = True
    ):
        super().__init__(f"Fadli_{timeframe}")
        self.timeframe = timeframe
        self.rr_target = rr_target
        self.min_body_ratio = min_body_ratio
        self.min_move_dollars = min_move_dollars
        self.sl_buffer = sl_buffer_dollars
        self.max_hold_bars = max_hold_bars
        self.use_macro_filter = use_macro_filter

        self.governor = MonthlyRatchetGovernor(
            base_risk_pct=0.5,
            greed_risk_pct=0.25,
            max_daily_loss_pct=1.0,
            monthly_loss_cap_pct=3.0,
            cooldown_bars=5
        )

        self.bars = []
        self.demand_zones = []
        self.supply_zones = []
        self.current_date = None
        self.traded_today = 0
        self.bars_in_trade = 0

    def on_init(self):
        self.bars.clear()
        self.demand_zones.clear()
        self.supply_zones.clear()
        self.current_date = None
        self.traded_today = 0
        self.bars_in_trade = 0

    def _get_h1_ema(self, dt):
        t = dt.replace(minute=0, second=0, microsecond=0)
        return h1_ema_map.get(t, None)

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
            self.bars_in_trade = 0

        self.governor.on_new_bar(dt, self.engine.equity)

        # Detect DBR / RBD bases
        if len(self.bars) >= 5:
            b_drop = self.bars[-4]
            b_base = self.bars[-3]
            b_rally = self.bars[-1]

            # DBR (Drop -> Base -> Explosive Rally)
            if (b_drop["close"] < b_drop["open"]) and (b_rally["close"] > b_rally["open"]):
                rally_body = b_rally["close"] - b_rally["open"]
                base_range = b_base["high"] - b_base["low"]
                if rally_body > base_range * self.min_body_ratio and rally_body >= self.min_move_dollars:
                    self.demand_zones.append({
                        "top": b_base["high"],
                        "bottom": b_base["low"],
                        "created_at": b_base["timestamp"],
                        "mitigated": False
                    })

            # RBD (Rally -> Base -> Explosive Drop)
            if (b_drop["close"] > b_drop["open"]) and (b_rally["close"] < b_rally["open"]):
                drop_body = b_rally["open"] - b_rally["close"]
                base_range = b_base["high"] - b_base["low"]
                if drop_body > base_range * self.min_body_ratio and drop_body >= self.min_move_dollars:
                    self.supply_zones.append({
                        "top": b_base["high"],
                        "bottom": b_base["low"],
                        "created_at": b_base["timestamp"],
                        "mitigated": False
                    })

            if len(self.demand_zones) > 25: self.demand_zones = self.demand_zones[-25:]
            if len(self.supply_zones) > 25: self.supply_zones = self.supply_zones[-25:]

        # Position management
        if len(self.engine.positions) > 0:
            self.bars_in_trade += 1
            if self.bars_in_trade >= self.max_hold_bars or (t.hour >= 21 and t.minute >= 30):
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
                self.bars_in_trade = 0
            return
        else:
            self.bars_in_trade = 0

        # Session trading window: 08:00 - 16:30 UTC
        max_trades = 3 if self.timeframe in ("M1", "M5") else 1
        if not ((8, 0) <= (t.hour, t.minute) <= (16, 30)) or self.traded_today >= max_trades:
            return

        # Macro Trend Context
        h1_ema = self._get_h1_ema(dt)
        is_bull_macro = True
        is_bear_macro = True
        if self.use_macro_filter and h1_ema is not None:
            is_bull_macro = (gc >= h1_ema)
            is_bear_macro = (gc <= h1_ema)

        # Retest Demand (BUY)
        if is_bull_macro:
            for z in reversed(self.demand_zones):
                if not z["mitigated"] and (z["bottom"] - 0.4) <= gl <= (z["top"] + 0.4) and gc > go:
                    z["mitigated"] = True
                    sl = round(z["bottom"] - self.sl_buffer, 2)
                    risk = gc - sl
                    min_r = 0.80 if self.timeframe == "M1" else 1.20
                    max_r = 4.00 if self.timeframe == "M1" else 8.00
                    if min_r <= risk <= max_r:
                        tp = round(gc + risk * self.rr_target, 2)
                        approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                        if approval.approved:
                            self.engine.buy("XAUUSD", approval.lots, sl, tp, comment=f"Fadli_{self.timeframe}_Buy")
                            self.traded_today += 1
                            self.bars_in_trade = 0
                            return

        # Retest Supply (SELL)
        if is_bear_macro:
            for z in reversed(self.supply_zones):
                if not z["mitigated"] and (z["bottom"] - 0.4) <= gh <= (z["top"] + 0.4) and gc < go:
                    z["mitigated"] = True
                    sl = round(z["top"] + self.sl_buffer, 2)
                    risk = sl - gc
                    min_r = 0.80 if self.timeframe == "M1" else 1.20
                    max_r = 4.00 if self.timeframe == "M1" else 8.00
                    if min_r <= risk <= max_r:
                        tp = round(gc - risk * self.rr_target, 2)
                        approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                        if approval.approved:
                            self.engine.sell("XAUUSD", approval.lots, sl, tp, comment=f"Fadli_{self.timeframe}_Sell")
                            self.traded_today += 1
                            self.bars_in_trade = 0
                            return


def run_benchmark(label, strat, df):
    t0 = time.time()
    c = AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0)
    e = EventEngine(config=c, commission_model=CommissionModel(7.0), slippage_model=FixedSlippageModel(0.02))
    e.reset()
    e.current_strategy = strat
    strat.set_engine(e)
    strat.on_init()

    for bar in df.iter_rows(named=True):
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

    print(f"[{label:<48}] in {elapsed:.1f}s -> Trades: {perf.total_trades:3d} | Win: {perf.win_rate_pct:>5.1f}% | Payoff: {perf.win_loss_ratio:>4.2f}x | Net: ${perf.net_profit:>10,.2f} | PF: {perf.profit_factor:>4.2f} | DD: {perf.max_drawdown_pct:>4.1f}% | Months: {pos_m}/{tot_m}")
    return {
        "name": label,
        "trades": perf.total_trades,
        "win_rate": round(perf.win_rate_pct, 1),
        "payoff": round(perf.win_loss_ratio, 2),
        "net_pnl": round(perf.net_profit, 2),
        "pf": round(perf.profit_factor, 2),
        "max_dd": round(perf.max_drawdown_pct, 1),
        "months": f"{pos_m}/{tot_m}",
        "monthly_pnl": dict(monthly)
    }


def main():
    print("=" * 110)
    print("🔬 AUDIT HORIZON FADLI (NFC): SCALPING (M1/M5) vs INTRADAY (M15/H1)")
    print("=" * 110)

    configs = [
        # Scalping Horizons
        ("1. Fadli M1 Scalping (Fast Base, 30m max hold)",
         FadliTimeframeBenchmark("M1", min_body_ratio=1.5, min_move_dollars=1.20, sl_buffer_dollars=0.50, max_hold_bars=30), df_m1),
        
        ("2. Fadli M5 Scalping (Intraday Scalp, 45m hold)",
         FadliTimeframeBenchmark("M5", min_body_ratio=1.5, min_move_dollars=2.00, sl_buffer_dollars=0.80, max_hold_bars=15), df_m5),

        # Intraday Horizons
        ("3. Fadli M15 Intraday (Standard Base, 3h hold)",
         FadliTimeframeBenchmark("M15", min_body_ratio=1.5, min_move_dollars=2.50, sl_buffer_dollars=1.20, max_hold_bars=16), df_m15),

        ("4. Fadli H1 Intraday / Swing (Macro Base, 8h hold)",
         FadliTimeframeBenchmark("H1", min_body_ratio=1.5, min_move_dollars=5.00, sl_buffer_dollars=2.50, max_hold_bars=12), df_h1),
    ]

    results = []
    for label, strat, df in configs:
        res = run_benchmark(label, strat, df)
        results.append(res)

    print("\n" + "=" * 110)
    print("🏆 HASIL EVALUASI HORIZON FADLI NFC: MANA YANG PALING MENGUNTUNGKAN?")
    print("=" * 110)
    header = f"{'Rank':<5} | {'Horizon & Timeframe':<50} | {'Trades':<6} | {'Win%':<6} | {'Payoff':<6} | {'Net PnL':<11} | {'PF':<5} | {'MaxDD':<6} | {'Months'}"
    print(header)
    print("-" * 110)
    results.sort(key=lambda x: (x["net_pnl"], x["pf"]), reverse=True)
    for rank, r in enumerate(results, 1):
        print(f"#{rank:<4} | {r['name']:<50} | {r['trades']:<6} | {r['win_rate']:>5.1f}% | {r['payoff']:>5.2f}x | ${r['net_pnl']:>10,.2f} | {r['pf']:>4.2f} | {r['max_dd']:>5.1f}% | {r['months']}")
    print("=" * 110)


if __name__ == "__main__":
    main()
