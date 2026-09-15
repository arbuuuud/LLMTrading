# LLMTrading: Autonomous Institutional-Grade AI Trading System
## Blueprint & Master Architecture Specification

> **Dokumen ini adalah referensi utama sistem (Single Source of Truth / SSOT).**
> Setiap sesi AI (walaupun ter-reset, terkena `/compact`, atau dibuka di environment baru) harus membaca file ini sebagai fondasi konteks, aturan arsitektur, dan standar eksekusi.

---

## 1. Visi & Filosofi Sistem

Sistem ini dirancang dengan mengadopsi prinsip **"Process Over Prediction"** dari kurikulum *The Institutional Protocol* (Matteo Conti - `@patcha015`), dikombinasikan dengan kemampuan penalaran dan adaptasi AI (*Lifelong/Continual Learning*).

### Prinsip Fondasi:
1. **Tidak Bergantung pada Tebakan Arah Candle**: Keunggulan (*edge*) institusional tidak dibangun dari meramal harga masa depan, melainkan dari:
   - Mengidentifikasi ketidakefisienan pasar (*market anomalies/inefficiencies*).
   - Menghitung probabilitas statistik yang terbukti (*positive mathematical expectation*).
   - Manajemen risiko dan alokasi posisi yang dinamis (*dynamic volatility-targeted sizing*).
   - Kecepatan dan kedisiplinan eksekusi bebas bias emosi.
2. **Modularitas & Iterasi Bertahap**:
   Setiap modul strategi, filter, manajemen risiko, dan data ingestion dibangun secara independen. Tidak ada kode monolitik yang rumit tanpa *checkpoint* pengujian.
3. **Long-Life Learning Tanpa Overfitting**:
   AI tidak di-retrain bobot neural-nya secara buta dengan data kemarin (mencegah *catastrophic forgetting*). Pembelajaran berkelanjutan dilakukan melalui:
   - **Strategy Lifecycle Management** (Inkubasi $\to$ Validasi $\to$ Live $\to$ Degradasi/Karantina).
   - **Episodic & Reflective Memory** (Post-Mortem Engine yang mengevaluasi deviasi antara ekspektasi backtest vs realitas live).
   - **Market Regime Alignment** (Memilih strategi yang sesuai dengan musim pasar).

---

## 2. Universe Aset & Analisis Intermarket

Fokus utama sistem adalah komoditas logam mulia dengan korelasi intermarket global:

| Simbol | Peran | Alasan & Karakteristik |
| :--- | :--- | :--- |
| **XAUUSD** (Gold / USD) | **Primary Trading Asset** | Likuiditas raksasa, volatilitas harian tinggi, sensitif terhadap data makro & suku bunga, ideal untuk scalping hingga swing. |
| **XAGUSD** (Silver / USD) | **Intermarket Reference** | Memiliki beta lebih tinggi dari Gold. Digunakan untuk mendeteksi *Gold/Silver Ratio (GSR)*, divergensi momentum (*lead-lag relationship*), dan konfirmasi breakout. |
| **DXY** (US Dollar Index) | **Macro & Liquidity Reference** | *Inverted driver* utama emas. Pelemahan/penguatan DXY mengonfirmasi validitas dorongan tren dan fase likuiditas institusi. |

---

## 3. Horizon Trading & Prioritas Eksekusi

Sistem mendukung tiga horizon waktu dengan prioritas utama pada **Scalping**:

### 3.1. Prioritas 1: Scalping (M1 / Tick-level / Second-level)
- **Karakteristik**: Durasi hold beberapa detik hingga 15 menit. Menangkap inefisiensi sesaat, order flow imbalances, liquidity sweeps, dan reaksi volatilitas pembukaan sesi (London/NY Open).
- **Tantangan Utama**: Biaya transaksi (Spread, Slippage, Komisi) dan *execution latency*.
- **Kunci Sukses**: Backtesting harus menggunakan **Tick Data aktual** dengan simulasi Bid/Ask spread dinamis.

### 3.2. Prioritas 2: Intraday (M5 - M15 - H1)
- **Karakteristik**: Durasi hold 1 jam hingga akhir sesi hari bersangkutan (menghindari biaya swap/overnight risk).
- **Logika**: Daily VWAP, Session High/Low Liquidity Run, Volume Profile Value Area (VAH/VAL/POC), Mean Reversion ke mean harga rata-rata sesi.

