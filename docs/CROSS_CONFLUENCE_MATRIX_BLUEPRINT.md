# Matriks Konfluensi Silang & Taksonomi Balok Lego Kuantitatif (SSOT)
**Project:** LLMTrading Quantitative Architecture  
**Dokumen:** Cross-Confluence Multi-Timeframe Matrix Blueprint  
**Tujuan:** Mendefinisikan secara presisi hipotesis konfluensi silang antar elemen teknikal, pembagian timeframe (HTF $\rightarrow$ MTF $\rightarrow$ LTF), peran tagging (Entry, SL, TP, Risk Management), dan kalkulasi jumlah klon Naruto Engine.  
**Filosofi:** *"Process Over Prediction — Jangan menguji parameter acak. Uji hubungan struktural sebab-akibat antar balok lego secara sistematis."*

---

## 1. Taksonomi Balok Lego Sistem (The Core Building Blocks)

Setiap elemen dalam sistem kita diklasifikasikan ke dalam 4 Tag Fungsional Utama:

| Kategori Tag | Elemen / Balok Lego | Definisi & Peran Sistem | Timeframe Yang Relevan |
| :--- | :--- | :--- | :--- |
| **[ENTRY]** | **Base NFC (RBR / DBD / DBR / RBD)** | Unexecuted institutional limit order cluster di mana harga meledak meninggalkan zona. | H4, H1, M15, M5, M3, M1 |
| **[ENTRY]** | **BOS / CHoCH** | Penembusan struktur swing (Change of Character = reversal awal, Break of Structure = kelanjutan tren). | H4, H1, M15, M5, M3, M1 |
| **[ENTRY]** | **Fibonacci OTE & Retracement** | Pengukuran diskon ayunan: 0.382, 0.500 (Equilibrium), 0.618, 0.705, 0.786. | H4, H1, M15 |
| **[ENTRY]** | **Price Action Trigger** | Rejection Wick (≥40-50%), Bullish/Bearish Engulfing, Inside Bar Breakout, Smart Limit Touch. | M15, M5, M3, M1 |
| **[ENTRY]** | **VWAP Deviation Bands** | Deviasi ekstrim rata-rata tertimbang volume: ±1.5σ, ±1.8σ, ±2.0σ. | M15, M5, M3, M1 |
| **[SL]** | **Distal Base Boundary** | Batas terjauh base NFC ± buffer tetap ($0.30 - $1.00). | H1, M15, M3 |
| **[SL]** | **LTF Rejection Wick Low/High** | Ujung sumbu candle konfirmasi M3/M1 + buffer spread ($0.30) -> *Kompresi SL*. | M3, M1 |
| **[SL]** | **ATR Dynamic Distance** | Jarak berbasis volatilitas nyata: $1.0\times$ s/d $1.5\times \text{ATR}_{14}$. | M15, M3 |
| **[TP]** | **Fixed Risk-to-Reward (R:R)** | Pengali kelipatan risiko: 1:2.0, 1:2.5, 1:3.5, 1:5.0. | Portfolio Level |
| **[TP]** | **HTF Liquidity Pool (Opposing Base)** | TP ditaruh di Base / Swing High/Low berlawanan pada H1/H4. | H4, H1 |
| **[TP]** | **Callisto Twin Partial (50/50)** | TP1 di 1:1.5R (tutup 50% lot + geser SL ke BE), sisa 50% dibiarkan lari ke 1:5.0R. | Trade Level |
| **[RISK]** | **Base Risk per Trade** | Ukuran risiko modal: 0.50% ($50), 0.75% ($75), 1.00% ($100), 1.50% ($150). | Account Level |
| **[RISK]** | **2-Strike Daily Shutdown** | Maksimal 2 loss berturut-turut (-1.0% s/d -2.0% daily cap) -> bot auto-shutdown. | Daily Governor |
| **[RISK]** | **Ratchet Profit Lock & Greed Mode**| Profit >= +1.25% mengunci lantai +1.0%, trade berikutnya wajib risiko 0.25% (House Money). | Daily Governor |
| **[RISK]** | **Dynamic Spread Gate** | Veto order jika Spread > $0.40 atau Spread / ATR > 0.35. | Pre-Execution Guard |

---

## 2. Matriks Konfluensi Silang Antar Elemen (Cross-Confluence Matrix)

