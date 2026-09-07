# Patch 10.9.6 -> 10.9.7 — Fitur baru EXPERIMENTAL: Early Watch scanner

Extract di root repo (di atas hasil 10.9.6), timpa/tambah 3 file di bawah.

## Isi paket

```
agents/early_watch_scanner.py   <-- BARU (file baru, ADITIF)
pages/2_Follow_Whale.py         <-- DIGANTI (tambah section EARLY WATCH baru)
version.json                    <-- DIGANTI (10.9.6 -> 10.9.7, 1 entry baru
                                     paling atas, 229 entry lama TETAP UTUH)
```

Tidak ada perubahan ke `agents/momentum_scanner.py`, `core/ob_engine.py`,
`core/structure_signals.py`, atau file produksi lain manapun.

## Latar belakang (kenapa fitur ini ada)

Setelah Momentum (BETA) di-ship (v10.9.4-10.9.6), kamu menantang premisnya
sendiri: *"kalau VIDYA (band luar) sudah beralih dari merah ke hijau, itu
sudah TELAT."* Early Watch adalah hasil investigasi konsep itu — sinyal
LEBIH DINI dari Momentum, bukan pengganti.

## Definisi mekanis

1. Close cross ke ATAS garis **centerline** VIDYA (`_vidya_calc`, TANPA
   offset ATR — beda dari upper/lower band yang dipakai Momentum).
2. HANYA dihitung kalau terjadi SAAT band luar (`is_trend_up`) **masih
   merah** — begitu band luar confirmed, itu domain Momentum, bukan Early
   Watch lagi.
3. Flicker yang berdekatan (gap <=5 bar) digabung jadi 1 **episode** —
   supaya fase choppy (flicker hijau-merah berkali-kali) tidak
   menghasilkan alert duplikat.
4. Episode WAJIB punya minimal 1 BOS/CHoCH (union, scope apapun) dalam
   ±5 bar dari rentang episode. Episode tanpa ini dibuang sebagai noise.

## PENTING — level validasi BEDA dari Momentum, WAJIB dibaca

**Momentum** (v10.9.4) divalidasi 3/3 terhadap study case chart nyata
(BUMI/SINI/UANG) SEBELUM di-ship.

**Early Watch BELUM** melewati validasi setara. Yang sudah diuji lewat 3
diagnostic script read-only (`diagnose_early_momentum.py` →
`diagnose_early_watch_concept.py` → `diagnose_early_watch_episodes.py`,
semua masih ada di root repo hasil sesi ini):

- BUMI: 25 episode sepanjang ~2.5 tahun histori, 9 match BOS/CHoCH = **36%**.
- SINI: 21 episode, 6 match = **29%**.
- Hipotesis "flicker berulang bikin angka ini keliatan rendah karena
  duplicate-counting" **TERBUKTI SALAH** — setelah episode-clustering,
  angka cuma bergeser tipis (30%→36%, 25%→29%). Bukan sumber noise utama.

Yang **BELUM** diuji: apakah 30-36% episode yang match ini BENAR lebih
sering mendahului breakout asli dibanding yang tidak match (predictive
value). Keputusan eksplisit kamu (2026-09-07): **ship apa adanya dengan
label EXPERIMENTAL**, validasi lanjut dari observasi pemakaian live —
bukan dari diagnostic tambahan.

Konsekuensinya di UI: section ini nampilin disclaimer angka ~30% itu
langsung di caption, dan kartu hasil pakai warna amber (C_WARNING) yang
sengaja beda dari Momentum — supaya tidak terlihat se-meyakinkan fitur
yang sudah tervalidasi.

## Penempatan UI

`pages/2_Follow_Whale.py`: section **"EARLY WATCH (EXPERIMENTAL)"**
ditaruh SEGERA setelah section MOMENTUM (BETA), sebelum 8 section whale
existing — standalone, di luar `if whale_results:`, pola identik dengan
MOMENTUM & GOLDEN SETUP 4H (independen dari hasil scan Whale, jadi selalu
kelihatan tanpa perlu scan Whale dulu).

## Verifikasi sebelum dikirim

- `py_compile` + `ast.parse` `agents/early_watch_scanner.py` dan
  `pages/2_Follow_Whale.py` (2513 baris) — PASS.
- Self-test module (`python -m agents.early_watch_scanner`): skenario
  sintetis yang SUDAH diverifikasi manual (centerline cross 1 bar sebelum
  band confirm, berjarak 4 bar dari CHoCH) — assert eksplisit ketemu
  minimal 1 episode, BUKAN cuma "tidak error". PASS.
- Smoke test terpisah: card-HTML-builder dijalankan terhadap
  `EarlyWatchEvent` ASLI (dari `find_all_early_watch_episodes()` atas
  data sintetis yang sama) — HTML valid, semua warna hex resolved, tidak
  ada `var(--x)` dikonkat suffix opacity, tidak ada nested f-string.
  PASS.

## Yang BELUM diuji (sama seperti pola v10.9.6)

1. **Scan live full-universe** (~560 ticker) — belum pernah dijalankan
   dengan `EarlyWatchScanner4H().scan()` di data real. Coba scope kecil
   dulu kalau ragu (`scan(tickers=[...50 ticker...])`) sebelum full
   universe, ikuti rekomendasi yang sama seperti Momentum dulu.
2. **Render visual browser** — `streamlit run gate.py`, buka Follow
   Whale, cek section "EARLY WATCH (EXPERIMENTAL)" muncul di bawah
   MOMENTUM (BETA), tombol SCAN EARLY WATCH jalan, kartu hasil tampil
   dengan accent warna amber.

Kalau live scan & render OK, ini rilis fitur Early Watch (EXPERIMENTAL)
penuh.
