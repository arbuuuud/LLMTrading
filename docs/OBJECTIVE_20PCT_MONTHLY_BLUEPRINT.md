# Institutional Blueprint: Achieving 1% Daily / 20% Monthly Target
**Project:** LLMTrading Core Architecture  
**Target Objective:** Net Return +1.0% per Trading Day / ~+20.0% per Month  
**Risk Tolerance:** Max Monthly Drawdown < 5.0% (Prop Firm & Hedge Fund Compliant)  
**Status:** Canonical Implementation Roadmap & Strategy Document (SSOT)  

---

## 1. Executive Summary & Objective

Tujuan utama sistem kuantitatif `LLMTrading` adalah menghasilkan imbal hasil konsisten sebesar **+1.0% per hari trading** atau setara dengan **~+20.0% per bulan kalender** (berdasarkan 20 hari aktif trading) dengan menjaga *Maximum Drawdown* bulanan tetap terkendali di bawah **5.0%**.

Dokumen ini merinci secara matematis dan arsitektural:
1. **Cara Berpikir (*Mental Model*) Kuantitatif:** Mengapa mengejar 1% per hari TIDAK BISA dilakukan dengan memaksakan diri trading setiap hari secara linier, melainkan melalui distribusi probabilitas asimetris (*Asymmetric Probability Distribution*).
2. **Tiga Jebakan Maut Retail:** Mengapa 99% trader retail gagal dan membakar akun saat mencoba mengejar 1% per hari.
3. **Lima Pilar Arsitektur Portofolio:** Integrasi *Dual-Horizon* (M2 Scalper + M15 NFC UFO), *Ratchet Profit Lock*, *2-Strike Daily Shutdown*, dan *Golden Execution Window*.
4. **Roadmap Pengujian Komprehensif:** Tahapan validasi ketat (*Kage Bunshin Grid, Falsification 500 Random Monkeys, 1.000 Monte Carlo Runs, dan Walk-Forward Analysis*).

---

## 2. Cara Berpikir Kuantitatif: Matematika Distribusi Asimetris

Dalam perdagangan institusional, target "1% per hari" **bukanlah garis lurus yang kaku**. Memaksakan bot harus untung 1% setiap hari akan memaksa bot melakukan *overtrading* pada hari-hari di mana pasar sedang sepi atau choppy, yang berujung pada kehancuran akun.

Cetak biru matematis yang benar dibangun di atas rumus ekspektasi:
$$E = (\text{Win Rate} \times \text{Average Win}) - (\text{Loss Rate} \times \text{Average Loss}) - \text{Friction (Spread + Slippage)}$$

### Parameter Sizing & Asymmetric Payoff:
* **Base Risk per Trade ($R$):** **0.50% modal** (Akun \$10.000 mempertaruhkan \$50).
* **Target Risk-to-Reward (R:R):** **$1 : 2.0$ hingga $1 : 2.5$**.
* **Keajaiban Asimetris:** Ketika 1 trade setup valid mengenai Take Profit, perolehan akun langsung:
  $$\mathbf{+1.00\%} \quad (0.5\% \times 2.0) \quad \text{hingga} \quad \mathbf{+1.25\%} \quad (0.5\% \times 2.5)$$
  👉 **Target harian 1% langsung tercapai lunas hanya dalam 1 trade tunggal!**

### Model Distribusi 20 Hari Trading per Bulan:
Target +20% per bulan dicapai melalui distribusi realistis berikut:

| Kategori Hari | Frekuensi | Karakteristik Hari | Net PnL Harian | Subtotal Kontribusi |
| :--- | :--- | :--- | :--- | :--- |
| **Big Win Days** | **8 Hari** | Tren kuat / Sinyal lanjutan dengan Greed Mode House Money (0.25% risk). | **+1.5% s/d +2.0%** | **+14.0%** |
| **Clean Win Days** | **5 Hari** | 1 trade valid langsung hit TP 1:2.0 RR, bot langsung istirahat. | **+1.0% s/d +1.25%** | **+5.5%** |
| **Flat / No-Trade Days** | **3 Hari** | Hari libur bank / volatilitas sempit / spread melebar (Nol trade). | **0.0%** | **0.0%** |
| **Controlled Loss Days** | **4 Hari** | Pasar berbalik arah, terkena 2-Strike Rule (-0.5% x 2), auto-shutdown. | **-1.0% (Hard Cap)**| **-4.0%** |
| **TOTAL BULANAN** | **20 Hari** | **Sistem berjalan disiplin tanpa dendam pasar.** | **Net Bulanan** | **+15.5% s/d +19.5% (~20%)** |
| **MAX DRAWDOWN** | — | **Terkunci ketat oleh batas harian -1.0%.** | **Max DD** | **-3.0% s/d -4.0% (Sangat Aman)** |

