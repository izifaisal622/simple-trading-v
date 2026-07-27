"""
check_stockbit_raw.py — Panggil endpoint /marketdetectors LANGSUNG (bypass
parser _parse_stockbit_broker yg lama), tampilkan struktur JSON mentah biar
bisa kita lihat bentuk data sesungguhnya sebelum parser diperbaiki.

Jalankan dari folder repo: python check_stockbit_raw.py
Read-only.
"""
import sys, json
sys.path.insert(0, ".")
from agents.ownership_agent import OwnershipAgent

oa = OwnershipAgent()
token = oa.get_stockbit_token()
if not token:
    print("❌ Token tidak ditemukan/kedaluwarsa.")
    raise SystemExit

import requests
url = ("https://exodus.stockbit.com/marketdetectors/BBCA"
       "?transaction_type=TRANSACTION_TYPE_NET"
       "&market_board=MARKET_BOARD_REGULER"
       "&investor_type=INVESTOR_TYPE_ALL"
       "&limit=25"
       "&period=BROKER_SUMMARY_PERIOD_LATEST")
headers = {
    "Authorization": f"Bearer {token}",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://stockbit.com/",
    "Origin": "https://stockbit.com",
}
r = requests.get(url, headers=headers, timeout=8)
print(f"Status code: {r.status_code}\n")

if r.status_code != 200:
    print(f"Body mentah (gagal):\n{r.text[:1000]}")
    raise SystemExit

data = r.json()
print("=" * 60)
print("STRUKTUR JSON MENTAH (top-level keys):")
print("=" * 60)
print(list(data.keys()) if isinstance(data, dict) else f"(bukan dict, tipe: {type(data)})")

print("\n" + "=" * 60)
print("FULL JSON (rapi, maks 3000 karakter pertama):")
print("=" * 60)
pretty = json.dumps(data, indent=2, ensure_ascii=False)
print(pretty[:20000])
if len(pretty) > 20000:
    print(f"\n... (dipotong, total {len(pretty)} karakter)")
