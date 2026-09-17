# Strategic Evolution Plan: Institutional Robustness & Empiricism Roadmap
**Project:** LLMTrading Quantitative Trading System  
**Date:** September 2026  
**Status:** Active Strategy Document & Execution Backlog  
**Core Philosophy:** *"Process Over Prediction — Never Accept Claims at Face Value, Validate Through Data (Naruto Engine)."*

---

## 1. Konteks & Latar Belakang

Menyusul audit independen dari partner/research desk eksternal yang menguji sistem kami pada data historis Dukascopy XAUUSD M1 selama 16,6 tahun (5,9 juta bar, 2010–2026), sistem kami menunjukkan daya tahan nyata:
* **Engine 1 (M1 VWAP Scalper)** bertahan hidup lintas rezim pasar dengan total **Net Profit +$36.064** dan positif pada **12 dari 17 tahun** ($t$-stat 3.60, peluang kebetulan murni 1:3.000).
* Namun, audit tersebut membuka mata kami terhadap potensi *sample bias* dari data 10,5 bulan (Mei 2025 – Maret 2026) di mana emas melonjak +33%, yang menyebabkan *Max Drawdown* riil mencapai **30,5%** (bukan 6,9%).
* Partner mengakui keunggulan telak sistem kami pada **Automated Execution Bridge (Python $\leftrightarrow$ MT5)**, **Interactive Backtest Chart (1.582 baris)**, dan **Separated Risk Governor**.

**Sikap Strategis Kami:**  
Kami menyerap wawasan positif dari audit luar, **namun tidak menelan mentah-mentah satu pun klaim atau rekomendasi eksternal**. Semua hipotesis baru wajib diuji secara objektif melalui engine backtest paralel kami (**Naruto Shadow Clone**) sebelum diterapkan ke live execution.

---

## 2. Struktur Tiga Jalur Strategis (Three Strategic Tracks)

```
                            [ INPUT & HIPOTESIS AUDIT ]
                                         │
                                         ▼
                     ┌────────────────────────────────────────┐
                     │   FILTER OBJEKTIFITAS:                 │
                     │   Buktikan Lewat Data, Bukan Asumsi!   │
                     └────────────────────────────────────────┘
                                         │
         ┌───────────────────────────────┼───────────────────────────────┐
         ▼                               ▼                               ▼
 [ TRACK 1: LIVE SAFETY ]       [ TRACK 2: BROKER REALITY ]     [ TRACK 3: NARUTO EXPERIMENTS ]
 • Engine 2 (Intraday):         • Profiling Spread Riil MT5     • Eksperimen N-01:
   HOLD live fire, tetap aktif    (PUPrime, Dupoin per jam).      Grid Multi-ATR (0.8x - 2.0x).
   di Radar HUD visualizer.     • Dynamic Spread Tolerance.     • Eksperimen N-02:
 • Engine 1 (M1 Scalper):       • Live Slippage Logger vs         Wick-Touch SL vs Bar-Close SL
   Tetap jalan dengan proteksi    Simulator Backtest.             (Anti-Fakeout vs Slippage).
   Risk Governor ketat.                                         • Track 4: Falsification Gate.
```

---

## 3. Track 1: Kebijakan Operasional Live (Immediate Production Action)

### 3.1 Status Engine 2 (M15 NFC / Skeptical UFO) $\rightarrow$ HOLD LIVE FIRE
* **Evaluasi:** Sampel 57 trade dengan profit +$713 menghasilkan p-value $p=0.33$ (peluang kebetulan 1 banding 3). Jumlah trade belum mencapai signifikansi statistik (*under-powered*).
* **Keputusan:**
  * Pengembangan dan penembakan order live untuk Engine 2 di-**HOLD**.
  * Di `bridge/server.py`, sinyal Engine 2 tidak lagi menembak order riil ke MetaTrader 5.
  * Engine 2 **tetap aktif 100% di Radar HUD Dashboard** sebagai modul kesadaran struktur pasar (*Market Acceptance, Premium/Discount Equilibrium, & UFO Unfilled Orders*).

### 3.2 Status Engine 1 (M1 VWAP Scalper) $\rightarrow$ ACTIVE & PROTECTED
* Tetap aktif berjalan live di VPS dengan pengawalan ketat oleh `MonthlyRatchetGovernor`.
* Parameter default tetap dipertahankan sampai pengujian empiris Track 3 selesai dan terbukti superior.

---

## 4. Track 2: Penelusuran Realitas Broker (Spread & Slippage Deep-Dive)
*Elemen kunci penentu profitabilitas bagi strategi M1 Scalper.*

### 4.1 Live Tick & Spread Profiler
* Menambahkan modul pencatat telemetri spread di `bridge/server.py` untuk merekam:
  * Median spread, spread p95, dan spread p99 per jam sesi (Asia, London Open, US Open, Rollover 04:00-06:00 WIB).
  * Data riil dari broker aktif: **PUPrime** dan **Dupoin**.
* Menghilangkan asumsi spread statis ($0.20) di simulator backtest, menggantikannya dengan kurva distribusi spread empiris per jam.

