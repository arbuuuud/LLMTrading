"""
Integration tests for MT5 Live Bridge Server and Dual-Engine Bar Aggregator.
Simulates TCP connection, tick streaming, dynamic magic number order dispatch, and round-trip receipts.
"""

import unittest
import sys
from pathlib import Path
from datetime import datetime, timezone
import asyncio
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bridge.server import MultiTimeframeBarAggregator, LiveBridgeServer


class TestLiveBridge(unittest.TestCase):

    def test_multi_timeframe_bar_aggregator(self):
        aggregator = MultiTimeframeBarAggregator()

        # Feed 3 ticks in minute 14 (10:14 UTC)
        t0 = 1748340840000  # 10:14:00 UTC
        m1, m15 = aggregator.process_tick("XAUUSD", bid=3300.0, ask=3300.20, spread=0.20, timestamp_ms=t0)
        self.assertIsNone(m1)
        self.assertIsNone(m15)

        aggregator.process_tick("XAUUSD", bid=3302.0, ask=3302.20, spread=0.20, timestamp_ms=t0 + 20000)
        aggregator.process_tick("XAUUSD", bid=3298.0, ask=3298.20, spread=0.20, timestamp_ms=t0 + 40000)

        # Tick at minute 15:05 (10:15:05 UTC) rolls over M1 AND rolls over M15
        completed_m1, completed_m15 = aggregator.process_tick("XAUUSD", bid=3301.0, ask=3301.20, spread=0.20, timestamp_ms=t0 + 65000)
        
        self.assertIsNotNone(completed_m1)
        self.assertEqual(completed_m1["tick_volume"], 3)
        self.assertAlmostEqual(completed_m1["open"], 3300.10, places=2)
        self.assertAlmostEqual(completed_m1["high"], 3302.10, places=2)
        self.assertAlmostEqual(completed_m1["low"], 3298.10, places=2)
        print(f"\n[Test Result] Completed M1 Bar: {completed_m1}")

        # Another tick at minute 30 to finalize M15
        t30 = t0 + (16 * 60 * 1000)
        m1_next, m15_final = aggregator.process_tick("XAUUSD", bid=3305.0, ask=3305.20, spread=0.20, timestamp_ms=t30)
        self.assertIsNotNone(m15_final)
        print(f"[Test Result] Completed M15 Bar: {m15_final}")

    def test_dual_engine_socket_round_trip(self):
        async def run_socket_test():
            server = LiveBridgeServer(host="127.0.0.1", port=5557, dry_run=False)
            server_task = asyncio.create_task(server.start())

            await asyncio.sleep(0.2)  # Wait for server to bind

            # Simulate MT5 EA Client
            reader, writer = await asyncio.open_connection("127.0.0.1", 5557)

            # Send TICK packet from mock MT5
            tick = {
                "type": "TICK",
                "symbol": "XAUUSD",
                "bid": 3310.0,
                "ask": 3310.20,
                "spread": 0.20,
                "time": 1748342400000,
                "equity": 10000.0,
                "balance": 10000.0,
                "open_positions": 0
            }
            writer.write((json.dumps(tick) + "\n").encode("utf-8"))
            await writer.drain()

            await asyncio.sleep(0.1)

            # 1. Test Scalper M1 Order (Magic 1001)
            await server.send_order(
                symbol="XAUUSD",
                side="BUY",
                lots=0.10,
                sl=3305.0,
                tp=3320.0,
                comment="Scalp_M1",
                magic=1001
            )

            order_line = await reader.readline()
            order_data = json.loads(order_line.decode("utf-8"))
            self.assertEqual(order_data["action"], "ORDER")
            self.assertEqual(order_data["magic"], 1001)
            self.assertEqual(order_data["lots"], 0.10)

            # 2. Test Intraday M15 Order (Magic 2001)
            await server.send_order(
                symbol="XAUUSD",
                side="SELL",
                lots=0.05,
                sl=3315.0,
                tp=3290.0,
                comment="Intra_M15",
                magic=2001
            )

            order_line2 = await reader.readline()
            order_data2 = json.loads(order_line2.decode("utf-8"))
            self.assertEqual(order_data2["action"], "ORDER")
            self.assertEqual(order_data2["magic"], 2001)
            self.assertEqual(order_data2["lots"], 0.05)

            # Mock MT5 sends back ORDER_RECEIPT for both
            receipt = {
                "type": "ORDER_RECEIPT",
                "symbol": "XAUUSD",
                "side": "BUY",
                "lots": 0.10,
                "success": True,
                "ticket": 987654321,
                "magic": 1001,
                "price": 3310.20
            }
            writer.write((json.dumps(receipt) + "\n").encode("utf-8"))
            await writer.drain()

            await asyncio.sleep(0.1)

            # Cleanup
            writer.close()
            await writer.wait_closed()
            await server.stop()
            server_task.cancel()

        asyncio.run(run_socket_test())

    def test_handshake_register_and_resilience(self):
        async def run_resilience_test():
            server = LiveBridgeServer(host="127.0.0.1", port=5558, dry_run=True)
            server_task = asyncio.create_task(server.start())

            await asyncio.sleep(0.2)

            reader, writer = await asyncio.open_connection("127.0.0.1", 5558)

            # 1. Send REGISTER message (triggers get_governor_for_account with time.time())
            reg_msg = {
                "type": "REGISTER",
                "account_id": "10001",
                "company": "ICMarkets",
                "balance": 10000.0,
                "equity": 10000.0
            }
            writer.write((json.dumps(reg_msg) + "\n").encode("utf-8"))
            await writer.drain()
            await asyncio.sleep(0.1)

            self.assertEqual(server.active_account_id, "10001")
            self.assertIn("10001", server.governors)

            # 2. Send malformed line (test resilience - should not crash bridge or disconnect MT5)
            writer.write(b"MALFORMED_NON_JSON_LINE\n")
            await writer.drain()
            await asyncio.sleep(0.1)

            # 3. Send valid TICK and verify server is still connected and operational
            tick = {
                "type": "TICK",
                "symbol": "XAUUSD",
                "bid": 3310.0,
                "ask": 3310.20,
                "spread": 0.20,
                "time": 1748342400000,
                "equity": 10000.0,
                "open_positions": 0,
                "account_id": "10001"
            }
            writer.write((json.dumps(tick) + "\n").encode("utf-8"))
            await writer.drain()
            await asyncio.sleep(0.1)

            self.assertIsNotNone(server.latest_tick)
            self.assertEqual(server.latest_tick["symbol"], "XAUUSD")

            writer.close()
            await writer.wait_closed()
            await server.stop()
            server_task.cancel()

        asyncio.run(run_resilience_test())

    def test_historical_bar_sync_reconciliation(self):
        """
        Tests that when MT5 reconnects after being disconnected for hours,
        it sends BAR_SYNC batches which re-anchor VWAP and update M15 structures
        without emitting false trade signals.
        """
        async def run_sync_test():
            server = LiveBridgeServer(host="127.0.0.1", port=5560, dry_run=True)
            server_task = asyncio.create_task(server.start())
            await asyncio.sleep(0.2)

            reader, writer = await asyncio.open_connection("127.0.0.1", 5560)

            # 1. Send Handshake
            reg = {
                "type": "REGISTER",
                "account_id": "10001",
                "symbol": "XAUUSD",
                "company": "ICMarkets",
                "currency": "USD",
                "balance": 10000.0,
                "equity": 10000.0
            }
            writer.write((json.dumps(reg) + "\n").encode())
            await writer.drain()
            await asyncio.sleep(0.1)

            # 2. Simulate MT5 sending 60 historical M1 bars (1 hour of missed market data)
            t0 = 1748342400000  # 10:40 UTC
            sync_bars = []
            for i in range(60):
                p = 4340.0 + (i * 0.1)
                sync_bars.append({
                    "time": t0 + (i * 60000),
                    "open": round(p, 2),
                    "high": round(p + 0.5, 2),
                    "low": round(p - 0.3, 2),
                    "close": round(p + 0.2, 2),
                    "volume": 250 + i,
                    "spread": 0.20
                })

            sync_payload = {
                "type": "BAR_SYNC",
                "symbol": "XAUUSD",
                "batch": 1,
                "total": 1,
                "bars": sync_bars
            }
            writer.write((json.dumps(sync_payload) + "\n").encode())
            await writer.drain()
            await asyncio.sleep(0.3)

            # 3. Assert VWAP and indicators are re-anchored
            self.assertGreater(server.scalper_strategy.current_vwap, 4300.0)
            self.assertGreater(server.scalper_strategy.upper_band, server.scalper_strategy.current_vwap)
            self.assertLess(server.scalper_strategy.lower_band, server.scalper_strategy.current_vwap)

            # Ensure no rogue trades were executed during catch-up
            self.assertEqual(len(server.scalper_adapter.positions), 0)

            # 4. Stream next live tick seamlessly
            next_tick = {
                "type": "TICK",
                "account_id": "10001",
                "symbol": "XAUUSD",
                "bid": 4346.20,
                "ask": 4346.40,
                "spread": 0.20,
                "time": t0 + (60 * 60000) + 15000,
                "equity": 10000.0,
                "balance": 10000.0,
                "open_positions": 0
            }
            writer.write((json.dumps(next_tick) + "\n").encode())
            await writer.drain()
            await asyncio.sleep(0.2)

            self.assertEqual(server.latest_tick["bid"], 4346.20)
            print(f"\n[Test Result] VWAP after historical catch-up: ${server.scalper_strategy.current_vwap:.2f}")
            print(f"[Test Result] Upper Band: ${server.scalper_strategy.upper_band:.2f} | Lower: ${server.scalper_strategy.lower_band:.2f}")

            writer.close()
            await writer.wait_closed()
            await server.stop()
            server_task.cancel()

        asyncio.run(run_sync_test())


if __name__ == "__main__":
    unittest.main()
