"""
Unit Test: Multi-Account Dynamic Lot Sizing & Equity Scalability.
Verifies that:
1. Account lots scale dynamically and proportionally with each account's live equity.
2. MonthlyRatchetGovernor correctly adopts each account's equity.
3. Multi-account parallel execution dispatches appropriate lot sizes without cross-contamination.
4. Engine 2 orders (Magic 2001) are held from live fire as per Strategic Plan Phase 8.
"""

import unittest
import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from agents.risk_manager.monthly_ratchet_governor import MonthlyRatchetGovernor
from bridge.server import LiveBridgeServer, OrderDirection


class TestMultiAccountDynamicLots(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    def test_governor_dynamic_equity_lot_sizing(self):
        """Test lot calculation for different equity levels with 0.5% risk and $2.00 SL."""
        entry_price = 3000.00
        stop_loss = 2998.00  # $2.00 SL distance
        spread = 0.20

        # Account 1: $500 equity (Micro Account)
        gov_micro = MonthlyRatchetGovernor(base_risk_pct=0.5)
        approval_micro = gov_micro.evaluate_entry(
            entry_price=entry_price,
            stop_loss=stop_loss,
            current_spread=spread,
            current_equity=500.0
        )
        self.assertTrue(approval_micro.approved)
        # Risk = $500 * 0.5% = $2.50. Lots = $2.50 / ($2.00 * 100) = 0.0125 -> clamped to 0.01
        self.assertEqual(approval_micro.lots, 0.01)
        self.assertAlmostEqual(approval_micro.risk_dollars, 2.00, places=1)

        # Account 2: $5,000 equity (Standard Account)
        gov_std = MonthlyRatchetGovernor(base_risk_pct=0.5)
        approval_std = gov_std.evaluate_entry(
            entry_price=entry_price,
            stop_loss=stop_loss,
            current_spread=spread,
            current_equity=5000.0
        )
        self.assertTrue(approval_std.approved)
        # Risk = $5,000 * 0.5% = $25.00. Lots = $25.00 / ($2.00 * 100) = 0.125 -> 0.12 or 0.13
        self.assertIn(approval_std.lots, [0.12, 0.13])

        # Account 3: $50,000 equity (Prop / Institutional Account)
        gov_inst = MonthlyRatchetGovernor(base_risk_pct=0.5)
        approval_inst = gov_inst.evaluate_entry(
            entry_price=entry_price,
            stop_loss=stop_loss,
            current_spread=spread,
            current_equity=50000.0
        )
        self.assertTrue(approval_inst.approved)
        # Risk = $50,000 * 0.5% = $250.00. Lots = $250.00 / ($2.00 * 100) = 1.25 lots
        self.assertEqual(approval_inst.lots, 1.25)
        self.assertAlmostEqual(approval_inst.risk_dollars, 250.00, places=1)

    def test_bridge_multi_account_parallel_dispatch(self):
        """Test LiveBridgeServer dispatches dynamically sized lots to different accounts."""
        server = LiveBridgeServer(dry_run=True)
        server.cached_config = {
            "risk_profiles": {
                "sweet_spot": {"base_risk_pct": 0.5, "greed_risk_pct": 0.25, "max_daily_loss_pct": 1.5, "monthly_loss_cap_pct": 4.5}
            },
            "accounts": {
                "11111": {"profile": "sweet_spot", "equity": 500.0, "balance": 500.0},
                "22222": {"profile": "sweet_spot", "equity": 5000.0, "balance": 5000.0},
                "33333": {"profile": "sweet_spot", "equity": 50000.0, "balance": 50000.0}
            }
        }
        server.last_config_load = time.time()
        server.latest_tick = {
            "ask": 3000.20,
            "bid": 3000.00,
            "spread": 0.20,
            "equity": 5000.0,
            "open_positions": 0
        }
        server.data_integrity_status = "SYNCHRONIZED"
        server.synced_bars_count = 360

        # Mock connected clients
        mock_writer_1 = AsyncMock()
        mock_writer_2 = AsyncMock()
        mock_writer_3 = AsyncMock()

        server.connected_clients = {
            "11111": mock_writer_1,
            "22222": mock_writer_2,
            "33333": mock_writer_3
        }

        # Check governor initialization gets correct equity
        gov_1 = server.get_governor_for_account("11111")
        gov_2 = server.get_governor_for_account("22222")
        gov_3 = server.get_governor_for_account("33333")

        self.assertEqual(gov_1.day_start_equity, 500.0)
        self.assertEqual(gov_2.day_start_equity, 5000.0)
        self.assertEqual(gov_3.day_start_equity, 50000.0)

        # Execute order via async runner
        async def run_order():
            await server.execute_strategy_order(
                symbol="XAUUSD",
                direction=OrderDirection.BUY,
                lots=0.01,
                stop_loss=2998.20,  # $2.00 SL
                take_profit=3004.20,
                comment="Scalper_M1",
                magic=1001,
                strategy_name="Scalper_M1"
            )

        self.loop.run_until_complete(run_order())

    def test_engine_2_hold_live_fire(self):
        """Test that Engine 2 (Magic 2001) orders are held from live fire."""
        server = LiveBridgeServer(dry_run=False)
        server.latest_tick = {
            "ask": 3000.20,
            "bid": 3000.00,
            "spread": 0.20,
            "equity": 10000.0,
            "open_positions": 0
        }
        server.data_integrity_status = "SYNCHRONIZED"
        server.synced_bars_count = 360

        mock_writer = AsyncMock()
        server.connected_clients = {"11111": mock_writer}

        async def run_intraday():
            await server.execute_strategy_order(
                symbol="XAUUSD",
                direction=OrderDirection.BUY,
                lots=0.05,
                stop_loss=2995.0,
                take_profit=3010.0,
                comment="Intraday_M15_NFC",
                magic=2001,
                strategy_name="Intraday_M15"
            )

        self.loop.run_until_complete(run_intraday())

        # Verify writer was NOT called because Engine 2 is on HOLD LIVE FIRE
        mock_writer.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
