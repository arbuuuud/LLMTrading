# Panduan Operasional & Eksekusi Sistem (Runbook)
## LLMTrading: Autonomous Institutional AI Trading System

Dokumen ini berisi panduan langkah demi langkah cara menjalankan seluruh modul dalam sistem **LLMTrading**: mulai dari pipeline data, backtesting, pengujian ablasi, framework multi-agent, hingga eksekusi live bridge ke MetaTrader 5.

---

## 📋 Daftar Isi
1. [Prasyarat & Virtual Environment](#1-prasyarat--virtual-environment)
2. [Data Pipeline (Ekspor & Resample Parquet)](#2-data-pipeline)
3. [Menjalankan Backtest Engine & Strategi](#3-menjalankan-backtest-engine--strategi)
4. [Menjalankan Ablation Study (Uji Komparasi Balok Lego)](#4-menjalankan-ablation-study)
5. [Menjalankan Multi-Agent AI Suite](#5-menjalankan-multi-agent-ai-suite)
6. [Menjalankan Live Bridge ke MetaTrader 5 (Paper & Live)](#6-menjalankan-live-bridge-ke-metatrader-5)
7. [Troubleshooting & FAQ](#7-troubleshooting--faq)

---

## 1. Prasyarat & Virtual Environment

Sistem menggunakan Python virtual environment lokal (`.venv`). Pastikan virtual environment aktif sebelum menjalankan script apa pun:

```bash
# Masuk ke direktori repositori
cd /Users/alami/Documents/1.work/Rekayasa/GIT/LLMTrading

# Aktifkan virtual environment
source .venv/bin/activate
```

Jika dependencies belum terpasang atau ada update:
```bash
pip install -r requirements.txt
```

---

## 2. Data Pipeline

Pipeline data bertugas mengonversi tick mentah milidetik dari MT5 menjadi format Apache Parquet terkompresi (ZSTD) dan meresample menjadi candle M1/M5 dengan kalkulasi spread riil.

### Langkah Ingest Data Baru dari MT5:
1. Jalankan script MQL5 `ExportHistoryToCSV.mq5` di MetaTrader 5 untuk mengekspor tick ke CSV.
2. Jalankan konversi high-speed ke Parquet:
```bash
.venv/bin/python data/scripts/mt5_data_pipeline.py
```
Data hasil olahan akan tersimpan di:
- `data/processed/ticks/XAUUSD/` (Tick Parquet)
- `data/processed/bars/XAUUSD/M1/XAUUSD_M1.parquet` (M1 Bars lengkap dengan `mean_spread` dan `max_spread`)
- `data/processed/bars/XAUUSD/M5/XAUUSD_M5.parquet` (M5 Bars)

---

## 3. Menjalankan Backtest Engine & Strategi

Backtest engine kita sepenuhnya independen (*in-house*), mendukung simulasi intrabar SL/TP pesimistis, model komisi ECN transparan ($7/lot), dynamic slippage, dan **1.000 simulasi Monte Carlo**.

### 3.1. Uji Kelayakan & Integritas Engine:
```bash
.venv/bin/python -m unittest tests/test_backtest_engine.py
```

### 3.2. Backtest Strategi Scalping Teruji (`XAUUSD_Trend_Pullback_Scalper`):
Menguji performa strategi pullback berbasis RBR/DBD Demand-Supply pada data riil 7.182 bar M1 dengan berbagai variasi Risk-to-Reward (1:1.8 s/d 1:2.5):
```bash
.venv/bin/python tests/test_trend_pullback.py
```
*Output akan menampilkan: Total Trade, Win Rate, Profit Factor, Net PnL, Max Drawdown, Komisi terbayar, dan Monte Carlo P95 Worst Drawdown.*

---

## 4. Menjalankan Ablation Study

Ablation study digunakan untuk membuktikan secara matematis apakah suatu filter (seperti Time Exit, Candlestick Engulfing/Pinbar, atau HTF POI) memberikan nilai tambah (*positive delta attribution*) atau justru merusak performa strategi dasar:

```bash
.venv/bin/python strategies/ablation/run_ablation_study.py
```

*Output akan menampilkan tabel perbandingan metrik dan $\Delta\text{PF}$, $\Delta\text{Winrate}$, $\Delta\text{DD}$ dari setiap variasi filter terhadap baseline.*

---

## 5. Menjalankan Multi-Agent AI Suite

Untuk menguji seluruh orkestrasi kecerdasan buatan:
- **Market Regime Detector**: Klasifikasi tren vs sideways vs volatilitas tinggi.
- **Risk Gatekeeper**: Perhitungan lot dinamis berbasis equity & stop loss, spread guardian, dan circuit breaker.
- **Strategy Miner & Auditor**: Eksplorasi kombinasi parameter dan penilaian skor kelayakan institusional.
- **Lifelong Learner**: Audit deviasi performa terhadap kurva Monte Carlo dan pencatatan refleksi post-mortem ke `knowledge/learnings/`.

Jalankan pengujian integrasi seluruh agen:
```bash
.venv/bin/python -m unittest tests/test_multi_agent_framework.py
```

---

## 6. Menjalankan Live Bridge ke MetaTrader 5

Sistem live bridge menggunakan arsitektur pemisahan: **Python Brain** (analisa AI) $\leftrightarrow$ **Native MQL5 TCP Socket** $\leftrightarrow$ **MetaTrader 5** (eksekusi broker).

### Langkah Awal: Setup Sekali Saja di MT5
1. Di MetaTrader 5, buka menu **Tools** $\to$ **Options** (shortcut `Ctrl + O`) $\to$ tab **Expert Advisors**.
2. Beri centang pada:
   - ✅ **Allow algorithmic trading**
   - ✅ **Allow WebRequest for listed URL**
3. Di daftar URL, tambahkan:
   - `http://127.0.0.1:5555`
   - `http://127.0.0.1`
4. Klik **OK**.
5. Buka chart **XAUUSD** (Timeframe **M1**).
6. Di panel Navigator, drag & drop **`LLM_Bridge_Executor`** ke chart. Pastikan tombol **AutoTrading** di toolbar atas MT5 berwarna hijau.

---

### Pilihan Mode Eksekusi:

### Opsi A: Mode Paper Trading (Simulasi / Dry-Run) - *Rekomendasi Awal*
AI memproses tick riil dari MT5 dan candle M1, namun jika ada sinyal, AI **hanya mencatat simulasi order** di terminal tanpa menyentuh saldo broker:
```bash
.venv/bin/python bridge/server.py
```

### Opsi B: Mode Live Auto-Trade (Eksekusi Riil di Akun Demo)
AI memproses tick riil, mengevaluasi regime dan filter risiko. Begitu setup disetujui, Python akan **mengirimkan perintah buka posisi otomatis** ke MT5 lengkap dengan Hard Stop Loss dan Take Profit:
```bash
.venv/bin/python bridge/server.py --live
```

---

## 7. Troubleshooting & FAQ

### 1. Error `SocketConnect failed to 127.0.0.1:5555. Error: 4014` di MT5
- **Penyebab**: Alamat `127.0.0.1:5555` belum didaftarkan di whitelist MT5.
- **Solusi**: Ikuti [Langkah Awal](#langkah-awal-setup-sekali-saja-di-mt5) di atas (Tools $\to$ Options $\to$ Expert Advisors $\to$ Tambahkan `http://127.0.0.1:5555`).

### 2. EA `LLM_Bridge_Executor` tidak muncul di Navigator MT5
- **Penyebab**: File `.mq5` belum di-compile menjadi `.ex5`.
- **Solusi**: Klik kanan folder `Experts` di Navigator MT5 lalu pilih **Refresh**. Atau compile manual via terminal:
  ```bash
  cd "/Users/alami/mt5prefix/drive_c/Program Files/MetaTrader 5"
  WINEPREFIX="/Users/alami/mt5prefix" /opt/homebrew/bin/wine ./MetaEditor64.exe /compile:"MQL5\Experts\LLM_Bridge_Executor.mq5" /log
  ```

### 3. Port 5555 sedang terpakai (`Address already in use`)
- Cek proses yang sedang memakai port 5555:
  ```bash
  lsof -i :5555
  ```
- Matikan proses lama jika perlu:
  ```bash
  kill -9 <PID>
  ```

---

## 🧪 Menjalankan Semua Pengujian Sekaligus

Untuk memverifikasi seluruh komponen sistem bekerja dengan sempurna:
```bash
.venv/bin/python -m unittest discover tests
```
*Seluruh 9 unit test harus berstatus OK dalam tempo ~1 detik.*
