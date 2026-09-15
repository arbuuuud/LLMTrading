"""
Ultra-Robust Standalone Pure SVG/Canvas Institutional Visualizer.
Features:
- EXACT DIAGONAL DASHED LINE from Entry coordinate (candle entry time & price)
  directly to Exit coordinate (candle exit time & exit price: TP or SL)!
- Green diagonal dashed line for Profitable trades (Take Profit).
- Red diagonal dashed line for Loss trades (Stop Loss / Cut).
- Exact dot and price badges at start of line (Entry) and end of line (Exit).
- Interactive navigation: Next/Prev buttons, Dropdown, Clickable table row.
- 100% Native HTML5 Canvas (Zero CDN, instant rendering).
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


def generate_standalone_visual(output_file: str = "reports/backtest_visual.html"):
    parquet_path = "data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet"
    print(f"[Visualizer] Reading {parquet_path}...")
    df = pl.read_parquet(parquet_path)

    engine = EventEngine(
        config=AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0),
        commission_model=CommissionModel(7.0),
        slippage_model=FixedSlippageModel(0.02)
    )
    strategy = XAUUSDTrendPullbackScalper(risk_reward_ratio=2.0, max_bars_hold=25)
    res = engine.run_bars(df, strategy)
    perf = res["performance"]
    mc = res["monte_carlo"]
    trades = res["trades"]
    equity_curve = res["equity_curve"]

    buys_count = sum(1 for t in trades if t.direction == OrderDirection.BUY)
    sells_count = sum(1 for t in trades if t.direction == OrderDirection.SELL)

    candles = []
    for row in df.iter_rows(named=True):
        dt = row["timestamp"]
        candles.append({
            "t": dt.strftime("%m-%d %H:%M"),
            "ts": int(dt.timestamp()),
            "o": round(row["open"], 2),
            "h": round(row["high"], 2),
            "l": round(row["low"], 2),
            "c": round(row["close"], 2)
        })

    trade_list = []
    for i, t in enumerate(trades):
        is_buy = (t.direction == OrderDirection.BUY)
        is_win = (t.net_pnl > 0)
        trade_list.append({
            "id": i + 1,
            "side": "BUY" if is_buy else "SELL",
            "open_t": t.open_time.strftime("%m-%d %H:%M"),
            "close_t": t.close_time.strftime("%m-%d %H:%M"),
            "open_ts": int(t.open_time.timestamp()),
            "close_ts": int(t.close_time.timestamp()),
            "entry": round(t.open_price, 2),
            "exit": round(t.close_price, 2),
            "sl": round(t.stop_loss, 2) if t.stop_loss else None,
            "tp": round(t.take_profit, 2) if t.take_profit else None,
            "pnl": round(t.net_pnl, 2),
            "win": is_win,
            "reason": t.exit_reason.value,
            "dur": round(t.duration_seconds / 60.0, 1)
        })

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LLMTrading Visualizer (Diagonal Trajectory)</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: #0d1117;
            color: #c9d1d9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            padding-bottom: 40px;
        }}
        header {{
            background: #161b22;
            padding: 14px 24px;
            border-bottom: 1px solid #30363d;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        h1 {{ font-size: 1.2rem; font-weight: 600; display: flex; align-items: center; gap: 8px; color: #fff; }}
        .badge {{ background: #238636; color: #fff; font-size: 0.72rem; padding: 3px 8px; border-radius: 4px; }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            gap: 10px;
            padding: 12px 24px;
            background: #0d1117;
            border-bottom: 1px solid #21262d;
        }}
        .stat-card {{
            background: #161b22;
            border: 1px solid #30363d;
            padding: 10px 12px;
            border-radius: 6px;
        }}
        .stat-label {{ font-size: 0.7rem; color: #8b949e; text-transform: uppercase; margin-bottom: 2px; }}
        .stat-value {{ font-size: 1.15rem; font-weight: 700; }}
        .val-green {{ color: #3fb950; }}
        .val-red {{ color: #f85149; }}
        .val-blue {{ color: #58a6ff; }}

        #toolbar {{
            padding: 10px 24px;
            background: #161b22;
            border-bottom: 1px solid #30363d;
            display: flex;
            align-items: center;
            gap: 12px;
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
        select:focus, button:hover {{ border-color: #58a6ff; background: #30363d; }}
        
        .chart-box {{
            margin: 16px 24px 0 24px;
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            overflow: hidden;
        }}
        .chart-header {{
            padding: 10px 16px;
            font-size: 0.85rem;
            font-weight: 600;
            color: #8b949e;
            border-bottom: 1px solid #21262d;
            display: flex;
            justify-content: space-between;
        }}
        canvas {{ display: block; width: 100%; cursor: crosshair; }}
        
        .table-box {{
            margin: 16px 24px;
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            overflow: hidden;
        }}
        .table-header {{
            padding: 10px 16px;
            font-size: 0.88rem;
            font-weight: 600;
            color: #fff;
            border-bottom: 1px solid #30363d;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .table-scroll {{
            max-height: 360px;
            overflow-y: auto;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.82rem;
        }}
        th, td {{
            padding: 8px 12px;
            text-align: left;
            border-bottom: 1px solid #21262d;
        }}
        th {{ background: #21262d; color: #8b949e; position: sticky; top: 0; z-index: 2; font-weight: 600; }}
        tr.clickable-row {{ cursor: pointer; transition: background 0.15s; }}
        tr.clickable-row:hover {{ background: #1f2937; }}
        tr.selected-row {{ background: #263342 !important; border-left: 4px solid #58a6ff; }}
    </style>
</head>
<body>
    <header>
        <h1>LLMTrading Visualizer <span class="badge">Trade Trajectory View</span></h1>
        <div style="font-size:0.85rem; color:#8b949e;">
            Asset: <strong style="color:#fff;">XAUUSD M1</strong> | Bars: <strong>{len(candles):,}</strong> | Trades: <strong>{len(trade_list)}</strong>
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

    <div id="toolbar">
        <label style="font-size:0.85rem; font-weight:600;">🔍 Select Trade:</label>
        <select id="trade-select" onchange="inspectTrade(this.value)">
            <option value="">-- Select a Trade to Zoom & View Diagonal Trajectory --</option>
        </select>
        
        <button onclick="prevTrade()">◀ Prev Trade</button>
        <button onclick="nextTrade()">Next Trade ▶</button>
        <button onclick="resetView()">Full Chart</button>

        <div style="margin-left:auto; display:flex; gap:16px; font-size:0.82rem; align-items:center;">
            <span><strong style="color:#3fb950; font-size:1.1rem;">- - - ↗</strong> Win Trade Line</span>
            <span><strong style="color:#f85149; font-size:1.1rem;">- - - ↘</strong> Loss Trade Line</span>
        </div>
    </div>

    <div class="chart-box">
        <div class="chart-header">
            <span id="inspect-banner" style="color:#58a6ff; font-weight:600;">Trade Trajectory View</span>
            <span style="font-size:0.75rem; color:#8b949e;">Drag mouse to pan • Scroll mouse to zoom</span>
        </div>
        <canvas id="candle-canvas" height="540"></canvas>
    </div>

    <div class="table-box">
        <div class="table-header">
            <span>All {len(trade_list)} Executed Trades (Click any row to jump directly)</span>
            <span style="font-size:0.75rem; color:#8b949e;">Sorted chronologically</span>
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
                <tbody id="trades-tbody"></tbody>
            </table>
        </div>
    </div>

    <script>
        const candles = {json.dumps(candles)};
        const trades = {json.dumps(trade_list)};
        
        const tsToIdx = new Map();
        candles.forEach((c, idx) => tsToIdx.set(c.ts, idx));

        const canvas = document.getElementById('candle-canvas');
        const ctx = canvas.getContext('2d');
        
        let startIdx = 0;
        let viewCount = 80;
        let selectedTradeId = 1;

        function resizeCanvas() {{
            canvas.width = canvas.parentElement.clientWidth;
            drawChart();
        }}
        window.addEventListener('resize', resizeCanvas);

        function drawChart() {{
            const W = canvas.width;
            const H = canvas.height;
            ctx.clearRect(0, 0, W, H);

            const endIdx = Math.min(candles.length, startIdx + viewCount);
            const slice = candles.slice(startIdx, endIdx);
            if (slice.length === 0) return;

            // Determine min/max price in view
            let minP = Infinity;
            let maxP = -Infinity;
            for (let c of slice) {{
                if (c.l < minP) minP = c.l;
                if (c.h > maxP) maxP = c.h;
            }}

            // Expand bounds if trade is selected
            if (selectedTradeId !== null) {{
                const tr = trades.find(t => t.id === selectedTradeId);
                if (tr) {{
                    minP = Math.min(minP, tr.entry, tr.exit);
                    maxP = Math.max(maxP, tr.entry, tr.exit);
                    if (tr.sl) {{ minP = Math.min(minP, tr.sl); maxP = Math.max(maxP, tr.sl); }}
                    if (tr.tp) {{ minP = Math.min(minP, tr.tp); maxP = Math.max(maxP, tr.tp); }}
                }}
            }}

            const pad = (maxP - minP) * 0.12 || 1.0;
            minP -= pad;
            maxP += pad;

            const padLeft = 10;
            const padRight = 75;
            const padTop = 35;
            const padBottom = 30;
            const chartW = W - padLeft - padRight;
            const chartH = H - padTop - padBottom;

            function getY(p) {{
                return padTop + (1.0 - (p - minP) / (maxP - minP)) * chartH;
            }}

            const barW = Math.max(2, (chartW / slice.length) * 0.7);
            const stepW = chartW / slice.length;

            // 1. Draw Grid Lines & Right Price Axis
            ctx.strokeStyle = '#21262d';
            ctx.lineWidth = 1;
            ctx.fillStyle = '#8b949e';
            ctx.font = '11px -apple-system, sans-serif';
            ctx.textAlign = 'left';

            const priceStep = (maxP - minP) / 6;
            for (let i = 0; i <= 6; i++) {{
                const p = minP + i * priceStep;
                const y = getY(p);
                ctx.beginPath();
                ctx.moveTo(padLeft, y);
                ctx.lineTo(W - padRight, y);
                ctx.stroke();
                ctx.fillText('$' + p.toFixed(2), W - padRight + 6, y + 4);
            }}

            // 2. Draw Candlesticks
            slice.forEach((c, i) => {{
                const x = padLeft + (i + 0.5) * stepW;
                const yO = getY(c.o);
                const yC = getY(c.c);
                const yH = getY(c.h);
                const yL = getY(c.l);

                const isGreen = (c.c >= c.o);
                const col = isGreen ? '#3fb950' : '#f85149';

                // Wick
                ctx.strokeStyle = col;
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(x, yH);
                ctx.lineTo(x, yL);
                ctx.stroke();

                // Body
                ctx.fillStyle = col;
                const top = Math.min(yO, yC);
                const bodyH = Math.max(2, Math.abs(yC - yO));
                ctx.fillRect(x - barW / 2, top, barW, bodyH);

                // Timestamp label every 15 bars
                if (i % 15 === 0) {{
                    ctx.fillStyle = '#6e7681';
                    ctx.textAlign = 'center';
                    ctx.fillText(c.t, x, H - 10);
                }}
            }});

            // 3. Draw Trades Trajectory (DIAGONAL DASHED LINES from Entry -> Exit)
            const visibleStartTs = slice[0].ts;
            const visibleEndTs = slice[slice.length - 1].ts;

            trades.forEach(tr => {{
                if (tr.close_ts < visibleStartTs || tr.open_ts > visibleEndTs) return;

                const openIdx = tsToIdx.get(tr.open_ts);
                const closeIdx = tsToIdx.get(tr.close_ts);
                if (openIdx === undefined) return;

                const x1 = padLeft + (openIdx - startIdx + 0.5) * stepW;
                const x2 = closeIdx !== undefined ? (padLeft + (closeIdx - startIdx + 0.5) * stepW) : (W - padRight);

                const y1 = getY(tr.entry);
                const y2 = getY(tr.exit);

                const isSelected = (tr.id === selectedTradeId);
                const lineColor = tr.win ? '#3fb950' : '#f85149';

                // Only draw if selected or reasonably zoomed in
                if (isSelected || slice.length <= 150) {{
                    // === DIAGONAL DASHED LINE FROM ENTRY DIRECTLY TO EXIT (TP/SL) ===
                    ctx.strokeStyle = lineColor;
                    ctx.setLineDash([5, 4]); // DASHED STYLE
                    ctx.lineWidth = isSelected ? 3 : 1.5;
                    ctx.beginPath();
                    ctx.moveTo(x1, y1);
                    ctx.lineTo(x2, y2);
                    ctx.stroke();
                    ctx.setLineDash([]); // Reset dash

                    // === ENTRY CIRCLE DOT AT EXACT ENTRY PRICE ===
                    ctx.fillStyle = '#58a6ff';
                    ctx.beginPath();
                    ctx.arc(x1, y1, isSelected ? 5 : 3.5, 0, Math.PI * 2);
                    ctx.fill();

                    // === EXIT CIRCLE DOT AT EXACT EXIT PRICE (TP / SL) ===
                    ctx.fillStyle = lineColor;
                    ctx.beginPath();
                    ctx.arc(x2, y2, isSelected ? 6 : 4, 0, Math.PI * 2);
                    ctx.fill();

                    // === TEXT LABELS (Badges) ===
                    if (isSelected) {{
                        ctx.font = 'bold 11px -apple-system, sans-serif';
                        
                        // Entry Badge
                        ctx.fillStyle = '#58a6ff';
                        ctx.textAlign = (x1 < x2) ? 'right' : 'center';
                        ctx.fillText(`Entry #${{tr.id}} (${{tr.side}}) $${{tr.entry.toFixed(2)}}`, x1 - 8, y1 - 6);

                        // Exit Badge
                        ctx.fillStyle = lineColor;
                        ctx.textAlign = 'left';
                        const pnlStr = (tr.win ? '+' : '') + '$' + tr.pnl.toFixed(2);
                        ctx.fillText(`Exit: $${{tr.exit.toFixed(2)}} [${{pnlStr}}] (${{tr.reason}})`, x2 + 8, y2 + 4);
                    }}
                }}
            }});
        }}

        // Interactivity: Drag to Pan
        let isDragging = false;
        let dragStartX = 0;
        let dragStartIdx = 0;

        canvas.addEventListener('mousedown', e => {{
            isDragging = true;
            dragStartX = e.clientX;
            dragStartIdx = startIdx;
        }});
        window.addEventListener('mouseup', () => isDragging = false);
        window.addEventListener('mousemove', e => {{
            if (!isDragging) return;
            const dx = e.clientX - dragStartX;
            const deltaBars = Math.round((dx / canvas.width) * viewCount);
            startIdx = Math.max(0, Math.min(candles.length - viewCount, dragStartIdx - deltaBars));
            drawChart();
        }});

        // Interactivity: Wheel to Zoom
        canvas.addEventListener('wheel', e => {{
            e.preventDefault();
            const zoomIn = (e.deltaY < 0);
            const delta = zoomIn ? -15 : 15;
            const newCount = Math.max(20, Math.min(800, viewCount + delta));
            startIdx = Math.max(0, Math.min(candles.length - newCount, startIdx + Math.round((viewCount - newCount) / 2)));
            viewCount = newCount;
            drawChart();
        }}, {{ passive: false }});

        // Trade Selection & Inspection
        const select = document.getElementById('trade-select');
        const tbody = document.getElementById('trades-tbody');

        trades.forEach(t => {{
            // Add option
            const opt = document.createElement('option');
            opt.value = t.id;
            const pnlStr = (t.win ? '+' : '') + '$' + t.pnl.toFixed(2);
            opt.textContent = `Trade #${{t.id}} [${{t.side}}] ${{t.open_t}} -> Entry: ${{t.entry}} | Exit: ${{t.exit}} | PnL: ${{pnlStr}} (${{t.reason}})`;
            select.appendChild(opt);

            // Add table row
            const tr = document.createElement('tr');
            tr.id = 'row-' + t.id;
            tr.className = 'clickable-row';
            tr.onclick = () => inspectTrade(t.id);
            tr.innerHTML = `
                <td>${{t.id}}</td>
                <td style="font-weight:700; color:${{t.side === 'BUY' ? '#3fb950' : '#f85149'}};">${{t.side}}</td>
                <td>${{t.open_t}}</td>
                <td>${{t.close_t}}</td>
                <td>$${{t.entry.toFixed(2)}}</td>
                <td>$${{t.exit.toFixed(2)}}</td>
                <td style="color:#f85149; font-weight:600;">$${{t.sl ? t.sl.toFixed(2) : '-'}}</td>
                <td style="color:#3fb950; font-weight:600;">$${{t.tp ? t.tp.toFixed(2) : '-'}}</td>
                <td style="font-weight:700; color:${{t.win ? '#3fb950' : '#f85149'}};">${{pnlStr}}</td>
                <td>${{t.reason}}</td>
                <td>${{t.dur}}m</td>
            `;
            tbody.appendChild(tr);
        }});

        function inspectTrade(tradeId) {{
            if (!tradeId) return;
            const id = parseInt(tradeId);
            const tr = trades.find(t => t.id === id);
            if (!tr) return;

            selectedTradeId = id;
            select.value = id;

            // Highlight table row
            document.querySelectorAll('.clickable-row').forEach(r => r.classList.remove('selected-row'));
            const r = document.getElementById('row-' + id);
            if (r) {{
                r.classList.add('selected-row');
                r.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
            }}

            // Zoom view directly onto trade trajectory
            const openIdx = tsToIdx.get(tr.open_ts) || 0;
            const closeIdx = tsToIdx.get(tr.close_ts) || openIdx;
            const durBars = Math.max(1, closeIdx - openIdx);

            viewCount = Math.max(30, durBars + 20);
            startIdx = Math.max(0, openIdx - 8);

            const pnlStr = (tr.win ? '+' : '') + '$' + tr.pnl.toFixed(2);
            document.getElementById('inspect-banner').innerHTML = 
                `Inspecting <strong>Trade #${{tr.id}} (${{tr.side}})</strong>: Entry <strong>$${{tr.entry}}</strong> -> Exit <strong>$${{tr.exit}}</strong> | PnL: <strong style="color:${{tr.win ? '#3fb950' : '#f85149'}};">${{pnlStr}}</strong> (${{tr.reason}}) | Duration: ${{tr.dur}} min`;

            drawChart();
        }}

        function prevTrade() {{
            const cur = selectedTradeId || 2;
            if (cur > 1) inspectTrade(cur - 1);
        }}
        function nextTrade() {{
            const cur = selectedTradeId || 0;
            if (cur < trades.length) inspectTrade(cur + 1);
        }}

        function resetView() {{
            selectedTradeId = null;
            startIdx = 0;
            viewCount = 100;
            select.value = '';
            document.getElementById('inspect-banner').textContent = 'Full chart overview';
            document.querySelectorAll('.clickable-row').forEach(r => r.classList.remove('selected-row'));
            drawChart();
        }}

        // Initialize view focused on Trade #1
        resizeCanvas();
        inspectTrade(1);
    </script>
</body>
</html>
"""

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        f.write(html)

    print(f"[Visualizer] SUCCESS! Generated at: {out_path.resolve()}")
    return str(out_path.resolve())


if __name__ == "__main__":
    generate_standalone_visual()
