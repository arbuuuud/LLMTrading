# Rencana Eksplorasi Peningkatan Profitabilitas "Shadow Clone"

## 🎯 **OVERALL GOAL: Mencapai Target Profit 1% per Hari / 20% per Bulan**

Ini adalah rencana iteratif untuk meningkatkan profitabilitas strategi Session Anchored VWAP, menggunakan metodologi "Shadow Clone" LLM untuk eksplorasi dan optimasi yang cepat.

---

## 🚀 **METHODOLOGY: "Shadow Clone" Iterative Exploration**

Kami akan menggunakan pendekatan multi-fase, di mana setiap fase akan berfokus pada area peningkatan tertentu. LLM akan bertindak sebagai "Shadow Clones" yang menjalankan berbagai skenario backtest, menganalisis data, dan mengidentifikasi pola untuk mempercepat proses penemuan.

### **Fase Eksplorasi 1: Persiapan Data Multi-Timeframe Otomatis**

*   **Tujuan**: Memastikan ketersediaan data High Timeframe (HTF) yang bersih dan terstruktur untuk analisis POI.
*   **Alasan**: Pondasi untuk setiap analisis MTFA. Menghindari duplikasi pekerjaan dan memastikan konsistensi data.
*   **Aksi LLM**:
    1.  **Buat Script**: Kembangkan script Python `data/scripts/generate_htf_bars.py`.
    2.  **Fungsionalitas**: Script akan membaca `XAUUSD_M1.parquet`, kemudian meresample-nya menjadi M5, M15, H1, dan H4.
    3.  **Output**: Setiap timeframe yang dihasilkan akan disimpan sebagai file Parquet terpisah di `data/processed/bars/XAUUSD/HTF/` (misal: `XAUUSD_H1.parquet`).

### **Fase Eksplorasi 2: Pengembangan Modul Deteksi Point of Interest (POI) & MTFA**

*   **Tujuan**: Membuat modul-modul yang dapat mendeteksi POI secara otomatis di berbagai timeframe. Prioritas akan diberikan pada POI yang paling relevan untuk XAUUSD dan strategi Mean Reversion/Range Trading.
*   **Alasan**: Memberikan "mata" kepada strategi untuk melihat level-level penting di HTF yang mungkin tidak terlihat di M1.
*   **Aksi LLM (Iteratif)**:
    1.  **Prioritas POI**: Fokus pada:
        *   **Order Block (OB)** & **Breaker Block (BB)**: Zona supply/demand institusional.
        *   **Fair Value Gap (FVG)** & **Inversion FVG (iFVG)**: Imbalance harga dan zona polaritas terbalik (support <-> resistance flip).
        *   **Market Structure (BOS/ChoCH)**: Pergeseran struktur pasar yang mengindikasikan perubahan bias.
        *   **Fibonacci Levels**: Retracement dan ekstensi kunci.
    2.  **Buat Modul**: Kembangkan modul-modul terpisah di `strategies/modules/context` atau `strategies/modules/setups` (misal: `ob_detector.py`, `fvg_detector.py`, `market_structure.py`).
    3.  **Implementasi**: Setiap modul akan mampu mendeteksi POI pada bar dari timeframe yang berbeda (M15, H1, H4).

### **Fase Eksplorasi 3: Eksplorasi Konfluensi & Integrasi POI ke Strategi**

*   **Tujuan**: Mengintegrasikan sinyal POI dari HTF ke dalam `SessionAnchoredVWAPStrategy` M1 untuk meningkatkan probabilitas dan/atau payoff ratio.
*   **Status**: **SELESAI (Ablation Study 10.5 Bulan / 300,440 Bars).**
*   **Temuan Kunci (Empirical Institutional Insights)**:
    1.  **Filter POI Ketat (Exclusionary Gate)**: Membatasi entry M1 hanya saat menyentuh OB/iFVG M15 memotong 70% trade valid dan menurunkan net PnL (sama seperti SMT Silver), karena mean reversion memudar di ekstrim band, bukan di zona konsolidasi masa lalu.
    2.  **Golden Institutional Window (10:30 - 14:30 UTC)**: Merupakan *game-changer* utama! Memangkas fakeout jam 08:00-10:00 dan whipsaw beracun jam 15:00-16:00 UTC melipatgandakan profit:
        *   **Net PnL**: Melejit dari **+$1,386.40 $\rightarrow$ +$4,043.98** (+191% profit lift).
        *   **Profit Factor**: Naik dari **1.17 $\rightarrow$ 1.49**.
        *   **Max Drawdown**: Turun drastis dari **12.3% $\rightarrow$ 6.7%** (risiko terpotong hampir separuh).
        *   **Payoff Ratio**: Mencapai **3.92x** (rata-rata win hampir 4x loss).
        *   **Konsistensi**: 6-7 bulan dari 10.5 bulan berprofit bersih dengan Monthly Ratchet Governor.

