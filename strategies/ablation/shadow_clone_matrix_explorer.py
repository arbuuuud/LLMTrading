"""
Shadow Clone Automated Multi-Timeframe & Confluence Matrix Explorer.
Simulates dozens of parallel strategy configurations across 10.5 months of data:
- Execution Timeframes: M1, M5, M15
- Bias / Structure Timeframes: M15, H1, H4
- Strategy Archetypes:
  * Archetype 1: Session Anchored VWAP Mean Reversion (1.8s vs 2.0s, Full vs Golden Window)
  * Archetype 2: SMC Market Structure Expansion (BOS/CHoCH + OB + iFVG, 2R vs 3R vs 4R)
  * Archetype 3: Fibonacci OTE Golden Pocket Confluence (OB + 61.8%-78.6% Retracement)
  * Archetype 4: Elliott Wave Expansion Target (Fibonacci 1.618 Extension TP)
Generates:
- Complete Comparative Leaderboard
- Top 5 Golden Institutional Combinations
- Markdown / JSON Artifacts
"""

import sys
import time
import os
import json
from pathlib import Path
from collections import defaultdict
import math

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from engine.core.event_engine import EventEngine
from engine.core.types import AccountConfig, ExitReason, OrderDirection
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from engine.metrics.performance import PerformanceCalculator
from engine.core.strategy_base import BaseStrategy
from agents.risk_manager.monthly_ratchet_governor import MonthlyRatchetGovernor
from strategies.modules.setups.ifvg_detector import InversionFVGDetector
from strategies.modules.triggers.market_structure import MarketStructureDetector, StructureEvent
from strategies.modules.setups.fibonacci_confluence import FibonacciCalculator, FiboSetup


