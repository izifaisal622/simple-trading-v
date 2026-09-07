# Patch 10.9.8 -> 10.9.9 — Hasil Momentum & Early Watch otomatis ada saat dashboard dibuka

Extract di root repo (di atas hasil 10.9.8), timpa 5 file di bawah.

## Isi paket

```
agents/momentum_scanner.py      <-- DIGANTI (tambah 2 fungsi serialisasi)
agents/early_watch_scanner.py   <-- DIGANTI (tambah 2 fungsi serialisasi)
orchestrator.py                 <-- DIGANTI (2 modul baru + wiring --mode all)
pages/2_Follow_Whale.py         <-- DIGANTI (baca cache di page-load + tombol
                                     manual ikut nulis balik ke cache)
version.json                    <-- DIGANTI (10.9.8 -> 10.9.9, 231 entry
                                     lama TETAP UTUH)
```

## Mekanisme (meniru pola Whale scan yang SUDAH ADA di repo kamu sendiri)

Kamu mungkin belum sadar, tapi Whale scan sudah lama begini: `orchestrator.py`
jalan headless (CLI, tanpa buka dashboard), simpan hasil ke
`logs/daily_results.json`, dan `pages/2_Follow_Whale.py` baca file itu di
AWAL script — jadi begitu kamu buka dashboard, Whale card sudah terisi
tanpa klik apa pun. Momentum & Early Watch sekarang ikut pola yang SAMA
PERSIS. Tidak ada arsitektur baru di sini.

Kerumitan satu-satunya: `MomentumMatch`/`EarlyWatchState` itu Python
dataclass (bukan dict polos seperti hasil Whale), jadi tidak bisa langsung
`json.dumps()`. Makanya ada 4 fungsi konversi baru (`*_to_dict`/`*_from_dict`
di masing-masing file `agents/`) — sudah diverifikasi round-trip penuh
(serialize → json.dumps → json.loads → deserialize, semua field termasuk
tag BOS/CHoCH/EQL nested cocok persis).

## Keputusan yang kamu pilih (dikonfirmasi sebelum saya kerjakan)

1. **Digabung ke `orchestrator.py --mode all`** — bukan mode terpisah yang
   dijadwalkan sendiri. Konsekuensinya: setiap kali kamu jalankan
   `orchestrator.py` mode `all` (atau `weekly`), run itu jadi **~10-12
   menit lebih lama** dari sebelumnya (2x scan 4H tanpa cache, sequential
   setelah EMA/Whale/MSCI).
2. Instruksi Windows Task Scheduler disertakan di bawah.

**Hal yang perlu kamu pikirkan sendiri (saya tidak asumsikan jawabannya):**
kalau kamu cuma jadwalkan `--mode all` SEKALI SEHARI (mis. jam buka pasar),
cache Momentum/Early Watch di dashboard cuma ke-refresh SEKALI SEHARI juga
— padahal timeframe-nya 4H (harusnya idealnya di-refresh tiap 4 jam selama
jam bursa). Kalau itu masalah buat kamu, dua modul ini SUDAH punya mode CLI
sendiri (`--mode momentum` / `--mode early_watch`) yang bisa kamu jadwalkan
LEBIH SERING lewat Task Scheduler kedua yang terpisah — tanpa perlu ubah
kode apa pun lagi, tinggal buat 1 scheduled task tambahan. Keputusan ini
sengaja saya serahkan ke kamu, bukan saya tebak.

## Windows Task Scheduler — command yang tinggal dipakai

1. Cek path python kamu dulu di PowerShell (di folder repo):
   ```powershell
   where python
   ```
   Salin path yang keluar (mis. `C:\Users\<nama>\AppData\Local\Programs\Python\Python312\python.exe`
   — kalau kamu pakai venv, pakai path python.exe DI DALAM venv itu).

2. **Test manual dulu SEBELUM dijadwalkan** (penting — belum pernah diuji
   live sama sekali):
   ```powershell
   cd "C:\Simple Trading\simple-trading-v"
   python orchestrator.py --mode momentum
   python orchestrator.py --mode early_watch
   ```
   Kalau dua-duanya jalan tanpa error, baru aman dimasukkan ke `--mode all`.

3. Buka **Task Scheduler** → **Create Task** (bukan "Create Basic Task",
   supaya opsi lebih lengkap):
   - **General**: Name = `STV Orchestrator Daily`. Centang "Run whether
     user is logged on or not" kalau mau tetap jalan walau kamu logout.
   - **Triggers** → New → Daily, set jam yang kamu mau (mis. sebelum jam
     bursa buka).
   - **Actions** → New:
     - Program/script: paste path python.exe dari langkah 1.
     - Add arguments: `orchestrator.py --mode all`
     - Start in: `C:\Simple Trading\simple-trading-v`
   - **Conditions**: uncheck "Start the task only if the computer is on
     AC power" kalau ini laptop dan sering jalan pakai baterai.
   - Save, masukkan password Windows kamu kalau diminta.

4. (Opsional, kalau kamu mau refresh 4H lebih sering dari sekali sehari)
   Buat task KEDUA terpisah, Trigger "Daily" tapi centang "Repeat task
   every: 4 hours, for a duration of: 1 day", Action argumen
   `orchestrator.py --mode momentum` (dan task ketiga sejenis untuk
   `--mode early_watch`, atau gabung keduanya dalam satu .bat file kalau
   mau 1 task saja).

## Verifikasi sebelum dikirim

- Round-trip test (`to_dict` → `json.dumps` → `json.loads` → `from_dict`)
  untuk `MomentumMatch` DAN `EarlyWatchState`, semua field termasuk nested
  `StructureEvent` confirmations — PASS, cocok persis dengan objek asli.
- Simulasi end-to-end: tulis file gaya `orchestrator.py` (fungsi asli, bukan
  mock) lalu baca gaya page-load `pages/2_Follow_Whale.py` (fungsi asli) —
  PASS, ticker & tag terekonstruksi benar.
- `py_compile` ke-4 file — PASS.
- `orchestrator.py --help` dijalankan langsung, `--mode` sudah menampilkan
  pilihan `momentum` dan `early_watch`.
- Self-test kedua scanner (`python -m agents.momentum_scanner` &
  `python -m agents.early_watch_scanner`) dijalankan ULANG setelah
  penambahan fungsi serialisasi — hasil IDENTIK dengan sebelumnya (tidak
  ada regresi logika).

## Yang BELUM diuji

1. **`orchestrator.py --mode momentum` / `--mode early_watch` / `--mode all`
   di mesin dengan akses data real** — belum pernah dijalankan live sama
   sekali (baik CLI-nya maupun tulis-ke-file-nya). WAJIB dites manual
   (langkah 2 di atas) sebelum dipercaya jalan otomatis tanpa pengawasan.
2. **Render visual browser** — buka dashboard SETELAH `orchestrator.py
   --mode momentum`/`early_watch` sukses jalan minimal sekali, cek section
   Momentum & Early Watch di halaman Follow Whale SUDAH terisi tanpa klik
   SCAN, dan tombol SCAN manual tetap berfungsi + ikut menyimpan hasil
   barunya (buka dashboard lagi, harus tetap kelihatan tanpa scan ulang).
