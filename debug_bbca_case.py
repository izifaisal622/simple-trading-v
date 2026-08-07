"""
debug_bbca_case.py — Fase 3: cek LANGSUNG kasus ground-truth yg user
kasih sendiri (BBCA, flip vidya ~12 Jun 2026 -> koreksi turun bikin OB ->
zona terbentuk ~1 Jul -> candle reversal 2 Jul -> user entry di situ),
BUKAN sampling percentile dari ticker lain spt diagnose_golden_setup.py.

KENAPA INI LEBIH KUAT dari statistik agregat: user sudah KONFIRMASI MANUAL
bahwa kasus ini adalah golden setup asli (bukan tebakan dari data). Kalau
proxy zone_ordinal_since_flip==1 + bars_since_vidya_flip BENAR menangkap
pola ini, harus kelihatan jelas persis di rentang tanggal ini -- bukan cuma
"masuk akal" scr statistik agregat 40 ticker.

v10.6.0: sekarang pakai use_ha_trend=True -- VIDYA/band dihitung dari
Heikin Ashi (terbukti smooth, tidak flicker, lihat validasi toggle chart
Candlestick vs HA di TradingView). Retest, invalidasi, ATR200 extension-
penalty TETAP di harga real -- tidak terpengaruh flag ini.

Jalankan dari folder repo: python debug_bbca_case.py
Read-only, tidak menyentuh cache/DB produksi.
"""
import sys
sys.path.insert(0, ".")

from core.data_feed import fetch_4h
from core.conviction_engine import run_conviction

TICKER = "BBCA"
DATE_START = "2026-05-15"
DATE_END = "2026-07-10"


def main():
    print(f"Ambil data 4h {TICKER}...")
    df = fetch_4h(TICKER)
    if df is None:
        print("[GAGAL] fetch_4h() gagal")
        return

    print(f"Total bar: {len(df)}, rentang {df.index[0]} s/d {df.index[-1]}\n")

    states = run_conviction(df, extension_safe_atr=9.5, use_ha_trend=True)  # v10.6.0

    print(f"{'='*100}")
    print(f"SEMUA bar {TICKER} antara {DATE_START} dan {DATE_END}")
    print(f"(cocokkan manual thd narasi Anda: flip ~12 Jun -> zona terbentuk ~1 Jul -> entry 2 Jul)")
    print(f"{'='*100}")
    header = (f"{'date':16s} {'status':12s} {'zona':22s} {'retest':6s} "
              f"{'flip_ago':8s} {'ordinal':7s} {'close':>10s} {'note':30s}")
    print(header)
    print("-" * len(header))

    found_any = False
    for s in states:
        d_str = str(s.date)[:16]
        if DATE_START <= d_str[:10] <= DATE_END:
            found_any = True
            zona = f"{s.zone_bottom:.2f}-{s.zone_top:.2f}" if s.zone_bottom is not None else "-"
            flip_ago = str(s.bars_since_vidya_flip) if s.bars_since_vidya_flip is not None else "-"
            ordinal = str(s.zone_ordinal_since_flip) if s.zone_ordinal_since_flip is not None else "-"
            print(f"{d_str:16s} {s.status:12s} {zona:22s} {s.retest_hold_days:<6d} "
                  f"{flip_ago:8s} {ordinal:7s} {s.close:>10.2f} {s.note:30s}")

    if not found_any:
        print("(tidak ada bar di rentang tanggal ini -- cek apakah data 4h Anda mencakup periode ini)")

    print(f"\n{'='*100}")
    print("INTERPRETASI: cari baris di mana status=WATCHING, note='zona baru terbentuk'")
    print("di sekitar 1 Jul -- itu SEHARUSNYA titik zona yg Anda maksud. Lihat kolom")
    print("'flip_ago' (bars_since_vidya_flip) & 'ordinal' (zone_ordinal_since_flip) di baris")
    print("itu -- apakah ordinal==1? Berapa flip_ago-nya? Cocok dgn perkiraan ~26-30 bar")
    print("(dari hitungan 12 Jun -> 1 Jul, ~15 hari bursa x 2 bar/hari) atau meleset jauh?")
    print("Kalau meleset jauh, kemungkinan ada zona LAIN yg terbentuk lebih dulu sebelum")
    print("1 Jul yg tidak masuk hitungan narasi Anda -- perlu lihat baris² sebelumnya juga.")


if __name__ == "__main__":
    main()
