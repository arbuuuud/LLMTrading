"""
Shadow Clone Exploration: Macro EMA Trend Filters (20, 50, 100, 200).
Investigates how EMA filters on H1 and H4 protect Session Anchored VWAP M1 Scalper
against runaway trending markets (e.g., Sept/Nov 2025) and flip losing months to profit.

Configurations tested:
- Baselines: No Filter (Pure VWAP 1.8s)
- Single EMA Alignment (H1 20, 50, 100, 200): Only take trades in trend direction
- Single EMA Alignment (H4 20, 50, 100, 200)
- Parabolic Runaway Filters (Suppress counter-trend only if distance > threshold)
- Dual EMA Ribbons (H1 20/50, H1 50/200, H4 20/50, H4 50/200)
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
from strategies.incubator.strat_3_anchored_vwap import SessionAnchoredVWAPStrategy

# Preload data guard
import os
if not os.path.exists("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet"):
    raise unittest.SkipTest("Parquet historical dataset not found on server; skipping backtest test.")

df_m1 = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")
df_h1 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_H1.parquet")
df_h4 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_H4.parquet")

# Precompute EMAs on H1
df_h1 = df_h1.with_columns([
    pl.col("close").ewm_mean(span=20).alias("ema20"),
    pl.col("close").ewm_mean(span=50).alias("ema50"),
    pl.col("close").ewm_mean(span=100).alias("ema100"),
    pl.col("close").ewm_mean(span=200).alias("ema200"),
])
h1_ema_map = {
    row["timestamp"]: {
        "ema20": row["ema20"],
        "ema50": row["ema50"],
        "ema100": row["ema100"],
        "ema200": row["ema200"],
        "close": row["close"]
    }
    for row in df_h1.iter_rows(named=True)
}

# Precompute EMAs on H4
df_h4 = df_h4.with_columns([
    pl.col("close").ewm_mean(span=20).alias("ema20"),
    pl.col("close").ewm_mean(span=50).alias("ema50"),
    pl.col("close").ewm_mean(span=100).alias("ema100"),
    pl.col("close").ewm_mean(span=200).alias("ema200"),
])
h4_ema_map = {
    row["timestamp"]: {
        "ema20": row["ema20"],
        "ema50": row["ema50"],
        "ema100": row["ema100"],
        "ema200": row["ema200"],
        "close": row["close"]
    }
    for row in df_h4.iter_rows(named=True)
}


class EMATrendFilterStrategy(SessionAnchoredVWAPStrategy):
    def __init__(
        self,
        name: str,
        filter_type: str = "NONE",  # "NONE", "STRICT_ALIGN", "PARABOLIC_BUFFER", "RIBBON"
        tf: str = "H1",             # "H1" or "H4"
        ema_key: str = "ema50",
        fast_ema: str = "ema20",
        slow_ema: str = "ema50",
        buffer_dollars: float = 15.0
    ):
        super().__init__(
            band_multiplier=1.8,
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
        self.strategy_name = name
        self.filter_type = filter_type
        self.tf = tf
        self.ema_key = ema_key
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.buffer_dollars = buffer_dollars

    def _get_htf_emas(self, dt):
        if self.tf == "H1":
            b_time = dt.replace(minute=0, second=0, microsecond=0)
            return h1_ema_map.get(b_time, None)
        else:
            b_hour = (dt.hour // 4) * 4
            b_time = dt.replace(hour=b_hour, minute=0, second=0, microsecond=0)
            return h4_ema_map.get(b_time, None)

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
        import math
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

        is_trade_window = self.start_time <= (t.hour, t.minute) <= self.end_time
        if not is_trade_window or self.traded_today_count >= 2:
            return

        rng = gh - gl
        if rng < 0.35:
            return

        upper_wick = gh - max(go, gc)
        lower_wick = min(go, gc) - gl

        # Evaluate EMA Trend Filter
        allow_buy = True
        allow_sell = True

        htf_data = self._get_htf_emas(dt)
        if htf_data is not None and self.filter_type != "NONE":
            htf_close = htf_data["close"]

            if self.filter_type == "STRICT_ALIGN":
                ema_val = htf_data[self.ema_key]
                if ema_val is not None:
                    if htf_close > ema_val:
                        allow_sell = False  # Bullish: only buy dips!
                    else:
                        allow_buy = False   # Bearish: only sell rallies!

            elif self.filter_type == "PARABOLIC_BUFFER":
                ema_val = htf_data[self.ema_key]
                if ema_val is not None:
                    # If price is way above EMA by buffer, don't sell into runaway rocket!
                    if (htf_close - ema_val) > self.buffer_dollars:
                        allow_sell = False
                    # If price is way below EMA by buffer, don't buy into falling knife!
                    elif (ema_val - htf_close) > self.buffer_dollars:
                        allow_buy = False

            elif self.filter_type == "RIBBON":
                fast = htf_data[self.fast_ema]
                slow = htf_data[self.slow_ema]
                if fast is not None and slow is not None:
                    if fast > slow:
                        allow_sell = False  # Bullish ribbon: only buy dips!
                    else:
                        allow_buy = False   # Bearish ribbon: only sell rallies!

        # SHORT SETUP
        if gh >= self.upper_band and (upper_wick / rng) >= 0.45 and gc < go and allow_sell:
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

        # LONG SETUP
        if gl <= self.lower_band and (lower_wick / rng) >= 0.45 and gc > go and allow_buy:
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


def run_single_experiment(spec):
    strat = EMATrendFilterStrategy(**spec)
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
    specs = [
        # Baseline
        {"name": "0. Baseline: Pure VWAP 1.8s (No EMA Filter)", "filter_type": "NONE"},

        # Strict Single EMA on H1
        {"name": "1. H1 Strict EMA 20 (Trade with Trend)", "filter_type": "STRICT_ALIGN", "tf": "H1", "ema_key": "ema20"},
        {"name": "2. H1 Strict EMA 50 (Trade with Trend)", "filter_type": "STRICT_ALIGN", "tf": "H1", "ema_key": "ema50"},
        {"name": "3. H1 Strict EMA 100 (Trade with Trend)", "filter_type": "STRICT_ALIGN", "tf": "H1", "ema_key": "ema100"},
        {"name": "4. H1 Strict EMA 200 (Trade with Trend)", "filter_type": "STRICT_ALIGN", "tf": "H1", "ema_key": "ema200"},

        # Strict Single EMA on H4
        {"name": "5. H4 Strict EMA 20 (Trade with Trend)", "filter_type": "STRICT_ALIGN", "tf": "H4", "ema_key": "ema20"},
        {"name": "6. H4 Strict EMA 50 (Trade with Trend)", "filter_type": "STRICT_ALIGN", "tf": "H4", "ema_key": "ema50"},
        {"name": "7. H4 Strict EMA 100 (Trade with Trend)", "filter_type": "STRICT_ALIGN", "tf": "H4", "ema_key": "ema100"},
        {"name": "8. H4 Strict EMA 200 (Trade with Trend)", "filter_type": "STRICT_ALIGN", "tf": "H4", "ema_key": "ema200"},

        # Parabolic Buffer Filters (Allows counter-trend UNLESS distance > $15)
        {"name": "9. H1 EMA 50 + Parabolic Buffer $15", "filter_type": "PARABOLIC_BUFFER", "tf": "H1", "ema_key": "ema50", "buffer_dollars": 15.0},
        {"name": "10. H1 EMA 50 + Parabolic Buffer $25", "filter_type": "PARABOLIC_BUFFER", "tf": "H1", "ema_key": "ema50", "buffer_dollars": 25.0},
        {"name": "11. H1 EMA 200 + Parabolic Buffer $30", "filter_type": "PARABOLIC_BUFFER", "tf": "H1", "ema_key": "ema200", "buffer_dollars": 30.0},
        {"name": "12. H4 EMA 50 + Parabolic Buffer $35", "filter_type": "PARABOLIC_BUFFER", "tf": "H4", "ema_key": "ema50", "buffer_dollars": 35.0},
        {"name": "13. H4 EMA 200 + Parabolic Buffer $50", "filter_type": "PARABOLIC_BUFFER", "tf": "H4", "ema_key": "ema200", "buffer_dollars": 50.0},

        # Dual EMA Ribbon Stacks
        {"name": "14. H1 Ribbon: EMA 20 / 50 Stack", "filter_type": "RIBBON", "tf": "H1", "fast_ema": "ema20", "slow_ema": "ema50"},
        {"name": "15. H1 Ribbon: EMA 50 / 200 Golden Cross", "filter_type": "RIBBON", "tf": "H1", "fast_ema": "ema50", "slow_ema": "ema200"},
        {"name": "16. H4 Ribbon: EMA 20 / 50 Stack", "filter_type": "RIBBON", "tf": "H4", "fast_ema": "ema20", "slow_ema": "ema50"},
        {"name": "17. H4 Ribbon: EMA 50 / 200 Golden Cross", "filter_type": "RIBBON", "tf": "H4", "fast_ema": "ema50", "slow_ema": "ema200"},
    ]

    print("=" * 115)
    print("🥷 NARUTO SHADOW CLONES: SYSTEMATIC EMA 20, 50, 100, 200 EXPLORATION MATRIX")
    print("=" * 115)

    results = []
    t0_all = time.time()
    for idx, spec in enumerate(specs, 1):
        t0 = time.time()
        res = run_single_experiment(spec)
        elapsed = time.time() - t0
        print(f"[{idx:02d}/{len(specs)}] {res['name']:<50} | PnL: ${res['net_pnl']:>10,.2f} | PF: {res['pf']:>4.2f} | Win: {res['win_rate']:>4.1f}% | DD: {res['max_dd']:>4.1f}% | Months: {res['months']} ({elapsed:.1f}s)")
        results.append(res)

    print(f"\n[Master Brain] Completed 17 Shadow Clones in {time.time()-t0_all:.1f}s.")

    # Sort by Net PnL and Profit Factor
    results.sort(key=lambda x: (x["net_pnl"], x["pf"]), reverse=True)

    print("\n" + "=" * 115)
    print("🏆 EMA TREND FILTER MASTER SCOREBOARD (RANKED BY TOTAL NET PROFIT)")
    print("=" * 115)
    header = f"{'Rank':<5} | {'Configuration':<52} | {'Trades':<6} | {'Win%':<6} | {'Payoff':<6} | {'Net PnL':<11} | {'PF':<5} | {'MaxDD':<6} | {'Months'}"
    print(header)
    print("-" * 115)
    for rank, r in enumerate(results, 1):
        print(f"#{rank:<4} | {r['name']:<52} | {r['trades']:<6} | {r['win_rate']:>5.1f}% | {r['payoff']:>5.2f}x | ${r['net_pnl']:>10,.2f} | {r['pf']:>4.2f} | {r['max_dd']:>5.1f}% | {r['months']}")
    print("=" * 115)

    # Save to json
    out_path = Path("reports/ema_exploration_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[Master Brain] Full audit saved to {out_path.resolve()}")


if __name__ == "__main__":
    main()
