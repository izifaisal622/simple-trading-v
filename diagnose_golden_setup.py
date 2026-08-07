"""
diagnose_golden_setup.py — Fase 3 tahap 1: cari proxy data utk "golden
setup" (VIDYA belok hijau -> koreksi turun membentuk OB zone -> retest ->
reversal candle -> entry), di 40 ticker IDX_WATCHLIST, cadence 4h.

RIWAYAT PENDEKATAN (v10.5.0/10.5.1 -> v10.5.2, KOREKSI ARAH):
Versi awal mengukur bars_since_vidya_flip (jarak bar mentah dari flip
terakhir) di titik retest pertama, lalu mengurutkan dari angka TERKECIL
sbg kandidat "paling golden". User cross-check manual ke TradingView
(BBCA: flip 12 Jun 2026 -> OB terbentuk 1 Jul -> entry 2 Jul, jarak ~30
bar 4h) -- hasilnya duduk di sekitar MEDIAN (35) distribusi waktu itu,
BUKAN di ekor angka kecil (0-2) yg ditampilkan sbg "8 kasus terdekat".
bars_since_vidya_flip=0 artinya flip & retest terjadi di BAR YANG SAMA
(V-turn instan) -- kasus ekstrem, bukan representasi pola user.

KOREKSI: yg membedakan pola user bukan DURASI (berapa bar), tapi URUTAN
-- apakah zona OB ini zona PERTAMA yg terbentuk & di-retest sejak flip
vidya terakhir (zone_ordinal_since_flip == 1), terlepas dari berapa lama
jaraknya scr bar (bisa 10 bar kalau koreksi dangkal, bisa 50 bar kalau
koreksi dalam). Field ini baru ditambah v10.5.2 di conviction_engine.py
(ConvictionState.zone_ordinal_since_flip), MURNI ADITIF, _score() belum
disentuh sama sekali.

YANG DIUKUR DI SINI:
  1. Distribusi bars_since_vidya_flip KHUSUS pada zona ordinal==1 (bukan
     campur semua ordinal spt versi sebelumnya) -- ini nunjukin berapa
     lama tipikal "siklus koreksi pertama" stlh flip berlangsung.
  2. Contoh konkret ordinal==1 disebar dari MIN sampai MAX (bukan cuma
     yg terkecil) -- supaya cross-check visual user lihat rentang penuh,
     bukan cuma ekor ekstrem yg terbukti menyesatkan di v10.5.1.

Jalankan dari folder repo: python diagnose_golden_setup.py
Read-only, tidak menyentuh cache/DB produksi. Sample = IDX_WATCHLIST (40
ticker) — konsisten dgn metodologi Fase 2.
v10.6.1: sekarang pakai use_ha_trend=True -- VIDYA/band (penentu
vidya_flipped_up/zone_ordinal_since_flip) dihitung dari Heikin Ashi,
terbukti mengurangi flicker dibanding basis harga real (lihat validasi
BBCA v10.5.3->10.6.0). Retest, invalidasi, ATR200 extension-penalty
TETAP di harga real -- angka ordinal/bars_since_flip di run SEBELUM ini
(basis real) TIDAK BISA dibandingkan apple-to-apple dgn run SETELAH ini.
"""
import sys
sys.path.insert(0, ".")

from core.data_feed import fetch_4h, IDX_WATCHLIST
from core.conviction_engine import run_conviction, STATE_WATCHING

MIN_BARS_REQUIRED = 260
SAMPLE_TICKERS = IDX_WATCHLIST


def diagnose_one(ticker: str, idx: int = 0, total: int = 0) -> dict:
    prefix = f"[{idx}/{total}] " if total else ""
    print(f"{prefix}{ticker}...", end=" ", flush=True)
    df = fetch_4h(ticker)
    if df is None:
        print("[GAGAL] fetch_4h() gagal")
        return {"ticker": ticker, "ok": False}

    n_bars = len(df)
    if n_bars < MIN_BARS_REQUIRED:
        print(f"[SKIP] bar={n_bars} < {MIN_BARS_REQUIRED}")
        return {"ticker": ticker, "ok": False, "reason": "insufficient_bars"}

    try:
        states = run_conviction(df, extension_safe_atr=9.5, use_ha_trend=True)  # v10.6.1: VIDYA basis HA
    except Exception as exc:
        print(f"[CRASH] {exc}")
        return {"ticker": ticker, "ok": False, "reason": "crash"}

    # Deteksi momen "retest pertama kali terkonfirmasi": retest_hold_days
    # baru jadi 1 (dari 0) di status WATCHING, dalam zona yg SAMA
    # (formed_bar_index sama dgn bar sebelumnya di zona tsb). Dari situ
    # filter KHUSUS zone_ordinal_since_flip == 1.
    ordinal1_bars_since_flip = []  # v10.5.2 — cuma dari zona ordinal==1
    ordinal1_detail = []
    ordinal_dist = {}  # v10.5.2 — sanity check: sebaran ordinal scr umum (1,2,3,...)
    none_count = 0
    prev_formed = None
    prev_retest_days = None
    for s in states:
        if s.status == STATE_WATCHING:
            is_new_zone_context = (s.formed_bar_index != prev_formed)
            baseline_retest = 0 if is_new_zone_context else prev_retest_days
            if baseline_retest == 0 and s.retest_hold_days == 1:
                ordinal_dist[s.zone_ordinal_since_flip] = ordinal_dist.get(s.zone_ordinal_since_flip, 0) + 1
                if s.zone_ordinal_since_flip == 1:
                    if s.bars_since_vidya_flip is None:
                        none_count += 1
                    else:
                        ordinal1_bars_since_flip.append(s.bars_since_vidya_flip)
                        ordinal1_detail.append({
                            "ticker": ticker, "date": s.date,
                            "bars_since_flip": s.bars_since_vidya_flip,
                            "zone_top": s.zone_top, "zone_bottom": s.zone_bottom,
                            "close": s.close,
                        })
            prev_formed = s.formed_bar_index
            prev_retest_days = s.retest_hold_days
        else:
            prev_formed = None
            prev_retest_days = None

    print(f"OK bar={n_bars} ordinal1_events={len(ordinal1_bars_since_flip)}")
    return {"ticker": ticker, "ok": True, "n_bars": n_bars,
            "ordinal1_events": ordinal1_bars_since_flip, "none_count": none_count,
            "ordinal1_detail": ordinal1_detail, "ordinal_dist": ordinal_dist}


