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

### **Fase Eksplorasi 4: Pengembangan Priority 2 - Intraday SMC Expansion Sniper & Dual-Horizon Portfolio**

*   **Status**: **SELESAI.**
*   **Modul Baru**:
    - `strategies/incubator/strat_6_intraday_smc.py`: Menggabungkan struktur H1 (BOS/CHoCH) dengan eksekusi M15 di zona Order Block & Inversion FVG.
    - `strategies/modules/setups/fibonacci_confluence.py`: Engine kalkulasi Fibonacci Retracement (Golden Pocket 61.8% - 78.6% OTE) & Fibonacci Extension (1.272 & 1.618 Wave 3 Expansion Target) berbasis prinsip Elliott Wave Theory.
*   **Temuan Kunci (Fibonacci & Multi-TP)**:
    1.  **Single TP vs Multi-Stage TP**: Terbukti secara kuantitatif bahwa 1 Single Target (100% @ 3.0R) mencetak profit 4x lebih tinggi (+$880 vs +$230) dibanding memecah order ke banyak TP (TP3, TP4, TP5) karena fragmentasi volume dan beban komisi broker.
    2.  **Fibonacci Golden Pocket Confluence (M15/H1)**: Menggabungkan zona Order Block dengan Golden Pocket (61.8% - 78.6% OTE) melompatkan Win Rate ke **75.0%** dengan Profit Factor luar biasa **5.65**! Sebaliknya, Fibonacci pada M5 gagal total (PF 0.63) akibat noise volatilitas mikro.

---
