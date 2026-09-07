"""
diagnose_momentum_window.py — Dump SEMUA event mentah (vidya_flipped_up +
BOS/CHoCH/EQL, kedua scope) di sekitar tanggal tertentu, untuk 1-2 ticker.
Dipakai buat investigasi kasus UANG (klaim: BOS internal muncul ~1 Sep 2026,
tapi find_all_momentum_events() nemunya CHoCH(swing) di 09-03) — supaya
kelihatan APAKAH ada BOS(internal) di window itu yang gagal ke-pasangkan
dengan flip manapun, bukan cuma nebak dari chart.

Jalankan: python diagnose_momentum_window.py
"""

from datetime import datetime, timedelta

from core.data_feed import fetch_4h
from core.ob_engine import run_engine
from core.structure_signals import compute_bullish_structure

WINDOWS = [
    {"ticker": "BUMI", "start": "2026-07-10", "end": "2026-07-27"},
    {"ticker": "UANG", "start": "2026-08-25", "end": "2026-09-05"},
]


def _d(x):
    return x.date() if hasattr(x, "date") else x


def dump(ticker: str, start_str: str, end_str: str):
    start = datetime.strptime(start_str, "%Y-%m-%d").date()
    end = datetime.strptime(end_str, "%Y-%m-%d").date()

    print(f"\n{'=' * 70}\n{ticker} — window {start_str} s.d. {end_str}\n{'=' * 70}")
    df = fetch_4h(ticker)
    if df is None:
        print("  [FAIL] fetch_4h gagal.")
        return

    engine_states = run_engine(df)
    sig = compute_bullish_structure(df, ticker=ticker)

    print("\n  -- VIDYA state per bar (is_trend_up / vidya_flipped_up) --")
    for s in engine_states:
        d = _d(s.date)
        if start <= d <= end:
            flag = " <== FLIP" if s.vidya_flipped_up else ""
            print(f"    {d} bar={s.bar_index:5d} close={s.close:>8.2f} "
                  f"is_trend_up={s.is_trend_up}{flag}")

    print("\n  -- Structure events (BOS/CHoCH/EQL, semua scope) --")
    if sig is None:
        print("    (compute_bullish_structure return None)")
        return
    any_ev = False
    for e in sig.events:
        d = _d(e.date)
        if start <= d <= end:
            any_ev = True
            print(f"    {d} bar={e.bar_index:5d} kind={e.kind:6s} scope={e.scope:8s} "
                  f"level={e.level:.2f} close={e.close:.2f}")
    if not any_ev:
        print("    (tidak ada event BOS/CHoCH/EQL di window ini)")

    print(f"\n  -- Bias akhir (di bar terakhir data) --")
    print(f"    internal_trend_bias={sig.internal_trend_bias} "
          f"swing_trend_bias={sig.swing_trend_bias}")


if __name__ == "__main__":
    for w in WINDOWS:
        dump(w["ticker"], w["start"], w["end"])
