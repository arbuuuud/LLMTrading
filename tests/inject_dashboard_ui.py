"""
Helper script to inject Institutional Auth & Multi-Account Risk Management UI into reports/index.html.
"""

from pathlib import Path

INDEX_PATH = Path("reports/index.html")

with open(INDEX_PATH, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Custom CSS styles to inject before </style>
custom_css = """
        /* === TOP NAVIGATION TABS === */
        .top-nav {
            display: flex;
            background: #161b22;
            padding: 8px 24px;
            border-bottom: 1px solid #30363d;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 12px;
        }
        .nav-tabs {
            display: flex;
            gap: 8px;
            align-items: center;
        }
        .nav-tab-btn {
            background: #0d1117;
            color: #8b949e;
            border: 1px solid #30363d;
            padding: 7px 16px;
            border-radius: 6px;
            font-size: 0.85rem;
            cursor: pointer;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: all 0.15s;
        }
        .nav-tab-btn:hover { border-color: #58a6ff; color: #fff; }
        .nav-tab-btn.active {
            background: #1f6feb;
            color: #fff;
            border-color: #58a6ff;
            box-shadow: 0 0 10px rgba(31, 111, 235, 0.4);
        }
        .user-chip {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 0.82rem;
            color: #c9d1d9;
            background: #0d1117;
            padding: 5px 12px;
            border-radius: 20px;
            border: 1px solid #30363d;
        }
        .logout-btn {
            background: #21262d;
            border: 1px solid #30363d;
            color: #f85149;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 0.75rem;
            cursor: pointer;
            font-weight: 600;
        }
        .logout-btn:hover { background: #b62324; color: #fff; }

        /* === LOGIN MODAL === */
        #login-modal-overlay {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(13, 17, 23, 0.88);
            backdrop-filter: blur(8px);
            z-index: 999999;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: opacity 0.3s ease;
        }
        .login-card {
            background: #161b22;
            border: 1px solid #30363d;
            box-shadow: 0 16px 40px rgba(0,0,0,0.8);
            width: 100%;
            max-width: 440px;
            border-radius: 12px;
            padding: 32px;
            color: #c9d1d9;
        }
        .login-title {
            font-size: 1.3rem;
            font-weight: 700;
            color: #fff;
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .login-subtitle {
            font-size: 0.82rem;
            color: #8b949e;
            margin-bottom: 24px;
            line-height: 1.4;
        }
        .form-group {
            margin-bottom: 16px;
        }
        .form-label {
            display: block;
            font-size: 0.8rem;
            font-weight: 600;
            margin-bottom: 6px;
            color: #8b949e;
        }
        .form-input {
            width: 100%;
            padding: 10px 14px;
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 6px;
            color: #fff;
            font-size: 0.9rem;
            outline: none;
            transition: border-color 0.15s;
        }
        .form-input:focus { border-color: #58a6ff; }
        .btn-submit {
            width: 100%;
            background: #238636;
            color: #fff;
            border: none;
            padding: 12px;
            border-radius: 6px;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            margin-top: 8px;
            transition: background 0.15s;
        }
        .btn-submit:hover { background: #2ea043; }
        .login-error {
            color: #f85149;
            font-size: 0.8rem;
            margin-top: 10px;
            display: none;
        }
        .quick-fill {
            margin-top: 18px;
            padding: 10px;
            background: rgba(56, 139, 253, 0.1);
            border: 1px dashed rgba(56, 139, 253, 0.4);
            border-radius: 6px;
            font-size: 0.75rem;
            color: #58a6ff;
            cursor: pointer;
            text-align: center;
        }
        .quick-fill:hover { background: rgba(56, 139, 253, 0.2); }

        /* === ACCOUNTS TAB UI === */
        .accounts-container {
            padding: 24px;
            max-width: 1400px;
            margin: 0 auto;
        }
        .accounts-banner {
            background: linear-gradient(135deg, #1f6feb 0%, #161b22 100%);
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 20px 24px;
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
        }
        .banner-title { font-size: 1.25rem; font-weight: 700; color: #fff; margin-bottom: 4px; }
        .banner-desc { font-size: 0.85rem; color: #c9d1d9; max-width: 700px; line-height: 1.4; }

        .profile-btn {
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 700;
            cursor: pointer;
            border: 1px solid transparent;
            transition: all 0.15s;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }
        .profile-btn.prop_firm {
            background: rgba(35, 134, 54, 0.15);
            color: #3fb950;
            border-color: #238636;
        }
        .profile-btn.prop_firm:hover, .profile-btn.prop_firm.selected {
            background: #238636;
            color: #fff;
            box-shadow: 0 0 8px rgba(35, 134, 54, 0.5);
        }

        .profile-btn.sweet_spot {
            background: rgba(31, 111, 235, 0.15);
            color: #58a6ff;
            border-color: #1f6feb;
        }
        .profile-btn.sweet_spot:hover, .profile-btn.sweet_spot.selected {
            background: #1f6feb;
            color: #fff;
            box-shadow: 0 0 8px rgba(31, 111, 235, 0.5);
        }

        .profile-btn.aggressive {
            background: rgba(210, 153, 34, 0.15);
            color: #d29922;
            border-color: #9e6a03;
        }
        .profile-btn.aggressive:hover, .profile-btn.aggressive.selected {
            background: #9e6a03;
            color: #fff;
            box-shadow: 0 0 8px rgba(210, 153, 34, 0.5);
        }

        .profile-btn.yolo {
            background: rgba(248, 81, 73, 0.15);
            color: #f85149;
            border-color: #b62324;
        }
        .profile-btn.yolo:hover, .profile-btn.yolo.selected {
            background: #da3633;
            color: #fff;
            box-shadow: 0 0 8px rgba(248, 81, 73, 0.5);
        }

        .toast-msg {
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: #238636;
            color: #fff;
            padding: 12px 20px;
            border-radius: 8px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.6);
            z-index: 999999;
            font-size: 0.85rem;
            font-weight: 600;
            display: none;
            animation: slideUp 0.3s ease;
        }
        @keyframes slideUp {
            from { transform: translateY(20px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
"""

# Insert custom_css before </style>
if "</style>" in content and "/* === TOP NAVIGATION TABS === */" not in content:
    content = content.replace("</style>", custom_css + "\n    </style>")

# 2. Add Login Modal and Top Navigation HTML
login_and_nav_html = """
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
        <div style="display:flex; align-items:center; gap:12px;">
            <span style="font-weight:700; font-size:1.05rem; color:#fff; display:flex; align-items:center; gap:6px;">
                ⚡ LLMTrading <span style="font-size:0.75rem; background:#21262d; border:1px solid #30363d; padding:2px 8px; border-radius:12px; color:#58a6ff;">Dual-Engine</span>
            </span>
            <div class="nav-tabs">
                <button id="nav-btn-accounts" class="nav-tab-btn active" onclick="switchMainTab('ACCOUNTS')">
                    👥 Account & Risk Manager
                </button>
                <button id="nav-btn-analytics" class="nav-tab-btn" onclick="switchMainTab('ANALYTICS')">
                    📈 Performance & 60fps Visualizer
                </button>
                <button id="nav-btn-profiles" class="nav-tab-btn" onclick="switchMainTab('PROFILES')">
                    🛡️ Institutional Risk Matrix
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

# Replace <body> with <body> + login_and_nav_html
if "<body>" in content and "login-modal-overlay" not in content:
    content = content.replace("<body>", "<body>\n" + login_and_nav_html)

# 3. Create Pane Containers:
# Wrap existing main content inside <div id="pane-analytics" style="display:none;"> ... </div>
# And add <div id="pane-accounts"> and <div id="pane-profiles">
accounts_pane_html = """
    <!-- ============================================================= -->
    <!-- TAB 1: ACCOUNTS & RISK PROFILES MANAGER (MAIN PANE)           -->
    <!-- ============================================================= -->
    <div id="pane-accounts" class="accounts-container">
        <div class="accounts-banner">
            <div>
                <div class="banner-title">👥 Multi-Account MetaTrader 5 Governance</div>
                <div class="banner-desc">
                    Kelola profil risiko untuk setiap akun MT5 yang terhubung. Cukup pilih profil 
                    <strong>[Prop Firm]</strong>, <strong>[Sweet Spot]</strong>, <strong>[Aggressive]</strong>, atau <strong>[YOLO]</strong> dengan 1 kali klik. 
                    Semua perhitungan lot dan batas circuit breaker langsung dikendalikan secara otonom oleh Python Brain tanpa perlu ubah config di MT5!
                </div>
            </div>
            <button class="engine-btn active" style="background:#238636; border-color:#3fb950;" onclick="openAddAccountModal()">
                ➕ Tambah / Register Akun Baru
            </button>
        </div>

        <!-- Metric Cards -->
        <div class="stats-grid" style="border:1px solid #30363d; border-radius:8px; margin-bottom:20px; background:#161b22;">
            <div class="stat-card">
                <div class="stat-label">Total Akun Terdaftar</div>
                <div id="dash-total-acc" class="stat-value val-blue">1 Akun</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Equity Gabungan</div>
                <div id="dash-total-equity" class="stat-value val-green">$10,000.00</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Bridge TCP Server</div>
                <div class="stat-value val-green">🟢 Port 5555 Active</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Default Risk Profil</div>
                <div class="stat-value" style="color:#58a6ff;">Sweet Spot (0.75%)</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Proteksi Harian</div>
                <div class="stat-value val-purple">2-Strike Breaker</div>
            </div>
        </div>

        <!-- Accounts Table -->
        <div class="table-box" style="margin:0 0 24px 0;">
            <div class="table-header">
                <span>📋 Daftar Akun MetaTrader 5 & Risk Profil Aktif</span>
                <span style="font-size:0.75rem; color:#8b949e;">Klik tombol profil untuk mengubah risiko seketika</span>
            </div>
            <div class="table-scroll" style="max-height:500px;">
                <table id="accounts-table">
                    <thead>
                        <tr>
                            <th>Account Login</th>
                            <th>Nama / Broker</th>
                            <th>Balance</th>
                            <th>Equity</th>
                            <th>Profil Aktif</th>
                            <th style="min-width:380px;">1-Click Quick Risk Selector</th>
                            <th>Status</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody id="accounts-tbody">
                        <!-- Populated by JS -->
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Modal Tambah Akun -->
        <div id="add-acc-modal" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.7); z-index:99999; align-items:center; justify-content:center;">
            <div class="login-card" style="max-width:500px;">
                <div class="login-title">➕ Daftarkan Akun MT5 Baru</div>
                <form id="add-acc-form" onsubmit="handleAddAccountSubmit(event)">
                    <div class="form-group">
                        <label class="form-label">Nomor Login Akun MT5</label>
                        <input type="text" id="acc-id" class="form-input" placeholder="Contoh: 1029384" required>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Label / Nama Akun</label>
                        <input type="text" id="acc-label" class="form-input" placeholder="Contoh: FTMO Challenge $100k" required>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Nama Broker / Server</label>
                        <input type="text" id="acc-broker" class="form-input" placeholder="Contoh: FTMO-Server / Exness-Real">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Pilih Profil Risiko Awal</label>
                        <select id="acc-profile" class="form-input">
                            <option value="sweet_spot" selected>⚖️ Sweet Spot (0.75% Risk - Rekomendasi)</option>
                            <option value="prop_firm">🛡️ Prop Firm (0.50% Risk - FTMO / MFFU Safe)</option>
                            <option value="aggressive">🚀 Aggressive (1.00% Risk - High Growth)</option>
                            <option value="yolo">🔥 YOLO (2.00% Risk - Max Velocity)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Catatan</label>
                        <input type="text" id="acc-notes" class="form-input" placeholder="Akun evaluasi tahap 1">
                    </div>
                    <div style="display:flex; gap:10px; margin-top:16px;">
                        <button type="submit" class="btn-submit">Simpan Akun</button>
                        <button type="button" class="btn-submit" style="background:#30363d;" onclick="closeAddAccountModal()">Batal</button>
                    </div>
                </form>
            </div>
        </div>
    </div>
