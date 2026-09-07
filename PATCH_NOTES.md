# Patch 10.9.4 -> 10.9.5 — FIX observability di fase hitung MomentumScanner4H

Ini FIX KECIL, murni tambahan logging — bukan perubahan logika match.
Extract di root repo (yang sudah berisi hasil patch 10.9.4 sebelumnya),
timpa 2 file di bawah.

## Isi paket

```
agents/momentum_scanner.py       <-- DIGANTI (tambah heartbeat log di
                                      fase hitung match MomentumScanner4H.scan(),
                                      lihat detail di bawah)
version.json                     <-- DIGANTI (10.9.4 -> 10.9.5, 1 entry baru
                                      paling atas, 227 entry lama TETAP UTUH)
```

Tidak ada perubahan ke `momentum_scan_trial.py`, `validate_momentum_cases.py`,
`diagnose_momentum_window.py`, atau file lain manapun — log baru otomatis
kelihatan di trial script karena sudah pakai `logging.basicConfig` yang sama.

## Kenapa fix ini dibuat

Trial full-universe 560 ticker yang kamu jalankan (2026-09-07) outputnya
berhenti PERSIS di baris:

```
10:49:58 [INFO] [Momentum4H] Fetch selesai: 519/560 berhasil (41 gagal/skip)
```

tanpa progress apa pun sesudahnya sampai kamu copy-paste. Diselidiki: fase
SESUDAH fetch (loop `find_latest_momentum_match()` per ticker — CPU-bound,
bukan network) memang **nol logging sama sekali** sebelum fix ini — jadi dari
terminal tidak bisa dibedakan "masih jalan", "hang", atau "crash silent".

## Yang berubah

`MomentumScanner4H.scan()` sekarang log:
1. `Mulai hitung match (N ticker)...` — begitu fase fetch selesai.
2. `Hitung match: X/N ticker diproses (Y match sejauh ini, Zs)` — tiap 50
   ticker diproses.
3. `Hitung match selesai: N ticker dalam Zs (C crash)` — begitu loop kelar.

Murni tambahan `logger.info(...)` di dalam loop yang sudah ada — urutan,
isi, dan hasil match **tidak berubah sama sekali**. Self-test `__main__`
(data sintetis) dijalankan ulang setelah edit, hasilnya identik (1 match,
sama seperti sebelum fix):

```
[self-test] total match sepanjang histori sintetis: 1
  flip=2024-02-17 bar=283 | CHOCH(internal)@2024-02-17 | jarak=3 bar | high_conviction=False
[self-test] PASS
```

## Yang BELUM diuji

Fix ini sendiri belum pernah dilihat jalan di terminal kamu (risiko rendah,
murni logging) — tolong jalankan ulang `python momentum_scan_trial.py 560`
sekali lagi setelah patch ini di-extract, supaya:
1. Heartbeat baru kelihatan jalan seperti yang diharapkan.
2. Kita AKHIRNYA bisa lihat blok `HASIL TRIAL` (daftar match) dan
   `ESTIMASI FULL UNIVERSE` yang selama ini belum pernah kelihatan di 2x
   percobaan sebelumnya (baik yang 50 ticker maupun yang 560 ticker).

Kalau kali ini ternyata prosesnya memang hang di tengah jalan (bukan cuma
soal logging), heartbeat baru ini akan menunjukkan PERSIS di ticker keberapa
macetnya — itu info yang kita tidak punya sebelumnya.