### 4.2 Dynamic Spread Tolerance Gate
* Mengganti batas spread statis ($0.25 atau $0.35) dengan *Dynamic Adaptive Ceiling*:
  $$\text{Max Allowed Spread} = \min(0.45, \text{SMA}_{30m}(\text{Spread}) \times 1.4)$$
  Mencegah bot mengalami kebuntuan order (*deadlock*) saat kondisi normal broker berada di kisaran $0.28–$0.32, namun tetap memblokir entry saat terjadi spike berita liar ($> 0.50).

### 4.3 Live Execution Slippage Tracker
* Mencatat deviasi antara harga order (`Order Price`) yang dikirim Python dengan harga fill riil (`Filled Price`) yang dilaporkan MT5 via `order_receipt.json`.
* Menghitung nilai *Average Real Slippage* pada eksekusi Market dan Pending Limit.

---

## 5. Track 3: Antrian Eksplorasi Engine Naruto (Empirical Backtesting Queue)

Semua argumen pihak luar diuji secara *head-to-head* di engine backtest `massive_shadow_clone_ema_grid.py`:

### 🧪 Eksperimen N-01: Multi-ATR Multiplier Grid (0.8x s/d 2.0x)
* **Hipotesis Rekan:** *"ATR 1.0x menghasilkan $136k PF 1.33 di data 16 tahun, sedangkan 1.5x hanya overfit pada 10 bulan terakhir."*
* **Desain Pengujian Naruto:**
  * Jalankan simulasi multi-regime untuk parameter: `[0.8x, 1.0x, 1.2x, 1.4x, 1.5x, 1.8x, 2.0x]`.
  * Bandingkan performa pada:
    1. Rezim Bullish Kuat (2025–2026).
    2. Rezim Sideways/Choppy Keras (2022–2024).
    3. Rezim Volatilitas Rendah (2017–2019).
  * **Keputusan:** Parameter hanya akan diubah jika varian 1.0x membuktikan keunggulan Sharpe Ratio dan *Calmar Ratio* (Return / Max Drawdown) di seluruh rezim tanpa merusak kestabilan kurva ekuitas.

### 🧪 Eksperimen N-02: Anatomi Stop Loss — *Wick-Touch SL* vs *Bar-Close Confirmation SL*
* **Latar Belakang Arsitektur Kami:**
  * Simulator kami sengaja mengevaluasi Stop Loss pada **Bar Close M1** untuk mengantisipasi *liquidity grab / wick hunt* (jarum broker yang hanya menyentuh sesaat lalu memantul kembali).
  * Rekan luar menganggap ini kekurangan karena di kondisi ekstrem, kerugian bisa melebar jika bar ditutup jauh menembus level SL.
* **Desain Pengujian Naruto:**
  * **Model A (Standard Retail / Tick SL):** Order langsung ter-stopout begitu `Low <= SL` (Buy) atau `High >= SL` (Sell), di-fill persis di harga `SL` (- slippage).
  * **Model B (Arsitektur Kami / Bar-Close SL):** Order hanya ditutup jika bar M1 ditutup menembus level SL (`Close < SL` untuk Buy).
  * **Matriks Pengujian:**
    * Jumlah trade yang terselamatkan oleh Model B (harga wick menembus SL tapi candle close selamat dan akhirnya mencapai TP).
    * Total ekstra drawdown yang diderita Model B saat harga benar-benar mengalami *trend continuation* melawan posisi.
    * *Net Expectancy Difference:* Membuktikan secara matematis apakah efek "Anti-Wick Hunt" menghasilkan nilai ekspektasi positif bersih.

---

## 6. Track 4: Backlog Framework Falsifikasi Riset (Institutional Noise Gate)
*Disimpan untuk sesi brainstorming dan implementasi di fase mendatang:*
1. **Noise Floor Baseline (Random Entry Control):**
   * Menguji sinyal strategi melawan 500 iterasi entry acak pada instrumen dan jam sesi yang sama.
   * Strategi wajib mengungguli batas atas noise ($Z\text{-score} > 2.5$).
2. **Directional Neutrality (Opposite Side Control):**
   * Membalik logika sinyal (BUY $\rightarrow$ SELL). Jika kedua sisi menghasilkan profit, hasil tersebut mencerminkan anomali volatilitas/trend sampel, bukan keunggulan strategi.
3. **Formal Out-of-Sample (OOS) Partitioning:**
   * Pembagian dataset: 70% In-Sample (Eksplorasi), 15% Validation (Tuning), 15% Blind Holdout (Verifikasi Sekali Eksekusi).

---

## 7. Track 5: User Management & Kemitraan Jangka Panjang
* **User Management & Keamanan:** Penataan autentikasi berbasis role (Admin vs Observer) dan pemindahan seluruh token sensitif ke environment variable terisolasi.
* **Kemitraan Teknis:** Menawarkan modul execution bridge kami (`bridge/server.py` dan `LLM_Bridge_Executor.mq5`) kepada tim riset rekanan untuk mengotomasi eksekusi strategi-strategi mereka yang telah lolos uji 16 tahun, menciptakan kolaborasi institusional yang saling menguntungkan.
