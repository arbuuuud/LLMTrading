# Institutional Quantitative Research Catalog (The 8 Dimensions of LLMTrading)
**Project:** LLMTrading Core Architecture  
**Dataset Base:** XAUUSD M1 Institutional Dataset (2003–2026 / 7,934,247 Bars / 23.3 Years)  
**Status:** Canonical Reference & Backtest Exploration Matrix (SSOT)  
**Philosophy:** *"Process Over Prediction — Alpha Emerges at the Confluence of Multidimensional Filters, Proven Through Rigorous Data Verification."*

---

## 1. Executive Summary & Purpose

Selama fase riset dan inkubasi sistem `LLMTrading`, kami telah meneliti, membangun, dan menguji puluhan setup teknikal, filter institusional, metodologi price action, dan model proteksi risiko. Pada fase awal, modul-modul ini diuji secara terisolasi (*ablation study / silo testing*) di atas dataset 10,5 bulan.

Kini, dengan tersedianya **Dataset M1 Historis 23,3 Tahun (2003–2026)** sebesar 7,93 juta bar, kami mengintegrasikan seluruh khazanah riset tersebut ke dalam **8 Dimensi Kuantitatif Terpadu**. Dokumen ini menjadi pedoman resmi (*Single Source of Truth*) untuk merancang dan melatih **Grand Master Kage Bunshin (Multi-Clone Parallel Explorer)** melintasi 6 era rezim pasar global.

---

## 2. Peta Arsitektur 8 Dimensi (The 3-Layer Funnel)

