"""
XAUUSD Liquidity SMC Scout (Baseline Modular Scalping Strategy).
Combines:
1. Context: Asia Session (00:00 - 06:00 UTC) Range tracking & Trade Window (London/NY).
2. Setup: Liquidity Sweep (BSL / SSL grab of Asia High/Low).
3. Trigger: M1 Change of Character (CHoCH) and/or Candlestick Pattern (Engulfing / Pinbar).
4. Exit: Strict R:R (1:2 - 1:2.5) with time-based cut.
Supports full ablation testing to isolate edge contribution of each component.
"""

from typing import Dict, Any, Optional
from datetime import datetime

from engine.core.types import OrderDirection, ExitReason
from engine.core.strategy_base import BaseStrategy
from strategies.modules.context.session_tracker import SessionTracker
from strategies.modules.context.htf_poi import HTFPOITracker
from strategies.modules.setups.liquidity_sweep import LiquiditySweepDetector, SweepType, SweepSignal
from strategies.modules.setups.supply_demand import SupplyDemandDetector
from strategies.modules.triggers.candlestick_patterns import CandlestickPatternDetector, PatternType
from strategies.modules.triggers.market_structure import MarketStructureDetector, StructureEvent
from strategies.modules.triggers.displacement_fvg import DisplacementFVGDetector, FVGType, FVGSignal
from strategies.modules.exits.risk_guard import RiskGuard


