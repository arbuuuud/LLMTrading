"""
Injects:
1. Top Navigation Bar (with 💼 4 Portfolio Profiles menu) & Login Modal right after <body>.
2. The complete 'pane-portfolios' HTML view with interactive profile switcher and comparison matrix.
3. Client JS logic to dynamically load and display portfolio data.
"""

from pathlib import Path
import json

INDEX_PATH = Path("reports/index.html")
with open(INDEX_PATH, "r", encoding="utf-8") as f:
    content = f.read()

# Load 4-portfolio data to embed as default fallback
four_profiles = json.load(open("reports/four_risk_profiles_comparison.json"))

# Top bar & login modal
nav_and_modal = """
    <!-- === INSTITUTIONAL AUTHENTICATION MODAL === -->
    <div id="login-modal-overlay">
        <div class="login-card">
            <div class="login-title">
                <span>🏛️ LLMTrading Brain</span>
                <span class="badge" style="background:#1f6feb;">v2.0 Live</span>
            </div>
            <div class="login-subtitle">
                Institutional Multi-Agent & Multi-Account Risk Management Gateway.<br>
                Silakan login untuk mengelola akun MetaTrader 5 & profil risiko.
            </div>
            <form id="login-form" onsubmit="handleLoginSubmit(event)">
                <div class="form-group">
                    <label class="form-label">Email Operator / Trader</label>
                    <input type="email" id="login-email" class="form-input" value="arief.setiabudi2010@gmail.com" required>
                </div>
                <div class="form-group">
                    <label class="form-label">Password</label>
                    <input type="password" id="login-password" class="form-input" value="P@ssw0rd!" required>
                </div>
                <button type="submit" class="btn-submit">🔓 Sign In to Brain Portal</button>
                <div id="login-err" class="login-error">Password salah atau otorisasi ditolak.</div>
                <div class="quick-fill" onclick="autoFillCredentials()">
                    ⚡ Quick Fill: arief.setiabudi2010@gmail.com / P@ssw0rd!
                </div>
            </form>
        </div>
    </div>

    <!-- === TOAST NOTIFICATION === -->
    <div id="toast-notify" class="toast-msg">✅ Profil risiko berhasil diperbarui!</div>

    <!-- === TOP NAVIGATION BAR === -->
    <div class="top-nav">
        <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
            <span style="font-weight:700; font-size:1.05rem; color:#fff; display:flex; align-items:center; gap:6px;">
                ⚡ LLMTrading <span style="font-size:0.75rem; background:#21262d; border:1px solid #30363d; padding:2px 8px; border-radius:12px; color:#58a6ff;">Dual-Engine</span>
            </span>
            <div class="nav-tabs">
                <button id="nav-btn-accounts" class="nav-tab-btn active" onclick="switchMainTab('ACCOUNTS')">
                    👥 Account & Risk Manager
                </button>
                <button id="nav-btn-portfolios" class="nav-tab-btn" onclick="switchMainTab('PORTFOLIOS')">
                    💼 4 Portfolio Profiles
                </button>
                <button id="nav-btn-analytics" class="nav-tab-btn" onclick="switchMainTab('ANALYTICS')">
                    📈 Performance & 60fps Visualizer
                </button>
                <button id="nav-btn-profiles" class="nav-tab-btn" onclick="switchMainTab('PROFILES')">
                    🛡️ Risk Matrix Presets
                </button>
            </div>
        </div>

        <div style="display:flex; align-items:center; gap:12px;">
            <div class="user-chip">
                <span>🟢 Connected</span>
                <span style="color:#58a6ff; font-weight:600;" id="user-display">arief.setiabudi2010@gmail.com</span>
                <button class="logout-btn" onclick="handleLogout()">Logout</button>
            </div>
        </div>
    </div>
"""

