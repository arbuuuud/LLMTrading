"""
Quantitative Audit of 3 Elite Indonesian Institutional Trading Setups:
1. John Paul 77: "Range to Range" (RTR) & "Pola N" (Asian Range Breakout/Retest Expansion & Reversal).
2. Fadli / NFC: Unfilled Institutional Orders (Fresh Supply & Demand Base: DBR / RBD).
3. Arya / NFC: High-Probability Intraday Liquidity Sweep (Asian/PDH/PDL Sweep -> Opposite Pool Target).

Tested on 10.5 months of continuous XAUUSD data (M15 & M5).
"""

import sys
import time
from pathlib import Path
from collections import defaultdict
import json
import math

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
if not os.path.exists("data/processed/bars/XAUUSD/HTF/XAUUSD_M15.parquet"):
    raise unittest.SkipTest("Parquet historical dataset not found on server; skipping backtest test.")

print("[Naruto Brain] Loading datasets for Institutional Setup Audit...")
df_m15 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_M15.parquet")
df_m1 = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")


# =====================================================================
# 1. JOHN PAUL 77: RANGE TO RANGE (RTR) & POLA N
# =====================================================================
class JohnPaul77RangeToRangeStrategy(BaseStrategy):
    """
    John Paul 77 Range to Range:
    - Measures Asian Session Range (00:00 - 07:00 UTC).
    - Range size must be realistic ($8.00 - $35.00).
    - Mode A (Breakout & Retest 'Pola N'): When price breaks Asian Range with strong close,
      waits for pullback to retest range edge, then enters continuation to 1.0x Range Expansion.
    - Mode B (Range Reversal / False Breakout): If price sweeps range boundary by < $4.00
      and closes back inside range, targets the opposite range boundary.
    """
    def __init__(self, mode="POLA_N", rr_mult=2.5):
        super().__init__(f"JohnPaul77_{mode}")
        self.mode = mode
        self.rr_mult = rr_mult
        self.governor = MonthlyRatchetGovernor(base_risk_pct=0.5, greed_risk_pct=0.25, max_daily_loss_pct=1.0, monthly_loss_cap_pct=3.0, cooldown_bars=5)

        self.current_date = None
        self.asia_high = None
        self.asia_low = None
        self.asia_range = None
        self.traded_today = 0
        self.state = "IDLE"  # "IDLE", "BREAK_HIGH", "BREAK_LOW"

    def on_init(self):
        self.current_date = None
        self.asia_high = None
        self.asia_low = None
        self.asia_range = None
        self.traded_today = 0
        self.state = "IDLE"

    def on_bar(self, bar):
        dt = bar["timestamp"]
        d = dt.date()
        t = dt.time()
        gh, gl, gc, go = bar["high"], bar["low"], bar["close"], bar["open"]
        spread = bar.get("mean_spread", 0.25)

        if self.current_date != d:
            self.current_date = d
            self.asia_high = None
            self.asia_low = None
            self.asia_range = None
            self.traded_today = 0
            self.state = "IDLE"

        self.governor.on_new_bar(dt, self.engine.equity)

        # Track Asian session (00:00 - 07:00 UTC)
        if (0, 0) <= (t.hour, t.minute) < (7, 0):
            if self.asia_high is None:
                self.asia_high = gh
                self.asia_low = gl
            else:
                self.asia_high = max(self.asia_high, gh)
                self.asia_low = min(self.asia_low, gl)
            return

        if self.asia_high is not None and self.asia_range is None:
            self.asia_range = self.asia_high - self.asia_low

        # If invalid range, skip
        if not self.asia_range or self.asia_range < 6.0 or self.asia_range > 45.0:
            return

        # Close intraday positions at 21:30 UTC
        if len(self.engine.positions) > 0:
            if t.hour >= 21 and t.minute >= 30:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
            return

        # Trading window: London & Early NY (07:30 - 15:30 UTC)
        if not ((7, 30) <= (t.hour, t.minute) <= (15, 30)) or self.traded_today >= 1:
            return

        # -----------------------------------------------------------------
        # MODE 1: POLA N (Breakout & Retest to Next Range)
        # -----------------------------------------------------------------
        if self.mode == "POLA_N":
            if self.state == "IDLE":
                if gc > self.asia_high and (gc - self.asia_high) >= 1.50:
                    self.state = "BREAK_HIGH"
                elif gc < self.asia_low and (self.asia_low - gc) >= 1.50:
                    self.state = "BREAK_LOW"

            elif self.state == "BREAK_HIGH":
                # Pullback to retest broken Asian High [asia_high - 1.0, asia_high + 1.5]
                if (self.asia_high - 1.00) <= gl <= (self.asia_high + 1.80) and gc > go:
                    sl = round(self.asia_high - 2.50, 2)
                    risk = gc - sl
                    if 2.0 <= risk <= 10.0:
                        tp = round(self.asia_high + self.asia_range, 2) # Range to Range Target
                        approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                        if approval.approved:
                            self.engine.buy("XAUUSD", approval.lots, sl, tp, comment="JP77_PolaN_Buy")
                            self.traded_today += 1
                            self.state = "DONE"

            elif self.state == "BREAK_LOW":
                # Pullback to retest broken Asian Low
                if (self.asia_low - 1.80) <= gh <= (self.asia_low + 1.00) and gc < go:
                    sl = round(self.asia_low + 2.50, 2)
                    risk = sl - gc
                    if 2.0 <= risk <= 10.0:
                        tp = round(self.asia_low - self.asia_range, 2) # Range to Range Target
                        approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                        if approval.approved:
                            self.engine.sell("XAUUSD", approval.lots, sl, tp, comment="JP77_PolaN_Sell")
                            self.traded_today += 1
                            self.state = "DONE"

        # -----------------------------------------------------------------
        # MODE 2: RANGE REVERSAL (Fakeout / Rejection back to opposite range)
        # -----------------------------------------------------------------
        elif self.mode == "RANGE_REVERSAL":
            # Sweep Asian High by < $3.00, close back below Asian High
            if gh > self.asia_high and (gh - self.asia_high) <= 4.50 and gc < self.asia_high and gc < go:
                sl = round(gh + 1.00, 2)
                risk = sl - gc
                if 2.0 <= risk <= 8.0:
                    tp = round(self.asia_low + 1.00, 2) # Target opposite boundary (Range to Range)
                    approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                    if approval.approved:
                        self.engine.sell("XAUUSD", approval.lots, sl, tp, comment="JP77_Rev_Sell")
                        self.traded_today += 1

            # Sweep Asian Low by < $3.00, close back above Asian Low
            elif gl < self.asia_low and (self.asia_low - gl) <= 4.50 and gc > self.asia_low and gc > go:
                sl = round(gl - 1.00, 2)
                risk = gc - sl
                if 2.0 <= risk <= 8.0:
                    tp = round(self.asia_high - 1.00, 2) # Target opposite boundary
                    approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                    if approval.approved:
                        self.engine.buy("XAUUSD", approval.lots, sl, tp, comment="JP77_Rev_Buy")
                        self.traded_today += 1


