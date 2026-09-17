"""
Comprehensive Quantitative Audit: 1x Risk vs 2x Risk Multiplier.
Compares:
- Engine 1: Scalper M1 (VWAP 1.8s + H1 EMA 50 ATR Buffer > 1.5x)
- Engine 2: Intraday M15 (Fadli NFC Unfilled Base + H1 EMA 50)
- Combined Dual-Engine Portfolio

Parameters:
1x Baseline:
  - Base Risk: 0.5% ($50)
  - Greed Risk: 0.25% ($25)
  - Max Daily Loss: 1.0% ($100 / 2 strikes)
  - Monthly Drawdown Cap: 3.0% ($300)
  - Daily Ratchet Tiers: +1.5% -> lock +1.0%, +2.0% -> lock +1.5%

2x Multiplier:
  - Base Risk: 1.0% ($100)
  - Greed Risk: 0.50% ($50)
  - Max Daily Loss: 2.0% ($200 / 2 strikes)
  - Monthly Drawdown Cap: 6.0% ($600)
  - Daily Ratchet Tiers: +3.0% -> lock +2.0%, +4.0% -> lock +3.0%
"""

import sys
import time
import math
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

print("[Naruto Brain] Preloading Parquet Datasets...")
df_m1 = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")
df_m15 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_M15.parquet")
df_h1 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_H1.parquet")

# Precompute H1 EMA 50 & ATR 14
df_h1 = df_h1.with_columns([
    pl.col("close").ewm_mean(span=50).alias("ema50"),
    (pl.col("high") - pl.col("low")).rolling_mean(window_size=14).alias("atr14")
])
h1_cache = {
    row["timestamp"]: {
        "close": row["close"],
        "ema50": row["ema50"],
        "atr14": row["atr14"] or 5.0
    }
    for row in df_h1.iter_rows(named=True)
}


