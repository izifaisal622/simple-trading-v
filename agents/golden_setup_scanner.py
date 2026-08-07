"""
agents/golden_setup_scanner.py — Fase 4-3: scanner TERPISAH utk "Golden
Setup 4H" (Page 1), v10.9.0.

KENAPA FILE TERPISAH, BUKAN EXTEND ZoneScanner: agents/zone_scanner.py
(scan daily, full universe, via DataFeed.fetch_batch yg SUDAH ada cache
pipeline) TIDAK disentuh sama sekali -- nol risiko ke jalur produksi yg
sudah jalan. fetch_4h() BELUM punya caching/batching (lihat catatan
core/data_feed.py Fase 1) -- scan full-universe ratusan ticker pakai itu
berisiko lambat/kena rate-limit Yahoo, BELUM PERNAH diuji di skala itu.
Scope sengaja dibatasi ke IDX_WATCHLIST (40 ticker) yg SUDAH terbukti
aman & cepat sepanjang sesi pengembangan Fase 2-4 (dipakai berulang kali
utk diagnose_4h_engine.py, diagnose_golden_setup.py, dll -- tidak pernah
gagal/rate-limited).

Params engine yg dipakai (SEMUA tervalidasi terpisah sblm ini):
  - extension_safe_atr=9.5   (Fase 2, 40-ticker, tervalidasi 2x)
  - use_ha_trend=True        (Fase 3-HA, VIDYA/band basis Heikin Ashi --
                               retest/invalidasi/pivot/ATR200 TETAP real)
  - golden_setup_bonus=True  (Fase 3 penutup, vidya_pct 15->20 saat
                               zone_ordinal_since_flip==1)

TIDAK ditulis ke logs/scan_history.db (skema tabel zone_scans belum py
kolom utk field baru) -- hasil scan session-only (Streamlit session_state),
konsisten dgn keputusan scope-kecil Fase 4-3. Persistensi DB, kalau
diperlukan nanti, adalah pekerjaan terpisah (migrasi skema).
"""

import logging
from datetime import datetime
from typing import Optional

from core.data_feed import fetch_4h, IDX_WATCHLIST
from core.conviction_engine import run_conviction, STATE_WATCHING

logger = logging.getLogger(__name__)

MIN_BARS_REQUIRED = 260


def _process_one_ticker(ticker: str) -> tuple:
    df = fetch_4h(ticker)
    if df is None or len(df) < MIN_BARS_REQUIRED:
        return ("skip", None)
    try:
        states = run_conviction(
            df, extension_safe_atr=9.5, use_ha_trend=True, golden_setup_bonus=True,
        )
    except Exception as exc:
        logger.debug(f"[Golden4H] {ticker}: engine crash — {exc}")
        return ("crash", None)

    latest = states[-1]
    base_ticker = ticker.replace(".JK", "")
    row = {
        "ticker": base_ticker,
        "close": latest.close,
        "status": latest.status,
        "conviction_pct": latest.conviction_pct,
        "zone_top": latest.zone_top,
        "zone_bottom": latest.zone_bottom,
        "retest_hold_days": latest.retest_hold_days,
        "base_pct": latest.base_pct, "retest_pct": latest.retest_pct,
        "vidya_pct": latest.vidya_pct, "volume_pct": latest.volume_pct,
        "structure_pct": latest.structure_pct,
        "extension_penalty": latest.extension_penalty,
        "extension_atr": latest.extension_atr,
        "bars_since_vidya_flip": latest.bars_since_vidya_flip,
        "zone_ordinal_since_flip": latest.zone_ordinal_since_flip,
        "is_golden_setup": latest.is_golden_setup,
    }
    return ("ok", row)


class GoldenSetupScanner4H:
    """Scan IDX_WATCHLIST (40 ticker) pakai engine 4h + HA-trend +
    golden_setup_bonus. Sekuensial (sama spt ZoneScanner — sudah terbukti
    ThreadPoolExecutor/ProcessPoolExecutor regresi utk walk-forward loop
    murni Python, lihat catatan zone_scanner.py)."""

    def scan(self, tickers: Optional[list] = None) -> tuple:
        tickers = tickers or IDX_WATCHLIST
        results = []
        all_scanned = []
        skipped_short = 0
        crashed = 0

        for i, ticker in enumerate(tickers):
            status, row = _process_one_ticker(ticker)
            if status == "skip":
                skipped_short += 1
            elif status == "crash":
                crashed += 1
            else:
                all_scanned.append(row)
                if row["status"] == STATE_WATCHING and row["conviction_pct"] > 0:
                    results.append(row)

        results.sort(key=lambda r: (-r["is_golden_setup"], -r["conviction_pct"]))
        ctx = {
            "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "total_universe": len(tickers), "analyzed": len(all_scanned),
            "skipped_short_history": skipped_short, "crashed": crashed,
            "watching_count": len(results),
            "golden_count": sum(1 for r in results if r["is_golden_setup"]),
        }
        logger.info(f"[Golden4H] Done: {len(results)} watching "
                    f"({ctx['golden_count']} golden setup) | {skipped_short} skip | {crashed} crash")
        return results, ctx
