"""
diagnose_golden_bonus_impact.py — Fase 3 penutup: ukur DAMPAK NYATA
golden_setup_bonus (v10.7.0, vidya_pct 15->20 khusus zone_ordinal_since_
flip==1) sebelum Fase 4 (wiring UI Page 1) dimulai.

KENAPA INI PERLU: golden_setup_bonus diimplementasi berdasar kalibrasi
WAKTU (ordinal==1 = populasi berbeda scr statistik, dua basis data
konvergen). TAPI belum pernah dicek dampak PRAKTISnya -- berapa banyak
zona yg skornya naik, seberapa besar pengaruhnya ke conviction_pct akhir,
dan apakah +5 poin itu cukup besar utk mengubah urutan/keputusan, atau
kekecilan dibanding base=20/retest=40 sehingga secara praktis diam saja.

Membandingkan run_conviction(..., golden_setup_bonus=False) [default,
skor lama] vs golden_setup_bonus=True [skor baru] pada bar TERAKHIR tiap
ticker (kondisi live/real-time, paling relevan utk keputusan scan
produksi) DAN di seluruh histori WATCHING (utk lihat frekuensi/skala
dampak secara umum).

Jalankan dari folder repo: python diagnose_golden_bonus_impact.py
Read-only, tidak menyentuh cache/DB produksi.
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
        states_old = run_conviction(df, extension_safe_atr=9.5, use_ha_trend=True,
                                     golden_setup_bonus=False)
        states_new = run_conviction(df, extension_safe_atr=9.5, use_ha_trend=True,
                                     golden_setup_bonus=True)
    except Exception as exc:
        print(f"[CRASH] {exc}")
        return {"ticker": ticker, "ok": False, "reason": "crash"}

    # Dampak di seluruh histori WATCHING: berapa bar yg conviction_pct-nya naik,
    # dan berapa besar kenaikannya (harus selalu 0 atau +5, krn cuma vidya_pct
    # yg berubah 15->20 -- verifikasi jadi bagian dari diagnostic ini juga).
    deltas = []
    for so, sn in zip(states_old, states_new):
        if so.status == STATE_WATCHING:
            d = sn.conviction_pct - so.conviction_pct
            if d != 0:
                deltas.append(d)

    latest_old = states_old[-1]
    latest_new = states_new[-1]
    latest_changed = latest_new.conviction_pct != latest_old.conviction_pct

    print(f"OK bar={n_bars} boosted_bars={len(deltas)} "
          f"latest_status={latest_new.status} "
          f"latest_delta={'+' + str(latest_new.conviction_pct - latest_old.conviction_pct) if latest_changed else '0'}")

    return {
        "ticker": ticker, "ok": True, "n_bars": n_bars,
        "deltas": deltas,
        "latest_status": latest_new.status,
        "latest_old_pct": latest_old.conviction_pct,
        "latest_new_pct": latest_new.conviction_pct,
        "latest_changed": latest_changed,
        "latest_ordinal": latest_new.zone_ordinal_since_flip,
    }


def main():
    print("Fase 3 penutup — dampak nyata golden_setup_bonus (v10.7.0) sblm Fase 4")
    print(f"Sample: {len(SAMPLE_TICKERS)} ticker (IDX_WATCHLIST)\n")

    total = len(SAMPLE_TICKERS)
    results = [diagnose_one(t, i + 1, total) for i, t in enumerate(SAMPLE_TICKERS)]

    print(f"\n{'='*70}\nRINGKASAN\n{'='*70}")
    ok = [r for r in results if r.get("ok")]
    print(f"Berhasil: {len(ok)}/{len(results)}\n")

    all_deltas = []
    for r in ok:
        all_deltas.extend(r.get("deltas", []))

    print(f"Total bar WATCHING sepanjang histori 40 ticker yg conviction_pct-nya naik: {len(all_deltas)}")
    if all_deltas:
        bad_deltas = [d for d in all_deltas if d != 5]
        print(f"  Semua kenaikan = +5 poin (sesuai desain)? {'YA' if not bad_deltas else f'TIDAK -- {len(bad_deltas)} anomali: {bad_deltas[:10]}'}")

    print(f"\n{'='*70}\nDAMPAK DI KONDISI LIVE (bar TERAKHIR tiap ticker, paling relevan utk scan produksi)\n{'='*70}")
    changed = [r for r in ok if r.get("latest_changed")]
    print(f"Ticker yg bar TERAKHIRnya berubah conviction_pct: {len(changed)}/{len(ok)}\n")
    for r in changed:
        print(f"  {r['ticker']:6s}  status={r['latest_status']:10s}  "
              f"{r['latest_old_pct']:>3d} -> {r['latest_new_pct']:>3d}  "
              f"(ordinal={r['latest_ordinal']})")

    if not changed:
        print("  (tidak ada -- di snapshot saat ini, TIDAK ADA ticker yg sedang WATCHING")
        print("  di zona ordinal==1. Bukan berarti bonus tidak pernah kepakai -- cuma")
        print("  kebetulan tidak ada golden setup yg aktif PERSIS hari ini.)")

    print(f"\n{'='*70}\nINTERPRETASI\n{'='*70}")
    print("+5 poin dari base conviction_pct (biasanya 60-90 saat WATCHING sehat) itu")
    print("KECIL secara proporsi (~5-8%) -- TIDAK akan membalik urutan ticker yg jomplang")
    print("jauh skornya, TAPI bisa jadi tie-breaker/penentu utk kandidat yg skornya")
    print("mepet (mis. 75 vs 78). Kalau tujuan Anda 'badge terpisah yg jelas terlihat'")
    print("(bukan cuma geser angka tipis), pertimbangkan: badge boolean terpisah")
    print("(is_golden_setup) yg ditampilkan eksplisit di UI, BUKAN cuma mengandalkan")
    print("+5 poin conviction_pct yg mudah tenggelam di angka besar lainnya.")
    print("\nLangkah lanjut: kirim hasil ini ke Claude sebelum Fase 4 (wiring Page 1)")
    print("dimulai -- keputusan format tampilan (badge vs cuma angka) sebaiknya ambil")
    print("evidence ini sbg dasar, bukan asumsi.")


if __name__ == "__main__":
    main()
