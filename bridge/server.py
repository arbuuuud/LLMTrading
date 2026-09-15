"""
LLM Trading Live Execution Bridge Server (Dual-Engine Architecture).
Connects MetaTrader 5 (running in Wine or native Windows) via asynchronous TCP Sockets.

Architecture:
1. Live Data Ingestion:
   - Receives high-frequency ticks from `LLM_Bridge_Executor.mq5` via TCP port 5555.
   - Real-time aggregation of ticks into M1 bars and rolling M1 bars into M15 bars.
2. Dual Engine Dispatch:
   - Engine 1: Priority 1 Scalper M1 (Session Anchored VWAP +/- 1.8s, Golden Window 10:30-14:30 UTC, Magic 1001).
   - Engine 2: Priority 2 Intraday M15 (SMC H1 Bias + Order Block/iFVG Expansion, Magic 2001).
3. Risk & Governance:
   - Central Risk Gatekeeper & Monthly Ratchet Governor.
   - Evaluates dynamic position sizing, max daily loss limit (-1.0%), and monthly circuit breaker (-3.0%).
4. Order Dispatch:
   - Sends atomic JSON execution orders with specific Magic Number and Tag back to MT5.
   - Tracks order fill receipts, deal tickets, slippage, and execution timestamps.
"""

import sys
import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.orchestrator import MultiAgentOrchestrator
from agents.market_regime.detector import MarketRegimeReport
from agents.risk_manager.gatekeeper import TradeApproval
from engine.core.types import OrderDirection
from strategies.incubator.strat_3_anchored_vwap import SessionAnchoredVWAPStrategy
from strategies.incubator.strat_6_intraday_smc import IntradaySMCStrategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("LLMBridgeServer")


