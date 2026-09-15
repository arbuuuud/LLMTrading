"""
Strategy 5: Hybrid Session Anchored VWAP + Multi-Timeframe POI (OB, FVG, iFVG, Structure).

Institutional Core Concept:
- Primary Execution Horizon: M1 (Auction Market Theory / Session Anchored VWAP +/- 1.8 to 2.0 Sigma).
- Higher Timeframe Context: M15 aggregated dynamically without lookahead bias.
- Confluence Layers:
  1. M15 Order Blocks (OB): Institutional accumulation/distribution mitigation zones.
  2. M15 Fair Value Gaps (FVG) & Inversion FVGs (iFVG): Dynamic support/resistance flips.
  3. M15 Market Structure (BOS / CHoCH): Macro orderflow direction.
  4. Time-Window Filter: Cutting toxic high-drawdown hours (15:00-16:00 UTC).
- Governed by MonthlyRatchetGovernor.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, time, date
from dataclasses import dataclass
import math

from engine.core.types import OrderDirection, ExitReason
from engine.core.strategy_base import BaseStrategy
from agents.risk_manager.monthly_ratchet_governor import MonthlyRatchetGovernor, RatchetApproval
from strategies.modules.setups.ifvg_detector import InversionFVGDetector, IFVGType
from strategies.modules.triggers.market_structure import MarketStructureDetector, StructureEvent


@dataclass
class ActiveHTFZone:
    zone_type: str       # "BULLISH_OB", "BEARISH_OB", "BULLISH_IFVG", "BEARISH_IFVG", "BULLISH_FVG", "BEARISH_FVG"
    top: float
    bottom: float
    created_at: Any
    mitigations: int = 0


class HybridVWAPPOIScalper(BaseStrategy):
    def __init__(
        self,
        band_multiplier: float = 1.8,
        sl_buffer_dollars: float = 0.50,
        risk_reward_ratio: float = 2.0,
        base_risk_pct: float = 0.5,
        greed_risk_pct: float = 0.25,
        max_bars_hold: int = 60,
        # Ablation / Configuration switches:
        enable_time_filter: bool = True,     # Avoid 15:00 - 16:59 UTC toxic hours
        require_ob_confluence: bool = False, # Must touch M15 Order Block
        require_ifvg_confluence: bool = False, # Must touch M15 FVG or iFVG
        require_structure_bias: bool = False, # Must align with M15 BOS/CHoCH
        poi_buffer_dollars: float = 1.00     # Tolerance distance to POI zone
    ):
        super().__init__("Hybrid_VWAP_HTF_POI_Scalper")
        self.band_multiplier = band_multiplier
        self.sl_buffer = sl_buffer_dollars
        self.risk_reward_ratio = risk_reward_ratio
        self.max_bars_hold = max_bars_hold

        self.enable_time_filter = enable_time_filter
        self.require_ob_confluence = require_ob_confluence
        self.require_ifvg_confluence = require_ifvg_confluence
        self.require_structure_bias = require_structure_bias
        self.poi_buffer = poi_buffer_dollars

        self.governor = MonthlyRatchetGovernor(
            base_risk_pct=base_risk_pct,
            greed_risk_pct=greed_risk_pct,
            max_daily_loss_pct=1.0,
            monthly_loss_cap_pct=3.0,
            cooldown_bars=25
        )

        # M15 Streaming Aggregator & Detectors
        self.current_m15_bar: Optional[Dict[str, Any]] = None
        self.m15_history: List[Dict[str, Any]] = []
        self.ifvg_detector = InversionFVGDetector(min_fvg_size_dollars=0.40)
        self.structure_detector = MarketStructureDetector(pivot_lookback=3)

        # Active POI Zones on M15
        self.active_order_blocks: List[ActiveHTFZone] = []
        self.active_ifvgs: List[ActiveHTFZone] = []
        self.current_m15_bias: int = 0  # +1 Bullish, -1 Bearish

        # VWAP State
        self.current_date: Optional[date] = None
        self.cum_vol: float = 0.0
        self.cum_pv: float = 0.0
        self.cum_p2v: float = 0.0

        self.current_vwap: float = 0.0
        self.current_std: float = 0.0
        self.upper_band: float = 0.0
        self.lower_band: float = 0.0

        self.bars_in_trade: int = 0
        self.traded_today_count: int = 0

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
        self.traded_today_count = 0

        self.current_m15_bar = None
        self.m15_history.clear()
        self.active_order_blocks.clear()
        self.active_ifvgs.clear()
        self.current_m15_bias = 0

    def on_trade_closed(self, trade_record):
        self.governor.on_trade_closed(trade_record.net_pnl)

    def _update_m15_candle(self, m1_bar: Dict[str, Any]):
        """Aggregates incoming M1 bar into M15 bar without lookahead bias."""
        dt: datetime = m1_bar["timestamp"]
        m15_minute = (dt.minute // 15) * 15
        m15_time = dt.replace(minute=m15_minute, second=0, microsecond=0)

        if self.current_m15_bar is None or self.current_m15_bar["timestamp"] != m15_time:
            # Previous M15 bar completed
            if self.current_m15_bar is not None:
                self._on_m15_bar_close(self.current_m15_bar)

            # Start new M15 bar
            self.current_m15_bar = {
                "timestamp": m15_time,
                "open": m1_bar["open"],
                "high": m1_bar["high"],
                "low": m1_bar["low"],
                "close": m1_bar["close"],
                "tick_volume": m1_bar.get("tick_volume", 1)
            }
        else:
            # Update current M15 bar
            self.current_m15_bar["high"] = max(self.current_m15_bar["high"], m1_bar["high"])
            self.current_m15_bar["low"] = min(self.current_m15_bar["low"], m1_bar["low"])
            self.current_m15_bar["close"] = m1_bar["close"]
            self.current_m15_bar["tick_volume"] += m1_bar.get("tick_volume", 1)

    def _on_m15_bar_close(self, bar: Dict[str, Any]):
        """Called whenever an M15 bar closes. Updates all HTF POIs."""
        self.m15_history.append(bar)
        if len(self.m15_history) > 100:
            self.m15_history.pop(0)

        # 1. Update Market Structure
        struct_event = self.structure_detector.update(bar)
        if struct_event in (StructureEvent.BULLISH_CHOCH, StructureEvent.BULLISH_BOS):
            self.current_m15_bias = 1
        elif struct_event in (StructureEvent.BEARISH_CHOCH, StructureEvent.BEARISH_BOS):
            self.current_m15_bias = -1

        # 2. Update FVG and iFVG Detector
        self.ifvg_detector.update(bar)
        active_zones = self.ifvg_detector.get_active_ifvg_zones()
        self.active_ifvgs = [
            ActiveHTFZone(
                zone_type=z["type"],
                top=z["top"],
                bottom=z["bottom"],
                created_at=z["created_at"],
                mitigations=z["mitigations"]
            )
            for z in active_zones
        ]

        # 3. Detect M15 Order Block (Last 5 bars lookback)
        if len(self.m15_history) >= 5:
            last = self.m15_history[-1]
            # Bullish impulse: current high breaks previous 4 highs
            prev_highs = [b["high"] for b in self.m15_history[-5:-1]]
            if last["high"] > max(prev_highs) and last["close"] > last["open"]:
                # Last bearish candle
                for b in reversed(self.m15_history[-5:-1]):
                    if b["close"] < b["open"]:
                        self.active_order_blocks.append(
                            ActiveHTFZone(
                                zone_type="BULLISH_OB",
                                top=b["high"],
                                bottom=b["low"],
                                created_at=b["timestamp"]
                            )
                        )
                        break

            # Bearish impulse: current low breaks previous 4 lows
            prev_lows = [b["low"] for b in self.m15_history[-5:-1]]
            if last["low"] < min(prev_lows) and last["close"] < last["open"]:
                # Last bullish candle
                for b in reversed(self.m15_history[-5:-1]):
                    if b["close"] > b["open"]:
                        self.active_order_blocks.append(
                            ActiveHTFZone(
                                zone_type="BEARISH_OB",
                                top=b["high"],
                                bottom=b["low"],
                                created_at=b["timestamp"]
                            )
                        )
                        break

            # Limit active OBs
            if len(self.active_order_blocks) > 20:
                self.active_order_blocks = self.active_order_blocks[-20:]

    def _is_price_in_zone(self, price: float, zone: ActiveHTFZone) -> bool:
        """Checks if price is within the zone or within the buffer distance."""
        return (zone.bottom - self.poi_buffer) <= price <= (zone.top + self.poi_buffer)

    def _check_htf_support(self, price: float) -> bool:
        """Returns True if price is at a Bullish OB, Bullish iFVG, or Bullish FVG."""
        # Check Bullish OB
        if self.require_ob_confluence:
            ob_hit = any(self._is_price_in_zone(price, ob) for ob in self.active_order_blocks if ob.zone_type == "BULLISH_OB")
            if not ob_hit:
                return False

        # Check Bullish iFVG
        if self.require_ifvg_confluence:
            ifvg_hit = any(self._is_price_in_zone(price, z) for z in self.active_ifvgs if z.zone_type == "BULLISH_IFVG")
            if not ifvg_hit:
                return False

        return True

    def _check_htf_resistance(self, price: float) -> bool:
        """Returns True if price is at a Bearish OB, Bearish iFVG, or Bearish FVG."""
        # Check Bearish OB
        if self.require_ob_confluence:
            ob_hit = any(self._is_price_in_zone(price, ob) for ob in self.active_order_blocks if ob.zone_type == "BEARISH_OB")
            if not ob_hit:
                return False

        # Check Bearish iFVG
        if self.require_ifvg_confluence:
            ifvg_hit = any(self._is_price_in_zone(price, z) for z in self.active_ifvgs if z.zone_type == "BEARISH_IFVG")
            if not ifvg_hit:
                return False

        return True

    def on_bar(self, bar: Dict[str, Any]):
        dt: datetime = bar["timestamp"]
        d = dt.date()
        t = dt.time()

        gh = bar["high"]
        gl = bar["low"]
        gc = bar["close"]
        go = bar["open"]
        vol = max(1.0, float(bar.get("tick_volume", 1)))
        spread = bar.get("mean_spread", 0.20)

        # Update M15 bar tracking
        self._update_m15_candle(bar)

        # Reset daily VWAP accumulators
        if self.current_date != d:
            self.current_date = d
            self.cum_vol = 0.0
            self.cum_pv = 0.0
            self.cum_p2v = 0.0
            self.bars_in_trade = 0
            self.traded_today_count = 0

        # Typical Price = (High + Low + Close) / 3
        tp_price = (gh + gl + gc) / 3.0
        self.cum_vol += vol
        self.cum_pv += tp_price * vol
        self.cum_p2v += (tp_price ** 2) * vol

        # Compute VWAP and Standard Deviation
        self.current_vwap = self.cum_pv / self.cum_vol
        variance = max(0.0, (self.cum_p2v / self.cum_vol) - (self.current_vwap ** 2))
        self.current_std = math.sqrt(variance)

        self.upper_band = self.current_vwap + (self.current_std * self.band_multiplier)
        self.lower_band = self.current_vwap - (self.current_std * self.band_multiplier)

        self.governor.on_new_bar(dt, self.engine.equity)

        # Manage open position hold time
        if len(self.engine.positions) > 0:
            self.bars_in_trade += 1
            if self.bars_in_trade >= self.max_bars_hold:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
                self.bars_in_trade = 0
            return
        else:
            self.bars_in_trade = 0

        # Session Time Filtering
        if self.enable_time_filter:
            # Golden window: 08:00 - 14:45 UTC (Cuts toxic 15:00-16:00 UTC drawdown hours)
            is_trade_window = (8, 0) <= (t.hour, t.minute) <= (14, 45)
        else:
            is_trade_window = (8, 0) <= (t.hour, t.minute) <= (16, 0)

        if not is_trade_window or self.traded_today_count >= 2:
            return

        # Candle rejection metrics
        rng = gh - gl
        if rng < 0.35:
            return

        upper_wick = gh - max(go, gc)
        lower_wick = min(go, gc) - gl

        # =====================================================================
        # SETUP 1: BEARISH MEAN REVERSION (+1.8 / 2.0 Sigma Overextension)
        # =====================================================================
        if gh >= self.upper_band and (upper_wick / rng) >= 0.45 and gc < go:
            # Check Structure Bias
            if self.require_structure_bias and self.current_m15_bias == 1:
                return  # Don't short against strong M15 bullish structure

            # Check POI Resistance (OB / iFVG)
            if not self._check_htf_resistance(gh):
                return

            stop = round(gh + self.sl_buffer, 2)
            risk_dist = stop - gc
            if 0.80 <= risk_dist <= 5.00:
                tp = round(gc - (risk_dist * self.risk_reward_ratio), 2)
                if self.current_vwap < gc and (gc - self.current_vwap) >= risk_dist * 1.5:
                    tp = round(self.current_vwap, 2)

                approval: RatchetApproval = self.governor.evaluate_entry(
                    entry_price=gc,
                    stop_loss=stop,
                    current_spread=spread,
                    max_allowed_spread=0.25,
                    num_open_positions=len(self.engine.positions)
                )

                if approval.approved:
                    pos_id = self.engine.sell(
                        symbol="XAUUSD",
                        volume_lots=approval.lots,
                        stop_loss=stop,
                        take_profit=tp,
                        comment="Hybrid_VWAP_POI_Short"
                    )
                    if pos_id:
                        self.bars_in_trade = 0
                        self.traded_today_count += 1
                        return

        # =====================================================================
        # SETUP 2: BULLISH MEAN REVERSION (-1.8 / 2.0 Sigma Overextension)
        # =====================================================================
        if gl <= self.lower_band and (lower_wick / rng) >= 0.45 and gc > go:
            # Check Structure Bias
            if self.require_structure_bias and self.current_m15_bias == -1:
                return  # Don't buy against strong M15 bearish structure

            # Check POI Support (OB / iFVG)
            if not self._check_htf_support(gl):
                return

            stop = round(gl - self.sl_buffer, 2)
            risk_dist = gc - stop
            if 0.80 <= risk_dist <= 5.00:
                tp = round(gc + (risk_dist * self.risk_reward_ratio), 2)
                if self.current_vwap > gc and (self.current_vwap - gc) >= risk_dist * 1.5:
                    tp = round(self.current_vwap, 2)

                approval: RatchetApproval = self.governor.evaluate_entry(
                    entry_price=gc,
                    stop_loss=stop,
                    current_spread=spread,
                    max_allowed_spread=0.25,
                    num_open_positions=len(self.engine.positions)
                )

                if approval.approved:
                    pos_id = self.engine.buy(
                        symbol="XAUUSD",
                        volume_lots=approval.lots,
                        stop_loss=stop,
                        take_profit=tp,
                        comment="Hybrid_VWAP_POI_Long"
                    )
                    if pos_id:
                        self.bars_in_trade = 0
                        self.traded_today_count += 1
                        return