def main():
    print("Fase 3 tahap 1 (v10.5.2) — proxy zone_ordinal_since_flip==1 utk golden setup")
    print(f"Sample: {len(SAMPLE_TICKERS)} ticker (IDX_WATCHLIST)\n")

    total = len(SAMPLE_TICKERS)
    results = [diagnose_one(t, i + 1, total) for i, t in enumerate(SAMPLE_TICKERS)]

    print(f"\n{'='*70}\nRINGKASAN\n{'='*70}")
    ok = [r for r in results if r.get("ok")]
    print(f"Berhasil: {len(ok)}/{len(results)}\n")

    all_events = []
    all_none = 0
    all_detail = []
    combined_ordinal_dist = {}
    for r in ok:
        all_events.extend(r.get("ordinal1_events", []))
        all_none += r.get("none_count", 0)
        all_detail.extend(r.get("ordinal1_detail", []))
        for k, v in r.get("ordinal_dist", {}).items():
            combined_ordinal_dist[k] = combined_ordinal_dist.get(k, 0) + v

    print("Sebaran zone_ordinal_since_flip scr umum (semua retest pertama, semua ordinal):")
    for k in sorted(combined_ordinal_dist.keys(), key=lambda x: (x is None, x)):
        label = "None (blm ada flip di histori)" if k is None else f"ordinal={k}"
        print(f"  {label:35s}: {combined_ordinal_dist[k]}")

    total_ordinal1 = len(all_events) + all_none
    print(f"\nTotal momen retest-pertama DI zona ordinal==1: {total_ordinal1}")
    print(f"  - Dgn bars_since_vidya_flip TERUKUR: {len(all_events)}")
    print(f"  - None (zona ordinal==1 tapi blm pernah ada flip di histori -- seharusnya jarang/nol,")
    print(f"    cek kalau angka ini besar berarti ada bug logika ordinal): {all_none}")

    if all_events:
        vals = sorted(all_events)
        n = len(vals)
        def pct(p):
            i = min(int(n * p / 100), n - 1)
            return vals[i]
        print(f"\n{'='*70}\nDISTRIBUSI bars_since_vidya_flip KHUSUS ordinal==1 (n={n})\n{'='*70}")
        print(f"  Min    : {vals[0]}")
        print(f"  P25    : {pct(25)}")
        print(f"  Median : {pct(50)}")
        print(f"  P75    : {pct(75)}")
        print(f"  P90    : {pct(90)}")
        print(f"  Max    : {vals[-1]}")
        print("\n  Ini jarak bar tipikal 'siklus koreksi pertama' (flip -> retest pertama)")
        print("  KHUSUS pada zona pertama sejak flip -- beda dari versi v10.5.1 yg nyampur")
        print("  semua ordinal jadi satu distribusi lebar (P25=11..P90=134).")
    else:
        print("\n  Tidak ada data point terukur di sample ini.")

    if all_detail:
        print(f"\n{'='*70}\nCONTOH KONKRET — ordinal==1, disebar MIN s/d MAX (v10.5.2)\n{'='*70}")
        print("Beda dari v10.5.1 (yg cuma nunjukin angka TERKECIL, ternyata menyesatkan):")
        print("kali ini contoh disebar dari ujung ke ujung biar Anda lihat rentang penuh")
        print("pola 'zona pertama sejak flip', bukan cuma kasus ekstrem V-turn instan.\n")
        sorted_detail = sorted(all_detail, key=lambda d: d["bars_since_flip"])
        n = len(sorted_detail)
        # ambil 8 titik tersebar merata di percentile 0,14,28,...,100
        picks = []
        seen_idx = set()
        for p in range(0, 101, 14):
            idx = min(int(n * p / 100), n - 1)
            if idx not in seen_idx:
                seen_idx.add(idx)
                picks.append(sorted_detail[idx])
        for d in picks[:8]:
            print(f"  {d['ticker']:6s}  {str(d['date'])[:16]:16s}  "
                  f"bars_since_flip={d['bars_since_flip']:>4}  "
                  f"zona={d['zone_bottom']:.2f}-{d['zone_top']:.2f}  close={d['close']:.2f}")

    print("\nLangkah lanjut: kirim hasil ini ke Claude — terutama cross-check visual Anda")
    print("thd 8 contoh di atas (bukan cuma percaya angka statistiknya). Kalau ordinal==1")
    print("terbukti match pola golden setup Anda scr visual, baru Claude usulkan formula")
    print("bonus skor (opsional, backward-compatible thd jalur daily produksi).")


if __name__ == "__main__":
    main()