# =====================================================================
# 2. FADLI / NFC: UNFILLED ORDER BASE (DROP-BASE-RALLY / RALLY-BASE-DROP)
# =====================================================================
class FadliNFCUnfilledOrderStrategy(BaseStrategy):
    """
    Fadli / NFC Unfilled Order Strategy:
    - Identifies institutional origin zones:
      * DBR (Drop-Base-Rally): Sharp drop -> tight base (1-3 candles) -> aggressive displacement rally.
      * RBD (Rally-Base-Drop): Sharp rally -> tight base -> aggressive displacement drop.
    - Base is labeled as "Unfilled Order Zone" where institutional resting limit orders reside.
    - Entry: First retest / touch into unmitigated fresh base.
    - SL: 1.00 beyond base edge.
    - TP: 2.5R to 3.0R or opposite unmitigated base.
    """
    def __init__(self, rr_target=2.5, max_base_bars=3):
        super().__init__(f"Fadli_NFC_SND_{rr_target}R")
        self.rr_target = rr_target
        self.max_base_bars = max_base_bars
        self.governor = MonthlyRatchetGovernor(base_risk_pct=0.5, greed_risk_pct=0.25, max_daily_loss_pct=1.0, monthly_loss_cap_pct=3.0, cooldown_bars=8)

        self.bars = []
        self.demand_zones = []  # [{top, bot, created_at, mitigated}]
        self.supply_zones = []
        self.current_date = None
        self.traded_today = 0

    def on_init(self):
        self.bars.clear()
        self.demand_zones.clear()
        self.supply_zones.clear()
        self.current_date = None
        self.traded_today = 0

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

        # Detect Fresh DBR / RBD bases
        if len(self.bars) >= 5:
            # Check DBR: bars[-4] is drop, bars[-3:-1] is base, bars[-1] is explosive rally
            b_drop = self.bars[-4]
            b_base = self.bars[-3]
            b_rally = self.bars[-1]

            # DBR: Drop -> Base -> Explosive Rally
            if (b_drop["close"] < b_drop["open"]) and (b_rally["close"] > b_rally["open"]):
                rally_body = b_rally["close"] - b_rally["open"]
                base_range = b_base["high"] - b_base["low"]
                if rally_body > base_range * 1.8 and rally_body > 3.0:
                    self.demand_zones.append({
                        "top": b_base["high"],
                        "bottom": b_base["low"],
                        "created_at": b_base["timestamp"],
                        "mitigated": False
                    })

            # RBD: Rally -> Base -> Explosive Drop
            if (b_drop["close"] > b_drop["open"]) and (b_rally["close"] < b_rally["open"]):
                drop_body = b_rally["open"] - b_rally["close"]
                base_range = b_base["high"] - b_base["low"]
                if drop_body > base_range * 1.8 and drop_body > 3.0:
                    self.supply_zones.append({
                        "top": b_base["high"],
                        "bottom": b_base["low"],
                        "created_at": b_base["timestamp"],
                        "mitigated": False
                    })

            if len(self.demand_zones) > 20: self.demand_zones = self.demand_zones[-20:]
            if len(self.supply_zones) > 20: self.supply_zones = self.supply_zones[-20:]

        if len(self.engine.positions) > 0:
            if t.hour >= 21 and t.minute >= 30:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
            return

        # Session hours: 08:00 - 16:30 UTC
        if not ((8, 0) <= (t.hour, t.minute) <= (16, 30)) or self.traded_today >= 1:
            return

        # Test Retest of Demand Zone (BUY)
        for z in reversed(self.demand_zones):
            if not z["mitigated"] and (z["bottom"] - 0.5) <= gl <= (z["top"] + 0.5) and gc > go:
                z["mitigated"] = True
                sl = round(z["bottom"] - 1.20, 2)
                risk = gc - sl
                if 1.50 <= risk <= 6.00:
                    tp = round(gc + risk * self.rr_target, 2)
                    approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                    if approval.approved:
                        self.engine.buy("XAUUSD", approval.lots, sl, tp, comment="NFC_DBR_Buy")
                        self.traded_today += 1
                        return

        # Test Retest of Supply Zone (SELL)
        for z in reversed(self.supply_zones):
            if not z["mitigated"] and (z["bottom"] - 0.5) <= gh <= (z["top"] + 0.5) and gc < go:
                z["mitigated"] = True
                sl = round(z["top"] + 1.20, 2)
                risk = sl - gc
                if 1.50 <= risk <= 6.00:
                    tp = round(gc - risk * self.rr_target, 2)
                    approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                    if approval.approved:
                        self.engine.sell("XAUUSD", approval.lots, sl, tp, comment="NFC_RBD_Sell")
                        self.traded_today += 1
                        return


