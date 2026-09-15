"""
Interactive Institutional Visualizer (TradingView Lightweight Charts).
Generates an interactive HTML dashboard with:
- Candlestick chart
- Exact Trade Entry markers (BUY green arrow / SELL red arrow)
- Exit markers (Target TP circle green / Stop Loss circle red / Time Exit orange)
- Dashed Lines connecting Entry -> SL (red dashed) and Entry -> TP (green dashed)
- Interactive Trade Selector: Clicking or selecting any trade automatically scrolls and zooms
  the chart directly to that trade with horizontal SL/TP rays!
- Complete Trade Table with filtering (All, Buys, Sells, Winners, Losers).
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

    buys_count = sum(1 for t in trades if t.direction == OrderDirection.BUY)
    sells_count = sum(1 for t in trades if t.direction == OrderDirection.SELL)
    print(f"[Visualizer] Generated {len(trades)} trades (Buys: {buys_count}, Sells: {sells_count}).")

    # Prepare Candlestick data for Lightweight Charts
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

    # Prepare Markers and Trade Records with full entry/exit/SL/TP coordinates
    markers = []
    trade_records = []

    for i, t in enumerate(trades):
        is_buy = (t.direction == OrderDirection.BUY)
        is_win = (t.net_pnl > 0)
        open_ts = int(t.open_time.timestamp())
        close_ts = int(t.close_time.timestamp())

        # Entry Marker: BELOW bar for BUY (arrow pointing up), ABOVE bar for SELL (arrow pointing down)
        markers.append({
            "time": open_ts,
            "position": "belowBar" if is_buy else "aboveBar",
            "color": "#00E676" if is_buy else "#FF1744",
            "shape": "arrowUp" if is_buy else "arrowDown",
            "text": f"{'BUY' if is_buy else 'SELL'} #{i+1} (${t.open_price:.2f})"
        })

        # Exit Marker: Shape circle with profit/loss
        if t.exit_reason == ExitReason.TAKE_PROFIT:
            exit_color = "#00E676"
            exit_label = f"TP #{i+1}: +${t.net_pnl:.2f}"
        elif t.exit_reason == ExitReason.STOP_LOSS:
            exit_color = "#FF1744"
            exit_label = f"SL #{i+1}: -${abs(t.net_pnl):.2f}"
        else:
            exit_color = "#FF9100"
            exit_label = f"TIME #{i+1}: {'+' if is_win else '-'}${abs(t.net_pnl):.2f}"

        markers.append({
            "time": close_ts,
            "position": "aboveBar" if is_buy else "belowBar",
            "color": exit_color,
            "shape": "circle",
            "text": exit_label
        })

        trade_records.append({
            "id": i + 1,
            "side": "BUY" if is_buy else "SELL",
            "open_time_str": t.open_time.strftime("%Y-%m-%d %H:%M"),
            "close_time_str": t.close_time.strftime("%Y-%m-%d %H:%M"),
            "open_ts": open_ts,
            "close_ts": close_ts,
            "open_price": round(t.open_price, 2),
            "close_price": round(t.close_price, 2),
            "sl": round(t.stop_loss, 2) if t.stop_loss else None,
            "tp": round(t.take_profit, 2) if t.take_profit else None,
            "net_pnl": round(t.net_pnl, 2),
            "exit_reason": t.exit_reason.value,
            "duration_min": round(t.duration_seconds / 60.0, 1)
        })

    # Prepare Equity data
    equity_data = []
    for eq in equity_curve:
        equity_data.append({
            "time": int(eq["timestamp"].timestamp()),
            "value": round(eq["equity"], 2)
        })

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>LLMTrading Visualizer - XAUUSD Scalping Engine</title>
    <script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: #0d1117;
            color: #c9d1d9;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
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
        h1 {{ font-size: 1.2rem; color: #fff; font-weight: 600; display: flex; align-items: center; gap: 8px; }}
        .badge {{ background: #238636; color: #fff; font-size: 0.75rem; padding: 3px 8px; border-radius: 4px; }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 12px;
            padding: 14px 24px;
            background: #0d1117;
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
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 0.85rem;
            cursor: pointer;
        }}
        select:focus, button:hover {{ border-color: #58a6ff; }}
        .legend-chip {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 0.8rem;
            margin-left: auto;
        }}
        .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
        
        #charts-container {{
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
            position: relative;
        }}
        .chart-title {{
            background: #161b22;
            padding: 8px 16px;
            font-size: 0.82rem;
            font-weight: 600;
            color: #8b949e;
            border-bottom: 1px solid #21262d;
            display: flex;
            justify-content: space-between;
        }}
        #candle-chart {{ height: 520px; width: 100%; }}
        #equity-chart {{ height: 200px; width: 100%; }}
        
        .trades-container {{
            padding: 0 24px 32px 24px;
        }}
        .table-wrapper {{
            max-height: 380px;
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
            padding: 8px 12px;
            text-align: left;
            border-bottom: 1px solid #21262d;
        }}
        th {{ background: #21262d; color: #8b949e; position: sticky; top: 0; z-index: 2; }}
        tr.clickable-row {{ cursor: pointer; transition: background 0.15s; }}
        tr.clickable-row:hover {{ background: #1f2937; }}
        tr.selected-row {{ background: #263342 !important; border-left: 3px solid #58a6ff; }}
    </style>
</head>
<body>
    <header>
        <h1>LLMTrading Visualizer <span class="badge">Institutional Scalp</span></h1>
        <div style="font-size: 0.85rem; color: #8b949e;">
            Asset: <strong style="color:#fff;">XAUUSD (M1)</strong> | Period: <strong>2025-05-27 to 2025-06-03</strong>
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

    <div id="controls-bar">
        <label style="font-size:0.85rem; font-weight:600;">Jump & Inspect Trade:</label>
        <select id="trade-select" onchange="onSelectTrade(this.value)">
            <option value="">-- Click a Trade to Zoom & Draw SL/TP Lines --</option>
        </select>
        
        <button onclick="resetZoom()">Reset Zoom</button>
        
        <div class="legend-chip">
            <span><span class="dot" style="background:#00E676;"></span> BUY</span> &nbsp;
            <span><span class="dot" style="background:#FF1744;"></span> SELL</span> &nbsp;
            <span style="color:#00E676;">--- TP Line</span> &nbsp;
            <span style="color:#FF1744;">--- SL Line</span>
        </div>
    </div>

    <div id="charts-container">
        <div class="chart-box">
            <div class="chart-title">
                <span>Interactive Price Chart (M1)</span>
                <span id="inspected-info" style="color:#58a6ff;">Zoom with mouse wheel, drag to pan</span>
            </div>
            <div id="candle-chart"></div>
        </div>
        <div class="chart-box">
            <div class="chart-title">
                <span>Equity Growth Curve ($10,000 Starting Capital)</span>
            </div>
            <div id="equity-chart"></div>
        </div>
    </div>

    <div class="trades-container">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <h3 style="font-size:0.95rem; color:#fff;">Complete Trade Ledger (Click any row to jump to chart)</h3>
            <span style="font-size:0.8rem; color:#8b949e;">Showing all {len(trade_records)} trades</span>
        </div>
        <div class="table-wrapper">
            <table id="trades-table">
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
                        <th>Duration</th>
                    </tr>
                </thead>
                <tbody id="trades-tbody">
                </tbody>
            </table>
        </div>
    </div>

    <script>
        const candleData = {json.dumps(candles)};
        const markersData = {json.dumps(markers)};
        const equityData = {json.dumps(equity_data)};
        const tradeRecords = {json.dumps(trade_records)};

        // 1. Initialize Candlestick Chart
        const chartElement = document.getElementById('candle-chart');
        const chart = LightweightCharts.createChart(chartElement, {{
            layout: {{
                background: {{ color: '#161b22' }},
                textColor: '#8b949e',
            }},
            grid: {{
                vertLines: {{ color: '#21262d' }},
                horzLines: {{ color: '#21262d' }},
            }},
            crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
            rightPriceScale: {{ borderColor: '#30363d' }},
            timeScale: {{
                borderColor: '#30363d',
                timeVisible: true,
                secondsVisible: false
            }},
        }});

        const candleSeries = chart.addCandlestickSeries({{
            upColor: '#3fb950',
            downColor: '#f85149',
            borderVisible: false,
            wickUpColor: '#3fb950',
            wickDownColor: '#f85149',
        }});

        candleSeries.setData(candleData);
        candleSeries.setMarkers(markersData);

        // 2. Initialize Equity Chart
        const eqElement = document.getElementById('equity-chart');
        const eqChart = LightweightCharts.createChart(eqElement, {{
            layout: {{
                background: {{ color: '#161b22' }},
                textColor: '#8b949e',
            }},
            grid: {{
                vertLines: {{ color: '#21262d' }},
                horzLines: {{ color: '#21262d' }},
            }},
            rightPriceScale: {{ borderColor: '#30363d' }},
            timeScale: {{
                borderColor: '#30363d',
                timeVisible: true,
                secondsVisible: false
            }},
        }});

        const eqSeries = eqChart.addAreaSeries({{
            topColor: 'rgba(88, 166, 255, 0.35)',
            bottomColor: 'rgba(88, 166, 255, 0.0)',
            lineColor: '#58a6ff',
            lineWidth: 2,
        }});
        eqSeries.setData(equityData);

        // Dynamic Line Series for Active SL / TP Lines
        let entryLineSeries = null;
        let tpLineSeries = null;
        let slLineSeries = null;

        function clearTradeLines() {{
            if (entryLineSeries) {{ chart.removeSeries(entryLineSeries); entryLineSeries = null; }}
            if (tpLineSeries) {{ chart.removeSeries(tpLineSeries); tpLineSeries = null; }}
            if (slLineSeries) {{ chart.removeSeries(slLineSeries); slLineSeries = null; }}
        }}

        function drawTradeLines(trade) {{
            clearTradeLines();
            if (!trade) return;

            const tStart = trade.open_ts;
            // Extend line slightly past exit for clear visual
            const tEnd = trade.close_ts + 300;

            // 1. Entry Line (Blue Dotted)
            entryLineSeries = chart.addLineSeries({{
                color: '#58a6ff',
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dotted,
                title: 'Entry'
            }});
            entryLineSeries.setData([
                {{ time: tStart, value: trade.open_price }},
                {{ time: tEnd, value: trade.open_price }}
            ]);

            // 2. Take Profit Line (Green Dashed)
            if (trade.tp) {{
                tpLineSeries = chart.addLineSeries({{
                    color: '#3fb950',
                    lineWidth: 2,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    title: 'TP Target'
                }});
                tpLineSeries.setData([
                    {{ time: tStart, value: trade.tp }},
                    {{ time: tEnd, value: trade.tp }}
                ]);
            }}

            // 3. Stop Loss Line (Red Dashed)
            if (trade.sl) {{
                slLineSeries = chart.addLineSeries({{
                    color: '#f85149',
                    lineWidth: 2,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    title: 'SL Stop'
                }});
                slLineSeries.setData([
                    {{ time: tStart, value: trade.sl }},
                    {{ time: tEnd, value: trade.sl }}
                ]);
            }}
        }}

        // Populate Dropdown & Table
        const select = document.getElementById('trade-select');
        const tbody = document.getElementById('trades-tbody');

        tradeRecords.forEach(t => {{
            // Add Option
            const opt = document.createElement('option');
            opt.value = t.id;
            const pnlStr = (t.net_pnl > 0 ? '+' : '') + '$' + t.net_pnl.toFixed(2);
            opt.textContent = `#${{t.id}} [${{t.side}}] ${{t.open_time_str}} | Entry: ${{t.open_price}} | PnL: ${{pnlStr}} (${{t.exit_reason}})`;
            select.appendChild(opt);

            // Add Table Row
            const tr = document.createElement('tr');
            tr.id = 'trade-row-' + t.id;
            tr.className = 'clickable-row';
            tr.onclick = () => onSelectTrade(t.id);

            const isWin = (t.net_pnl > 0);
            tr.innerHTML = `
                <td>${{t.id}}</td>
                <td style="font-weight:700; color:${{t.side === 'BUY' ? '#3fb950' : '#f85149'}};">${{t.side}}</td>
                <td>${{t.open_time_str}}</td>
                <td>${{t.close_time_str}}</td>
                <td>${{t.open_price.toFixed(2)}}</td>
                <td>${{t.close_price.toFixed(2)}}</td>
                <td style="color:#f85149;">${{t.sl ? t.sl.toFixed(2) : '-'}}</td>
                <td style="color:#3fb950;">${{t.tp ? t.tp.toFixed(2) : '-'}}</td>
                <td style="font-weight:700; color:${{isWin ? '#3fb950' : '#f85149'}};">${{pnlStr}}</td>
                <td>${{t.exit_reason}}</td>
                <td>${{t.duration_min}}m</td>
            `;
            tbody.appendChild(tr);
        }});

        function onSelectTrade(tradeId) {{
            if (!tradeId) return;
            const id = parseInt(tradeId);
            const trade = tradeRecords.find(t => t.id === id);
            if (!trade) return;

            select.value = id;

            // Highlight table row
            document.querySelectorAll('.clickable-row').forEach(r => r.classList.remove('selected-row'));
            const selectedRow = document.getElementById('trade-row-' + id);
            if (selectedRow) {{
                selectedRow.classList.add('selected-row');
                selectedRow.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
            }}

            // Draw TP/SL Dashed Lines
            drawTradeLines(trade);

            // Zoom Chart to trade window (start 30 bars before, end 30 bars after)
            const zoomStart = trade.open_ts - (60 * 20);
            const zoomEnd = trade.close_ts + (60 * 25);
            chart.timeScale().setVisibleRange({{ from: zoomStart, to: zoomEnd }});

            // Update Info label
            const info = document.getElementById('inspected-info');
            const pnlStr = (trade.net_pnl > 0 ? '+' : '') + '$' + trade.net_pnl.toFixed(2);
            info.innerHTML = `Inspecting <strong>Trade #${{trade.id}} (${{trade.side}})</strong>: Entry @ <strong>${{trade.open_price}}</strong> | SL: <strong style="color:#f85149;">${{trade.sl}}</strong> | TP: <strong style="color:#3fb950;">${{trade.tp}}</strong> | Result: <strong>${{pnlStr}}</strong> (${{trade.exit_reason}})`;
        }}

        function resetZoom() {{
            clearTradeLines();
            chart.timeScale().fitContent();
            document.getElementById('inspected-info').textContent = 'Zoom with mouse wheel, drag to pan';
            document.querySelectorAll('.clickable-row').forEach(r => r.classList.remove('selected-row'));
            select.value = '';
        }}

        // Responsive Resize
        window.addEventListener('resize', () => {{
            chart.applyOptions({{ width: chartElement.clientWidth }});
            eqChart.applyOptions({{ width: eqElement.clientWidth }});
        }});

        // Fit content on initial load
        chart.timeScale().fitContent();
        eqChart.timeScale().fitContent();
    </script>
</body>
</html>
"""

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        f.write(html_content)

    print(f"[Visualizer] SUCCESS! Advanced Interactive HTML generated at: {out_path.resolve()}")
    return str(out_path.resolve())


if __name__ == "__main__":
    generate_visual_html()