class MatrixStrategy(BaseStrategy):
    def __init__(
        self,
        config_name: str,
        archetype: str,            # "VWAP_REVERSION" or "SMC_EXPANSION" or "SMC_FIBO_OTE"
        exec_tf: str,              # "M1", "M5", "M15"
        bias_tf: str,              # "M15", "H1", "H4"
        band_multiplier: float = 1.8,
        rr_target: float = 2.0,
        use_fibo_target: bool = False,
        use_fibo_ote_filter: bool = False,
        start_hour: int = 8,
        start_min: int = 0,
        end_hour: int = 16,
        end_min: int = 30,
        sl_buffer: float = 0.50
    ):
        super().__init__(config_name)
        self.config_name = config_name
        self.archetype = archetype
        self.exec_tf = exec_tf
        self.bias_tf = bias_tf
        self.band_multiplier = band_multiplier
        self.rr_target = rr_target
        self.use_fibo_target = use_fibo_target
        self.use_fibo_ote_filter = use_fibo_ote_filter
        self.start_time = (start_hour, start_min)
        self.end_time = (end_hour, end_min)
        self.sl_buffer = sl_buffer

        self.governor = MonthlyRatchetGovernor(
            base_risk_pct=0.5,
            greed_risk_pct=0.25,
            max_daily_loss_pct=1.0,
            monthly_loss_cap_pct=3.0,
            cooldown_bars=15
        )

        # Structure & POI
        self.structure_detector = MarketStructureDetector(pivot_lookback=3)
        self.ifvg_detector = InversionFVGDetector(min_fvg_size_dollars=0.50)
        self.current_bias: int = 0
        self.active_pois = []
        self.htf_history = []
        self.current_htf_bar = None
        self.latest_fibo = None

        # VWAP
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
        self.bars_in_trade = 0
        self.traded_today = 0
        self.current_bias = 0
        self.active_pois.clear()
        self.htf_history.clear()
        self.current_htf_bar = None
        self.latest_fibo = None

    def on_trade_closed(self, trade_record):
        self.governor.on_trade_closed(trade_record.net_pnl)

    def _update_htf_bar(self, bar):
        dt = bar["timestamp"]
        # Determine HTF bucket
        if self.bias_tf == "M15":
            bucket_min = (dt.minute // 15) * 15
            bucket_time = dt.replace(minute=bucket_min, second=0, microsecond=0)
        elif self.bias_tf == "H1":
            bucket_time = dt.replace(minute=0, second=0, microsecond=0)
        elif self.bias_tf == "H4":
            bucket_hour = (dt.hour // 4) * 4
            bucket_time = dt.replace(hour=bucket_hour, minute=0, second=0, microsecond=0)
        else:
            bucket_time = dt.replace(minute=0, second=0, microsecond=0)

        if self.current_htf_bar is None or self.current_htf_bar["timestamp"] != bucket_time:
            if self.current_htf_bar is not None:
                self._on_htf_close(self.current_htf_bar)
            self.current_htf_bar = {
                "timestamp": bucket_time,
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "tick_volume": bar.get("tick_volume", 1)
            }
        else:
            self.current_htf_bar["high"] = max(self.current_htf_bar["high"], bar["high"])
            self.current_htf_bar["low"] = min(self.current_htf_bar["low"], bar["low"])
            self.current_htf_bar["close"] = bar["close"]
            self.current_htf_bar["tick_volume"] += bar.get("tick_volume", 1)

    def _on_htf_close(self, htf_bar):
        self.htf_history.append(htf_bar)
        if len(self.htf_history) > 60:
            self.htf_history.pop(0)

        struct = self.structure_detector.update(htf_bar)
        if struct in (StructureEvent.BULLISH_CHOCH, StructureEvent.BULLISH_BOS):
            self.current_bias = 1
        elif struct in (StructureEvent.BEARISH_CHOCH, StructureEvent.BEARISH_BOS):
            self.current_bias = -1

        self.ifvg_detector.update(htf_bar)
        self.active_pois = self.ifvg_detector.get_active_ifvg_zones()

        # OB detection
        if len(self.htf_history) >= 5:
            last = self.htf_history[-1]
            prev_h = [b["high"] for b in self.htf_history[-5:-1]]
            prev_l = [b["low"] for b in self.htf_history[-5:-1]]
            if last["high"] > max(prev_h) and last["close"] > last["open"]:
                for b in reversed(self.htf_history[-5:-1]):
                    if b["close"] < b["open"]:
                        self.active_pois.append({"type": "BULLISH_OB", "top": b["high"], "bottom": b["low"], "created_at": b["timestamp"]})
                        break
            if last["low"] < min(prev_l) and last["close"] < last["open"]:
                for b in reversed(self.htf_history[-5:-1]):
                    if b["close"] > b["open"]:
                        self.active_pois.append({"type": "BEARISH_OB", "top": b["high"], "bottom": b["low"], "created_at": b["timestamp"]})
                        break
            if len(self.active_pois) > 20:
                self.active_pois = self.active_pois[-20:]

        # Fibo on HTF
        if len(self.htf_history) >= 10:
            recent_highs = [b["high"] for b in self.htf_history[-15:]]
            recent_lows = [b["low"] for b in self.htf_history[-15:]]
            sh = max(recent_highs)
            sl = min(recent_lows)
            if self.current_bias == 1:
                self.latest_fibo = FibonacciCalculator.compute_bullish_fibo(sl, sh)
            elif self.current_bias == -1:
                self.latest_fibo = FibonacciCalculator.compute_bearish_fibo(sh, sl)

    def on_bar(self, bar):
        dt = bar["timestamp"]
        d = dt.date()
        t = dt.time()
        gh, gl, gc, go = bar["high"], bar["low"], bar["close"], bar["open"]
        vol = max(1.0, float(bar.get("tick_volume", 1)))
        spread = bar.get("mean_spread", 0.20)

        # Update HTF
        if self.bias_tf != self.exec_tf:
            self._update_htf_bar(bar)
        else:
            self._on_htf_close(bar)

        # VWAP Accumulators
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

        # Manage positions
        if len(self.engine.positions) > 0:
            self.bars_in_trade += 1
            max_hold = 60 if self.exec_tf == "M1" else (24 if self.exec_tf == "M5" else 16)
            if self.bars_in_trade >= max_hold or (t.hour >= 21 and t.minute >= 30):
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
        min_rng = 0.35 if self.exec_tf == "M1" else (0.50 if self.exec_tf == "M5" else 0.80)
        if rng < min_rng:
            return

        upper_wick = gh - max(go, gc)
        lower_wick = min(go, gc) - gl

        # =====================================================================
        # ARCHETYPE 1: VWAP MEAN REVERSION
        # =====================================================================
        if self.archetype == "VWAP_REVERSION":
            # Short Fade
            if gh >= self.upper_band and (upper_wick / rng) >= 0.45 and gc < go:
                stop = round(gh + self.sl_buffer, 2)
                risk = stop - gc
                if 0.80 <= risk <= 6.00:
                    tp = round(gc - (risk * self.rr_target), 2)
                    if self.current_vwap < gc and (gc - self.current_vwap) >= risk * 1.5:
                        tp = round(self.current_vwap, 2)

                    approval = self.governor.evaluate_entry(gc, stop, spread, 0.30, len(self.engine.positions))
                    if approval.approved:
                        pid = self.engine.sell("XAUUSD", approval.lots, stop, tp, comment="VWAP_Short")
                        if pid:
                            self.traded_today += 1
                            return

            # Long Fade
            if gl <= self.lower_band and (lower_wick / rng) >= 0.45 and gc > go:
                stop = round(gl - self.sl_buffer, 2)
                risk = gc - stop
                if 0.80 <= risk <= 6.00:
                    tp = round(gc + (risk * self.rr_target), 2)
                    if self.current_vwap > gc and (self.current_vwap - gc) >= risk * 1.5:
                        tp = round(self.current_vwap, 2)

                    approval = self.governor.evaluate_entry(gc, stop, spread, 0.30, len(self.engine.positions))
                    if approval.approved:
                        pid = self.engine.buy("XAUUSD", approval.lots, stop, tp, comment="VWAP_Long")
                        if pid:
                            self.traded_today += 1
                            return

        # =====================================================================
        # ARCHETYPE 2 & 3: SMC EXPANSION / FIBO OTE
        # =====================================================================
        elif self.archetype in ("SMC_EXPANSION", "SMC_FIBO_OTE"):
            if self.current_bias == 0:
                return

            # BULLISH EXPANSION
            if self.current_bias == 1 and gc > go and (lower_wick / rng) >= 0.35:
                # Fibo OTE Filter
                if self.use_fibo_ote_filter and self.latest_fibo:
                    if not FibonacciCalculator.is_in_golden_pocket(gl, self.latest_fibo, buffer=0.50):
                        return

                # POI Confluence
                buf = 1.00
                pois = [p for p in self.active_pois if p["type"] in ("BULLISH_OB", "BULLISH_IFVG") and (p["bottom"] - buf) <= gl <= (p["top"] + buf)]
                if pois:
                    best = pois[-1]
                    stop = round(best["bottom"] - self.sl_buffer, 2)
                    risk = gc - stop
                    if 1.00 <= risk <= 8.00:
                        approval = self.governor.evaluate_entry(gc, stop, spread, 0.35, len(self.engine.positions))
                        if approval.approved:
                            if self.use_fibo_target and self.latest_fibo:
                                tp = self.latest_fibo.ext_1618
                            else:
                                tp = round(gc + risk * self.rr_target, 2)
                            if tp <= gc or (tp - gc) < risk * 1.2:
                                tp = round(gc + risk * self.rr_target, 2)

                            pid = self.engine.buy("XAUUSD", approval.lots, stop, tp, comment="SMC_Bull")
                            if pid:
                                self.traded_today += 1
                                return

            # BEARISH EXPANSION
            if self.current_bias == -1 and gc < go and (upper_wick / rng) >= 0.35:
                if self.use_fibo_ote_filter and self.latest_fibo:
                    if not FibonacciCalculator.is_in_golden_pocket(gh, self.latest_fibo, buffer=0.50):
                        return

                buf = 1.00
                pois = [p for p in self.active_pois if p["type"] in ("BEARISH_OB", "BEARISH_IFVG") and (p["bottom"] - buf) <= gh <= (p["top"] + buf)]
                if pois:
                    best = pois[-1]
                    stop = round(best["top"] + self.sl_buffer, 2)
                    risk = stop - gc
                    if 1.00 <= risk <= 8.00:
                        approval = self.governor.evaluate_entry(gc, stop, spread, 0.35, len(self.engine.positions))
                        if approval.approved:
                            if self.use_fibo_target and self.latest_fibo:
                                tp = self.latest_fibo.ext_1618
                            else:
                                tp = round(gc - risk * self.rr_target, 2)
                            if tp >= gc or (gc - tp) < risk * 1.2:
                                tp = round(gc - risk * self.rr_target, 2)

                            pid = self.engine.sell("XAUUSD", approval.lots, stop, tp, comment="SMC_Bear")
                            if pid:
                                self.traded_today += 1
                                return


def run_single_clone(clone_id: int, spec: dict, data_cache: dict):
    t0 = time.time()
    strat = MatrixStrategy(
        config_name=spec["name"],
        archetype=spec["archetype"],
        exec_tf=spec["exec_tf"],
        bias_tf=spec["bias_tf"],
        band_multiplier=spec.get("band", 1.8),
        rr_target=spec.get("rr", 2.0),
        use_fibo_target=spec.get("use_fibo_tp", False),
        use_fibo_ote_filter=spec.get("use_fibo_ote", False),
        start_hour=spec.get("start_h", 8),
        start_min=spec.get("start_m", 0),
        end_hour=spec.get("end_h", 16),
        end_min=spec.get("end_m", 30),
        sl_buffer=spec.get("sl_buf", 0.50)
    )

    df = data_cache[spec["exec_tf"]]

    config = AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0)
    engine = EventEngine(config=config, commission_model=CommissionModel(7.0), slippage_model=FixedSlippageModel(0.02))
    engine.reset()
    engine.current_strategy = strat
    strat.set_engine(engine)
    strat.on_init()

    for bar in df.iter_rows(named=True):
        engine.current_time = bar["timestamp"]
        spread = bar.get("mean_spread", 0.22)
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
    elapsed = time.time() - t0

    monthly_pnl = defaultdict(float)
    for tr in engine.closed_trades:
        monthly_pnl[tr.open_time.strftime("%Y-%m")] += tr.net_pnl
    pos_m = sum(1 for v in monthly_pnl.values() if v > 0)
    tot_m = len(monthly_pnl) or 1

    return {
        "id": clone_id,
        "name": spec["name"],
        "archetype": spec["archetype"],
        "exec_tf": spec["exec_tf"],
        "bias_tf": spec["bias_tf"],
        "trades": perf.total_trades,
        "win_rate": round(perf.win_rate_pct, 1),
        "payoff": round(perf.win_loss_ratio, 2),
        "net_pnl": round(perf.net_profit, 2),
        "profit_factor": round(perf.profit_factor, 2),
        "max_dd": round(perf.max_drawdown_pct, 1),
        "months": f"{pos_m}/{tot_m}",
        "months_pct": round((pos_m / tot_m) * 100, 1),
        "calmar": round(perf.calmar_ratio, 2),
        "elapsed_sec": round(elapsed, 2)
    }


def main():
    print("=" * 100)
    print("🥷 NARUTO SHADOW CLONE MATRIX EXPLORATION ENGINE (10.5 MONTHS XAUUSD)")
    print("=" * 100)

    # 1. Preload data cache
    print("[Master Brain] Preloading Parquet Timeframes...")
    t_start = time.time()
    data_cache = {
        "M1": pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet"),
        "M5": pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_M5.parquet"),
        "M15": pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_M15.parquet"),
    }
    print(f"[Master Brain] Loaded M1 ({len(data_cache['M1']):,}), M5 ({len(data_cache['M5']):,}), M15 ({len(data_cache['M15']):,}) in {time.time()-t_start:.1f}s.")

    # 2. Define Shadow Clone Exploration Matrix
    matrix_specs = [
        # --- VWAP CLONES (M1) ---
        {"name": "Clone-01: M1 VWAP 1.8s Full Day (08:00-16:30)", "archetype": "VWAP_REVERSION", "exec_tf": "M1", "bias_tf": "M1", "band": 1.8, "rr": 2.0, "start_h": 8, "start_m": 0, "end_h": 16, "end_m": 30},
        {"name": "Clone-02: M1 VWAP 1.8s Golden Win (10:30-14:30)", "archetype": "VWAP_REVERSION", "exec_tf": "M1", "bias_tf": "M1", "band": 1.8, "rr": 2.0, "start_h": 10, "start_m": 30, "end_h": 14, "end_m": 30},
        {"name": "Clone-03: M1 VWAP 2.0s Golden Win (10:30-14:30)", "archetype": "VWAP_REVERSION", "exec_tf": "M1", "bias_tf": "M1", "band": 2.0, "rr": 2.0, "start_h": 10, "start_m": 30, "end_h": 14, "end_m": 30},
        {"name": "Clone-04: M1 VWAP 1.8s Pure London (08:00-11:30)", "archetype": "VWAP_REVERSION", "exec_tf": "M1", "bias_tf": "M1", "band": 1.8, "rr": 2.0, "start_h": 8, "start_m": 0, "end_h": 11, "end_m": 30},

        # --- VWAP CLONES (M5) ---
        {"name": "Clone-05: M5 VWAP 1.8s Full Day (08:00-16:30)", "archetype": "VWAP_REVERSION", "exec_tf": "M5", "bias_tf": "M5", "band": 1.8, "rr": 2.0, "start_h": 8, "start_m": 0, "end_h": 16, "end_m": 30, "sl_buf": 0.80},
        {"name": "Clone-06: M5 VWAP 1.8s Golden Win (10:30-14:30)", "archetype": "VWAP_REVERSION", "exec_tf": "M5", "bias_tf": "M5", "band": 1.8, "rr": 2.0, "start_h": 10, "start_m": 30, "end_h": 14, "end_m": 30, "sl_buf": 0.80},
        {"name": "Clone-07: M5 VWAP 2.0s Golden Win (10:30-14:30)", "archetype": "VWAP_REVERSION", "exec_tf": "M5", "bias_tf": "M5", "band": 2.0, "rr": 2.0, "start_h": 10, "start_m": 30, "end_h": 14, "end_m": 30, "sl_buf": 0.80},

        # --- SMC EXPANSION CLONES (M15 Exec) ---
        {"name": "Clone-08: M15 SMC (H1 Bias) + 2.0R Target", "archetype": "SMC_EXPANSION", "exec_tf": "M15", "bias_tf": "H1", "rr": 2.0, "sl_buf": 1.50},
        {"name": "Clone-09: M15 SMC (H1 Bias) + 3.0R Target", "archetype": "SMC_EXPANSION", "exec_tf": "M15", "bias_tf": "H1", "rr": 3.0, "sl_buf": 1.50},
        {"name": "Clone-10: M15 SMC (H1 Bias) + 4.0R Target", "archetype": "SMC_EXPANSION", "exec_tf": "M15", "bias_tf": "H1", "rr": 4.0, "sl_buf": 1.50},
        {"name": "Clone-11: M15 SMC (H4 Bias) + 3.0R Target", "archetype": "SMC_EXPANSION", "exec_tf": "M15", "bias_tf": "H4", "rr": 3.0, "sl_buf": 2.00},

        # --- SMC EXPANSION CLONES (M5 Exec) ---
        {"name": "Clone-12: M5 SMC (H1 Bias) + 2.0R Target", "archetype": "SMC_EXPANSION", "exec_tf": "M5", "bias_tf": "H1", "rr": 2.0, "sl_buf": 1.00},
        {"name": "Clone-13: M5 SMC (H1 Bias) + 3.0R Target", "archetype": "SMC_EXPANSION", "exec_tf": "M5", "bias_tf": "H1", "rr": 3.0, "sl_buf": 1.00},

        # --- FIBONACCI GOLDEN POCKET & EXTENSION CLONES ---
        {"name": "Clone-14: M15 SMC + Fibo OTE Golden Pocket (61.8-78.6%) + 3R", "archetype": "SMC_FIBO_OTE", "exec_tf": "M15", "bias_tf": "H1", "rr": 3.0, "use_fibo_ote": True, "sl_buf": 1.50},
        {"name": "Clone-15: M15 SMC + Fibo 1.618 Extension TP (No Filter)", "archetype": "SMC_EXPANSION", "exec_tf": "M15", "bias_tf": "H1", "use_fibo_tp": True, "sl_buf": 1.50},
        {"name": "Clone-16: M15 SMC + Fibo OTE + 1.618 Extension TP", "archetype": "SMC_FIBO_OTE", "exec_tf": "M15", "bias_tf": "H1", "use_fibo_ote": True, "use_fibo_tp": True, "sl_buf": 1.50},
    ]

    print(f"[Master Brain] Deploying {len(matrix_specs)} Shadow Clones across timeframes...")
    results = []
    for idx, spec in enumerate(matrix_specs, 1):
        print(f"  -> Dispatched Clone #{idx:02d}: {spec['name']}...")
        res = run_single_clone(idx, spec, data_cache)
        print(f"     [Result] Net: ${res['net_pnl']:+,.2f} | PF: {res['profit_factor']:.2f} | Win: {res['win_rate']}% | DD: {res['max_dd']}% ({res['elapsed_sec']}s)")
        results.append(res)

    # 3. Sort and Rank Leaderboard
    # Rank primarily by Profit Factor (risk-adjusted quality) then Net PnL
    results.sort(key=lambda r: (r["profit_factor"], r["net_pnl"]), reverse=True)

    print("\n" + "=" * 115)
    print("🏆 SHADOW CLONES MULTI-TIMEFRAME MASTER SCOREBOARD (RANKED BY INSTITUTIONAL HEALTH)")
    print("=" * 115)
    header = f"{'Rank':<5} | {'Configuration':<52} | {'Trades':<6} | {'Win%':<6} | {'Payoff':<6} | {'Net PnL':<11} | {'PF':<5} | {'MaxDD':<6} | {'Months'}"
    print(header)
    print("-" * 115)
    for rank, r in enumerate(results, 1):
        print(f"#{rank:<4} | {r['name']:<52} | {r['trades']:<6} | {r['win_rate']:>5.1f}% | {r['payoff']:>5.2f}x | ${r['net_pnl']:>10,.2f} | {r['profit_factor']:>4.2f} | {r['max_dd']:>5.1f}% | {r['months']}")
    print("=" * 115)

    # 4. Save Artifacts for Single Source of Truth
    out_dir = Path("reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "shadow_clone_leaderboard.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[Master Brain] Saved full leaderboard to: {json_path.resolve()}")


if __name__ == "__main__":
    main()
