# Institutional High-Precision Multi-Timeframe (MTF) Fractal Execution Pipeline
**Project:** LLMTrading Quantitative Trading System  
**Document:** High-Precision LTF Sniper Architecture (SSOT)  
**Objective:** Accelerating the +1.0% Daily / +20.0% Monthly Target via Asymmetric Risk-to-Reward ($1 : 5.0$ s/d $1 : 8.0$)  
**Status:** Canonical Strategy & Engineering Specification  

---

## 1. Executive Summary & Problem Formulation

### Masalah pada Pendekatan Konvensional (Naive Single Timeframe M15):
Pada sistem trading retail konvensional, entry pada timeframe M15 sering kali mengalami kelemahan fatal:
1. **Stop Loss Terlalu Lebar (\$5.00 – \$8.00):** Karena mengukur seluruh rentang candle atau zona M15, jarak Stop Loss menjadi sangat jauh dari harga masuk.
2. **Ukuran Posisi (Lot) Mengecil:** Dengan batas risiko tetap $0.50\%$ (\$50 pada akun \$10.000), Stop Loss \$6.00 memaksa ukuran posisi menyusut ke **0.08 – 0.10 lot**.
3. **Risk-to-Reward (R:R) Terbatas ($1 : 2.0$ s/d $1 : 2.5$):** Untuk mendapatkan keuntungan yang layak, target harga harus bergerak \$12.00 – \$15.00 yang jarang tercapai dalam satu hari tanpa pembalikan arah (*reversal*).
4. **Beban Jumlah Kemenangan:** Untuk mencapai target +20% per bulan, sistem membutuhkan **15 hingga 18 kali kemenangan**.

### Solusi Institusional: High-Precision LTF Sniper Pipeline:
Dengan menerapkan hukum fraktal pasar keuangan:
$$\text{HTF Context (H4/H1)} \implies \text{MTF Filter (M15)} \implies \text{LTF Sniper Execution (M3/M1)}$$
* **Stop Loss Menciut Drastis:** Menjadi hanya **\$1.20 – \$1.80** (menggunakan konfirmasi sumbu/swing M3 di dalam batas zona institusi).
* **Ukuran Posisi (Lot) Efisien:** Lot naik ke **0.30 – 0.40 lot** dengan risiko dolar yang **tetap sama persis (\$50)**.
* **Risk-to-Reward (R:R) Melompat ke $1 : 5.0$ s/d $1 : 8.0+$:** Satu kali kemenangan menghasilkan **+2.50% s/d +4.00% net profit**.
* **Target 20%/Bulan Tercapai Sangat Ringan:** Hanya membutuhkan **5 hingga 7 kemenangan dalam satu bulan**!

---

## 2. Diagram Alur Fraktal 4 Tahap (The 4-Stage Fractal Pipeline)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. HTF CONTEXT (H4 / H1): PENENTU ARAH & ZONA INSTITUSI                     │
│    • Macro Trend: H4 EMA 50 (Bullish di atas, Bearish di bawah).            │
│    • Point of Interest (POI): Unfilled Base (DBR / RBD / RBR / DBD).        │
│    • Fibonacci OTE (Optimal Trade Entry): Golden Pocket 61.8% - 78.6%.      │
│    • Equilibrium 50% Rule: Buy HANYA di Discount (<50%), Sell HANYA Premium.│
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼ (Harga masuk ke area POI / Golden Pocket)
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. MTF RADAR STATE (M15): PENGAMAN PISAU JATUH (ARMED STATE)                │
│    • Status Radar HUD: "ARMED" (Kill Zone Aktif).                           │
│    • Menolak entry prematur: Dilarang entry jika momentum penurunan H1      │
│      masih berupa candle ekspansi marubozu tanpa perlambatan volume.        │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼ (Drop timeframe ke M3 / M1)
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. LTF HIGH-PRECISION SNIPER (M3 / M1): TRIGGER EKSEKUSI PRESISI            │
│    • Model A: NO_CONFIRM_SMART_LIMIT (Limit order resting di Proximal Line) │
│    • Model B: M15_CANDLE_CONFIRM (Hammer / Engulfing / Doji di M15)         │
│    • Model C: LTF_M3_WICK_CONFIRM (Rejection Wick >= 45% di M3)             │
│    • Model D: LTF_M3_CHOCH_CONFIRM (Change of Character / Break of Minor M3)│
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. DISPATCH KE BROKER MT5 DENGAN HARD TICK-TOUCH SL                         │
│    • Order: BUY / SELL Market atau Smart Limit.                             │
│    • Stop Loss: Tepat di luar sumbu M3 / CHoCH swing + buffer $0.30.        │
│    • Take Profit: Struktur Liquidity Pool HTF ($10.00 - $15.00 target).     │
│    • Risk Governor: Terintegrasi dengan 2-Strike Rule & Ratchet Profit Lock.│
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Empat Model Trigger Eksekusi yang Diuji

