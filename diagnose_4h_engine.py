"""
diagnose_4h_engine.py — Fase 2: uji ENGINE PENUH (ob_engine -> conviction_engine)
di atas data 4H, BUKAN cuma resample mentah (itu sudah Fase 1, selesai &
tervalidasi visual thd TradingView).

KEPUTUSAN EKSPLISIT USER (jangan diubah tanpa persetujuan baru): konstanta
bar-count TIDAK di-scale dari versi daily (internal_size=5, swing_size=50,
vidya_length=10, vidya_momentum=20, band_distance=2.0, atr_length=200 —
semua default VidyaSmcEngine() apa adanya). Alasan: itu PERSIS angka yang
dipakai user di indikator Pine "VIDYA + SMC 10 20 2 ... 50 5 5" pada chart
TradingView 4H favoritnya — golden setup yang jadi motivasi awal proyek ini
sudah dilatih matanya baca pola dari angka2 itu, bukan versi di-scale.

YANG DIUJI DI SINI:
  1. Apakah 4h punya cukup bar utk MIN_BARS_REQUIRED=260 (sama spt versi
     daily di agents/zone_scanner.py — ATR200 + swing_size(50) buffer,
     TIDAK berubah krn atr_length & swing_size TIDAK di-scale).
  2. Status zona TERKINI tiap ticker sample (WATCHING/IDLE/dll) + breakdown
     conviction — sanity check apakah outputnya masuk akal, bukan sampah.
  3. DISTRIBUSI extension_atr di seluruh histori WATCHING tiap ticker —
     INI yang masih perlu direkalibrasi (lihat catatan modul). EXTENSION_
     SAFE_ATR=8.0 (dikalibrasi dari ATR200 DAILY, studi 334 zona) BELUM
     tentu valid di skala ATR200 4H — jendela waktu riilnya beda meski
     jumlah bar sama.

v10.4.3 UPDATE: sample diperluas dari 5 -> 40 ticker, pakai IDX_WATCHLIST
(core/data_feed.py) apa adanya — BUKAN dipilih tangan, itu daftar yg sudah
dikurasi repo ini sendiri utk keberagaman sektor (bank/telko/consumer/
tambang/properti/tech) DAN keberagaman likuiditas (blue chip spt BBCA
sampai volatile spt GOTO/BUKA), konsisten dgn "doktrin satu sumber
universe" yg dipegang di seluruh repo. Tujuan: perkuat kalibrasi
extension_safe_atr=10.5 (provisional, dari 5 ticker) sebelum Fase 3.

PERINGATAN WAKTU: fetch_4h() belum ada caching/batching (keterbatasan
Fase 1 yg sengaja) — tiap ticker = 1 fetch 60m terpisah + walk-forward
compute penuh (~1431 bar). Perkiraan KASAR (belum pernah dites end-to-end
di 40 ticker): beberapa menit, bukan detik. Kalau kelamaan, boleh Ctrl+C
kapan saja — hasil ticker yg SUDAH selesai tetap tercetak per baris
(bukan nunggu semua kelar baru nampil), jadi hasil parsial tetap berguna.

Jalankan dari folder repo: python diagnose_4h_engine.py
Read-only.
"""
import sys
import statistics

sys.path.insert(0, ".")

from core.data_feed import fetch_4h, IDX_WATCHLIST
from core.ob_engine import run_engine
from core.conviction_engine import run_conviction, STATE_WATCHING

MIN_BARS_REQUIRED = 260  # sama dgn agents/zone_scanner.py — TIDAK berubah (Opsi B)
SAMPLE_TICKERS = IDX_WATCHLIST  # v10.4.3: 40 ticker, bukan 5 -- lihat catatan modul