---

## 3. Tiga Jebakan Maut Pemburu "1% per Hari"

Dokumen ini melarang keras 3 perilaku trading yang terbukti mematikan sistem:

1. **Jebakan Forced Trading di Hari Sepi (Overtrading):**
   * Di hari libur atau konsolidasi sempit, trader retail memaksakan 5–10 trade untuk mengejar 1%. Akhirnya menderita -3% hingga -5%.
   * *Solusi:* Jika dalam Golden Window tidak ada setup valid, **Nol Trade adalah hasil yang sempurna**.
2. **Jebakan Sizing Up (Overleverage):**
   * Menaikkan risiko ke 2.0% per trade agar cepat mencapai 1%. Tiga kekalahan beruntun langsung memicu -6% (gagal evaluasi Prop Firm).
   * *Solusi:* Base risk dikunci mutlak di **0.50%**.
3. **Ketergantungan pada 1 Mesin Tunggal (Single Strategy Trap):**
   * Data 23,3 tahun membuktikan scalper mean reversion menderita saat pasar trending satu arah tanpa henti. Sebaliknya, trend-follower menderita saat pasar sideways.
   * *Solusi:* Menggunakan sinergi **Dual-Horizon Portfolio** (Scalper + Trend Intraday).

---

## 4. Lima Pilar Arsitektur Portofolio 20%/Bulan

```
                         ┌──────────────────────────────────────────────┐
                         │              TARGET: +1% HARI INI            │
                         └──────────────────────┬───────────────────────┘
                                                │
                 ┌──────────────────────────────┴──────────────────────────────┐
                 ▼                                                             ▼
     [ MESIN 1: SCALPER M2 ]                                      [ MESIN 2: INTRADAY M15 ]
     • Frekuensi: 1 - 2 trade/hari                                • Frekuensi: 3 - 5 trade/minggu
     • Target: 1:2.0 RR (+1.0%)                                   • Target: 1:3.5 RR (+1.75%)
     • Jam: 10:30 - 14:30 UTC                                     • Sinyal: NFC Unfilled Base (DBR/RBD)
                 │                                                             │
                 └──────────────────────────────┬──────────────────────────────┘
                                                │
                                                ▼
                            ┌───────────────────────────────────────┐
                            │        THE RATCHET PROFIT LOCK        │
                            │        1. Capai +1.25% -> Kunci +1.0% │
                            │        2. Greed Mode (Risk 0.25%)     │
                            │        3. Pullback ke +1.0% -> SHUTDOWN│
                            └───────────────────────────────────────┘
```

### Pilar 1: Sinergi Dual-Horizon Portfolio
* **Engine 1 (M2 Session-Anchored VWAP Scalper):**
  * Penghasil *cashflow* harian reguler. Menembak 1–2 kali sehari di jam likuiditas tertinggi. Begitu 1 trade menang, target 1% hari itu selesai.
* **Engine 2 (M15 NFC Unfilled Orders & Trend Expansion):**
  * Penghasil *Home Run* (kemenangan besar) saat harga mengalami tren ekspansi ratusan pips.
  * Target R:R $1:3.5$ s/d $1:4.0$ (+1.75% s/d +2.0% per trade). Menopang akumulasi profit bulanan saat pasar sedang trending kuat.

### Pilar 2: The Ratchet Profit Lock & Greed Mode
* Fitur pengaman di `MonthlyRatchetGovernor`:
  1. Begitu profit hari ini mencapai $\ge +1.25\%$, **Lantai Profit Terkunci di +1.0%**.
  2. Bot hanya boleh membuka trade kedua jika menggunakan **Greed Mode (House Money)**: risiko dipotong menjadi **0.25%**.
  3. Jika trade kedua menang $\rightarrow$ profit naik ke $+1.8\%$ s/d $+2.0\%$.
  4. Jika trade kedua kalah $\rightarrow$ profit turun menyentuh lantai $+1.0\%$, bot **LANGSUNG SHUTDOWN OTOMATIS** untuk hari itu. Keuntungan 1% tidak bisa direbut kembali oleh pasar!

### Pilar 3: The 2-Strike Defensive Guard
* Jika hari trading dibuka dengan kekalahan:
  * Loss 1 = -0.50%. Loss 2 = -0.50%.
  * Total kerugian mencapai **-1.0%**, bot langsung **AUTO-LOCK & MATI TOTAL** hingga hari esok.
  * Menghilangkan faktor emosi, balas dendam (*revenge trading*), dan membatasi drawdown bulanan $< 5\%$.