Matriks di bawah ini memetakan pertanyaan riset objektif ketika satu balok lego bertemu dengan balok lego lainnya:

| Balok Lego X \ Balok Lego Y | **Base NFC (RBR / DBD / DBR / RBD)** | **Struktur BOS / CHoCH** | **Fibonacci Retracement (0.50 / 0.618 / 0.786)** | **Price Action Candle Trigger (Wick / Engulfing / Limit)** | **VWAP Extremes (±1.5σ / ±1.8σ)** |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Base NFC (RBR/DBD/ DBR/RBD)** | **Hubungan Multi-Timeframe:**<br>Apakah Base M15 yang berada di dalam Base H4/H1 memiliki probabilitas pantulan lebih tinggi daripada Base M15 yang berdiri sendiri? | **Validasi Ledakan (Departure):**<br>Apakah Base yang ledakan keluarnya menghasilkan BOS/CHoCH memiliki win rate lebih tinggi daripada Base tanpa BOS? | **Saringan Lokasi (Equilibrium):**<br>Apakah Base DBR/RBR yang berada di area Fibo OTE (61.8%–78.6%) menghasilkan R:R lebih tinggi dibanding Base di luar Fibo? | **Konfirmasi Eksekusi:**<br>Apakah menempelkan Limit Order di Proximal Base lebih unggul dari menunggu Rejection Wick M3/M15 di dalam Base? | **Value Convergence:**<br>Apakah Base Demand yang bertabrakan dengan Lower Band VWAP (-1.8σ) menghasilkan pantulan V-Shape tercepat? |
| **Struktur BOS / CHoCH** | *Sama dengan atas (Simetris)* | **Fraktal Struktural:**<br>Ketika terjadi CHoCH di LTF (M3), apakah wajib searah dengan BOS HTF (H1/H4)? Kombinasi TF mana yang paling bersih dari noise? | **Konfirmasi Pembalikan:**<br>Pantulan di level Fibonacci berapa (0.50 vs 0.618 vs 0.786) yang paling sering memicu CHoCH valid pada timeframe M3/M5? | **Trigger Timing:**<br>Apakah entry di candle penembus CHoCH lebih aman dibanding menunggu retest pullback ke sumbu CHoCH? | **Trend Exhaustion:**<br>Apakah penembusan BOS di luar band ±2.0σ VWAP rentan menjadi jebakan likuiditas (*fake breakout*)? |
| **Fibonacci Retracement** | *Sama dengan atas (Simetris)* | *Sama dengan atas (Simetris)* | **Kedalaman Retracement:**<br>Apakah level 0.618 memberikan win rate tertinggi, atau level 0.786 yang memberikan rasio R:R terbesar? | **Sensitivitas Sumbu:**<br>Berapa panjang sumbu rejection minimal (40% vs 45% vs 50%) saat menyentuh Golden Pocket 61.8% agar pantulan terkonfirmasi? | **Confluence Overextension:**<br>Apakah level Fibo 61.8% yang sejajar dengan VWAP Lower Band -1.5σ merupakan titik pantulan probabilitas tertinggi? |
| **Price Action Trigger** | *Sama dengan atas (Simetris)* | *Sama dengan atas (Simetris)* | *Sama dengan atas (Simetris)* | **Komparasi Model Trigger:**<br>Di antara Limit Order, Hammer/Pinbar, dan Engulfing, manakah yang menghasilkan rasio Profit Factor tertinggi di emas? | **Filter Kebisingan:**<br>Apakah rejection wick di luar band VWAP lebih valid daripada rejection wick di area tengah (VWAP Mean)? |
| **VWAP Extremes** | *Sama dengan atas (Simetris)* | *Sama dengan atas (Simetris)* | *Sama dengan atas (Simetris)* | *Sama dengan atas (Simetris)* | **Multi-Band Dispersion:**<br>Apakah band 1.5σ menghasilkan frekuensi trade yang cukup untuk target 20%/bulan tanpa meningkatkan drawdown dibanding 1.8σ? |

---

## 3. Detail Hipotesis Kuantitatif & Konfigurasi Timeframe

