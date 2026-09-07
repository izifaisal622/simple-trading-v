# Patch 10.9.7 -> 10.9.8 — Redefinisi Early Watch: 2 syarat saja

Extract di root repo (di atas hasil 10.9.7 — kalau kamu BELUM extract
10.9.7 sama sekali, extract patch ini langsung, tidak masalah karena
`pages/2_Follow_Whale.py` & `version.json` di sini SUDAH termasuk semua
perubahan 10.9.7 + 10.9.8 sekaligus).

## Isi paket

```
agents/early_watch_scanner.py   <-- DITULIS ULANG TOTAL (bukan file baru,
                                     TIMPA yang 10.9.7 kalau sudah ada)
pages/2_Follow_Whale.py         <-- DIGANTI (card Early Watch redesign)
version.json                    <-- DIGANTI (10.9.7 -> 10.9.8, 1 entry
                                     baru, 230 entry lama TETAP UTUH)
```

## Kenapa berubah lagi secepat ini

Kamu lihat hasil backtest 10.9.7 (BUMI 36%, SINI 29% match dgn syarat
wajib BOS/CHoCH) dan bilang itu kerumitan yang tidak perlu — bukan
karena angkanya jelek, tapi karena definisinya bukan yang kamu mau.
Permintaanmu: **cuma 2 syarat** — VIDYA (band luar) merah + garis
Momentum (centerline) hijau. Choppy atau bersih kamu yang nilai manual
dari chart. COCH/BOS/EQL turun status jadi tag informasi saja.

File 10.9.7 belum pernah kamu jalankan live, jadi ini bukan "ganti fitur
yang sudah dipakai" — murni definisi lama diganti sebelum sempat dipakai
sama sekali.

## Definisi baru (v2)

**Wajib (2 syarat, keduanya harus benar):**
1. Band luar VIDYA (`is_trend_up`) MASIH merah di bar terakhir (sekarang).
2. Ada cross Close ke ATAS centerline VIDYA (`vidya_val`, tanpa offset
   ATR) dalam 5 bar terakhir, DAN band luar masih merah PERSIS di bar
   cross itu.

**Tag saja, TIDAK wajib ada:**
- BOS/CHoCH dalam ±5 bar dari titik cross — ditampilkan kalau ada.
- EQL dalam 20 bar sebelum titik cross — ditampilkan kalau ada.
- Kartu TANPA tag sama sekali itu SAH, bukan dibuang.

## Konsekuensi yang perlu kamu tahu

Scan Early Watch v2 akan menampilkan **LEBIH BANYAK** ticker per scan
dibanding v1 — filternya jauh lebih longgar (2 syarat vs 4). Ini SESUAI
permintaanmu (kamu yang saring manual), tapi berarti:
- Jangan kaget kalau hasil scan jadi panjang.
- Angka 30-36% dari backtest v1 **TIDAK BERLAKU** untuk v2 — belum ada
  angka hit-rate baru sama sekali untuk definisi ini, karena definisinya
  sengaja dibuat "tidak menyaring", validasinya ada di mata kamu pas
  baca chart.

## Verifikasi sebelum dikirim

- `py_compile` `agents/early_watch_scanner.py` — PASS.
- 2 self-test skenario (bukan cuma "tidak error", ada assert eksplisit):
  - **A**: potong data persis di bar centerline-cross (band masih merah)
    → HARUS ketemu state, tag BOS/CHoCH boleh kosong. PASS.
  - **B**: potong data 1 bar SETELAH band confirm jadi hijau → HARUS
    `None` (negative test — begitu band beneran hijau, itu domain
    Momentum, bukan Early Watch lagi). PASS.
- `py_compile` `pages/2_Follow_Whale.py` (2519 baris) — PASS.
- Smoke test terpisah: card-HTML-builder dijalankan terhadap
  `EarlyWatchState` ASLI, termasuk jalur TANPA tag (fallback teks
  "(tidak ada tag...)") — PASS, HTML valid, tidak ada `var(--x)` konkat
  suffix opacity, tidak ada nested f-string.

## Yang BELUM diuji

1. **Scan live full-universe** dengan definisi v2 — belum pernah
   dijalankan terhadap data real sama sekali (baik v1 maupun v2).
2. **Render visual browser** — `streamlit run gate.py`, cek kartu Early
   Watch tampil dengan info Close/centerline/jarak bar, dan kartu tanpa
   tag BOS/CHoCH menampilkan fallback teks dengan benar (bukan kosong
   atau error).

Kalau live scan ternyata TERLALU banyak hasil (choppy market bikin
banyak ticker lolos 2 syarat ini), opsinya nanti: perketat window 5 bar
jadi lebih pendek, atau tambah 1 syarat longgar (bukan BOS/CHoCH wajib
lagi, tapi mis. minimal jarak dari band luar) — didiskusikan lagi kalau
kejadian, bukan diasumsikan sekarang.
