"""
momentum_scan_trial.py — Coba MomentumScanner4H (agents/momentum_scanner.py)
di SUBSET KECIL universe dulu, sebelum full ~561 ticker. Ini scan pertama
yang PERNAH dijalankan sama sekali di proyek ini (baca CATATAN PENTING (2)
di docstring agents/momentum_scanner.py soal kenapa harus hati-hati) —
tujuannya cek dua hal:
  1. Apakah fetch_4h() chunked (chunk=15, delay 3s) jalan tanpa kena
     rate-limit Yahoo di skala ini.
  2. Berapa lama waktu yang dibutuhkan, buat estimasi kasar full-universe.

Cara pakai:
    python momentum_scan_trial.py          (default 50 ticker pertama)
    python momentum_scan_trial.py 100      (custom N ticker)

Kalau ini lancar (tidak ada banyak "fetch gagal" di log, waktu masih
wajar), baru pertimbangkan naik ke subset lebih besar atau full universe.
JANGAN langsung lompat ke full 561 dari sini.
"""

import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

from agents.momentum_scanner import MomentumScanner4H
from core.data_feed import get_catalyst_universe

DEFAULT_N = 50


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_N

    print(f"\nAmbil universe full (get_catalyst_universe(full_universe=True)), "
          f"ambil {n} ticker pertama buat trial...")
    t0 = time.time()
    universe = get_catalyst_universe(full_universe=True)
    t_universe = time.time() - t0
    print(f"Universe penuh: {len(universe)} ticker (fetch daftar: {t_universe:.1f}s)")

    subset = universe[:n]
    print(f"Trial scan {len(subset)} ticker: {subset}\n")

    scanner = MomentumScanner4H()
    t0 = time.time()
    results, ctx = scanner.scan(tickers=subset)
    elapsed = time.time() - t0

    print(f"\n{'=' * 70}\nHASIL TRIAL — {len(subset)} ticker, {elapsed:.1f} detik "
          f"({elapsed / max(len(subset), 1):.2f} detik/ticker)\n{'=' * 70}")
    print(f"  Context: {ctx}\n")

    if not results:
        print("  Tidak ada match fresh di subset ini saat ini (wajar kalau "
              "subset kecil/acak — momentum fresh itu jarang per definisi).")
    else:
        print(f"  {len(results)} match ditemukan:\n")
        for m in sorted(results, key=lambda r: r.bars_between):
            print(f"    {m.ticker:6s} | flip={m.flip_date.date()} | "
                  f"{m.kinds_label} | jarak={m.bars_between} bar | "
                  f"high_conviction={m.high_conviction} | "
                  f"delta_volume_pct={m.delta_volume_pct}")

    print(f"\n{'=' * 70}\nESTIMASI FULL UNIVERSE ({len(universe)} ticker)\n{'=' * 70}")
    est_seconds = elapsed / max(len(subset), 1) * len(universe)
    print(f"  Kasar (linear dari trial ini): ~{est_seconds / 60:.1f} menit.")
    print(f"  CATATAN: ini ekstrapolasi linear sederhana, BUKAN jaminan — "
          f"rate-limit Yahoo kalau muncul di skala lebih besar akan bikin "
          f"lebih lambat dari estimasi ini (chunk gagal berulang, retry, dst).")


if __name__ == "__main__":
    main()