### **Fase Eksplorasi 7: Audit Setup Institusional Indonesia (Fadli NFC, Arya NFC, John Paul 77) & Rekor Portofolio +$7,252**

*   **Status**: **SELESAI.**
*   **Investigasi 3 Setup Komunitas Indonesia**:
    1.  **John Paul 77 ("Range to Range" & "Pola N")**:
        - Range Reversal di Gold menghasilkan drawdown (-$421, DD 14.4%) karena ekspansi Gold sering menembus batas sesi Asia.
        - Pola N (Breakout & Retest) jauh lebih sehat dengan Max Drawdown hanya 6.0%.
    2.  **Arya / NFC (Asian Liquidity Sweep ke Opposite Pool)**:
        - Mengalami loss (-$1,739) saat diterapkan murni tanpa filter makro karena di 70% kondisi Gold, penembusan Asian High/Low di jam London/NY adalah *Momentum Continuation*, bukan *fakeout reversal*.
    3.  **Fadli / NFC (Unfilled Orders / Supply & Demand Base: DBR / RBD)**:
        - Terbukti sangat profitable di M15 ketika dipadukan dengan **H1 EMA 50 Macro Filter**:
        - Net Profit Intraday melompat dari +$298 $\rightarrow$ **+$713.03** (Win Rate 38.6%, PF 1.31, DD 5.6%).
*   **Pencapaian Rekor Tertinggi Portofolio (The All-Time Record: +$7,252.51)**:
    - **Engine 1**: Scalper M1 (Champion ATR Buffer H1 EMA 50): **+$6,539.48**
    - **Engine 2**: Intraday M15 (Fadli NFC Unfilled Orders + H1 EMA 50): **+$713.03**
    - **Total Net PnL Gabungan**: **+$7,252.51** (+72.5% ROI pada modal $10k).
    - **September 2025 Berhasil Dibalik Menjadi Hijau**: **+$24.11**!
    - Kerugian Juli terpangkas menjadi hanya -$72.77!

---

### **Fase Eksplorasi 8: Quantitative Stress-Test, Broker Reality Profiling & Antrian Validasi Empiris Naruto (Post-Partner Audit)**

*   **Status**: **AKTIF / IN PROGRESS.**
*   **Dokumen Acuan Utama**: `docs/STRATEGIC_EVOLUTION_PLAN.md` (SSOT Roadmap).
*   **Konsep Utama**: *"Process Over Prediction — Jangan menelan mentah-mentah opini eksternal, buktikan lewat data empiris (Naruto Engine)."*
*   **Aksi Operasional & Kebijakan Live**:
    1.  **Engine 2 (Intraday M15 / Skeptical UFO)**: **HOLD LIVE FIRE**. Eksekusi order ke MT5 dinonaktifkan sementara karena sampel 57 trade memiliki nilai $p=0.33$. Modul tetap 100% aktif di Radar HUD sebagai kesadaran struktur pasar (*Premium/Discount*).
    2.  **Engine 1 (M1 VWAP Scalper)**: Tetap berjalan live dengan kawalan `MonthlyRatchetGovernor`.
*   **Antrian Eksperimen Naruto (Shadow Clone Backtest Queue)**:
    1.  **Eksperimen N-01 (Multi-ATR Grid 0.8x s/d 2.0x)**: Uji hipotesis rekanan mengenai varian 1.0x ATR vs 1.5x ATR lintas rezim pasar (trending vs sideways vs low volatility).
    2.  **Eksperimen N-02 (Wick-Touch SL vs Bar-Close Confirmation SL)**: Komparasi matematis antara proteksi anti-fakeout/anti-wick hunt kita melawan risiko pelebaran loss saat breakout.
