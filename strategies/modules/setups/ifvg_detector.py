"""
Inversion Fair Value Gap (iFVG) Detector (POI / Setup Layer).

Institutional Mechanics (ICT / SMC):
1. Formation:
   - A normal FVG forms (3-candle sequence with an imbalance).
     - Bullish FVG: Bar 2 Low > Bar 0 High (acting as demand/support).
     - Bearish FVG: Bar 0 Low > Bar 2 High (acting as supply/resistance).

2. Inversion (The Flip):
   - When price impulsively violates and closes completely through an active FVG:
     - Bullish FVG broken to the downside (Close < FVG Bottom) flips into a BEARISH iFVG
       (former support flips to institutional resistance).
     - Bearish FVG broken to the upside (Close > FVG Top) flips into a BULLISH iFVG
       (former resistance flips to institutional support).

3. Retest / Mitigation:
   - When price retraces back into the flipped iFVG zone:
     - Retest of Bearish iFVG from below -> High-probability SHORT POI / trigger.
     - Retest of Bullish iFVG from above -> High-probability LONG POI / trigger.

4. Expiration / Full Invalidation:
   - If an iFVG is penetrated and closed through in the opposite direction, or mitigated
     more than max_mitigations times, it is retired.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import polars as pl


class IFVGType(Enum):
    BULLISH_IFVG = "BULLISH_IFVG"  # Formerly Bearish FVG, broken upwards -> Now Support
    BEARISH_IFVG = "BEARISH_IFVG"  # Formerly Bullish FVG, broken downwards -> Now Resistance


class FVGStatus(Enum):
    ACTIVE_NORMAL = "ACTIVE_NORMAL"  # Intact original FVG
    INVERTED = "INVERTED"            # Broken through, flipped polarity to iFVG
    MITIGATED = "MITIGATED"          # Tapped / traded into after inversion
    EXPIRED = "EXPIRED"              # Broken again or aged out


@dataclass
class FairValueGap:
    id: int
    original_type: str  # "BULLISH" or "BEARISH"
    top: float
    bottom: float
    mid: float
    created_at: Any
    status: FVGStatus = FVGStatus.ACTIVE_NORMAL
    inverted_at: Optional[Any] = None
    ifvg_type: Optional[IFVGType] = None
    mitigation_count: int = 0


@dataclass
class IFVGSignal:
    signal_type: str               # "IFVG_CREATED" or "IFVG_RETEST"
    ifvg_type: IFVGType
    top: float
    bottom: float
    mid: float
    fvg_id: int
    price_at_signal: float
    timestamp: Any


class InversionFVGDetector:
    def __init__(
        self,
        min_fvg_size_dollars: float = 0.30,
        max_active_fvgs: int = 50,
        max_mitigations: int = 2
    ):
        self.min_fvg_size = min_fvg_size_dollars
        self.max_active_fvgs = max_active_fvgs
        self.max_mitigations = max_mitigations

        self.bars_history: List[Dict[str, Any]] = []
        self.fvgs: List[FairValueGap] = []
        self._next_id: int = 1

    def update(self, bar: Dict[str, Any]) -> List[IFVGSignal]:
        """
        Feed one bar at a time (streaming / event-driven).
        Returns any new IFVG created or retested on this bar.
        """
        signals: List[IFVGSignal] = []
        self.bars_history.append(bar)
        if len(self.bars_history) > 10:
            self.bars_history.pop(0)

        # 1. Detect new raw FVG formation from last 3 bars
        if len(self.bars_history) >= 3:
            b0 = self.bars_history[-3]
            b1 = self.bars_history[-2]
            b2 = self.bars_history[-1]

            # Bearish FVG: b0 Low > b2 High
            if b0["low"] - b2["high"] >= self.min_fvg_size:
                new_fvg = FairValueGap(
                    id=self._next_id,
                    original_type="BEARISH",
                    top=b0["low"],
                    bottom=b2["high"],
                    mid=(b0["low"] + b2["high"]) / 2.0,
                    created_at=b1["timestamp"]
                )
                self._next_id += 1
                self.fvgs.append(new_fvg)

            # Bullish FVG: b2 Low > b0 High
            elif b2["low"] - b0["high"] >= self.min_fvg_size:
                new_fvg = FairValueGap(
                    id=self._next_id,
                    original_type="BULLISH",
                    top=b2["low"],
                    bottom=b0["high"],
                    mid=(b2["low"] + b0["high"]) / 2.0,
                    created_at=b1["timestamp"]
                )
                self._next_id += 1
                self.fvgs.append(new_fvg)

        # Limit active list
        if len(self.fvgs) > self.max_active_fvgs:
            self.fvgs = [f for f in self.fvgs if f.status != FVGStatus.EXPIRED][-self.max_active_fvgs:]

        curr_close = bar["close"]
        curr_high = bar["high"]
        curr_low = bar["low"]
        curr_time = bar["timestamp"]

        # 2. Check transitions for all tracked FVGs
        for fvg in self.fvgs:
            # Stage A: Check for Inversion (ACTIVE_NORMAL -> INVERTED)
            if fvg.status == FVGStatus.ACTIVE_NORMAL:
                # If Bullish FVG violated to downside by candle CLOSE
                if fvg.original_type == "BULLISH" and curr_close < fvg.bottom:
                    fvg.status = FVGStatus.INVERTED
                    fvg.ifvg_type = IFVGType.BEARISH_IFVG
                    fvg.inverted_at = curr_time
                    signals.append(
                        IFVGSignal(
                            signal_type="IFVG_CREATED",
                            ifvg_type=fvg.ifvg_type,
                            top=fvg.top,
                            bottom=fvg.bottom,
                            mid=fvg.mid,
                            fvg_id=fvg.id,
                            price_at_signal=curr_close,
                            timestamp=curr_time
                        )
                    )

                # If Bearish FVG violated to upside by candle CLOSE
                elif fvg.original_type == "BEARISH" and curr_close > fvg.top:
                    fvg.status = FVGStatus.INVERTED
                    fvg.ifvg_type = IFVGType.BULLISH_IFVG
                    fvg.inverted_at = curr_time
                    signals.append(
                        IFVGSignal(
                            signal_type="IFVG_CREATED",
                            ifvg_type=fvg.ifvg_type,
                            top=fvg.top,
                            bottom=fvg.bottom,
                            mid=fvg.mid,
                            fvg_id=fvg.id,
                            price_at_signal=curr_close,
                            timestamp=curr_time
                        )
                    )

            # Stage B: Check for Retest of Inverted FVG (INVERTED -> Retest Signal)
            elif fvg.status in (FVGStatus.INVERTED, FVGStatus.MITIGATED):
                if fvg.ifvg_type == IFVGType.BEARISH_IFVG:
                    # Bearish iFVG acts as resistance: price rallies into [bottom, top]
                    if curr_high >= fvg.bottom and curr_low <= fvg.top:
                        # Check if candle doesn't completely blow through top
                        if curr_close <= fvg.top:
                            fvg.mitigation_count += 1
                            if fvg.mitigation_count >= self.max_mitigations:
                                fvg.status = FVGStatus.EXPIRED
                            else:
                                fvg.status = FVGStatus.MITIGATED

                            signals.append(
                                IFVGSignal(
                                    signal_type="IFVG_RETEST",
                                    ifvg_type=fvg.ifvg_type,
                                    top=fvg.top,
                                    bottom=fvg.bottom,
                                    mid=fvg.mid,
                                    fvg_id=fvg.id,
                                    price_at_signal=curr_close,
                                    timestamp=curr_time
                                )
                            )
                        else:
                            # Blown through opposite side -> Invalidation
                            fvg.status = FVGStatus.EXPIRED

                elif fvg.ifvg_type == IFVGType.BULLISH_IFVG:
                    # Bullish iFVG acts as support: price dips into [bottom, top]
                    if curr_low <= fvg.top and curr_high >= fvg.bottom:
                        # Check if candle doesn't completely blow through bottom
                        if curr_close >= fvg.bottom:
                            fvg.mitigation_count += 1
                            if fvg.mitigation_count >= self.max_mitigations:
                                fvg.status = FVGStatus.EXPIRED
                            else:
                                fvg.status = FVGStatus.MITIGATED

                            signals.append(
                                IFVGSignal(
                                    signal_type="IFVG_RETEST",
                                    ifvg_type=fvg.ifvg_type,
                                    top=fvg.top,
                                    bottom=fvg.bottom,
                                    mid=fvg.mid,
                                    fvg_id=fvg.id,
                                    price_at_signal=curr_close,
                                    timestamp=curr_time
                                )
                            )
                        else:
                            # Blown through opposite side -> Invalidation
                            fvg.status = FVGStatus.EXPIRED

        return signals

    def get_active_ifvg_zones(self) -> List[Dict[str, Any]]:
        """Returns currently active iFVG zones available as POI for confluence."""
        active_zones = []
        for f in self.fvgs:
            if f.status in (FVGStatus.INVERTED, FVGStatus.MITIGATED):
                active_zones.append({
                    "id": f.id,
                    "type": f.ifvg_type.value,
                    "top": f.top,
                    "bottom": f.bottom,
                    "mid": f.mid,
                    "created_at": f.created_at,
                    "inverted_at": f.inverted_at,
                    "mitigations": f.mitigation_count
                })
        return active_zones

    def find_ifvgs_in_dataframe(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Batch processing of historical DataFrame.
        Adds columns:
        - `is_ifvg_created`: bool
        - `is_ifvg_retest`: bool
        - `ifvg_type`: string (BULLISH_IFVG / BEARISH_IFVG or null)
        - `ifvg_top`: float
        - `ifvg_bottom`: float
        """
        rows = df.to_dicts()
        ifvg_created_list = [False] * len(rows)
        ifvg_retest_list = [False] * len(rows)
        ifvg_type_list = [None] * len(rows)
        ifvg_top_list = [None] * len(rows)
        ifvg_bottom_list = [None] * len(rows)

        # Reset state for clean batch run
        self.bars_history.clear()
        self.fvgs.clear()
        self._next_id = 1

        for i, row in enumerate(rows):
            signals = self.update(row)
            for sig in signals:
                if sig.signal_type == "IFVG_CREATED":
                    ifvg_created_list[i] = True
                    ifvg_type_list[i] = sig.ifvg_type.value
                    ifvg_top_list[i] = sig.top
                    ifvg_bottom_list[i] = sig.bottom
                elif sig.signal_type == "IFVG_RETEST":
                    ifvg_retest_list[i] = True
                    ifvg_type_list[i] = sig.ifvg_type.value
                    ifvg_top_list[i] = sig.top
                    ifvg_bottom_list[i] = sig.bottom

        return df.with_columns([
            pl.Series("is_ifvg_created", ifvg_created_list, dtype=pl.Boolean),
            pl.Series("is_ifvg_retest", ifvg_retest_list, dtype=pl.Boolean),
            pl.Series("ifvg_type", ifvg_type_list, dtype=pl.Utf8),
            pl.Series("ifvg_top", ifvg_top_list, dtype=pl.Float64),
            pl.Series("ifvg_bottom", ifvg_bottom_list, dtype=pl.Float64),
        ])