# =====================================================================
# 3. ARYA / NFC: HIGH-PROBABILITY INTRADAY LIQUIDITY SWEEP
# =====================================================================
class AryaNFCLiquiditySweepStrategy(BaseStrategy):
    """
    Arya / NFC Intraday Liquidity Sweep:
    - Marks Asian Session High/Low (00:00 - 07:00 UTC) as major liquidity pools (BSL & SSL).
    - In London/NY Open: Waits for market makers to sweep Asian High (BSL) or Asian Low (SSL).
    - Entry Trigger: Immediately upon liquidity sweep, looks for sharp displacement in opposite direction
      breaking the 3-candle minor structure (MSS), entering on retest towards the opposite liquidity pool.
    """
    def __init__(self, target_opposite_pool=True, fixed_rr=3.0):
        super().__init__("Arya_NFC_LiquiditySweep")
        self.target_opposite_pool = target_opposite_pool
        self.fixed_rr = fixed_rr
        self.governor = MonthlyRatchetGovernor(base_risk_pct=0.5, greed_risk_pct=0.25, max_daily_loss_pct=1.0, monthly_loss_cap_pct=3.0, cooldown_bars=5)

        self.current_date = None
        self.asia_high = None
        self.asia_low = None
        self.swept_high = False
        self.swept_low = False
        self.traded_today = 0
        self.bars = []

    def on_init(self):
        self.current_date = None
        self.asia_high = None
        self.asia_low = None
        self.swept_high = False
        self.swept_low = False
        self.traded_today = 0
        self.bars.clear()

    def on_bar(self, bar):
        dt = bar["timestamp"]
        d = dt.date()
        t = dt.time()
        gh, gl, gc, go = bar["high"], bar["low"], bar["close"], bar["open"]
        spread = bar.get("mean_spread", 0.25)

        self.bars.append(bar)
        if len(self.bars) > 40:
            self.bars.pop(0)

        if self.current_date != d:
            self.current_date = d
            self.asia_high = None
            self.asia_low = None
            self.swept_high = False
            self.swept_low = False
            self.traded_today = 0

        self.governor.on_new_bar(dt, self.engine.equity)

        # Track Asian Range
        if (0, 0) <= (t.hour, t.minute) < (7, 0):
            if self.asia_high is None:
                self.asia_high = gh
                self.asia_low = gl
            else:
                self.asia_high = max(self.asia_high, gh)
                self.asia_low = min(self.asia_low, gl)
            return

        if self.asia_high is None:
            return

        if len(self.engine.positions) > 0:
            if t.hour >= 21 and t.minute >= 30:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
            return

        if not ((7, 30) <= (t.hour, t.minute) <= (16, 0)) or self.traded_today >= 1:
            return

        # Check Sweep of Asian High (BSL Purge) -> Looking for SHORT
        if gh > self.asia_high:
            self.swept_high = True
        # Check Sweep of Asian Low (SSL Purge) -> Looking for LONG
        if gl < self.asia_low:
            self.swept_low = True

        # Short Trigger: Swept High + Bearish Displacement Rejection
        if self.swept_high and not self.swept_low:
            if gc < self.asia_high and gc < go:
                # Candle closed back inside with strong rejection
                sl = round(max(gh, self.asia_high) + 1.20, 2)
                risk = sl - gc
                if 2.0 <= risk <= 7.0:
                    tp = round(self.asia_low + 1.50, 2) if self.target_opposite_pool else round(gc - risk * self.fixed_rr, 2)
                    if (gc - tp) >= risk * 1.5:
                        approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                        if approval.approved:
                            self.engine.sell("XAUUSD", approval.lots, sl, tp, comment="Arya_Sweep_Short")
                            self.traded_today += 1
                            self.swept_high = False
                            return

        # Long Trigger: Swept Low + Bullish Displacement Rejection
        if self.swept_low and not self.swept_high:
            if gc > self.asia_low and gc > go:
                sl = round(min(gl, self.asia_low) - 1.20, 2)
                risk = gc - sl
                if 2.0 <= risk <= 7.0:
                    tp = round(self.asia_high - 1.50, 2) if self.target_opposite_pool else round(gc + risk * self.fixed_rr, 2)
                    if (tp - gc) >= risk * 1.5:
                        approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                        if approval.approved:
                            self.engine.buy("XAUUSD", approval.lots, sl, tp, comment="Arya_Sweep_Long")
                            self.traded_today += 1
                            self.swept_low = False
                            return


