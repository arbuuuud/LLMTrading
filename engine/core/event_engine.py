"""
Institutional High-Performance Event-Driven Backtest Engine.
Handles realistic order execution, tick/bar processing, slippage, spread dynamics,
stop-loss/take-profit intrabar checks, and daily circuit breakers.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, date
import uuid
import polars as pl
import numpy as np

from engine.core.types import (
    OrderDirection, OrderType, OrderStatus, ExitReason,
    Order, Position, TradeRecord, AccountConfig, AccountState
)
from engine.core.strategy_base import BaseStrategy
from engine.execution.commission import CommissionModel
from engine.execution.slippage import SlippageModel, FixedSlippageModel
from engine.metrics.performance import PerformanceCalculator, PerformanceSummary
from engine.monte_carlo.simulator import MonteCarloSimulator, MonteCarloReport


class EventEngine:
    def __init__(
        self,
        config: Optional[AccountConfig] = None,
        commission_model: Optional[CommissionModel] = None,
        slippage_model: Optional[SlippageModel] = None,
        max_daily_loss_pct: float = 2.0,
        max_spread_filter: float = 0.50  # In price units, e.g. $0.50 max spread
    ):
        self.config = config or AccountConfig()
        self.commission_model = commission_model or CommissionModel(self.config.commission_per_lot_round_turn)
        self.slippage_model = slippage_model or FixedSlippageModel(0.02)
        
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_spread_filter = max_spread_filter

        # Runtime state
        self.balance = self.config.initial_balance
        self.equity = self.config.initial_balance
        self.peak_equity = self.config.initial_balance
        
        self.positions: Dict[str, Position] = {}
        self.closed_trades: List[TradeRecord] = []
        self.equity_curve: List[Dict[str, Any]] = []

        # Circuit breaker tracking
        self.current_trade_date: Optional[date] = None
        self.day_start_equity = self.config.initial_balance
        self.circuit_breaker_tripped = False

        # Current market price snapshot
        self.current_time: Optional[datetime] = None
        self.current_bid: float = 0.0
        self.current_ask: float = 0.0
        self.current_spread: float = 0.0

    def reset(self):
        self.balance = self.config.initial_balance
        self.equity = self.config.initial_balance
        self.peak_equity = self.config.initial_balance
        self.positions.clear()
        self.closed_trades.clear()
        self.equity_curve.clear()
        self.current_trade_date = None
        self.day_start_equity = self.config.initial_balance
        self.circuit_breaker_tripped = False

    def _check_daily_circuit_breaker(self, dt: datetime):
        trade_date = dt.date()
        if self.current_trade_date != trade_date:
            # New trading day
            self.current_trade_date = trade_date
            self.day_start_equity = self.equity
            self.circuit_breaker_tripped = False

        if not self.circuit_breaker_tripped:
            daily_dd_pct = ((self.day_start_equity - self.equity) / self.day_start_equity) * 100.0
            if daily_dd_pct >= self.max_daily_loss_pct:
                self.circuit_breaker_tripped = True
                # Close all open positions when circuit breaker is tripped
                for pos_id in list(self.positions.keys()):
                    self._close_position_internal(pos_id, ExitReason.CIRCUIT_BREAKER)

    def buy(
        self,
        symbol: str,
        volume_lots: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        comment: str = "",
        tag: str = ""
    ) -> Optional[str]:
        if self.circuit_breaker_tripped:
            return None

        if self.current_spread > self.max_spread_filter:
            return None

        # Apply slippage on Ask price
        fill_price = self.slippage_model.apply_slippage(
            self.current_ask, OrderDirection.BUY, self.current_spread
        )

        pos_id = str(uuid.uuid4())[:8]
        commission = self.commission_model.calculate_commission(volume_lots, is_round_turn=True)

        position = Position(
            position_id=pos_id,
            symbol=symbol,
            direction=OrderDirection.BUY,
            volume_lots=volume_lots,
            open_time=self.current_time,
            open_price=fill_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            commission_paid=commission,
            current_price=self.current_bid,
            unrealized_pnl=0.0,
            highest_price=fill_price,
            lowest_price=fill_price,
            comment=comment,
            tag=tag
        )

        self.positions[pos_id] = position
        return pos_id

    def sell(
        self,
        symbol: str,
        volume_lots: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        comment: str = "",
        tag: str = ""
    ) -> Optional[str]:
        if self.circuit_breaker_tripped:
            return None

        if self.current_spread > self.max_spread_filter:
            return None

        # Apply slippage on Bid price
        fill_price = self.slippage_model.apply_slippage(
            self.current_bid, OrderDirection.SELL, self.current_spread
        )

        pos_id = str(uuid.uuid4())[:8]
        commission = self.commission_model.calculate_commission(volume_lots, is_round_turn=True)

        position = Position(
            position_id=pos_id,
            symbol=symbol,
            direction=OrderDirection.SELL,
            volume_lots=volume_lots,
            open_time=self.current_time,
            open_price=fill_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            commission_paid=commission,
            current_price=self.current_ask,
            unrealized_pnl=0.0,
            highest_price=fill_price,
            lowest_price=fill_price,
            comment=comment,
            tag=tag
        )

        self.positions[pos_id] = position
        return pos_id

    def close_position(self, position_id: str, reason: ExitReason = ExitReason.SIGNAL) -> bool:
        if position_id not in self.positions:
            return False
        self._close_position_internal(position_id, reason)
        return True

    def _close_position_internal(self, position_id: str, reason: ExitReason):
        pos = self.positions.pop(position_id)
        
        # Determine exit fill price with slippage
        if pos.direction == OrderDirection.BUY:
            raw_exit = self.current_bid
            exit_price = self.slippage_model.apply_slippage(raw_exit, OrderDirection.SELL, self.current_spread)
            slippage_cost = abs(raw_exit - exit_price) * pos.volume_lots * self.config.contract_size
            gross_pnl = (exit_price - pos.open_price) * pos.volume_lots * self.config.contract_size
        else:
            raw_exit = self.current_ask
            exit_price = self.slippage_model.apply_slippage(raw_exit, OrderDirection.BUY, self.current_spread)
            slippage_cost = abs(exit_price - raw_exit) * pos.volume_lots * self.config.contract_size
            gross_pnl = (pos.open_price - exit_price) * pos.volume_lots * self.config.contract_size

        net_pnl = gross_pnl - pos.commission_paid
        self.balance += net_pnl

        duration_sec = (self.current_time - pos.open_time).total_seconds() if self.current_time else 0.0

        trade_record = TradeRecord(
            trade_id=pos.position_id,
            symbol=pos.symbol,
            direction=pos.direction,
            volume_lots=pos.volume_lots,
            open_time=pos.open_time,
            close_time=self.current_time,
            open_price=pos.open_price,
            close_price=exit_price,
            gross_pnl=round(gross_pnl, 2),
            commission=round(pos.commission_paid, 2),
            slippage=round(slippage_cost, 2),
            net_pnl=round(net_pnl, 2),
            return_pct=round((net_pnl / self.config.initial_balance) * 100.0, 3),
            stop_loss=pos.stop_loss,
            take_profit=pos.take_profit,
            exit_reason=reason,
            duration_seconds=duration_sec,
            comment=pos.comment,
            tag=pos.tag
        )

        self.closed_trades.append(trade_record)

    def _update_positions_on_tick(self, bid: float, ask: float):
        unrealized_total = 0.0

        for pos_id, pos in list(self.positions.items()):
            if pos.direction == OrderDirection.BUY:
                pos.current_price = bid
                pos.highest_price = max(pos.highest_price, bid)
                pos.lowest_price = min(pos.lowest_price, bid)
                unrealized = (bid - pos.open_price) * pos.volume_lots * self.config.contract_size
                pos.unrealized_pnl = unrealized - pos.commission_paid
                unrealized_total += pos.unrealized_pnl

                # Stop Loss hit
                if pos.stop_loss and bid <= pos.stop_loss:
                    self._close_position_internal(pos_id, ExitReason.STOP_LOSS)
                    continue

                # Take Profit hit
                if pos.take_profit and bid >= pos.take_profit:
                    self._close_position_internal(pos_id, ExitReason.TAKE_PROFIT)
                    continue

            else:  # SELL
                pos.current_price = ask
                pos.highest_price = max(pos.highest_price, ask)
                pos.lowest_price = min(pos.lowest_price, ask)
                unrealized = (pos.open_price - ask) * pos.volume_lots * self.config.contract_size
                pos.unrealized_pnl = unrealized - pos.commission_paid
                unrealized_total += pos.unrealized_pnl

                # Stop Loss hit
                if pos.stop_loss and ask >= pos.stop_loss:
                    self._close_position_internal(pos_id, ExitReason.STOP_LOSS)
                    continue

                # Take Profit hit
                if pos.take_profit and ask <= pos.take_profit:
                    self._close_position_internal(pos_id, ExitReason.TAKE_PROFIT)
                    continue

        self.equity = self.balance + unrealized_total
        self.peak_equity = max(self.peak_equity, self.equity)

    def _update_positions_on_bar(self, bar: Dict[str, Any]):
        """
        Pessimistic intrabar SL/TP execution model:
        If both SL and TP price levels fall within the bar's High-Low range,
        we assume Stop Loss was hit first to prevent overly optimistic backtest results.
        """
        high = bar["high"]
        low = bar["low"]
        close = bar["close"]
        spread = bar.get("mean_spread", 0.20)

        unrealized_total = 0.0

        for pos_id, pos in list(self.positions.items()):
            if pos.direction == OrderDirection.BUY:
                pos.current_price = close
                pos.highest_price = max(pos.highest_price, high)
                pos.lowest_price = min(pos.lowest_price, low)
                
                # Check Stop Loss on Low
                sl_hit = (pos.stop_loss is not None) and (low <= pos.stop_loss)
                tp_hit = (pos.take_profit is not None) and (high >= pos.take_profit)

                if sl_hit:
                    # Pessimistic: SL wins
                    self._close_position_internal(pos_id, ExitReason.STOP_LOSS)
                    continue
                elif tp_hit:
                    self._close_position_internal(pos_id, ExitReason.TAKE_PROFIT)
                    continue

                unrealized = (close - pos.open_price) * pos.volume_lots * self.config.contract_size
                pos.unrealized_pnl = unrealized - pos.commission_paid
                unrealized_total += pos.unrealized_pnl

            else:  # SELL
                ask_high = high + spread
                ask_low = low + spread
                ask_close = close + spread

                pos.current_price = ask_close
                pos.highest_price = max(pos.highest_price, ask_high)
                pos.lowest_price = min(pos.lowest_price, ask_low)

                sl_hit = (pos.stop_loss is not None) and (ask_high >= pos.stop_loss)
                tp_hit = (pos.take_profit is not None) and (ask_low <= pos.take_profit)

                if sl_hit:
                    self._close_position_internal(pos_id, ExitReason.STOP_LOSS)
                    continue
                elif tp_hit:
                    self._close_position_internal(pos_id, ExitReason.TAKE_PROFIT)
                    continue

                unrealized = (pos.open_price - ask_close) * pos.volume_lots * self.config.contract_size
                pos.unrealized_pnl = unrealized - pos.commission_paid
                unrealized_total += pos.unrealized_pnl

        self.equity = self.balance + unrealized_total
        self.peak_equity = max(self.peak_equity, self.equity)

    def run_ticks(self, df_ticks: pl.DataFrame, strategy: BaseStrategy) -> Dict[str, Any]:
        """
        Executes backtest on raw tick data.
        Columns required: timestamp, bid, ask, spread, flags
        """
        self.reset()
        strategy.set_engine(self)
        strategy.on_init()

        timestamps = df_ticks["timestamp"].to_list()
        bids = df_ticks["bid"].to_numpy()
        asks = df_ticks["ask"].to_numpy()
        spreads = df_ticks["spread"].to_numpy()
        flags = df_ticks["flags"].to_numpy() if "flags" in df_ticks.columns else np.zeros(len(bids), dtype=int)

        n = len(timestamps)
        # Sample equity curve every 1000 ticks or on minute changes
        sample_step = max(1, n // 2000)

        for i in range(n):
            self.current_time = timestamps[i]
            self.current_bid = float(bids[i])
            self.current_ask = float(asks[i])
            self.current_spread = float(spreads[i])

            self._check_daily_circuit_breaker(self.current_time)
            self._update_positions_on_tick(self.current_bid, self.current_ask)

            strategy.on_tick(self.current_time, self.current_bid, self.current_ask, self.current_spread, int(flags[i]))

            if i % sample_step == 0:
                self.equity_curve.append({
                    "timestamp": self.current_time,
                    "equity": round(self.equity, 2),
                    "balance": round(self.balance, 2)
                })

        # Close any remaining open positions at end of dataset
        for pos_id in list(self.positions.keys()):
            self._close_position_internal(pos_id, ExitReason.END_OF_DATA)

        strategy.on_finish()

        perf = PerformanceCalculator.calculate(self.closed_trades, self.equity_curve, self.config.initial_balance)
        mc_sim = MonteCarloSimulator(num_simulations=1000)
        mc_report = mc_sim.run(self.closed_trades, self.config.initial_balance)

        return {
            "performance": perf,
            "monte_carlo": mc_report,
            "trades": self.closed_trades,
            "equity_curve": self.equity_curve
        }

    def run_bars(self, df_bars: pl.DataFrame, strategy: BaseStrategy) -> Dict[str, Any]:
        """
        Executes backtest on bar data (M1, M5, etc.).
        Columns required: timestamp, open, high, low, close, mean_spread
        """
        self.reset()
        strategy.set_engine(self)
        strategy.on_init()

        rows = df_bars.iter_rows(named=True)
        for bar in rows:
            self.current_time = bar["timestamp"]
            spread = bar.get("mean_spread", 0.20)
            self.current_bid = bar["close"]
            self.current_ask = round(self.current_bid + spread, 3)
            self.current_spread = spread

            self._check_daily_circuit_breaker(self.current_time)
            self._update_positions_on_bar(bar)

            strategy.on_bar(bar)

            self.equity_curve.append({
                "timestamp": self.current_time,
                "equity": round(self.equity, 2),
                "balance": round(self.balance, 2)
            })

        for pos_id in list(self.positions.keys()):
            self._close_position_internal(pos_id, ExitReason.END_OF_DATA)

        strategy.on_finish()

        perf = PerformanceCalculator.calculate(self.closed_trades, self.equity_curve, self.config.initial_balance)
        mc_sim = MonteCarloSimulator(num_simulations=1000)
        mc_report = mc_sim.run(self.closed_trades, self.config.initial_balance)

        return {
            "performance": perf,
            "monte_carlo": mc_report,
            "trades": self.closed_trades,
            "equity_curve": self.equity_curve
        }
