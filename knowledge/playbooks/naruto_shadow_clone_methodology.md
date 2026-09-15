# Metodologi Eksplorasi Kuantitatif "Naruto Shadow Clone" (Kage Bunshin)

Metodologi ini adalah protokol eksplorasi kuantitatif otonom yang terinspirasi dari jurus *Kage Bunshin* dalam anime Naruto: **membagi puluhan hingga ratusan klon independen untuk menguji hipotesis trading secara paralel**, kemudian **menghimpun seluruh pengalaman, kemenangan, dan kegagalan kembali ke otak utama (Master Brain)** tanpa mengulang kesalahan yang sama.

---

## 1. Arsitektur Inti: Dari Hipotesis hingga Konsolidasi Memori

```text
                               ┌──────────────────────────────────────────────┐
                               │       LLM Master Brain (Hokage Layer)        │
                               │  - Merumuskan Hipotesis & Ruang Pencarian    │
                               │  - Menetapkan Batas Risiko & Metrik Evaluasi │
                               └──────────────────────┬───────────────────────┘
                                                      │
              ┌───────────────────────────────────────┼───────────────────────────────────────┐
              ▼                                       ▼                                       ▼
      [Shadow Clone #01]                      [Shadow Clone #02]                     [Shadow Clone #N]
      Horizon: Scalp M1                       Horizon: Intraday M15                  Horizon: Swing H4
      Filter: H1 EMA 50 (1.5x ATR)            Setup: Fadli NFC Unfilled Base         Setup: Elliott Wave Fibo
      Mekanika: Mean Reversion                Mekanika: Base Retest                  Mekanika: Trend Expansion
      (300,440 bar / 1.6 detik)               (20,113 bar / 0.1 detik)               (5,038 bar / 0.2 detik)
              │                                       │                                       │
              └───────────────────────────────────────┼───────────────────────────────────────┘
                                                      │
                                                      ▼ (Pengalaman Kloning Menghilang & Balik)
                               ┌──────────────────────────────────────────────┐
                               │         Senior Quant Auditor Agent           │
                               │  - Eliminasi Strategi Overfitting & Noise    │
                               │  - Peringkat berdasarkan Ketahanan (PF & DD) │
                               │  - Catat Pelajaran ke Single Source of Truth │
                               └──────────────────────┬───────────────────────┘
                                                      │
                                                      ▼
                               ┌──────────────────────────────────────────────┐
                               │   Master Memory & Single Source of Truth     │
                               │     (PLAN.md, BLUEPRINT.md, Visualizer)      │
                               └──────────────────────────────────────────────┘
```

---

## 2. 4 Pilar Siklus Hidup Shadow Clone

### Pilar 1: Formulasi Ruang Pencarian (Search Space Definition)
Daripada menebak satu per satu secara manual, Master Brain mendefinisikan ruang parameter multidimensi:
1. **Horizon Eksekusi**: `[M1, M5, M15, H1, H4]`
2. **Konteks Tren Makro**: `[H1 EMA 20, 50, 100, 200; H4 EMA 20, 50, 100, 200]`
3. **Mekanika Risiko**:
   - `BINARY_VETO`: Melarang order berlawanan arah tren makro.
   - `ASYMMETRIC_SIZING`: Bobot risiko 0.65% searah tren vs 0.20% melawan tren.
   - `DYNAMIC_TARGET`: Target ekspansi 3.5R searah tren vs target impas VWAP mean.
   - `ATR_NORMALIZED_BUFFER`: Filter dinamis adaptif berbasis volatilitas $N \times \text{ATR}$.

### Pilar 2: Eksekusi Paralel Kecepatan Tinggi (Ultra-Fast Event Engine)
- Menggunakan mesin event-driven Python murni yang ter-decouple dari MetaTrader 5.
- Data tersimpan dalam format **Apache Parquet terkompresi** (dibaca via Polars dalam < 0.1 detik).
- 60+ klon backtesting pada 10.5 bulan data (300,000+ bar) selesai dalam **102 detik**.

### Pilar 3: Filter Kuantitatif Anti-Overfitting (The Auditor Veto)
Shadow Clone tidak terpukau oleh strategi yang hanya mencetak profit di satu bulan tertentu. Auditor menyaring dengan kriteria institusional:
* **Profit Factor (PF) wajib $\ge 1.30$** (Rasio uang menang terhadap uang kalah).
* **Max Drawdown (DD) wajib $\le 10.0\%$**.
* **Konsistensi Bulanan $\ge 60\%$ bulan hijau** di bawah kendala *Monthly Circuit Breaker*.
* **Payoff Ratio Asimetris $\ge 2.5x$** (Rata-rata untung minimal 2.5 kali rata-rata rugi).

### Pilar 4: Konsolidasi Memori Permanen (No Amnesia)
Ketika klon selesai:
* Temuan pemenang diintegrasikan ke kode produksi (`bridge/server.py`).
* Temuan kegagalan (seperti SMT Silver pada VWAP, atau scalping murni M1 pada Unfilled Orders) dikunci ke dokumen `PLAN.md` agar sistem generasi berikutnya tidak pernah mengulang kesalahan yang sama.

---

## 3. Hasil Pembuktian Riil Metode Naruto di Proyek Ini

Melalui protokol Shadow Clone ini, sistem berhasil melakukan lompatan performa bertahap:

| Iterasi Eksplorasi | Konfigurasi yang Ditemukan | Net Profit (10.5 Bulan) | Profit Factor | Max Drawdown | Bulan Hijau |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Awal (Baseline)** | Standalone VWAP $\pm 1.8\sigma$ (08:00-16:00 UTC) | +$1,386.40 | 1.17 | 12.3% | 4 / 12 (33%) |
| **Kloning Fase 3** | Golden Window (10:30-14:30 UTC) | +$4,043.98 | 1.49 | 6.7% | 6 / 12 (50%) |
| **Kloning Fase 5** | Kombinasi Multi-Timeframe M1 & M15 | +$4,342.14 | 1.52 | 6.5% | 6 / 12 (50%) |
| **Kloning Fase 6** | Macro Defense: H1 EMA 50 (ATR Buffer > 1.5x) | +$6,539.48 | 2.37 | 6.9% | 7 / 11 (64%) |
| **Kloning Fase 7** | **Dual-Horizon: Scalper M1 + Fadli NFC M15** | **+$7,252.51** | **2.35** | **6.9%** | **8 / 11 (73%)** |

---

## 4. Script & Alat Eksekusi (Ready to Use)
- **`strategies/ablation/shadow_clone_matrix_explorer.py`**: Explorer 16 kombinasi multi-timeframe.
- **`tests/massive_shadow_clone_ema_grid.py`**: Grid explorer 61 kombinasi instrumen EMA & ATR.
- **`tests/test_institutional_setups_nusantara_johnpaul.py`**: Benchmark komparatif John Paul 77 vs Fadli vs Arya.
- **`reports/massive_shadow_clone_results.json`**: Basis data artefak hasil pengujian lengkap.
