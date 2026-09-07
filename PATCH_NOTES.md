# Patch 10.9.3 -> 10.9.4 — Momentum scanner (Fase 1: engine layer, TERVALIDASI)

Ini paket LENGKAP dan FINAL dari seluruh sesi — extract di root repo,
timpa/tambah semua 4 file di bawah. Kalau kamu mulai dari commit 10.9.3
yang bersih, extract paket ini = hasil akhir yang sudah tervalidasi 3/3
(BUMI/SINI/UANG), tidak ada versi antara yang perlu ditelusuri lagi.

## Isi paket

```
agents/momentum_scanner.py       <-- BARU
validate_momentum_cases.py       <-- BARU (root, sejajar diagnose_*.py)
diagnose_momentum_window.py      <-- BARU (root, sejajar diagnose_*.py)
version.json                     <-- DIGANTI (10.9.3 -> 10.9.4, cuma nambah
                                      1 entry changelog paling atas, 225
                                      entry lama TETAP UTUH)
```

Tidak ada perubahan ke `core/ob_engine.py`, `core/structure_signals.py`,
`agents/structure_scanner.py`, `agents/golden_setup_scanner.py`, atau file
produksi lain manapun. Murni aditif + 1 file config (version.json).

## Status: Fase 1 selesai & tervalidasi. Fase 2 (UI) BELUM dikerjakan.

Definisi rule "Momentum" (VIDYA flip + BOS/CHoCH union + EQL opsional)
sudah dites terhadap 3 study case ASLI dari chart TradingView user, via
`validate_momentum_cases.py` dijalankan di mesin lokal (perlu akses data
live — Claude sendiri tidak bisa jalankan ini):

| Ticker | Target (dikonfirmasi manual) | Hasil |
|---|---|---|
| BUMI | BOS(internal) 20-Jul-2026 | PASS |
| SINI | CHoCH ~18-Aug-2026 | PASS |
| UANG | BOS(internal)+CHoCH(swing) bareng, 02/03-Sep-2026 | PASS |

Dua bug ketemu & diperbaiki selama proses (detail lengkap di changelog
10.9.4 dalam `version.json`, dan di docstring `agents/momentum_scanner.py`):
1. `high_conviction` (tag EQL) awalnya cek EQL di SELURUH histori, bukan
   window terbatas — hasilnya True di 38/38 match (jelas bug). Fix: batasi
   ke 20 bar sebelum confirmation.
2. Kalau di window yang sama ada >1 event valid (mis. BOS internal DAN
   CHoCH swing bareng, kasus nyata UANG), versi awal cuma nyimpen yang
   terdekat dan MEMBUANG sisanya. Fix: `MomentumMatch.confirmations`
   sekarang list, semua event ditampilkan (niru pola yang sudah ada di
   `agents/structure_scanner.py`).

## Yang BELUM dikerjakan / belum diuji (baca sebelum lanjut)

- **`MomentumScanner4H` (scan full universe) belum pernah dicoba sama
  sekali** — baik skala kecil maupun full ~561 ticker. `fetch_4h()` tidak
  punya caching, jadi ini beban baru yang belum pernah diuji di proyek ini.
  **Coba subset kecil dulu** sebelum full universe:
  ```python
  from agents.momentum_scanner import MomentumScanner4H
  from core.data_feed import get_catalyst_universe

  s = MomentumScanner4H()
  results, ctx = s.scan(tickers=get_catalyst_universe(full_universe=True)[:50])
  print(ctx)
  ```
- **UI wiring belum disentuh** — rename "Scan Controls" -> "Follow Whale"
  + subbab baru "Momentum" masih menunggu hasil tes di atas.
- **Flip yang berdekatan bisa menghasilkan match yang confirmations-nya
  tumpang-tindih** (contoh nyata: BUMI flip 21 Jul & 23 Jul, cuma 4 bar
  terpisah, dua-duanya nunjukkin BOS 20-Jul + CHoCH 23-Jul yang sama).
  Belum di-cluster jadi 1 kartu — sengaja ditunda supaya scope fix tetap
  sempit. Kalau nanti kelihatan duplikat di UI produksi, ini yang perlu
  disentuh duluan sebelum Fase 2 selesai.

## Catatan format arsip

Diminta RAR, environment ini tidak punya encoder `.rar` (proprietary,
tidak terpasang) — jadi `.zip` biasa, WinRAR/7-Zip buka tanpa masalah.
