"""
Hybrid Synthesis: Fadli NFC Unfilled Orders + Fibonacci Golden Pocket + Macro H1 EMA Filter.
Production-ready strategy class for Engine 2 (M15 Intraday).
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.core.strategy_base import BaseStrategy
from engine.core.types import ExitReason
from agents.risk_manager.monthly_ratchet_governor import MonthlyRatchetGovernor
from strategies.modules.setups.skeptical_ufo_detector import SkepticalUFODetector


class NFCFiboHybridStrategy(BaseStrategy):
    def __init__(self, rr_target=2.5, use_macro_ema=True, use_fibo_ote=False, min_score=35, h1_map=None):
        super().__init__(f"NFC_UFO_RR{rr_target}")
        self.rr_target = rr_target
        self.use_macro_ema = use_macro_ema
        self.use_fibo_ote = use_fibo_ote
        self.min_score = min_score
        self.h1_map = h1_map or {}
        self.governor = MonthlyRatchetGovernor(
            base_risk_pct=0.5, greed_risk_pct=0.25, max_daily_loss_pct=1.0, monthly_loss_cap_pct=3.0, cooldown_bars=8
        )
        self.detector = SkepticalUFODetector(
            min_score_threshold=min_score,
            max_base_bars=3,
            min_departure_ratio=1.6
        )
        self.bars = []
        self.current_date = None
        self.traded_today = 0

    @property
    def demand_zones(self):
        return self.detector.demand_zones

    @property
    def supply_zones(self):
        return self.detector.supply_zones

    def on_init(self):
        self.bars.clear()
        self.detector.reset()
        self.current_date = None
        self.traded_today = 0

    def _get_h1(self, dt):
        if not self.h1_map:
            return None
        t = dt.replace(minute=0, second=0, microsecond=0)
        return self.h1_map.get(t, None)

    def update_zones_only(self, bar):
        """
        Updates internal M15 bar history and detects DBR/RBR/RBD/DBD supply/demand zones
        without evaluating trade entry triggers.
        Used for Historical Catch-Up Sync on reconnect.
        """
        self.bars.append(bar)
        if len(self.bars) > 60:
            self.bars.pop(0)
        self.detector.update(bar)

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

        # Update Skeptical UFO Detector
        self.detector.update(bar)

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
        if h1 is not None and self.use_macro_ema:
            c_h1 = h1["close"]
            ema_h1 = h1["ema50"]
            is_bull_macro = (c_h1 >= ema_h1)
            is_bear_macro = (c_h1 <= ema_h1)

        # Retest Demand (BUY AT DISCOUNT)
        if is_bull_macro:
            for z in reversed(self.detector.demand_zones):
                if not z.mitigated and (z.bottom - 0.50) <= gl <= (z.top + 0.50) and gc > go:
                    z.mitigated = True
                    sl = round(z.bottom - 1.00, 2)
                    risk = gc - sl
                    if 1.20 <= risk <= 6.50:
                        tp = round(gc + risk * self.rr_target, 2)
                        approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                        if approval.approved:
                            self.engine.buy("XAUUSD", approval.lots, sl, tp, comment=f"UFO_{z.zone_type.name}")
                            self.traded_today += 1
                            return

        # Retest Supply (SELL AT PREMIUM)
        if is_bear_macro:
            for z in reversed(self.detector.supply_zones):
                if not z.mitigated and (z.bottom - 0.50) <= gh <= (z.top + 0.50) and gc < go:
                    z.mitigated = True
                    sl = round(z.top + 1.00, 2)
                    risk = sl - gc
                    if 1.20 <= risk <= 6.50:
                        tp = round(gc - risk * self.rr_target, 2)
                        approval = self.governor.evaluate_entry(gc, sl, spread, 0.35, len(self.engine.positions))
                        if approval.approved:
                            self.engine.sell("XAUUSD", approval.lots, sl, tp, comment=f"UFO_{z.zone_type.name}")
                            self.traded_today += 1
                            return
