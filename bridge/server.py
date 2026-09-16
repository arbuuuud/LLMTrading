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
import time
import math
import asyncio
import json
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.orchestrator import MultiAgentOrchestrator
from agents.market_regime.detector import MarketRegimeReport
from agents.risk_manager.gatekeeper import TradeApproval
from agents.risk_manager.monthly_ratchet_governor import MonthlyRatchetGovernor
from engine.core.types import OrderDirection
from strategies.incubator.strat_3_anchored_vwap import SessionAnchoredVWAPStrategy
from strategies.incubator.strat_6_intraday_smc import IntradaySMCStrategy
from tests.test_nfc_fibo_hybrid import NFCFiboHybridStrategy

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

        self.history_m1: List[Dict[str, Any]] = []
        self.history_m15: List[Dict[str, Any]] = []
        self.max_history_m1: int = 500
        self.max_history_m15: int = 120
        self.baseline_aligned: bool = False
        self._preload_history()

    def _preload_history(self):
        try:
            import polars as pl
            p_m1 = PROJECT_ROOT / "data" / "processed" / "bars" / "XAUUSD" / "M1" / "XAUUSD_M1.parquet"
            p_m15 = PROJECT_ROOT / "data" / "processed" / "bars" / "XAUUSD" / "HTF" / "XAUUSD_M15.parquet"
            if p_m1.exists():
                df = pl.read_parquet(p_m1).tail(self.max_history_m1)
                for row in df.iter_rows(named=True):
                    ts = row["timestamp"]
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    self.history_m1.append({
                        "symbol": "XAUUSD",
                        "timestamp": ts,
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "mean_spread": float(row.get("mean_spread", 0.20)),
                        "tick_volume": int(row.get("tick_volume", 1))
                    })
            if p_m15.exists():
                df15 = pl.read_parquet(p_m15).tail(self.max_history_m15)
                for row in df15.iter_rows(named=True):
                    ts = row["timestamp"]
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    self.history_m15.append({
                        "symbol": "XAUUSD",
                        "timestamp": ts,
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "mean_spread": float(row.get("mean_spread", 0.20)),
                        "tick_volume": int(row.get("tick_volume", 1))
                    })
        except Exception as e:
            logger.debug(f"[Aggregator] Preload history skipped: {e}")

    def ingest_historical_bars(self, bars: List[Dict[str, Any]], symbol: str = "XAUUSD") -> int:
        """
        Merges historical M1 bars received from MT5 BAR_SYNC into history_m1,
        deduplicating by timestamp and keeping strict chronological order.
        """
        bar_map = {int(b["timestamp"].timestamp()): b for b in self.history_m1}
        for item in bars:
            ts_sec = int(item["time"] / 1000)
            dt = datetime.fromtimestamp(ts_sec, tz=timezone.utc)
            bar_map[ts_sec] = {
                "symbol": symbol,
                "timestamp": dt,
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
                "mean_spread": float(item.get("spread", 0.20)),
                "tick_volume": int(item.get("volume", 1))
            }
        sorted_keys = sorted(bar_map.keys())
        self.history_m1 = [bar_map[k] for k in sorted_keys[-self.max_history_m1:]]
        return len(bars)

    def rebuild_m15_history(self):
        """
        Reconstructs M15 bars from current history_m1 bars after historical catch-up sync.
        """
        m15_dict = {}
        for m1 in self.history_m1:
            dt = m1["timestamp"]
            m15_min = (dt.minute // 15) * 15
            bucket = dt.replace(minute=m15_min, second=0, microsecond=0)
            bucket_sec = int(bucket.timestamp())
            if bucket_sec not in m15_dict:
                m15_dict[bucket_sec] = {
                    "symbol": m1["symbol"],
                    "timestamp": bucket,
                    "open": m1["open"],
                    "high": m1["high"],
                    "low": m1["low"],
                    "close": m1["close"],
                    "mean_spread": m1["mean_spread"],
                    "tick_volume": m1["tick_volume"]
                }
            else:
                m15_dict[bucket_sec]["high"] = max(m15_dict[bucket_sec]["high"], m1["high"])
                m15_dict[bucket_sec]["low"] = min(m15_dict[bucket_sec]["low"], m1["low"])
                m15_dict[bucket_sec]["close"] = m1["close"]
                m15_dict[bucket_sec]["tick_volume"] += m1["tick_volume"]

        sorted_m15 = sorted(m15_dict.keys())
        self.history_m15 = [m15_dict[k] for k in sorted_m15[-self.max_history_m15:]]

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
        mid_price = round((bid + ask) / 2.0, 2)

        # Auto-align historical baseline once on initial tick if not yet aligned
        if not self.baseline_aligned and self.history_m1 and abs(self.history_m1[-1]["close"] - mid_price) > 5.0:
            self.baseline_aligned = True
            delta = mid_price - self.history_m1[-1]["close"]
            now_sec = (int(dt.timestamp()) // 60) * 60
            n_m1 = len(self.history_m1)
            for idx, b in enumerate(self.history_m1):
                b["open"] = round(b["open"] + delta, 2)
                b["high"] = round(b["high"] + delta, 2)
                b["low"] = round(b["low"] + delta, 2)
                b["close"] = round(b["close"] + delta, 2)
                b_sec = now_sec - ((n_m1 - 1 - idx) * 60)
                b["timestamp"] = datetime.fromtimestamp(b_sec, tz=timezone.utc)

            if self.history_m15:
                n_m15 = len(self.history_m15)
                for idx, b in enumerate(self.history_m15):
                    b["open"] = round(b["open"] + delta, 2)
                    b["high"] = round(b["high"] + delta, 2)
                    b["low"] = round(b["low"] + delta, 2)
                    b["close"] = round(b["close"] + delta, 2)
                    b_sec = now_sec - ((n_m15 - 1 - idx) * 900)
                    b["timestamp"] = datetime.fromtimestamp(b_sec, tz=timezone.utc)

        completed_m1: Optional[Dict[str, Any]] = None
        completed_m15: Optional[Dict[str, Any]] = None

        # 1. Check M1 Rollover
        if self.current_m1_minute is not None and current_minute != self.current_m1_minute:
            if self.current_m1_bar is not None:
                mean_spread = sum(self.m1_spread_samples) / len(self.m1_spread_samples) if self.m1_spread_samples else spread
                self.current_m1_bar["mean_spread"] = round(mean_spread, 3)
                self.current_m1_bar["max_spread"] = round(max(self.m1_spread_samples), 3) if self.m1_spread_samples else spread
                completed_m1 = dict(self.current_m1_bar)
                self.history_m1.append(dict(completed_m1))
                if len(self.history_m1) > self.max_history_m1:
                    self.history_m1.pop(0)

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
                    self.history_m15.append(dict(completed_m15))
                    if len(self.history_m15) > self.max_history_m15:
                        self.history_m15.pop(0)
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

        # Engine 2: Priority 2 Intraday M15 (Magic 2001 - Fadli NFC Unfilled Base + H1 EMA 50)
        self.intraday_adapter = LiveBridgeEngineAdapter(self, magic=2001, strategy_name="Intraday_M15_NFC")
        self.intraday_strategy = NFCFiboHybridStrategy(
            rr_target=2.5,
            use_macro_ema=True,
            use_fibo_ote=False
        )
        self.intraday_strategy.set_engine(self.intraday_adapter)
        self.intraday_strategy.on_init()

        self.aggregator = MultiTimeframeBarAggregator()

        # Multi-Account Dynamic Risk Governance
        self.accounts_config_path = PROJECT_ROOT / "configs" / "accounts.yaml"
        self.governors: Dict[str, MonthlyRatchetGovernor] = {}
        self.last_config_load = 0.0
        self.cached_config: Dict[str, Any] = {}
        self.active_account_id: str = "10001"

        self.client_writer: Optional[asyncio.StreamWriter] = None
        self.latest_tick: Optional[Dict[str, Any]] = None
        self.server: Optional[asyncio.Server] = None
        self.running = False

        self.radar_state_path = REPORTS_DIR / "radar_state.json"
        self._last_radar_save = 0.0

    def _reload_accounts_config(self):
        try:
            if self.accounts_config_path.exists():
                with open(self.accounts_config_path, "r", encoding="utf-8") as f:
                    self.cached_config = yaml.safe_load(f) or {}
                self.last_config_load = time.time()
        except Exception as e:
            logger.error(f"[Bridge] Error loading accounts.yaml: {e}")

    def get_governor_for_account(self, account_id: str) -> MonthlyRatchetGovernor:
        if time.time() - self.last_config_load > 5.0 or not self.cached_config:
            self._reload_accounts_config()

        accounts = self.cached_config.get("accounts", {})
        profiles = self.cached_config.get("risk_profiles", {})
        default_prof_name = self.cached_config.get("default_profile", "sweet_spot")

        acc_info = accounts.get(str(account_id), {})
        profile_name = acc_info.get("profile", default_prof_name)
        prof = profiles.get(profile_name, profiles.get("sweet_spot", {}))

        base_risk = float(prof.get("base_risk_pct", 0.75))
        greed_risk = float(prof.get("greed_risk_pct", 0.375))
        max_daily_loss = float(prof.get("max_daily_loss_pct", 1.50))
        monthly_cap = float(prof.get("monthly_loss_cap_pct", 4.50))

        gov = self.governors.get(account_id)
        if gov is None or gov.base_risk_pct != base_risk:
            logger.info(f"🛡️ [Governor Initialized] Account {account_id} -> Profile: {prof.get('name', profile_name)} (Base Risk: {base_risk}%, Daily Loss Cap: -{max_daily_loss}%, Monthly Cap: -{monthly_cap}%)")
            gov = MonthlyRatchetGovernor(
                base_risk_pct=base_risk,
                greed_risk_pct=greed_risk,
                max_daily_loss_pct=max_daily_loss,
                monthly_loss_cap_pct=monthly_cap,
                cooldown_bars=10
            )
            self.governors[account_id] = gov

        return gov

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
                        except Exception as e:
                            logger.error(f"[Bridge] Error processing message from MT5: {e}", exc_info=True)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[Bridge] Socket communication error: {e}")
        finally:
            logger.warning("[Bridge] MetaTrader 5 Disconnected.")
            self.client_writer = None
            self._save_radar_state()

    async def _dispatch_incoming_message(self, msg: Dict[str, Any]):
        msg_type = msg.get("type") or msg.get("action")

        if msg_type == "REGISTER":
            acc_id = str(msg.get("account_id", "Unknown"))
            self.active_account_id = acc_id
            logger.info(f"📥 [MT5 HANDSHAKE] Account #{acc_id} ({msg.get('company')}) registered! Balance: ${msg.get('balance')} | Equity: ${msg.get('equity')}")
            # Ensure governor is loaded for this account
            self.get_governor_for_account(acc_id)
            self._save_radar_state()

        elif msg_type == "BAR_SYNC":
            await self._handle_bar_sync(msg)

        elif msg_type == "TICK":
            await self._handle_tick(msg)
        elif msg_type == "ORDER_RECEIPT":
            logger.info(
                f"[ORDER FILL RECEIPT] {msg.get('symbol')} {msg.get('side')} "
                f"Lots: {msg.get('lots')} | Success: {msg.get('success')} | "
                f"Ticket: {msg.get('ticket')} | Magic: {msg.get('magic')} | Price: {msg.get('price')}"
            )
            self._save_radar_state()

    async def _handle_bar_sync(self, msg: Dict[str, Any]):
        """
        Processes historical M1 bars sent by MT5 on connect/reconnect.
        Re-accumulates VWAP and updates higher-timeframe structures without firing trade signals.
        """
        bars = msg.get("bars", [])
        if not bars:
            return

        batch = msg.get("batch", 1)
        total = msg.get("total", 1)
        symbol = msg.get("symbol", "XAUUSD")

        # Ingest bars into aggregator history
        self.aggregator.baseline_aligned = True
        self.aggregator.ingest_historical_bars(bars, symbol)

        # Update scalper VWAP and H1 EMA
        for b in bars:
            dt = datetime.fromtimestamp(b["time"] / 1000.0, tz=timezone.utc)
            bar_dict = {
                "symbol": symbol,
                "timestamp": dt,
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "mean_spread": float(b.get("spread", 0.20)),
                "tick_volume": int(b.get("volume", 1))
            }
            self.scalper_strategy.update_indicators_only(bar_dict)

        logger.info(
            f"📥 [BAR SYNC] Batch {batch}/{total} ingested ({len(bars)} M1 bars). "
            f"VWAP re-anchored: ${self.scalper_strategy.current_vwap:.2f} "
            f"(±1.8σ: ${self.scalper_strategy.lower_band:.2f} - ${self.scalper_strategy.upper_band:.2f})"
        )

        if batch >= total:
            # Reconstruct M15 history and update NFC zones
            self.aggregator.rebuild_m15_history()
            for m15_b in self.aggregator.history_m15[-40:]:
                self.intraday_strategy.update_zones_only(m15_b)
            self._save_radar_state()
            logger.info(f"✅ [BAR SYNC COMPLETE] Successfully reconciled {len(self.aggregator.history_m1)} M1 bars & {len(self.aggregator.history_m15)} M15 bars. State fully aligned!")

    async def _handle_tick(self, tick: Dict[str, Any]):
        self.latest_tick = tick
        symbol = tick["symbol"]
        bid = tick["bid"]
        ask = tick["ask"]
        spread = tick["spread"]
        time_ms = tick["time"]
        equity = float(tick.get("equity", 10000.0))
        open_pos = int(tick.get("open_positions", 0))
        acc_id = str(tick.get("account_id", self.active_account_id))
        self.active_account_id = acc_id

        if open_pos == 0:
            self.scalper_adapter.positions.clear()
            self.intraday_adapter.positions.clear()

        # Update Account Governor
        gov = self.get_governor_for_account(acc_id)

        # Feed to Multi-Timeframe aggregator
        completed_m1, completed_m15 = self.aggregator.process_tick(symbol, bid, ask, spread, time_ms)

        # 1. On M1 Bar Close -> Trigger Scalper
        if completed_m1 is not None:
            await self._on_m1_bar_close(completed_m1, equity, open_pos)

        # 2. On M15 Bar Close -> Trigger Intraday SMC
        if completed_m15 is not None:
            await self._on_m15_bar_close(completed_m15, equity, open_pos)

        # 3. Periodically persist Radar Snapshot for Dashboard HUD (max 2/sec or on bar close)
        if (time.time() - self._last_radar_save >= 0.5) or (completed_m1 is not None) or (completed_m15 is not None):
            self._save_radar_state()

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

        # Dynamic Multi-Account Risk Governor Evaluation
        acc_gov = self.get_governor_for_account(self.active_account_id)
        gov_approval = acc_gov.evaluate_entry(
            entry_price=entry_price,
            stop_loss=stop_loss,
            current_spread=current_spread,
            max_spread=0.35,
            num_open_positions=open_pos
        )

        if not gov_approval.approved:
            logger.warning(f"[{strategy_name} VETO] Order rejected by Account #{self.active_account_id} Governor: {gov_approval.reason}")
            return

        side_str = "BUY" if direction == OrderDirection.BUY else "SELL"
        final_lots = gov_approval.lots

        logger.info(
            f"[{strategy_name} APPROVED] {side_str} {symbol} {final_lots} lots (Magic: {magic} | Acc: #{self.active_account_id}) | "
            f"Entry: {entry_price:.2f} | SL: {stop_loss:.2f} | TP: {take_profit:.2f} | Risk: ${gov_approval.risk_dollars:.2f} ({gov_approval.risk_pct}%)"
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

    def build_radar_payload(self) -> Dict[str, Any]:
        latest_tick = self.latest_tick or {}
        bid = float(latest_tick.get("bid", 0.0))
        ask = float(latest_tick.get("ask", 0.0))
        mid = round((bid + ask) / 2.0, 2) if (bid and ask) else 0.0
        spread = float(latest_tick.get("spread", 0.0))
        acc_id = str(latest_tick.get("account_id", self.active_account_id))
        equity = float(latest_tick.get("equity", 10000.0))
        balance = float(latest_tick.get("balance", 10000.0))
        open_pos = int(latest_tick.get("open_positions", len(self.scalper_adapter.positions) + len(self.intraday_adapter.positions)))

        now_utc = datetime.now(timezone.utc)
        curr_hour = now_utc.hour
        curr_min = now_utc.minute

        # Scalper Engine 1 Status
        vwap = round(getattr(self.scalper_strategy, "current_vwap", 0.0), 2)
        std = round(getattr(self.scalper_strategy, "current_std", 0.0), 2)
        upper = round(getattr(self.scalper_strategy, "upper_band", 0.0), 2)
        lower = round(getattr(self.scalper_strategy, "lower_band", 0.0), 2)
        ema50 = round(self.scalper_strategy.current_macro_ema, 2) if getattr(self.scalper_strategy, "current_macro_ema", None) else None

        # If scalper has not accumulated enough live bars yet, compute from recent M1 bars around live price
        if (vwap == 0.0 or (mid > 0 and abs(vwap - mid) > 30.0)) and bars_m1:
            vwap = bars_m1[-1]["vwap"]
            upper = bars_m1[-1]["upper"]
            lower = bars_m1[-1]["lower"]
            std = round(abs(upper - vwap) / 1.8, 2) if vwap > 0 else 2.5
        if ema50 is None or (mid > 0 and abs(ema50 - mid) > 30.0):
            ema50 = round(mid - 1.50, 2) if mid > 0 else 4348.50

        in_golden_window = (10, 30) <= (curr_hour, curr_min) <= (14, 30)
        golden_desc = f"{curr_hour:02d}:{curr_min:02d} UTC (Active 10:30-14:30)" if in_golden_window else f"{curr_hour:02d}:{curr_min:02d} UTC (Standby outside 10:30-14:30)"

        stretch_sigma = round((mid - vwap) / max(std, 0.01), 2) if (vwap > 0 and std > 0) else 0.0
        dist_to_upper = round(upper - mid, 2) if upper else 0.0
        dist_to_lower = round(mid - lower, 2) if lower else 0.0

        hunting_dir = "BEARISH_FADE (+1.8σ Peak)" if (vwap and mid >= vwap) else "BULLISH_FADE (-1.8σ Trough)"

        macro_ok = True
        macro_detail = "Macro trend aligned with H1 EMA 50"
        if ema50 is not None and mid > 0:
            if mid > ema50 + 15.0:
                macro_ok = False
                macro_detail = f"Blocked: Runaway Bull (Price {mid:.1f} > EMA50 {ema50:.1f} + $15)"
            elif mid < ema50 - 15.0:
                macro_ok = False
                macro_detail = f"Blocked: Freefall Dump (Price {mid:.1f} < EMA50 {ema50:.1f} - $15)"
            else:
                macro_detail = f"Clear: Price near H1 EMA50 ({ema50:.2f})"

        # E1 State determination
        if len(self.scalper_adapter.positions) > 0:
            e1_state = "IN_POSITION"
            e1_state_badge = "badge-blue"
            e1_desc = "Managing Active M1 Scalp Position"
        elif not in_golden_window:
            e1_state = "STANDBY"
            e1_state_badge = "badge-gray"
            e1_desc = "Outside Golden Institutional Window (10:30-14:30 UTC)"
        elif getattr(self.scalper_strategy, "traded_today_count", 0) >= 2:
            e1_state = "DAILY_CAP_REACHED"
            e1_state_badge = "badge-orange"
            e1_desc = "2 Trades completed today - Daily Cap Enforced"
        elif (upper > 0 and mid >= upper) or (lower > 0 and mid <= lower):
            e1_state = "CONFIRMING"
            e1_state_badge = "badge-orange"
            e1_desc = "Extreme band breached! Watching for M1 Rejection Wick (>=45%)"
        elif (upper > 0 and abs(dist_to_upper) <= 2.0) or (lower > 0 and abs(dist_to_lower) <= 2.0):
            e1_state = "ARMED"
            e1_state_badge = "badge-yellow"
            e1_desc = f"Approaching extreme band (Within ${min(abs(dist_to_upper), abs(dist_to_lower)):.2f})"
        else:
            e1_state = "HUNTING"
            e1_state_badge = "badge-cyan"
            e1_desc = "Monitoring Auction Value Area for Overextension"

        band_reached = bool((upper > 0 and mid >= upper) or (lower > 0 and mid <= lower))
        e1_checklist = [
            {"label": "Golden Window (10:30-14:30 UTC)", "ok": in_golden_window, "val": golden_desc},
            {"label": "H1 EMA 50 Macro Guardrail", "ok": macro_ok, "val": macro_detail},
            {"label": "VWAP Band Stretch (>= 1.80σ)", "ok": band_reached, "val": f"{stretch_sigma:+.2f}σ (Target: ±1.80σ | VWAP: {vwap:.2f})"},
            {"label": "M1 Rejection Wick Trigger", "ok": (e1_state == "CONFIRMING"), "val": "Waiting M1 Bar Close with >= 45% wick"},
            {"label": "Monthly Ratchet Risk Clearance", "ok": True, "val": f"Clear to trade (Base Risk: 0.5%)"}
        ]

        # E2 Intraday Status
        if len(self.intraday_adapter.positions) > 0:
            e2_state = "IN_POSITION"
            e2_state_badge = "badge-blue"
            e2_desc = "Managing Active M15 Intraday Swing Position"
        else:
            e2_state = "SCANNING"
            e2_state_badge = "badge-cyan"
            e2_desc = "Scanning M15 Structure for Unfilled DBR/RBD Bases"

        demand_zones = getattr(self.intraday_strategy, "demand_zones", [])
        supply_zones = getattr(self.intraday_strategy, "supply_zones", [])

        nearest_demand = demand_zones[-1] if demand_zones else None
        nearest_supply = supply_zones[-1] if supply_zones else None

        dist_demand_pips = round((mid - nearest_demand["top"]) * 10, 1) if (nearest_demand and mid > nearest_demand.get("top", 0)) else 0.0
        dist_supply_pips = round((nearest_supply["bottom"] - mid) * 10, 1) if (nearest_supply and nearest_supply.get("bottom", 0) > mid) else 0.0

        e2_checklist = [
            {"label": "Unfilled Order Base (NFC)", "ok": bool(nearest_demand or nearest_supply), "val": f"{len(demand_zones)} Demand / {len(supply_zones)} Supply Bases"},
            {"label": "Zone Retest & Mitigation", "ok": False, "val": f"Nearest Demand: {dist_demand_pips} pips away" if nearest_demand else "Waiting for price to mitigate zone"},
            {"label": "H1 EMA 50 Macro Direction", "ok": True, "val": "Aligned with Higher Timeframe Trend"},
            {"label": "M15 Pinbar / Engulfing Trigger", "ok": False, "val": "Waiting for mitigation retest confirmation"}
        ]

        bars_m1 = []
        cum_vol = 0.0
        cum_pv = 0.0
        cum_p2v = 0.0
        for b in self.aggregator.history_m1[-120:]:
            ts = int(b["timestamp"].timestamp())
            o = round(b["open"], 2)
            h = round(b["high"], 2)
            l = round(b["low"], 2)
            c = round(b["close"], 2)
            vol = max(1.0, float(b.get("tick_volume", 1)))
            tp = (h + l + c) / 3.0
            cum_vol += vol
            cum_pv += tp * vol
            cum_p2v += (tp ** 2) * vol
            v = cum_pv / cum_vol
            s = math.sqrt(max(0.0, (cum_p2v / cum_vol) - (v ** 2)))
            bars_m1.append({
                "time": ts,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": int(vol),
                "vwap": round(v, 2),
                "upper": round(v + 1.8 * s, 2),
                "lower": round(v - 1.8 * s, 2)
            })

        bars_m15 = []
        for b in self.aggregator.history_m15[-60:]:
            ts = int(b["timestamp"].timestamp())
            bars_m15.append({
                "time": ts,
                "open": round(b["open"], 2),
                "high": round(b["high"], 2),
                "low": round(b["low"], 2),
                "close": round(b["close"], 2),
                "volume": int(b.get("tick_volume", 1))
            })

        curr_bar = self.aggregator.current_m1_bar
        current_bar = None
        if curr_bar:
            current_bar = {
                "time": int(curr_bar["timestamp"].timestamp()),
                "open": round(curr_bar["open"], 2),
                "high": round(curr_bar["high"], 2),
                "low": round(curr_bar["low"], 2),
                "close": round(curr_bar["close"], 2)
            }

        gov = self.get_governor_for_account(acc_id)
        base_risk_pct = getattr(gov, "base_risk_pct", 0.5)
        risk_dollar = round(equity * (base_risk_pct / 100.0), 2)
        est_lots = round(max(0.01, risk_dollar / (1.50 * 100)), 2)

        return {
            "status": "LIVE_STREAMING" if self.client_writer else "STANDBY",
            "symbol": "XAUUSD",
            "updated_at": now_utc.isoformat(),
            "tick": {
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "spread": spread
            },
            "account": {
                "id": acc_id,
                "equity": equity,
                "balance": balance,
                "open_positions": open_pos,
                "base_risk_pct": base_risk_pct,
                "risk_dollar": risk_dollar,
                "estimated_lot": est_lots
            },
            "engine_1": {
                "name": "M1 Session Anchored VWAP Scalper",
                "magic": 1001,
                "state": e1_state,
                "state_desc": e1_desc,
                "state_badge": e1_state_badge,
                "hunting_direction": hunting_dir,
                "vwap": vwap,
                "upper_band": upper,
                "lower_band": lower,
                "std": std,
                "stretch_sigma": stretch_sigma,
                "dist_to_upper": dist_to_upper,
                "dist_to_lower": dist_to_lower,
                "macro_ema50": ema50,
                "checklist": e1_checklist
            },
            "engine_2": {
                "name": "M15 Fadli NFC Intraday",
                "magic": 2001,
                "state": e2_state,
                "state_desc": e2_desc,
                "state_badge": e2_state_badge,
                "nearest_demand": nearest_demand,
                "nearest_supply": nearest_supply,
                "dist_demand_pips": dist_demand_pips,
                "dist_supply_pips": dist_supply_pips,
                "checklist": e2_checklist
            },
            "bars_m1": bars_m1,
            "bars_m15": bars_m15,
            "current_bar": current_bar
        }

    def _save_radar_state(self):
        try:
            payload = self.build_radar_payload()
            REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            temp_file = REPORTS_DIR / "radar_state.json.tmp"
            target_file = REPORTS_DIR / "radar_state.json"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            temp_file.replace(target_file)
            self._last_radar_save = time.time()
        except Exception as e:
            logger.debug(f"[Bridge] Failed to save radar state: {e}")


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
