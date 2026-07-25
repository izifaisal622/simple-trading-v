"""
diagnose_conviction.py — Uji engine conviction (tahap 1+2) terhadap data IDX
SUNGGUHAN. Jalankan dari folder repo: python diagnose_conviction.py
Read-only, tidak mengubah data apa pun.
"""
import sys
sys.path.insert(0, ".")
from core.data_feed import DataFeed
from core.conviction_engine import run_conviction

# Beberapa ticker representatif: likuid + volatil + kecil
TICKERS = ["BBCA.JK", "AGII.JK", "GOTO.JK", "BREN.JK", "ANTM.JK"]

feed = DataFeed(timeframe="1d", period="2y")  # 2y agar cukup utk swing_size=50 + ATR(200)

for ticker in TICKERS:
    print("=" * 70)
    print(f"TICKER: {ticker}")
    print("=" * 70)
    try:
        df = feed.fetch(ticker)
    except Exception as exc:
        print(f"  GAGAL fetch: {exc}")
        continue

    if df is None or len(df) < 250:
        print(f"  Data tidak cukup: {len(df) if df is not None else 0} bar (butuh >=250 utk ATR200+swing50)")
        continue

    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)

    try:
        states = run_conviction(df, internal_size=5, swing_size=50)
    except Exception as exc:
        import traceback
        print(f"  ENGINE CRASH: {exc}")
        traceback.print_exc()
        continue

    latest = states[-1]
    print(f"  Total bar: {len(states)} | Bar terakhir: {latest.date}")
    print(f"  Status HARI INI: {latest.status} | Conviction: {latest.conviction_pct}%")
    if latest.zone_top:
        print(f"  Zona: top={latest.zone_top:.1f} bottom={latest.zone_bottom:.1f} "
              f"(dibentuk {len(states) - 1 - latest.formed_bar_index} bar lalu)")
        print(f"  Breakdown: base={latest.base_pct} retest={latest.retest_pct} "
              f"vidya={latest.vidya_pct} vol={latest.volume_pct} struct={latest.structure_pct}")
        print(f"  Retest hold days: {latest.retest_hold_days}")

    # Statistik ringkas seluruh riwayat — supaya kita tahu seberapa sering
    # zona terbentuk/retest/invalidasi/expired di data nyata
    from collections import Counter
    status_counts = Counter(s.status for s in states)
    conv_over_0 = sum(1 for s in states if s.conviction_pct > 0)
    conv_100 = sum(1 for s in states if s.conviction_pct == 100)
    print(f"\n  Statistik {len(states)} bar riwayat:")
    print(f"    Status count: {dict(status_counts)}")
    print(f"    Bar dgn conviction>0: {conv_over_0} ({conv_over_0/len(states)*100:.1f}%)")
    print(f"    Bar dgn conviction=100%: {conv_100}")
    print()

print("=" * 70)
print("SELESAI — salin SEMUA output di atas.")
print("Perhatikan khusus: GAGAL/CRASH apa pun, dan apakah conviction=100%")
print("PERNAH terjadi (kalau tak pernah di 2 tahun data, skema perlu ditinjau).")
print("=" * 70)
