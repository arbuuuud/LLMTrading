"""
Institutional Precision Visualizer (Plotly Interactive Candlestick Chart).
Generates an institutional-grade, TradingView-style interactive HTML chart where:
- Every trade has exact horizontal & connecting dashed lines (Entry Blue, TP Green, SL Red)
  rendered directly at the EXACT price levels on the candlestick body/wick.
- Shaded PnL boxes (Green for Profit, Red for Loss) spanning from entry time to exit time.
- Exact price badges on candle points.
- Instant search/jump dropdown to zoom into any trade.
- Fully self-contained HTML (No server required).
"""

import sys
from pathlib import Path
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from engine.core.event_engine import EventEngine
from engine.core.types import AccountConfig, OrderDirection, ExitReason
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from strategies.incubator.xauusd_trend_pullback_scalper import XAUUSDTrendPullbackScalper


def generate_plotly_visual(output_file: str = "reports/backtest_visual.html"):
    parquet_path = "data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet"
    print(f"[Plotly Visualizer] Loading data from {parquet_path}...")
    df = pl.read_parquet(parquet_path)
    print(f"[Plotly Visualizer] Loaded {len(df):,} M1 bars.")

    engine = EventEngine(
        config=AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0),
        commission_model=CommissionModel(7.0),
        slippage_model=FixedSlippageModel(0.02)
    )
    strategy = XAUUSDTrendPullbackScalper(risk_reward_ratio=2.0, max_bars_hold=25)

    print("[Plotly Visualizer] Running simulation...")
    res = engine.run_bars(df, strategy)
    perf = res["performance"]
    mc = res["monte_carlo"]
    trades = res["trades"]
    equity_curve = res["equity_curve"]

    buys_count = sum(1 for t in trades if t.direction == OrderDirection.BUY)
    sells_count = sum(1 for t in trades if t.direction == OrderDirection.SELL)

    # Extract OHLC arrays
    timestamps = [dt.strftime("%Y-%m-%d %H:%M:%S") for dt in df["timestamp"].to_list()]
    opens = df["open"].to_list()
    highs = df["high"].to_list()
    lows = df["low"].to_list()
    closes = df["close"].to_list()

    # Build trades data payload
    trade_list = []
    for i, t in enumerate(trades):
        is_buy = (t.direction == OrderDirection.BUY)
        is_win = (t.net_pnl > 0)
        trade_list.append({
            "id": i + 1,
            "side": "BUY" if is_buy else "SELL",
            "open_time": t.open_time.strftime("%Y-%m-%d %H:%M:%S"),
            "close_time": t.close_time.strftime("%Y-%m-%d %H:%M:%S"),
            "open_price": round(t.open_price, 2),
            "close_price": round(t.close_price, 2),
            "sl": round(t.stop_loss, 2) if t.stop_loss else None,
            "tp": round(t.take_profit, 2) if t.take_profit else None,
            "net_pnl": round(t.net_pnl, 2),
            "is_win": is_win,
            "exit_reason": t.exit_reason.value,
            "duration_min": round(t.duration_seconds / 60.0, 1)
        })

    # Equity curve arrays
    eq_times = [eq["timestamp"].strftime("%Y-%m-%d %H:%M:%S") for eq in equity_curve]
    eq_values = [round(eq["equity"], 2) for eq in equity_curve]

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>LLMTrading Institutional Visualizer</title>
    <script src="https://cdn.plot.ly/plotly-2.30.0.min.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: #0e1117;
            color: #e6edf3;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            overflow-x: hidden;
        }}
        header {{
            background: #161b22;
            padding: 14px 24px;
            border-bottom: 1px solid #30363d;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        h1 {{ font-size: 1.25rem; font-weight: 600; display: flex; align-items: center; gap: 8px; }}
        .badge {{ background: #238636; color: #fff; font-size: 0.75rem; padding: 3px 8px; border-radius: 4px; }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 12px;
            padding: 14px 24px;
            background: #0e1117;
            border-bottom: 1px solid #21262d;
        }}
        .stat-card {{
            background: #161b22;
            border: 1px solid #30363d;
            padding: 10px 14px;
            border-radius: 6px;
        }}
        .stat-label {{ font-size: 0.72rem; color: #8b949e; text-transform: uppercase; margin-bottom: 2px; }}
        .stat-value {{ font-size: 1.2rem; font-weight: 700; }}
        .val-green {{ color: #3fb950; }}
        .val-red {{ color: #f85149; }}
        .val-blue {{ color: #58a6ff; }}

        #controls-bar {{
            padding: 12px 24px;
            background: #161b22;
            border-bottom: 1px solid #30363d;
            display: flex;
            align-items: center;
            gap: 16px;
            flex-wrap: wrap;
        }}
        select, button {{
            background: #21262d;
            color: #c9d1d9;
            border: 1px solid #30363d;
            padding: 7px 14px;
            border-radius: 6px;
            font-size: 0.85rem;
            cursor: pointer;
            font-weight: 500;
        }}
        select:focus, button:hover {{ border-color: #58a6ff; background: #30363d; }}
        
        .legend-bar {{
            display: flex;
            align-items: center;
            gap: 14px;
            font-size: 0.82rem;
            margin-left: auto;
        }}
        .legend-item {{ display: flex; align-items: center; gap: 5px; }}
        .line-sample {{ width: 18px; height: 2px; display: inline-block; }}
        
        #charts-wrapper {{
            padding: 16px 24px;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }}
        .chart-box {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            overflow: hidden;
        }}
        .chart-header {{
            background: #161b22;
            padding: 10px 18px;
            font-size: 0.85rem;
            font-weight: 600;
            color: #8b949e;
            border-bottom: 1px solid #21262d;
            display: flex;
            justify-content: space-between;
        }}
        #candle-plot {{ height: 550px; width: 100%; }}
        #equity-plot {{ height: 220px; width: 100%; }}
        
        .table-section {{
            padding: 0 24px 32px 24px;
        }}
        .table-scroll {{
            max-height: 400px;
            overflow-y: auto;
            border: 1px solid #30363d;
            border-radius: 6px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: #161b22;
            font-size: 0.82rem;
        }}
        th, td {{
            padding: 9px 12px;
            text-align: left;
            border-bottom: 1px solid #21262d;
        }}
        th {{ background: #21262d; color: #8b949e; position: sticky; top: 0; z-index: 2; font-weight: 600; }}
        tr.trade-row {{ cursor: pointer; transition: background 0.15s; }}
        tr.trade-row:hover {{ background: #1f2937; }}
        tr.selected-row {{ background: #263342 !important; border-left: 4px solid #58a6ff; }}
    </style>
</head>
<body>
    <header>
        <h1>LLMTrading Visualizer <span class="badge">Institutional Scalp</span></h1>
        <div style="font-size:0.85rem; color:#8b949e;">
            XAUUSD (M1) | Bars: <strong>{len(df):,}</strong> | Trades: <strong>{len(trades)} ({buys_count} BUY / {sells_count} SELL)</strong>
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
            <div class="stat-label">Buys / Sells</div>
            <div class="stat-value">{buys_count} <span style="font-size:0.8rem; color:#8b949e;">/</span> {sells_count}</div>
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

    <div id="controls-bar">
        <label style="font-size:0.85rem; font-weight:600;">🔍 Jump to Trade:</label>
        <select id="trade-select" onchange="inspectTrade(this.value)">
            <option value="">-- Choose a Trade to Zoom & Show Exact SL/TP Lines --</option>
        </select>
        
        <button onclick="zoomAllTrades()">View All Trades</button>
        <button onclick="resetOverview()">Reset Full Chart</button>

        <div class="legend-bar">
            <div class="legend-item"><span class="line-sample" style="background:#58a6ff; border-top: 1px dotted #58a6ff;"></span> Entry Level</div>
            <div class="legend-item"><span class="line-sample" style="background:#3fb950; border-top: 2px dashed #3fb950;"></span> TP Target Level</div>
            <div class="legend-item"><span class="line-sample" style="background:#f85149; border-top: 2px dashed #f85149;"></span> SL Stop Level</div>
        </div>
    </div>

    <div id="charts-wrapper">
        <div class="chart-box">
            <div class="chart-header">
                <span id="chart-status-title">XAUUSD M1 Candlestick Chart (Plotly Institutional Engine)</span>
                <span id="inspect-label" style="color:#58a6ff; font-weight:500;">Select any trade to inspect</span>
            </div>
            <div id="candle-plot"></div>
        </div>
        <div class="chart-box">
            <div class="chart-header">
                <span>Equity Growth Curve ($10,000 Starting Balance)</span>
            </div>
            <div id="equity-plot"></div>
        </div>
    </div>

    <div class="table-section">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
            <h3 style="font-size:0.95rem; color:#fff;">All {len(trade_list)} Executed Trades (Click any row to jump to chart)</h3>
            <span style="font-size:0.8rem; color:#8b949e;">Sorted chronologically</span>
        </div>
        <div class="table-scroll">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Side</th>
                        <th>Entry Time</th>
                        <th>Exit Time</th>
                        <th>Entry Price</th>
                        <th>Exit Price</th>
                        <th>Stop Loss</th>
                        <th>Take Profit</th>
                        <th>Net PnL ($)</th>
                        <th>Exit Reason</th>
                        <th>Duration</th>
                    </tr>
                </thead>
                <tbody id="table-body"></tbody>
            </table>
        </div>
    </div>

    <script>
        const timestamps = {json.dumps(timestamps)};
        const opens = {json.dumps(opens)};
        const highs = {json.dumps(highs)};
        const lows = {json.dumps(lows)};
        const closes = {json.dumps(closes)};
        const trades = {json.dumps(trade_list)};
        const eqTimes = {json.dumps(eq_times)};
        const eqValues = {json.dumps(eq_values)};

        // Build base candlestick trace
        const candleTrace = {{
            x: timestamps,
            open: opens,
            high: highs,
            low: lows,
            close: closes,
            type: 'candlestick',
            name: 'XAUUSD M1',
            increasing: {{ line: {{ color: '#3fb950' }} }},
            decreasing: {{ line: {{ color: '#f85149' }} }},
            showlegend: false
        }};

        // Build Entry & Exit Scatter Markers
        const buyEntries = trades.filter(t => t.side === 'BUY');
        const sellEntries = trades.filter(t => t.side === 'SELL');
        const winExits = trades.filter(t => t.is_win);
        const lossExits = trades.filter(t => !t.is_win);

        const buyMarkerTrace = {{
            x: buyEntries.map(t => t.open_time),
            y: buyEntries.map(t => t.open_price),
            mode: 'markers+text',
            type: 'scatter',
            name: 'BUY Entry',
            text: buyEntries.map(t => '#' + t.id + ' BUY'),
            textposition: 'bottom center',
            textfont: {{ color: '#3fb950', size: 10 }},
            marker: {{
                symbol: 'triangle-up',
                color: '#3fb950',
                size: 13,
                line: {{ color: '#ffffff', width: 1 }}
            }}
        }};

        const sellMarkerTrace = {{
            x: sellEntries.map(t => t.open_time),
            y: sellEntries.map(t => t.open_price),
            mode: 'markers+text',
            type: 'scatter',
            name: 'SELL Entry',
            text: sellEntries.map(t => '#' + t.id + ' SELL'),
            textposition: 'top center',
            textfont: {{ color: '#f85149', size: 10 }},
            marker: {{
                symbol: 'triangle-down',
                color: '#f85149',
                size: 13,
                line: {{ color: '#ffffff', width: 1 }}
            }}
        }};

        const winExitTrace = {{
            x: winExits.map(t => t.close_time),
            y: winExits.map(t => t.close_price),
            mode: 'markers+text',
            type: 'scatter',
            name: 'Take Profit Exit',
            text: winExits.map(t => '+$' + t.net_pnl.toFixed(0)),
            textposition: 'top right',
            textfont: {{ color: '#3fb950', size: 10 }},
            marker: {{ symbol: 'circle', color: '#3fb950', size: 8 }}
        }};

        const lossExitTrace = {{
            x: lossExits.map(t => t.close_time),
            y: lossExits.map(t => t.close_price),
            mode: 'markers+text',
            type: 'scatter',
            name: 'Stop Loss Exit',
            text: lossExits.map(t => '-$' + Math.abs(t.net_pnl).toFixed(0)),
            textposition: 'bottom right',
            textfont: {{ color: '#f85149', size: 10 }},
            marker: {{ symbol: 'x', color: '#f85149', size: 8 }}
        }};

        const candleLayout = {{
            dragmode: 'zoom',
            margin: {{ r: 50, t: 25, b: 40, l: 60 }},
            showlegend: true,
            legend: {{ orientation: 'h', y: 1.05, x: 0, font: {{ color: '#8b949e', size: 11 }} }},
            plot_bgcolor: '#161b22',
            paper_bgcolor: '#161b22',
            xaxis: {{
                rangeslider: {{ visible: false }},
                color: '#8b949e',
                gridcolor: '#21262d'
            }},
            yaxis: {{
                color: '#8b949e',
                gridcolor: '#21262d',
                autorange: true
            }}
        }};

        Plotly.newPlot('candle-plot', [candleTrace, buyMarkerTrace, sellMarkerTrace, winExitTrace, lossExitTrace], candleLayout, {{ responsive: true }});

        // Equity Plot
        const eqTrace = {{
            x: eqTimes,
            y: eqValues,
            type: 'scatter',
            mode: 'lines',
            fill: 'tozeroy',
            line: {{ color: '#58a6ff', width: 2 }},
            fillcolor: 'rgba(88, 166, 255, 0.15)',
            name: 'Account Equity'
        }};
        const eqLayout = {{
            margin: {{ r: 50, t: 15, b: 35, l: 60 }},
            plot_bgcolor: '#161b22',
            paper_bgcolor: '#161b22',
            xaxis: {{ color: '#8b949e', gridcolor: '#21262d' }},
            yaxis: {{ color: '#8b949e', gridcolor: '#21262d' }},
            showlegend: false
        }};
        Plotly.newPlot('equity-plot', [eqTrace], eqLayout, {{ responsive: true }});

        // Populate Table & Dropdown
        const select = document.getElementById('trade-select');
        const tbody = document.getElementById('table-body');

        trades.forEach(t => {{
            // Add to dropdown
            const opt = document.createElement('option');
            opt.value = t.id;
            const pnlStr = (t.net_pnl > 0 ? '+' : '') + '$' + t.net_pnl.toFixed(2);
            opt.textContent = `Trade #${{t.id}} [${{t.side}}] ${{t.open_time}} | Entry: ${{t.open_price}} | PnL: ${{pnlStr}} (${{t.exit_reason}})`;
            select.appendChild(opt);

            // Add table row
            const tr = document.createElement('tr');
            tr.id = 'trade-row-' + t.id;
            tr.className = 'trade-row';
            tr.onclick = () => inspectTrade(t.id);

            tr.innerHTML = `
                <td>${{t.id}}</td>
                <td style="font-weight:700; color:${{t.side === 'BUY' ? '#3fb950' : '#f85149'}};">${{t.side}}</td>
                <td>${{t.open_time}}</td>
                <td>${{t.close_time}}</td>
                <td>$${{t.open_price.toFixed(2)}}</td>
                <td>$${{t.close_price.toFixed(2)}}</td>
                <td style="color:#f85149; font-weight:600;">$${{t.sl ? t.sl.toFixed(2) : '-'}}</td>
                <td style="color:#3fb950; font-weight:600;">$${{t.tp ? t.tp.toFixed(2) : '-'}}</td>
                <td style="font-weight:700; color:${{t.is_win ? '#3fb950' : '#f85149'}};">${{pnlStr}}</td>
                <td>${{t.exit_reason}}</td>
                <td>${{t.duration_min}}m</td>
            `;
            tbody.appendChild(tr);
        }});

        function inspectTrade(tradeId) {{
            if (!tradeId) return;
            const id = parseInt(tradeId);
            const trade = trades.find(t => t.id === id);
            if (!trade) return;

            select.value = id;

            // Highlight table row
            document.querySelectorAll('.trade-row').forEach(r => r.classList.remove('selected-row'));
            const row = document.getElementById('trade-row-' + id);
            if (row) {{
                row.classList.add('selected-row');
                row.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
            }}

            // Draw Shapes: Dashed Horizontal Lines for Entry, TP, and SL
            const shapes = [];

            // 1. Entry Line (Blue Dotted)
            shapes.push({{
                type: 'line',
                x0: trade.open_time,
                y0: trade.open_price,
                x1: trade.close_time,
                y1: trade.open_price,
                line: {{ color: '#58a6ff', width: 2, dash: 'dot' }}
            }});

            // 2. Take Profit Line (Green Dashed)
            if (trade.tp) {{
                shapes.push({{
                    type: 'line',
                    x0: trade.open_time,
                    y0: trade.tp,
                    x1: trade.close_time,
                    y1: trade.tp,
                    line: {{ color: '#3fb950', width: 2, dash: 'dash' }}
                }});
            }}

            // 3. Stop Loss Line (Red Dashed)
            if (trade.sl) {{
                shapes.push({{
                    type: 'line',
                    x0: trade.open_time,
                    y0: trade.sl,
                    x1: trade.close_time,
                    y1: trade.sl,
                    line: {{ color: '#f85149', width: 2, dash: 'dash' }}
                }});
            }}

            // 4. Shaded Box connecting Entry to Exit
            shapes.push({{
                type: 'rect',
                x0: trade.open_time,
                y0: trade.open_price,
                x1: trade.close_time,
                y1: trade.close_price,
                fillcolor: trade.is_win ? 'rgba(63, 185, 80, 0.18)' : 'rgba(248, 81, 73, 0.18)',
                line: {{ width: 0 }}
            }});

            // Annotations to show exact labels on chart
            const annotations = [
                {{
                    x: trade.open_time,
                    y: trade.open_price,
                    text: `Entry: $${{trade.open_price.toFixed(2)}}`,
                    showarrow: true,
                    arrowhead: 2,
                    arrowcolor: '#58a6ff',
                    font: {{ color: '#58a6ff', size: 11 }},
                    bgcolor: '#161b22',
                    bordercolor: '#58a6ff'
                }},
                {{
                    x: trade.close_time,
                    y: trade.close_price,
                    text: `Exit: $${{trade.close_price.toFixed(2)}} (${{trade.exit_reason}})`,
                    showarrow: true,
                    arrowhead: 2,
                    arrowcolor: trade.is_win ? '#3fb950' : '#f85149',
                    font: {{ color: trade.is_win ? '#3fb950' : '#f85149', size: 11 }},
                    bgcolor: '#161b22',
                    bordercolor: trade.is_win ? '#3fb950' : '#f85149'
                }}
            ];

            if (trade.tp) {{
                annotations.push({{
                    x: trade.close_time,
                    y: trade.tp,
                    text: `TP Target: $${{trade.tp.toFixed(2)}}`,
                    showarrow: false,
                    font: {{ color: '#3fb950', size: 10 }},
                    bgcolor: '#161b22'
                }});
            }}
            if (trade.sl) {{
                annotations.push({{
                    x: trade.close_time,
                    y: trade.sl,
                    text: `SL Stop: $${{trade.sl.toFixed(2)}}`,
                    showarrow: false,
                    font: {{ color: '#f85149', size: 10 }},
                    bgcolor: '#161b22'
                }});
            }}

            // Calculate zoom range (30 minutes before, 30 minutes after)
            const openDate = new Date(trade.open_time);
            const closeDate = new Date(trade.close_time);
            const xMin = new Date(openDate.getTime() - 25 * 60 * 1000).toISOString().replace('T', ' ').substring(0, 19);
            const xMax = new Date(closeDate.getTime() + 25 * 60 * 1000).toISOString().replace('T', ' ').substring(0, 19);

            const yPrices = [trade.open_price, trade.close_price];
            if (trade.sl) yPrices.push(trade.sl);
            if (trade.tp) yPrices.push(trade.tp);
            const yMin = Math.min(...yPrices) - 1.0;
            const yMax = Math.max(...yPrices) + 1.0;

            Plotly.relayout('candle-plot', {{
                'xaxis.range': [xMin, xMax],
                'yaxis.range': [yMin, yMax],
                'yaxis.autorange': false,
                'shapes': shapes,
                'annotations': annotations
            }});

            const pnlStr = (trade.net_pnl > 0 ? '+' : '') + '$' + trade.net_pnl.toFixed(2);
            document.getElementById('inspect-label').innerHTML = `Inspecting <strong>Trade #${{trade.id}} (${{trade.side}})</strong>: Entry <strong>$${{trade.open_price}}</strong> | SL: <strong style="color:#f85149;">$${{trade.sl}}</strong> | TP: <strong style="color:#3fb950;">$${{trade.tp}}</strong> | PnL: <strong style="color:${{trade.is_win ? '#3fb950' : '#f85149'}};">${{pnlStr}}</strong>`;
        }}

        function resetOverview() {{
            Plotly.relayout('candle-plot', {{
                'xaxis.autorange': true,
                'yaxis.autorange': true,
                'shapes': [],
                'annotations': []
            }});
            document.getElementById('inspect-label').textContent = 'Full overview restored';
            document.querySelectorAll('.trade-row').forEach(r => r.classList.remove('selected-row'));
            select.value = '';
        }}

        function zoomAllTrades() {{
            // Show all trades with full range
            resetOverview();
        }}
    </script>
</body>
</html>
"""

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        f.write(html_content)

    print(f"[Plotly Visualizer] SUCCESS! Generated at: {out_path.resolve()}")
    return str(out_path.resolve())


if __name__ == "__main__":
    generate_plotly_visual()
