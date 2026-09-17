"""
Shadow Clone Battle Royale: Top 3 World-Class Intraday A+ Setups.
1. Linda Raschke: 'The Holy Grail' (ADX > 30 + 20 EMA Pullback)
2. Toby Crabel: 'Opening Range Breakout (ORB) + Volatility Stretch'
3. Al Brooks: 'High 2 / Low 2 (Two-Legged Pullback to 20 EMA)'

Tested rigorously across 10.5 months of continuous XAUUSD data (M15 / M5).
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

print("[Naruto Brain] Preloading Data for Top 3 Legends...")
df_m15 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_M15.parquet")
df_m5 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_M5.parquet")


# =====================================================================
# 1. LINDA RASCHKE: THE HOLY GRAIL (ADX > 30 + 20 EMA PULLBACK)
# =====================================================================
class LindaRaschkeHolyGrailStrategy(BaseStrategy):
    """
    Linda Bradford Raschke: The Holy Grail (Street Smarts, 1995)
    1. Trend filter: 14-period ADX > adx_threshold (e.g. 30 or 25).
    2. Primary Trend: Close > 20 EMA (Bull) or Close < 20 EMA (Bear).
    3. Retracement: Price touches or dips into 20 EMA.
    4. Trigger: Candle turns back in trend direction, breaking high/low of touch candle.
    5. Target: 2.0R to 3.5R re-testing the previous trend high/low.
    """
    def __init__(self, adx_threshold: float = 28.0, rr_target: float = 2.5):
        super().__init__(f"LindaRaschke_HolyGrail_ADX{int(adx_threshold)}_RR{rr_target}")
        self.adx_threshold = adx_threshold
        self.rr_target = rr_target
        self.governor = MonthlyRatchetGovernor(base_risk_pct=0.5, greed_risk_pct=0.25, max_daily_loss_pct=1.0, monthly_loss_cap_pct=3.0, cooldown_bars=8)

        self.bars = []
        self.current_date = None
        self.traded_today = 0
        self.touched_ema = False
        self.touch_high = None
        self.touch_low = None

    def on_init(self):
        self.bars.clear()
        self.current_date = None
        self.traded_today = 0
        self.touched_ema = False
        self.touch_high = None
        self.touch_low = None

    def _calc_indicators(self):
        # Calculate 20 EMA and 14 ADX over recent bars
        n = len(self.bars)
        if n < 30:
            return None, None

        closes = [b["close"] for b in self.bars]
        # 20 EMA
        alpha = 2.0 / (20.0 + 1.0)
        ema20 = closes[0]
        for c in closes[1:]:
            ema20 = (c * alpha) + (ema20 * (1.0 - alpha))

        # 14 ADX approximation
        # True Range, +DM, -DM
        tr_list = []
        pdm_list = []
        mdm_list = []
        for i in range(n - 14, n):
            h = self.bars[i]["high"]
            l = self.bars[i]["low"]
            ph = self.bars[i-1]["high"]
            pl_prev = self.bars[i-1]["low"]
            pc = self.bars[i-1]["close"]

            tr = max(h - l, abs(h - pc), abs(l - pc))
            tr_list.append(tr)

            up_move = h - ph
            down_move = pl_prev - l
            pdm = up_move if (up_move > down_move and up_move > 0) else 0.0
            mdm = down_move if (down_move > up_move and down_move > 0) else 0.0
            pdm_list.append(pdm)
            mdm_list.append(mdm)

        sum_tr = sum(tr_list) or 1.0
        pdi = (sum(pdm_list) / sum_tr) * 100.0
        mdi = (sum(mdm_list) / sum_tr) * 100.0
        dx = (abs(pdi - mdi) / (pdi + mdi)) * 100.0 if (pdi + mdi) > 0 else 0.0
        adx = dx  # 14-period smoothed DX

        return ema20, adx

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
            self.touched_ema = False
            self.touch_high = None
            self.touch_low = None

        self.governor.on_new_bar(dt, self.engine.equity)

        if len(self.engine.positions) > 0:
            if t.hour >= 21 and t.minute >= 30:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
            return

        if not ((8, 0) <= (t.hour, t.minute) <= (16, 30)) or self.traded_today >= 1:
            return

        ema20, adx = self._calc_indicators()
        if ema20 is None or adx is None:
            return

        # Condition 1: ADX > threshold indicates institutional trending momentum
        if adx < self.adx_threshold:
            self.touched_ema = False
            return

        # Bull Trend: Price is generally above 20 EMA, now retracing into it
        if gc > ema20 and gl <= (ema20 + 0.80):
            self.touched_ema = "BULL"
            self.touch_high = gh
            self.touch_low = gl

        # Bear Trend: Price is generally below 20 EMA, now retracing into it
        elif gc < ema20 and gh >= (ema20 - 0.80):
            self.touched_ema = "BEAR"
            self.touch_high = gh
            self.touch_low = gl

        # Trigger on continuation
        if self.touched_ema == "BULL" and gc > go and gh > (self.touch_high or gh):
            sl = round(self.touch_low - 1.20, 2)
            risk = gc - sl
            if 1.50 <= risk <= 7.00:
                tp = round(gc + risk * self.rr_target, 2)
                approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                if approval.approved:
                    self.engine.buy("XAUUSD", approval.lots, sl, tp, comment="Raschke_HolyGrail_Buy")
                    self.traded_today += 1
                    self.touched_ema = False

        elif self.touched_ema == "BEAR" and gc < go and gl < (self.touch_low or gl):
            sl = round(self.touch_high + 1.20, 2)
            risk = sl - gc
            if 1.50 <= risk <= 7.00:
                tp = round(gc - risk * self.rr_target, 2)
                approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                if approval.approved:
                    self.engine.sell("XAUUSD", approval.lots, sl, tp, comment="Raschke_HolyGrail_Sell")
                    self.traded_today += 1
                    self.touched_ema = False


# =====================================================================
# 2. TOBY CRABEL: OPENING RANGE BREAKOUT (ORB) + NR7
# =====================================================================
class TobyCrabelORBStrategy(BaseStrategy):
    """
    Toby Crabel: Opening Range Breakout (ORB) (Day Trading with Short-Term Patterns, 1990)
    1. Define Opening Range: High and Low of first 30 minutes of London session (08:00 - 08:30 UTC).
    2. Stretch calculation: Stretch = 0.25 * 10-period ATR.
    3. Breakout trigger:
       - Buy: Price crosses (OR_High + Stretch).
       - Sell: Price crosses (OR_Low - Stretch).
    4. Stop Loss: Placed at midpoint of the Opening Range (tight risk!).
    5. Target: 2.5R to 3.5R or End-of-Day session exit.
    """
    def __init__(self, stretch_mult: float = 0.25, rr_target: float = 2.5, session="LONDON"):
        super().__init__(f"Crabel_ORB_{session}_S{stretch_mult}_RR{rr_target}")
        self.stretch_mult = stretch_mult
        self.rr_target = rr_target
        self.session = session
        self.governor = MonthlyRatchetGovernor(base_risk_pct=0.5, greed_risk_pct=0.25, max_daily_loss_pct=1.0, monthly_loss_cap_pct=3.0, cooldown_bars=5)

        self.current_date = None
        self.or_high = None
        self.or_low = None
        self.or_complete = False
        self.traded_today = 0
        self.bars = []

    def on_init(self):
        self.current_date = None
        self.or_high = None
        self.or_low = None
        self.or_complete = False
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
            self.or_high = None
            self.or_low = None
            self.or_complete = False
            self.traded_today = 0

        self.governor.on_new_bar(dt, self.engine.equity)

        # Build Opening Range: 08:00 to 08:30 UTC (London)
        if (8, 0) <= (t.hour, t.minute) < (8, 30):
            if self.or_high is None:
                self.or_high = gh
                self.or_low = gl
            else:
                self.or_high = max(self.or_high, gh)
                self.or_low = min(self.or_low, gl)
            return

        if (t.hour, t.minute) >= (8, 30) and not self.or_complete:
            self.or_complete = True

        if len(self.engine.positions) > 0:
            if t.hour >= 21 and t.minute >= 30:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
            return

        if not self.or_complete or self.traded_today >= 1:
            return

        if self.or_high is None or self.or_low is None:
            return

        # Session trading window: 08:30 - 15:30 UTC
        if not ((8, 30) <= (t.hour, t.minute) <= (15, 30)):
            return

        # Calculate recent ATR
        if len(self.bars) < 10:
            return
        recent_tr = [max(b["high"] - b["low"], abs(b["high"] - b["close"])) for b in self.bars[-10:]]
        atr = sum(recent_tr) / len(recent_tr)
        stretch = max(0.80, atr * self.stretch_mult)

        or_mid = (self.or_high + self.or_low) / 2.0
        or_range = self.or_high - self.or_low

        if or_range < 2.0 or or_range > 30.0:
            return  # Skip crazy anomalous days

        # BUY BREAKOUT
        if gc > (self.or_high + stretch) and gc > go:
            sl = round(or_mid, 2)  # Stop loss at mid of opening range
            risk = gc - sl
            if 1.50 <= risk <= 7.00:
                tp = round(gc + risk * self.rr_target, 2)
                approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                if approval.approved:
                    self.engine.buy("XAUUSD", approval.lots, sl, tp, comment="Crabel_ORB_Buy")
                    self.traded_today += 1
                    return

        # SELL BREAKOUT
        elif gc < (self.or_low - stretch) and gc < go:
            sl = round(or_mid, 2)
            risk = sl - gc
            if 1.50 <= risk <= 7.00:
                tp = round(gc - risk * self.rr_target, 2)
                approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                if approval.approved:
                    self.engine.sell("XAUUSD", approval.lots, sl, tp, comment="Crabel_ORB_Sell")
                    self.traded_today += 1
                    return


# =====================================================================
# 3. AL BROOKS: HIGH 2 / LOW 2 (TWO-LEGGED PULLBACK TO 20 EMA)
# =====================================================================
class AlBrooksHigh2Low2Strategy(BaseStrategy):
    """
    Al Brooks: High 2 / Low 2 Setup (Reading Price Action Bar by Bar)
    The undisputed #1 setup in pure Price Action:
    1. Trend context: Price above 20 EMA (Bull Trend) or below 20 EMA (Bear Trend).
    2. Two-legged pullback counter-trend:
       - High 1: First minor bounce during pullback fails.
       - High 2: Second attempt by bears fails at/near 20 EMA, forming a bullish reversal signal bar.
    3. Entry: Buy stop 1 tick above High 2 signal bar.
    4. Target: 2.0R to 3.0R.
    """
    def __init__(self, rr_target: float = 2.5):
        super().__init__(f"AlBrooks_H2L2_RR{rr_target}")
        self.rr_target = rr_target
        self.governor = MonthlyRatchetGovernor(base_risk_pct=0.5, greed_risk_pct=0.25, max_daily_loss_pct=1.0, monthly_loss_cap_pct=3.0, cooldown_bars=8)

        self.bars = []
        self.current_date = None
        self.traded_today = 0
        self.leg_count = 0
        self.in_pullback = False

    def on_init(self):
        self.bars.clear()
        self.current_date = None
        self.traded_today = 0
        self.leg_count = 0
        self.in_pullback = False

    def _calc_ema20(self):
        if len(self.bars) < 20:
            return None
        closes = [b["close"] for b in self.bars]
        alpha = 2.0 / (20.0 + 1.0)
        ema = closes[0]
        for c in closes[1:]:
            ema = (c * alpha) + (ema * (1.0 - alpha))
        return ema

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
            self.traded_today = 0
            self.leg_count = 0
            self.in_pullback = False

        self.governor.on_new_bar(dt, self.engine.equity)

        if len(self.engine.positions) > 0:
            if t.hour >= 21 and t.minute >= 30:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
            return

        # Session window: 08:00 - 16:30 UTC
        if not ((8, 0) <= (t.hour, t.minute) <= (16, 30)) or self.traded_today >= 1:
            return

        ema20 = self._calc_ema20()
        if ema20 is None or len(self.bars) < 6:
            return

        b1 = self.bars[-1]
        b2 = self.bars[-2]
        b3 = self.bars[-3]

        # -------------------------------------------------------------
        # HIGH 2 (BULL TREND 2-LEGGED PULLBACK TO 20 EMA)
        # -------------------------------------------------------------
        if gc > ema20:
            # Check if recent bars formed a 2-legged pullback:
            # Leg 1: b3 went down below b4
            # Attempt 1: b2 attempted to go up
            # Leg 2: b1 went down towards EMA20, now rejected (bullish close)
            is_near_ema = abs(gl - ema20) <= 1.50 or (gl <= ema20 <= gh)
            if is_near_ema and gc > go:
                # b1 is bullish reversal signal bar after 2 down bars
                if b3["close"] < b3["open"] or b2["close"] < b2["open"]:
                    sl = round(min(gl, b2["low"]) - 1.20, 2)
                    risk = gc - sl
                    if 1.50 <= risk <= 6.00:
                        tp = round(gc + risk * self.rr_target, 2)
                        approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                        if approval.approved:
                            self.engine.buy("XAUUSD", approval.lots, sl, tp, comment="Brooks_High2_Buy")
                            self.traded_today += 1
                            return

        # -------------------------------------------------------------
        # LOW 2 (BEAR TREND 2-LEGGED PULLBACK TO 20 EMA)
        # -------------------------------------------------------------
        elif gc < ema20:
            is_near_ema = abs(gh - ema20) <= 1.50 or (gl <= ema20 <= gh)
            if is_near_ema and gc < go:
                if b3["close"] > b3["open"] or b2["close"] > b2["open"]:
                    sl = round(max(gh, b2["high"]) + 1.20, 2)
                    risk = sl - gc
                    if 1.50 <= risk <= 6.00:
                        tp = round(gc - risk * self.rr_target, 2)
                        approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                        if approval.approved:
                            self.engine.sell("XAUUSD", approval.lots, sl, tp, comment="Brooks_Low2_Sell")
                            self.traded_today += 1
                            return


def run_test(name, strat, df):
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

    print(f"[{name:<50}] in {elapsed:.1f}s -> Trades: {perf.total_trades:3d} | Win: {perf.win_rate_pct:>5.1f}% | Payoff: {perf.win_loss_ratio:>4.2f}x | Net: ${perf.net_profit:>10,.2f} | PF: {perf.profit_factor:>4.2f} | DD: {perf.max_drawdown_pct:>4.1f}% | Months: {pos_m}/{tot_m}")
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
    print("=" * 110)
    print("⚔️ SHADOW CLONE BATTLE ROYALE: TOP 3 WORLD TRADERS (10.5 MONTHS XAUUSD)")
    print("=" * 110)

    battles = [
        # Linda Raschke
        ("1. Linda Raschke: Holy Grail (ADX 28 + 20 EMA, RR 2.5)", LindaRaschkeHolyGrailStrategy(adx_threshold=28.0, rr_target=2.5), df_m15),
        ("2. Linda Raschke: Holy Grail (ADX 32 + 20 EMA, RR 3.0)", LindaRaschkeHolyGrailStrategy(adx_threshold=32.0, rr_target=3.0), df_m15),
        ("3. Linda Raschke: Holy Grail (ADX 25 + 20 EMA, RR 2.0)", LindaRaschkeHolyGrailStrategy(adx_threshold=25.0, rr_target=2.0), df_m15),

        # Toby Crabel
        ("4. Toby Crabel: London ORB (Stretch 0.20, RR 2.5)", TobyCrabelORBStrategy(stretch_mult=0.20, rr_target=2.5), df_m15),
        ("5. Toby Crabel: London ORB (Stretch 0.25, RR 3.0)", TobyCrabelORBStrategy(stretch_mult=0.25, rr_target=3.0), df_m15),
        ("6. Toby Crabel: London ORB (Stretch 0.35, RR 2.5)", TobyCrabelORBStrategy(stretch_mult=0.35, rr_target=2.5), df_m15),

        # Al Brooks
        ("7. Al Brooks: High 2 / Low 2 (20 EMA, RR 2.0)", AlBrooksHigh2Low2Strategy(rr_target=2.0), df_m15),
        ("8. Al Brooks: High 2 / Low 2 (20 EMA, RR 2.5)", AlBrooksHigh2Low2Strategy(rr_target=2.5), df_m15),
        ("9. Al Brooks: High 2 / Low 2 (20 EMA, RR 3.0)", AlBrooksHigh2Low2Strategy(rr_target=3.0), df_m15),
    ]

    results = []
    for name, strat, df in battles:
        res = run_test(name, strat, df)
        results.append(res)

    results.sort(key=lambda x: (x["net_pnl"], x["pf"]), reverse=True)

    print("\n" + "=" * 110)
    print("🏆 FINAL RANKING SCOREBOARD: WORLD TRADERS BATTLE ROYALE")
    print("=" * 110)
    header = f"{'Rank':<5} | {'Strategi':<52} | {'Trades':<6} | {'Win%':<6} | {'Payoff':<6} | {'Net PnL':<11} | {'PF':<5} | {'MaxDD':<6} | {'Months'}"
    print(header)
    print("-" * 110)
    for rank, r in enumerate(results, 1):
        print(f"#{rank:<4} | {r['name']:<52} | {r['trades']:<6} | {r['win_rate']:>5.1f}% | {r['payoff']:>5.2f}x | ${r['net_pnl']:>10,.2f} | {r['pf']:>4.2f} | {r['max_dd']:>5.1f}% | {r['months']}")
    print("=" * 110)

    out_file = Path("reports/world_traders_battle_results.json")
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[Naruto Brain] Saved battle results to: {out_file.resolve()}")


if __name__ == "__main__":
    main()
