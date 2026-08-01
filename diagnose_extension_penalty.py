"""
diagnose_extension_penalty.py — Analisis EMPIRIS (bukan dugaan): seberapa
besar dampak extension_penalty terhadap distribusi conviction hari ini.
Menjawab: apakah penalty ini yang bikin filter >=80% cuma lolos sedikit,
atau itu memang wajar dari funnel yang sudah ketat sejak dulu.

Jalankan dari folder repo: python diagnose_extension_penalty.py
Read-only, tidak mengubah data apa pun.
"""
import sqlite3

conn = sqlite3.connect("logs/scan_history.db")
latest_date = conn.execute("SELECT MAX(scan_date) FROM zone_scans").fetchone()[0]
if not latest_date:
    print("Belum ada data zone_scans sama sekali.")
    raise SystemExit

rows = conn.execute("""
    SELECT ticker, conviction_pct, extension_penalty, extension_atr,
           base_pct, retest_pct, vidya_pct, volume_pct, structure_pct
    FROM zone_scans
    WHERE scan_date = ? AND status = 'WATCHING'
""", (latest_date,)).fetchall()
conn.close()

print(f"Scan date: {latest_date}")
print(f"Total zona WATCHING (conviction apa pun, termasuk 0%): {len(rows)}\n")

if not rows:
    print("Tidak ada zona WATCHING sama sekali.")
    raise SystemExit

# ═══ 1) Skor SEBELUM penalty (rekonstruksi) vs SESUDAH ═══
before_pen = []
after_pen = []
for (t, conv, ext_pen, ext_atr, base, retest, vidya, vol, struct) in rows:
    ext_pen = ext_pen or 0
    before = base + retest + vidya + vol + struct  # tanpa penalty, sebelum di-clip 100
    before = min(100, before)
    before_pen.append((t, before))
    after_pen.append((t, conv))

print("=" * 70)
print("DAMPAK EXTENSION PENALTY — berapa banyak zona TURUN status filter")
print("=" * 70)
for threshold in [90, 80, 70, 60, 50]:
    n_before = sum(1 for _, s in before_pen if s >= threshold)
    n_after = sum(1 for _, s in after_pen if s >= threshold)
    delta = n_before - n_after
    print(f"  Ambang >={threshold}%:  SEBELUM penalty={n_before:>3} | SESUDAH penalty={n_after:>3} | "
          f"HILANG krn extension={delta:>3}")

# ═══ 2) Distribusi extension_penalty itu sendiri ═══
print("\n" + "=" * 70)
print("DISTRIBUSI extension_penalty DI SELURUH ZONA WATCHING")
print("=" * 70)
pen_values = [(ext_pen or 0) for (_, _, ext_pen, _, _, _, _, _, _) in rows]
n_zero = sum(1 for p in pen_values if p == 0)
n_small = sum(1 for p in pen_values if 0 < p < 15)
n_big = sum(1 for p in pen_values if p >= 15)
print(f"  Penalty = 0 poin (tidak extended):     {n_zero} zona")
print(f"  Penalty 1-14 poin (agak extended):     {n_small} zona")
print(f"  Penalty >=15 poin (sangat extended):   {n_big} zona")

# ═══ 3) 10 zona dengan skor SEBELUM penalty tertinggi — utk lihat konkret
#         apa yg 'digugurkan' oleh extension penalty ═══
print("\n" + "=" * 70)
print("TOP 10 ZONA BERDASARKAN SKOR SEBELUM PENALTY (utk lihat siapa yg gugur)")
print("=" * 70)
combined = []
for (t, conv, ext_pen, ext_atr, base, retest, vidya, vol, struct) in rows:
    before = min(100, base + retest + vidya + vol + struct)
    combined.append((t, before, conv, ext_pen or 0, ext_atr or 0))
combined.sort(key=lambda x: -x[1])

print(f"{'Ticker':<10} {'SblmPenalty':>12} {'SesudahPenalty':>15} {'ExtPenalty':>11} {'ExtATR':>8}")
for t, before, after, pen, atr in combined[:10]:
    flag = " <<< GUGUR dari >=80%" if before >= 80 and after < 80 else ""
    print(f"{t:<10} {before:>11}% {after:>14}% {pen:>10} {atr:>7.1f}x{flag}")

print("\nSELESAI — salin SEMUA output di atas.")
