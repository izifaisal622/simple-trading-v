# Patch 10.9.5 -> 10.9.6 — Fase 2: UI wiring Momentum (rename + section baru)

Extract di root repo (di atas hasil 10.9.5), timpa 2 file di bawah.

## Isi paket

```
pages/2_Follow_Whale.py   <-- DIGANTI (rename section + tambah section MOMENTUM)
version.json              <-- DIGANTI (10.9.5 -> 10.9.6, 1 entry baru paling atas,
                                228 entry lama TETAP UTUH)
```

Tidak ada perubahan ke `agents/momentum_scanner.py` atau file produksi lain
manapun — Fase 2 murni konsumsi `MomentumScanner4H` yang sudah ada & tervalidasi
(v10.9.4/10.9.5), tidak menyentuh logikanya sama sekali.

## Yang berubah di pages/2_Follow_Whale.py

1. **Rename**: `sec_head("◆ SCAN CONTROLS")` (baris 307) -> `sec_head("◆ FOLLOW WHALE")`.
2. **Section baru "MOMENTUM (BETA)"** — tombol `SCAN MOMENTUM`, manggil
   `MomentumScanner4H().scan()` (lazy import, sama pola dgn `WhaleScanner`
   di file yang sama), render kartu per ticker: jarak flip->konfirmasi (bar),
   badge tiap confirmation (mis. `BOS(internal)`), badge `★ HIGH CONVICTION`
   kalau ada EQL, badge delta-volume. Metric row di atas: universe/fetch
   ok/match/high-conviction/waktu scan.

## Keputusan penempatan (PENTING, dikonfirmasi 2x dgn kamu di chat)

Kamu awalnya minta MOMENTUM persis sebelum INTEL PANEL. Investigasi kode
nemu constraint baru: **INTEL PANEL (dan semua section sesudahnya sampai
OUTCOME TRACKER) ada DI DALAM `if whale_results:`** — cuma tampil kalau
sudah pernah scan Whale. Kalau MOMENTUM ditaruh di situ, section itu ikut
"tersembunyi" sampai user scan Whale dulu (~5-6 menit), padahal
`MomentumScanner4H` scanner independen yang tidak butuh hasil Whale sama
sekali.

**Keputusan final (kamu pilih "Recommended")**: MOMENTUM ditaruh SEGERA
setelah trigger FOLLOW WHALE, SEBELUM 8 section whale existing (Akumulasi
Broker, Hengky Lot Math, dst) — jadi section ke-2 dari atas di halaman,
SELALU kelihatan tanpa syarat scan Whale dulu. Pola ini identik dengan
GOLDEN SETUP 4H & BOS/CHoCH/EQL BETA di `pages/1_VIDYA_SMC_Zone.py`
(keduanya juga sengaja independen, karena pernah ada bug NameError nyata
di v10.9.0 gara-gara section baru ke-nest di dalam `if` section lain).

## Verifikasi sebelum dikirim

- `py_compile` + `ast.parse` `pages/2_Follow_Whale.py` lolos (2397 baris).
- Smoke test TERPISAH: fungsi pembangun HTML kartu dijalankan terhadap
  `MomentumMatch` ASLI (dari `find_all_momentum_events()` atas data
  sintetis yang sama dgn self-test `momentum_scanner.py`) — lolos tanpa
  error, HTML valid (semua warna hex resolved, tidak ada `var(--x)`
  dikonkat dgn suffix opacity, tidak ada nested f-string — ikut semua
  aturan proyek).

## Yang BELUM diuji

**Render visual di browser Streamlit terhadap data real.** Jalankan
`streamlit run gate.py`, buka halaman Follow Whale, cek:
1. Section "FOLLOW WHALE" (rename) tampil normal, trigger scan whale tetap
   jalan seperti biasa.
2. Section "MOMENTUM (BETA)" tampil SEGERA di bawahnya (sebelum Akumulasi
   Broker dkk) — TIDAK perlu scan Whale dulu untuk melihatnya.
3. Klik SCAN MOMENTUM — spinner ~5-6 menit, lalu kartu hasil tampil sesuai
   harapan (bandingkan dgn hasil trial `momentum_scan_trial.py` yang sudah
   kamu jalankan — harusnya jumlah match & ticker yang sama, mis. UANG
   dgn badge BOS(internal)+CHOCH(swing)).

Kalau render OK, ini rilis Fase 1+2 penuh untuk fitur Momentum.