### 3.3. Prioritas 3: Swing (H4 - Daily)
- **Karakteristik**: Durasi hold beberapa hari hingga minggu.
- **Logika**: Macro regime trend-following, korelasi makro DXY dan real yields, breakout struktur mingguan, momentum continuation.

---

## 4. Pipeline Data: Integrasi MetaTrader 5 (Wine) ke High-Speed Parquet

Sistem memanfaatkan MetaTrader 5 yang terpasang secara lokal di environment Wine macOS untuk ekstraksi data mentah, namun tidak bergantung pada MT5 untuk logika backtest.

### 4.1. Lokasi MT5 Lokal
- Path instalasi MT5:
  `/Users/alami/mt5prefix/drive_c/Program Files/MetaTrader 5`
- Path Data/History:
  `/Users/alami/mt5prefix/drive_c/Program Files/MetaTrader 5/Bases/`

### 4.2. Arsitektur Data Pipeline
1. **Extractor Service**: Script Python / MQL5 Exporter untuk mengambil:
   - **Tick Data Historis**: `[timestamp_ms, bid, ask, last, volume, flags]`.
   - **M1/M5/H1 OHLCV**: `[timestamp, open, high, low, close, tick_volume, spread]`.
2. **Storage Layer (Apache Parquet + DuckDB / Polars)**:
   - File mentah dikonversi menjadi format Parquet terkompresi (Snappy/ZSTD) yang terpartisi berdasarkan tahun/bulan:
     `data/processed/ticks/XAUUSD/2024/01.parquet`
     `data/processed/bars/XAUUSD/M1/2024.parquet`
   - Parquet memberikan kecepatan pembacaan data hingga 50x - 100x lebih cepat dibanding CSV/SQLite, hemat memori, dan mendukung *zero-copy memory mapping*.

---

## 5. Custom High-Performance Backtest Engine

Membangun mesin backtest kustom (*in-house*) adalah keharusan mutlak karena built-in Strategy Tester MT5 terlalu lambat untuk iterasi AI multi-agent yang membutuhkan ribuan simulasi Monte Carlo.

### 5.1. Spesifikasi Teknis Engine
- **Bahasa**: Python berkekuatan tinggi (NumPy, Polars, Numba JIT) dengan opsi akselerasi C++/Rust jika dibutuhkan.
- **Dua Mode Eksekusi**:
  1. **Vectorized Engine (Fast Screening)**: Menghitung metrik kasar dalam hitungan detik untuk ratusan kombinasi hipotesis strategi.
  2. **Event-Driven Tick Engine (Institutional Precision)**: Mensimulasikan setiap tick harga, antrian order (Limit vs Market), spread aktual, slippage acak berbasis volatilitas, dan latensi eksekusi broker.

### 5.2. Protokol Validasi Institusional (Lesson 8 & 9)
Setiap strategi yang diajukan AI harus melewati filter berjenjang:
1. **In-Sample (IS) vs Out-of-Sample (OOS)**: Data dibagi menjadi 70% Development (IS), 15% Blind Validation (OOS), dan 15% Forward Stress Test.
2. **Walk-Forward Analysis (WFA)**: Menguji ketahanan parameter terhadap perubahan waktu (parameter tidak boleh statis membeku).
3. **Monte Carlo Simulation (Minimal 1.000 Iterasi)**:
   - Mengacak urutan trade (*trade shuffle*).
   - Mengacak slippage & spread secara agresif (*stress test*).
   - Menghitung batas *Maximum Drawdown at 95% Confidence Interval*.
4. **Parameter Stability Test**: Variasi parameter $\pm 10\% - 20\%$ tidak boleh menyebabkan kurva ekuitas runtuh (mendeteksi indikasi *curve fitting*).

---

## 6. Arsitektur Multi-Agent & Skill AI

Sistem dipecah menjadi peran terspesialisasi yang bekerja secara orkestrasi:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            SUPERVISOR WORKFLOW                              │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
         ┌─────────────────────────────┼─────────────────────────────┐
         ▼                             ▼                             ▼
┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│  Market Regime   │         │ Quant Researcher │         │   Risk & Sizing  │
│      Agent       │         │      Agent       │         │      Agent       │
│                  │         │                  │         │  (The Gatekeeper)│
│- Volatility State│         │- Strategy Ideator│         │- Kelly/Vol Sizing│
│- DXY & Silver Rel│         │- AI Code Builder │         │- Max DD & Veto   │
│- Session Liquidity│        │- Modular Syntax  │         │- Spread Guardian │
└────────┬─────────┘         └────────┬─────────┘         └────────┬─────────┘
         │                             │                           │
         └──────────────────────┬──────┴───────────────────────────┘
                                ▼
                     ┌──────────────────────┐
                     │   Validation Agent   │
                     │ (Auditor & Stress)   │
                     │- Tick Backtesting    │
                     │- Monte Carlo Test    │
                     │- Anti-Overfit Filter │
                     └──────────┬───────────┘
                                │ (Pass / Reject)
                                ▼
                     ┌──────────────────────┐
                     │ Strategy Repository  │
                     │ (Active Pool / Inc.) │
                     └──────────┬───────────┘
                                │
                        Live / Paper Execution
                                │
                                ▼
                     ┌──────────────────────┐
                     │ Post-Mortem Learner  │
                     │  (Memory & Reflexion)│
                     │- Trade Deviation Log │
                     │- Rule Evolution      │
                     │- Knowledge Base Sync │
                     └──────────────────────┘
```

### 6.1. Agen 1: Market Regime & Intermarket Agent
- **Fungsi**: Membaca kondisi cuaca pasar sebelum strategi dieksekusi.
- **Skills**:
  - `calculate_regime(atr, adx, hurst_exponent, realized_volatility)`
  - `analyze_intermarket(gold_price, silver_price, dxy_price)`
  - `get_session_phase(utc_time)`: Asia, London Open, London/NY Overlap, NY Close.

### 6.2. Agen 2: Quant Researcher & AI Coder Agent
- **Fungsi**: Merumuskan logika strategi dalam kode modular standar sesuai protokol Lesson 6 & 7.
- **Skills**:
  - `generate_strategy_spec(hypothesis, family)`
  - `compile_strategy_code(entry_rules, exit_rules, risk_params)`
  - `refactor_strategy_modular(code)`

### 6.3. Agen 3: Validation & Monte Carlo Auditor Agent
- **Fungsi**: Menilai kelayakan strategi secara kejam (*hostile testing*). Menjadi tembok penangkal halusinasi.
- **Skills**:
  - `run_vectorized_screening(strategy, data_is)`
  - `run_event_driven_backtest(strategy, data_oos, tick_data)`
  - `run_monte_carlo(trade_list, iterations=1000)`
  - `verify_institutional_criteria(results)`: Sharpe > 1.3, Max DD < 15%, Monte Carlo 95% DD < 20%, Profit Factor > 1.4.

### 6.4. Agen 4: Risk Manager & Circuit Breaker Agent (The Gatekeeper)
- **Fungsi**: Memiliki otoritas tertinggi untuk membatalkan sinyal (*Veto Power*).
- **Skills**:
  - `calculate_position_size(account_equity, stop_loss_pips, asset_volatility)`
  - `enforce_daily_drawdown_limit(current_daily_pnl, max_limit_pct=2.0)`
  - `check_circuit_breaker(spread, news_events, consecutive_losses)`

### 6.5. Agen 5: Lifelong Learner & Post-Mortem Memory Agent
- **Fungsi**: Inti dari pembelajaran jangka panjang.
- **Skills**:
  - `audit_executed_trade(trade_record, expected_distribution)`
  - `categorize_loss(loss_record)`: Slippage execution, False regime, News spike, Bad logic.
  - `update_heuristic_knowledge_base(post_mortem_report)`: Menambahkan instruksi dan batasan pada repositori pengetahuan lokal (`knowledge/`).

---

## 7. Mekanisme Long-Life Learning (Continual Evolution)

Untuk mencegah degradasi performa atau kebingungan AI seiring waktu, alur pembelajaran diatur sebagai berikut:

1. **State Tracking (Strategy Lifecycle)**:
   - `IDEA` $\to$ `VALIDATED` $\to$ `PAPER_INCUBATION` $\to$ `LIVE_ACTIVE` $\to$ `UNDERPERFORMING` $\to$ `RETIRED`.
2. **Karantina Otomatis (*Kill-Switch*)**:
   Jika strategi yang sedang berjalan mengalami *consecutive loss* atau drawdown yang melampaui batas $2\sigma$ dari kurva Monte Carlo-nya, sistem otomatis mencabut strategi tersebut dari *LIVE_ACTIVE* ke *UNDERPERFORMING*.
3. **Reflexion File & Heuristic Playbook**:
   Setiap kegagalan dicatat dalam format markdown terstruktur di folder `knowledge/learnings/`. Agen Researcher wajib membaca arsip kegagalan ini sebelum merancang variasi strategi baru agar kesalahan lama tidak diulang.

---

## 8. Modular Composable Strategy Architecture & Ablation Testing

Untuk memungkinkan pengujian terukur (*measurable*) dan penambahan strategi/filter baru secara berkelanjutan (*continual alpha generation*), setiap strategi dibangun dengan konsep **Composable Lego Bricks**:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        COMPOSABLE STRATEGY ENGINE                      │
├────────────────────────────────────────────────────────────────────────┤
│ 1. HTF CONTEXT LAYER (Filter Arah / Payung Besar)                      │
│    - H1/M15 Point of Interest (POI) & Reversal Key Zones               │
│    - Daily VWAP & Value Area (VAH/VAL/POC)                             │
│    - DXY & Silver SMT Divergence Filter                                │
├────────────────────────────────────────────────────────────────────────┤
│ 2. SETUP LAYER (Inefisiensi Pasar / Apa yang Dicari)                   │
│    - Session High/Low Liquidity Sweep (Asia Sweep pada London Open)    │
│    - RBR / DBD (Rally-Base-Rally / Drop-Base-Drop) Supply & Demand     │
│    - Fair Value Gap (FVG) / Imbalance Pasca BOS/CHoCH                  │
├────────────────────────────────────────────────────────────────────────┤
│ 3. TRIGGER LAYER (Pemicu Masuk Order di M1 / Sub-menit)                │
│    - Candlestick Formations: Engulfing, Hammer/Shooting Star Wick      │
│    - M1 Market Structure Shift (MSS) / Change of Character (CHoCH)     │
│    - Retest Fibonacci Optimal Trade Entry (OTE 0.618 - 0.786)          │
├────────────────────────────────────────────────────────────────────────┤
│ 4. EXIT & RISK LAYER (Manajemen Keluar)                                │
│    - Fixed Risk:Reward (1:2, 1:2.5, 1:3)                               │
│    - Dynamic Trailing Stop berbasis ATR atau M1 Swing Low/High         │
│    - Time-based Cut (Exit jika dalam 15 menit harga tidak berekspansi)  │
└────────────────────────────────────────────────────────────────────────┘
```

