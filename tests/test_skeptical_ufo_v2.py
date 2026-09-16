"""
Comprehensive Institutional Backtest & Validation for Skeptical UFO Engine v2.
Compares:
1. Baseline NFC v1 (Simple DBR/RBD with basic ratio)
2. Skeptical UFO v2 (DBR, RBR, RBD, DBD + Skeptical Audit + Discount/Premium New Normal)
"""

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from engine.core.event_engine import EventEngine
from engine.core.types import AccountConfig, ExitReason
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from engine.metrics.performance import PerformanceCalculator
from engine.core.strategy_base import BaseStrategy
from agents.risk_manager.monthly_ratchet_governor import MonthlyRatchetGovernor
from strategies.modules.setups.skeptical_ufo_detector import SkepticalUFODetector, UFOType, ZoneQuality


# Load Data
df_m15 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_M15.parquet")
df_h1 = pl.read_parquet("data/processed/bars/XAUUSD/HTF/XAUUSD_H1.parquet")

df_h1 = df_h1.with_columns([
    pl.col("close").ewm_mean(span=50).alias("ema50"),
    (pl.col("high") - pl.col("low")).rolling_mean(window_size=14).alias("atr14")
])
h1_map = {
    row["timestamp"]: {"close": row["close"], "ema50": row["ema50"], "atr14": row["atr14"] or 5.0}
    for row in df_h1.iter_rows(named=True)
}


class SkepticalUFOStrategy(BaseStrategy):
    """
    Institutional NFC v2 Strategy with Skeptical UFO Auditor & Auction Discount/Premium.
    """
    def __init__(
        self,
        rr_target: float = 2.5,
        min_score: int = 65,
        use_discount_premium: bool = True,
        use_macro_ema: bool = True,
        enable_rbr_dbd: bool = True
    ):
        super().__init__(f"SkepticalUFO_RR{rr_target}_Score{min_score}")
        self.rr_target = rr_target
        self.min_score = min_score
        self.use_discount_premium = use_discount_premium
        self.use_macro_ema = use_macro_ema
        self.enable_rbr_dbd = enable_rbr_dbd

        self.governor = MonthlyRatchetGovernor(
            base_risk_pct=0.5,
            greed_risk_pct=0.25,
            max_daily_loss_pct=1.0,
            monthly_loss_cap_pct=3.0,
            cooldown_bars=8
        )
        self.detector = SkepticalUFODetector(
            min_score_threshold=min_score,
            max_base_bars=3,
            min_departure_ratio=1.6
        )
        self.current_date = None
        self.traded_today = 0

    def on_init(self):
        self.detector.reset()
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

        if self.current_date != d:
            self.current_date = d
            self.traded_today = 0

        self.governor.on_new_bar(dt, self.engine.equity)

        # Update detector and zones
        self.detector.update(bar)

        # Manage positions (End of day close at 21:30 UTC)
        if len(self.engine.positions) > 0:
            if t.hour >= 21 and t.minute >= 30:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
            return

        # Institutional Session Window (08:00 - 16:30 UTC) & Max 1 trade/day for low DD
        if not ((8, 0) <= (t.hour, t.minute) <= (16, 30)) or self.traded_today >= 1:
            return

        # Macro Trend Context
        h1 = self._get_h1(dt)
        is_bull_macro = True
        is_bear_macro = True
        if h1 is not None and self.use_macro_ema:
            c_h1 = h1["close"]
            ema_h1 = h1["ema50"]
            is_bull_macro = (c_h1 >= ema_h1)
            is_bear_macro = (c_h1 <= ema_h1)

        # -----------------------------------------------------------------
        # EVALUATE DEMAND RETEST (BUY AT DISCOUNT)
        # -----------------------------------------------------------------
        if is_bull_macro:
            for z in reversed(self.detector.demand_zones):
                if z.mitigated:
                    continue
                if not self.enable_rbr_dbd and z.zone_type == UFOType.DEMAND_RBR:
                    continue

                # Check if current low penetrates into the Demand zone (Proximal to Distal)
                # with small buffer
                if (z.bottom - 0.40) <= gl <= (z.top + 0.40) and gc > go:
                    # NFC Principle: Only buy if price is in DISCOUNT territory
                    if self.use_discount_premium and not self.detector.is_price_in_discount(gc, z):
                        continue

                    # Mark zone as mitigated/tested
                    z.mitigated = True

                    sl = round(z.bottom - 1.00, 2)
                    risk = gc - sl
                    if 1.20 <= risk <= 6.50:
                        tp = round(gc + risk * self.rr_target, 2)
                        approval = self.governor.evaluate_entry(
                            gc, sl, spread, 0.35, len(self.engine.positions)
                        )
                        if approval.approved:
                            self.engine.buy(
                                "XAUUSD",
                                approval.lots,
                                sl,
                                tp,
                                comment=f"UFO_{z.zone_type.name}_{z.quality.name}"
                            )
                            self.traded_today += 1
                            return

        # -----------------------------------------------------------------
        # EVALUATE SUPPLY RETEST (SELL AT PREMIUM)
        # -----------------------------------------------------------------
        if is_bear_macro:
            for z in reversed(self.detector.supply_zones):
                if z.mitigated:
                    continue
                if not self.enable_rbr_dbd and z.zone_type == UFOType.SUPPLY_DBD:
                    continue

                if (z.bottom - 0.40) <= gh <= (z.top + 0.40) and gc < go:
                    # NFC Principle: Only sell if price is in PREMIUM territory
                    if self.use_discount_premium and not self.detector.is_price_in_premium(gc, z):
                        continue

                    z.mitigated = True

                    sl = round(z.top + 1.00, 2)
                    risk = sl - gc
                    if 1.20 <= risk <= 6.50:
                        tp = round(gc - risk * self.rr_target, 2)
                        approval = self.governor.evaluate_entry(
                            gc, sl, spread, 0.35, len(self.engine.positions)
                        )
                        if approval.approved:
                            self.engine.sell(
                                "XAUUSD",
                                approval.lots,
                                sl,
                                tp,
                                comment=f"UFO_{z.zone_type.name}_{z.quality.name}"
                            )
                            self.traded_today += 1
                            return


