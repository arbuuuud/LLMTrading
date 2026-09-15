"""
XAUUSD Institutional SMT Divergence Sniper.
Uses Silver (XAGUSD) and Dollar Index (DXY) as intermarket reference assets
to detect true institutional liquidity traps / false breakouts:
1. Bearish SMT Trap:
   - Gold sweeps Swing/Asia High (Higher High).
   - Silver FAILS to make Higher High (Lower High non-confirmation).
   - Bearish Rejection confirmation -> SELL with tight SL above sweep wick.
2. Bullish SMT Trap:
   - Gold sweeps Swing/Asia Low (Lower Low).
   - Silver FAILS to make Lower Low (Higher Low non-confirmation).
   - Bullish Rejection confirmation -> BUY with tight SL below sweep wick.
3. Daily Ratchet Governor:
   - Dynamic lot sizing (0.5% standard, 0.25% in Greed Mode).
   - 2-Strike loss circuit breaker (-1.0% daily hard stop).
   - Locks floor at +1.0% when daily profit reaches >= +1.5%.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from engine.core.types import OrderDirection, ExitReason
from engine.core.strategy_base import BaseStrategy
from strategies.modules.context.smt_divergence import SMTDivergenceDetector, SMTType, SMTReport
from strategies.modules.triggers.candlestick_patterns import CandlestickPatternDetector, PatternType
from agents.risk_manager.daily_ratchet import DailyRatchetRiskGovernor, SizingApproval


class XAUUSDSMTSniper(BaseStrategy):
    def __init__(
        self,
        risk_reward_ratio: float = 2.0,
        sl_buffer_dollars: float = 0.35,
        max_bars_hold: int = 25,
        base_risk_pct: float = 0.5,
        greed_risk_pct: float = 0.25,
        smt_lookback_bars: int = 25
    ):
        super().__init__("XAUUSD_SMT_Sniper")
        self.risk_reward_ratio = risk_reward_ratio
        self.sl_buffer = sl_buffer_dollars
        self.max_bars_hold = max_bars_hold

        self.smt_detector = SMTDivergenceDetector(lookback_bars=smt_lookback_bars)
        self.candle_detector = CandlestickPatternDetector()
        self.risk_governor = DailyRatchetRiskGovernor(
            base_risk_pct=base_risk_pct,
            greed_risk_pct=greed_risk_pct,
            max_daily_loss_pct=1.0,
            max_daily_trades_under_target=3,
            cooldown_bars=15
        )

        self.bars_in_trade: int = 0
        self.pending_smt: Optional[SMTReport] = None
        self.smt_expiry_bars: int = 0
        self.extremum_anchor: float = 0.0

    def on_init(self):
        self.bars_in_trade = 0
        self.pending_smt = None
        self.smt_expiry_bars = 0
        self.extremum_anchor = 0.0

    def on_trade_closed(self, trade_record):
        self.risk_governor.on_trade_closed(trade_record.net_pnl)

    def on_bar_intermarket(
        self,
        gold_bar: Dict[str, Any],
        silver_bar: Optional[Dict[str, Any]],
        dxy_bar: Optional[Dict[str, Any]]
    ):
        dt: datetime = gold_bar["timestamp"]
        price = gold_bar["close"]
        spread = gold_bar.get("gold_spread", gold_bar.get("mean_spread", 0.20))

        # 1. Update daily governor state
        self.risk_governor.on_bar_tick(dt, self.engine.equity)
        candle = self.candle_detector.update(gold_bar)

        # 2. Manage active trade holding period
        if len(self.engine.positions) > 0:
            self.bars_in_trade += 1
            if self.bars_in_trade >= self.max_bars_hold:
                for pos_id in list(self.engine.positions.keys()):
                    self.engine.close_position(pos_id, ExitReason.TIME_EXPIRED)
                self.bars_in_trade = 0
            return
        else:
            self.bars_in_trade = 0

        # 3. Golden Hours Filter (London 07:00-11:00 UTC & NY 12:30-16:00 UTC)
        t = dt.time()
        is_london = (7, 0) <= (t.hour, t.minute) <= (11, 0)
        is_ny = (12, 30) <= (t.hour, t.minute) <= (16, 0)
        if not (is_london or is_ny):
            self.pending_smt = None
            return

        # 4. Update Intermarket SMT Detector
        smt_report: SMTReport = self.smt_detector.update(gold_bar, silver_bar, dxy_bar)

        if smt_report.is_confirmed:
            self.pending_smt = smt_report
            self.smt_expiry_bars = 10  # Must trigger within 10 M1 bars
            if smt_report.smt_type == SMTType.BEARISH_SMT_SWEEP:
                self.extremum_anchor = gold_bar["high"]
            else:
                self.extremum_anchor = gold_bar["low"]
        elif self.pending_smt is not None:
            self.smt_expiry_bars -= 1
            if self.smt_expiry_bars <= 0:
                self.pending_smt = None

        if self.pending_smt is None:
            return

        # 5. Evaluate SMT Execution
        # Case A: Bearish SMT (Gold Swept High, Silver Failed) + Bearish Candle Rejection
        if self.pending_smt.smt_type == SMTType.BEARISH_SMT_SWEEP:
            self.extremum_anchor = max(self.extremum_anchor, gold_bar["high"])
            if candle in (PatternType.BEARISH_ENGULFING, PatternType.SHOOTING_STAR):
                sl = round(self.extremum_anchor + self.sl_buffer, 2)
                sl_dist = sl - price
                tp = round(price - (sl_dist * self.risk_reward_ratio), 2)

                approval: SizingApproval = self.risk_governor.evaluate_entry(
                    entry_price=price,
                    stop_loss=sl,
                    current_spread=spread,
                    max_allowed_spread=0.22,
                    num_open_positions=len(self.engine.positions)
                )

                if approval.approved:
                    pos_id = self.engine.sell(
                        symbol="XAUUSD",
                        volume_lots=approval.lots,
                        stop_loss=sl,
                        take_profit=tp,
                        comment=f"Bearish_SMT_{approval.risk_pct}%",
                        tag="SMT_Sniper"
                    )
                    if pos_id:
                        self.pending_smt = None

        # Case B: Bullish SMT (Gold Swept Low, Silver Failed) + Bullish Candle Rejection
        elif self.pending_smt.smt_type == SMTType.BULLISH_SMT_SWEEP:
            self.extremum_anchor = min(self.extremum_anchor, gold_bar["low"])
            if candle in (PatternType.BULLISH_ENGULFING, PatternType.BULLISH_HAMMER):
                sl = round(self.extremum_anchor - self.sl_buffer, 2)
                sl_dist = price - sl
                tp = round(price + (sl_dist * self.risk_reward_ratio), 2)

                approval: SizingApproval = self.risk_governor.evaluate_entry(
                    entry_price=price,
                    stop_loss=sl,
                    current_spread=spread,
                    max_allowed_spread=0.22,
                    num_open_positions=len(self.engine.positions)
                )

                if approval.approved:
                    pos_id = self.engine.buy(
                        symbol="XAUUSD",
                        volume_lots=approval.lots,
                        stop_loss=sl,
                        take_profit=tp,
                        comment=f"Bullish_SMT_{approval.risk_pct}%",
                        tag="SMT_Sniper"
                    )
                    if pos_id:
                        self.pending_smt = None