### 8.1. Metodologi Pengujian: Ablation Testing & Delta Attribution
Setiap penambahan filter atau parameter baru (misal: penambahan HTF POI atau Candle Engulfing) **WAJIB melalui uji komparasi baseline**:
1. **Run Baseline**: Jalankan strategi dasar (hanya Setup + Exit standar). Catat Winrate, Profit Factor, Sharpe, Max DD.
2. **Add Single Module**: Masukkan satu filter (misal: HTF POI). Jalankan ulang backtest pada dataset yang persis sama.
3. **Measure Delta Attribution**:
   - Jika $\Delta \text{Profit Factor} > 0$ dan $\Delta \text{Max DD} \le 0$, modul **diterima** dan disimpan sebagai varian strategi terverifikasi.
   - Jika penambahan modul justru menurunkan profit factor atau memangkas trade terlalu ekstrem (*over-filtering*), modul **ditolak/dieliminasi**.

### 8.2. Dynamic Ratchet Profit Governor & Monthly Circuit Breaker (Target Bulanan ~20%)
Untuk mencapai target return bulanan tinggi (~15% - 20%) tanpa mempertaruhkan modal dasar, sistem mengadopsi mekanisme **Multi-Tiered Bottoming Profit Lock**:
1. **Awal Hari (Normal Risk: 0.5% / $50)**:
   - Target Take Profit R:R 1:2.5 (+1.25% net profit).
