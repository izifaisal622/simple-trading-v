"""
diagnose_extension_distribution.py — Statistik distribusi LENGKAP extension_atr
di seluruh zona WATCHING hari ini, utk kalibrasi ambang EXTENSION_SAFE_ATR
berbasis data, bukan tebakan.

Jalankan dari folder repo: python diagnose_extension_distribution.py
Read-only.
"""
import sqlite3
import statistics

conn = sqlite3.connect("logs/scan_history.db")
latest_date = conn.execute("SELECT MAX(scan_date) FROM zone_scans").fetchone()[0]
rows = conn.execute("""
    SELECT extension_atr FROM zone_scans
    WHERE scan_date = ? AND status = 'WATCHING' AND extension_atr IS NOT NULL
""", (latest_date,)).fetchall()
conn.close()

values = sorted(r[0] for r in rows if r[0] is not None)
n = len(values)
print(f"Scan date: {latest_date}")
print(f"Total zona dgn extension_atr terhitung: {n}\n")

if n == 0:
    print("Tidak ada data.")
    raise SystemExit

def pct(p):
    idx = int(n * p / 100)
    idx = min(idx, n - 1)
    return values[idx]

print("=" * 60)
print("STATISTIK DISTRIBUSI extension_atr (satuan: kelipatan ATR)")
print("=" * 60)
print(f"  Minimum        : {values[0]:.2f}x")
print(f"  P10  (10%)     : {pct(10):.2f}x")
print(f"  P25  (25%)     : {pct(25):.2f}x")
print(f"  Median (P50)   : {pct(50):.2f}x")
print(f"  P75  (75%)     : {pct(75):.2f}x")
print(f"  P90  (90%)     : {pct(90):.2f}x")
print(f"  Maximum        : {values[-1]:.2f}x")
print(f"  Rata-rata      : {statistics.mean(values):.2f}x")

print("\n" + "=" * 60)
print("SIMULASI: kalau EXTENSION_SAFE_ATR diubah, berapa zona yg TETAP")
print("kena penalti (extension_atr > ambang)?")
print("=" * 60)
for threshold in [3, 5, 6, 7, 8, 10, 12, 15]:
    n_over = sum(1 for v in values if v > threshold)
    pct_over = n_over / n * 100
    print(f"  Ambang {threshold:>2}x ATR: {n_over:>3} dari {n} zona ({pct_over:.0f}%) masih kena penalti")

print("\nSELESAI — salin SEMUA output di atas.")
