import sys
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from engine.core.event_engine import EventEngine
from engine.core.types import AccountConfig
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from strategies.incubator.strat_3_anchored_vwap import SessionAnchoredVWAPStrategy

df_all = pl.read_parquet("data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet")
engine = EventEngine(
    config=AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0),
    commission_model=CommissionModel(7.0),
    slippage_model=FixedSlippageModel(0.02)
)
strat = SessionAnchoredVWAPStrategy(
    band_multiplier=1.8,
    sl_buffer_dollars=0.40,
    risk_reward_ratio=2.0,
    base_risk_pct=0.5,
    greed_risk_pct=0.25,
    max_bars_hold=60
)
res = engine.run_bars(df_all, strat)
trades = res["trades"]

wins = [t for t in trades if t.net_pnl > 0]
losses = [t for t in trades if t.net_pnl <= 0]

total_win_dollars = sum(t.net_pnl for t in wins)
total_loss_dollars = abs(sum(t.net_pnl for t in losses))

avg_win = total_win_dollars / len(wins) if wins else 0
avg_loss = total_loss_dollars / len(losses) if losses else 0
payoff_ratio = avg_win / avg_loss if avg_loss else 0

print("=" * 60)
print("MATHEMATICAL BREAKDOWN OF THE 187 TRADES")
print("=" * 60)
print(f"Total Trades: {len(trades)}")
print(f"Winning Trades ({(len(wins)/len(trades)*100):.1f}%): {len(wins)} trades")
print(f"Losing Trades  ({(len(losses)/len(trades)*100):.1f}%): {len(losses)} trades")
print("-" * 60)
print(f"Average Profit on WIN:  +${avg_win:,.2f}")
print(f"Average Loss on LOSS:   -${avg_loss:,.2f}")
print(f"Realized Payoff Ratio:  {payoff_ratio:.2f} to 1 (Win size is {payoff_ratio:.2f}x bigger than Loss size!)")
print("-" * 60)
print(f"Total Profit from Wins:   +${total_win_dollars:,.2f}")
print(f"Total Loss from Losses:   -${total_loss_dollars:,.2f}")
print(f"NET PROFIT IN YOUR POCKET: +${total_win_dollars - total_loss_dollars:,.2f}")
print("=" * 60)

# --- NEW ANALYSIS: PnL by Hour of Day (UTC) ---
print("\n" + "=" * 60)
print("PNL DISTRIBUTION BY ENTRY HOUR (UTC)")
print("=" * 60)
hourly_pnl = defaultdict(float)
hourly_trades_count = defaultdict(int)

for trade in trades:
    entry_hour = trade.open_time.hour
    hourly_pnl[entry_hour] += trade.net_pnl
    hourly_trades_count[entry_hour] += 1

sorted_hours = sorted(hourly_pnl.keys())

print(f"{'Hour (UTC)':<12} | {'Trades':<8} | {'Total PnL':<15} | {'Avg PnL/Trade':<15}")
print("-" * 60)
for hour in sorted_hours:
    total_pnl = hourly_pnl[hour]
    count = hourly_trades_count[hour]
    avg_pnl = total_pnl / count if count > 0 else 0
    print(f"{hour:<12} | {count:<8} | {total_pnl:,.2f} | {avg_pnl:,.2f}")
print("=" * 60)