def diagnose_one(ticker: str, idx: int = 0, total: int = 0) -> dict:
    prog = f"[{idx}/{total}] " if total else ""
    print(f"\n{'='*70}\n{prog}{ticker}\n{'='*70}")
    df = fetch_4h(ticker)
    if df is None:
        print("  [GAGAL] fetch_4h() gagal total")
        return {"ticker": ticker, "ok": False}

    n_bars = len(df)
    print(f"  Bar 4h tersedia : {n_bars} "
          f"{'[OK, >= 260]' if n_bars >= MIN_BARS_REQUIRED else '[KURANG, < 260 -- akan di-skip di scan produksi]'}")
    if n_bars < MIN_BARS_REQUIRED:
        return {"ticker": ticker, "ok": False, "reason": "insufficient_bars", "n_bars": n_bars}

    try:
        # v10.4.4 REVISI: extension_safe_atr=9.5 (turun dari 10.5). Run
        # pertama (5 ticker) P75=10.65x TERBUKTI overestimate -- run kedua
        # (40 ticker, IDX_WATCHLIST, n=20009 titik) P75=9.22x, jauh lebih
        # solid. 9.5 dipilih dgn margin kecil di atas P75 riil, sama spt
        # pola kalibrasi daily dulu (8.0 dipilih sedikit di atas P75
        # daily=7.36, bukan pas di angkanya). internal_size/swing_size
        # TETAP default (5/50, TIDAK di-scale, Opsi B keputusan user).
        states = run_conviction(df, extension_safe_atr=9.5)
    except Exception as exc:
        print(f"  [CRASH] engine gagal: {exc}")
        return {"ticker": ticker, "ok": False, "reason": "crash"}

    latest = states[-1]
    print(f"  Status terkini   : {latest.status}")
    if latest.status == STATE_WATCHING:
        print(f"  Conviction       : {latest.conviction_pct}% "
              f"(base={latest.base_pct} retest={latest.retest_pct} vidya={latest.vidya_pct} "
              f"vol={latest.volume_pct} struct={latest.structure_pct} ext_penalty=-{latest.extension_penalty})")
        print(f"  Zona             : {latest.zone_bottom} - {latest.zone_top}")
        print(f"  Retest hold      : {latest.retest_hold_days}/2 bar")
        print(f"  Extension ATR    : {latest.extension_atr}x")

    # Kumpulkan SEMUA extension_atr sepanjang histori WATCHING (bukan cuma bar terakhir)
    # -- ini yang jadi bahan distribusi utk cek kalibrasi EXTENSION_SAFE_ATR versi 4h
    ext_values = [s.extension_atr for s in states
                  if s.status == STATE_WATCHING and s.extension_atr and s.extension_atr > 0]

    # Hitung juga berapa kali zona baru terbentuk sepanjang histori (proxy frekuensi sinyal)
    zone_formed_count = sum(1 for s in states if "zona baru terbentuk" in (s.note or ""))
    print(f"  Zona terbentuk sepanjang histori: {zone_formed_count}x")
    print(f"  Data point extension_atr (WATCHING): {len(ext_values)}")

    return {"ticker": ticker, "ok": True, "n_bars": n_bars, "latest_status": latest.status,
            "ext_values": ext_values, "zone_formed_count": zone_formed_count}


def main():
    print("Fase 2 — uji engine penuh di atas data 4h (konstanta TIDAK di-scale, Opsi B)")
    print(f"Sample: {SAMPLE_TICKERS}\n")

    total = len(SAMPLE_TICKERS)
    results = [diagnose_one(t, i + 1, total) for i, t in enumerate(SAMPLE_TICKERS)]

    print(f"\n{'='*70}\nRINGKASAN\n{'='*70}")
    ok = [r for r in results if r.get("ok")]
    print(f"Berhasil: {len(ok)}/{len(results)}\n")

    all_ext = []
    for r in ok:
        all_ext.extend(r.get("ext_values", []))
        print(f"  {r['ticker']:6s} bar={r['n_bars']:>5} status={r['latest_status']:12s} "
              f"zona_terbentuk={r['zone_formed_count']:>3}x  n_ext_pts={len(r.get('ext_values', []))}")

    print(f"\n{'='*70}\nDISTRIBUSI extension_atr GABUNGAN (n={len(all_ext)})\n{'='*70}")
    if len(all_ext) < 50:
        print(f"  [PERHATIAN] Cuma {len(all_ext)} data point dari {len(ok)} ticker -- "
              "masih tergolong tipis. Cek juga apakah banyak ticker di ringkasan di atas "
              "berstatus IDLE (jarang WATCHING = sedikit kontribusi data per ticker).")
    if all_ext:
        vals = sorted(all_ext)
        n = len(vals)
        def pct(p):
            idx = min(int(n * p / 100), n - 1)
            return vals[idx]
        print(f"  Min    : {vals[0]:.2f}x")
        print(f"  P25    : {pct(25):.2f}x")
        print(f"  Median : {pct(50):.2f}x")
        print(f"  P75    : {pct(75):.2f}x")
        print(f"  Max    : {vals[-1]:.2f}x")
        print(f"\n  Ambang LAMA (EXTENSION_SAFE_ATR=8.0, kalibrasi DAILY):")
        over_old = sum(1 for v in vals if v > 8.0)
        print(f"  {over_old}/{n} ({over_old/n*100:.0f}%) di atas -- run ENGINE di atas sudah "
              "pakai extension_safe_atr=9.5 (bukan 8.0), jadi conviction/penalty yg "
              "ditampilkan per-ticker di atas SUDAH pakai ambang baru.")
        print(f"\n  Ambang BARU (extension_safe_atr=9.5, kalibrasi REVISI v10.4.4):")
        over_new = sum(1 for v in vals if v > 9.5)
        print(f"  {over_new}/{n} ({over_new/n*100:.0f}%) di atas -- target desain ~25% "
              "(niat P75).")
    else:
        print("  Tidak ada data point (belum ada zona WATCHING dgn extension_atr valid"
              " di sample ini).")

    print("\nLangkah lanjut: kirim hasil ini ke Claude. Dengan 40 ticker (IDX_WATCHLIST) "
          "distribusi ini jauh lebih kuat drpd run pertama (5 ticker) -- Claude akan cek "
          "apakah 10.5 masih pas atau perlu direvisi lagi berdasarkan P75 baru di atas.")


if __name__ == "__main__":
    main()
