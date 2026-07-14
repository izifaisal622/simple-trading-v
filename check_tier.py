"""
Cek TIER (sizing tier dari analyst_agent, kalibrasi x0.8) vs forward return.
Read-only. Jalankan: python check_tier.py
"""
import sqlite3

conn = sqlite3.connect("logs/scan_history.db")

print("=" * 70)
print("EMA — score bucket (proxy TIER, sblm x0.8) vs fwd_ret_5d")
print("=" * 70)
rows = conn.execute("""
    SELECT score, fwd_ret_5d
    FROM ema_scans WHERE fwd_ret_5d IS NOT NULL
""").fetchall()

from collections import defaultdict
buckets = defaultdict(list)
for score, ret in rows:
    if score >= 9:
        tier = "T1 (score 9-10)"
    elif score >= 7:
        tier = "T2 (score 7-8)"
    elif score >= 5:
        tier = "T3 (score 5-6)"
    else:
        tier = "T4 (score <5)"
    buckets[tier].append(ret)

print(f"{'tier_proxy':<18} {'n':>4} {'avg%':>8} {'n_positif':>10} {'winrate%':>9}")
for tier in sorted(buckets.keys()):
    rets = buckets[tier]
    n = len(rets)
    avg = sum(rets) / n * 100
    pos = sum(1 for r in rets if r > 0)
    wr = pos / n * 100
    print(f"{tier:<18} {n:>4} {avg:>8.2f} {pos:>10} {wr:>8.1f}%")

print()
print("Interpretasi: kalau T1 (score tinggi) TIDAK unggul avg%/winrate dibanding")
print("T3/T4, kalibrasi x0.8 (yg makin memperkecil sizing utk score rendah)")
print("berjalan searah dgn asumsi yg BELUM terbukti data.")

conn.close()
