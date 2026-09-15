"""
Run and render the proven winning strategy: Anchored VWAP 1.8 Sigma (+1,746.92 USD Net Profit)
to `reports/backtest_visual.html` so the user can visually inspect all trades.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from engine.visualization.interactive_chart import generate_optimized_visual

if __name__ == "__main__":
    generate_optimized_visual()