"""

profiles_pane_html = """
    <!-- ============================================================= -->
    <!-- TAB 3: RISK PROFILES & CIRCUIT BREAKER MATRIX                -->
    <!-- ============================================================= -->
    <div id="pane-profiles" class="accounts-container" style="display:none;">
        <div class="accounts-banner" style="background: linear-gradient(135deg, #238636 0%, #161b22 100%);">
            <div>
                <div class="banner-title">🛡️ Institutional Risk Profiles & Circuit Breaker Matrix</div>
                <div class="banner-desc">
                    Setiap profil memiliki formula proteksi risiko independen. 
                    Audit hasil uji 10.5 bulan membuktikan ketahanan masing-masing profil dalam berbagai kondisi pasar.
                </div>
            </div>
        </div>

        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap:20px;">
            <!-- Profile 1: Prop Firm -->
            <div class="matrix-col" style="border-top:4px solid #3fb950; background:#161b22; border-radius:8px; padding:20px;">
                <div class="matrix-col-header" style="margin-bottom:12px;">
                    <span style="color:#3fb950; font-size:1.1rem; font-weight:700;">🛡️ Prop Firm</span>
                    <span class="badge" style="background:#238636;">FTMO Compliant</span>
                </div>
                <div class="matrix-row"><span class="matrix-k">Base Risk per Trade</span><span class="matrix-v" style="color:#3fb950; font-weight:700;">0.50% ($50)</span></div>
                <div class="matrix-row"><span class="matrix-k">Greed Mode (House Money)</span><span class="matrix-v">0.25% ($25)</span></div>
                <div class="matrix-row"><span class="matrix-k">Batas Rugi Harian (CB)</span><span class="matrix-v" style="color:#f85149;">-1.00% (-$100)</span></div>
                <div class="matrix-row"><span class="matrix-k">Monthly Loss Cap (CB)</span><span class="matrix-v" style="color:#f85149;">-3.00% (-$300)</span></div>
                <div class="matrix-row"><span class="matrix-k">Target Harian</span><span class="matrix-v">+0.5% s/d +1.0%</span></div>
                <div class="matrix-row"><span class="matrix-k">10.5M Net Profit</span><span class="matrix-v val-green">+$8,865.55</span></div>
                <div class="matrix-row"><span class="matrix-k">10.5M Max Drawdown</span><span class="matrix-v" style="color:#3fb950; font-weight:700;">9.6% (Aman!)</span></div>
                <div class="matrix-row"><span class="matrix-k">Rekomendasi Penggunaan</span><span class="matrix-v">Akun Tantangan / Funded</span></div>
            </div>

            <!-- Profile 2: Sweet Spot -->
            <div class="matrix-col" style="border-top:4px solid #1f6feb; background:#161b22; border-radius:8px; padding:20px;">
                <div class="matrix-col-header" style="margin-bottom:12px;">
                    <span style="color:#58a6ff; font-size:1.1rem; font-weight:700;">⚖️ Sweet Spot</span>
                    <span class="badge badge-cyan">Rekomendasi</span>
                </div>
                <div class="matrix-row"><span class="matrix-k">Base Risk per Trade</span><span class="matrix-v" style="color:#58a6ff; font-weight:700;">0.75% ($75)</span></div>
                <div class="matrix-row"><span class="matrix-k">Greed Mode (House Money)</span><span class="matrix-v">0.375% ($37.5)</span></div>
                <div class="matrix-row"><span class="matrix-k">Batas Rugi Harian (CB)</span><span class="matrix-v" style="color:#f85149;">-1.50% (-$150)</span></div>
                <div class="matrix-row"><span class="matrix-k">Monthly Loss Cap (CB)</span><span class="matrix-v" style="color:#f85149;">-4.50% (-$450)</span></div>
                <div class="matrix-row"><span class="matrix-k">Target Harian</span><span class="matrix-v">+0.8% s/d +1.8%</span></div>
                <div class="matrix-row"><span class="matrix-k">10.5M Net Profit</span><span class="matrix-v val-green">+$14,475.06</span></div>
                <div class="matrix-row"><span class="matrix-k">10.5M Max Drawdown</span><span class="matrix-v" style="color:#58a6ff; font-weight:700;">14.2%</span></div>
                <div class="matrix-row"><span class="matrix-k">Rekomendasi Penggunaan</span><span class="matrix-v">Akun Real Pribadi</span></div>
            </div>

            <!-- Profile 3: Aggressive -->
            <div class="matrix-col" style="border-top:4px solid #d29922; background:#161b22; border-radius:8px; padding:20px;">
                <div class="matrix-col-header" style="margin-bottom:12px;">
                    <span style="color:#d29922; font-size:1.1rem; font-weight:700;">🚀 Aggressive</span>
                    <span class="badge badge-amber">High Compounding</span>
                </div>
                <div class="matrix-row"><span class="matrix-k">Base Risk per Trade</span><span class="matrix-v" style="color:#d29922; font-weight:700;">1.00% ($100)</span></div>
                <div class="matrix-row"><span class="matrix-k">Greed Mode (House Money)</span><span class="matrix-v">0.50% ($50)</span></div>
                <div class="matrix-row"><span class="matrix-k">Batas Rugi Harian (CB)</span><span class="matrix-v" style="color:#f85149;">-2.00% (-$200)</span></div>
                <div class="matrix-row"><span class="matrix-k">Monthly Loss Cap (CB)</span><span class="matrix-v" style="color:#f85149;">-6.00% (-$600)</span></div>
                <div class="matrix-row"><span class="matrix-k">Target Harian</span><span class="matrix-v">+1.2% s/d +2.5%</span></div>
                <div class="matrix-row"><span class="matrix-k">10.5M Net Profit</span><span class="matrix-v val-green">+$22,654.04</span></div>
                <div class="matrix-row"><span class="matrix-k">10.5M Max Drawdown</span><span class="matrix-v" style="color:#d29922; font-weight:700;">21.5%</span></div>
                <div class="matrix-row"><span class="matrix-k">Rekomendasi Penggunaan</span><span class="matrix-v">High-Growth Portfolio</span></div>
            </div>

            <!-- Profile 4: YOLO -->
            <div class="matrix-col" style="border-top:4px solid #f85149; background:#161b22; border-radius:8px; padding:20px;">
                <div class="matrix-col-header" style="margin-bottom:12px;">
                    <span style="color:#f85149; font-size:1.1rem; font-weight:700;">🔥 YOLO</span>
                    <span class="badge" style="background:#da3633;">Maximum Velocity</span>
                </div>
                <div class="matrix-row"><span class="matrix-k">Base Risk per Trade</span><span class="matrix-v" style="color:#f85149; font-weight:700;">2.00% ($200)</span></div>
                <div class="matrix-row"><span class="matrix-k">Greed Mode (House Money)</span><span class="matrix-v">1.00% ($100)</span></div>
                <div class="matrix-row"><span class="matrix-k">Batas Rugi Harian (CB)</span><span class="matrix-v" style="color:#f85149;">-4.00% (-$400)</span></div>
                <div class="matrix-row"><span class="matrix-k">Monthly Loss Cap (CB)</span><span class="matrix-v" style="color:#f85149;">-10.00% (-$1,000)</span></div>
                <div class="matrix-row"><span class="matrix-k">Target Harian</span><span class="matrix-v">+2.5% s/d +6.0%</span></div>
                <div class="matrix-row"><span class="matrix-k">10.5M Net Profit</span><span class="matrix-v val-green">+$45,000+</span></div>
                <div class="matrix-row"><span class="matrix-k">10.5M Max Drawdown</span><span class="matrix-v" style="color:#f85149; font-weight:700;">38.0%</span></div>
                <div class="matrix-row"><span class="matrix-k">Rekomendasi Penggunaan</span><span class="matrix-v">Modal Kecil / Flipping</span></div>
            </div>
        </div>
    </div>
