"""
Diagnostik ema_scans backfill — jalankan dari folder repo:
    python diagnose_ema.py
Tidak mengubah data apa pun. Cetak semua tahap ke layar.
"""
import sys, sqlite3
sys.path.insert(0, ".")
import pandas as pd
import yfinance as yf
import agents.scan_logger as sl

conn = sl._get_conn()
sl._ensure_ema_table(conn)

rows = conn.execute("""
    SELECT id, ticker, scan_date FROM ema_scans
    WHERE backfilled_at IS NULL
      AND julianday('now') - julianday(scan_date) >= 3
    ORDER BY scan_date LIMIT 500
""").fetchall()
print(f"1) Baris eligible: {len(rows)}")
print(f"   Contoh 5 baris pertama: {rows[:5]}")

if not rows:
    print("STOP — tidak ada baris eligible sama sekali. Cek umur data.")
    sys.exit()

def _sym(t):
    return t if t.endswith(".JK") or t.startswith("^") else f"{t}.JK"

tickers = sorted({_sym(r[1]) for r in rows})
print(f"\n2) Ticker unik yang akan di-download: {len(tickers)}")
print(f"   Contoh 10 pertama: {tickers[:10]}")

oldest = min(r[2] for r in rows)
start = (pd.Timestamp(oldest) - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
print(f"\n3) start date untuk download: {start}")

chunk = tickers[:180]
print(f"\n4) Download chunk pertama ({len(chunk)} ticker)...")
try:
    raw = yf.download(chunk, start=start, interval="1d",
                      group_by="ticker", auto_adjust=False,
                      progress=False, threads=True)
    print(f"   OK — shape: {raw.shape}, kolom level: {raw.columns.nlevels}")
    print(f"   Contoh kolom: {list(raw.columns[:6])}")
except Exception as exc:
    print(f"   GAGAL TOTAL: {exc}")
    sys.exit()

print(f"\n5) Coba slice + dropna per simbol (5 sampel pertama)...")
ok, fail = 0, 0
for sym in chunk[:5]:
    try:
        d = raw[sym] if len(chunk) > 1 else raw
        if getattr(d.columns, "nlevels", 1) > 1:
            d = d.copy(); d.columns = d.columns.get_level_values(0)
        d2 = d.dropna(subset=["Open", "Close"])
        print(f"   {sym}: OK, {len(d2)} baris valid, tanggal terakhir {d2.index[-1] if len(d2) else '-'}")
        ok += 1
    except Exception as exc:
        print(f"   {sym}: GAGAL — {type(exc).__name__}: {exc}")
        fail += 1
print(f"   Ringkasan sampel: {ok} OK, {fail} gagal")

print(f"\n6) Test _horizon_metrics untuk 1 baris nyata dari ema_scans...")
row_id, tkr, sdate = rows[0]
sym = _sym(tkr)
try:
    d = raw[sym] if len(chunk) > 1 and sym in chunk else None
    if d is None:
        print(f"   Ticker baris pertama ({sym}) TIDAK ADA di chunk pertama (mungkin di chunk lain)")
    else:
        if getattr(d.columns, "nlevels", 1) > 1:
            d = d.copy(); d.columns = d.columns.get_level_values(0)
        d2 = d.dropna(subset=["Open", "Close"])
        m = sl._horizon_metrics(d2, sdate)
        print(f"   ticker={sym}, scan_date={sdate}")
        print(f"   df index range: {d2.index.min()} s/d {d2.index.max()}" if len(d2) else "   df kosong")
        print(f"   _horizon_metrics hasil: {m}")
except Exception as exc:
    print(f"   ERROR: {type(exc).__name__}: {exc}")

conn.close()
print("\nSELESAI — salin SEMUA output di atas.")
