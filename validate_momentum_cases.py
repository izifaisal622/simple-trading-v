"""
validate_momentum_cases.py — Validasi agents/momentum_scanner.py terhadap
3 study case yang dipakai untuk mendefinisikan rule Momentum (sesi diskusi
2026-09-05 dengan Claude). Tanggal target di bawah SUDAH dikoreksi dari
tanggal awal (17 Jul / 18 Aug / 31 Aug) ke tanggal event sebenarnya, hasil
konfirmasi manual user via diagnose_momentum_window.py:

  1. BUMI — flip VIDYA + BOS(internal), konfirmasi manual: 20 Jul 2026
  2. SINI — flip VIDYA + CHoCH,          sekitar 18 Aug 2026 (belum dikoreksi,
     sudah PASS di run pertama)
  3. UANG — flip VIDYA + BOS(internal)@02-Sep DAN CHoCH(swing)@03-Sep di bar
     yang sama — user lihatnya sebagai "candle break BOS di 3 Sep" (breakout
     candle besar), meskipun tag internal-BOS teknisnya 1 bar lebih awal.
     Ini KENAPA MomentumMatch sekarang bawa SEMUA confirmation, bukan cuma 1
     (lihat CATATAN PENTING di momentum_scanner.py).

JALANKAN DI MESIN LOKAL (butuh akses network ke Yahoo Finance — environment
Claude yang menulis file ini TIDAK bisa fetch data live, lihat CATATAN
PENTING di agents/momentum_scanner.py).

Cara pakai:
    python validate_momentum_cases.py

Untuk tiap ticker, script fetch 4h via core.data_feed.fetch_4h(), jalankan
find_all_momentum_events(), lalu cek apakah ADA match (flip_date ATAU salah
satu confirmation date) dalam +/- TOLERANCE_DAYS dari tanggal target. Semua
match lain di histori ticker itu juga ditampilkan (bukan cuma yang match
target) supaya kelihatan kalau window/definisi rule perlu disetel ulang.
"""

from datetime import datetime, timedelta

from core.data_feed import fetch_4h
from agents.momentum_scanner import find_all_momentum_events

TOLERANCE_DAYS = 2  # toleransi pencocokan tanggal target vs tanggal event

CASES = [
    {"ticker": "BUMI", "target_date": "2026-07-20", "expect": "BOS"},
    {"ticker": "SINI", "target_date": "2026-08-18", "expect": "CHOCH"},
    {"ticker": "UANG", "target_date": "2026-09-03", "expect": "BOS"},
]


def _date_of(d):
    return d.date() if hasattr(d, "date") else d


def _within_tolerance(event_date, target_date) -> bool:
    ed = _date_of(event_date)
    return abs((ed - target_date).days) <= TOLERANCE_DAYS


def run_case(ticker: str, target_date_str: str, expect_kind: str) -> bool:
    target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    print(f"\n{'=' * 70}\n{ticker} — target: {target_date_str} (expect {expect_kind})\n{'=' * 70}")

    df = fetch_4h(ticker)
    if df is None:
        print(f"  [FAIL] fetch_4h({ticker}) gagal / data kurang. Cek koneksi/ticker.")
        return False
    print(f"  Data: {len(df)} bar 4h, {df.index[0].date()} s.d. {df.index[-1].date()}")

    matches = find_all_momentum_events(df, ticker=ticker)
    if not matches:
        print(f"  [FAIL] 0 match ditemukan sepanjang histori — rule tidak menangkap "
              f"kondisi ini sama sekali untuk {ticker}.")
        return False

    print(f"  Total match sepanjang histori: {len(matches)}")
    hit = False
    for m in matches:
        near_flip = _within_tolerance(m.flip_date, target_date)
        near_any_confirmation = any(_within_tolerance(c.date, target_date) for c in m.confirmations)
        marker = " <== DEKAT TARGET" if (near_flip or near_any_confirmation) else ""
        conf_str = ", ".join(f"{c.kind}({c.scope})@{_date_of(c.date)}" for c in m.confirmations)
        print(f"    flip={_date_of(m.flip_date)} | {conf_str} | jarak={m.bars_between} bar | "
              f"high_conviction={m.high_conviction}{marker}")
        if near_flip or near_any_confirmation:
            hit = True
            found_kinds = {c.kind for c in m.confirmations}
            if expect_kind not in found_kinds:
                print(f"    [WARNING] tanggal cocok tapi kind yang ketemu={found_kinds}, "
                      f"expect={expect_kind} — cek apakah ini match yang benar.")

    if hit:
        print(f"  [PASS] {ticker}: ada match dalam +/-{TOLERANCE_DAYS} hari dari {target_date_str}.")
    else:
        print(f"  [FAIL] {ticker}: ADA match lain di histori, tapi TIDAK ADA yang dekat "
              f"{target_date_str}. Window (RECENT_WINDOW) atau definisi rule kemungkinan "
              f"perlu disetel ulang — lihat daftar match di atas buat bandingin manual "
              f"sama chart TradingView.")
    return hit


if __name__ == "__main__":
    results = {}
    for case in CASES:
        try:
            results[case["ticker"]] = run_case(case["ticker"], case["target_date"], case["expect"])
        except Exception as exc:
            print(f"\n[CRASH] {case['ticker']}: {exc}")
            results[case["ticker"]] = False

    print(f"\n{'=' * 70}\nRINGKASAN\n{'=' * 70}")
    for ticker, ok in results.items():
        print(f"  {ticker}: {'PASS' if ok else 'FAIL'}")
    if all(results.values()):
        print("\nSemua case PASS — rule di agents/momentum_scanner.py konsisten dengan "
              "3 study case. Aman lanjut ke Fase 2 (UI wiring) SETELAH universe scope "
              "diputuskan (lihat CATATAN PENTING di momentum_scanner.py).")
    else:
        print("\nADA case yang FAIL — jangan lanjut ke Fase 2 dulu. Kirim balik output "
              "lengkap script ini supaya rule/window bisa disesuaikan.")
