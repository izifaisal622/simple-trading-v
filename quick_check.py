"""
Sanity check cepat — BUKAN validasi formal (n masih kecil).
Jalankan dari folder repo: python quick_check.py
Read-only, tidak mengubah data apa pun.
"""
import sqlite3

conn = sqlite3.connect("logs/scan_history.db")

print("=" * 70)
print("WHALE — conviction bucket vs fwd_ret_5d")
print("=" * 70)
rows = conn.execute("""
    SELECT
        CASE
            WHEN conviction >= 8 THEN '8-10 (tinggi)'
            WHEN conviction >= 5 THEN '5-7 (sedang)'
            ELSE '0-4 (rendah)'
        END AS bucket,
        COUNT(*) AS n,
        ROUND(AVG(fwd_ret_5d) * 100, 2) AS avg_ret_pct,
        ROUND(MIN(fwd_ret_5d) * 100, 1) AS worst_pct,
        ROUND(MAX(fwd_ret_5d) * 100, 1) AS best_pct,
        SUM(CASE WHEN fwd_ret_5d > 0 THEN 1 ELSE 0 END) AS n_positif
    FROM whale_scans
    WHERE fwd_ret_5d IS NOT NULL
    GROUP BY bucket
    ORDER BY bucket DESC
""").fetchall()
print(f"{'bucket':<15} {'n':>4} {'avg%':>8} {'worst%':>8} {'best%':>8} {'n_positif':>10}")
for r in rows:
    print(f"{r[0]:<15} {r[1]:>4} {r[2] if r[2] is not None else 0:>8} {r[3] if r[3] is not None else 0:>8} {r[4] if r[4] is not None else 0:>8} {r[5]:>10}")

print()
print("=" * 70)
print("WHALE — quality (SMART/UNCERTAIN/dst) vs fwd_ret_5d")
print("=" * 70)
rows = conn.execute("""
    SELECT quality, COUNT(*) AS n,
           ROUND(AVG(fwd_ret_5d) * 100, 2) AS avg_ret_pct,
           SUM(CASE WHEN fwd_ret_5d > 0 THEN 1 ELSE 0 END) AS n_positif
    FROM whale_scans
    WHERE fwd_ret_5d IS NOT NULL
    GROUP BY quality
    ORDER BY avg_ret_pct DESC
""").fetchall()
print(f"{'quality':<15} {'n':>4} {'avg%':>8} {'n_positif':>10}")
for r in rows:
    print(f"{r[0]:<15} {r[1]:>4} {r[2] if r[2] is not None else 0:>8} {r[3]:>10}")

print()
print("=" * 70)
print("WHALE — dibandingkan IHSG (apakah beat market?)")
print("=" * 70)
row = conn.execute("""
    SELECT COUNT(*), ROUND(AVG(fwd_ret_5d)*100,2), ROUND(AVG(ihsg_ret_5d)*100,2),
           ROUND(AVG(fwd_ret_5d - ihsg_ret_5d)*100,2)
    FROM whale_scans WHERE fwd_ret_5d IS NOT NULL AND ihsg_ret_5d IS NOT NULL
""").fetchone()
print(f"n={row[0]} | avg saham={row[1]}% | avg IHSG={row[2]}% | excess return={row[3]}%")

print()
print("=" * 70)
print("EMA — score bucket vs fwd_ret_5d")
print("=" * 70)
rows = conn.execute("""
    SELECT
        CASE
            WHEN score >= 8 THEN '8-10 (tinggi)'
            WHEN score >= 5 THEN '5-7 (sedang)'
            ELSE '0-4 (rendah)'
        END AS bucket,
        COUNT(*) AS n,
        ROUND(AVG(fwd_ret_5d) * 100, 2) AS avg_ret_pct,
        SUM(CASE WHEN fwd_ret_5d > 0 THEN 1 ELSE 0 END) AS n_positif
    FROM ema_scans
    WHERE fwd_ret_5d IS NOT NULL
    GROUP BY bucket
    ORDER BY bucket DESC
""").fetchall()
print(f"{'bucket':<15} {'n':>4} {'avg%':>8} {'n_positif':>10}")
for r in rows:
    print(f"{r[0]:<15} {r[1]:>4} {r[2] if r[2] is not None else 0:>8} {r[3]:>10}")

print()
print("=" * 70)
print("EMA — dibandingkan IHSG")
print("=" * 70)
row = conn.execute("""
    SELECT COUNT(*), ROUND(AVG(fwd_ret_5d)*100,2), ROUND(AVG(ihsg_ret_5d)*100,2),
           ROUND(AVG(fwd_ret_5d - ihsg_ret_5d)*100,2)
    FROM ema_scans WHERE fwd_ret_5d IS NOT NULL AND ihsg_ret_5d IS NOT NULL
""").fetchone()
print(f"n={row[0]} | avg saham={row[1]}% | avg IHSG={row[2]}% | excess return={row[3]}%")

conn.close()
print()
print("SELESAI — ingat: n masih kecil, ini sanity check bukan kesimpulan final.")