def run_experiment(strat, label):
    c = AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0)
    e = EventEngine(config=c, commission_model=CommissionModel(7.0), slippage_model=FixedSlippageModel(0.02))
    e.reset()
    e.current_strategy = strat
    strat.set_engine(e)
    strat.on_init()

    t0 = time.time()
    for bar in df_m15.iter_rows(named=True):
        e.current_time = bar["timestamp"]
        spread = bar.get("mean_spread", 0.25)
        e.current_bid = bar["close"]
        e.current_ask = round(e.current_bid + spread, 3)
        e.current_spread = spread
        e._check_daily_circuit_breaker(e.current_time)
        e._update_positions_on_bar(bar)
        strat.on_bar(bar)
        e.equity_curve.append({
            "timestamp": e.current_time,
            "equity": round(e.equity, 2),
            "balance": round(e.balance, 2)
        })

    for pos_id in list(e.positions.keys()):
        e._close_position_internal(pos_id, ExitReason.END_OF_DATA)

    strat.on_finish()
    perf = PerformanceCalculator.calculate(e.closed_trades, e.equity_curve, c.initial_balance)
    elapsed = time.time() - t0

    # Monthly consistency
    monthly = {}
    for tr in e.closed_trades:
        m_key = tr.open_time.strftime("%Y-%m")
        monthly[m_key] = monthly.get(m_key, 0.0) + tr.net_pnl

    green_m = sum(1 for p in monthly.values() if p > 0)
    tot_m = len(monthly) or 1

    print(
        f"[{label:<55}] in {elapsed:.2f}s -> "
        f"Trades: {perf.total_trades:>3} | "
        f"Win: {perf.win_rate_pct:>5.1f}% | "
        f"Payoff: {perf.win_loss_ratio:>4.2f}x | "
        f"Net: ${perf.net_profit:>10.2f} | "
        f"PF: {perf.profit_factor:>4.2f} | "
        f"Max DD: {perf.max_drawdown_pct:>4.1f}% | "
        f"Months: {green_m}/{tot_m}"
    )
    return perf


if __name__ == "__main__":
    print("=" * 115)
    print("🔬 SKEPTICAL UFO ENGINE v2 BENCHMARK MATRIX (10.5 MONTHS XAUUSD M15)")
    print("=" * 115)

    experiments = [
        ("1. Baseline NFC v1 (Simple DBR/RBD, H1 EMA, RR 2.5)", 
         SkepticalUFOStrategy(rr_target=2.5, min_score=0, use_discount_premium=False, use_macro_ema=True, enable_rbr_dbd=False)),
        ("2. NFC v1 + RBR/DBD Continuation (Unfiltered)", 
         SkepticalUFOStrategy(rr_target=2.5, min_score=0, use_discount_premium=False, use_macro_ema=True, enable_rbr_dbd=True)),
        ("3. Skeptical UFO v2 (Score >= 65, Reversal + Contin)", 
         SkepticalUFOStrategy(rr_target=2.5, min_score=65, use_discount_premium=False, use_macro_ema=True, enable_rbr_dbd=True)),
        ("4. Skeptical UFO v2 + Discount/Premium Auction Rule", 
         SkepticalUFOStrategy(rr_target=2.5, min_score=65, use_discount_premium=True, use_macro_ema=True, enable_rbr_dbd=True)),
        ("5. Skeptical UFO v2 + Discount/Premium + Higher RR (3.0)", 
         SkepticalUFOStrategy(rr_target=3.0, min_score=65, use_discount_premium=True, use_macro_ema=True, enable_rbr_dbd=True)),
        ("6. Skeptical UFO v2 PRIME Zones Only (Score >= 75, RR 3.0)", 
         SkepticalUFOStrategy(rr_target=3.0, min_score=75, use_discount_premium=True, use_macro_ema=True, enable_rbr_dbd=True)),
    ]

    for label, strat in experiments:
        run_experiment(strat, label)
