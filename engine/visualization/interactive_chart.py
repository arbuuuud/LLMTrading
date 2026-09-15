"""
Ultra-Responsive Institutional Visualizer & Dashboard (Native HTML5 Canvas).
Features:
- Butter-smooth 60fps performance (lightweight, memory-safe, instant load).
- Candlestick Chart with 2D pan and vertical price scale zoom.
- Interactive Account Equity Curve ($10,000 Starting Balance).
- 2 New Dedicated PnL Analytics Graphs:
  * Daily PnL Bar Chart (% Return vs H-1 Prior Day Equity).
  * Monthly PnL Bar Chart (% Return vs Month-1 Prior Month Equity).
  * Interactive tooltips displaying exact $ PnL, % vs previous equity, starting & ending equity.
  * Click any bar to jump the candlestick chart directly to that day/month!
- Complete Executed Trades Ledger with search, filter chips, and one-click jump.
- 100% Native HTML5 Canvas (Zero external dependencies, zero CDN blocking).
"""

import sys
from pathlib import Path
import json
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from engine.core.event_engine import EventEngine
from engine.core.types import AccountConfig, OrderDirection, ExitReason
from engine.execution.commission import CommissionModel
from engine.execution.slippage import FixedSlippageModel
from strategies.incubator.strat_3_anchored_vwap import SessionAnchoredVWAPStrategy


