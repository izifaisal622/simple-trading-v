"""
agents/structure_scanner.py — Scan full universe cari ticker yang BARU
membentuk SALAH SATU event bullish: BOS, CHoCH, atau EQL biru (v10.9.2).

KENAPA FILE TERPISAH, BUKAN EXTEND ZoneScanner/GoldenSetupScanner4H: sama
prinsipnya dgn agents/golden_setup_scanner.py — nol risiko ke jalur
produksi yang sudah jalan (ZoneScanner/logs/scan_history.db TIDAK
disentuh sama sekali). Logic deteksi event-nya sendiri ada di
core/structure_signals.py (compute_bullish_structure, ADITIF juga,
lihat docstring modul itu) — file ini HANYA orkestrasi: fetch_batch
full-universe (pola sudah terbukti aman di agents/zone_scanner.py,
BUKAN fetch_4h() yang belum py caching), lalu filter ticker yang
punya event baru terbentuk.

Definisi "baru terbentuk" (v10.9.2 — KOREKSI dari v10.9.1: sebelumnya
salah paham dikira user minta ketiga event WAJIB muncul bareng/AND,
yang benar CUKUP SALAH SATU/OR):
  - Window RECENT_WINDOW=5 bar (hari bursa) terakhir dari total histori
    yang berhasil di-fetch per ticker.
  - Ticker lolos kalau PALING TIDAK SATU dari {BOS, CHoCH, EQL} punya
    event dengan bar_index di dalam window tsb. BOS/CHoCH dari scope
    manapun (internal ATAU swing) dihitung.
  - Kalau lebih dari satu jenis event yang match dalam window yang sama,
    SEMUA yang match ditampilkan di kartu yang sama (bukan cuma 1) —
    field yang tidak match tetap None, di-skip pas render kartu.

Hasil session-only (Streamlit session_state), TIDAK ditulis ke DB — sama
alasannya dgn Golden Setup 4H: field baru ini di luar skema zone_scans
saat ini, migrasi skema (kalau diperlukan) pekerjaan terpisah.
"""

import logging
from datetime import datetime
from typing import Optional

from core.data_feed import DataFeed, get_catalyst_universe
from core.structure_signals import compute_bullish_structure

logger = logging.getLogger(__name__)

MIN_BARS_REQUIRED = 260  # sama dgn zone_scanner/golden_setup_scanner — buffer ATR(200)+swing(50)
RECENT_WINDOW = 5        # hari bursa — disepakati eksplisit dgn user (v10.9.1, tetap dipakai v10.9.2)


def _latest_of_kind(events: list, kind: str):
    matches = [e for e in events if e.kind == kind]
    return max(matches, key=lambda e: e.bar_index) if matches else None


def _process_one_ticker(ticker: str, df) -> tuple:
    """Return (status, row) — status in {"skip","crash","no_match","ok"}.
    Worker terisolasi, pola sama dgn zone_scanner.py/golden_setup_scanner.py."""
    if df is None or len(df) < MIN_BARS_REQUIRED:
        return ("skip", None)
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df = df.copy()
        df.columns = df.columns.get_level_values(0)

    base_ticker = ticker.replace(".JK", "")
    try:
        sig = compute_bullish_structure(df, ticker=base_ticker)
    except Exception as exc:
        logger.debug(f"[StructureFresh] {ticker}: engine crash — {exc}")
        return ("crash", None)

    if sig is None:
        return ("skip", None)

    n = len(df)
    cutoff = n - RECENT_WINDOW
    recent = [e for e in sig.events if e.bar_index >= cutoff]

    bos_ev = _latest_of_kind(recent, "BOS")
    choch_ev = _latest_of_kind(recent, "CHOCH")
    eql_ev = _latest_of_kind(recent, "EQL")

    # v10.9.2: OR, bukan AND — cukup SALAH SATU yang baru terbentuk.
    if not (bos_ev or choch_ev or eql_ev):
        return ("no_match", None)

    last_bar = n - 1

    def _days_ago(ev):
        return last_bar - ev.bar_index

    def _date_str(ev):
        return ev.date.strftime("%Y-%m-%d") if hasattr(ev.date, "strftime") else str(ev.date)

    row = {
        "ticker": base_ticker,
        "close": float(df["Close"].iloc[-1]),
        "internal_bias": sig.internal_trend_bias,
        "swing_bias": sig.swing_trend_bias,
        "bos_date": _date_str(bos_ev) if bos_ev else None,
        "bos_scope": bos_ev.scope if bos_ev else None,
        "bos_level": bos_ev.level if bos_ev else None,
        "bos_days_ago": _days_ago(bos_ev) if bos_ev else None,
        "choch_date": _date_str(choch_ev) if choch_ev else None,
        "choch_scope": choch_ev.scope if choch_ev else None,
        "choch_level": choch_ev.level if choch_ev else None,
        "choch_days_ago": _days_ago(choch_ev) if choch_ev else None,
        "eql_date": _date_str(eql_ev) if eql_ev else None,
        "eql_level": eql_ev.level if eql_ev else None,
        "eql_days_ago": _days_ago(eql_ev) if eql_ev else None,
    }
    present_days_ago = [v for v in
                        (row["bos_days_ago"], row["choch_days_ago"], row["eql_days_ago"])
                        if v is not None]
    row["freshness"] = min(present_days_ago)
    row["match_kinds"] = [k for k, ev in (("BOS", bos_ev), ("CHOCH", choch_ev), ("EQL", eql_ev)) if ev]
    return ("ok", row)


class StructureFreshScanner:
    """Scan full universe (default) cari ticker dgn SALAH SATU dari
    BOS/CHoCH/EQL biru baru terbentuk dalam RECENT_WINDOW hari bursa
    terakhir (v10.9.2 — OR, bukan AND). Sekuensial (sama spt ZoneScanner
    — lihat catatan benchmark di zone_scanner.py soal kenapa paralelisasi
    loop ini terbukti regresi, bukan asumsi)."""

    def __init__(self):
        self.feed = DataFeed(timeframe="1d", period="2y")

    def scan(self, tickers: Optional[list] = None, full_universe: bool = True,
             max_workers: int = 8) -> tuple:
        tickers = tickers or get_catalyst_universe(full_universe=full_universe)

        logger.info(f"[StructureFresh] Batch downloading {len(tickers)} tickers (period=2y)...")
        data = self.feed.fetch_batch(tickers, max_workers=max_workers)
        logger.info(f"[StructureFresh] Data ready: {len(data)} tickers")

        results = []
        analyzed = 0
        skipped = 0
        crashed = 0

        for i, ticker in enumerate(tickers):
            status, row = _process_one_ticker(ticker, data.get(ticker))
            if status == "skip":
                skipped += 1
            elif status == "crash":
                crashed += 1
            elif status == "no_match":
                analyzed += 1
            else:
                analyzed += 1
                results.append(row)
                if (i + 1) % 100 == 0:
                    logger.info(f"[StructureFresh] {i+1}/{len(tickers)} | {len(results)} match")

        results.sort(key=lambda r: r["freshness"])
        ctx = {
            "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "total_universe": len(tickers), "analyzed": analyzed,
            "skipped_short_history": skipped, "crashed": crashed,
            "match_count": len(results),
        }
        logger.info(f"[StructureFresh] Done: {len(results)} match | "
                    f"{skipped} skip | {crashed} crash | {analyzed} dianalisis")
        return results, ctx
