"""
Institutional Skeptical UFO (Unfilled Orders) & Supply-Demand Detector v2.
Adopts the Nusantara FX (NFC - Fadli & Dwiyan Anggara) Market Acceptance & Auction Principles:
1. Prices do not bounce from lines; they bounce from unexecuted institutional limit orders (UFO).
2. Tight sideway/base represents fair-value consensus. When broken by impulse (BOS),
   the previous price becomes 'Cheap' (Discount) for Demand or 'Expensive' (Premium) for Supply.
3. Incorporates a Skeptical Auditor Agent (Red Team) scoring 0-100 to eliminate false bases/noise.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import math


class UFOType(Enum):
    DEMAND_DBR = "DEMAND_DBR"  # Drop-Base-Rally (Reversal Demand)
    DEMAND_RBR = "DEMAND_RBR"  # Rally-Base-Rally (Continuation Demand)
    SUPPLY_RBD = "SUPPLY_RBD"  # Rally-Base-Drop (Reversal Supply)
    SUPPLY_DBD = "SUPPLY_DBD"  # Drop-Base-Drop (Continuation Supply)


class ZoneQuality(Enum):
    PRIME = "PRIME"          # Score >= 80 (Eligible for Smart Limit / High Confidence)
    STANDARD = "STANDARD"    # Score 65-79 (Requires Bar-Close Rejection Confirmation)
    SKEPTIC_REJECTED = "REJECTED"  # Score < 65 (False Base / Congestion / Trapped Liquidity)


@dataclass
class UFOZone:
    zone_type: UFOType
    top: float             # Proximal Line (nearest to current price)
    bottom: float          # Distal Line (Stop Loss anchor)
    mid: float
    created_at: Any
    score: int
    quality: ZoneQuality
    reasons: List[str] = field(default_factory=list)
    has_fvg: bool = False
    fvg_gap_size: float = 0.0
    departure_velocity: float = 0.0
    base_bar_count: int = 1
    tested_count: int = 0
    mitigated: bool = False
    new_normal_high: Optional[float] = None  # Highest price reached after departure (for Demand)
    new_normal_low: Optional[float] = None   # Lowest price reached after departure (for Supply)

    @property
    def height(self) -> float:
        return max(0.01, self.top - self.bottom)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "zone_type": self.zone_type.value,
            "type_short": self.zone_type.value.replace("DEMAND_", "").replace("SUPPLY_", ""),
            "top": round(self.top, 2),
            "bottom": round(self.bottom, 2),
            "mid": round(self.mid, 2),
            "created_at": str(self.created_at),
            "score": self.score,
            "quality": self.quality.value,
            "reasons": self.reasons,
            "has_fvg": self.has_fvg,
            "fvg_gap_size": self.fvg_gap_size,
            "departure_velocity": self.departure_velocity,
            "base_bar_count": self.base_bar_count,
            "tested_count": self.tested_count,
            "mitigated": self.mitigated,
            "new_normal_high": round(self.new_normal_high, 2) if self.new_normal_high else None,
            "new_normal_low": round(self.new_normal_low, 2) if self.new_normal_low else None,
        }

    def __getitem__(self, item: str) -> Any:
        if item in ("zone_type", "quality"):
            val = getattr(self, item)
            return val.value if hasattr(val, "value") else str(val)
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)


class SkepticalUFODetector:
    """
    Skeptical Institutional UFO Detector.
    Scans candlestick sequences for RBR, DBR, RBD, DBD patterns and audits them
    with institutional microstructure criteria.
    """
    def __init__(
        self,
        min_score_threshold: int = 65,
        max_base_bars: int = 4,
        min_departure_ratio: float = 1.6,
        min_fvg_dollars: float = 0.30,
        max_active_zones: int = 20
    ):
        self.min_score_threshold = min_score_threshold
        self.max_base_bars = max_base_bars
        self.min_departure_ratio = min_departure_ratio
        self.min_fvg_dollars = min_fvg_dollars
        self.max_active_zones = max_active_zones

        self.bars: List[Dict[str, Any]] = []
        self.demand_zones: List[UFOZone] = []
        self.supply_zones: List[UFOZone] = []

    def reset(self):
        self.bars.clear()
        self.demand_zones.clear()
        self.supply_zones.clear()

    def update(self, bar: Dict[str, Any]) -> List[UFOZone]:
        """
        Ingests a completed bar, updates zone lifecycle (mitigation & New Normal tracking),
        and detects new verified UFO zones.
        """
        self.bars.append(bar)
        if len(self.bars) > 120:
            self.bars.pop(0)

        # 1. Update existing zones with current bar (Check mitigation & expand New Normal)
        self._track_lifecycle(bar)

        # 2. Scan for new UFO formations
        new_zones = self._detect_ufo_formations()
        return new_zones

    def _track_lifecycle(self, bar: Dict[str, Any]):
        c_high = bar["high"]
        c_low = bar["low"]
        c_close = bar["close"]

        # Track demand zones
        for z in self.demand_zones:
            if not z.mitigated:
                # Update New Normal High if price continues moving up
                if z.new_normal_high is None or c_high > z.new_normal_high:
                    z.new_normal_high = c_high
                
                # Check if zone is invalidated: close breaks below distal line
                if c_close < z.bottom:
                    z.mitigated = True

        # Track supply zones
        for z in self.supply_zones:
            if not z.mitigated:
                # Update New Normal Low if price continues moving down
                if z.new_normal_low is None or c_low < z.new_normal_low:
                    z.new_normal_low = c_low

                # Check if zone is invalidated: close breaks above distal line
                if c_close > z.top:
                    z.mitigated = True

    def _detect_ufo_formations(self) -> List[UFOZone]:
        n = len(self.bars)
        if n < 6:
            return []

        # We look at recent windows: [Leg 1] -> [Base (1..max_base_bars)] -> [Leg 2 / Departure]
        # Leg 2 is the most recently completed bar (self.bars[-1]) or sequence [-2, -1]
        leg2 = self.bars[-1]
        leg2_is_bull = leg2["close"] > leg2["open"]
        leg2_is_bear = leg2["close"] < leg2["open"]

        discovered: List[UFOZone] = []

        # Scan different base lengths (1 to max_base_bars)
        for base_len in range(1, self.max_base_bars + 1):
            if n < 2 + base_len:
                continue

            base_bars = self.bars[-1 - base_len: -1]
            leg1 = self.bars[-1 - base_len - 1]

            leg1_is_bull = leg1["close"] > leg1["open"]
            leg1_is_bear = leg1["close"] < leg1["open"]

            # Compute Base dimensions
            base_high = max(b["high"] for b in base_bars)
            base_low = min(b["low"] for b in base_bars)
            base_range = max(0.20, base_high - base_low)
            avg_base_body = sum(abs(b["close"] - b["open"]) for b in base_bars) / len(base_bars)

            # Leg 2 (Departure) dimensions
            leg2_range = leg2["high"] - leg2["low"]
            leg2_body = abs(leg2["close"] - leg2["open"])
            velocity_ratio = leg2_body / base_range if base_range > 0 else 0

            # -------------------------------------------------------------
            # CASE A: DEMAND PATTERNS (Leg 2 is Bullish Departure)
            # -------------------------------------------------------------
            if leg2_is_bull and velocity_ratio >= self.min_departure_ratio:
                # Determine subtype
                ufo_type = UFOType.DEMAND_RBR if leg1_is_bull else UFOType.DEMAND_DBR
                
                # Check for Fair Value Gap (Imbalance)
                # FVG in Bullish Departure: leg2 Low > leg1 High (or base bar high)
                has_fvg = False
                fvg_size = 0.0
                prior_high = max(leg1["high"], max(b["high"] for b in base_bars[:-1]) if len(base_bars) > 1 else leg1["high"])
                if leg2["low"] > prior_high:
                    fvg_size = leg2["low"] - prior_high
                    has_fvg = (fvg_size >= self.min_fvg_dollars)

                # Proximal & Distal lines
                # Institutional convention: Proximal is highest body/wick of base, Distal is lowest low of base
                proximal = base_high
                distal = base_low

                # Run Skeptical Audit
                score, reasons, quality = self._audit_demand_zone(
                    base_bars=base_bars,
                    leg1=leg1,
                    leg2=leg2,
                    velocity_ratio=velocity_ratio,
                    has_fvg=has_fvg,
                    fvg_size=fvg_size,
                    base_range=base_range
                )

                if score >= self.min_score_threshold:
                    zone = UFOZone(
                        zone_type=ufo_type,
                        top=proximal,
                        bottom=distal,
                        mid=(proximal + distal) / 2.0,
                        created_at=base_bars[-1]["timestamp"],
                        score=score,
                        quality=quality,
                        reasons=reasons,
                        has_fvg=has_fvg,
                        fvg_gap_size=round(fvg_size, 2),
                        departure_velocity=round(velocity_ratio, 2),
                        base_bar_count=base_len,
                        new_normal_high=leg2["high"]
                    )
                    # Check for duplicate
                    if not self._is_duplicate_zone(zone, self.demand_zones):
                        self.demand_zones.append(zone)
                        discovered.append(zone)
                        break  # Found best base length for this departure

            # -------------------------------------------------------------
            # CASE B: SUPPLY PATTERNS (Leg 2 is Bearish Departure)
            # -------------------------------------------------------------
            elif leg2_is_bear and velocity_ratio >= self.min_departure_ratio:
                ufo_type = UFOType.SUPPLY_DBD if leg1_is_bear else UFOType.SUPPLY_RBD

                # Check for Fair Value Gap (Imbalance)
                # FVG in Bearish Departure: leg2 High < leg1 Low (or base bar low)
                has_fvg = False
                fvg_size = 0.0
                prior_low = min(leg1["low"], min(b["low"] for b in base_bars[:-1]) if len(base_bars) > 1 else leg1["low"])
                if leg2["high"] < prior_low:
                    fvg_size = prior_low - leg2["high"]
                    has_fvg = (fvg_size >= self.min_fvg_dollars)

                proximal = base_low
                distal = base_high

                score, reasons, quality = self._audit_supply_zone(
                    base_bars=base_bars,
                    leg1=leg1,
                    leg2=leg2,
                    velocity_ratio=velocity_ratio,
                    has_fvg=has_fvg,
                    fvg_size=fvg_size,
                    base_range=base_range
                )

                if score >= self.min_score_threshold:
                    zone = UFOZone(
                        zone_type=ufo_type,
                        top=distal,
                        bottom=proximal,
                        mid=(proximal + distal) / 2.0,
                        created_at=base_bars[-1]["timestamp"],
                        score=score,
                        quality=quality,
                        reasons=reasons,
                        has_fvg=has_fvg,
                        fvg_gap_size=round(fvg_size, 2),
                        departure_velocity=round(velocity_ratio, 2),
                        base_bar_count=base_len,
                        new_normal_low=leg2["low"]
                    )
                    if not self._is_duplicate_zone(zone, self.supply_zones):
                        self.supply_zones.append(zone)
                        discovered.append(zone)
                        break

        # Trim zones
        if len(self.demand_zones) > self.max_active_zones:
            self.demand_zones = self.demand_zones[-self.max_active_zones:]
        if len(self.supply_zones) > self.max_active_zones:
            self.supply_zones = self.supply_zones[-self.max_active_zones:]

        return discovered

    def _audit_demand_zone(
        self, base_bars, leg1, leg2, velocity_ratio, has_fvg, fvg_size, base_range
    ):
        """
        Skeptical Red-Team Auditor for Demand UFO Zones (0-100 score).
        Demands proof of institutional participation before granting pass.
        """
        score = 0
        reasons = []

        # 1. Departure Velocity & Displacement (Max 30 pts)
        if velocity_ratio >= 2.5:
            score += 30
            reasons.append(f"Explosive Departure ({velocity_ratio:.1f}x base range)")
        elif velocity_ratio >= 1.8:
            score += 20
            reasons.append(f"Strong Departure ({velocity_ratio:.1f}x base range)")
        else:
            score += 10

        # 2. Fair Value Imbalance (FVG) Test (Max 25 pts)
        if has_fvg and fvg_size >= 0.50:
            score += 25
            reasons.append(f"Clean FVG Imbalance (+${fvg_size:.2f})")
        elif has_fvg:
            score += 15
            reasons.append(f"Moderate FVG (+${fvg_size:.2f})")
        else:
            reasons.append("No clean FVG (wick overlap)")

        # 3. Base Tightness & Accumulation Duration (Max 25 pts)
        base_count = len(base_bars)
        if base_count <= 2 and base_range <= 3.50:
            score += 25
            reasons.append(f"Ideal Tight Base ({base_count} bars, ${base_range:.2f} wide)")
        elif base_count <= 3 and base_range <= 5.00:
            score += 15
            reasons.append(f"Compact Base ({base_count} bars)")
        else:
            score -= 10
            reasons.append(f"Messy/Wide Base ({base_count} bars, ${base_range:.2f})")

        # 4. Volume Expansion on Departure (Max 20 pts)
        recent_vol = [b.get("tick_volume", 1) for b in self.bars[-20:]]
        avg_vol = sum(recent_vol) / len(recent_vol) if recent_vol else 1.0
        leg2_vol = leg2.get("tick_volume", 1)
        vol_ratio = leg2_vol / avg_vol if avg_vol > 0 else 1.0

        if vol_ratio >= 1.4:
            score += 20
            reasons.append(f"Volume Surge ({vol_ratio:.1f}x avg)")
        elif vol_ratio >= 1.1:
            score += 10
            reasons.append(f"Volume Expansion ({vol_ratio:.1f}x avg)")
        else:
            reasons.append("Weak Volume on departure")

        # Cap score
        score = max(0, min(100, score))
        if score >= 80:
            quality = ZoneQuality.PRIME
        elif score >= 65:
            quality = ZoneQuality.STANDARD
        else:
            quality = ZoneQuality.SKEPTIC_REJECTED

        return score, reasons, quality

    def _audit_supply_zone(
        self, base_bars, leg1, leg2, velocity_ratio, has_fvg, fvg_size, base_range
    ):
        """
        Skeptical Red-Team Auditor for Supply UFO Zones (0-100 score).
        """
        score = 0
        reasons = []

        # 1. Departure Velocity & Displacement (Max 30 pts)
        if velocity_ratio >= 2.5:
            score += 30
            reasons.append(f"Explosive Departure ({velocity_ratio:.1f}x base range)")
        elif velocity_ratio >= 1.8:
            score += 20
            reasons.append(f"Strong Departure ({velocity_ratio:.1f}x base range)")
        else:
            score += 10

        # 2. Fair Value Imbalance (FVG) Test (Max 25 pts)
        if has_fvg and fvg_size >= 0.50:
            score += 25
            reasons.append(f"Clean FVG Imbalance (-${fvg_size:.2f})")
        elif has_fvg:
            score += 15
            reasons.append(f"Moderate FVG (-${fvg_size:.2f})")
        else:
            reasons.append("No clean FVG (wick overlap)")

        # 3. Base Tightness & Distribution Duration (Max 25 pts)
        base_count = len(base_bars)
        if base_count <= 2 and base_range <= 3.50:
            score += 25
            reasons.append(f"Ideal Tight Base ({base_count} bars, ${base_range:.2f} wide)")
        elif base_count <= 3 and base_range <= 5.00:
            score += 15
            reasons.append(f"Compact Base ({base_count} bars)")
        else:
            score -= 10
            reasons.append(f"Messy/Wide Base ({base_count} bars, ${base_range:.2f})")

        # 4. Volume Expansion (Max 20 pts)
        recent_vol = [b.get("tick_volume", 1) for b in self.bars[-20:]]
        avg_vol = sum(recent_vol) / len(recent_vol) if recent_vol else 1.0
        leg2_vol = leg2.get("tick_volume", 1)
        vol_ratio = leg2_vol / avg_vol if avg_vol > 0 else 1.0

        if vol_ratio >= 1.4:
            score += 20
            reasons.append(f"Volume Surge ({vol_ratio:.1f}x avg)")
        elif vol_ratio >= 1.1:
            score += 10
            reasons.append(f"Volume Expansion ({vol_ratio:.1f}x avg)")
        else:
            reasons.append("Weak Volume on departure")

        score = max(0, min(100, score))
        if score >= 80:
            quality = ZoneQuality.PRIME
        elif score >= 65:
            quality = ZoneQuality.STANDARD
        else:
            quality = ZoneQuality.SKEPTIC_REJECTED

        return score, reasons, quality

    def _is_duplicate_zone(self, new_zone: UFOZone, zone_list: List[UFOZone]) -> bool:
        """Avoids adding overlapping duplicate zones from slightly different base lengths."""
        for z in zone_list:
            if not z.mitigated:
                overlap = min(z.top, new_zone.top) - max(z.bottom, new_zone.bottom)
                if overlap > 0 and (overlap / min(z.height, new_zone.height)) >= 0.70:
                    # Overlaps significantly with an existing active zone
                    return True
        return False

    def is_price_in_discount(self, current_price: float, zone: UFOZone) -> bool:
        """
        NFC 'New Normal' Principle:
        Only buy if current price is in the DISCOUNT (Cheap) half (< 50% equilibrium)
        relative to the New Normal High created after departure.
        """
        if zone.new_normal_high is None:
            return True
        total_swing = zone.new_normal_high - zone.bottom
        if total_swing <= 1.0:
            return True
        discount_threshold = zone.bottom + (total_swing * 0.50)
        return current_price <= discount_threshold

    def is_price_in_premium(self, current_price: float, zone: UFOZone) -> bool:
        """
        NFC 'New Normal' Principle:
        Only sell if current price is in the PREMIUM (Expensive) half (> 50% equilibrium)
        relative to the New Normal Low created after departure.
        """
        if zone.new_normal_low is None:
            return True
        total_swing = zone.top - zone.new_normal_low
        if total_swing <= 1.0:
            return True
        premium_threshold = zone.new_normal_low + (total_swing * 0.50)
        return current_price >= premium_threshold
