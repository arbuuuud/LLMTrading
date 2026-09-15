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

### **Fase Eksplorasi 6: Riset Filter Tren Makro EMA (20, 50, 100, 200) & Eliminasi Bulan Merah**

*   **Status**: **SELESAI.**
*   **Aksi Shadow Clone**:
    - Script `tests/test_ema_shadow_clones.py` mengerahkan 17 konfigurasi Shadow Clone secara paralel menguji EMA 20, 50, 100, dan 200 pada H1 dan H4.
    - Menyelidiki fenomena "Losing Months" (September & November 2025 di mana Gold meledak parabolik +$400).
*   **Temuan Kunci (Breakthrough Results)**:
    1.  **Rank #1: H1 EMA 50 + Parabolic Buffer $15**:
        - Net Profit melonjak dari **+$4,043.98 $\rightarrow$ +$4,974.72** (+23% profit lift).
        - Profit Factor melesat dari **1.49 $\rightarrow$ 2.02**.
        - Win Rate meningkat dari **27.6% $\rightarrow$ 35.9%**.
        - Max Drawdown tertekan ke level super aman **5.9%**.
    2.  **Rank #2: H4 Strict EMA 20 (Trade with Trend)**:
        - Membalikkan bulan minus menjadi hijau secara spektakuler:
          * Mei 2025: -$305 $\rightarrow$ **+$99.60**
          * September 2025: -$348 $\rightarrow$ **+$478.39**
          * November 2025: -$382 $\rightarrow$ **+$102.45**
        - Konsistensi bulanan melonjak ke **9 dari 11 bulan profit (82% bulan hijau)**!
        - Profit Factor **2.41**, Win Rate **39.4%**, Payoff **3.70x**.
    3.  **Portofolio Gabungan (H4 EMA20 Scalper + Intraday SMC)**:
        - Net PnL gabungan: **+$4,750.23** (+47.5% ROI pada modal $10k).
        - Konsistensi: **9 dari 11 bulan profit bersih (82%)**.

---