*   **Penelusuran Realitas Broker (Spread & Slippage Profiler)**:
    1.  Merekam telemetri spread riil per jam dari terminal MT5 (PUPrime & Dupoin).
    2.  Implementasi *Dynamic Spread Ceiling* berbasis moving average spread untuk mencegah deadlock order.
    3.  Pencatatan live slippage MT5 via `order_receipt.json`.
*   **Backlog Falsifikasi Institusional**:
    1.  *Noise Ceiling Check* (Random Entry Control).
    2.  *Directional Neutrality* (Opposite Side Test).
    3.  *Out-of-Sample (OOS) Pipeline 70/15/15*.

---

### **Fase Eksplorasi 9: Grand Master Kage Bunshin — 8-Dimensional Multi-Clone Learning (2003–2026 / 7.93M Bars)**

*   **Status**: **IN PROGRESS / ACTIVE PIPELINE.**
*   **Dokumen Acuan Utama**: `docs/QUANTITATIVE_RESEARCH_CATALOG_8D.md` (SSOT Research Catalog).
*   **Dataset Source**: `data/processed/bars/XAUUSD/M1/XAUUSD_M1_2003_2026.parquet` (7.934.247 bars M1 / 23.3 Tahun).
*   **Tujuan**: Mengintegrasikan seluruh hasil riset historis (ATR, Time Window, Market Session, Risk Profile, HTF EMA, POI NFC/ICT, Candlestick Rejection, SMT, Stop Loss Model, Callisto BE) ke dalam satu engine pengujian paralel multi-dimensi.
*   **8 Dimensi Kuantitatif Terpadu**:
    1.  *Time & Session Filters*: Golden Window 10:30-14:30 vs London 08-11 vs Asia 00-06 vs Rollover Cutoff.
    2.  *Macro Trend & Market Structure*: Sumbu VWAP Harian + H1 EMA 50/100/H4 + Parabolic Runaway Guard ($15) + Korelasi Fraktal MTF (H4 -> H1 -> M15 -> M2/M3 sweet spot -> M1).
    3.  *Setups & POI*: NFC Unfilled Orders (Continuation: RBR/DBD vs Reversal: DBR/RBD vs FTR) + Equilibrium 50% Rule (Discount/Premium) + Base Age Decay & First Retest + ICT OB/FVG + Fibo OTE.
    4.  *Price Action Triggers*: Rejection Wick (≥40-50%) + Color Confirmation + Engulfing + Doji + Al Brooks H2/L2.
    5.  *SMT Divergence*: Intermarket confirmation (XAUUSD vs Silver XAGUSD / DXY non-confirmation).
    6.  *Stop Loss, Defense & Order Execution*: Multi-ATR (0.8x - 1.8x) vs Structure Distal SL; Bar-Close Confirmation SL vs Tick SL; **Market Order on Close vs Resting Limit Order at Proximal Line vs Confirmed Smart Limit**.
    7.  *Profit Harvesting*: Callisto Twin 50/50 BE Ratchet vs Fixed 1:2 RR vs VWAP Mean Target + Trailing Stop.
    8.  *Risk Governor*: Prop Firm (0.5%), Sweet Spot (0.75%), Bottoming Profit Lock (+1% s/d +3%), 2-Strike Daily Shutdown.
    9.  *Monte Carlo Robustness & Falsification Engine*: 1.000 Bootstrap Reshuffles (P95 Worst-Case DD, Risk of Ruin < 1%) + Missed Trade Stress (15% drop) + Noise Floor Control (500 Random Monkeys, Z-score > 2.0).
*   **Timeframe Inventory (2003–2026)**:
    - M1 (7.93M bars), M2 (4.06M bars), M3 (2.74M bars), M5 (1.66M bars), M15 (561K bars), H1 (141K bars), H4 (37K bars), D1 (7.2K bars).
*   **Target Output**:
    - Leaderboard Juara Sejati 2003–2026 yang teruji kebal di 6 era pasar emas dunia (2008 Crash, 2013-2018 Bear/Sideways Churn, 2020 COVID, 2024-2026 Bull Run).