### Model A: `NO_CONFIRM_SMART_LIMIT` (Aggressive Institutional Limit)
* **Mekanisme:** Menempatkan *Buy Limit* atau *Sell Limit* langsung di garis *proximal* POI / level Fibonacci 61.8%.
* **Kelebihan:** *Zero slippage*, mendapatkan harga termurah di ujung ayunan, R:R sangat tinggi ($1 : 5.0+$).
* **Risiko:** Berpotensi terseret jika pasar sedang mengalami *runaway breakout news*.

### Model B: `M15_CANDLE_CONFIRM` (Standard Price Action Bar Close)
* **Mekanisme:** Menunggu penutupan bar M15 membentuk pola *Hammer*, *Bullish/Bearish Engulfing*, atau *Doji Expansion*.
* **Kelebihan:** Menghindari pisau jatuh, konfirmasi jelas bahwa seller/buyer sudah bereaksi.
* **Risiko:** Stop Loss menjadi lebih lebar (\$4.00 – \$6.00) karena harus mencakup seluruh body candle M15.

### Model C: `LTF_M3_WICK_CONFIRM` (High-Precision Rejection Wick)
* **Mekanisme:** Ketika harga masuk ke POI H4/H1, bot memantau penutupan bar **M3**. Begitu bar M3 menyentuh lantai POI dan meninggalkan sumbu penolakan (*rejection wick*) $\ge 45\%$ dengan penutupan searah tren, bot langsung menembak *Market Order*.
* **Stop Loss:** Di luar sumbu terendah/tertinggi bar M3 + \$0.30 buffer (hanya berjarak **\$1.20 – \$1.80**!).
* **Keunggulan:** Kombinasi terbaik antara konfirmasi visual dan Stop Loss ultra-tipis.

### Model D: `LTF_M3_CHOCH_CONFIRM` (Change of Character / Structural Shift)
* **Mekanisme:** Di dalam POI HTF, harga di timeframe M3 membentuk *Lower Lows* dan *Lower Highs*. Bot menunggu bar M3 pertama yang berhasil menembus ke atas *Swing High M3 terakhir* (terjadi *Change of Character / CHoCH*).
* **Stop Loss:** Di bawah lembah swing M3 yang memicu CHoCH.
* **Keunggulan:** Bukti definitif bahwa struktur mikro lelang telah berbalik dari dominasi seller ke buyer.

---

## 4. Komparasi Matematika Asimetris: Mengapa LTF Sniper Mengubah Segalanya

Berikut adalah simulasi riil perhitungan ukuran posisi dan hasil profit pada akun modal **\$10.000** dengan risiko tetap **0.50% (\$50 per trade)**:

| Parameter Kuantitatif | Pendekatan Konvensional (M15 Naive) | Pendekatan Sniper Presisi Tinggi (LTF M3) |
| :--- | :---: | :---: |
| **Harga Masuk (Entry)** | 3.305,00 | 3.301,50 (Lebih dekat ke lantai POI) |
| **Stop Loss (Level)** | 3.299,00 | 3.300,00 (Di bawah sumbu M3) |
| **Jarak Stop Loss (\$ / poin)** | **\$6.00** | **\$1.50 (4x Lebih Tipis!)** |
| **Ukuran Lot (\$50 Risk)** | $\frac{\$50}{\$6.00 \times 100} = \mathbf{0.08\text{ lot}}$ | $\frac{\$50}{\$1.50 \times 100} = \mathbf{0.33\text{ lot}}$ |
| **Target Harga (TP)** | 3.317,00 (\$12.00 target) | 3.315,00 (Kembali ke HTF Resistance) |
| **Jarak Take Profit (\$ / poin)** | \$12.00 | \$13.50 |
| **Risk-to-Reward (R:R)** | **$1 : 2.0$** | **$1 : 9.0$** |
| **Hasil 1 Trade Menang (Net \$)** | **+\$96,00 (+0.96%)** | **+\$445,50 (+4.45%)** |
| **Trade untuk Capai +20%/Bulan** | **~21 Kali Kemenangan** | **HANYA 5 KALI KEMENANGAN!** |

> 💎 **Insight Kuantitatif:**  
> Dengan kompresi Stop Loss via LTF Confirmation, kita **TIDAK PERLU** menaikkan risiko modal (\$50 tetap \$50). Tetapi daya ungkit matematis (*asymmetric leverage*) melonjak drastis, sehingga target bulanan 20% dapat dicapai hanya dengan segelintir trade berkualitas institusional.

---

## 5. Sinergi Portofolio Dual-Engine (Scalper M3 + Intraday M15 Sniper)

Kedua mesin berjalan secara harmonis di bawah naungan `MonthlyRatchetGovernor`:

```
                                 [ AKUN TRADING: $10.000 ]
                                             │
             ┌───────────────────────────────┴───────────────────────────────┐
             ▼                                                               ▼
   [ ENGINE 1: SCALPER M3 ]                                       [ ENGINE 2: INTRADAY SNIPER ]
   • Magic: 1001                                                  • Magic: 2001
   • Frekuensi: 1 - 2 trade/hari                                  • Frekuensi: 2 - 4 trade/minggu
   • Target: 1:2.0 RR (+1.0%)                                     • Target: 1:5.0 s/d 1:8.0 RR (+2.5% - +4.0%)
   • Jam: 10:30 - 14:30 UTC                                       • Jam: London & NY Session
   • Logika: VWAP Reversion Extremes                              • Logika: HTF POI + Fibo OTE + LTF CHoCH
             │                                                               │
             └───────────────────────────────┬───────────────────────────────┘
                                             │
                                             ▼
                             [ RATIO RISIKO GABUNGAN GOVERNOR ]
                             • Hard Daily Loss Limit: -1.0% (Maksimal 2 loss total).
                             • Daily Ratchet Lock:
                               - Begitu profit harian mencapai >= +1.25%, lantai
                                 profit dikunci mati di +1.0%.
                               - Trade berikutnya wajib memakai risiko 0.25% (House Money).
                               - Jika profit turun menyentuh lantai +1.0%, BOT AUTO-SHUTDOWN.
```

---

## 6. Matriks Kage Bunshin Tournament Grid (216 Klon Agent 2)

Untuk memvalidasi model konfirmasi terbaik secara empiris melintasi data 16,6 tahun (2010–2026), turnamen paralel berikutnya akan menguji:

1. **HTF POI Context:** H4 Supply/Demand vs H1 Supply/Demand vs Daily Equilibrium (3 variasi).
2. **Fibonacci Confluence:** Tanpa Fibo vs Fibo OTE (61.8%–78.6%) vs Fibo Discount (50%–61.8%) (3 variasi).
3. **Execution Model:**
   * `NO_CONFIRM_LIMIT`
   * `M15_CANDLE_CONFIRM` (Hammer / Engulfing)
   * `LTF_M3_WICK_CONFIRM` (Rejection wick $\ge 45\%$)
   * `LTF_M3_CHOCH_CONFIRM` (Structural shift M3) (4 variasi).
4. **Target R:R:** $1 : 3.0$ vs $1 : 4.0$ vs $1 : 6.0$ (3 variasi).
5. **Stop Loss Buffer:** Sumbu M3 $\pm \$0.30$ vs Garis Distal POI $\pm 0.8\times \text{ATR}$ (2 variasi).

$$\mathbf{3 \times 3 \times 4 \times 3 \times 2 = 216 \text{ Klon Paralel}}$$