class XAUUSDLiquiditySMCScout(BaseStrategy):
    def __init__(
        self,
        # Ablation / Feature toggles
        use_htf_poi: bool = False,
        use_candle_pattern: bool = False,
        use_choch_confirmation: bool = False,
        use_fvg_trigger: bool = True,
        use_time_exit: bool = True,
        # Sizing & Execution
        lot_size: float = 0.1,
        risk_reward_ratio: float = 1.5,
        max_bars_hold: int = 25,
        # Sweep parameters
        min_sweep_dollars: float = 0.15,
        max_sweep_dollars: float = 3.50,
        sl_buffer_dollars: float = 0.25
    ):
        super().__init__("XAUUSD_Liquidity_SMC_Scout")
        
        self.use_htf_poi = use_htf_poi
        self.use_candle_pattern = use_candle_pattern
        self.use_choch_confirmation = use_choch_confirmation
        self.use_fvg_trigger = use_fvg_trigger
        self.use_time_exit = use_time_exit

        self.lot_size = lot_size
        self.max_bars_hold = max_bars_hold

        # Modular components
        self.session_tracker = SessionTracker()
        self.htf_poi = HTFPOITracker(zone_buffer_dollars=0.50)
        self.sweep_detector = LiquiditySweepDetector(
            min_sweep_dollars=min_sweep_dollars,
            max_sweep_dollars=max_sweep_dollars,
            require_close_inside=True
        )
        self.sd_detector = SupplyDemandDetector()
        self.candle_detector = CandlestickPatternDetector()
        self.structure_detector = MarketStructureDetector(pivot_lookback=2)
        self.fvg_detector = DisplacementFVGDetector(min_fvg_size_dollars=0.15, min_body_ratio=0.55)
        self.risk_guard = RiskGuard(
            risk_reward_ratio=risk_reward_ratio,
            sl_buffer_dollars=sl_buffer_dollars,
            min_sl_distance=0.40,
            max_sl_distance=3.50,
            max_bars_hold=max_bars_hold
        )

        # State tracking for setup evolution
        self.pending_sweep: Optional[SweepSignal] = None
        self.sweep_expiry_bars: int = 0
        self.open_position_bars: int = 0
        self.active_position_id: Optional[str] = None

    def on_init(self):
        self.pending_sweep = None
        self.sweep_expiry_bars = 0
        self.open_position_bars = 0
        self.active_position_id = None

    def on_bar(self, bar: Dict[str, Any]):
        dt: datetime = bar["timestamp"]
        price = bar["close"]

        # 1. Update Context Layers
        self.session_tracker.update(bar)
        self.htf_poi.update(bar)

        # 2. Update Trigger & Pattern Layers
        candle_pattern = self.candle_detector.update(bar)
        structure_event = self.structure_detector.update(bar)
        fvg_signal = self.fvg_detector.update(bar)
        self.sd_detector.update(bar)

        # 3. Handle Active Position Time Exit
        if len(self.engine.positions) > 0:
            self.open_position_bars += 1
            if self.use_time_exit and self.open_position_bars >= self.max_bars_hold:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
                self.active_position_id = None
                self.open_position_bars = 0
            return
        else:
            self.open_position_bars = 0
            self.active_position_id = None

        # 4. Check Trade Window (Only trade London & NY sessions after Asia is complete)
        if not self.session_tracker.is_in_trade_window(dt, allow_london=True, allow_ny=True):
            self.pending_sweep = None
            return

        if not self.session_tracker.asia_complete:
            return

        # 5. Check for New Liquidity Sweep
        sweep = self.sweep_detector.check_sweep(
            bar,
            reference_high=self.session_tracker.asia_high,
            reference_low=self.session_tracker.asia_low
        )
        if sweep is not None:
            self.pending_sweep = sweep
            self.sweep_expiry_bars = 15  # Must confirm within 15 bars
            # Reset extremum if price continues to sweep higher/lower
        elif self.pending_sweep is not None:
            self.sweep_expiry_bars -= 1
            if self.sweep_expiry_bars <= 0:
                self.pending_sweep = None

        if self.pending_sweep is None:
            return

        # 6. Check HTF POI Filter (if enabled)
        if self.use_htf_poi:
            if self.pending_sweep.sweep_type == SweepType.BUY_SIDE_SWEEP:
                if not self.htf_poi.is_price_at_htf_supply_poi(price):
                    return
            else:
                if not self.htf_poi.is_price_at_htf_demand_poi(price):
                    return

        # 7. Check Triggers (CHoCH, FVG, or Candlestick Pattern)
        should_enter_short = False
        should_enter_long = False

        if self.pending_sweep.sweep_type == SweepType.BUY_SIDE_SWEEP:
            # Bearish reversal conditions
            choch_ok = not self.use_choch_confirmation or (structure_event == StructureEvent.BEARISH_CHOCH)
            candle_ok = not self.use_candle_pattern or (candle_pattern in (PatternType.BEARISH_ENGULFING, PatternType.SHOOTING_STAR))
            fvg_ok = not self.use_fvg_trigger or (fvg_signal is not None and fvg_signal.fvg_type == FVGType.BEARISH_FVG)
            
            if choch_ok and candle_ok and fvg_ok:
                should_enter_short = True

        elif self.pending_sweep.sweep_type == SweepType.SELL_SIDE_SWEEP:
            # Bullish reversal conditions
            choch_ok = not self.use_choch_confirmation or (structure_event == StructureEvent.BULLISH_CHOCH)
            candle_ok = not self.use_candle_pattern or (candle_pattern in (PatternType.BULLISH_ENGULFING, PatternType.BULLISH_HAMMER))
            fvg_ok = not self.use_fvg_trigger or (fvg_signal is not None and fvg_signal.fvg_type == FVGType.BULLISH_FVG)

            if choch_ok and candle_ok and fvg_ok:
                should_enter_long = True

        # 8. Execute Order via Risk Guard
        if should_enter_short:
            levels = self.risk_guard.calculate_levels(
                OrderDirection.SELL,
                entry_price=price,
                extremum_anchor=self.pending_sweep.extremum_price
            )
            if levels:
                sl, tp = levels
                pos_id = self.engine.sell(
                    symbol="XAUUSD",
                    volume_lots=self.lot_size,
                    stop_loss=sl,
                    take_profit=tp,
                    comment="BSL_Sweep_Reversal",
                    tag="M1_Scalp"
                )
                if pos_id:
                    self.active_position_id = pos_id
                    self.pending_sweep = None

        elif should_enter_long:
            levels = self.risk_guard.calculate_levels(
                OrderDirection.BUY,
                entry_price=price,
                extremum_anchor=self.pending_sweep.extremum_price
            )
            if levels:
                sl, tp = levels
                pos_id = self.engine.buy(
                    symbol="XAUUSD",
                    volume_lots=self.lot_size,
                    stop_loss=sl,
                    take_profit=tp,
                    comment="SSL_Sweep_Reversal",
                    tag="M1_Scalp"
                )
                if pos_id:
                    self.active_position_id = pos_id
                    self.pending_sweep = None
