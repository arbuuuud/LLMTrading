"""
Integration tests for MT5 Live Bridge Server and Real-Time Bar Aggregator.
Simulates TCP connection, tick streaming, and order dispatch round-trip.
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

from bridge.server import LiveBarAggregator, LiveBridgeServer


class TestLiveBridge(unittest.TestCase):

    def test_live_bar_aggregator(self):
        aggregator = LiveBarAggregator()

        # Feed 3 ticks in minute 10
        t0 = 1748342400000  # Epoch ms
        bar1 = aggregator.process_tick("XAUUSD", bid=3300.0, ask=3300.20, spread=0.20, timestamp_ms=t0)
        self.assertIsNone(bar1)  # Not closed yet

        aggregator.process_tick("XAUUSD", bid=3302.0, ask=3302.20, spread=0.20, timestamp_ms=t0 + 20000)
        aggregator.process_tick("XAUUSD", bid=3298.0, ask=3298.20, spread=0.20, timestamp_ms=t0 + 40000)

        # Tick in minute 11 (60 seconds later) should finalize the bar of minute 10
        completed_bar = aggregator.process_tick("XAUUSD", bid=3301.0, ask=3301.20, spread=0.20, timestamp_ms=t0 + 65000)
        self.assertIsNotNone(completed_bar)
        self.assertEqual(completed_bar["tick_volume"], 3)
        self.assertAlmostEqual(completed_bar["open"], 3300.10, places=2)
        self.assertAlmostEqual(completed_bar["high"], 3302.10, places=2)
        self.assertAlmostEqual(completed_bar["low"], 3298.10, places=2)
        print(f"\n[Test Result] Completed M1 Bar: {completed_bar}")

    def test_socket_round_trip(self):
        async def run_socket_test():
            server = LiveBridgeServer(host="127.0.0.1", port=5556, dry_run=False)
            server_task = asyncio.create_task(server.start())

            await asyncio.sleep(0.2)  # Wait for server to bind

            # Simulate MT5 EA Client
            reader, writer = await asyncio.open_connection("127.0.0.1", 5556)

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

            # Server sends an order
            await server.send_order(
                symbol="XAUUSD",
                side="BUY",
                lots=0.10,
                sl=3305.0,
                tp=3320.0,
                comment="Unit_Test_Scalp"
            )

            # Mock MT5 receives order
            order_line = await reader.readline()
            order_data = json.loads(order_line.decode("utf-8"))
            self.assertEqual(order_data["action"], "ORDER")
            self.assertEqual(order_data["side"], "BUY")
            self.assertEqual(order_data["lots"], 0.10)

            # Mock MT5 sends back ORDER_RECEIPT
            receipt = {
                "type": "ORDER_RECEIPT",
                "symbol": "XAUUSD",
                "side": "BUY",
                "lots": 0.10,
                "success": True,
                "ticket": 987654321,
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


if __name__ == "__main__":
    unittest.main()