# =====================================================================
# DUAL ENGINE STRATEGY RUNNER
# =====================================================================
class DualEngineCombinedStrategy(BaseStrategy):
    def __init__(self, risk_multiplier: float = 1.0):
        super().__init__(f"DualEngine_{risk_multiplier}x")
        self.risk_multiplier = risk_multiplier

        base_risk = 0.5 * risk_multiplier
        greed_risk = 0.25 * risk_multiplier
        max_daily_loss = 1.0 * risk_multiplier
        monthly_loss_cap = 3.0 * risk_multiplier

        # Scalper M1 Governor
        self.scalper_governor = MonthlyRatchetGovernor(
            base_risk_pct=base_risk,
            greed_risk_pct=greed_risk,
            max_daily_loss_pct=max_daily_loss,
            monthly_loss_cap_pct=monthly_loss_cap,
            cooldown_bars=20
        )
        # Scale daily ratchet thresholds
        self.scalper_governor.ratchet_tiers = [
            (1.5 * risk_multiplier, 1.0 * risk_multiplier),
            (2.0 * risk_multiplier, 1.5 * risk_multiplier),
            (2.5 * risk_multiplier, 2.0 * risk_multiplier),
            (3.5 * risk_multiplier, 3.0 * risk_multiplier),
        ]

        # Intraday M15 Governor
        self.intraday_governor = MonthlyRatchetGovernor(
            base_risk_pct=base_risk,
            greed_risk_pct=greed_risk,
            max_daily_loss_pct=max_daily_loss,
            monthly_loss_cap_pct=monthly_loss_cap,
            cooldown_bars=8
        )
        self.intraday_governor.ratchet_tiers = [
            (1.5 * risk_multiplier, 1.0 * risk_multiplier),
            (2.0 * risk_multiplier, 1.5 * risk_multiplier),
            (2.5 * risk_multiplier, 2.0 * risk_multiplier),
            (3.5 * risk_multiplier, 3.0 * risk_multiplier),
        ]

        # Scalper State
        self.current_date = None
        self.cum_vol = 0.0
        self.cum_pv = 0.0
        self.cum_p2v = 0.0
        self.current_vwap = 0.0
        self.current_std = 0.0
        self.upper_band = 0.0
        self.lower_band = 0.0
        self.scalper_traded_today = 0
        self.scalper_bars_in_trade = 0

        # Intraday State
        self.m15_bars = []
        self.demand_zones = []
        self.supply_zones = []
        self.intraday_traded_today = 0

    def on_init(self):
        self.current_date = None
        self.cum_vol = 0.0
        self.cum_pv = 0.0
        self.cum_p2v = 0.0
        self.scalper_traded_today = 0
        self.scalper_bars_in_trade = 0
        self.m15_bars.clear()
        self.demand_zones.clear()
        self.supply_zones.clear()
        self.intraday_traded_today = 0

    def _get_h1(self, dt):
        t = dt.replace(minute=0, second=0, microsecond=0)
        return h1_cache.get(t, None)

    # -------------------------------------------------------------
    # M1 BAR PROCESSING (SCALPER ENGINE 1)
    # -------------------------------------------------------------
    def on_m1_bar(self, bar):
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
            self.scalper_traded_today = 0
            self.scalper_bars_in_trade = 0
            self.intraday_traded_today = 0

        # Update Session VWAP
        tp_price = (gh + gl + gc) / 3.0
        self.cum_vol += vol
        self.cum_pv += tp_price * vol
        self.cum_p2v += (tp_price ** 2) * vol

        self.current_vwap = self.cum_pv / self.cum_vol
        variance = max(0.0, (self.cum_p2v / self.cum_vol) - (self.current_vwap ** 2))
        self.current_std = math.sqrt(variance)
        self.upper_band = self.current_vwap + (self.current_std * 1.8)
        self.lower_band = self.current_vwap - (self.current_std * 1.8)

        self.scalper_governor.on_new_bar(dt, self.engine.equity)

        # Scalper position management
        scalp_positions = [p for p in self.engine.positions.values() if p.tag == "Scalper_M1"]
        if len(scalp_positions) > 0:
            self.scalper_bars_in_trade += 1
            if self.scalper_bars_in_trade >= 60:
                for p in scalp_positions:
                    self.engine.close_position(p.position_id, ExitReason.TIME_EXPIRED)
                self.scalper_bars_in_trade = 0
            return
        else:
            self.scalper_bars_in_trade = 0

        # Golden Institutional Window: 10:30 - 14:30 UTC
        if not ((10, 30) <= (t.hour, t.minute) <= (14, 30)) or self.scalper_traded_today >= 2:
            return

        rng = gh - gl
        if rng < 0.35:
            return

        upper_wick = gh - max(go, gc)
        lower_wick = min(go, gc) - gl

        # H1 EMA 50 + ATR Buffer check
        h1 = self._get_h1(dt)
        block_sell = False
        block_buy = False
        if h1 is not None:
            c_h1 = h1["close"]
            ema_h1 = h1["ema50"]
            atr_h1 = h1["atr14"]
            dist = c_h1 - ema_h1
            if dist > (1.5 * atr_h1):
                block_sell = True
            elif dist < -(1.5 * atr_h1):
                block_buy = True

        # Scalper Short
        if gh >= self.upper_band and (upper_wick / rng) >= 0.45 and gc < go and not block_sell:
            stop = round(gh + 0.50, 2)
            risk_dist = stop - gc
            if 0.80 <= risk_dist <= 5.00:
                tp = round(gc - (risk_dist * 2.0), 2)
                if self.current_vwap < gc and (gc - self.current_vwap) >= risk_dist * 1.5:
                    tp = round(self.current_vwap, 2)

                approval = self.scalper_governor.evaluate_entry(gc, stop, spread, 0.25, len(scalp_positions))
                if approval.approved:
                    pid = self.engine.sell("XAUUSD", approval.lots, stop, tp, comment="Scalp_VWAP_Upper", tag="Scalper_M1")
                    if pid:
                        self.scalper_traded_today += 1
                        return

        # Scalper Long
        if gl <= self.lower_band and (lower_wick / rng) >= 0.45 and gc > go and not block_buy:
            stop = round(gl - 0.50, 2)
            risk_dist = gc - stop
            if 0.80 <= risk_dist <= 5.00:
                tp = round(gc + (risk_dist * 2.0), 2)
                if self.current_vwap > gc and (self.current_vwap - gc) >= risk_dist * 1.5:
                    tp = round(self.current_vwap, 2)

                approval = self.scalper_governor.evaluate_entry(gc, stop, spread, 0.25, len(scalp_positions))
                if approval.approved:
                    pid = self.engine.buy("XAUUSD", approval.lots, stop, tp, comment="Scalp_VWAP_Lower", tag="Scalper_M1")
                    if pid:
                        self.scalper_traded_today += 1
                        return

    # -------------------------------------------------------------
    # M15 BAR PROCESSING (INTRADAY ENGINE 2)
    # -------------------------------------------------------------
    def on_m15_bar(self, bar):
        dt = bar["timestamp"]
        d = dt.date()
        t = dt.time()
        gh, gl, gc, go = bar["high"], bar["low"], bar["close"], bar["open"]
        spread = bar.get("mean_spread", 0.25)

        self.m15_bars.append(bar)
        if len(self.m15_bars) > 60:
            self.m15_bars.pop(0)

        self.intraday_governor.on_new_bar(dt, self.engine.equity)

        # Detect DBR / RBD bases
        if len(self.m15_bars) >= 5:
            b_drop = self.m15_bars[-4]
            b_base = self.m15_bars[-3]
            b_rally = self.m15_bars[-1]

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

        intraday_positions = [p for p in self.engine.positions.values() if p.tag == "Intraday_M15"]
        if len(intraday_positions) > 0:
            if t.hour >= 21 and t.minute >= 30:
                for p in intraday_positions:
                    self.engine.close_position(p.position_id, ExitReason.TIME_EXPIRED)
            return

        if not ((8, 0) <= (t.hour, t.minute) <= (16, 30)) or self.intraday_traded_today >= 1:
            return

        h1 = self._get_h1(dt)
        is_bull_macro = True
        is_bear_macro = True
        if h1 is not None:
            c_h1 = h1["close"]
            ema_h1 = h1["ema50"]
            is_bull_macro = (c_h1 >= ema_h1)
            is_bear_macro = (c_h1 <= ema_h1)

        # Retest Demand (BUY)
        if is_bull_macro:
            for z in reversed(self.demand_zones):
                if not z["mitigated"] and (z["bottom"] - 0.5) <= gl <= (z["top"] + 0.5) and gc > go:
                    z["mitigated"] = True
                    sl = round(z["bottom"] - 1.20, 2)
                    risk = gc - sl
                    if 1.50 <= risk <= 6.50:
                        tp = round(gc + risk * 2.5, 2)
                        approval = self.intraday_governor.evaluate_entry(gc, sl, spread, 0.35, len(intraday_positions))
                        if approval.approved:
                            pid = self.engine.buy("XAUUSD", approval.lots, sl, tp, comment="NFC_DBR_Buy", tag="Intraday_M15")
                            if pid:
                                self.intraday_traded_today += 1
                                return

        # Retest Supply (SELL)
        if is_bear_macro:
            for z in reversed(self.supply_zones):
                if not z["mitigated"] and (z["bottom"] - 0.5) <= gh <= (z["top"] + 0.5) and gc < go:
                    z["mitigated"] = True
                    sl = round(z["top"] + 1.20, 2)
                    risk = sl - gc
                    if 1.50 <= risk <= 6.50:
                        tp = round(gc - risk * 2.5, 2)
                        approval = self.intraday_governor.evaluate_entry(gc, sl, spread, 0.35, len(intraday_positions))
                        if approval.approved:
                            pid = self.engine.sell("XAUUSD", approval.lots, sl, tp, comment="NFC_RBD_Sell", tag="Intraday_M15")
                            if pid:
                                self.intraday_traded_today += 1
                                return


