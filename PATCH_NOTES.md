# Patch 10.9.9 -> 10.9.10 — Hapus label BETA/EXPERIMENTAL + filter "berapa bar lalu"

Extract di root repo (di atas hasil 10.9.9), timpa 2 file di bawah.

## Isi paket

```
pages/2_Follow_Whale.py   <-- DIGANTI (labeling + filter dropdown)
version.json               <-- DIGANTI (10.9.9 -> 10.9.10, 232 entry lama TETAP UTUH)
```

Tidak ada file lain yang berubah — `agents/momentum_scanner.py`,
`agents/early_watch_scanner.py`, `orchestrator.py` TIDAK disentuh sama
sekali (definisi/logic scan 100% tidak berubah).

## Apa yang berubah

1. **Label dihapus** (kedua section, sesuai konfirmasi kamu):
   - `◆ MOMENTUM (BETA)` → `◆ MOMENTUM`
   - `◆ EARLY WATCH (EXPERIMENTAL)` → `◆ EARLY WATCH`
   - Disclaimer besar `⚠ EXPERIMENTAL, BELUM tervalidasi...` di Early Watch
     dipersingkat jadi caption definisi biasa.

   **Catatan jujur** (tetap saya cantumkan sebagai komentar di kode, bukan
   di UI): definisi Early Watch v2 secara fakta belum pernah dihitung
   hit-rate/backtest-nya — hilangnya label bukan berarti fitur ini sudah
   "terbukti", cuma kamu yang memutuskan tidak perlu peringatan itu terus
   ditampilkan karena desainnya memang menyerahkan penyaringan choppy/
   bersih ke chart manual kamu, bukan ke algoritma. Kalau nanti mau
   backtest v2 baru, itu kerjaan terpisah.

2. **Filter dropdown "berapa bar lalu"** — ditambahkan ke KEDUA section
   (Momentum & Early Watch), muncul di atas grid kartu, dengan pilihan:
   `Semua / Bar ini (0) / ≤1 bar lalu / ≤2 bar lalu / ≤3 bar lalu / ≤4 bar
   lalu / ≤5 bar lalu` (mengikuti `RECENT_WINDOW=5` yang dipakai kedua
   scanner). Filter ini HANYA menyaring kartu yang tampil — angka metric
   di atas (UNIVERSE/FETCH OK/MATCH/dst) tetap laporan scan penuh, tidak
   ikut berubah. Saat filter aktif, muncul caption "Menampilkan N dari M
   match/state". Kalau filter menyaring sampai 0 hasil, muncul empty-state
   baru yang beda dari "belum ada hasil scan sama sekali".

## Verifikasi sebelum dikirim

- `py_compile pages/2_Follow_Whale.py` (2618 baris) — PASS.
- Simulasi logic filter (list objek fake `bars_between` 0/1/2/3/5, x 7
  pilihan dropdown) — PASS, hasil sesuai ekspektasi untuk semua pilihan
  termasuk batas ≤4 dan ≤5.
- `json.loads(version.json)` — PASS, struktur valid, 233 entry total.

## Yang BELUM diuji

Render visual browser dengan dropdown filter yang sebenarnya (belum
pernah diklik live) — silakan cek setelah patch di-apply: buka dashboard,
pastikan dropdown filter muncul di kedua section dan kartu benar-benar
berkurang/bertambah sesuai pilihan filter.
