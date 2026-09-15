"""
Strategy 6: Priority 2 - Intraday SMC Expansion Sniper (M5 / M15 with H1 Context).
Institutional Mechanics:
- Macro Structure (H1): Market Structure Shift (BOS / CHoCH) sets the Daily Orderflow Bias.
- Institutional Zones (M15 / H1):
  * Order Blocks (OB): Unmitigated institutional accumulation/distribution footprints.
  * Inversion Fair Value Gaps (iFVG): Flipped polarity support/resistance zones.
- Entry Trigger (M5 / M15):
  * Retracement into active POI zone during London & New York sessions (08:00 - 16:30 UTC).
  * Rejection wick confirmation in alignment with H1 orderflow.
- Callisto Trade Management (Twin Positions):
  * Order A (50% lots): Partial TP at 1.5R - 2.0R to bank guaranteed cash.
  * Order B (50% lots): Once Order A reaches TP1, move Order B SL to Breakeven (+spread buffer).
    Order B targets 4.0R - 5.0R expansion.
- Intraday Discipline: Maximum 1 setup per day; close all open intraday positions before midnight UTC.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, time, date
from dataclasses import dataclass
import math

from engine.core.types import OrderDirection, ExitReason
from engine.core.strategy_base import BaseStrategy
from agents.risk_manager.monthly_ratchet_governor import MonthlyRatchetGovernor, RatchetApproval
from strategies.modules.setups.ifvg_detector import InversionFVGDetector
from strategies.modules.triggers.market_structure import MarketStructureDetector, StructureEvent


@dataclass
class ActivePOI:
    poi_type: str  # "BULLISH_OB", "BEARISH_OB", "BULLISH_IFVG", "BEARISH_IFVG"
    top: float
    bottom: float
    created_at: Any
    mitigations: int = 0


class IntradaySMCStrategy(BaseStrategy):
    def __init__(
        self,
        base_risk_pct: float = 0.50,
        greed_risk_pct: float = 0.25,
        max_daily_loss_pct: float = 1.0,
        monthly_loss_cap_pct: float = 3.0,
        tp1_r: float = 1.5,                 # Partial TP ratio
        tp2_r: float = 4.0,                 # Runner TP ratio
        sl_buffer_dollars: float = 1.50,    # Buffer beyond POI edge
        poi_tolerance_dollars: float = 1.00,# Retracement buffer into POI
        start_hour: int = 8,
        start_minute: int = 0,
        end_hour: int = 16,
        end_minute: int = 30
    ):
        super().__init__("Intraday_SMC_Sniper")
        self.base_risk = base_risk_pct
        self.tp1_r = tp1_r
        self.tp2_r = tp2_r
        self.sl_buffer = sl_buffer_dollars
        self.poi_tolerance = poi_tolerance_dollars
        self.start_time = (start_hour, start_minute)
        self.end_time = (end_hour, end_minute)

        self.governor = MonthlyRatchetGovernor(
            base_risk_pct=base_risk_pct,
            greed_risk_pct=greed_risk_pct,
            max_daily_loss_pct=max_daily_loss_pct,
            monthly_loss_cap_pct=monthly_loss_cap_pct,
            cooldown_bars=10
        )

        # H1 Aggregation & Structure
        self.current_h1_bar: Optional[Dict[str, Any]] = None
        self.h1_history: List[Dict[str, Any]] = []
        self.h1_structure = MarketStructureDetector(pivot_lookback=3)
        self.h1_bias: int = 0  # +1 Bullish, -1 Bearish

        # M15/H1 POI Detectors
        self.ifvg_detector = InversionFVGDetector(min_fvg_size_dollars=0.80)
        self.active_pois: List[ActivePOI] = []

        # Callisto Twin Tracking
        # { "pair_id": { "master_id": ..., "runner_id": ..., "entry": ..., "risk_dist": ..., "dir": ..., "be_moved": False } }
        self.active_twins: Dict[str, Dict[str, Any]] = {}

        self.current_date: Optional[date] = None
        self.traded_today: int = 0

    def on_init(self):
        self.current_date = None
        self.traded_today = 0
        self.current_h1_bar = None
        self.h1_history.clear()
        self.h1_bias = 0
        self.active_pois.clear()
        self.active_twins.clear()

    def on_trade_closed(self, trade_record):
        self.governor.on_trade_closed(trade_record.net_pnl)

    def _update_h1_bar(self, bar: Dict[str, Any]):
        """Aggregates incoming bars into H1 bars to detect H1 Structure & Bias."""
        dt: datetime = bar["timestamp"]
        h1_time = dt.replace(minute=0, second=0, microsecond=0)

        if self.current_h1_bar is None or self.current_h1_bar["timestamp"] != h1_time:
            if self.current_h1_bar is not None:
                self._on_h1_bar_close(self.current_h1_bar)

            self.current_h1_bar = {
                "timestamp": h1_time,
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "tick_volume": bar.get("tick_volume", 1)
            }
        else:
            self.current_h1_bar["high"] = max(self.current_h1_bar["high"], bar["high"])
            self.current_h1_bar["low"] = min(self.current_h1_bar["low"], bar["low"])
            self.current_h1_bar["close"] = bar["close"]
            self.current_h1_bar["tick_volume"] += bar.get("tick_volume", 1)

    def _on_h1_bar_close(self, h1_bar: Dict[str, Any]):
        self.h1_history.append(h1_bar)
        if len(self.h1_history) > 100:
            self.h1_history.pop(0)

        # 1. Update H1 Market Structure
        struct = self.h1_structure.update(h1_bar)
        if struct in (StructureEvent.BULLISH_CHOCH, StructureEvent.BULLISH_BOS):
            self.h1_bias = 1
        elif struct in (StructureEvent.BEARISH_CHOCH, StructureEvent.BEARISH_BOS):
            self.h1_bias = -1

        # 2. Update H1 iFVG / FVG
        self.ifvg_detector.update(h1_bar)
        active_zones = self.ifvg_detector.get_active_ifvg_zones()
        self.active_pois = [
            ActivePOI(
                poi_type=z["type"],
                top=z["top"],
                bottom=z["bottom"],
                created_at=z["created_at"],
                mitigations=z["mitigations"]
            )
            for z in active_zones
        ]

        # 3. Detect H1 Order Blocks (Lookback 5)
        if len(self.h1_history) >= 5:
            last = self.h1_history[-1]
            prev_highs = [b["high"] for b in self.h1_history[-5:-1]]
            prev_lows = [b["low"] for b in self.h1_history[-5:-1]]

            # Bullish OB: impulse up breaking 4 prior highs
            if last["high"] > max(prev_highs) and last["close"] > last["open"]:
                for b in reversed(self.h1_history[-5:-1]):
                    if b["close"] < b["open"]:
                        self.active_pois.append(
                            ActivePOI("BULLISH_OB", top=b["high"], bottom=b["low"], created_at=b["timestamp"])
                        )
                        break

            # Bearish OB: impulse down breaking 4 prior lows
            if last["low"] < min(prev_lows) and last["close"] < last["open"]:
                for b in reversed(self.h1_history[-5:-1]):
                    if b["close"] > b["open"]:
                        self.active_pois.append(
                            ActivePOI("BEARISH_OB", top=b["high"], bottom=b["low"], created_at=b["timestamp"])
                        )
                        break

        # Cap POI count
        if len(self.active_pois) > 25:
            self.active_pois = self.active_pois[-25:]

    def _manage_callisto_twins(self):
        """Callisto Trade Management: When Order A (Partial TP1) hits, move Order B SL to Breakeven."""
        for key, twin in list(self.active_twins.items()):
            master_id = twin["master_pos_id"]
            runner_id = twin["runner_pos_id"]

            if master_id not in self.engine.positions and runner_id in self.engine.positions:
                runner_pos = self.engine.positions[runner_id]
                if not twin["be_moved"]:
                    if twin["dir"] == OrderDirection.BUY:
                        new_sl = round(twin["entry"] + 0.20, 2)  # BE + spread buffer
                        if runner_pos.stop_loss < new_sl:
                            runner_pos.stop_loss = new_sl
                    else:
                        new_sl = round(twin["entry"] - 0.20, 2)
                        if runner_pos.stop_loss > new_sl:
                            runner_pos.stop_loss = new_sl
                    twin["be_moved"] = True

            if runner_id not in self.engine.positions and master_id not in self.engine.positions:
                self.active_twins.pop(key, None)

    def on_bar(self, bar: Dict[str, Any]):
        dt: datetime = bar["timestamp"]
        d = dt.date()
        t = dt.time()

        gh = bar["high"]
        gl = bar["low"]
        gc = bar["close"]
        go = bar["open"]
        spread = bar.get("mean_spread", 0.25)

        self._update_h1_bar(bar)

        if self.current_date != d:
            self.current_date = d
            self.traded_today = 0

        self.governor.on_new_bar(dt, self.engine.equity)

        # 1. Manage Active Positions & Callisto Breakeven
        if len(self.engine.positions) > 0:
            self._manage_callisto_twins()

            # End of day session close (21:30 UTC): close all intraday trades
            if t.hour >= 21 and t.minute >= 30:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
            return

        # 2. Session Trading Window Filter (08:00 - 16:30 UTC)
        is_window = self.start_time <= (t.hour, t.minute) <= self.end_time
        if not is_window or self.traded_today >= 1:
            return

        # Need directional H1 bias
        if self.h1_bias == 0:
            return

        rng = gh - gl
        if rng < 0.60:
            return

        upper_wick = gh - max(go, gc)
        lower_wick = min(go, gc) - gl

        # =====================================================================
        # SETUP 1: BULLISH INTRADAY EXPANSION (H1 Bias == 1)
        # =====================================================================
        if self.h1_bias == 1 and gc > go and (lower_wick / rng) >= 0.35:
            # Check if low pierced an active Bullish POI (OB or iFVG)
            valid_pois = [
                poi for poi in self.active_pois
                if poi.poi_type in ("BULLISH_OB", "BULLISH_IFVG")
                and (poi.bottom - self.poi_tolerance) <= gl <= (poi.top + self.poi_tolerance)
            ]

            if valid_pois:
                best_poi = valid_pois[-1]
                stop = round(best_poi.bottom - self.sl_buffer, 2)
                risk_dist = gc - stop

                if 1.50 <= risk_dist <= 8.00:
                    approval: RatchetApproval = self.governor.evaluate_entry(
                        entry_price=gc,
                        stop_loss=stop,
                        current_spread=spread,
                        max_allowed_spread=0.35,
                        num_open_positions=len(self.engine.positions)
                    )

                    if approval.approved:
                        total_lots = approval.lots
                        lots_a = round(max(0.01, total_lots * 0.50), 2)
                        lots_b = round(max(0.01, total_lots - lots_a), 2)

                        tp1 = round(gc + (risk_dist * self.tp1_r), 2)
                        tp2 = round(gc + (risk_dist * self.tp2_r), 2)

                        pid_a = self.engine.buy("XAUUSD", lots_a, stop, tp1, comment="Intra_A_Partial")
                        pid_b = self.engine.buy("XAUUSD", lots_b, stop, tp2, comment="Intra_B_Runner")

                        if pid_a and pid_b:
                            pair_id = f"{pid_a}_{pid_b}"
                            self.active_twins[pair_id] = {
                                "master_pos_id": pid_a,
                                "runner_pos_id": pid_b,
                                "entry": gc,
                                "risk_dist": risk_dist,
                                "dir": OrderDirection.BUY,
                                "be_moved": False
                            }
                            self.traded_today += 1
                            return

        # =====================================================================
        # SETUP 2: BEARISH INTRADAY EXPANSION (H1 Bias == -1)
        # =====================================================================
        if self.h1_bias == -1 and gc < go and (upper_wick / rng) >= 0.35:
            valid_pois = [
                poi for poi in self.active_pois
                if poi.poi_type in ("BEARISH_OB", "BEARISH_IFVG")
                and (poi.bottom - self.poi_tolerance) <= gh <= (poi.top + self.poi_tolerance)
            ]

            if valid_pois:
                best_poi = valid_pois[-1]
                stop = round(best_poi.top + self.sl_buffer, 2)
                risk_dist = stop - gc

                if 1.50 <= risk_dist <= 8.00:
                    approval: RatchetApproval = self.governor.evaluate_entry(
                        entry_price=gc,
                        stop_loss=stop,
                        current_spread=spread,
                        max_allowed_spread=0.35,
                        num_open_positions=len(self.engine.positions)
                    )

                    if approval.approved:
                        total_lots = approval.lots
                        lots_a = round(max(0.01, total_lots * 0.50), 2)
                        lots_b = round(max(0.01, total_lots - lots_a), 2)

                        tp1 = round(gc - (risk_dist * self.tp1_r), 2)
                        tp2 = round(gc - (risk_dist * self.tp2_r), 2)

                        pid_a = self.engine.sell("XAUUSD", lots_a, stop, tp1, comment="Intra_A_Partial")
                        pid_b = self.engine.sell("XAUUSD", lots_b, stop, tp2, comment="Intra_B_Runner")

                        if pid_a and pid_b:
                            pair_id = f"{pid_a}_{pid_b}"
                            self.active_twins[pair_id] = {
                                "master_pos_id": pid_a,
                                "runner_pos_id": pid_b,
                                "entry": gc,
                                "risk_dist": risk_dist,
                                "dir": OrderDirection.SELL,
                                "be_moved": False
                            }
                            self.traded_today += 1
                            return