class MultiTimeframeBarAggregator:
    """
    Aggregates raw incoming ticks into M1 bars, and rolls completed M1 bars into M15 bars.
    """
    def __init__(self):
        self.current_m1_minute: Optional[int] = None
        self.current_m1_bar: Optional[Dict[str, Any]] = None
        self.m1_spread_samples: List[float] = []

        self.current_m15_bucket: Optional[datetime] = None
        self.current_m15_bar: Optional[Dict[str, Any]] = None

    def process_tick(
        self,
        symbol: str,
        bid: float,
        ask: float,
        spread: float,
        timestamp_ms: int
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Processes an incoming tick.
        Returns (completed_m1_bar, completed_m15_bar).
        """
        dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
        current_minute = dt.minute

        completed_m1: Optional[Dict[str, Any]] = None
        completed_m15: Optional[Dict[str, Any]] = None

        # 1. Check M1 Rollover
        if self.current_m1_minute is not None and current_minute != self.current_m1_minute:
            if self.current_m1_bar is not None:
                mean_spread = sum(self.m1_spread_samples) / len(self.m1_spread_samples) if self.m1_spread_samples else spread
                self.current_m1_bar["mean_spread"] = round(mean_spread, 3)
                self.current_m1_bar["max_spread"] = round(max(self.m1_spread_samples), 3) if self.m1_spread_samples else spread
                completed_m1 = dict(self.current_m1_bar)

            self.current_m1_bar = None
            self.m1_spread_samples.clear()

        self.current_m1_minute = current_minute
        mid_price = (bid + ask) / 2.0
        self.m1_spread_samples.append(spread)

        if self.current_m1_bar is None:
            self.current_m1_bar = {
                "symbol": symbol,
                "timestamp": dt.replace(second=0, microsecond=0),
                "open": mid_price,
                "high": mid_price,
                "low": mid_price,
                "close": mid_price,
                "tick_volume": 1
            }
        else:
            self.current_m1_bar["high"] = max(self.current_m1_bar["high"], mid_price)
            self.current_m1_bar["low"] = min(self.current_m1_bar["low"], mid_price)
            self.current_m1_bar["close"] = mid_price
            self.current_m1_bar["tick_volume"] += 1

        # 2. If an M1 bar completed, aggregate into M15 bar
        if completed_m1 is not None:
            m1_dt: datetime = completed_m1["timestamp"]
            m15_min = (m1_dt.minute // 15) * 15
            bucket_time = m1_dt.replace(minute=m15_min, second=0, microsecond=0)

            if self.current_m15_bucket is not None and bucket_time != self.current_m15_bucket:
                # Finalize previous M15 bar
                if self.current_m15_bar is not None:
                    completed_m15 = dict(self.current_m15_bar)
                self.current_m15_bar = None

            self.current_m15_bucket = bucket_time

            if self.current_m15_bar is None:
                self.current_m15_bar = {
                    "symbol": symbol,
                    "timestamp": bucket_time,
                    "open": completed_m1["open"],
                    "high": completed_m1["high"],
                    "low": completed_m1["low"],
                    "close": completed_m1["close"],
                    "mean_spread": completed_m1["mean_spread"],
                    "tick_volume": completed_m1["tick_volume"]
                }
            else:
                self.current_m15_bar["high"] = max(self.current_m15_bar["high"], completed_m1["high"])
                self.current_m15_bar["low"] = min(self.current_m15_bar["low"], completed_m1["low"])
                self.current_m15_bar["close"] = completed_m1["close"]
                self.current_m15_bar["tick_volume"] += completed_m1["tick_volume"]

        return completed_m1, completed_m15


class LiveBridgeEngineAdapter:
    """
    Adapter bridging BaseStrategy orders to the LiveBridgeServer with isolated Magic Numbers.
    """
    def __init__(self, bridge_server: "LiveBridgeServer", magic: int, strategy_name: str):
        self.bridge = bridge_server
        self.magic = magic
        self.name = strategy_name
        self.positions: Dict[str, Any] = {}

    @property
    def equity(self) -> float:
        if self.bridge.latest_tick:
            return float(self.bridge.latest_tick.get("equity", 10000.0))
        return 10000.0

    @property
    def balance(self) -> float:
        if self.bridge.latest_tick:
            return float(self.bridge.latest_tick.get("balance", 10000.0))
        return 10000.0

    def buy(
        self,
        symbol: str,
        volume_lots: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        comment: str = "",
        tag: str = ""
    ) -> Optional[str]:
        pos_id = f"ORDER_{self.magic}_{int(datetime.now().timestamp()*1000)}"
        self.positions[pos_id] = True
        asyncio.create_task(
            self.bridge.execute_strategy_order(
                symbol=symbol,
                direction=OrderDirection.BUY,
                lots=volume_lots,
                stop_loss=stop_loss,
                take_profit=take_profit,
                comment=comment or tag or self.name,
                magic=self.magic,
                strategy_name=self.name
            )
        )
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
        pos_id = f"ORDER_{self.magic}_{int(datetime.now().timestamp()*1000)}"
        self.positions[pos_id] = True
        asyncio.create_task(
            self.bridge.execute_strategy_order(
                symbol=symbol,
                direction=OrderDirection.SELL,
                lots=volume_lots,
                stop_loss=stop_loss,
                take_profit=take_profit,
                comment=comment or tag or self.name,
                magic=self.magic,
                strategy_name=self.name
            )
        )
        return pos_id

    def close_position(self, position_id: str, reason: Any = None):
        self.positions.pop(position_id, None)
        asyncio.create_task(self.bridge.send_close_all(magic=self.magic))


class LiveBridgeServer:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5555,
        dry_run: bool = True  # True = Paper Trading (Dry Run), False = Real MT5 Demo/Live Order
    ):
        self.host = host
        self.port = port
        self.dry_run = dry_run

        self.orchestrator = MultiAgentOrchestrator()

        # Engine 1: Priority 1 Scalper M1 (Magic 1001)
        self.scalper_adapter = LiveBridgeEngineAdapter(self, magic=1001, strategy_name="Scalper_M1_VWAP")
        self.scalper_strategy = SessionAnchoredVWAPStrategy(
            band_multiplier=1.8,
            sl_buffer_dollars=0.50,
            risk_reward_ratio=2.0,
            base_risk_pct=0.5,
            greed_risk_pct=0.25,
            max_bars_hold=60,
            start_hour=10,
            start_minute=30,
            end_hour=14,
            end_minute=30
        )
        self.scalper_strategy.set_engine(self.scalper_adapter)
        self.scalper_strategy.on_init()

        # Engine 2: Priority 2 Intraday M15 (Magic 2001)
        self.intraday_adapter = LiveBridgeEngineAdapter(self, magic=2001, strategy_name="Intraday_M15_SMC")
        self.intraday_strategy = IntradaySMCStrategy(
            base_risk_pct=0.50,
            tp1_r=1.5,
            tp2_r=4.0,
            sl_buffer_dollars=1.50,
            poi_tolerance_dollars=1.00
        )
        self.intraday_strategy.set_engine(self.intraday_adapter)
        self.intraday_strategy.on_init()

        self.aggregator = MultiTimeframeBarAggregator()

        self.client_writer: Optional[asyncio.StreamWriter] = None
        self.latest_tick: Optional[Dict[str, Any]] = None
        self.server: Optional[asyncio.Server] = None
        self.running = False

    async def start(self):
        self.running = True
        mode_str = "PAPER TRADING (SIMULATION - NO REAL ORDERS SENT)" if self.dry_run else "LIVE MT5 DEMO/REAL EXECUTION (ACTIVE TRADING!)"
        logger.info("=" * 80)
        logger.info(f"🚀 Starting LLM Trading Dual-Engine Bridge Server on {self.host}:{self.port}")
        logger.info(f"⚙️ Execution Mode: {mode_str}")
        logger.info(f"🎯 Priority 1 Scalper: M1 Session Anchored VWAP +/- 1.8s (Magic: 1001)")
        logger.info(f"🏹 Priority 2 Intraday: M15 SMC Expansion + Callisto BE (Magic: 2001)")
        logger.info("=" * 80)

        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)
        logger.info(f"Bridge Server listening on {self.host}:{self.port}. Waiting for MT5 EA connection...")

        async with self.server:
            await self.server.serve_forever()

    async def stop(self):
        self.running = False
        if self.client_writer:
            self.client_writer.close()
            await self.client_writer.wait_closed()
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        logger.info("Bridge Server stopped.")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        client_addr = writer.get_extra_info("peername")
        logger.info(f"[Bridge] MetaTrader 5 Connected from {client_addr}!")
        self.client_writer = writer

        buffer = ""
        try:
            while self.running and not reader.at_eof():
                data = await reader.read(4096)
                if not data:
                    break

                buffer += data.decode("utf-8", errors="ignore")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        try:
                            msg = json.loads(line)
                            await self._dispatch_incoming_message(msg)
                        except json.JSONDecodeError:
                            logger.error(f"[Bridge] Invalid JSON payload from MT5: {line}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[Bridge] Socket communication error: {e}")
        finally:
            logger.warning("[Bridge] MetaTrader 5 Disconnected.")
            self.client_writer = None

    async def _dispatch_incoming_message(self, msg: Dict[str, Any]):
        msg_type = msg.get("type") or msg.get("action")

        if msg_type == "TICK":
            await self._handle_tick(msg)
        elif msg_type == "ORDER_RECEIPT":
            logger.info(
                f"[ORDER FILL RECEIPT] {msg.get('symbol')} {msg.get('side')} "
                f"Lots: {msg.get('lots')} | Success: {msg.get('success')} | "
                f"Ticket: {msg.get('ticket')} | Magic: {msg.get('magic')} | Price: {msg.get('price')}"
            )

    async def _handle_tick(self, tick: Dict[str, Any]):
        self.latest_tick = tick
        symbol = tick["symbol"]
        bid = tick["bid"]
        ask = tick["ask"]
        spread = tick["spread"]
        time_ms = tick["time"]
        equity = float(tick.get("equity", 10000.0))
        open_pos = int(tick.get("open_positions", 0))

        if open_pos == 0:
            self.scalper_adapter.positions.clear()
            self.intraday_adapter.positions.clear()

        # Feed to Multi-Timeframe aggregator
        completed_m1, completed_m15 = self.aggregator.process_tick(symbol, bid, ask, spread, time_ms)

        # 1. On M1 Bar Close -> Trigger Scalper
        if completed_m1 is not None:
            await self._on_m1_bar_close(completed_m1, equity, open_pos)

        # 2. On M15 Bar Close -> Trigger Intraday SMC
        if completed_m15 is not None:
            await self._on_m15_bar_close(completed_m15, equity, open_pos)

    async def _on_m1_bar_close(self, bar: Dict[str, Any], account_equity: float, open_positions: int):
        logger.info(
            f"[M1 Bar Close] {bar['timestamp'].strftime('%H:%M')} | "
            f"O: {bar['open']:.2f} H: {bar['high']:.2f} L: {bar['low']:.2f} C: {bar['close']:.2f} | "
            f"Spread: ${bar['mean_spread']:.2f} | Vol: {bar['tick_volume']}"
        )

        regime_report: MarketRegimeReport = self.orchestrator.analyze_market(bar)
        self.orchestrator.risk_gatekeeper.on_new_bar(bar["timestamp"], account_equity)
        self.scalper_strategy.on_bar(bar)

    async def _on_m15_bar_close(self, bar: Dict[str, Any], account_equity: float, open_positions: int):
        logger.info(
            f"[M15 Bar Close] {bar['timestamp'].strftime('%H:%M')} | "
            f"O: {bar['open']:.2f} H: {bar['high']:.2f} L: {bar['low']:.2f} C: {bar['close']:.2f} | "
            f"Spread: ${bar['mean_spread']:.2f} (Evaluating Intraday SMC...)"
        )
        self.intraday_strategy.on_bar(bar)

    async def execute_strategy_order(
        self,
        symbol: str,
        direction: OrderDirection,
        lots: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        comment: str,
        magic: int = 1001,
        strategy_name: str = "Scalper_M1"
    ):
        if not self.latest_tick or not stop_loss or not take_profit:
            return

        entry_price = self.latest_tick["ask"] if direction == OrderDirection.BUY else self.latest_tick["bid"]
        current_spread = self.latest_tick["spread"]
        account_equity = float(self.latest_tick.get("equity", 10000.0))
        open_pos = int(self.latest_tick.get("open_positions", 0))

        # Central Risk Gatekeeper approval
        approval: TradeApproval = self.orchestrator.evaluate_trade_risk(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            current_spread=current_spread,
            account_equity=account_equity,
            num_open_positions=open_pos
        )

        if not approval.approved:
            logger.warning(f"[{strategy_name} VETO] Order rejected by Gatekeeper: {approval.reason}")
            return

        side_str = "BUY" if direction == OrderDirection.BUY else "SELL"
        final_lots = approval.recommended_lots

        logger.info(
            f"[{strategy_name} APPROVED] {side_str} {symbol} {final_lots} lots (Magic: {magic}) | "
            f"Entry: {entry_price:.2f} | SL: {stop_loss:.2f} | TP: {take_profit:.2f} | Risk: ${approval.risk_dollars}"
        )

        await self.send_order(
            symbol=symbol,
            side=side_str,
            lots=final_lots,
            sl=stop_loss,
            tp=take_profit,
            comment=comment,
            magic=magic
        )

    async def send_order(
        self,
        symbol: str,
        side: str,
        lots: float,
        sl: float,
        tp: float,
        comment: str = "LLM_AI",
        magic: int = 1001
    ) -> bool:
        cmd = {
            "action": "ORDER",
            "symbol": symbol,
            "side": side.upper(),
            "lots": lots,
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "comment": comment,
            "magic": magic
        }

        if self.dry_run:
            logger.info(f"[PAPER TRADE DRY-RUN] Simulating Order: {cmd}")
            return True

        if not self.client_writer:
            logger.warning("[Bridge] Cannot send order: MT5 not connected.")
            return False

        payload = json.dumps(cmd) + "\n"
        self.client_writer.write(payload.encode("utf-8"))
        await self.client_writer.drain()
        logger.info(f"[DISPATCH TO MT5] Sent live order command: {payload.strip()}")
        return True

    async def send_close_all(self, symbol: str = "", magic: int = 0):
        cmd = {"action": "CLOSE_ALL", "symbol": symbol, "magic": magic}
        if self.dry_run:
            logger.info(f"[PAPER TRADE DRY-RUN] Close Positions: {cmd}")
            return

        if self.client_writer:
            payload = json.dumps(cmd) + "\n"
            self.client_writer.write(payload.encode("utf-8"))
            await self.client_writer.drain()
            logger.info(f"[DISPATCH TO MT5] Sent close command: {payload.strip()}")


# Backward-compatible alias for existing unit tests
LiveBarAggregator = MultiTimeframeBarAggregator


async def run_server_cli():
    import argparse
    parser = argparse.ArgumentParser(description="LLM Trading Live Execution Bridge Server")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5555, help="Port to listen on (default: 5555)")
    parser.add_argument("--live", action="store_true", help="Enable REAL execution on MT5 (default: dry_run simulation)")
    args = parser.parse_args()

    server = LiveBridgeServer(host=args.host, port=args.port, dry_run=not args.live)
    try:
        await server.start()
    except KeyboardInterrupt:
        logger.info("Server received interrupt signal, shutting down...")
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(run_server_cli())