2. **Kondisi 1: Greed Mode dengan Bottoming Lock**:
   - Saat Daily PnL $\ge +1.5\%$ $\to$ **Kunci Floor di +1.0%** (Profit $100 PASTI DI TANGAN).
   - Risiko trade berikutnya dipotong setengahnya menjadi **0.25% ($25 / "House Money")**.
   - Jika PnL naik ke $\ge +2.0\%$ $\to$ Floor naik ke **+1.5%**.
   - Jika PnL naik ke $\ge +2.5\%$ $\to$ Floor naik ke **+2.0%**.
   - **Floor Breach**: Jika pasar berbalik dan profit surut menyentuh Floor $\to$ **DETIK ITU JUGA BOT SHUTDOWN HARI ITU**.
3. **Kondisi 2: 2-Strike Loss Circuit Breaker**:
   - 2 loss berturut-turut di hari yang sama (-0.5% + -0.5% = -1.0%) $\to$ **EMERGENCY SHUTDOWN HARI ITU**. Modal 99.0% aman.
4. **Kondisi 3: Monthly Drawdown Circuit Breaker (-3.0% Cap)**:
   - Jika akumulasi drawdown dalam 1 bulan tertentu menyentuh **-3.0% (-$300)**:
   - Bot otomatis **PAUSE TRADING untuk sisa bulan tersebut** agar modal 97.0% terlindungi dan tidak menghapus akumulasi profit bulan-bulan sebelumnya.
5. **Kondisi 4: Volatility-Adaptive Stop Loss**:
   - Stop Loss dan Take Profit dikalkulasikan dinamis menggunakan **$1.2 \times \text{ATR}_{14}$ M15**, beradaptasi otomatis terhadap musim volatilitas pasar.

---

## 9. Arsitektur Live Execution Bridge (MT5 Wine ke Python Brain)

Sistem memisahkan tanggung jawab antara analisis cerdas dan eksekusi broker:

```
┌────────────────────────────────────────────────────────┐
│                   PYTHON BRAIN (Native macOS)           │
│                                                        │
│  - Multi-Agent Orchestrator (Regime, Strategy, Risk)   │
│  - Real-time SMT Divergence (XAUUSD + XAGUSD + DXY)    │
│  - Long-Life Learning Memory & Reflection              │
└──────────────┬──────────────────────────▲──────────────┘
               │ (1) Send Order           │ (2) Stream Ticks/Positions
               ▼                          │
┌─────────────────────────────────────────┴──────────────┐
│       LIGHTWEIGHT BRIDGE EA (Inside MT5 / Wine)        │
│                                                        │
│  - Expert Advisor: `LLM_Bridge_Executor.mq5`           │
│  - Tugas 1: Streaming Tick live ke Python (ZeroMQ/IPC) │
│  - Tugas 2: Menembak order BUY/SELL ke broker          │
│             dengan Hard Stop Loss & Magic Number       │
│  - Tugas 3: Heartbeat safety (Fail-safe jika koneksi   │
│             Python terputus, jaga posisi terbuka)      │
└────────────────────────────────────────────────────────┘
```

---

## 10. Inventaris Data Terverifikasi

- **Primary Dataset**: `XAUUSD`
- **Volume**: **77.348.506 Ticks** (3.07 GB raw CSV, terkompresi ke ZSTD Parquet).
- **Periode**: **27 Mei 2025 s/d 02 April 2026 (~10.5 Bulan)**.
- **Karakteristik Data**:
  - Millisecond timestamp precision.
  - Bid & Ask aktual di setiap tick (Spread riil sudah termasuk).
  - Teragregasi ke Parquet M1 dan M5 dengan metrik `mean_spread` dan `max_spread`.

---

## 11. Struktur Folder Repositori

```
LLMTrading/
├── BLUEPRINT.md                 <- Master Architecture & Rules (File ini - SSOT)
├── README.md                    <- Quickstart & Overview
├── configs/                     <- Konfigurasi sistem (broker, risk limits, paths)
│   ├── assets.yaml
│   └── risk_limits.yaml
├── data/                        <- Data Storage (Tick & OHLCV)
│   ├── raw/                     <- Ekspor mentah dari MT5
│   ├── processed/               <- Format Parquet terindeks (ticks & bars)
│   └── scripts/                 <- Exporter dari MT5 Wine & Data Pipeline
│       ├── ExportHistoryToCSV.mq5
│       └── mt5_data_pipeline.py
├── engine/                      <- Custom Backtest & Simulation Engine
│   ├── core/                    <- Event-driven engine, types & strategy base
│   ├── metrics/                 <- Sharpe, Sortino, Drawdown, Profit Factor
│   ├── monte_carlo/             <- Monte Carlo 1000+ permutation simulator
│   └── execution/               <- Slippage & spread dynamic models
├── agents/                      <- Multi-Agent Framework
├── strategies/                  <- Library Strategi Teruji (Incubator, Active, Retired)
├── knowledge/                   <- Memory & Heuristics untuk Long-Life Learning
└── tests/                       <- Unit tests untuk memastikan keakuratan engine
```