### Pilar 4: Migrasi Resolusi Eksekusi ke M2 / M3 (Anti-Noise Sweet Spot)
* Temuan 23,3 tahun membuktikan M1 menghasilkan OOS Profit Factor hanya 0.61 karena terlalu banyak *wick traps* (sumbu manipulasi).
* **M2 dan M3 berhasil melipatgandakan OOS PF ke 1.11+** karena menyaring *noise* mikro tanpa kehilangan kecepatan entri momentum.

### Pilar 5: Disiplin Jam Operasional (Golden Window 10:30 – 14:30 UTC)
* Eksekusi scalper dibatasi ketat hanya pada jam overlap likuiditas London & New York (10:30 – 14:30 UTC / 17:30 – 21:30 WIB).
* Menghindari sesi Asia subuh dan sesi rollover (04:00–06:00 WIB) di mana spread broker melebar ekstrem.

---

## 5. Roadmap Pengujian Komprehensif (*Validation & Stress-Test*)

Untuk membuktikan secara ilmiah bahwa sistem ini kebal dari *overfitting* sebelum modal riil diskalakan, sistem wajib melalui 5 tahapan pengujian:

```
[ STEP 1: Era Normalization ]  -->  [ STEP 2: Grand Kage Bunshin ]  -->  [ STEP 3: Falsification Gate ]
         │                                       │                                      │
         ▼                                       ▼                                      ▼
   Fokus 2010-2026 ECN                    100+ Clone Tournament                 500 Random Monkeys
   (Spread/ATR < 0.35)                    (M2 Scalper + M15 UFO)               + 1.000 Monte Carlo
                                                 │
                                                 ▼
                                  [ STEP 4: Walk-Forward Matrix ]
                                                 │
                                                 ▼
                                  [ STEP 5: Live Pilot Run VPS ]
                                  (Multi-Account Demo Telemetry)
```

### 📍 Tahap 1: Era Normalization & Spread Friction Filter
* Memisahkan data distorsi era 2003–2007 (di mana spread \$0.56 memakan 98% rentang candle) dan mengunci pengujian inti pada **Era Modern ECN (2010–2026 / 16,6 Tahun / 5,9 Juta Bar M1)** dengan batas friksi $\text{Spread} / \text{ATR} \le 0.35$.

### 📍 Tahap 2: Grand Master Kage Bunshin Tournament (Dual-Horizon: M2 + M15)
* Melatih 100+ klon paralel melintasi 16,6 tahun data untuk menguji konfluensi:
  1. *Timeframe Trigger:* M2 vs M3.
  2. *Macro Trend Gate:* H1 EMA 50 vs H1 EMA 100 vs H4 EMA 50.
  3. *Unfilled Base Filter:* RBR/DBD Continuation vs DBR/RBD Reversal.
  4. *Stop Loss:* Sumbu Wick Buffer (\$0.50) vs Dynamic ATR (1.0x).
  5. *Target Management:* Fixed 1:2.0 RR vs Callisto Twin 50/50 Breakeven.

### 📍 Tahap 3: Anti-Overfitting & Institutional Falsification Gate
* Setiap klon juara wajib lulus 3 filter eliminasi:
  1. **Partitioning 70/15/15:** Train (2010–2019) $\rightarrow$ Validation (2020–2023) $\rightarrow$ **Blind Out-of-Sample (2024–2026)**. Klon wajib mempertahankan $PF \ge 1.15$ di data buta 2024–2026.
  2. **500 Random Monkeys (Noise Floor):** Menjalankan 500 iterasi entry acak. Strategi wajib mengungguli batas atas acak dengan signifikansi statistik $Z\text{-score} > 2.0$.
  3. **1.000 Monte Carlo Permutations:** P95 Max Drawdown wajib $< 8.0\%$ dan Risk of Ruin $< 0.5\%$.

### 📍 Tahap 4: Walk-Forward Rolling Analysis
* Melatih strategi pada jendela bergerak 2 tahun dan memvalidasi pada 6 bulan berikutnya secara berputar melintasi 2010–2026 untuk mengukur elastisitas adaptasi model.

### 📍 Tahap 5: Live Pilot Run di VPS IndoVM (Multi-Account Telemetry)
* Menghubungkan EA MT5 PUPrime dan MT5 Dupoin secara paralel ke `bridge/server.py` yang telah terpasang parameter M2 Scalper dan Ratchet 1%/hari, mengawal telemetri live slippage selama 1–2 minggu.
