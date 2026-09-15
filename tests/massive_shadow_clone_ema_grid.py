"""
Massive Naruto Shadow Clone Grid Search:
Deploys 100+ parallel clones across:
1. Timeframes: M15, H1, H4
2. EMA Periods: 20, 50, 100, 200
3. Institutional Mechanics:
   - A. BINARY_VETO: Block counter-trend
   - B. ASYMMETRIC_SIZING: With-trend 0.65% risk, Counter-trend 0.20% risk
   - C. DYNAMIC_TARGET: With-trend rides to +3.5R, Counter-trend exits at VWAP mean
   - D. SLOPE_ACCELERATION: Only block counter-trend if EMA slope is steep
   - E. ATR_NORMALIZED_BUFFER: Block counter-trend only if distance > 1.5x ATR
"""

import sys
import time
from pathlib import Path
from collections import defaultdict
import json
import itertools

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

print("[Naruto Brain] Preloading Parquet Datasets...")
df_m1 = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")
df_m15 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_M15.parquet")
df_h1 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_H1.parquet")
df_h4 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_H4.parquet")

# Precompute EMAs and ATRs with full historical warmup
def enrich_tf(df, tf_name):
    df_e = df.with_columns([
        pl.col("close").ewm_mean(span=20).alias("ema20"),
        pl.col("close").ewm_mean(span=50).alias("ema50"),
        pl.col("close").ewm_mean(span=100).alias("ema100"),
        pl.col("close").ewm_mean(span=200).alias("ema200"),
        (pl.col("high") - pl.col("low")).rolling_mean(window_size=14).alias("atr14")
    ])
    # Also compute 3-bar slope of each EMA
    df_e = df_e.with_columns([
        (pl.col("ema20") - pl.col("ema20").shift(3)).alias("slope20"),
        (pl.col("ema50") - pl.col("ema50").shift(3)).alias("slope50"),
        (pl.col("ema100") - pl.col("ema100").shift(3)).alias("slope100"),
        (pl.col("ema200") - pl.col("ema200").shift(3)).alias("slope200"),
    ])
    return {
        row["timestamp"]: {
            "close": row["close"],
            "ema20": row["ema20"], "ema50": row["ema50"], "ema100": row["ema100"], "ema200": row["ema200"],
            "atr14": row["atr14"] or 5.0,
            "slope20": row["slope20"] or 0.0, "slope50": row["slope50"] or 0.0,
            "slope100": row["slope100"] or 0.0, "slope200": row["slope200"] or 0.0,
        }
        for row in df_e.iter_rows(named=True)
    }

print("[Naruto Brain] Precomputing enriched EMA indicators on M15, H1, H4...")
tf_cache = {
    "M15": enrich_tf(df_m15, "M15"),
    "H1": enrich_tf(df_h1, "H1"),
    "H4": enrich_tf(df_h4, "H4"),
}


