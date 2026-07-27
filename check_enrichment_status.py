"""
check_enrichment_status.py — Cek apakah enrichment Stockbit (broker_live)
pernah berhasil terisi True di hasil scan manapun yang tersimpan, terlepas
dari apakah scan HARI INI menemukan whale atau tidak.

Jalankan dari folder repo: python check_enrichment_status.py
Read-only.
"""
import json
from pathlib import Path

f = Path("logs/daily_results.json")
if not f.exists():
    print("daily_results.json belum ada.")
    raise SystemExit

d = json.loads(f.read_text(encoding="utf-8"))
whale_results = d.get("whale_results", [])
scan_date = d.get("whale_date", d.get("date", "?"))

print(f"Scan date tersimpan: {scan_date}")
print(f"Jumlah whale_results tersimpan: {len(whale_results)}")

if not whale_results:
    print("\nKosong — tidak ada apa pun utk dicek soal enrichment saat ini.")
    print("(Ini konsisten dgn 'WHALE ALERTS 0' yg kau lihat di halaman.)")
    raise SystemExit

print(f"\n{'Ticker':<10} {'Conviction':>10} {'broker_live':>12} {'top_buyers':>11} {'top_sellers':>12}")
print("-" * 60)
n_live = 0
for r in whale_results:
    bl = r.get("broker_live", False)
    if bl:
        n_live += 1
    print(f"{r.get('ticker','?'):<10} {r.get('conviction','?'):>10} {str(bl):>12} "
          f"{len(r.get('top_buyers',[])):>11} {len(r.get('top_sellers',[])):>12}")

print(f"\nTotal ticker dgn broker_live=True: {n_live} dari {len(whale_results)}")
if n_live == 0:
    print("\n⚠ TIDAK ADA yg broker_live=True — berarti enrich_top_results()")
    print("  sendiri gagal mengisi data (bukan soal save_broker_data).")
    print("  Kemungkinan: token dianggap invalid/expired oleh Stockbit saat")
    print("  scan ini berjalan, atau format API Stockbit berubah.")
else:
    print("\n✅ Enrichment Stockbit BERFUNGSI (ada broker_live=True).")
    print("  Kalau broker_daily TETAP kosong meski ini True, baru itu bug baru.")
