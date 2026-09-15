"""
Commission models for institutional backtesting.
Calculates round-turn or per-side broker commissions.
"""

from engine.core.types import AccountConfig


class CommissionModel:
    """
    Standard institutional commission model based on lot size.
    Typical ECN accounts charge ~$5 to $7 per round turn per standard lot.
    """
    def __init__(self, commission_per_lot_round_turn: float = 7.0):
        self.commission_per_lot_rt = commission_per_lot_round_turn

    def calculate_commission(self, lots: float, is_round_turn: bool = True) -> float:
        """
        Returns commission in account currency (USD).
        """
        rate = self.commission_per_lot_rt if is_round_turn else (self.commission_per_lot_rt / 2.0)
        return round(lots * rate, 4)