class MassiveCloneStrategy(BaseStrategy):
    def __init__(
        self,
        name: str,
        mechanic: str,      # "BASELINE", "BINARY_VETO", "ASYMMETRIC_SIZING", "DYNAMIC_TARGET", "SLOPE_ACCEL", "ATR_BUFFER"
        tf: str = "H1",
        ema_period: int = 50,
        with_trend_risk: float = 0.60,
        counter_trend_risk: float = 0.20,
        with_trend_rr: float = 3.0,
        counter_trend_rr: float = 1.8,
        slope_threshold: float = 1.5,
        atr_mult: float = 1.5
    ):
        super().__init__(name)
        self.mechanic = mechanic
        self.tf = tf
        self.ema_key = f"ema{ema_period}"
        self.slope_key = f"slope{ema_period}"
        self.with_trend_risk = with_trend_risk
        self.counter_trend_risk = counter_trend_risk
        self.with_trend_rr = with_trend_rr
        self.counter_trend_rr = counter_trend_rr
        self.slope_threshold = slope_threshold
        self.atr_mult = atr_mult

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

    def _get_htf(self, dt):
        lookup = tf_cache[self.tf]
        if self.tf == "M15":
            m15_m = (dt.minute // 15) * 15
            t = dt.replace(minute=m15_m, second=0, microsecond=0)
        elif self.tf == "H1":
            t = dt.replace(minute=0, second=0, microsecond=0)
        else: # H4
            h4_h = (dt.hour // 4) * 4
            t = dt.replace(hour=h4_h, minute=0, second=0, microsecond=0)
        return lookup.get(t, None)

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
        import math
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

        # Evaluate HTF Trend & EMA Context
        htf = self._get_htf(dt) if self.mechanic != "BASELINE" else None

        is_bull_trend = False
        is_bear_trend = False
        allow_buy = True
        allow_sell = True
        buy_risk = 0.50
        sell_risk = 0.50
        buy_rr = 2.0
        sell_rr = 2.0

        if htf is not None:
            c_htf = htf["close"]
            ema_val = htf.get(self.ema_key, c_htf)
            atr_val = htf.get("atr14", 5.0)
            slope_val = htf.get(self.slope_key, 0.0)

            is_bull_trend = (c_htf > ema_val)
            is_bear_trend = (c_htf < ema_val)

            if self.mechanic == "BINARY_VETO":
                if is_bull_trend:
                    allow_sell = False
                elif is_bear_trend:
                    allow_buy = False

            elif self.mechanic == "ASYMMETRIC_SIZING":
                if is_bull_trend:
                    buy_risk = self.with_trend_risk
                    sell_risk = self.counter_trend_risk
                else:
                    buy_risk = self.counter_trend_risk
                    sell_risk = self.with_trend_risk

            elif self.mechanic == "DYNAMIC_TARGET":
                if is_bull_trend:
                    buy_rr = self.with_trend_rr
                    sell_rr = self.counter_trend_rr
                else:
                    buy_rr = self.counter_trend_rr
                    sell_rr = self.with_trend_rr

            elif self.mechanic == "SLOPE_ACCEL":
                # Only veto counter-trend if slope is steep (accelerating trend)
                if is_bull_trend and slope_val > self.slope_threshold:
                    allow_sell = False
                elif is_bear_trend and slope_val < -self.slope_threshold:
                    allow_buy = False

            elif self.mechanic == "ATR_BUFFER":
                # Only veto if price is stretched beyond N * ATR from EMA
                if is_bull_trend and (c_htf - ema_val) > (self.atr_mult * atr_val):
                    allow_sell = False
                elif is_bear_trend and (ema_val - c_htf) > (self.atr_mult * atr_val):
                    allow_buy = False

        # SHORT SETUP
        if gh >= self.upper_band and (upper_wick / rng) >= 0.45 and gc < go and allow_sell:
            stop = round(gh + 0.50, 2)
            risk = stop - gc
            if 0.80 <= risk <= 5.00:
                tp = round(gc - (risk * sell_rr), 2)
                if self.current_vwap < gc and (gc - self.current_vwap) >= risk * 1.5:
                    tp = round(self.current_vwap, 2)

                # Dynamic sizing based on sell_risk
                risk_amt = self.engine.equity * (sell_risk / 100.0)
                lots = round(max(0.01, risk_amt / (risk * 100.0)), 2)

                approval = self.governor.evaluate_entry(gc, stop, spread, 0.25, len(self.engine.positions))
                if approval.approved:
                    final_lots = approval.lots if self.mechanic in ("BASELINE", "BINARY_VETO") else lots
                    pid = self.engine.sell("XAUUSD", final_lots, stop, tp, comment="Short")
                    if pid:
                        self.traded_today += 1
                        return

        # LONG SETUP
        if gl <= self.lower_band and (lower_wick / rng) >= 0.45 and gc > go and allow_buy:
            stop = round(gl - 0.50, 2)
            risk = gc - stop
            if 0.80 <= risk <= 5.00:
                tp = round(gc + (risk * buy_rr), 2)
                if self.current_vwap > gc and (self.current_vwap - gc) >= risk * 1.5:
                    tp = round(self.current_vwap, 2)

                risk_amt = self.engine.equity * (buy_risk / 100.0)
                lots = round(max(0.01, risk_amt / (risk * 100.0)), 2)

                approval = self.governor.evaluate_entry(gc, stop, spread, 0.25, len(self.engine.positions))
                if approval.approved:
                    final_lots = approval.lots if self.mechanic in ("BASELINE", "BINARY_VETO") else lots
                    pid = self.engine.buy("XAUUSD", final_lots, stop, tp, comment="Long")
                    if pid:
                        self.traded_today += 1
                        return


def run_clone(spec):
    strat = MassiveCloneStrategy(**spec)
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

    return {
        "name": spec["name"],
        "mechanic": spec.get("mechanic"),
        "tf": spec.get("tf"),
        "ema": spec.get("ema_period"),
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
    print("=" * 100)
    print("🥷 NARUTO 100+ SHADOW CLONES: SYSTEMATIC EXPLORATION OF EMA INSTITUTIONAL MECHANICS")
    print("=" * 100)

    specs = [{"name": "Baseline: Pure VWAP 1.8s (No EMA Filter)", "mechanic": "BASELINE"}]

    tfs = ["M15", "H1", "H4"]
    emas = [20, 50, 100, 200]

    # 1. Asymmetric Sizing (With-trend 0.65%, Counter-trend 0.20% or 0.25%)
    for tf in tfs:
        for ema in emas:
            for c_risk in [0.15, 0.25]:
                specs.append({
                    "name": f"Asymm Sizing {tf} EMA {ema} (With 0.65% / Counter {c_risk*100:.0f}%)",
                    "mechanic": "ASYMMETRIC_SIZING",
                    "tf": tf,
                    "ema_period": ema,
                    "with_trend_risk": 0.65,
                    "counter_trend_risk": c_risk
                })

    # 2. Dynamic Target Expansion (With-trend rides 3.0R or 4.0R, Counter-trend exits VWAP mean)
    for tf in ["H1", "H4"]:
        for ema in [20, 50, 200]:
            for w_rr in [2.5, 3.5]:
                specs.append({
                    "name": f"Dynamic Target {tf} EMA {ema} (With {w_rr}R / Counter 1.8R)",
                    "mechanic": "DYNAMIC_TARGET",
                    "tf": tf,
                    "ema_period": ema,
                    "with_trend_rr": w_rr,
                    "counter_trend_rr": 1.8
                })

    # 3. Slope Acceleration Gate
    for tf in ["H1", "H4"]:
        for ema in [20, 50]:
            for slope_th in [0.8, 1.5, 2.5]:
                specs.append({
                    "name": f"Slope Gate {tf} EMA {ema} (Threshold {slope_th})",
                    "mechanic": "SLOPE_ACCEL",
                    "tf": tf,
                    "ema_period": ema,
                    "slope_threshold": slope_th
                })

    # 4. ATR Normalized Buffer
    for tf in ["H1", "H4"]:
        for ema in [50, 200]:
            for mult in [1.0, 1.5, 2.0]:
                specs.append({
                    "name": f"ATR Buffer {tf} EMA {ema} (Dist > {mult}x ATR)",
                    "mechanic": "ATR_BUFFER",
                    "tf": tf,
                    "ema_period": ema,
                    "atr_mult": mult
                })

    print(f"[Naruto Brain] Generated {len(specs)} Shadow Clone Specifications!")
    print("[Naruto Brain] Launching massive parallel execution...")

    results = []
    t_start = time.time()
    for idx, spec in enumerate(specs, 1):
        t0 = time.time()
        res = run_clone(spec)
        elapsed = time.time() - t0
        if idx % 5 == 0 or idx == 1 or idx == len(specs) or res["net_pnl"] > 4000:
            print(f"[{idx:03d}/{len(specs)}] {res['name']:<55} | PnL: ${res['net_pnl']:>10,.2f} | PF: {res['pf']:>4.2f} | Win: {res['win_rate']:>4.1f}% | DD: {res['max_dd']:>4.1f}% | Months: {res['months']} ({elapsed:.1f}s)")
        results.append(res)

    print(f"\n[Naruto Brain] All {len(specs)} Shadow Clones executed in {time.time()-t_start:.1f}s!")

    # Sort primarily by Net PnL, then Profit Factor
    results.sort(key=lambda x: (x["net_pnl"], x["pf"]), reverse=True)

    print("\n" + "=" * 125)
    print("🏆 TOP 15 ABSOLUTE CHAMPIONS FROM 100+ SHADOW CLONES (RANKED BY NET PNL)")
    print("=" * 125)
    header = f"{'Rank':<5} | {'Configuration':<58} | {'Trades':<6} | {'Win%':<6} | {'Payoff':<6} | {'Net PnL':<11} | {'PF':<5} | {'MaxDD':<6} | {'Months'}"
    print(header)
    print("-" * 125)
    for rank, r in enumerate(results[:15], 1):
        print(f"#{rank:<4} | {r['name']:<58} | {r['trades']:<6} | {r['win_rate']:>5.1f}% | {r['payoff']:>5.2f}x | ${r['net_pnl']:>10,.2f} | {r['pf']:>4.2f} | {r['max_dd']:>5.1f}% | {r['months']}")
    print("=" * 125)

    out_file = Path("reports/massive_shadow_clone_results.json")
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[Naruto Brain] Complete data of {len(results)} clones saved to: {out_file.resolve()}")


if __name__ == "__main__":
    main()