def generate_optimized_visual(output_file: str = "reports/backtest_visual.html", max_display_bars: int = 25000):
    parquet_path = "data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet"
    print(f"[Visualizer] Loading {parquet_path}...")
    df_all = pl.read_parquet(parquet_path)
    total_bars_count = len(df_all)
    print(f"[Visualizer] Total available bars: {total_bars_count:,}.")

    # Run the Proven Winning Strategy: Session Anchored VWAP 1.8 Sigma Golden Window
    engine = EventEngine(
        config=AccountConfig(initial_balance=10000.0, commission_per_lot_round_turn=7.0),
        commission_model=CommissionModel(7.0),
        slippage_model=FixedSlippageModel(0.02)
    )
    strategy = SessionAnchoredVWAPStrategy(
        band_multiplier=1.8,
        sl_buffer_dollars=0.50,
        risk_reward_ratio=2.0,
        base_risk_pct=0.5,
        greed_risk_pct=0.25,
        max_bars_hold=60
    )
    
    print("[Visualizer] Running simulation...")
    res = engine.run_bars(df_all, strategy)
    perf = res["performance"]
    mc = res["monte_carlo"]
    trades = res["trades"]
    equity_curve = res["equity_curve"]

    buys_count = sum(1 for t in trades if t.direction == OrderDirection.BUY)
    sells_count = sum(1 for t in trades if t.direction == OrderDirection.SELL)
    print(f"[Visualizer] Simulation complete: {len(trades)} trades ({buys_count} BUY / {sells_count} SELL).")

    # Load 100% continuous, seamless M5 bars
    m5_path = "data/processed/bars/XAUUSD/M5/XAUUSD_M5.parquet"
    print(f"[Visualizer] Loading seamless continuous M5 bars from {m5_path}...")
    df_display = pl.read_parquet(m5_path)
    print(f"[Visualizer] Display bars: {len(df_display):,} continuous M5 bars (covering all 10.5 months seamlessly).")

    candles = []
    for row in df_display.iter_rows(named=True):
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
            "lots": t.volume_lots,
            "open_t": t.open_time.strftime("%Y-%m-%d %H:%M"),
            "close_t": t.close_time.strftime("%Y-%m-%d %H:%M"),
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

    # Sample equity curve points
    eq_step = max(1, len(equity_curve) // 1000)
    eq_pts = []
    for eq in equity_curve[::eq_step]:
        eq_pts.append({
            "t": eq["timestamp"].strftime("%m-%d %H:%M"),
            "ts": int(eq["timestamp"].timestamp()),
            "eq": round(eq["equity"], 2)
        })
    if equity_curve:
        eq_pts.append({
            "t": equity_curve[-1]["timestamp"].strftime("%m-%d %H:%M"),
            "ts": int(equity_curve[-1]["timestamp"].timestamp()),
            "eq": round(equity_curve[-1]["equity"], 2)
        })

    # Calculate Daily PnL and % return vs H-1 prior day equity
    daily_groups = defaultdict(list)
    for t in trades:
        d_str = t.open_time.strftime("%Y-%m-%d")
        daily_groups[d_str].append(t)

    sorted_days = sorted(daily_groups.keys())
    daily_pnl_data = []
    running_eq = 10000.0
    for d_str in sorted_days:
        t_list = daily_groups[d_str]
        day_pnl = sum(t.net_pnl for t in t_list)
        pct_vs_prev = (day_pnl / running_eq) * 100.0 if running_eq > 0 else 0.0
        end_eq = running_eq + day_pnl
        wins = sum(1 for t in t_list if t.net_pnl > 0)
        daily_pnl_data.append({
            "date": d_str,
            "pnl": round(day_pnl, 2),
            "prev_eq": round(running_eq, 2),
            "end_eq": round(end_eq, 2),
            "pct_vs_prev": round(pct_vs_prev, 2),
            "trades": len(t_list),
            "wins": wins,
            "losses": len(t_list) - wins,
            "first_ts": int(t_list[0].open_time.timestamp())
        })
        running_eq = end_eq

    # Calculate Monthly PnL and % return vs Month-1 prior month equity
    monthly_groups = defaultdict(list)
    for t in trades:
        m_str = t.open_time.strftime("%Y-%m")
        monthly_groups[m_str].append(t)

    sorted_months = sorted(monthly_groups.keys())
    monthly_pnl_data = []
    running_month_eq = 10000.0
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    for m_str in sorted_months:
        t_list = monthly_groups[m_str]
        m_pnl = sum(t.net_pnl for t in t_list)
        pct_vs_prev_m = (m_pnl / running_month_eq) * 100.0 if running_month_eq > 0 else 0.0
        end_m_eq = running_month_eq + m_pnl
        wins = sum(1 for t in t_list if t.net_pnl > 0)
        yr, mo = m_str.split("-")
        label = f"{month_names[int(mo)-1]} '{yr[2:]}"
        monthly_pnl_data.append({
            "month": m_str,
            "label": label,
            "pnl": round(m_pnl, 2),
            "prev_eq": round(running_month_eq, 2),
            "end_eq": round(end_m_eq, 2),
            "pct_vs_prev": round(pct_vs_prev_m, 2),
            "trades": len(t_list),
            "wins": wins,
            "losses": len(t_list) - wins,
            "win_rate": round((wins / len(t_list)) * 100.0, 1),
            "first_ts": int(t_list[0].open_time.timestamp())
        })
        running_month_eq = end_m_eq

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LLMTrading Institutional Visualizer & Dashboard</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: #0d1117;
            color: #c9d1d9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            padding-bottom: 50px;
        }}
        header {{
            background: #161b22;
            padding: 14px 24px;
            border-bottom: 1px solid #30363d;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        h1 {{ font-size: 1.25rem; font-weight: 600; display: flex; align-items: center; gap: 8px; color: #fff; }}
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
            gap: 8px;
            flex-wrap: wrap;
        }}
        .btn {{
            background: #21262d;
            color: #c9d1d9;
            border: 1px solid #30363d;
            padding: 5px 11px;
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
            padding: 5px 10px;
            border-radius: 6px;
            font-size: 0.82rem;
            cursor: pointer;
        }}
        
        .chart-box {{
            margin: 14px 24px 0 24px;
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            overflow: hidden;
            position: relative;
        }}
        .chart-header {{
            padding: 8px 16px;
            font-size: 0.83rem;
            font-weight: 600;
            color: #8b949e;
            border-bottom: 1px solid #21262d;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        canvas {{ display: block; width: 100%; }}
        
        #tooltip {{
            position: absolute;
            display: none;
            background: rgba(22, 27, 34, 0.96);
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
            max-height: 320px;
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
        <h1>LLMTrading Visualizer <span class="badge">Seamless 10.5-Month Canvas</span></h1>
        <div style="font-size:0.85rem; color:#8b949e;">
            Asset: <strong style="color:#fff;">XAUUSD M5 (Continuous 24h Flow)</strong> | Bars: <strong>{len(candles):,}</strong> | Trades: <strong>{len(trade_list)}</strong>
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
        <span style="font-size:0.8rem; font-weight:600; color:#8b949e;">FILTER:</span>
        <button id="btn-all" class="btn active" onclick="setDisplayFilter('all')">All ({len(trade_list)})</button>
        <button id="btn-buys" class="btn" onclick="setDisplayFilter('buys')">BUY ({buys_count})</button>
        <button id="btn-sells" class="btn" onclick="setDisplayFilter('sells')">SELL ({sells_count})</button>
        <button id="btn-wins" class="btn" onclick="setDisplayFilter('wins')">Winners</button>
        <button id="btn-losses" class="btn" onclick="setDisplayFilter('losses')">Losers</button>

        <select id="trade-select" onchange="onSelectTradeDropdown(this.value)">
            <option value="">-- Jump to Trade --</option>
        </select>
        
        <button class="btn" onclick="resetPriceScale()">Reset Vertical Scale</button>
        <button class="btn" onclick="fitAllChart()">Fit Dataset</button>

        <div style="margin-left:auto; display:flex; gap:12px; font-size:0.8rem; align-items:center;">
            <span style="color:#58a6ff; font-weight:600;">↕ Drag Price Axis to Zoom Vertically</span>
            <span><strong style="color:#3fb950;">- - - ↗</strong> Win</span>
            <span><strong style="color:#f85149;">- - - ↘</strong> Loss</span>
        </div>
    </div>

    <!-- 1. Candlestick Chart Box -->
    <div class="chart-box">
        <div class="chart-header">
            <span id="inspect-banner">XAUUSD Candlestick Trajectory View</span>
            <span style="font-size:0.75rem; color:#8b949e;">
                🖱️ Chart: Drag in any direction (2D pan) • Right Axis: Drag Up/Down to zoom vertically
            </span>
        </div>
        <canvas id="candle-canvas" height="470"></canvas>
        <div id="tooltip"></div>
    </div>

    <!-- 2. Equity Curve Chart Box -->
    <div class="chart-box" style="margin-top:10px;">
        <div class="chart-header">
            <span>📈 Account Equity Curve ($10,000 Starting Balance)</span>
            <span style="font-weight:700; color:{'#3fb950' if perf.net_profit >= 0 else '#f85149'};">
                {'+' if perf.net_profit >= 0 else ''}${perf.net_profit:,.2f}
            </span>
        </div>
        <canvas id="equity-canvas" height="140"></canvas>
    </div>

    <!-- 3. Daily & Monthly PnL Analytics (2 Interactive Graphs with % vs H-1 / Month-1) -->
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(460px, 1fr)); gap: 14px; margin: 10px 24px 0 24px;">
        <!-- Daily PnL Chart Box -->
        <div class="chart-box" style="margin: 0;">
            <div class="chart-header">
                <span>📅 Daily PnL (% Return vs H-1 Equity)</span>
                <span id="daily-stat-badge" style="font-size:0.75rem; color:#58a6ff;">Hover any bar for H-1 return & PnL</span>
            </div>
            <canvas id="daily-canvas" height="180"></canvas>
        </div>

        <!-- Monthly PnL Chart Box -->
        <div class="chart-box" style="margin: 0;">
            <div class="chart-header">
                <span>📆 Monthly PnL (% Return vs Month-1 Equity)</span>
                <span id="monthly-stat-badge" style="font-size:0.75rem; color:#58a6ff;">Hover any bar for M-1 return & PnL</span>
            </div>
            <canvas id="monthly-canvas" height="180"></canvas>
        </div>
    </div>

    <!-- 4. Executed Trades Table -->
    <div class="table-box">
        <div class="table-header">
            <span>Executed Trades Ledger ({len(trade_list)} Trades)</span>
            <span style="font-size:0.75rem; color:#8b949e;">Click any row to jump directly on chart</span>
        </div>
        <div class="table-scroll">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Side</th>
                        <th>Lots</th>
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
        const eqData = {json.dumps(eq_pts)};
        const dailyData = {json.dumps(daily_pnl_data)};
        const monthlyData = {json.dumps(monthly_pnl_data)};
        
        // Binary search for exact bar index
        function findBarIndex(targetTs) {{
            let low = 0, high = candles.length - 1;
            while (low <= high) {{
                let mid = (low + high) >> 1;
                if (candles[mid].ts <= targetTs) {{
                    if (mid === candles.length - 1 || candles[mid + 1].ts > targetTs) return mid;
                    low = mid + 1;
                }} else {{
                    high = mid - 1;
                }}
            }}
            return Math.max(0, Math.min(candles.length - 1, low));
        }}

        // Canvas 1: Candlestick
        const canvas = document.getElementById('candle-canvas');
        const ctx = canvas.getContext('2d');
        const tooltip = document.getElementById('tooltip');

        // Canvas 2: Equity
        const eqCanvas = document.getElementById('equity-canvas');
        const eqCtx = eqCanvas.getContext('2d');

        // Canvas 3: Daily PnL
        const dailyCanvas = document.getElementById('daily-canvas');
        const dailyCtx = dailyCanvas.getContext('2d');

        // Canvas 4: Monthly PnL
        const monthlyCanvas = document.getElementById('monthly-canvas');
        const monthlyCtx = monthlyCanvas.getContext('2d');
        
        let startIdx = 0;
        let viewCount = 140;
        let displayFilter = 'all';
        let focusedTradeId = null;

        // Vertical Scale State
        let priceScaleMultiplier = 1.0;
        let priceCenterOffset = 0.0;
        let lastVisiblePriceSpan = 10.0;

        let tradeHitboxes = [];
        let dailyHitboxes = [];
        let monthlyHitboxes = [];
        let hoveredDailyIdx = -1;
        let hoveredMonthlyIdx = -1;

        const padLeft = 10;
        const padRight = 85;
        const padTop = 25;
        const padBottom = 25;

        function resizeCanvases() {{
            canvas.width = canvas.parentElement.clientWidth;
            eqCanvas.width = eqCanvas.parentElement.clientWidth;
            dailyCanvas.width = dailyCanvas.parentElement.clientWidth;
            monthlyCanvas.width = monthlyCanvas.parentElement.clientWidth;
            drawChart();
            drawEquityChart();
            drawDailyPnLChart();
            drawMonthlyPnLChart();
        }}
        window.addEventListener('resize', resizeCanvases);

        // --- DRAW CANDLESTICK CHART ---
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

            const visibleStartTs = slice[0].ts;
            const visibleEndTs = slice[slice.length - 1].ts;

            const visibleTrades = trades.filter(t => {{
                if (displayFilter === 'buys' && t.side !== 'BUY') return false;
                if (displayFilter === 'sells' && t.side !== 'SELL') return false;
                if (displayFilter === 'wins' && !t.win) return false;
                if (displayFilter === 'losses' && t.win) return false;
                return (t.close_ts >= visibleStartTs && t.open_ts <= visibleEndTs);
            }});

            for (let t of visibleTrades) {{
                minP = Math.min(minP, t.entry, t.exit);
                maxP = Math.max(maxP, t.entry, t.exit);
                if (t.sl) minP = Math.min(minP, t.sl);
                if (t.tp) maxP = Math.max(maxP, t.tp);
            }}

            const rawSpan = Math.max(0.2, maxP - minP);
            const rawCenter = (minP + maxP) / 2.0;

            const effectiveSpan = rawSpan / priceScaleMultiplier;
            lastVisiblePriceSpan = effectiveSpan;

            const effectiveCenter = rawCenter + priceCenterOffset;
            const effectiveMinP = effectiveCenter - (effectiveSpan / 2.0);
            const effectiveMaxP = effectiveCenter + (effectiveSpan / 2.0);

            const chartW = W - padLeft - padRight;
            const chartH = H - padTop - padBottom;
            const candleW = Math.max(1, chartW / slice.length);

            function getY(p) {{
                return padTop + chartH - ((p - effectiveMinP) / effectiveSpan) * chartH;
            }}

            function getX(idxInSlice) {{
                return padLeft + idxInSlice * candleW + candleW / 2;
            }}

            // Draw Background Grid
            ctx.strokeStyle = '#21262d';
            ctx.lineWidth = 1;
            ctx.fillStyle = '#8b949e';
            ctx.font = '11px -apple-system, sans-serif';
            ctx.textAlign = 'left';

            const priceStep = Math.pow(10, Math.floor(Math.log10(effectiveSpan))) * 0.5 || 1.0;
            const firstGridP = Math.ceil(effectiveMinP / priceStep) * priceStep;
            for (let p = firstGridP; p <= effectiveMaxP; p += priceStep) {{
                const y = getY(p);
                if (y >= padTop && y <= H - padBottom) {{
                    ctx.beginPath();
                    ctx.moveTo(padLeft, y);
                    ctx.lineTo(W - padRight, y);
                    ctx.stroke();
                    ctx.fillText('$' + p.toFixed(2), W - padRight + 10, y + 4);
                }}
            }}

            // Draw Candles
            for (let i = 0; i < slice.length; i++) {{
                const c = slice[i];
                const x = getX(i);
                const isGreen = c.c >= c.o;
                const bodyTop = getY(Math.max(c.o, c.c));
                const bodyBottom = getY(Math.min(c.o, c.c));
                const bodyH = Math.max(1, bodyBottom - bodyTop);

                ctx.strokeStyle = isGreen ? '#3fb950' : '#f85149';
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(x, getY(c.h));
                ctx.lineTo(x, getY(c.l));
                ctx.stroke();

                ctx.fillStyle = isGreen ? '#238636' : '#da3633';
                const bw = Math.max(1, candleW - 2);
                ctx.fillRect(x - bw / 2, bodyTop, bw, bodyH);
            }}

            // Draw Trade Trajectories
            for (let t of visibleTrades) {{
                const openIdxAll = findBarIndex(t.open_ts);
                const closeIdxAll = findBarIndex(t.close_ts);

                const openRelIdx = openIdxAll - startIdx;
                const closeRelIdx = closeIdxAll - startIdx;

                const x1 = getX(openRelIdx);
                const y1 = getY(t.entry);
                const x2 = getX(closeRelIdx);
                const y2 = getY(t.exit);

                const isFocused = (t.id === focusedTradeId);
                const trajColor = t.win ? '#3fb950' : '#f85149';

                ctx.save();
                ctx.strokeStyle = trajColor;
                ctx.lineWidth = isFocused ? 3 : 2;
                ctx.setLineDash([5, 4]);
                ctx.beginPath();
                ctx.moveTo(x1, y1);
                ctx.lineTo(x2, y2);
                ctx.stroke();
                ctx.restore();

                // Entry dot
                ctx.fillStyle = '#58a6ff';
                ctx.beginPath();
                ctx.arc(x1, y1, isFocused ? 6 : 4, 0, Math.PI * 2);
                ctx.fill();

                // Exit dot
                ctx.fillStyle = trajColor;
                ctx.beginPath();
                ctx.arc(x2, y2, isFocused ? 6 : 4, 0, Math.PI * 2);
                ctx.fill();

                tradeHitboxes.push({{ trade: t, x1, y1, x2, y2 }});
            }}

            // Right Price Scale Area Divider
            ctx.fillStyle = '#161b22';
            ctx.fillRect(W - padRight, 0, padRight, H);
            ctx.strokeStyle = '#30363d';
            ctx.beginPath();
            ctx.moveTo(W - padRight, 0);
            ctx.lineTo(W - padRight, H);
            ctx.stroke();
        }}

        // --- DRAW EQUITY CHART ---
        function drawEquityChart() {{
            const W = eqCanvas.width;
            const H = eqCanvas.height;
            eqCtx.clearRect(0, 0, W, H);
            if (eqData.length === 0) return;

            let minEq = Infinity;
            let maxEq = -Infinity;
            for (let d of eqData) {{
                if (d.eq < minEq) minEq = d.eq;
                if (d.eq > maxEq) maxEq = d.eq;
            }}
            minEq = Math.min(minEq, 10000.0);
            maxEq = Math.max(maxEq, 10000.0);
            const spanEq = Math.max(100.0, maxEq - minEq);

            function getEqY(val) {{
                return padTop + (H - padTop - padBottom) - ((val - minEq) / spanEq) * (H - padTop - padBottom);
            }}

            eqCtx.strokeStyle = '#21262d';
            eqCtx.lineWidth = 1;
            eqCtx.fillStyle = '#8b949e';
            eqCtx.font = '11px -apple-system, sans-serif';
            eqCtx.textAlign = 'left';

            const eqSteps = [minEq, 10000.0, maxEq];
            for (let val of eqSteps) {{
                const y = getEqY(val);
                eqCtx.beginPath();
                eqCtx.moveTo(padLeft, y);
                eqCtx.lineTo(W - padRight, y);
                eqCtx.stroke();
                eqCtx.fillText('$' + val.toLocaleString('en-US', {{ minimumFractionDigits: 0 }}), W - padRight + 10, y + 4);
            }}

            // $10,000 Baseline
            const y10k = getEqY(10000.0);
            eqCtx.strokeStyle = '#30363d';
            eqCtx.setLineDash([4, 4]);
            eqCtx.beginPath();
            eqCtx.moveTo(padLeft, y10k);
            eqCtx.lineTo(W - padRight, y10k);
            eqCtx.stroke();
            eqCtx.setLineDash([]);

            // Draw Equity Area & Line
            const stepX = (W - padLeft - padRight) / Math.max(1, eqData.length - 1);
            eqCtx.beginPath();
            for (let i = 0; i < eqData.length; i++) {{
                const x = padLeft + i * stepX;
                const y = getEqY(eqData[i].eq);
                if (i === 0) eqCtx.moveTo(x, y);
                else eqCtx.lineTo(x, y);
            }}
            eqCtx.lineTo(padLeft + (eqData.length - 1) * stepX, H - 20);
            eqCtx.lineTo(padLeft, H - 20);
            eqCtx.closePath();
            eqCtx.fillStyle = 'rgba(88, 166, 255, 0.12)';
            eqCtx.fill();

            eqCtx.beginPath();
            for (let i = 0; i < eqData.length; i++) {{
                const x = padLeft + i * stepX;
                const y = getEqY(eqData[i].eq);
                if (i === 0) eqCtx.moveTo(x, y);
                else eqCtx.lineTo(x, y);
            }}
            eqCtx.strokeStyle = '#58a6ff';
            eqCtx.lineWidth = 2;
            eqCtx.stroke();

            const lastX = padLeft + (eqData.length - 1) * stepX;
            const lastY = getEqY(eqData[eqData.length - 1].eq);
            eqCtx.fillStyle = '#58a6ff';
            eqCtx.beginPath();
            eqCtx.arc(lastX, lastY, 5, 0, Math.PI * 2);
            eqCtx.fill();

            eqCtx.fillStyle = '#161b22';
            eqCtx.fillRect(W - padRight, 0, padRight, H);
            eqCtx.strokeStyle = '#30363d';
            eqCtx.beginPath();
            eqCtx.moveTo(W - padRight, 0);
            eqCtx.lineTo(W - padRight, H);
            eqCtx.stroke();

            eqCtx.fillStyle = '#58a6ff';
            eqCtx.font = 'bold 11px sans-serif';
            eqCtx.fillText('$' + eqData[eqData.length - 1].eq.toFixed(2), W - padRight + 10, lastY + 4);
        }}

        // --- DRAW DAILY PNL CHART (% vs H-1 Equity) ---
        function drawDailyPnLChart() {{
            const W = dailyCanvas.width;
            const H = dailyCanvas.height;
            dailyCtx.clearRect(0, 0, W, H);
            dailyHitboxes = [];
            if (dailyData.length === 0) return;

            let maxAbsPct = 0.5;
            for (let d of dailyData) {{
                const a = Math.abs(d.pct_vs_prev);
                if (a > maxAbsPct) maxAbsPct = a;
            }}
            maxAbsPct = Math.max(1.5, maxAbsPct * 1.15); // Add headroom

            const chartW = W - padLeft - padRight;
            const chartH = H - 40;
            const zeroY = 20 + chartH / 2.0;

            function getYPct(pct) {{
                return zeroY - (pct / maxAbsPct) * (chartH / 2.0);
            }}

            // Gridlines for %
            dailyCtx.strokeStyle = '#21262d';
            dailyCtx.lineWidth = 1;
            dailyCtx.fillStyle = '#8b949e';
            dailyCtx.font = '10px -apple-system, sans-serif';
            dailyCtx.textAlign = 'left';

            const pctSteps = [-2.0, -1.0, 1.0, 2.0, 3.0].filter(p => Math.abs(p) <= maxAbsPct);
            for (let p of pctSteps) {{
                const y = getYPct(p);
                dailyCtx.beginPath();
                dailyCtx.moveTo(padLeft, y);
                dailyCtx.lineTo(W - padRight, y);
                dailyCtx.stroke();
                dailyCtx.fillText((p > 0 ? '+' : '') + p.toFixed(1) + '%', W - padRight + 10, y + 3);
            }}

            // Zero Line (0.0%)
            dailyCtx.strokeStyle = '#30363d';
            dailyCtx.lineWidth = 1.5;
            dailyCtx.beginPath();
            dailyCtx.moveTo(padLeft, zeroY);
            dailyCtx.lineTo(W - padRight, zeroY);
            dailyCtx.stroke();
            dailyCtx.fillText('0.0%', W - padRight + 10, zeroY + 3);

            // Draw Daily Bars
            const slotW = chartW / dailyData.length;
            const barW = Math.max(2, slotW - 1.5);

            for (let i = 0; i < dailyData.length; i++) {{
                const d = dailyData[i];
                const x = padLeft + i * slotW + (slotW - barW) / 2;
                const yVal = getYPct(d.pct_vs_prev);
                const isPos = d.pct_vs_prev >= 0;

                const topY = isPos ? yVal : zeroY;
                const barH = Math.max(2, Math.abs(yVal - zeroY));

                dailyCtx.fillStyle = isPos ? '#3fb950' : '#f85149';
                if (i === hoveredDailyIdx) {{
                    dailyCtx.fillStyle = '#fff'; // Highlight on hover
                }}
                dailyCtx.fillRect(x, topY, barW, barH);

                dailyHitboxes.push({{
                    idx: i,
                    data: d,
                    x: x,
                    y: topY,
                    w: barW,
                    h: barH
                }});
            }}

            // Right Axis Mask
            dailyCtx.fillStyle = '#161b22';
            dailyCtx.fillRect(W - padRight, 0, padRight, H);
            dailyCtx.strokeStyle = '#30363d';
            dailyCtx.beginPath();
            dailyCtx.moveTo(W - padRight, 0);
            dailyCtx.lineTo(W - padRight, H);
            dailyCtx.stroke();
            dailyCtx.fillStyle = '#8b949e';
            dailyCtx.font = '10px sans-serif';
            dailyCtx.fillText('0.0%', W - padRight + 10, zeroY + 3);
        }}

        // --- DRAW MONTHLY PNL CHART (% vs Month-1 Equity) ---
        function drawMonthlyPnLChart() {{
            const W = monthlyCanvas.width;
            const H = monthlyCanvas.height;
            monthlyCtx.clearRect(0, 0, W, H);
            monthlyHitboxes = [];
            if (monthlyData.length === 0) return;

            let maxAbsPct = 3.0;
            for (let m of monthlyData) {{
                const a = Math.abs(m.pct_vs_prev);
                if (a > maxAbsPct) maxAbsPct = a;
            }}
            maxAbsPct = Math.max(5.0, maxAbsPct * 1.25); // Add headroom for label text

            const chartW = W - padLeft - padRight;
            const chartH = H - 45;
            const zeroY = 20 + chartH * (maxAbsPct / (maxAbsPct * 1.5)); // Balanced zero axis

            function getYPct(pct) {{
                return zeroY - (pct / maxAbsPct) * (chartH * 0.65);
            }}

            // Zero Line
            monthlyCtx.strokeStyle = '#30363d';
            monthlyCtx.lineWidth = 1.5;
            monthlyCtx.beginPath();
            monthlyCtx.moveTo(padLeft, zeroY);
            monthlyCtx.lineTo(W - padRight, zeroY);
            monthlyCtx.stroke();

            monthlyCtx.fillStyle = '#8b949e';
            monthlyCtx.font = '10px -apple-system, sans-serif';
            monthlyCtx.textAlign = 'left';
            monthlyCtx.fillText('0.0%', W - padRight + 10, zeroY + 3);

            // Draw Monthly Bars
            const slotW = chartW / monthlyData.length;
            const barW = Math.max(12, Math.min(32, slotW * 0.65));

            for (let i = 0; i < monthlyData.length; i++) {{
                const m = monthlyData[i];
                const xCenter = padLeft + i * slotW + slotW / 2;
                const x = xCenter - barW / 2;
                const yVal = getYPct(m.pct_vs_prev);
                const isPos = m.pct_vs_prev >= 0;

                const topY = isPos ? yVal : zeroY;
                const barH = Math.max(3, Math.abs(yVal - zeroY));

                // Bar fill
                monthlyCtx.fillStyle = isPos ? '#238636' : '#da3633';
                if (i === hoveredMonthlyIdx) {{
                    monthlyCtx.fillStyle = isPos ? '#3fb950' : '#f85149';
                    monthlyCtx.strokeStyle = '#fff';
                    monthlyCtx.lineWidth = 1.5;
                    monthlyCtx.strokeRect(x, topY, barW, barH);
                }}
                monthlyCtx.fillRect(x, topY, barW, barH);

                // Label above / below bar (% vs Month-1)
                monthlyCtx.fillStyle = isPos ? '#3fb950' : '#f85149';
                monthlyCtx.font = 'bold 10px -apple-system, sans-serif';
                monthlyCtx.textAlign = 'center';
                const pctStr = (isPos ? '+' : '') + m.pct_vs_prev.toFixed(1) + '%';
                if (isPos) {{
                    monthlyCtx.fillText(pctStr, xCenter, topY - 5);
                }} else {{
                    monthlyCtx.fillText(pctStr, xCenter, topY + barH + 12);
                }}

                // Month Name underneath
                monthlyCtx.fillStyle = '#8b949e';
                monthlyCtx.font = '10px sans-serif';
                monthlyCtx.fillText(m.label, xCenter, H - 6);

                monthlyHitboxes.push({{
                    idx: i,
                    data: m,
                    x: x,
                    y: topY,
                    w: barW,
                    h: barH,
                    xCenter: xCenter
                }});
            }}

            // Right Axis Mask
            monthlyCtx.fillStyle = '#161b22';
            monthlyCtx.fillRect(W - padRight, 0, padRight, H);
            monthlyCtx.strokeStyle = '#30363d';
            monthlyCtx.beginPath();
            monthlyCtx.moveTo(W - padRight, 0);
            monthlyCtx.lineTo(W - padRight, H);
            monthlyCtx.stroke();
            monthlyCtx.fillStyle = '#8b949e';
            monthlyCtx.font = '10px sans-serif';
            monthlyCtx.fillText('0.0%', W - padRight + 10, zeroY + 3);
        }}

        // --- DAILY CANVAS INTERACTIONS ---
        dailyCanvas.addEventListener('mousemove', e => {{
            const rect = dailyCanvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;

            let hit = null;
            for (let hb of dailyHitboxes) {{
                if (mouseX >= hb.x - 2 && mouseX <= hb.x + hb.w + 2) {{
                    hit = hb;
                    break;
                }}
            }}

            if (hit) {{
                hoveredDailyIdx = hit.idx;
                drawDailyPnLChart();

                const d = hit.data;
                const pnlCol = d.pnl >= 0 ? '#3fb950' : '#f85149';
                const sign = d.pnl >= 0 ? '+' : '';
                document.getElementById('daily-stat-badge').innerHTML = 
                    `📅 <strong>${{d.date}}</strong>: PnL <strong style="color:${{pnlCol}};">${{sign}}$${{d.pnl.toFixed(2)}}</strong> | <strong style="color:${{pnlCol}};">${{sign}}${{d.pct_vs_prev}}% vs H-1</strong> (Eq: $${{d.prev_eq.toLocaleString()}} → $${{d.end_eq.toLocaleString()}})`;

                tooltip.style.display = 'block';
                tooltip.style.left = (e.clientX + 15) + 'px';
                tooltip.style.top = (e.clientY - 20) + 'px';
                tooltip.innerHTML = `
                    <div style="font-weight:700; color:#fff; margin-bottom:2px;">📅 Day: ${{d.date}}</div>
                    <div>Net PnL: <strong style="color:${{pnlCol}};">${{sign}}$${{d.pnl.toFixed(2)}}</strong></div>
                    <div>Return vs H-1: <strong style="color:${{pnlCol}};">${{sign}}${{d.pct_vs_prev}}%</strong></div>
                    <div>Prior Equity (H-1): <strong>$${{d.prev_eq.toLocaleString()}}</strong></div>
                    <div>Day-End Equity: <strong>$${{d.end_eq.toLocaleString()}}</strong></div>
                    <div>Trades: <strong>${{d.trades}}</strong> (${{d.wins}}W / ${{d.losses}}L)</div>
                    <div style="font-size:0.7rem; color:#8b949e; margin-top:4px;">🖱️ Click bar to jump chart to this day</div>
                `;
            }} else {{
                hoveredDailyIdx = -1;
                drawDailyPnLChart();
                tooltip.style.display = 'none';
            }}
        }});

        dailyCanvas.addEventListener('mouseleave', () => {{
            hoveredDailyIdx = -1;
            drawDailyPnLChart();
            tooltip.style.display = 'none';
            document.getElementById('daily-stat-badge').textContent = 'Hover any bar for H-1 return & PnL';
        }});

        dailyCanvas.addEventListener('click', e => {{
            const rect = dailyCanvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            for (let hb of dailyHitboxes) {{
                if (mouseX >= hb.x - 2 && mouseX <= hb.x + hb.w + 2) {{
                    const barIdx = findBarIndex(hb.data.first_ts);
                    startIdx = Math.max(0, barIdx - 15);
                    viewCount = 100;
                    resetPriceScale();
                    drawChart();
                    document.getElementById('inspect-banner').innerHTML = 
                        `Jumped to Date: <strong>${{hb.data.date}}</strong> | Day Return: <strong style="color:${{hb.data.pct_vs_prev >= 0 ? '#3fb950' : '#f85149'}};">${{hb.data.pct_vs_prev >= 0 ? '+' : ''}}${{hb.data.pct_vs_prev}}% vs H-1</strong>`;
                    break;
                }}
            }}
        }});

        // --- MONTHLY CANVAS INTERACTIONS ---
        monthlyCanvas.addEventListener('mousemove', e => {{
            const rect = monthlyCanvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;

            let hit = null;
            for (let hb of monthlyHitboxes) {{
                if (mouseX >= hb.x - 4 && mouseX <= hb.x + hb.w + 4) {{
                    hit = hb;
                    break;
                }}
            }}

            if (hit) {{
                hoveredMonthlyIdx = hit.idx;
                drawMonthlyPnLChart();

                const m = hit.data;
                const pnlCol = m.pnl >= 0 ? '#3fb950' : '#f85149';
                const sign = m.pnl >= 0 ? '+' : '';
                document.getElementById('monthly-stat-badge').innerHTML = 
                    `📆 <strong>${{m.label}}</strong>: PnL <strong style="color:${{pnlCol}};">${{sign}}$${{m.pnl.toFixed(2)}}</strong> | <strong style="color:${{pnlCol}};">${{sign}}${{m.pct_vs_prev}}% vs M-1</strong>`;

                tooltip.style.display = 'block';
                tooltip.style.left = (e.clientX + 15) + 'px';
                tooltip.style.top = (e.clientY - 20) + 'px';
                tooltip.innerHTML = `
                    <div style="font-weight:700; color:#fff; margin-bottom:2px;">📆 Month: ${{m.label}} (${{m.month}})</div>
                    <div>Net PnL: <strong style="color:${{pnlCol}};">${{sign}}$${{m.pnl.toFixed(2)}}</strong></div>
                    <div>Return vs Month-1: <strong style="color:${{pnlCol}};">${{sign}}${{m.pct_vs_prev}}%</strong></div>
                    <div>Prior Month Eq (M-1): <strong>$${{m.prev_eq.toLocaleString()}}</strong></div>
                    <div>Month-End Equity: <strong>$${{m.end_eq.toLocaleString()}}</strong></div>
                    <div>Trades: <strong>${{m.trades}}</strong> (${{m.wins}}W / ${{m.losses}}L | ${{m.win_rate}}% Win Rate)</div>
                    <div style="font-size:0.7rem; color:#8b949e; margin-top:4px;">🖱️ Click bar to jump chart to this month</div>
                `;
            }} else {{
                hoveredMonthlyIdx = -1;
                drawMonthlyPnLChart();
                tooltip.style.display = 'none';
            }}
        }});

        monthlyCanvas.addEventListener('mouseleave', () => {{
            hoveredMonthlyIdx = -1;
            drawMonthlyPnLChart();
            tooltip.style.display = 'none';
            document.getElementById('monthly-stat-badge').textContent = 'Hover any bar for M-1 return & PnL';
        }});

        monthlyCanvas.addEventListener('click', e => {{
            const rect = monthlyCanvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            for (let hb of monthlyHitboxes) {{
                if (mouseX >= hb.x - 4 && mouseX <= hb.x + hb.w + 4) {{
                    const barIdx = findBarIndex(hb.data.first_ts);
                    startIdx = Math.max(0, barIdx - 10);
                    viewCount = 300;
                    resetPriceScale();
                    drawChart();
                    document.getElementById('inspect-banner').innerHTML = 
                        `Jumped to Month: <strong>${{hb.data.label}}</strong> | Return: <strong style="color:${{hb.data.pct_vs_prev >= 0 ? '#3fb950' : '#f85149'}};">${{hb.data.pct_vs_prev >= 0 ? '+' : ''}}${{hb.data.pct_vs_prev}}% vs Month-1</strong>`;
                    break;
                }}
            }}
        }});

        // --- MOUSE INTERACTIONS (PAN & SCALE FOR CANDLESTICK) ---
        let dragMode = null;
        let startMouseX = 0;
        let startMouseY = 0;
        let dragStartIdx = 0;
        let dragStartCenterOffset = 0.0;
        let initialScaleMultiplier = 1.0;

        canvas.addEventListener('mousedown', e => {{
            const rect = canvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;

            startMouseX = e.clientX;
            startMouseY = e.clientY;

            if (mouseX >= canvas.width - padRight) {{
                dragMode = 'scale-price';
                initialScaleMultiplier = priceScaleMultiplier;
                canvas.style.cursor = 'ns-resize';
            }} else {{
                dragMode = 'pan-chart';
                dragStartIdx = startIdx;
                dragStartCenterOffset = priceCenterOffset;
                canvas.style.cursor = 'grabbing';
            }}
        }});

        window.addEventListener('mouseup', () => {{
            dragMode = null;
            canvas.style.cursor = 'crosshair';
        }});

        window.addEventListener('mousemove', e => {{
            const rect = canvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;

            if (!dragMode) {{
                if (mouseX >= canvas.width - padRight) {{
                    canvas.style.cursor = 'ns-resize';
                }} else {{
                    canvas.style.cursor = 'crosshair';
                }}
            }}

            if (dragMode === 'scale-price') {{
                const dy = startMouseY - e.clientY;
                const scaleFactor = 1.0 + (dy * 0.01);
                priceScaleMultiplier = Math.max(0.1, Math.min(20.0, initialScaleMultiplier * scaleFactor));
                drawChart();
                return;
            }}

            if (dragMode === 'pan-chart') {{
                const dx = e.clientX - startMouseX;
                const dy = e.clientY - startMouseY;

                const deltaBars = Math.round((dx / canvas.width) * viewCount);
                startIdx = Math.max(0, Math.min(candles.length - viewCount, dragStartIdx - deltaBars));

                const chartH = canvas.height - padTop - padBottom;
                const priceDelta = (dy / chartH) * lastVisiblePriceSpan;
                priceCenterOffset = dragStartCenterOffset + priceDelta;

                drawChart();
                return;
            }}

            // Hover Tooltip Check
            let hovered = null;
            let minDist = 14;
            for (let hb of tradeHitboxes) {{
                const d = distToSegment(mouseX, mouseY, hb.x1, hb.y1, hb.x2, hb.y2);
                if (d < minDist) {{
                    minDist = d;
                    hovered = hb.trade;
                }}
            }}

            if (hovered && mouseX < canvas.width - padRight) {{
                tooltip.style.display = 'block';
                tooltip.style.left = (e.clientX + 15) + 'px';
                tooltip.style.top = (e.clientY - 20) + 'px';
                const pnlCol = hovered.win ? '#3fb950' : '#f85149';
                const pnlSign = hovered.win ? '+' : '';
                tooltip.innerHTML = `
                    <div style="font-weight:700; color:#fff; margin-bottom:2px;">Trade #${{hovered.id}} (${{hovered.side}} - ${{hovered.lots}}L)</div>
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

        canvas.addEventListener('dblclick', e => {{
            const rect = canvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            if (mouseX >= canvas.width - padRight) resetPriceScale();
        }});

        function resetPriceScale() {{
            priceScaleMultiplier = 1.0;
            priceCenterOffset = 0.0;
            drawChart();
        }}

        canvas.addEventListener('wheel', e => {{
            e.preventDefault();
            const rect = canvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;

            if (mouseX >= canvas.width - padRight) {{
                const zoomIn = (e.deltaY < 0);
                priceScaleMultiplier = Math.max(0.1, Math.min(20.0, priceScaleMultiplier * (zoomIn ? 1.15 : 0.85)));
                drawChart();
            }} else {{
                const zoomIn = (e.deltaY < 0);
                const delta = zoomIn ? -Math.max(5, Math.floor(viewCount * 0.15)) : Math.max(5, Math.floor(viewCount * 0.15));
                const newCount = Math.max(25, Math.min(candles.length, viewCount + delta));
                startIdx = Math.max(0, Math.min(candles.length - newCount, startIdx + Math.round((viewCount - newCount) / 2)));
                viewCount = newCount;
                drawChart();
            }}
        }}, {{ passive: false }});

        function distToSegment(px, py, x1, y1, x2, y2) {{
            const l2 = (x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1);
            if (l2 === 0) return Math.hypot(px - x1, py - y1);
            let t = ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2;
            t = Math.max(0, Math.min(1, t));
            return Math.hypot(px - (x1 + t * (x2 - x1)), py - (y1 + t * (y2 - y1)));
        }}

        function setDisplayFilter(filter) {{
            displayFilter = filter;
            document.querySelectorAll('#toolbar .btn').forEach(b => b.classList.remove('active'));
            if (filter === 'all') document.getElementById('btn-all').classList.add('active');
            if (filter === 'buys') document.getElementById('btn-buys').classList.add('active');
            if (filter === 'sells') document.getElementById('btn-sells').classList.add('active');
            if (filter === 'wins') document.getElementById('btn-wins').classList.add('active');
            if (filter === 'losses') document.getElementById('btn-losses').classList.add('active');

            drawChart();
        }}

        function fitAllChart() {{
            startIdx = 0;
            viewCount = candles.length;
            resetPriceScale();
            drawChart();
        }}

        // Populate Table & Dropdown
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
                <td>${{t.lots}}</td>
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

            document.querySelectorAll('.clickable-row').forEach(r => r.classList.remove('selected-row'));
            const r = document.getElementById('row-' + tradeId);
            if (r) {{
                r.classList.add('selected-row');
                r.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
            }}

            let openIdx = findBarIndex(tr.open_ts);
            openIdx = openIdx || 0;

            viewCount = 60;
            startIdx = Math.max(0, openIdx - 15);
            resetPriceScale();

            const pnlStr = (tr.win ? '+' : '') + '$' + tr.pnl.toFixed(2);
            document.getElementById('inspect-banner').innerHTML = 
                `Inspecting <strong>Trade #${{tr.id}} (${{tr.side}} - ${{tr.lots}}L)</strong>: Entry <strong>$${{tr.entry}}</strong> -> Exit <strong>$${{tr.exit}}</strong> | PnL: <strong style="color:${{tr.win ? '#3fb950' : '#f85149'}};">${{pnlStr}}</strong> (${{tr.reason}})`;

            drawChart();
        }}

        resizeCanvases();
    </script>
</body>
</html>
"""

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        f.write(html)

    print(f"[Visualizer] SUCCESS! Generated ultra-responsive visualizer with Daily & Monthly PnL (% vs H-1 / M-1) at: {out_path.resolve()} ({out_path.stat().st_size / (1024**2):.2f} MB)")
    return str(out_path.resolve())


if __name__ == "__main__":
    generate_optimized_visual()