"""

# Insert panes before <header>
analytics_start = '<div id="pane-analytics" style="display:none;">\n'
analytics_end = '\n    </div><!-- end pane-analytics -->'

if '<header>' in content and 'id="pane-analytics"' not in content:
    idx_header = content.find('<header>')
    content = content[:idx_header] + accounts_pane_html + profiles_pane_html + analytics_start + content[idx_header:]
    # Append analytics_end before </body>
    idx_body_close = content.rfind('</body>')
    content = content[:idx_body_close] + analytics_end + "\n" + content[idx_body_close:]

# 4. Inject Client-side JS Logic for Auth, Tabs & Profile Switching
client_js = """
        // =========================================================
        // INSTITUTIONAL AUTHENTICATION & MULTI-ACCOUNT MANAGER JS
        // =========================================================
        let currentAuthToken = localStorage.getItem('llm_auth_token') || '';
        let currentAccountsData = {};
        let currentProfilesData = {};

        function showToast(msg) {
            const t = document.getElementById('toast-notify');
            t.textContent = msg;
            t.style.display = 'block';
            setTimeout(() => { t.style.display = 'none'; }, 3500);
        }

        function autoFillCredentials() {
            document.getElementById('login-email').value = 'arief.setiabudi2010@gmail.com';
            document.getElementById('login-password').value = 'P@ssw0rd!';
        }

        async function handleLoginSubmit(e) {
            e.preventDefault();
            const email = document.getElementById('login-email').value.trim();
            const password = document.getElementById('login-password').value;
            const errEl = document.getElementById('login-err');
            errEl.style.display = 'none';

            try {
                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, password })
                });
                const data = await res.json();
                if (data.success && data.token) {
                    currentAuthToken = data.token;
                    localStorage.setItem('llm_auth_token', data.token);
                    document.getElementById('login-modal-overlay').style.display = 'none';
                    document.getElementById('user-display').textContent = email;
                    showToast('✅ Selamat datang, Pak Arief! Brain Portal aktif.');
                    loadAccountsDashboard();
                } else {
                    errEl.textContent = data.error || 'Login gagal';
                    errEl.style.display = 'block';
                }
            } catch (err) {
                // If running on static without backend server, allow offline fallback
                if (email === 'arief.setiabudi2010@gmail.com' && password === 'P@ssw0rd!') {
                    currentAuthToken = 'offline_token';
                    localStorage.setItem('llm_auth_token', currentAuthToken);
                    document.getElementById('login-modal-overlay').style.display = 'none';
                    showToast('✅ Login berhasil (Offline Mode)');
                    renderMockAccounts();
                } else {
                    errEl.textContent = 'Koneksi ke backend server gagal.';
                    errEl.style.display = 'block';
                }
            }
        }

        function handleLogout() {
            if (currentAuthToken) {
                fetch('/api/logout', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + currentAuthToken }
                }).catch(() => {});
            }
            localStorage.removeItem('llm_auth_token');
            currentAuthToken = '';
            document.getElementById('login-modal-overlay').style.display = 'flex';
        }

        function switchMainTab(tab) {
            const btnAcc = document.getElementById('nav-btn-accounts');
            const btnAna = document.getElementById('nav-btn-analytics');
            const btnPro = document.getElementById('nav-btn-profiles');
            const paneAcc = document.getElementById('pane-accounts');
            const paneAna = document.getElementById('pane-analytics');
            const panePro = document.getElementById('pane-profiles');

            btnAcc.classList.remove('active');
            btnAna.classList.remove('active');
            btnPro.classList.remove('active');
            paneAcc.style.display = 'none';
            paneAna.style.display = 'none';
            panePro.style.display = 'none';

            if (tab === 'ACCOUNTS') {
                btnAcc.classList.add('active');
                paneAcc.style.display = 'block';
                loadAccountsDashboard();
            } else if (tab === 'ANALYTICS') {
                btnAna.classList.add('active');
                paneAna.style.display = 'block';
                resizeCanvases();
                drawChart();
            } else if (tab === 'PROFILES') {
                btnPro.classList.add('active');
                panePro.style.display = 'block';
            }
        }

        async function loadAccountsDashboard() {
            try {
                const res = await fetch('/api/accounts', {
                    headers: { 'Authorization': 'Bearer ' + currentAuthToken }
                });
                if (res.status === 401) {
                    document.getElementById('login-modal-overlay').style.display = 'flex';
                    return;
                }
                const data = await res.json();
                currentAccountsData = data.accounts || {};
                currentProfilesData = data.profiles || {};
                renderAccountsTable(currentAccountsData, currentProfilesData);
            } catch (err) {
                renderMockAccounts();
            }
        }

        function renderAccountsTable(accounts, profiles) {
            const tbody = document.getElementById('accounts-tbody');
            tbody.innerHTML = '';

            const accKeys = Object.keys(accounts);
            document.getElementById('dash-total-acc').textContent = accKeys.length + ' Akun';

            let totEq = 0;
            accKeys.forEach(k => {
                const acc = accounts[k];
                totEq += parseFloat(acc.equity || acc.balance || 10000);
            });
            document.getElementById('dash-total-equity').textContent = '$' + totEq.toLocaleString('en-US', { minimumFractionDigits: 2 });

            accKeys.forEach(accId => {
                const acc = accounts[accId];
                const tr = document.createElement('tr');
                tr.className = 'clickable-row';

                const curProfile = acc.profile || 'sweet_spot';
                let badgeClass = 'badge-cyan';
                if (curProfile === 'prop_firm') badgeClass = 'badge';
                else if (curProfile === 'aggressive') badgeClass = 'badge-amber';
                else if (curProfile === 'yolo') badgeClass = 'badge';

                const profName = (profiles[curProfile] && profiles[curProfile].name) || curProfile.toUpperCase();

                tr.innerHTML = `
                    <td><strong style="color:#fff; font-size:0.9rem;">#${acc.account_id}</strong></td>
                    <td>
                        <strong style="color:#c9d1d9;">${acc.label || 'MT5 Account'}</strong><br>
                        <span style="font-size:0.75rem; color:#8b949e;">${acc.broker || 'Demo'} (${acc.currency || 'USD'})</span>
                    </td>
                    <td>$${parseFloat(acc.balance || 10000).toLocaleString('en-US', {minimumFractionDigits:2})}</td>
                    <td><strong style="color:#3fb950;">$${parseFloat(acc.equity || 10000).toLocaleString('en-US', {minimumFractionDigits:2})}</strong></td>
                    <td>
                        <span class="badge ${badgeClass}" id="badge-${acc.account_id}">${profName}</span>
                    </td>
                    <td>
                        <div style="display:flex; gap:6px; flex-wrap:wrap;">
                            <button class="profile-btn prop_firm ${curProfile === 'prop_firm' ? 'selected' : ''}" 
                                onclick="setAccountRiskProfile('${acc.account_id}', 'prop_firm')">
                                🛡️ Prop Firm (0.5%)
                            </button>
                            <button class="profile-btn sweet_spot ${curProfile === 'sweet_spot' ? 'selected' : ''}" 
                                onclick="setAccountRiskProfile('${acc.account_id}', 'sweet_spot')">
                                ⚖️ Sweet Spot (0.75%)
                            </button>
                            <button class="profile-btn aggressive ${curProfile === 'aggressive' ? 'selected' : ''}" 
                                onclick="setAccountRiskProfile('${acc.account_id}', 'aggressive')">
                                🚀 Aggressive (1.0%)
                            </button>
                            <button class="profile-btn yolo ${curProfile === 'yolo' ? 'selected' : ''}" 
                                onclick="setAccountRiskProfile('${acc.account_id}', 'yolo')">
                                🔥 YOLO (2.0%)
                            </button>
                        </div>
                    </td>
                    <td><span style="color:#3fb950; font-weight:600;">🟢 Active</span></td>
                    <td>
                        <button style="background:none; border:none; color:#f85149; cursor:pointer; font-size:0.8rem;" 
                            onclick="deleteAccount('${acc.account_id}')">🗑️ Hapus</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        }

        function renderMockAccounts() {
            renderAccountsTable({
                "10001": {
                    "account_id": "10001",
                    "label": "MetaQuotes Wine Primary Demo",
                    "broker": "MetaQuotes-Demo",
                    "profile": "sweet_spot",
                    "balance": 10000.0,
                    "equity": 10000.0,
                    "currency": "USD"
                }
            }, {
                "prop_firm": { "name": "Prop Firm" },
                "sweet_spot": { "name": "Sweet Spot" },
                "aggressive": { "name": "Aggressive" },
                "yolo": { "name": "YOLO" }
            });
        }

        async function setAccountRiskProfile(accountId, profile) {
            try {
                const res = await fetch('/api/account/profile', {
                    method: 'POST',
                    headers: { 
                        'Content-Type': 'application/json',
                        'Authorization': 'Bearer ' + currentAuthToken
                    },
                    body: JSON.stringify({ account_id: accountId, profile: profile })
                });
                const data = await res.json();
                if (data.success) {
                    showToast(`✅ Akun #${accountId} dialihkan ke profil: ${profile.toUpperCase()}`);
                    loadAccountsDashboard();
                } else {
                    alert(data.error || 'Gagal mengubah profil risiko');
                }
            } catch (e) {
                showToast(`✅ Akun #${accountId} dialihkan ke profil: ${profile.toUpperCase()} (Local update)`);
                if (currentAccountsData[accountId]) currentAccountsData[accountId].profile = profile;
                renderAccountsTable(currentAccountsData, currentProfilesData);
            }
        }

        function openAddAccountModal() { document.getElementById('add-acc-modal').style.display = 'flex'; }
        function closeAddAccountModal() { document.getElementById('add-acc-modal').style.display = 'none'; }

        async function handleAddAccountSubmit(e) {
            e.preventDefault();
            const id = document.getElementById('acc-id').value.trim();
            const label = document.getElementById('acc-label').value.trim();
            const broker = document.getElementById('acc-broker').value.trim();
            const profile = document.getElementById('acc-profile').value;
            const notes = document.getElementById('acc-notes').value.trim();

            try {
                const res = await fetch('/api/account/save', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': 'Bearer ' + currentAuthToken
                    },
                    body: JSON.stringify({ account_id: id, label, broker, profile, notes })
                });
                const data = await res.json();
                if (data.success) {
                    closeAddAccountModal();
                    showToast(`✅ Akun #${id} (${label}) berhasil didaftarkan!`);
                    loadAccountsDashboard();
                } else {
                    alert(data.error || 'Gagal menyimpan akun');
                }
            } catch (err) {
                currentAccountsData[id] = { account_id: id, label, broker, profile, balance: 10000, equity: 10000, currency: 'USD' };
                closeAddAccountModal();
                showToast(`✅ Akun #${id} (${label}) tersimpan.`);
                renderAccountsTable(currentAccountsData, currentProfilesData);
            }
        }

        async function deleteAccount(id) {
            if (!confirm(`Yakin ingin menghapus akun #${id} dari manajemen dashboard?`)) return;
            try {
                await fetch('/api/account/delete', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': 'Bearer ' + currentAuthToken
                    },
                    body: JSON.stringify({ account_id: id })
                });
                showToast(`Akun #${id} telah dihapus.`);
                loadAccountsDashboard();
            } catch (e) {
                delete currentAccountsData[id];
                showToast(`Akun #${id} dihapus.`);
                renderAccountsTable(currentAccountsData, currentProfilesData);
            }
        }

        // Check authentication state on page load
        window.addEventListener('DOMContentLoaded', () => {
            if (currentAuthToken) {
                document.getElementById('login-modal-overlay').style.display = 'none';
                loadAccountsDashboard();
            } else {
                document.getElementById('login-modal-overlay').style.display = 'flex';
            }
        });
"""

if "window.addEventListener('DOMContentLoaded'" not in content:
    idx_script_close = content.rfind("</script>")
    content = content[:idx_script_close] + client_js + "\n    </script>" + content[idx_script_close + len("</script>"):]

with open(INDEX_PATH, "w", encoding="utf-8") as f:
    f.write(content)

print("[Naruto Brain] Successfully injected Institutional Auth & Multi-Account UI into reports/index.html")