def run_full_simulation(risk_multiplier: float):
    t0 = time.time()
    config = AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0)
    engine = EventEngine(config=config, commission_model=CommissionModel(7.0), slippage_model=FixedSlippageModel(0.02))

    strat = DualEngineCombinedStrategy(risk_multiplier=risk_multiplier)
    strat.set_engine(engine)
    strat.on_init()

    current_m15 = None

    for bar in df_m1.iter_rows(named=True):
        engine.current_time = bar["timestamp"]
        spread = bar.get("mean_spread", 0.20)
        engine.current_bid = bar["close"]
        engine.current_ask = round(engine.current_bid + spread, 3)
        engine.current_spread = spread

        engine._check_daily_circuit_breaker(engine.current_time)
        engine._update_positions_on_bar(bar)

        # Engine 1 (M1)
        strat.on_m1_bar(bar)

        # Aggregate M15 for Engine 2
        dt = bar["timestamp"]
        m15_minute = (dt.minute // 15) * 15
        m15_time = dt.replace(minute=m15_minute, second=0, microsecond=0)

        if current_m15 is None or current_m15["timestamp"] != m15_time:
            if current_m15 is not None:
                strat.on_m15_bar(current_m15)
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
        strat.on_m15_bar(current_m15)

    for pos_id in list(engine.positions.keys()):
        engine._close_position_internal(pos_id, ExitReason.END_OF_DATA)

    strat.on_finish()
    elapsed = time.time() - t0

    perf = PerformanceCalculator.calculate(engine.closed_trades, engine.equity_curve, config.initial_balance)

    # Monthly breakdown
    monthly_pnl = defaultdict(float)
    daily_pnl = defaultdict(float)
    for tr in engine.closed_trades:
        monthly_pnl[tr.open_time.strftime("%Y-%m")] += tr.net_pnl
        daily_pnl[tr.open_time.strftime("%Y-%m-%d")] += tr.net_pnl

    pos_months = sum(1 for v in monthly_pnl.values() if v > 0)
    total_months = len(monthly_pnl) or 1

    # Engine breakdown
    scalp_trades = [t for t in engine.closed_trades if t.tag == "Scalper_M1"]
    intra_trades = [t for t in engine.closed_trades if t.tag == "Intraday_M15"]

    scalp_pnl = sum(t.net_pnl for t in scalp_trades)
    intra_pnl = sum(t.net_pnl for t in intra_trades)

    # Daily metrics
    daily_values = list(daily_pnl.values())
    avg_daily_profit_when_green = (sum(v for v in daily_values if v > 0) / sum(1 for v in daily_values if v > 0)) if any(v > 0 for v in daily_values) else 0.0
    avg_daily_loss_when_red = (sum(v for v in daily_values if v < 0) / sum(1 for v in daily_values if v < 0)) if any(v < 0 for v in daily_values) else 0.0
    max_single_day_gain = max(daily_values) if daily_values else 0.0
    max_single_day_loss = min(daily_values) if daily_values else 0.0
    win_days = sum(1 for v in daily_values if v > 0)
    loss_days = sum(1 for v in daily_values if v < 0)
    daily_win_rate = (win_days / (win_days + loss_days) * 100.0) if (win_days + loss_days) > 0 else 0.0

    return {
        "risk_mult": risk_multiplier,
        "elapsed": elapsed,
        "total_trades": perf.total_trades,
        "win_rate": round(perf.win_rate_pct, 1),
        "payoff": round(perf.win_loss_ratio, 2),
        "net_profit": round(perf.net_profit, 2),
        "roi_pct": round((perf.net_profit / config.initial_balance) * 100.0, 1),
        "profit_factor": round(perf.profit_factor, 2),
        "max_drawdown_pct": round(perf.max_drawdown_pct, 1),
        "sharpe_ratio": round(perf.sharpe_ratio, 2),
        "green_months": f"{pos_months}/{total_months}",
        "green_months_pct": round((pos_months / total_months) * 100.0, 1),
        "scalp_trades": len(scalp_trades),
        "scalp_pnl": round(scalp_pnl, 2),
        "intra_trades": len(intra_trades),
        "intra_pnl": round(intra_pnl, 2),
        "daily_win_rate": round(daily_win_rate, 1),
        "avg_daily_gain": round(avg_daily_profit_when_green, 2),
        "avg_daily_loss": round(avg_daily_loss_when_red, 2),
        "max_day_gain": round(max_single_day_gain, 2),
        "max_day_loss": round(max_single_day_loss, 2),
        "monthly_pnl": dict(monthly_pnl)
    }


def main():
    print("=" * 100)
    print("⚖️ AUDIT KUANTITATIF EKSPERIMENTAL: BASELINE 1x RISK vs 2x RISK MULTIPLIER")
    print("=" * 100)

    print("\n[1/2] Menjalankan Simulasi 1x Risk Baseline (Base 0.5%, Greed 0.25%, Max Loss -1.0%, Month Cap -3.0%)...")
    res_1x = run_full_simulation(risk_multiplier=1.0)
    print(f"  -> Selesai dalam {res_1x['elapsed']:.1f}s | Net Profit: ${res_1x['net_profit']:+,.2f} | PF: {res_1x['profit_factor']:.2f} | DD: {res_1x['max_drawdown_pct']:.1f}%")

    print("\n[2/2] Menjalankan Simulasi 2x Risk Multiplier (Base 1.0%, Greed 0.50%, Max Loss -2.0%, Month Cap -6.0%)...")
    res_2x = run_full_simulation(risk_multiplier=2.0)
    print(f"  -> Selesai dalam {res_2x['elapsed']:.1f}s | Net Profit: ${res_2x['net_profit']:+,.2f} | PF: {res_2x['profit_factor']:.2f} | DD: {res_2x['max_drawdown_pct']:.1f}%")

    # Save to json
    output = {
        "res_1x": res_1x,
        "res_2x": res_2x
    }
    with open("reports/risk_multiplier_comparison.json", "w") as f:
        json.dump(output, f, indent=2)
    print("\n[Naruto Brain] Comparison saved to reports/risk_multiplier_comparison.json")


if __name__ == "__main__":
    main()
