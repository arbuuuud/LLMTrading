"""
Interactive Institutional Visualizer (TradingView Lightweight Charts).
Generates an interactive HTML dashboard with candlestick chart, trade markers (BUY/SELL),
SL/TP visualization, performance summary, and equity curve.
"""

import sys
from pathlib import Path
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from engine.core.event_engine import EventEngine
from engine.core.types import AccountConfig, OrderDirection
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from strategies.incubator.xauusd_trend_pullback_scalper import XAUUSDTrendPullbackScalper


def generate_visual_html(output_file: str = "reports/backtest_visual.html"):
    parquet_path = "data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet"
    print(f"[Visualizer] Loading data from {parquet_path}...")
    df = pl.read_parquet(parquet_path)
    print(f"[Visualizer] Loaded {len(df):,} M1 bars.")

    engine = EventEngine(
        config=AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0),
        commission_model=CommissionModel(7.0),
        slippage_model=FixedSlippageModel(0.02)
    )
    strategy = XAUUSDTrendPullbackScalper(risk_reward_ratio=2.0, max_bars_hold=25)

    print("[Visualizer] Running backtest simulation...")
    res = engine.run_bars(df, strategy)
    perf = res["performance"]
    mc = res["monte_carlo"]
    trades = res["trades"]
    equity_curve = res["equity_curve"]

    print(f"[Visualizer] Generated {len(trades)} trades. Win Rate: {perf.win_rate_pct}% | PF: {perf.profit_factor}")

    # Prepare Candlestick data for Lightweight Charts (timestamp in unix seconds)
    candles = []
    for row in df.iter_rows(named=True):
        dt = row["timestamp"]
        candles.append({
            "time": int(dt.timestamp()),
            "open": round(row["open"], 2),
            "high": round(row["high"], 2),
            "low": round(row["low"], 2),
            "close": round(row["close"], 2)
        })

    # Prepare Trade Markers
    markers = []
    trade_details = []
    for i, t in enumerate(trades):
        is_buy = (t.direction == OrderDirection.BUY)
        is_win = (t.net_pnl > 0)
        
        # Entry Marker
        markers.append({
            "time": int(t.open_time.timestamp()),
            "position": "belowBar" if is_buy else "aboveBar",
            "color": "#00E676" if is_buy else "#FF1744",
            "shape": "arrowUp" if is_buy else "arrowDown",
            "text": f"{'BUY' if is_buy else 'SELL'} #{i+1} (${t.open_price:.2f})"
        })

        # Exit Marker
        markers.append({
            "time": int(t.close_time.timestamp()),
            "position": "aboveBar" if is_buy else "belowBar",
            "color": "#00E676" if is_win else "#FF5252",
            "shape": "circle",
            "text": f"{'+' if is_win else ''}${t.net_pnl:.2f} ({t.exit_reason.value})"
        })

        trade_details.append({
            "id": i + 1,
            "side": "BUY" if is_buy else "SELL",
            "open_time": t.open_time.strftime("%Y-%m-%d %H:%M"),
            "close_time": t.close_time.strftime("%Y-%m-%d %H:%M"),
            "open_price": t.open_price,
            "close_price": t.close_price,
            "sl": t.stop_loss,
            "tp": t.take_profit,
            "net_pnl": t.net_pnl,
            "exit_reason": t.exit_reason.value,
            "duration_min": round(t.duration_seconds / 60.0, 1)
        })

    # Prepare Equity data
    equity_data = []
    for eq in equity_curve:
        equity_data.append({
            "time": int(eq["timestamp"].timestamp()),
            "value": eq["equity"]
        })

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>LLMTrading Visualizer - XAUUSD Scalping</title>
    <script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: #0f141c;
            color: #d1d4dc;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            overflow-x: hidden;
        }}
        header {{
            background: #182230;
            padding: 16px 24px;
            border-bottom: 1px solid #2a3b50;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        h1 {{ font-size: 1.25rem; color: #fff; font-weight: 600; display: flex; align-items: center; gap: 8px; }}
        .badge {{ background: #2962ff; color: #fff; font-size: 0.75rem; padding: 4px 8px; border-radius: 4px; }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 12px;
            padding: 16px 24px;
            background: #131b26;
            border-bottom: 1px solid #2a3b50;
        }}
        .stat-card {{
            background: #182230;
            border: 1px solid #2a3b50;
            padding: 12px 16px;
            border-radius: 6px;
        }}
        .stat-label {{ font-size: 0.75rem; color: #788b9c; text-transform: uppercase; margin-bottom: 4px; }}
        .stat-value {{ font-size: 1.25rem; font-weight: 700; }}
        .val-green {{ color: #00e676; }}
        .val-red {{ color: #ff5252; }}
        .val-blue {{ color: #29b6f6; }}
        #charts-container {{
            padding: 16px 24px;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }}
        .chart-box {{
            background: #131b26;
            border: 1px solid #2a3b50;
            border-radius: 8px;
            overflow: hidden;
            position: relative;
        }}
        .chart-title {{
            background: #182230;
            padding: 10px 16px;
            font-size: 0.85rem;
            font-weight: 600;
            color: #90a4ae;
            border-bottom: 1px solid #2a3b50;
        }}
        #candle-chart {{ height: 500px; width: 100%; }}
        #equity-chart {{ height: 220px; width: 100%; }}
        .trades-table-container {{
            padding: 0 24px 32px 24px;
        }}
        .table-title {{
            font-size: 1rem;
            font-weight: 600;
            margin-bottom: 12px;
            color: #fff;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: #131b26;
            border: 1px solid #2a3b50;
            border-radius: 6px;
            overflow: hidden;
            font-size: 0.85rem;
        }}
        th, td {{
            padding: 10px 14px;
            text-align: left;
            border-bottom: 1px solid #223042;
        }}
        th {{ background: #182230; color: #90a4ae; font-weight: 600; }}
        tr:hover {{ background: #1a2536; }}
    </style>
</head>
<body>
    <header>
        <h1>LLMTrading Visualizer <span class="badge">Institutional Scalp</span></h1>
        <div style="font-size: 0.85rem; color: #90a4ae;">
            Asset: <strong style="color:#fff;">XAUUSD (M1)</strong> | Period: <strong>2025-05-27 - 2025-06-03</strong>
        </div>
    </header>

    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-label">Net Profit</div>
            <div class="stat-value {'val-green' if perf.net_profit >= 0 else 'val-red'}">
                {'+' if perf.net_profit >= 0 else ''}${perf.net_profit:,.2f}
            </div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Profit Factor</div>
            <div class="stat-value val-blue">{perf.profit_factor:.2f}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Win Rate</div>
            <div class="stat-value val-green">{perf.win_rate_pct:.1f}%</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Total Trades</div>
            <div class="stat-value">{perf.total_trades}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Max Drawdown</div>
            <div class="stat-value val-red">{perf.max_drawdown_pct:.2f}%</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Monte Carlo P95 DD</div>
            <div class="stat-value val-blue">{mc.p95_max_drawdown_pct:.2f}%</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Commissions Paid</div>
            <div class="stat-value">${perf.total_commission_paid:,.2f}</div>
        </div>
    </div>

    <div id="charts-container">
        <div class="chart-box">
            <div class="chart-title">XAUUSD M1 Interactive Candlestick Chart (Pan, Zoom, Inspect Arrows)</div>
            <div id="candle-chart"></div>
        </div>
        <div class="chart-box">
            <div class="chart-title">Equity Growth Curve ($10,000 Initial Capital)</div>
            <div id="equity-chart"></div>
        </div>
    </div>

    <div class="trades-table-container">
        <div class="table-title">Executed Trades Log (Latest 25 Trades)</div>
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Type</th>
                    <th>Entry Time</th>
                    <th>Exit Time</th>
                    <th>Entry Price</th>
                    <th>Exit Price</th>
                    <th>Stop Loss</th>
                    <th>Take Profit</th>
                    <th>Net PnL ($)</th>
                    <th>Exit Reason</th>
                    <th>Hold (Min)</th>
                </tr>
            </thead>
            <tbody>
"""

    for t in trade_details[-25:]:
        is_win = (t["net_pnl"] > 0)
        html_content += f"""
                <tr>
                    <td>{t['id']}</td>
                    <td style="font-weight:600; color:{'#00e676' if t['side']=='BUY' else '#ff1744'};">{t['side']}</td>
                    <td>{t['open_time']}</td>
                    <td>{t['close_time']}</td>
                    <td>${t['open_price']:.2f}</td>
                    <td>${t['close_price']:.2f}</td>
                    <td>${t['sl']:.2f}</td>
                    <td>${t['tp']:.2f}</td>
                    <td style="font-weight:700; color:{'#00e676' if is_win else '#ff5252'};">{'+' if is_win else ''}${t['net_pnl']:.2f}</td>
                    <td>{t['exit_reason']}</td>
                    <td>{t['duration_min']}m</td>
                </tr>
        """

    html_content += f"""
            </tbody>
        </table>
    </div>

    <script>
        const candleData = {json.dumps(candles)};
        const markersData = {json.dumps(markers)};
        const equityData = {json.dumps(equity_data)};

        // 1. Candlestick Chart
        const chartElement = document.getElementById('candle-chart');
        const chart = LightweightCharts.createChart(chartElement, {{
            layout: {{
                background: {{ color: '#131b26' }},
                textColor: '#90a4ae',
            }},
            grid: {{
                vertLines: {{ color: '#1c2838' }},
                horzLines: {{ color: '#1c2838' }},
            }},
            crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
            rightPriceScale: {{ borderColor: '#2a3b50' }},
            timeScale: {{
                borderColor: '#2a3b50',
                timeVisible: true,
                secondsVisible: false
            }},
        }});

        const candleSeries = chart.addCandlestickSeries({{
            upColor: '#00e676',
            downColor: '#ff5252',
            borderVisible: false,
            wickUpColor: '#00e676',
            wickDownColor: '#ff5252',
        }});

        candleSeries.setData(candleData);
        candleSeries.setMarkers(markersData);

        // 2. Equity Curve Chart
        const eqElement = document.getElementById('equity-chart');
        const eqChart = LightweightCharts.createChart(eqElement, {{
            layout: {{
                background: {{ color: '#131b26' }},
                textColor: '#90a4ae',
            }},
            grid: {{
                vertLines: {{ color: '#1c2838' }},
                horzLines: {{ color: '#1c2838' }},
            }},
            rightPriceScale: {{ borderColor: '#2a3b50' }},
            timeScale: {{
                borderColor: '#2a3b50',
                timeVisible: true,
                secondsVisible: false
            }},
        }});

        const eqSeries = eqChart.addAreaSeries({{
            topColor: 'rgba(41, 182, 246, 0.4)',
            bottomColor: 'rgba(41, 182, 246, 0.0)',
            lineColor: '#29b6f6',
            lineWidth: 2,
        }});

        eqSeries.setData(equityData);

        // Synchronize TimeScales
        chart.timeScale().subscribeVisibleTimeRangeChange(range => {{
            eqChart.timeScale().setVisibleRange(range);
        }});

        // Responsive resize
        window.addEventListener('resize', () => {{
            chart.applyOptions({{ width: chartElement.clientWidth }});
            eqChart.applyOptions({{ width: eqElement.clientWidth }});
        }});
    </script>
</body>
</html>
"""

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        f.write(html_content)

    print(f"[Visualizer] SUCCESS! Interactive HTML generated at: {out_path.resolve()}")
    return str(out_path.resolve())


if __name__ == "__main__":
    generate_visual_html()
