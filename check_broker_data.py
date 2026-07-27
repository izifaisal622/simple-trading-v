"""
check_broker_data.py — Cek volume data broker_daily yang sudah terkumpul.
Jalankan dari folder repo: python check_broker_data.py
Read-only, tidak mengubah data apa pun.
"""
import sqlite3
from pathlib import Path

db_path = Path("logs/broker_history.db")
if not db_path.exists():
    print("broker_history.db BELUM ADA sama sekali — token Stockbit mungkin")
    print("belum pernah aktif/fresh saat scan berjalan.")
    raise SystemExit

conn = sqlite3.connect(str(db_path))

total_rows = conn.execute("SELECT COUNT(*) FROM broker_daily").fetchone()[0]
print(f"Total baris broker_daily: {total_rows}")

if total_rows == 0:
    print("Tabel ada tapi KOSONG.")
    raise SystemExit

n_tickers = conn.execute("SELECT COUNT(DISTINCT ticker) FROM broker_daily").fetchone()[0]
n_dates = conn.execute("SELECT COUNT(DISTINCT date) FROM broker_daily").fetchone()[0]
date_range = conn.execute("SELECT MIN(date), MAX(date) FROM broker_daily").fetchone()
print(f"Ticker unik: {n_tickers} | Tanggal unik: {n_dates} | Rentang: {date_range[0]} s/d {date_range[1]}")

print("\nTop 10 ticker dengan riwayat broker TERBANYAK (hari):")
rows = conn.execute("""
    SELECT ticker, COUNT(DISTINCT date) as n_hari
    FROM broker_daily GROUP BY ticker ORDER BY n_hari DESC LIMIT 10
""").fetchall()
for t, n in rows:
    print(f"  {t}: {n} hari")

print("\nDistribusi: berapa ticker yang punya >= 3 hari data berturut-turut (kandidat 'defend 3 hari')?")
rows = conn.execute("SELECT ticker, COUNT(DISTINCT date) as n FROM broker_daily GROUP BY ticker").fetchall()
n_ge3 = sum(1 for t, n in rows if n >= 3)
print(f"  {n_ge3} dari {len(rows)} ticker punya >=3 hari data (belum tentu BERTURUT-TURUT, cuma total hari)")

conn.close()
