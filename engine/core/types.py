"""
Core domain types and data structures for LLMTrading Backtest Engine.
Institutional-grade representations of orders, positions, trades, and account states.
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any


class OrderDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class ExitReason(str, Enum):
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    SIGNAL = "SIGNAL"
    TIME_EXPIRED = "TIME_EXPIRED"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"
    END_OF_DATA = "END_OF_DATA"


@dataclass
class Order:
    order_id: str
    symbol: str
    direction: OrderDirection
    order_type: OrderType
    volume_lots: float
    created_time: datetime
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    comment: str = ""
    tag: str = ""


@dataclass
class Position:
    position_id: str
    symbol: str
    direction: OrderDirection
    volume_lots: float
    open_time: datetime
    open_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    commission_paid: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    highest_price: float = 0.0
    lowest_price: float = 0.0
    comment: str = ""
    tag: str = ""


@dataclass
class TradeRecord:
    trade_id: str
    symbol: str
    direction: OrderDirection
    volume_lots: float
    open_time: datetime
    close_time: datetime
    open_price: float
    close_price: float
    gross_pnl: float
    commission: float
    slippage: float
    net_pnl: float
    return_pct: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    exit_reason: ExitReason
    duration_seconds: float
    comment: str = ""
    tag: str = ""


@dataclass
class AccountConfig:
    initial_balance: float = 10000.0
    currency: str = "USD"
    leverage: float = 100.0
    point_size: float = 0.01        # For XAUUSD: $0.01 price move
    contract_size: float = 100.0    # 1 standard lot of XAUUSD = 100 oz
    commission_per_lot_round_turn: float = 7.0  # $7 per lot round-turn ECN standard
    min_lot: float = 0.01
    max_lot: float = 100.0
    lot_step: float = 0.01


@dataclass
class AccountState:
    balance: float
    equity: float
    used_margin: float
    free_margin: float
    margin_level_pct: float
    open_positions_count: int
    closed_trades_count: int
    daily_realized_pnl: float = 0.0
    max_equity_reached: float = 0.0
    current_drawdown_amount: float = 0.0
    current_drawdown_pct: float = 0.0
