"""
check_stockbit_connection.py — Uji LANGSUNG koneksi Stockbit (get_broker_summary_stockbit)
memakai ticker likuid (BBCA) yg PASTI ada data broker-nya, terpisah total dari
hasil scan whale hari ini. Ini memisahkan "apakah token & API Stockbit bekerja"
dari "apakah scan whale hari ini menemukan hasil" — dua hal yg berbeda.

Jalankan dari folder repo: python check_stockbit_connection.py
Read-only (tidak menyimpan apa pun ke broker_daily).
"""
import sys
sys.path.insert(0, ".")
from agents.ownership_agent import OwnershipAgent

oa = OwnershipAgent()
token = oa.get_stockbit_token()

if not token:
    print("❌ TOKEN TIDAK DITEMUKAN / KEDALUWARSA (>23 jam).")
    print("   Harvest ulang token dari Stockbit, lalu jalankan skrip ini lagi.")
    raise SystemExit

print(f"✅ Token ditemukan (panjang: {len(token)} karakter)\n")

TEST_TICKER = "BBCA"
print(f"Menguji get_broker_summary_stockbit('{TEST_TICKER}')...")
result = oa.get_broker_summary_stockbit(TEST_TICKER)

print(f"\nHasil mentah:")
for k, v in result.items():
    if k in ("top_buyers", "top_sellers") and isinstance(v, list):
        print(f"  {k}: {len(v)} broker")
        for b in v[:3]:
            print(f"      {b}")
    else:
        print(f"  {k}: {v}")

print("\n" + "=" * 60)
if result.get("available"):
    print("✅ KONEKSI STOCKBIT BERFUNGSI — data broker berhasil diambil.")
    print("   Kalau nanti scan whale menemukan >=1 hit dgn conviction>=4,")
    print("   enrichment + save_broker_data (fix 10.2.1) SEHARUSNYA bekerja.")
else:
    print(f"❌ KONEKSI GAGAL — reason: {result.get('reason', '?')}")
    print("   Ini masalah TERPISAH dari fix 10.2.1 (soal token/API Stockbit")
    print("   itu sendiri, bukan soal penyimpanan ke database).")
