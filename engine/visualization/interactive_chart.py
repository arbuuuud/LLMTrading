"""
Ultra-Robust Standalone Pure HTML5 Canvas Institutional Visualizer.
Features:
- "Show All Trades" toggle: Renders ALL 135 trade trajectory diagonal lines simultaneously
  (Green dashed for WIN, Red dashed for LOSS) across the entire chart!
- Exact entry dot (Blue) and exit dot (Green/Red) directly at price coordinates.
- Hover tooltip showing trade details when hovering over any trade line or entry/exit dot.
- Interactive toggle buttons: [Show All Trades (135)] / [Selected Trade Only] / [Wins Only] / [Losses Only].
- Smooth drag to pan and mouse wheel to zoom across the entire 7,182 M1 bars.
- 100% Native HTML5 Canvas (Zero external libraries, instant local rendering).
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


def generate_all_trades_visual(output_file: str = "reports/backtest_visual.html"):
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
    <title>LLMTrading Visualizer (All Trades Multi-Trajectory)</title>
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
            gap: 10px;
            flex-wrap: wrap;
        }}
        .btn {{
            background: #21262d;
            color: #c9d1d9;
            border: 1px solid #30363d;
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 0.82rem;
            cursor: pointer;
            font-weight: 500;
            transition: all 0.15s;
        }}
        .btn:hover {{ border-color: #58a6ff; background: #30363d; }}
        .btn.active {{
            background: #1f6feb;
            color: #fff;
            border-color: #58a6ff;
            font-weight: 600;
        }}
        select {{
            background: #21262d;
            color: #c9d1d9;
            border: 1px solid #30363d;
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 0.82rem;
            cursor: pointer;
        }}
        
        .chart-box {{
            margin: 16px 24px 0 24px;
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            overflow: hidden;
            position: relative;
        }}
        .chart-header {{
            padding: 10px 16px;
            font-size: 0.85rem;
            font-weight: 600;
            color: #8b949e;
            border-bottom: 1px solid #21262d;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        canvas {{ display: block; width: 100%; cursor: crosshair; }}
        
        #tooltip {{
            position: absolute;
            display: none;
            background: rgba(22, 27, 34, 0.95);
            border: 1px solid #58a6ff;
            color: #e6edf3;
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 0.8rem;
            pointer-events: none;
            z-index: 100;
            box-shadow: 0 4px 12px rgba(0,0,0,0.5);
            line-height: 1.4;
        }}

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
        <h1>LLMTrading Visualizer <span class="badge">Multi-Trajectory View</span></h1>
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
        <span style="font-size:0.82rem; font-weight:600; color:#8b949e;">DISPLAY MODE:</span>
        <button id="btn-all" class="btn active" onclick="setDisplayMode('all')">✨ Show ALL {len(trade_list)} Trades</button>
        <button id="btn-wins" class="btn" onclick="setDisplayMode('wins')">🟢 Winners Only</button>
        <button id="btn-losses" class="btn" onclick="setDisplayMode('losses')">🔴 Losers Only</button>
        <button id="btn-single" class="btn" onclick="setDisplayMode('single')">🎯 Focused Trade</button>

        <select id="trade-select" onchange="onSelectTradeDropdown(this.value)">
            <option value="">-- Jump to Specific Trade --</option>
        </select>
        
        <button class="btn" onclick="zoomIn()">Zoom In (+)</button>
        <button class="btn" onclick="zoomOut()">Zoom Out (-)</button>
        <button class="btn" onclick="fitAllChart()">Fit Entire Dataset</button>

        <div style="margin-left:auto; display:flex; gap:14px; font-size:0.82rem; align-items:center;">
            <span><strong style="color:#3fb950; font-size:1.1rem;">- - - ↗</strong> Win Trade</span>
            <span><strong style="color:#f85149; font-size:1.1rem;">- - - ↘</strong> Loss Trade</span>
            <span><strong style="color:#58a6ff;">●</strong> Entry</span>
        </div>
    </div>

    <div class="chart-box">
        <div class="chart-header">
            <span id="inspect-banner">Mode: Showing ALL {len(trade_list)} Trade Trajectories simultaneously</span>
            <span style="font-size:0.75rem; color:#8b949e;">Scroll to zoom • Drag to pan • Hover over lines for details</span>
        </div>
        <canvas id="candle-canvas" height="560"></canvas>
        <div id="tooltip"></div>
    </div>

    <div class="table-box">
        <div class="table-header">
            <span>All {len(trade_list)} Executed Trades (Click any row to jump & highlight)</span>
            <span style="font-size:0.75rem; color:#8b949e;">Chronological Ledger</span>
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
        const tooltip = document.getElementById('tooltip');
        
        let startIdx = 0;
        let viewCount = 180; // Show a generous view by default
        let displayMode = 'all'; // 'all', 'wins', 'losses', 'single'
        let focusedTradeId = null;

        // Rendered line hitboxes for hover inspection
        let tradeHitboxes = [];

        function resizeCanvas() {{
            canvas.width = canvas.parentElement.clientWidth;
            drawChart();
        }}
        window.addEventListener('resize', resizeCanvas);

        function drawChart() {{
            const W = canvas.width;
            const H = canvas.height;
            ctx.clearRect(0, 0, W, H);
            tradeHitboxes = [];

            const endIdx = Math.min(candles.length, startIdx + viewCount);
            const slice = candles.slice(startIdx, endIdx);
            if (slice.length === 0) return;

            let minP = Infinity;
            let maxP = -Infinity;
            for (let c of slice) {{
                if (c.l < minP) minP = c.l;
                if (c.h > maxP) maxP = c.h;
            }}

            // Include visible trades in price bounds
            const visibleStartTs = slice[0].ts;
            const visibleEndTs = slice[slice.length - 1].ts;

            trades.forEach(tr => {{
                const inView = !(tr.close_ts < visibleStartTs || tr.open_ts > visibleEndTs);
                if (inView) {{
                    minP = Math.min(minP, tr.entry, tr.exit);
                    maxP = Math.max(maxP, tr.entry, tr.exit);
                    if (tr.sl) minP = Math.min(minP, tr.sl);
                    if (tr.tp) maxP = Math.max(maxP, tr.tp);
                }}
            }});

            const pad = (maxP - minP) * 0.10 || 1.0;
            minP -= pad;
            maxP += pad;

            const padLeft = 10;
            const padRight = 75;
            const padTop = 30;
            const padBottom = 30;
            const chartW = W - padLeft - padRight;
            const chartH = H - padTop - padBottom;

            function getY(p) {{
                return padTop + (1.0 - (p - minP) / (maxP - minP)) * chartH;
            }}

            const barW = Math.max(1.5, (chartW / slice.length) * 0.7);
            const stepW = chartW / slice.length;

            // 1. Draw Grid Lines & Right Price Axis
            ctx.strokeStyle = '#21262d';
            ctx.lineWidth = 1;
            ctx.fillStyle = '#8b949e';
            ctx.font = '11px -apple-system, sans-serif';
            ctx.textAlign = 'left';

            const priceStep = (maxP - minP) / 7;
            for (let i = 0; i <= 7; i++) {{
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

                // Timestamp label
                const labelFreq = Math.max(10, Math.floor(viewCount / 6));
                if (i % labelFreq === 0) {{
                    ctx.fillStyle = '#6e7681';
                    ctx.textAlign = 'center';
                    ctx.fillText(c.t, x, H - 10);
                }}
            }});

            // 3. Draw Trade Trajectories (DIAGONAL DASHED LINES)
            trades.forEach(tr => {{
                // Filter by mode
                if (displayMode === 'wins' && !tr.win) return;
                if (displayMode === 'losses' && tr.win) return;
                if (displayMode === 'single' && tr.id !== focusedTradeId) return;

                // Check visibility
                if (tr.close_ts < visibleStartTs || tr.open_ts > visibleEndTs) return;

                const openIdx = tsToIdx.get(tr.open_ts);
                const closeIdx = tsToIdx.get(tr.close_ts);
                if (openIdx === undefined) return;

                const x1 = padLeft + (openIdx - startIdx + 0.5) * stepW;
                const x2 = closeIdx !== undefined ? (padLeft + (closeIdx - startIdx + 0.5) * stepW) : (W - padRight);

                const y1 = getY(tr.entry);
                const y2 = getY(tr.exit);

                const isFocused = (tr.id === focusedTradeId);
                const lineColor = tr.win ? '#3fb950' : '#f85149';

                // Save hitbox for hover detection
                tradeHitboxes.push({{
                    trade: tr,
                    x1, y1, x2, y2
                }});

                // --- Draw Diagonal Dashed Trajectory Line ---
                ctx.strokeStyle = lineColor;
                ctx.setLineDash(isFocused ? [6, 4] : [4, 4]);
                ctx.lineWidth = isFocused ? 3.5 : 2;
                ctx.beginPath();
                ctx.moveTo(x1, y1);
                ctx.lineTo(x2, y2);
                ctx.stroke();
                ctx.setLineDash([]); // Reset

                // --- Draw Entry Dot (Blue) at Exact Price ---
                ctx.fillStyle = '#58a6ff';
                ctx.beginPath();
                ctx.arc(x1, y1, isFocused ? 5.5 : 3.5, 0, Math.PI * 2);
                ctx.fill();

                // --- Draw Exit Dot (Green or Red) at Exact Price ---
                ctx.fillStyle = lineColor;
                ctx.beginPath();
                ctx.arc(x2, y2, isFocused ? 6.5 : 4, 0, Math.PI * 2);
                ctx.fill();

                // Draw Label Badge if focused or few bars
                if (isFocused || viewCount <= 90) {{
                    ctx.font = isFocused ? 'bold 11px -apple-system, sans-serif' : '10px -apple-system, sans-serif';
                    ctx.fillStyle = '#58a6ff';
                    ctx.textAlign = 'center';
                    ctx.fillText(`#${{tr.id}} ${{tr.side}}`, x1, y1 - 8);

                    ctx.fillStyle = lineColor;
                    const pnlText = (tr.win ? '+' : '') + '$' + tr.pnl.toFixed(0);
                    ctx.fillText(pnlText, x2, y2 + (tr.win ? -8 : 14));
                }}
            }});
        }}

        // Hover Tooltip Detection
        canvas.addEventListener('mousemove', e => {{
            const rect = canvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;

            // Find closest trade line
            let hovered = null;
            let minDist = 12; // 12px threshold

            for (let hb of tradeHitboxes) {{
                const d = distToSegment(mouseX, mouseY, hb.x1, hb.y1, hb.x2, hb.y2);
                if (d < minDist) {{
                    minDist = d;
                    hovered = hb.trade;
                }}
            }}

            if (hovered) {{
                tooltip.style.display = 'block';
                tooltip.style.left = (e.clientX + 15) + 'px';
                tooltip.style.top = (e.clientY - 20) + 'px';
                const pnlCol = hovered.win ? '#3fb950' : '#f85149';
                const pnlSign = hovered.win ? '+' : '';
                tooltip.innerHTML = `
                    <div style="font-weight:700; color:#fff; margin-bottom:2px;">Trade #${{hovered.id}} (${{hovered.side}})</div>
                    <div>Entry: <strong>$${{hovered.entry.toFixed(2)}}</strong> @ ${{hovered.open_t}}</div>
                    <div>Exit: <strong>$${{hovered.exit.toFixed(2)}}</strong> @ ${{hovered.close_t}}</div>
                    <div>SL: <span style="color:#f85149;">$${{hovered.sl ? hovered.sl.toFixed(2) : '-'}}</span> | TP: <span style="color:#3fb950;">$${{hovered.tp ? hovered.tp.toFixed(2) : '-'}}</span></div>
                    <div>Net PnL: <strong style="color:${{pnlCol}};">${{pnlSign}}$${{hovered.pnl.toFixed(2)}}</strong> (${{hovered.reason}})</div>
                    <div>Duration: ${{hovered.dur}} min</div>
                `;
            }} else {{
                tooltip.style.display = 'none';
            }}
        }});

        canvas.addEventListener('mouseleave', () => {{
            tooltip.style.display = 'none';
        }});

        function distToSegment(px, py, x1, y1, x2, y2) {{
            const l2 = (x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1);
            if (l2 === 0) return Math.hypot(px - x1, py - y1);
            let t = ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2;
            t = Math.max(0, Math.min(1, t));
            return Math.hypot(px - (x1 + t * (x2 - x1)), py - (y1 + t * (y2 - y1)));
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
            const delta = zoomIn ? -Math.max(5, Math.floor(viewCount * 0.15)) : Math.max(5, Math.floor(viewCount * 0.15));
            const newCount = Math.max(25, Math.min(candles.length, viewCount + delta));
            startIdx = Math.max(0, Math.min(candles.length - newCount, startIdx + Math.round((viewCount - newCount) / 2)));
            viewCount = newCount;
            drawChart();
        }}, {{ passive: false }});

        // Mode Switching
        function setDisplayMode(mode) {{
            displayMode = mode;
            document.querySelectorAll('#toolbar .btn').forEach(b => b.classList.remove('active'));
            if (mode === 'all') document.getElementById('btn-all').classList.add('active');
            if (mode === 'wins') document.getElementById('btn-wins').classList.add('active');
            if (mode === 'losses') document.getElementById('btn-losses').classList.add('active');
            if (mode === 'single') document.getElementById('btn-single').classList.add('active');

            const countMap = {{
                'all': 'ALL 135 Trades',
                'wins': 'Winners Only (56 Trades)',
                'losses': 'Losers Only (79 Trades)',
                'single': `Focused Trade #${{focusedTradeId || 1}}`
            }};
            document.getElementById('inspect-banner').textContent = `Mode: Showing ${{countMap[mode]}}`;
            drawChart();
        }}

        function zoomIn() {{
            viewCount = Math.max(25, Math.floor(viewCount * 0.7));
            drawChart();
        }}
        function zoomOut() {{
            viewCount = Math.min(candles.length, Math.floor(viewCount * 1.4));
            drawChart();
        }}
        function fitAllChart() {{
            startIdx = 0;
            viewCount = candles.length;
            drawChart();
        }}

        // Table & Dropdown Population
        const select = document.getElementById('trade-select');
        const tbody = document.getElementById('trades-tbody');

        trades.forEach(t => {{
            const opt = document.createElement('option');
            opt.value = t.id;
            const pnlStr = (t.win ? '+' : '') + '$' + t.pnl.toFixed(2);
            opt.textContent = `Trade #${{t.id}} [${{t.side}}] ${{t.open_t}} -> ${{t.entry}} | PnL: ${{pnlStr}} (${{t.reason}})`;
            select.appendChild(opt);

            const tr = document.createElement('tr');
            tr.id = 'row-' + t.id;
            tr.className = 'clickable-row';
            tr.onclick = () => jumpToTrade(t.id);
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

        function onSelectTradeDropdown(val) {{
            if (val) jumpToTrade(parseInt(val));
        }}

        function jumpToTrade(tradeId) {{
            const tr = trades.find(t => t.id === tradeId);
            if (!tr) return;

            focusedTradeId = tradeId;
            select.value = tradeId;

            // Highlight table row
            document.querySelectorAll('.clickable-row').forEach(r => r.classList.remove('selected-row'));
            const r = document.getElementById('row-' + tradeId);
            if (r) {{
                r.classList.add('selected-row');
                r.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
            }}

            // Center chart on this trade
            const openIdx = tsToIdx.get(tr.open_ts) || 0;
            const closeIdx = tsToIdx.get(tr.close_ts) || openIdx;
            const dur = Math.max(1, closeIdx - openIdx);

            viewCount = Math.max(35, dur + 25);
            startIdx = Math.max(0, openIdx - 10);

            const pnlStr = (tr.win ? '+' : '') + '$' + tr.pnl.toFixed(2);
            document.getElementById('inspect-banner').innerHTML = 
                `Highlighted <strong>Trade #${{tr.id}} (${{tr.side}})</strong>: Entry <strong>$${{tr.entry}}</strong> -> Exit <strong>$${{tr.exit}}</strong> | PnL: <strong style="color:${{tr.win ? '#3fb950' : '#f85149'}};">${{pnlStr}}</strong> (${{tr.reason}})`;

            drawChart();
        }}

        // Initial setup: Show all trades mode
        resizeCanvas();
        setDisplayMode('all');
    </script>
</body>
</html>
"""

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        f.write(html)

    print(f"[Visualizer] SUCCESS! Generated Multi-Trajectory Visualizer at: {out_path.resolve()}")
    return str(out_path.resolve())


if __name__ == "__main__":
    generate_all_trades_visual()