### Hipotesis A: "The Golden Pocket NFC Fortress" (Base NFC + Fibo OTE)
* **Pertanyaan Objektif:** *Apakah menyaring Base DBR/RBD dengan Fibonacci Golden Pocket (61.8% – 78.6%) benar-benar meningkatkan Win Rate dan Profit Factor dibanding Base biasa tanpa Fibo?*
* **Kombinasi Timeframe:**
  * **HTF (H4 / H1):** Mengukur swing leg untuk tarikan Fibonacci (Swing Low $\rightarrow$ Swing High).
  * **MTF (M15):** Lokasi Base Unfilled Orders (DBR/RBD). Base harus bertumpuk (*confluent*) di dalam zona 61.8% – 78.6%.
  * **LTF (M3 / M1):** Konfirmasi candle entri (sumbu rejection $\ge 40\%$).
* **Tagging:**
  * `[ENTRY]`: Touch Proximal Base di Fibo 61.8%–78.6% + M3 Wick $\ge 40\%$.
  * `[SL]`: Sumbu terendah M3 + buffer \$0.30 (Kompresi SL \$1.20 – \$1.80).
  * `[TP]`: Fixed 1:4.0 s/d 1:5.0 R:R.
  * `[RISK]`: 1.00% Base Risk.

### Hipotesis B: "Fractal CHoCH Sniper" (HTF POI + LTF CHoCH)
* **Pertanyaan Objektif:** *Kombinasi timeframe manakah yang paling akurat untuk konfirmasi Change of Character saat harga menyentuh POI institusi?*
* **Kombinasi Timeframe yang Diuji:**
  1. H4 POI $\rightarrow$ M15 CHoCH (Klasik Swing).
  2. H1 POI $\rightarrow$ M5 CHoCH (Standar Intraday).
  3. M15 POI $\rightarrow$ M3 CHoCH (Precision Intraday).
  4. M15 POI $\rightarrow$ M1 CHoCH (Ultra-Scalp).
* **Tagging:**
  * `[ENTRY]`: Bar close penembusan minor swing high/low di LTF saat harga berada di dalam zona MTF/HTF.
  * `[SL]`: Lembah/puncak swing LTF yang menciptakan CHoCH.
  * `[TP]`: Struktur Swing HTF berlawanan (Target \$10.00 – \$15.00).
  * `[RISK]`: 1.00% Base Risk + 2-Strike Daily Shutdown.

### Hipotesis C: "Mean Reversion Band Spring" (VWAP Band + Rejection Wick)
* **Pertanyaan Objektif:** *Pada deviasi berapa (1.3σ vs 1.5σ vs 1.8σ) dan ambang sumbu berapa (35% vs 40% vs 45%) yang menghasilkan frekuensi trade 10–15 trade/bulan dengan Profit Factor > 1.20?*
* **Kombinasi Timeframe:**
  * **HTF (H4):** Macro Trend Filter (H4 EMA 50).
  * **LTF (M3):** Sumbu VWAP harian + deviasi band + penutupan bar M3.
* **Tagging:**
  * `[ENTRY]`: Harga sentuh Band ±1.5σ + Sumbu M3 $\ge 40\%$ searah H4 EMA.
  * `[SL]`: Hard tick broker di ujung sumbu + \$0.50 atau $1.0\times \text{ATR}$.
  * `[TP]`: Fixed 1:2.0 s/d 1:2.5 R:R atau kembali ke Garis Tengah VWAP.
  * `[RISK]`: 1.00% Base Risk + Ratchet Profit Lock +1.0%.

---

## 4. Matriks Perhitungan Dimensi & Jumlah Klon Naruto

Berdasarkan blueprint konfluensi di atas, Naruto Engine tidak lagi memilih parameter secara acak. Kage Bunshin akan membagi klon ke dalam **5 Kluster Riset Terstruktur**:

```
                                [ TOTAL KLON NARUTO: 288 KLON ]
                                               │
         ┌──────────────────┬──────────────────┼──────────────────┬──────────────────┐
         ▼                  ▼                  ▼                  ▼                  ▼
    [ KLUSTER 1 ]      [ KLUSTER 2 ]      [ KLUSTER 3 ]      [ KLUSTER 4 ]      [ KLUSTER 5 ]
   NFC Base + Fibo    HTF POI + CHoCH    VWAP Sensitivitas   Stop Loss Model   Risk & Harvesting
     (72 Klon)          (64 Klon)          (54 Klon)          (48 Klon)          (50 Klon)
```

### Rincian Pembagian Kluster:

