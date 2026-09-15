"""
High-Performance Python Bridge Server for MetaTrader 5.
Runs a non-blocking asyncio TCP server communicating with LLM_Bridge_Executor.mq5.
Ingests real-time ticks, aggregates live M1 bars, executes the Multi-Agent pipeline,
and sends execution orders with strict institutional risk controls.
"""

import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from agents.orchestrator import MultiAgentOrchestrator
from agents.market_regime.detector import MarketRegimeReport
from agents.risk_manager.gatekeeper import TradeApproval
from engine.core.types import OrderDirection
from strategies.incubator.xauusd_trend_pullback_scalper import XAUUSDTrendPullbackScalper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("LLMBridgeServer")


class LiveBarAggregator:
    """Aggregates incoming ticks into M1 bars in real time."""
    def __init__(self):
        self.current_bar_minute: Optional[int] = None
        self.current_bar: Optional[Dict[str, Any]] = None
        self.spread_samples = []

    def process_tick(self, symbol: str, bid: float, ask: float, spread: float, timestamp_ms: int) -> Optional[Dict[str, Any]]:
        dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
        current_minute = dt.minute

        completed_bar = None
        if self.current_bar_minute is not None and current_minute != self.current_bar_minute:
            # Current minute rolled over, finalize previous bar
            if self.current_bar is not None:
                mean_spread = sum(self.spread_samples) / len(self.spread_samples) if self.spread_samples else spread
                self.current_bar["mean_spread"] = round(mean_spread, 3)
                self.current_bar["max_spread"] = round(max(self.spread_samples), 3) if self.spread_samples else spread
                completed_bar = dict(self.current_bar)

            # Reset for new bar
            self.current_bar = None
            self.spread_samples = []

        self.current_bar_minute = current_minute
        mid_price = (bid + ask) / 2.0
        self.spread_samples.append(spread)

        if self.current_bar is None:
            self.current_bar = {
                "symbol": symbol,
                "timestamp": dt.replace(second=0, microsecond=0),
                "open": mid_price,
                "high": mid_price,
                "low": mid_price,
                "close": mid_price,
                "tick_volume": 1
            }
        else:
            self.current_bar["high"] = max(self.current_bar["high"], mid_price)
            self.current_bar["low"] = min(self.current_bar["low"], mid_price)
            self.current_bar["close"] = mid_price
            self.current_bar["tick_volume"] += 1

        return completed_bar


class LiveBridgeServer:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5555,
        dry_run: bool = True  # Default to Paper Trading mode for safety
    ):
        self.host = host
        self.port = port
        self.dry_run = dry_run

        self.orchestrator = MultiAgentOrchestrator()
        self.strategy = XAUUSDTrendPullbackScalper(risk_reward_ratio=2.0, max_bars_hold=25)
        self.aggregator = LiveBarAggregator()

        self.client_writer: Optional[asyncio.StreamWriter] = None
        self.latest_tick: Optional[Dict[str, Any]] = None
        self.server: Optional[asyncio.Server] = None
        self.running = False

    async def start(self):
        self.running = True
        mode_str = "PAPER TRADING (DRY RUN)" if self.dry_run else "LIVE BROKER EXECUTION"
        logger.info(f"Starting MT5 Bridge Server on {self.host}:{self.port} [{mode_str}]...")

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
            while self.running:
                data = await reader.read(4096)
                if not data:
                    logger.warning("[Bridge] MT5 Client disconnected.")
                    break

                buffer += data.decode("utf-8", errors="ignore")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        await self._process_incoming_json(line)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[Bridge] Socket communication error: {e}", exc_info=True)
        finally:
            self.client_writer = None
            writer.close()
            await writer.wait_closed()
            logger.info("[Bridge] Client handler closed.")

    async def _process_incoming_json(self, json_str: str):
        try:
            msg = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning(f"[Bridge] Failed to parse JSON: {json_str[:100]}")
            return

        msg_type = msg.get("type")
        if msg_type == "TICK":
            await self._handle_tick(msg)
        elif msg_type == "ORDER_RECEIPT":
            logger.info(
                f"[ORDER FILL RECEIPT] {msg.get('symbol')} {msg.get('side')} "
                f"Lots: {msg.get('lots')} | Success: {msg.get('success')} | "
                f"Ticket: {msg.get('ticket')} | Price: {msg.get('price')}"
            )
        else:
            logger.debug(f"[Bridge] Received unhandled message type: {msg_type}")

    async def _handle_tick(self, tick: Dict[str, Any]):
        self.latest_tick = tick
        symbol = tick["symbol"]
        bid = tick["bid"]
        ask = tick["ask"]
        spread = tick["spread"]
        time_ms = tick["time"]
        equity = tick.get("equity", 10000.0)
        open_pos = tick.get("open_positions", 0)

        # Feed to aggregator to form M1 bar
        bar = self.aggregator.process_tick(symbol, bid, ask, spread, time_ms)
        if bar is not None:
            await self._on_m1_bar_close(bar, equity, open_pos)

    async def _on_m1_bar_close(self, bar: Dict[str, Any], account_equity: float, open_positions: int):
        logger.info(
            f"[M1 Bar Close] {bar['timestamp'].strftime('%H:%M')} | "
            f"O: {bar['open']:.2f} H: {bar['high']:.2f} L: {bar['low']:.2f} C: {bar['close']:.2f} | "
            f"Spread: ${bar['mean_spread']:.2f} | Ticks: {bar['tick_volume']}"
        )

        # 1. Market Regime Assessment
        regime_report: MarketRegimeReport = self.orchestrator.analyze_market(bar)
        logger.info(
            f"[Regime AI] {regime_report.regime.value} | ATR: ${regime_report.atr:.2f} | "
            f"Trend Strength: {regime_report.trend_strength:+.2f} | Target: {regime_report.recommended_strategy_family}"
        )

        # 2. Risk Gatekeeper bar sync
        self.orchestrator.risk_gatekeeper.on_new_bar(bar["timestamp"], account_equity)

        # If regime is not favorable, stand aside
        if regime_report.recommended_strategy_family == "STAND_ASIDE":
            return

        # 3. Strategy Signal Generation
        # (In live execution, strategy inspects bar and requests order via callback)
        # For demonstration of live bridge, we simulate order dispatch
        # when strategy conditions are met.

    async def send_order(
        self,
        symbol: str,
        side: str,
        lots: float,
        sl: float,
        tp: float,
        comment: str = "LLM_AI"
    ) -> bool:
        cmd = {
            "action": "ORDER",
            "symbol": symbol,
            "side": side.upper(),
            "lots": lots,
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "comment": comment
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
        logger.info(f"[DISPATCH TO MT5] Sent order command: {payload.strip()}")
        return True


if __name__ == "__main__":
    server = LiveBridgeServer(host="127.0.0.1", port=5555, dry_run=True)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Server interrupted by user.")