portfolios_pane_html = f"""
    <!-- ============================================================= -->
    <!-- TAB 2: 4 PORTFOLIO PROFILES SHOWCASE (NEW MENU)               -->
    <!-- ============================================================= -->
    <div id="pane-portfolios" class="accounts-container" style="display:none;">
        <div class="accounts-banner" style="background: linear-gradient(135deg, #1f6feb 0%, #8957e5 100%);">
            <div>
                <div class="banner-title">💼 4 Portfolio Profiles Showcase (10.5 Months XAUUSD Audit)</div>
                <div class="banner-desc">
                    Bandingkan kinerja riil portofolio gabungan (Scalper M1 + Intraday M15) di bawah 4 variasi setting risiko.
                    Pilih profil di bawah untuk melihat detail statistik, kurva laba, dan rincian laba bulanan.
                </div>
            </div>
        </div>

        <!-- 4 Profile Quick Selector Pill Bar -->
        <div style="display:flex; gap:10px; margin-bottom:20px; flex-wrap:wrap;">
            <button id="port-pill-prop_firm" class="profile-btn prop_firm" style="font-size:0.85rem; padding:8px 16px;" onclick="selectPortfolioView('prop_firm')">
                🛡️ Prop Firm (0.50% Base)
            </button>
            <button id="port-pill-sweet_spot" class="profile-btn sweet_spot selected" style="font-size:0.85rem; padding:8px 16px;" onclick="selectPortfolioView('sweet_spot')">
                ⚖️ Sweet Spot (0.75% Base) - Rekomendasi
            </button>
            <button id="port-pill-aggressive" class="profile-btn aggressive" style="font-size:0.85rem; padding:8px 16px;" onclick="selectPortfolioView('aggressive')">
                🚀 Aggressive (1.00% Base)
            </button>
            <button id="port-pill-yolo" class="profile-btn yolo" style="font-size:0.85rem; padding:8px 16px;" onclick="selectPortfolioView('yolo')">
                🔥 YOLO (2.00% Base)
            </button>
            <button id="port-pill-comparison" class="engine-btn" style="font-size:0.85rem; padding:8px 16px; margin-left:auto;" onclick="selectPortfolioView('comparison')">
                📊 4-Way Comparison Matrix
            </button>
        </div>

        <!-- Detail Box for Selected Portfolio -->
        <div id="port-single-view">
            <!-- Dynamic Stats Grid -->
            <div class="stats-grid" style="border:1px solid #30363d; border-radius:8px; margin-bottom:20px; background:#161b22;">
                <div class="stat-card">
                    <div class="stat-label">Net Profit</div>
                    <div id="p-stat-net" class="stat-value val-green">+$14,475.06</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total ROI</div>
                    <div id="p-stat-roi" class="stat-value val-green">+144.8%</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Profit Factor</div>
                    <div id="p-stat-pf" class="stat-value val-blue">2.17</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Max Drawdown</div>
                    <div id="p-stat-dd" class="stat-value val-red">14.2%</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Bulan Profit</div>
                    <div id="p-stat-months" class="stat-value">7 / 11 Bulan</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Rata-rata Untung Harian</div>
                    <div id="p-stat-avg-gain" class="stat-value val-green">+$461.25 / hr</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Rata-rata Rugi Harian</div>
                    <div id="p-stat-avg-loss" class="stat-value val-red">-$202.34 / hr</div>
                </div>
            </div>

            <!-- Description Banner -->
            <div id="p-profile-desc-box" style="background:#161b22; border:1px solid #30363d; border-left:4px solid #1f6feb; border-radius:8px; padding:16px 20px; margin-bottom:20px;">
                <h3 id="p-profile-name" style="color:#58a6ff; font-size:1.1rem; margin-bottom:6px;">⚖️ Sweet Spot (0.75% Base Risk - Rekomendasi)</h3>
                <p id="p-profile-text" style="color:#c9d1d9; font-size:0.85rem; line-height:1.5;">
                    Setting paling seimbang untuk akun real pribadi: menghasilkan profit tinggi <strong>+$14,475.06 (+144.8% ROI)</strong> dengan Max Drawdown moderat di <strong>14.2%</strong>.
                </p>
            </div>

            <!-- Monthly PnL Table for Selected Profile -->
            <div class="table-box" style="margin:0 0 24px 0;">
                <div class="table-header">
                    <span>📅 Rincian Profit / Loss Bulanan (Mei 2025 - Maret 2026)</span>
                    <span id="p-month-summary-badge" class="badge badge-cyan">7 / 11 Bulan Hijau</span>
                </div>
                <div class="table-scroll">
                    <table>
                        <thead>
                            <tr>
                                <th>Bulan</th>
                                <th>Net PnL ($)</th>
                                <th>Persentase Terhadap Akun</th>
                                <th>Status Hasil</th>
                            </tr>
                        </thead>
                        <tbody id="p-monthly-tbody">
                            <!-- Populated dynamically -->
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- 4-Way Side-by-Side Comparison Matrix -->
        <div id="port-matrix-view" style="display:none;">
            <div class="table-box" style="margin:0;">
                <div class="table-header">
                    <span>📊 4-Way Head-to-Head Portfolio Comparison Matrix</span>
                    <span style="font-size:0.75rem; color:#8b949e;">Audit 10.5 Bulan / 300,440 Bar M1 XAUUSD</span>
                </div>
                <div class="table-scroll">
                    <table>
                        <thead>
                            <tr>
                                <th>Parameter / Metrik</th>
                                <th style="color:#3fb950;">🛡️ Prop Firm (0.50%)</th>
                                <th style="color:#58a6ff; background:#1c2433;">⚖️ Sweet Spot (0.75%) ⭐️</th>
                                <th style="color:#d29922;">🚀 Aggressive (1.00%)</th>
                                <th style="color:#f85149;">🔥 YOLO (2.00%)</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td><strong>Base Risk per Trade</strong></td>
                                <td>0.50% ($50)</td>
                                <td style="background:#1c2433; font-weight:700; color:#58a6ff;">0.75% ($75)</td>
                                <td>1.00% ($100)</td>
                                <td style="color:#f85149; font-weight:700;">2.00% ($200)</td>
                            </tr>
                            <tr>
                                <td><strong>Greed Mode (House Money)</strong></td>
                                <td>0.25% ($25)</td>
                                <td style="background:#1c2433;">0.375% ($37.5)</td>
                                <td>0.50% ($50)</td>
                                <td>1.00% ($100)</td>
                            </tr>
                            <tr>
                                <td><strong>Batas Rugi Harian (CB)</strong></td>
                                <td>-1.00% (-$100)</td>
                                <td style="background:#1c2433;">-1.50% (-$150)</td>
                                <td>-2.00% (-$200)</td>
                                <td style="color:#f85149;">-4.00% (-$400)</td>
                            </tr>
                            <tr>
                                <td><strong>Batas Drawdown Bulanan (CB)</strong></td>
                                <td>-3.00% (-$300)</td>
                                <td style="background:#1c2433;">-4.50% (-$450)</td>
                                <td>-6.00% (-$600)</td>
                                <td style="color:#f85149;">-10.00% (-$1,000)</td>
                            </tr>
                            <tr style="border-top:2px solid #30363d;">
                                <td><strong>Total Net Profit ($)</strong></td>
                                <td style="color:#3fb950; font-weight:700;">+$8,865.55</td>
                                <td style="background:#1c2433; color:#58a6ff; font-weight:700; font-size:1rem;">+$14,475.06</td>
                                <td style="color:#d29922; font-weight:700;">+$22,654.04</td>
                                <td style="color:#3fb950; font-weight:700; font-size:1.05rem;">+$45,912.50</td>
                            </tr>
                            <tr>
                                <td><strong>Total ROI (%)</strong></td>
                                <td>+88.7%</td>
                                <td style="background:#1c2433; font-weight:700; color:#58a6ff;">+144.8%</td>
                                <td>+226.5%</td>
                                <td style="font-weight:700; color:#3fb950;">+459.1%</td>
                            </tr>
                            <tr>
                                <td><strong>Profit Factor (PF)</strong></td>
                                <td>2.19</td>
                                <td style="background:#1c2433; font-weight:700;">2.17</td>
                                <td>2.24</td>
                                <td style="font-weight:700;">2.25</td>
                            </tr>
                            <tr>
                                <td><strong>Max Drawdown (%)</strong></td>
                                <td><span class="badge" style="background:#238636;">9.6% (Super Safe)</span></td>
                                <td style="background:#1c2433;"><span class="badge badge-cyan">14.2% (Moderate)</span></td>
                                <td><span class="badge badge-amber">21.5% (High)</span></td>
                                <td><span class="badge" style="background:#da3633;">32.1% (Extreme)</span></td>
                            </tr>
                            <tr>
                                <td><strong>Bulan Hijau / Profit</strong></td>
                                <td>8 / 11 Bulan (72.7%)</td>
                                <td style="background:#1c2433;">7 / 11 Bulan (63.6%)</td>
                                <td>7 / 11 Bulan (63.6%)</td>
                                <td>8 / 11 Bulan (72.7%)</td>
                            </tr>
                            <tr>
                                <td><strong>Rata-rata Untung Harian</strong></td>
                                <td>+$268.41</td>
                                <td style="background:#1c2433; font-weight:700; color:#3fb950;">+$461.25</td>
                                <td>+$738.13</td>
                                <td>+$1,450.20</td>
                            </tr>
                            <tr>
                                <td><strong>Hari Terbaik (Best Day)</strong></td>
                                <td>+$860.66</td>
                                <td style="background:#1c2433;">+$1,732.40</td>
                                <td>+$2,775.67</td>
                                <td style="color:#3fb950; font-weight:700;">+$5,480.00</td>
                            </tr>
                            <tr>
                                <td><strong>Kesesuaian Akun</strong></td>
                                <td>🛡️ Akun Evaluasi Prop Firm (FTMO, MFFU)</td>
                                <td style="background:#1c2433; color:#58a6ff; font-weight:700;">⚖️ Akun Real Pribadi (Rekomendasi Utama)</td>
                                <td>🚀 Akun Compounding Pertumbuhan Cepat</td>
                                <td>🔥 Akun Modal Kecil / Flipping Akun</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
"""

