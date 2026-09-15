"""
Institutional Supply & Demand Detector (RBR and DBD).
Identifies Rally-Base-Rally (Demand) and Drop-Base-Drop (Supply) order flow footprints
with Fair Value Imbalance.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum


class ZoneType(Enum):
    DEMAND_RBR = "DEMAND_RBR"
    SUPPLY_DBD = "SUPPLY_DBD"


@dataclass
class SupplyDemandZone:
    zone_type: ZoneType
    high: float
    low: float
    mid: float
    timestamp: Any
    tested_count: int = 0


class SupplyDemandDetector:
    def __init__(self, max_base_bars: int = 3, min_impulse_ratio: float = 1.5):
        self.max_base_bars = max_base_bars
        self.min_impulse_ratio = min_impulse_ratio
        self.active_zones: List[SupplyDemandZone] = []
        self.history: List[Dict[str, Any]] = []

    def update(self, bar: Dict[str, Any]) -> Optional[SupplyDemandZone]:
        self.history.append(bar)
        if len(self.history) > 100:
            self.history.pop(0)

        n = len(self.history)
        if n < 4:
            return None

        # Look for [Leg 1, Base (1..N bars), Leg 2]
        leg2 = self.history[-1]
        leg2_body = abs(leg2["close"] - leg2["open"])
        leg2_range = leg2["high"] - leg2["low"]

        # Check for DBD (Drop - Base - Drop)
        if leg2["close"] < leg2["open"]:
            # Leg 2 is bearish
            for base_len in range(1, self.max_base_bars + 1):
                if n < 2 + base_len:
                    continue
                leg1 = self.history[-1 - base_len - 1]
                if leg1["close"] >= leg1["open"]:
                    continue  # Leg 1 must be bearish for DBD

                base_bars = self.history[-1 - base_len: -1]
                avg_base_body = sum(abs(b["close"] - b["open"]) for b in base_bars) / len(base_bars)
                # Check volume expansion on leg 2
                recent_vol = [b.get("tick_volume", 0) for b in self.history[-20:]]
                avg_vol = (sum(recent_vol) / len(recent_vol)) if recent_vol else 1
                leg2_vol = leg2.get("tick_volume", 0)

                if leg2_body > avg_base_body * self.min_impulse_ratio and leg2_vol >= avg_vol * 1.1:
                    # Valid DBD Supply Zone created at Base
                    zone_high = max(b["high"] for b in base_bars)
                    zone_low = min(b["low"] for b in base_bars)
                    zone = SupplyDemandZone(
                        zone_type=ZoneType.SUPPLY_DBD,
                        high=zone_high,
                        low=zone_low,
                        mid=(zone_high + zone_low) / 2.0,
                        timestamp=base_bars[-1]["timestamp"]
                    )
                    self.active_zones.append(zone)
                    if len(self.active_zones) > 30:
                        self.active_zones.pop(0)
                    return zone

        # Check for RBR (Rally - Base - Rally)
        elif leg2["close"] > leg2["open"]:
            # Leg 2 is bullish
            for base_len in range(1, self.max_base_bars + 1):
                if n < 2 + base_len:
                    continue
                leg1 = self.history[-1 - base_len - 1]
                if leg1["close"] <= leg1["open"]:
                    continue  # Leg 1 must be bullish for RBR

                base_bars = self.history[-1 - base_len: -1]
                avg_base_body = sum(abs(b["close"] - b["open"]) for b in base_bars) / len(base_bars)
                recent_vol = [b.get("tick_volume", 0) for b in self.history[-20:]]
                avg_vol = (sum(recent_vol) / len(recent_vol)) if recent_vol else 1
                leg2_vol = leg2.get("tick_volume", 0)

                if leg2_body > avg_base_body * self.min_impulse_ratio and leg2_vol >= avg_vol * 1.1:
                    # Valid RBR Demand Zone created at Base
                    zone_high = max(b["high"] for b in base_bars)
                    zone_low = min(b["low"] for b in base_bars)
                    zone = SupplyDemandZone(
                        zone_type=ZoneType.DEMAND_RBR,
                        high=zone_high,
                        low=zone_low,
                        mid=(zone_high + zone_low) / 2.0,
                        timestamp=base_bars[-1]["timestamp"]
                    )
                    self.active_zones.append(zone)
                    if len(self.active_zones) > 30:
                        self.active_zones.pop(0)
                    return zone

        return None

    def is_price_in_supply_zone(self, price: float) -> bool:
        for z in reversed(self.active_zones):
            if z.zone_type == ZoneType.SUPPLY_DBD and z.low <= price <= z.high + 0.10:
                return True
        return False

    def is_price_in_demand_zone(self, price: float) -> bool:
        for z in reversed(self.active_zones):
            if z.zone_type == ZoneType.DEMAND_RBR and z.low - 0.10 <= price <= z.high:
                return True
        return False