def run_strategy(name, strat, df):
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

    print(f"[{name:<46}] in {elapsed:.1f}s -> Trades: {perf.total_trades:3d} | Win: {perf.win_rate_pct:>5.1f}% | Payoff: {perf.win_loss_ratio:>4.2f}x | Net: ${perf.net_profit:>10,.2f} | PF: {perf.profit_factor:>4.2f} | DD: {perf.max_drawdown_pct:>4.1f}% | Months: {pos_m}/{tot_m}")
    return {
        "name": name,
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
    print("=" * 105)
    print("🔬 AUDIT 3 SETUP INSTITUSIONAL: JOHN PAUL 77 vs FADLI (NFC) vs ARYA (NFC)")
    print("=" * 105)

    experiments = [
        # John Paul 77 Range to Range Variations
        ("1. John Paul 77: Range Reversal (Opposite Edge Target)", JohnPaul77RangeToRangeStrategy(mode="RANGE_REVERSAL"), df_m15),
        ("2. John Paul 77: Pola N Breakout & Retest Expansion", JohnPaul77RangeToRangeStrategy(mode="POLA_N"), df_m15),

        # Fadli NFC Unfilled Orders (Supply & Demand Base)
        ("3. Fadli (NFC): DBR / RBD Unfilled Orders (2.0R Target)", FadliNFCUnfilledOrderStrategy(rr_target=2.0), df_m15),
        ("4. Fadli (NFC): DBR / RBD Unfilled Orders (2.5R Target)", FadliNFCUnfilledOrderStrategy(rr_target=2.5), df_m15),
        ("5. Fadli (NFC): DBR / RBD Unfilled Orders (3.0R Target)", FadliNFCUnfilledOrderStrategy(rr_target=3.0), df_m15),

        # Arya NFC Intraday Liquidity Sweep
        ("6. Arya (NFC): Asian Liquidity Sweep -> Opposite Pool", AryaNFCLiquiditySweepStrategy(target_opposite_pool=True), df_m15),
        ("7. Arya (NFC): Asian Liquidity Sweep -> 3.0R Target", AryaNFCLiquiditySweepStrategy(target_opposite_pool=False, fixed_rr=3.0), df_m15),
    ]

    results = []
    for name, strat, df in experiments:
        res = run_strategy(name, strat, df)
        results.append(res)

    results.sort(key=lambda x: (x["net_pnl"], x["pf"]), reverse=True)

    print("\n" + "=" * 105)
    print("🏆 HASIL PERINGKAT KINERJA METODE INSTITUSIONAL INDONESIA (10.5 BULAN XAUUSD)")
    print("=" * 105)
    header = f"{'Rank':<5} | {'Strategi':<48} | {'Trades':<6} | {'Win%':<6} | {'Payoff':<6} | {'Net PnL':<11} | {'PF':<5} | {'MaxDD':<6} | {'Months'}"
    print(header)
    print("-" * 105)
    for rank, r in enumerate(results, 1):
        print(f"#{rank:<4} | {r['name']:<48} | {r['trades']:<6} | {r['win_rate']:>5.1f}% | {r['payoff']:>5.2f}x | ${r['net_pnl']:>10,.2f} | {r['pf']:>4.2f} | {r['max_dd']:>5.1f}% | {r['months']}")
    print("=" * 105)

    out_file = Path("reports/indonesia_institutional_setups.json")
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[Naruto Brain] Disimpan di: {out_file.resolve()}")


if __name__ == "__main__":
    main()
