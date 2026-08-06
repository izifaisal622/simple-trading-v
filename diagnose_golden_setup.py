"""
diagnose_golden_setup.py — Fase 3 tahap 1: ukur DISTRIBUSI NYATA
bars_since_vidya_flip pada momen "retest pertama kali terkonfirmasi"
(retest_hold_days baru saja jadi 1 di sebuah zona WATCHING), di 40 ticker
IDX_WATCHLIST, cadence 4h.

KENAPA INI PERLU (jangan skip): mekanisme vidya_flipped_up/bars_since_
vidya_flip yang baru ditambahkan (v10.5.0) MURNI ADITIF — belum mengubah
skor apa pun. Sebelum berani menentukan ambang "fresh flip" utk golden
setup (mis. bars_since_vidya_flip <= X dianggap "segar", kasih bonus skor
vidya_pct lebih tinggi drpd VIDYA yg sudah hijau lama), kita WAJIB lihat
dulu bagaimana sebaran angka ini di data nyata — persis alur yg sama yg
dipakai Fase 2 utk extension_safe_atr (tebakan awal dari sample kecil
sering meleset, lihat histori 10.5 -> 9.5).

MOMEN YANG DIUKUR: retest pertama kali terkonfirmasi per zona (retest_hold_
days 0->1 di status WATCHING) — ini titik paling relevan dgn "golden setup"
favorit user: VIDYA baru belok hijau, lalu pullback, lalu (di titik retest
pertama ini) mulai kelihatan reversal-nya beneran atau tidak. Kalau di titik
ini bars_since_vidya_flip kecil (VIDYA baru saja belok), itu closer ke pola
chart yg user maksud drpd VIDYA yg sudah hijau puluhan bar sebelum retest.

Jalankan dari folder repo: python diagnose_golden_setup.py
Read-only, tidak menyentuh cache/DB produksi. Sample = IDX_WATCHLIST (40
ticker, sama dgn Fase 2) — konsisten dgn metodologi kalibrasi sebelumnya.
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
        states = run_conviction(df, extension_safe_atr=9.5)  # v10.4.5: ambang tervalidasi
    except Exception as exc:
        print(f"[CRASH] {exc}")
        return {"ticker": ticker, "ok": False, "reason": "crash"}

    # Deteksi momen "retest pertama kali terkonfirmasi": retest_hold_days
    # baru jadi 1 (dari 0) di status WATCHING, dalam zona yg SAMA
    # (formed_bar_index sama dgn bar sebelumnya di zona tsb).
    first_retest_events = []  # list of bars_since_vidya_flip (None dibuang di sini, dihitung terpisah)
    none_count = 0
    prev_formed = None
    prev_retest_days = None
    for s in states:
        if s.status == STATE_WATCHING:
            is_new_zone_context = (s.formed_bar_index != prev_formed)
            baseline_retest = 0 if is_new_zone_context else prev_retest_days
            if baseline_retest == 0 and s.retest_hold_days == 1:
                if s.bars_since_vidya_flip is None:
                    none_count += 1
                else:
                    first_retest_events.append(s.bars_since_vidya_flip)
            prev_formed = s.formed_bar_index
            prev_retest_days = s.retest_hold_days
        else:
            prev_formed = None
            prev_retest_days = None

    print(f"OK bar={n_bars} retest_events={len(first_retest_events)}+{none_count}none")
    return {"ticker": ticker, "ok": True, "n_bars": n_bars,
            "events": first_retest_events, "none_count": none_count}


def main():
    print("Fase 3 tahap 1 — distribusi bars_since_vidya_flip di momen retest pertama")
    print(f"Sample: {len(SAMPLE_TICKERS)} ticker (IDX_WATCHLIST, sama dgn Fase 2)\n")

    total = len(SAMPLE_TICKERS)
    results = [diagnose_one(t, i + 1, total) for i, t in enumerate(SAMPLE_TICKERS)]

    print(f"\n{'='*70}\nRINGKASAN\n{'='*70}")
    ok = [r for r in results if r.get("ok")]
    print(f"Berhasil: {len(ok)}/{len(results)}\n")

    all_events = []
    all_none = 0
    for r in ok:
        all_events.extend(r.get("events", []))
        all_none += r.get("none_count", 0)

    total_moments = len(all_events) + all_none
    print(f"Total momen 'retest pertama terkonfirmasi': {total_moments}")
    print(f"  - Dgn bars_since_vidya_flip TERUKUR (ada flip di histori sblmnya): {len(all_events)}")
    print(f"  - None (belum pernah ada event vidya_flipped_up di histori sblm retest ini): {all_none}")

    if len(all_events) < 10:
        print("\n  [PERHATIAN] Data terlalu sedikit utk kesimpulan statistik solid.")

    if all_events:
        vals = sorted(all_events)
        n = len(vals)
        def pct(p):
            i = min(int(n * p / 100), n - 1)
            return vals[i]
        print(f"\n{'='*70}\nDISTRIBUSI bars_since_vidya_flip (n={n})\n{'='*70}")
        print(f"  Min    : {vals[0]}")
        print(f"  P25    : {pct(25)}")
        print(f"  Median : {pct(50)}")
        print(f"  P75    : {pct(75)}")
        print(f"  P90    : {pct(90)}")
        print(f"  Max    : {vals[-1]}")
        print("\n  Interpretasi kasar: kalau median/P75 kecil (mis. <10 bar 4h = <~1.7 hari")
        print("  bursa @ 2 bar/hari), itu artinya kebanyakan retest MEMANG terjadi tak lama")
        print("  setelah VIDYA belok hijau -- pola 'golden setup' relatif umum, bukan langka.")
        print("  Kalau sebarannya lebar (P75 jauh dari median), ada dua populasi campur:")
        print("  retest cepat (fresh flip) vs retest telat (VIDYA sudah hijau lama) -- baru di")
        print("  situ ambang pemisah 'fresh' vs 'established' bisa diusulkan dgn dasar data,")
        print("  bukan tebakan.")
    else:
        print("\n  Tidak ada data point bars_since_vidya_flip terukur di sample ini.")

    print("\nLangkah lanjut: kirim hasil ini ke Claude. JANGAN tentukan ambang 'fresh flip'")
    print("dari sample kecil (pelajaran extension_safe_atr Fase 2: 5 ticker -> 10.5 meleset,")
    print("40 ticker -> 9.5 valid). Kalau distribusi di atas cukup n (>=~30-50 titik) dan")
    print("masuk akal, Claude akan usulkan ambang & formula bonus skor -- tetap opsional/")
    print("backward-compatible thd jalur daily produksi.")


if __name__ == "__main__":
    main()