```
┌────────────────────────────────────────────────────────────────────────┐
│  LAYER 1: REGIME & CONTEXT FILTER (Kapan Boleh Trading?)               │
│  [Dimensi 1: Time & Sessions]  +  [Dimensi 2: Macro Trend & Structure] │
│  - Golden Window (10:30-14:30 UTC) vs Asia (00-06) vs London (08-11)   │
│  - Sumbu VWAP Harian + H1 EMA 50/100/H4 + Parabolic Runaway Guard      │
│  - Dynamic Spread Filter (< $0.35 - $0.45)                             │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ (Hanya bar yang lolos filter)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  LAYER 2: ENTRY TRIGGER & CONFLUENCE (Di mana & Bagaimana Entry?)      │
│  [Dimensi 3: Setups & POI]  +  [Dimensi 4: Price Action]  +            │
│  [Dimensi 5: SMT Divergence]                                           │
│  - VWAP Deviation Bands (±1.6σ, ±1.8σ, ±2.0σ)                          │
│  - NFC Unfilled Orders (DBR, RBD, RBR, DBD) + Equilibrium 50% Rule    │
│  - Rejection Wick (≥40-50%) + Color Confirm + Engulfing + Doji        │
│  - Intermarket SMT (XAUUSD vs Silver XAGUSD / DXY Non-Confirmation)    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ (Saat sinyal tervalidasi)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  LAYER 3: EXECUTION, DEFENSE & HARVESTING (Bagaimana Mengelola Posisi?)│
│  [Dimensi 6: Stop Loss & Defense]  +  [Dimensi 7: Profit Harvesting] + │
│  [Dimensi 8: Risk Governor]                                            │
│  - ATR Buffer (0.8x - 1.8x) vs Structure Distal SL                    │
│  - Bar-Close Confirmation SL (Anti-Wick Hunt) vs Tick-Touch SL         │
│  - Callisto Twin 50/50 BE Ratchet vs Fixed 1:2 RR vs VWAP Mean Exit    │
│  - Monthly Ratchet Governor: Profit Lock (+1% s/d +3%), 2-Strike Stop  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Rincian Detail 8 Dimensi Riset Kuantitatif

### ⏰ DIMENSI 1: Time, Session & Window Filters
*Menentukan jam-jam di mana likuiditas institusional nyata hadir dan memotong jam-jam whipsaw beracun.*

1. **Asia Session Accumulation Window (00:00 – 06:00 UTC / 07:00 – 13:00 WIB):**
   * Karakter: Rentang harga sempit dengan volume rendah.
   * Fungsi: Membentuk batas *Asian High* dan *Asian Low* sebagai kolam likuiditas (*liquidity pool*) yang akan disapu di sesi Eropa/AS.
2. **London Killzone (07:00 – 09:30 UTC / 14:00 – 16:30 WIB):**
   * Karakter: Pembukaan bank-bank London, sering menciptakan penembusan palsu (*Judas Swing*).
3. **Golden Institutional Overlap Window (10:30 – 14:30 UTC / 17:30 – 21:30 WIB):**
   * Karakter: Puncak perputaran volume global antara London & New York.
   * Temuan Empiris 10,5 Bulan: Mengeliminasi 70% fakeout pagi hari dan menaikkan Profit Factor dari 1.17 $\rightarrow$ 1.49 dengan Payoff Ratio 3.92x.
4. **Toxic Drawdown Cutoff (15:00 – 16:59 UTC / 22:00 – 23:59 WIB):**
   * Jam penutupan London (*London Fix*) yang rawan menghasilkan pergerakan tanpa arah dan whipsaw tajam.
5. **Rollover & Spread Spike Freeze (21:00 – 23:00 UTC / 04:00 – 06:00 WIB):**
   * Periode pergantian hari bank di mana spread emas broker melebar hingga \$1.50–\$3.00. Sistem wajib membekukan seluruh eksekusi order baru.

---

### 🧭 DIMENSI 2: Macro Trend, Filter & Market Structure
*Menjaga sistem agar selalu searah dengan arus likuiditas besar dan menghindari jebakan tren runaway.*

1. **Session-Anchored VWAP (Volume-Weighted Average Price):**
   * Direset setiap hari pukul `00:00 UTC`. Menjadi patokan harga wajar (*Fair Value*) institusi.
2. **VWAP Standard Deviation Bands:**
   * Pita dispersi harga: $\pm 1.6\sigma$, $\pm 1.8\sigma$, $\pm 2.0\sigma$, $\pm 2.2\sigma$. Menandakan deviasi ekstrem di mana harga mengalami ketegangan pegas (*mean-reverting tension*).
3. **Macro Moving Average Trend Filters:**
   * **H1 EMA 50 & H1 EMA 100:** Filter bias utama per jam.
   * **H4 EMA 50:** Filter bias gelombang makro 4 jam.
   * *Rule:* Order Buy hanya sah jika harga berada di atas EMA, dan Order Sell hanya sah jika harga di bawah EMA.
4. **Parabolic Runaway Buffer Guard:**
   * Jika harga melesat melebihi $\$15.00$ atau $\$20.00$ dari H1 EMA 50, pasar dinyatakan dalam kondisi *Parabolic Expansion* (kereta ekspres). Seluruh entry counter-trend otomatis **DIBLOKIR** untuk menghindari *whipsaw squeeze*.
5. **Market Structure Shifts (SMC):**
   * **BOS (Break of Structure):** Penembusan swing high/low yang mengonfirmasi tren sedang berlanjut.
   * **ChoCH (Change of Character):** Penembusan struktur berlawanan pertama yang memberi peringatan awal pembalikan arah bias.

---

### 🏛️ DIMENSI 3: Setup Institusional & POI (Point of Interest)
*Menentukan zona harga spesifik di mana institusi meninggalkan jejak pesanan besar (Unfilled Orders).*

1. **Nusantara FX (NFC - Fadli & Dwiyan Anggara) Auction & UFO Engine:**
   * **DBR (Drop-Base-Rally):** Demand Reversal yang sangat kuat saat harga memantul dari titik jenuh.
   * **RBR (Rally-Base-Rally):** Demand Continuation saat tren kuat berlanjut.
   * **RBD (Rally-Base-Drop):** Supply Reversal dari puncak harga.
   * **DBD (Drop-Base-Drop):** Supply Continuation saat aksi jual berlanjut.
2. **Equilibrium 50% Rule (Auction Acceptance):**
   * Membagi struktur harga menjadi zona Diskon dan Premium.
   * *Strict Rule:* Hanya beli di area **Discount (< 50% Equilibrium)**; Hanya jual di area **Premium (> 50% Equilibrium)**.
3. **ICT Order Block (OB) & Breaker Block (BB):**
   * *Order Block:* Candle berlawanan terakhir sebelum terjadi pergerakan agresif (*Displacement*).
   * *Breaker Block:* Order block yang gagal menahan harga lalu berubah fungsi menjadi bantalan pantulan baru.
4. **Fair Value Gap (FVG) & Inversion FVG (iFVG):**
   * *FVG:* Ketidakseimbangan harga 3 bar (*liquidity imbalance*).
   * *iFVG:* FVG yang ditembus penuh oleh candle impulsif, kemudian diuji ulang sebagai area polaritas terbalik (*support/resistance flip*).
5. **Fibonacci Confluence & Optimal Trade Entry (OTE):**
   * Retracement Golden Pocket: **0.618**, **0.705 (Institutional Sweet Spot)**, dan **0.786 (Deep OTE)**.
   * Extension Profit Targets: **1.272** dan **1.618 (Golden Expansion Target)**.
6. **John Paul 77 Indonesian Formations:**
   * **Range to Range:** Trading pemantulan di batas atas dan batas bawah channel konsolidasi.
   * **Pola N (Breakout & Retest):** Pola zigzag N di mana harga menembus level penting, melakukan retest ringan pada garis leher, lalu melanjutkan akselerasi.
7. **Arya NFC / Judas Swing Liquidity Sweep:**
   * Strategi menjebak trader breakout: harga menembus tipis batas Asia High atau Low, menyerap likuiditas stop order retail, lalu berbalik arah secara tajam.

---

### 🕯️ DIMENSI 4: Price Action & Candlestick Triggers
*Syarat bentuk candle pada penutupan bar close (:00s) sebelum order dieksekusi.*

1. **Rejection Wick / Pin Bar Ratio:**
   * Menghitung panjang sumbu penolakan terhadap total panjang candle:
     $$\text{Wick Ratio} = \frac{\text{Panjang Sumbu Penolakan}}{\text{High} - \text{Low}}$$
   * Ambang batas yang diuji: $\ge 40\%$, $\ge 45\%$, atau $\ge 50\%$.
2. **Candle Directional Confirmation (Color Gating):**
   * Buy wajib memiliki sumbu bawah panjang **DAN** ditutup dengan candle Bullish (Hijau: $\text{Close} > \text{Open}$).
   * Sell wajib memiliki sumbu atas panjang **DAN** ditutup dengan candle Bearish (Merah: $\text{Close} < \text{Open}$).
3. **Bullish & Bearish Engulfing:**
   * Badan candle saat ini secara utuh menelan seluruh badan dan sumbu dari candle sebelumnya.
4. **Doji & Morning/Evening Star Exhaustion:**
   * Candle Doji ($\text{Body} < 10\%$ rentang) menandakan berakhirnya momentum satu arah, disusul oleh bar konfirmasi ledakan arah baru.
5. **Al Brooks H2 / L2 Bar Counting:**
   * Entry pada percobaan pullback kedua (*Second Attempt Trap*) di area moving average, di mana trader counter-trend kehabisan tenaga (*exhaustion*).

---

### ⚡ DIMENSI 5: SMT Divergence & Intermarket Correlation
*Validasi arus dana global dengan membandingkan Emas terhadap instrumen terkait.*

1. **Gold vs Silver (XAUUSD $\leftrightarrow$ XAGUSD):**
   * **Bearish SMT:** XAUUSD mencetak *Higher High*, tetapi XAGUSD mencetak *Lower High*. Mengindikasikan penembusan emas tidak didukung aliran dana logam mulia murni (*liquidity trap*).
   * **Bullish SMT:** XAUUSD mencetak *Lower Low*, tetapi XAGUSD mencetak *Higher Low*. Mengindikasikan akumulasi institusional diam-diam.
2. **Gold vs US Dollar Index (XAUUSD $\leftrightarrow$ DXY):**
   * Mengukur ketidakharmonisan antara indeks dolar dan emas untuk mengonfirmasi titik balik makro.

---

### 🛡️ DIMENSI 6: Stop Loss, Slippage & Broker Reality
*Arsitektur pertahanan modal dari pelebaran spread dan manipulasi broker.*

1. **Model Penentuan Level Stop Loss:**
   * **ATR Buffer:** SL ditaruh pada jarak $0.8\times$, $1.0\times$, $1.2\times$, $1.5\times$, atau $1.8\times$ ATR dari level swing terdekat.
   * **Structure Swing / Distal SL:** SL diletakkan tepat di luar *Distal Line* zona base NFC / Order Block, ditambah buffer $\$0.30–\$0.50$.
   * **Fixed Dollar SL:** SL tetap pada jarak \$1.50 s/d \$3.00.
2. **Mekanisme Eksekusi Stop Loss:**
   * **Model A (Standard Tick-Touch SL):** Posisi langsung ter-stop out seketika saat harga High/Low menyentuh angka SL.
   * **Model B (Bar-Close Confirmation SL / Anti-Wick Hunt):** Posisi hanya ditutup jika bar M1 ditutup menembus level SL. Melindungi posisi dari jarum spread broker yang hanya menusuk sesaat lalu memantul kembali ke arah TP.
3. **Dynamic Spread Tolerance Filter:**
   * Mengganti batas spread statis (\$0.25/\$0.35) dengan batas dinamis moving average:
     $$\text{Max Spread} = \min(0.45, \text{SMA}_{30m}(\text{Spread}) \times 1.4)$$
   * Mencegah sistem macet saat broker melebarkan spread normal ke \$0.32, namun tetap memblokir entry saat terjadi spike berita liar ($> \$0.50$).

---

### 🎯 DIMENSI 7: Take Profit & Trade Management
*Optimalisasi pemanenan laba dan mitigasi risiko saat posisi sedang floating profit.*

1. **Fixed Risk:Reward Ratios:**
   * Target $1:1.5$, $1:2.0$, $1:2.5$, atau $1:3.0$.
2. **Dynamic Target (VWAP Mean Reversion):**
   * Target laba dinamis pada garis tengah VWAP harian (titik equilibrium pasar).
3. **Callisto Partial Take Profit & Breakeven Ratchet:**
   * **Twin Order 50/50:** Begitu target 1.0R tercapai, 50% volume posisi langsung ditutup untuk mengamankan profit tunai.
   * Sisa 50% volume posisi digeser Stop Loss-nya ke **Breakeven (BE + buffer spread/komisi)**, dengan target TP akhir di 2.5R atau garis VWAP.
4. **Advanced Trailing Stop:**
   * Menggeser SL mengikuti level Low/High 3 candle terakhir saat profit telah melampaui 1.5R.
5. **Time-Stop Cutoff (Max Hold Bars):**
   * Jika posisi trading tidak menyentuh TP ataupun SL dalam waktu **60 menit (60 bar M1)**, sistem mengeksekusi *market close* paksa untuk menghindari risiko pergantian sesi dan biaya rollover malam hari.

---

### 🏦 DIMENSI 8: Multi-Account Risk Governor & Capital Allocation
*Sistem kemudi portofolio multi-akun untuk memastikan keberlangsungan modal (anti-ruin).*

1. **4 Profil Risiko Terkalibrasi:**
   * **Prop Firm (Ultra Safe):** 0.25%–0.5% base risk, Max Daily Loss -1.0%, Monthly Cap -3.0%.
   * **Sweet Spot (Balanced Alpha):** 0.5%–0.75% base risk, Max Daily Loss -1.5%, Monthly Cap -4.5%.
   * **Aggressive:** 1.0% base risk, Max Daily Loss -2.5%, Monthly Cap -6.0%.
   * **YOLO (High Octane):** 1.5%–2.0% base risk (hanya untuk akun kecil berisiko tinggi).
2. **Dynamic Ratchet Profit Locking (Bottoming Lock):**
   * Jika profit harian akun mencapai **+1.5%**, lantai profit harian dikunci pada **+1.0%** (bot otomatis berhenti jika keuntungan tergerus ke batas lantai).
   * Jika profit harian mencapai **+2.5%**, lantai profit dikunci pada **+2.0%**.
3. **2-Strike Daily Shutdown:**
   * Jika sistem mengalami 2 kekalahan berturut-turut pada hari yang sama, eksekusi hari tersebut ditutup (*cool-off period* hingga pembukaan hari baru).
4. **Greed Mode (House Money Effect):**
   * Setelah profit hari ini melewati ambang aman (+1.5%), risiko order berikutnya otomatis dipotong menjadi separuh (0.25%) agar tidak mengikis keuntungan yang telah didapat.

---

## 4. Matriks Pengujian Lintas 6 Era Sejarah Emas (2003–2026)

Dataset 23,3 tahun kami memuat seluruh siklus psikologi pasar emas:

| No | Periode Era | Kondisi Pasar & Volatilitas | Rentang Harga Emas | Tantangan Model |
| :--- | :--- | :--- | :--- | :--- |
| **1** | **2003 – 2007** | Pre-Krisis, Low Volatility Trend | \$340 – \$650 | Spread relatif lebar dibanding harga emas, rentang ATR harian sempit. |
| **2** | **2008** | Global Financial Crisis (Lehman Collapse) | \$680 – \$1.030 | Likuiditas kering, guncangan flash crash dan spike likuidasi. |
| **3** | **2009 – 2011** | QE Super Bull Run Pasca-Krisis | \$850 – \$1.920 | Tren parabolik searah satu arah tanpa pullback dalam. |
| **4** | **2013 – 2018** | **Brutal Bear Market & Sideways Churn** | **\$1.050 – \$1.380** | **Ujian sejati (The Kill Zone):** Fake breakout terus menerus, whipsaw panjang. |
| **5** | **2020 – 2021** | COVID-19 Shock & Geopolitical Friction | \$1.450 – \$2.075 | Volatilitas intraday raksasa (\$50–\$100 per hari). |
| **6** | **2024 – 2026** | Global Inflation & Central Bank Rush | \$2.000 – \$4.300+ | All-time high baru, pergeseran spread broker modern. |

---

## 5. Implementasi Mesin: Grand Master Kage Bunshin (`tests/grand_master_kagebunshin_23y.py`)

Untuk mengeksekusi seluruh matriks kombinasi di atas tanpa membebani sistem:
1. **Single-Pass Indicator Pre-Computation:** Seluruh indikator dasar (VWAP, StDev Bands, ATR, H1 EMA, Wick Ratios, Bar Returns) dihitung secara paralel sekali jalan pada 7,93 juta bar menggunakan Polars.
2. **Parallel Clone Evaluation:** Masing-masing Shadow Clone (kombinasi filter) mengevaluasi trade array-nya secara independen dan menyaring metrik performa:
   * Total Net PnL ($) & ROI (%)
   * Profit Factor (PF)
   * Maximum Drawdown (%) & Calmar Ratio
   * Win Rate (%) & Payoff Ratio
   * Annual Consistency (Berapa tahun positif dari 23 tahun)
   * Sharpe Ratio & $t$-statistic signifikansi statistik.
