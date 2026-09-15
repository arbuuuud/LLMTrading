# XAUUSD Scalping Playbook (M1 / Tick Horizon)

## 1. Karakteristik Pasar XAUUSD (Gold)
- **High Volatility & Deep Liquidity**: Emas bergerak $15 - $40 per hari secara rata-rata (ATR Daily). Pada level M1, pergerakan $1 - $3 dapat terjadi dalam hitungan menit.
- **Stop Hunting & Liquidity Sweeps**: Sebelum terjadi pergerakan impulsif terarah, *smart money / liquidity providers* sering kali melakukan *sweep* di atas/bawah Asia Session Range atau level Equal Highs / Equal Lows (EQH/EQL).
- **Spread Sensitivity**: Spread standar pada broker ECN adalah 1.0 - 2.5 pips ($0.10 - $0.25). Saat sesi roll-over (21:00 - 23:00 UTC) atau news rilis, spread bisa melonjak ke > $1.00. **Dilarang scalping saat spread melebar**.

---

## 2. Analisis Intermarket (Sinyal Konfirmasi)

### A. Konfirmasi XAGUSD (Silver Lead-Lag & SMT Divergence)
- Emas dan Perak biasanya bergerak searah.
- **Bullish SMT Divergence**: Jika XAUUSD membuat *Lower Low*, namun XAGUSD gagal membuat Lower Low (*Higher Low*), ini mengindikasikan akumulasi institusi (indikasi pembalikan arah naik / *reversal long*).
- **Bearish SMT Divergence**: Jika XAUUSD membuat *Higher High*, namun XAGUSD gagal membuat Higher High (*Lower High*), ini mengindikasikan distribusi institusi (indikasi pembalikan arah turun / *reversal short*).

### B. Konfirmasi DXY (US Dollar Index Inverse Movement)
- Hubungan Emas terhadap DXY adalah **korelasi negatif kuat (-0.7 hingga -0.9)**.
- Breakout valid pada XAUUSD Long harus didukung oleh pelemahan atau rejection resistance pada DXY.
- Jika XAUUSD naik namun DXY juga naik agresif, waspadai dorongan semu (*trap / squeeze*).

---

## 3. Setup Scalping Prioritas Utama

### Setup 1: Session Open Liquidity Sweep (Asia Range Sweep pada London Open)
1. **Identifikasi Range Asia (00:00 - 06:00 UTC)**: Catat High dan Low sesi Asia.
2. **Sweep Fase London (07:00 - 09:00 UTC)**:
   - Tunggu harga menembus Asia High sebesar 10-30 cents, lalu segera ditutup kembali ke dalam range (M1 Market Structure Shift / MSS).
   - Masuk posisi Short dengan target kembali ke mean (VWAP Asia atau Asia Low).
   - Stop Loss diletakkan di atas swing high sweep.

### Setup 2: High Volatility Order Flow Retest (M1 VWAP + Imbalance Fill)
1. Setelah dorongan momentum kuat yang menyisakan Fair Value Gap (FVG) / Imbalance pada M1:
2. Tunggu pullback terukur menyentuh M1 Volume-Weighted Average Price (VWAP) dan level batas FVG.
3. Konfirmasi momentum via tick delta atau volume spike.
4. Entry searah tren dengan rasio R:R minimal 1:1.5.

---

## 4. Aturan Eksekusi & Proteksi
1. **Max Hold Time**: 15 menit. Jika dalam 15 menit trade tidak mencapai TP atau bergerak sideways, lakukan review untuk exit break-even.
2. **Slippage Tolerated**: Maksimal 2 pips. Jika slippage aktual > 3 pips, flag audit eksekusi broker.
3. **Hard Stop Loss**: Wajib dipasang pada saat pengiriman order pertama kali (bukan mental stop).