# Check if <body> needs nav_and_modal
if "<!-- === INSTITUTIONAL AUTHENTICATION MODAL === -->" not in content:
    content = content.replace("<body>", "<body>\n" + nav_and_modal)

# Check if pane-portfolios exists
if "id=\"pane-portfolios\"" not in content:
    # Insert pane-portfolios before pane-profiles
    idx_prof = content.find('<div id="pane-profiles"')
    if idx_prof >= 0:
        content = content[:idx_prof] + portfolios_pane_html + "\n" + content[idx_prof:]

# Replace / Update switchMainTab in Javascript
new_js_logic = f"""
        // Portfolio Data embedded from backend simulation
        const ALL_PORTFOLIOS_DATA = {json.dumps(four_profiles)};

        function switchMainTab(tab) {{
            const btnAcc = document.getElementById('nav-btn-accounts');
            const btnPort = document.getElementById('nav-btn-portfolios');
            const btnAna = document.getElementById('nav-btn-analytics');
            const btnPro = document.getElementById('nav-btn-profiles');

            const paneAcc = document.getElementById('pane-accounts');
            const panePort = document.getElementById('pane-portfolios');
            const paneAna = document.getElementById('pane-analytics');
            const panePro = document.getElementById('pane-profiles');

            if (btnAcc) btnAcc.classList.remove('active');
            if (btnPort) btnPort.classList.remove('active');
            if (btnAna) btnAna.classList.remove('active');
            if (btnPro) btnPro.classList.remove('active');

            if (paneAcc) paneAcc.style.display = 'none';
            if (panePort) panePort.style.display = 'none';
            if (paneAna) paneAna.style.display = 'none';
            if (panePro) panePro.style.display = 'none';

            if (tab === 'ACCOUNTS') {{
                if (btnAcc) btnAcc.classList.add('active');
                if (paneAcc) paneAcc.style.display = 'block';
                loadAccountsDashboard();
            }} else if (tab === 'PORTFOLIOS') {{
                if (btnPort) btnPort.classList.add('active');
                if (panePort) panePort.style.display = 'block';
                selectPortfolioView('sweet_spot');
            }} else if (tab === 'ANALYTICS') {{
                if (btnAna) btnAna.classList.add('active');
                if (paneAna) paneAna.style.display = 'block';
                resizeCanvases();
                drawChart();
            }} else if (tab === 'PROFILES') {{
                if (btnPro) btnPro.classList.add('active');
                if (panePro) panePro.style.display = 'block';
            }}
        }}

        function selectPortfolioView(key) {{
            ['prop_firm', 'sweet_spot', 'aggressive', 'yolo', 'comparison'].forEach(k => {{
                const el = document.getElementById('port-pill-' + k);
                if (el) el.classList.remove('selected');
            }});
            const activeEl = document.getElementById('port-pill-' + key);
            if (activeEl) activeEl.classList.add('selected');

            const singleView = document.getElementById('port-single-view');
            const matrixView = document.getElementById('port-matrix-view');

            if (key === 'comparison') {{
                singleView.style.display = 'none';
                matrixView.style.display = 'block';
                return;
            }}

            singleView.style.display = 'block';
            matrixView.style.display = 'none';

            const pData = ALL_PORTFOLIOS_DATA[key];
            if (!pData) return;

            document.getElementById('p-stat-net').textContent = '+$' + parseFloat(pData.net_profit).toLocaleString('en-US', {{minimumFractionDigits:2}});
            document.getElementById('p-stat-roi').textContent = '+' + pData.roi_pct + '%';
            document.getElementById('p-stat-pf').textContent = pData.profit_factor || pData.pf || '2.17';
            document.getElementById('p-stat-dd').textContent = (pData.max_drawdown_pct || pData.max_dd) + '%';
            document.getElementById('p-stat-months').textContent = pData.green_months + ' Bulan';
            document.getElementById('p-stat-avg-gain').textContent = '+$' + (pData.avg_daily_gain || '0.00') + ' / hr';
            document.getElementById('p-stat-avg-loss').textContent = '-$' + Math.abs(pData.avg_daily_loss || 0).toFixed(2) + ' / hr';

            const descBox = document.getElementById('p-profile-desc-box');
            const nameEl = document.getElementById('p-profile-name');
            const textEl = document.getElementById('p-profile-text');

            if (key === 'prop_firm') {{
                descBox.style.borderLeftColor = '#238636';
                nameEl.style.color = '#3fb950';
                nameEl.textContent = '🛡️ Prop Firm (0.50% Base Risk)';
                textEl.innerHTML = 'Fokus utama menjaga Drawdown seketat mungkin agar memenuhi aturan evaluasi prop firm (FTMO, MFFU, FundedNext). Menghasilkan net profit <strong>+$8,865.55 (+88.7% ROI)</strong> dengan Max Drawdown hanya <strong>9.6%</strong>.';
            }} else if (key === 'sweet_spot') {{
                descBox.style.borderLeftColor = '#1f6feb';
                nameEl.style.color = '#58a6ff';
                nameEl.textContent = '⚖️ Sweet Spot (0.75% Base Risk - Rekomendasi Utama)';
                textEl.innerHTML = 'Rasio Return-to-Drawdown terbaik untuk akun real pribadi: melonjakkan profit bersih menjadi <strong>+$14,475.06 (+144.8% ROI)</strong> dengan Max Drawdown yang sangat terkontrol di <strong>14.2%</strong>.';
            }} else if (key === 'aggressive') {{
                descBox.style.borderLeftColor = '#9e6a03';
                nameEl.style.color = '#d29922';
                nameEl.textContent = '🚀 Aggressive (1.00% Base Risk)';
                textEl.innerHTML = 'Pertumbuhan eksponensial dengan compounding equity agresif. Menghasilkan profit bersih <strong>+$22,654.04 (+226.5% ROI)</strong> namun dengan konsekuensi Max Drawdown <strong>21.5%</strong>.';
            }} else if (key === 'yolo') {{
                descBox.style.borderLeftColor = '#da3633';
                nameEl.style.color = '#f85149';
                nameEl.textContent = '🔥 YOLO (2.00% Base Risk - Max Velocity)';
                textEl.innerHTML = 'Akselerasi modal berkecepatan tinggi untuk modal kecil. Mencetak <strong>+$45,912.50 (+459.1% ROI)</strong> dalam 10.5 bulan dengan Max Drawdown <strong>32.1%</strong>.';
            }}

            // Render monthly table
            const tbody = document.getElementById('p-monthly-tbody');
            tbody.innerHTML = '';
            const months = pData.monthly_pnl || {{}};
            Object.keys(months).forEach(m => {{
                const val = months[m];
                const tr = document.createElement('tr');
                const isGreen = val >= 0;
                const sign = isGreen ? '+' : '';
                const col = isGreen ? '#3fb950' : '#f85149';
                const statusBadge = isGreen ? '<span class="badge">PROFIT</span>' : '<span class="badge" style="background:#da3633;">DRAWDOWN</span>';
                tr.innerHTML = `
                    <td><strong>${{m}}</strong></td>
                    <td style="color:${{col}}; font-weight:700;">${{sign}}$${{Math.abs(val).toLocaleString('en-US', {{minimumFractionDigits:2}})}}</td>
                    <td style="color:${{col}};">${{sign}}${{(val / 100).toFixed(1)}}%</td>
                    <td>${{statusBadge}}</td>
                `;
                tbody.appendChild(tr);
            }});
        }}
"""

# Replace switchMainTab logic in content
idx_func = content.find("function switchMainTab(tab)")
if idx_func >= 0:
    idx_end = content.find("async function loadAccountsDashboard()", idx_func)
    content = content[:idx_func] + new_js_logic + "\n        " + content[idx_end:]

with open(INDEX_PATH, "w", encoding="utf-8") as f:
    f.write(content)

print("[Naruto Brain] Successfully updated index.html with 4 Portfolio Profiles Navigation Menu!")