---

## 12. Roadmap Pengembangan

- [x] **Fase 0**: Riset Metodologi (@patcha015) & Penyusunan Master Blueprint.
- [x] **Fase 1**: MT5 Wine Data Exporter & High-Speed Parquet Pipeline (77.3M Ticks XAUUSD terindeks).
- [x] **Fase 2**: Core Custom Backtest Engine (Event-Driven Tick/Bar, Intrabar SL/TP, Monte Carlo, Slippage/Commissions terverifikasi).
- [x] **Fase 3**: Modular Strategy Framework & Scalping Baseline (`XAUUSD_Liquidity_SMC_Scout` & `XAUUSD_Trend_Pullback_Scalper` dengan Ablation Testing terverifikasi).
- [x] **Fase 4**: Multi-Agent Implementation (Market Regime Detector, Risk Gatekeeper, Strategy Miner, Institutional Auditor).
- [x] **Fase 5**: Post-Mortem Feedback Loop & Knowledge Base Integration (`LifelongLearnerAgent` saving to `knowledge/learnings/`).
- [x] **Fase 6**: Live Bridge Execution (`LLM_Bridge_Executor.mq5` via native MQL5 TCP Socket ke Python Bridge Server `bridge/server.py`).

---

## 13. Backlog Strategis Lanjutan (Next Strategic Milestones)

Daftar 4 opsi prioritas pengembangan selanjutnya yang siap dilanjutkan:

1. **Opsi 1: Observasi Live Forward-Testing di Akun Demo (Priority 1)**
   - Menjalankan `bridge/server.py` dalam mode Paper Trading (`python bridge/server.py`) atau Auto-Trade Live Demo (`python bridge/server.py --live`).
   - Melakukan observasi di sesi aktif (London Open ~14:00 WIB & NY Open ~19:30 WIB).
   - Memantau streaming tick milidetik, pembentukan bar M1, klasifikasi *Market Regime* real-time, dan respon eksekusi order MT5.

2. **Opsi 2: Integrasi Intermarket SMT Divergence (Gold + Silver + DXY)**
   - Menambahkan streaming feed untuk `XAGUSD` (Silver) dan `DXY` (Dollar Index) ke dalam bridge.
   - Mengimplementasikan deteksi **Smart Money Technique (SMT) Divergence**:
     - *Bearish SMT*: XAUUSD membentuk Higher High, tetapi XAGUSD gagal membentuk Higher High $\to$ konfirmasi sweep/fakeout untuk Sell.
     - *Bullish SMT*: XAUUSD membentuk Lower Low, tetapi XAGUSD gagal membentuk Lower Low $\to$ konfirmasi akumulasi untuk Buy.

3. **Opsi 3: Big Data Scaling (Batch Ingest 77,3 Juta Ticks ke Parquet)**
   - Memproses file riil penuh `XAUUSD_202505271036_202604022259.csv` (77.348.506 ticks, 10.5 bulan dari Mei 2025 - April 2026).
   - Menghasilkan dataset Parquet M1 dan M5 berukuran penuh dengan metrik spread per menit.
   - Menjalankan *Walk-Forward Analysis (WFA)* dan uji ketahanan musiman (*seasonal regime shifts*).

4. **Opsi 4: Setup Remote Repository Git (GitHub / GitLab) & Merge Request**
   - Menautkan local git ke remote origin (`git remote add origin <url>`).
   - Melakukan push seluruh branch fitur (`feat/system-blueprint`, `feat/core-backtest-engine`, `feat/modular-strategy`, `feat/multi-agent`, `feat/live-bridge-execution`).
   - Menyiapkan Pull Request / Merge Request ke branch `main`.


