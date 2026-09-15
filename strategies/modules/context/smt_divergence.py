"""
Smart Money Technique (SMT) Intermarket Divergence Detector.
Correlates primary asset (XAUUSD) against reference assets (XAGUSD Silver and DXY Dollar Index)
to detect institutional non-confirmation / liquidity traps:
1. Bearish SMT Divergence:
   - Gold prints a Higher High (sweeping swing high or Asia High).
   - Silver fails to make a Higher High (prints a Lower High) and/or DXY fails to make a Lower Low.
   - Confirmation: High-probability institutional short (false breakout).
2. Bullish SMT Divergence:
   - Gold prints a Lower Low (sweeping swing low or Asia Low).
   - Silver fails to make a Lower Low (prints a Higher Low) and/or DXY fails to make a Higher High.
   - Confirmation: High-probability institutional long (bear trap).
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum


class SMTType(Enum):
    BEARISH_SMT_SWEEP = "BEARISH_SMT_SWEEP"  # Gold HH vs Silver LH (Strong Sell)
    BULLISH_SMT_SWEEP = "BULLISH_SMT_SWEEP"  # Gold LL vs Silver HL (Strong Buy)
    NO_DIVERGENCE = "NO_DIVERGENCE"          # Assets in sync (True Expansion)


@dataclass
class SMTReport:
    smt_type: SMTType
    is_confirmed: bool
    gold_high_swept: bool
    silver_confirmed_failure: bool
    dxy_divergence: bool
    gold_price: float
    silver_price: Optional[float]
    dxy_price: Optional[float]
    explanation: str


class SMTDivergenceDetector:
    def __init__(self, lookback_bars: int = 30):
        self.lookback = lookback_bars
        self.gold_history: List[Dict[str, Any]] = []
        self.silver_history: List[Dict[str, Any]] = []
        self.dxy_history: List[Dict[str, Any]] = []

    def update(
        self,
        gold_bar: Dict[str, Any],
        silver_bar: Optional[Dict[str, Any]] = None,
        dxy_bar: Optional[Dict[str, Any]] = None
    ) -> SMTReport:
        self.gold_history.append(gold_bar)
        if len(self.gold_history) > self.lookback * 2:
            self.gold_history.pop(0)

        if silver_bar is not None:
            self.silver_history.append(silver_bar)
            if len(self.silver_history) > self.lookback * 2:
                self.silver_history.pop(0)

        if dxy_bar is not None:
            self.dxy_history.append(dxy_bar)
            if len(self.dxy_history) > self.lookback * 2:
                self.dxy_history.pop(0)

        n = len(self.gold_history)
        if n < self.lookback or len(self.silver_history) < self.lookback:
            return SMTReport(
                smt_type=SMTType.NO_DIVERGENCE,
                is_confirmed=False,
                gold_high_swept=False,
                silver_confirmed_failure=False,
                dxy_divergence=False,
                gold_price=gold_bar["close"],
                silver_price=silver_bar["close"] if silver_bar else None,
                dxy_price=dxy_bar["close"] if dxy_bar else None,
                explanation="Insufficient historical bars for SMT"
            )

        # Recent baseline before current bar
        gold_past_high = max(b["high"] for b in self.gold_history[-self.lookback:-1])
        gold_past_low = min(b["low"] for b in self.gold_history[-self.lookback:-1])

        silver_past_high = max(b["high"] for b in self.silver_history[-self.lookback:-1])
        silver_past_low = min(b["low"] for b in self.silver_history[-self.lookback:-1])

        curr_gold = gold_bar
        curr_silver = self.silver_history[-1]

        gold_made_hh = curr_gold["high"] > gold_past_high
        gold_made_ll = curr_gold["low"] < gold_past_low

        silver_made_hh = curr_silver["high"] > silver_past_high
        silver_made_ll = curr_silver["low"] < silver_past_low

        # DXY analysis (Inverted correlation to Gold)
        dxy_divergence = False
        curr_dxy = self.dxy_history[-1] if self.dxy_history else None
        if curr_dxy is not None and len(self.dxy_history) >= self.lookback:
            dxy_past_high = max(b["high"] for b in self.dxy_history[-self.lookback:-1])
            dxy_past_low = min(b["low"] for b in self.dxy_history[-self.lookback:-1])
            # If Gold made HH, DXY should make LL. If DXY didn't make LL -> DXY divergence!
            if gold_made_hh and curr_dxy["low"] >= dxy_past_low:
                dxy_divergence = True
            elif gold_made_ll and curr_dxy["high"] <= dxy_past_high:
                dxy_divergence = True

        # === 1. BEARISH SMT DIVERGENCE ===
        # Gold made Higher High, but Silver FAILED (Lower High)
        if gold_made_hh and not silver_made_hh:
            return SMTReport(
                smt_type=SMTType.BEARISH_SMT_SWEEP,
                is_confirmed=True,
                gold_high_swept=True,
                silver_confirmed_failure=True,
                dxy_divergence=dxy_divergence,
                gold_price=curr_gold["close"],
                silver_price=curr_silver["close"],
                dxy_price=curr_dxy["close"] if curr_dxy else None,
                explanation="BEARISH SMT: Gold made Higher High while Silver failed to break High. Liquidity trap confirmed."
            )

        # === 2. BULLISH SMT DIVERGENCE ===
        # Gold made Lower Low, but Silver FAILED (Higher Low)
        if gold_made_ll and not silver_made_ll:
            return SMTReport(
                smt_type=SMTType.BULLISH_SMT_SWEEP,
                is_confirmed=True,
                gold_high_swept=False,
                silver_confirmed_failure=True,
                dxy_divergence=dxy_divergence,
                gold_price=curr_gold["close"],
                silver_price=curr_silver["close"],
                dxy_price=curr_dxy["close"] if curr_dxy else None,
                explanation="BULLISH SMT: Gold made Lower Low while Silver held Higher Low. Bear trap confirmed."
            )

        return SMTReport(
            smt_type=SMTType.NO_DIVERGENCE,
            is_confirmed=False,
            gold_high_swept=gold_made_hh,
            silver_confirmed_failure=False,
            dxy_divergence=dxy_divergence,
            gold_price=curr_gold["close"],
            silver_price=curr_silver["close"],
            dxy_price=curr_dxy["close"] if curr_dxy else None,
            explanation="Both assets moving in directional sync"
        )
