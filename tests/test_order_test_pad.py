"""
Unit tests for Manual Order Execution & Simulation Pad (Python Brain -> MT5 Bridge IPC & API)
"""
import unittest
import asyncio
import json
import os
import shutil
from pathlib import Path

from bridge.server import LiveBridgeServer, REPORTS_DIR


class TestOrderTestPad(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cmd_file = REPORTS_DIR / "bridge_command.json"
        self.receipt_file = REPORTS_DIR / "order_receipt.json"
        if self.cmd_file.exists():
            self.cmd_file.unlink()
        if self.receipt_file.exists():
            self.receipt_file.unlink()

    def tearDown(self):
        if self.cmd_file.exists():
            self.cmd_file.unlink()
        if self.receipt_file.exists():
            self.receipt_file.unlink()

    async def test_order_dispatch_in_dry_run(self):
        server = LiveBridgeServer(host="127.0.0.1", port=5556, dry_run=True)
        server.running = True

        # Test sending BUY order
        res_buy = await server.send_order(
            symbol="XAUUSD",
            side="BUY",
            lots=0.01,
            price=0.0,
            sl=4260.0,
            tp=4300.0,
            comment="Test_Buy",
            magic=9999
        )
        self.assertTrue(res_buy)

        # Test sending BUY_LIMIT order with price
        res_limit = await server.send_order(
            symbol="XAUUSD",
            side="BUY_LIMIT",
            lots=0.02,
            price=4270.0,
            sl=4265.0,
            tp=4290.0,
            comment="Test_Limit",
            magic=9999
        )
        self.assertTrue(res_limit)

        # Test sending CLOSE_ALL
        res_close = await server.send_close_all(symbol="XAUUSD", magic=0)
        self.assertTrue(res_close)

    async def test_order_receipt_dispatch(self):
        server = LiveBridgeServer(host="127.0.0.1", port=5556, dry_run=True)
        server.running = True

        receipt_msg = {
            "type": "ORDER_RECEIPT",
            "symbol": "XAUUSD",
            "side": "BUY",
            "lots": 0.01,
            "success": True,
            "ticket": 12345678,
            "retcode": 10009,
            "retcode_desc": "Request completed",
            "deal": 87654321,
            "price": 4278.50,
            "magic": 9999
        }

        await server._dispatch_incoming_message(receipt_msg)
        self.assertIsNotNone(server.latest_order_receipt)
        self.assertEqual(server.latest_order_receipt["ticket"], 12345678)
        self.assertTrue(self.receipt_file.exists())

        with open(self.receipt_file, "r") as f:
            data = json.load(f)
        self.assertEqual(data["ticket"], 12345678)
        self.assertEqual(data["price"], 4278.50)


if __name__ == "__main__":
    unittest.main()