if __name__ == "__main__":
    import time

    print("=== Testing Inversion Fair Value Gap (iFVG) Detector ===")
    h1_path = "data/processed/bars/XAUUSD/HTF/XAUUSD_H1.parquet"
    df_h1 = pl.read_parquet(h1_path)
    print(f"Loaded {len(df_h1)} H1 bars from {h1_path}")

    detector = InversionFVGDetector(min_fvg_size_dollars=0.50)
    t0 = time.time()
    df_res = detector.find_ifvgs_in_dataframe(df_h1)
    t1 = time.time()

    created = df_res.filter(pl.col("is_ifvg_created"))
    retests = df_res.filter(pl.col("is_ifvg_retest"))

    print(f"Processed in {t1 - t0:.2f}s")
    print(f"Detected iFVG Formations (Flips): {len(created)}")
    print(f"Detected iFVG Retests (Mitigations): {len(retests)}")

    # Breakdown by type
    bullish_flips = created.filter(pl.col("ifvg_type") == "BULLISH_IFVG")
    bearish_flips = created.filter(pl.col("ifvg_type") == "BEARISH_IFVG")
    print(f"  -> Bullish iFVG (Resistance flipped to Support): {len(bullish_flips)}")
    print(f"  -> Bearish iFVG (Support flipped to Resistance): {len(bearish_flips)}")