1. **Kluster 1: NFC Base + Fibo OTE Confluence (72 Klon)**
   * Base Type: DBR/RBD Reversal vs RBR/DBD Continuation vs All Bases (3 varian).
   * Fibo Level: Tanpa Fibo vs OTE 61.8%–78.6% vs Discount 50%–61.8% (3 varian).
   * Timeframe Trigger: M5 vs M3 vs M1 (3 varian).
   * Target R:R: 1:3.0 vs 1:4.0 vs 1:5.0 vs 1:6.0 (4 varian).
   * *Total:* $3 \times 3 \times 3 \times 4 = \mathbf{72 \text{ Klon}}$.

2. **Kluster 2: Multi-Timeframe Structural CHoCH (64 Klon)**
   * HTF POI Timeframe: H4 vs H1 vs M15 (3 varian + 1 baseline = 4 varian).
   * LTF CHoCH Timeframe: M5 vs M3 vs M1 (3 varian + 1 no-confirm = 4 varian).
   * Retest Mode: Immediate Break Close vs Pullback to CHoCH Wick (2 varian).
   * Target R:R: 1:3.5 vs 1:5.0 (2 varian).
   * *Total:* $4 \times 4 \times 2 \times 2 = \mathbf{64 \text{ Klon}}$.

3. **Kluster 3: VWAP Band & Window Sensitivity (54 Klon)**
   * Trading Window: Golden 4h (10:30-14:30) vs London+NY 10h (07:00-17:00) vs Full 14h (3 varian).
   * Band Multiplier: $\pm 1.8\sigma$ vs $\pm 1.5\sigma$ vs $\pm 1.3\sigma$ (3 varian).
   * Sumbu Wick Threshold: $45\%$ vs $40\%$ vs $35\%$ (3 varian).
   * Target R:R: 1:2.0 vs 1:2.5 (2 varian).
   * *Total:* $3 \times 3 \times 3 \times 2 = \mathbf{54 \text{ Klon}}$.

4. **Kluster 4: Stop Loss Compression & Defense (48 Klon)**
   * SL Model: Hard Tick-Touch vs Bar-Close Confirmation (2 varian).
   * SL Distance: Sumbu Tipis M3 (+$0.30) vs Distal Base (+$1.00) vs $1.0\times \text{ATR}$ (3 varian).
   * Breakeven Trigger: Tanpa BE vs BE setelah +1.0R vs BE setelah +1.5R (4 varian).
   * Target R:R: 1:2.5 vs 1:4.0 (2 varian).
   * *Total:* $2 \times 3 \times 4 \times 2 = \mathbf{48 \text{ Klon}}$.

5. **Kluster 5: Target 20% Monthly Risk Scaling & Harvesting (50 Klon)**
   * Base Risk: 0.50% vs 0.75% vs 1.00% vs 1.50% vs 2.00% (5 varian).
   * Daily Loss Cap (2-Strike): -1.0% vs -1.5% vs -2.0% (3 varian).
   * Ratchet Profit Lock: Tanpa Lock vs Lock di +1.0% vs Lock di +1.5% (3 varian).
   * Harvesting Model: Fixed RR vs Callisto Twin 50/50 Partial (2 varian).
   * *Total Sub-Grid:* Terfokus pada **50 Klon Kombinasi Optimal**.

---

## 5. Standar Evaluasi & Tag Output Hasil Uji

Setiap klon yang disimulasikan oleh Naruto Engine wajib menghasilkan metrik berstandar hedge fund:
1. `trades_per_month`: Rata-rata transaksi per bulan (Target: 10–25 trade/bulan).
2. `active_days_pct`: Persentase hari aktif trading dari total 5.198 hari bursa (Target: 15%–30%).
3. `full_pf`: Profit Factor sepanjang 16,6 tahun 2010–2026 (Wajib $\ge 1.20$).
4. `oos_pf`: Blind Out-of-Sample Profit Factor 2024–2026 (Wajib $\ge 1.50$).
5. `pct_months_hit_20`: Persentase bulan yang berhasil mencapai profit $\ge +20.0\%$.
6. `pct_months_hit_10`: Persentase bulan yang berhasil mencapai profit $\ge +10.0\%$.
7. `max_drawdown`: Drawdown maksimal akun sepanjang 16,6 tahun (Target: $\le 20.0\%$).
8. `p95_monte_carlo_dd`: Skenario 95% terburuk dari 1.000 simulasi acak.
9. `risk_of_ruin`: Peluang kebangkrutan akun (Wajib **0.0%**).
