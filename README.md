# LLMTrading: Autonomous Institutional-Grade AI Trading System

[![Status](https://img.shields.io/badge/status-active_development-blue.svg)]()
[![Architecture](https://img.shields.io/badge/architecture-multi--agent_lifelong_learning-green.svg)]()
[![Core_Assets](https://img.shields.io/badge/assets-XAUUSD%20%7C%20XAGUSD%20%7C%20DXY-gold.svg)]()

Repositori sistem trading kuantitatif mandiri berbasis **Multi-Agent AI** dengan paradigma **Long-Life Learning**, dirancang berdasarkan prinsip **Institutional Protocol** (Matteo Conti - `@patcha015`).

---

## 📖 Master Blueprint

Sebelum mulai bekerja atau menjalankan modul apa pun, baca dokumentasi lengkap arsitektur sistem pada file:
👉 **[BLUEPRINT.md](./BLUEPRINT.md)**

File tersebut adalah **Single Source of Truth (SSOT)** yang memuat:
1. Filosofi Institusional: *"Process Over Prediction"*.
2. Setup Instrumen: XAUUSD (Primary), XAGUSD & DXY (Intermarket Reference).
3. Horizon Prioritas: **Scalping (M1/Tick)** $\to$ Intraday $\to$ Swing.
4. Data Pipeline MT5 (Wine macOS) ke Apache Parquet.
5. In-house Fast Backtest Engine (Vectorized + Event-Driven Tick-Level).
6. Multi-Agent Framework (Regime, Researcher, Validator, Risk Manager, Lifelong Learner).
7. Mekanisme Long-Life Learning tanpa Catastrophic Forgetting.

---

## 🗂️ Struktur Direktori

```text
LLMTrading/
├── BLUEPRINT.md                 # Master Architecture & System Specification (SSOT)
├── README.md                    # Ringkasan proyek & panduan setup
├── configs/                     # Konfigurasi aset & limit risiko
├── data/                        # Penyimpanan data lokal (Parquet Tick & Bars)
│   └── scripts/                 # Ekstraktor data dari MetaTrader 5 (Wine)
├── engine/                      # Custom High-Performance Backtest Engine
│   ├── core/                    # Engine event-driven & order matching
│   ├── metrics/                 # Metrik kinerja institusional (Sharpe, DD, Sortino)
│   └── monte_carlo/             # Simulasi permutasi Monte Carlo (1000+ run)
├── agents/                      # Modul AI Multi-Agent & Prompts
├── strategies/                  # Katalog strategi (Incubator, Active, Retired)
├── knowledge/                   # Memori sistem (Playbooks, Post-Mortem, Learnings)
└── tests/                       # Unit tests & verifikasi matematika
```

---

## ⚙️ Persyaratan Sistem

- **OS**: macOS / Linux
- **Python**: 3.11+
- **Database/Engine**: Polars, NumPy, DuckDB, PyArrow
- **Terminal Trading**: MetaTrader 5 (terpasang di macOS melalui Wine)
- **Data Cache**: Apache Parquet

---

## 🚀 Panduan Menjalankan Sistem (How to Run)

Panduan operasional lengkap langkah demi langkah telah didokumentasikan di:
👉 **[RUNBOOK.md](./RUNBOOK.md)**

### Quickstart Ringkas:

1. **Jalankan Semua Unit Tests (Verifikasi Sistem)**:
   ```bash
   .venv/bin/python -m unittest discover tests
   ```

2. **Jalankan Backtest Strategi Scalping Emas (`XAUUSD_Trend_Pullback_Scalper`)**:
   ```bash
   .venv/bin/python tests/test_trend_pullback.py
   ```

3. **Jalankan Ablation Study (Uji Komparasi Filter)**:
   ```bash
   .venv/bin/python strategies/ablation/run_ablation_study.py
   ```

4. **Jalankan Live Bridge Server ke MetaTrader 5**:
   - **Mode Paper Trading (Simulasi)**:
     ```bash
     .venv/bin/python bridge/server.py
     ```
   - **Mode Auto-Trade Riil (Akun Demo MT5)**:
     ```bash
     .venv/bin/python bridge/server.py --live
     ```

---

## 🧭 Backlog Pengembangan Selanjutnya (Next Strategic Milestones)

Empat opsi kelanjutan yang telah dicatat dan siap dikerjakan (detail lengkap di [BLUEPRINT.md #13](./BLUEPRINT.md)):
1. **Opsi 1**: Observasi Live Forward-Testing di Akun Demo (London & NY Sessions).
2. **Opsi 2**: Integrasi Intermarket SMT Divergence (`XAUUSD` + `XAGUSD` + `DXY`).
3. **Opsi 3**: Big Data Scaling (Konversi batch penuh 77,3 juta tick ke Parquet M1/M5).
4. **Opsi 4**: Setup Remote Git (GitHub/GitLab) & Merge Request Review.

---

## 🔒 Git & Workflow Directive

Setiap kontribusi kode harus mematuhi aturan berikut:
1. **Dilarang keras commit langsung ke `main` / `master`**.
2. Selalu buat branch deskriptif terlebih dahulu (`feat/...` atau `fix/...`).
3. Lakukan pengujian sebelum submit Merge Request / Pull Request.
