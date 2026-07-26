"""
agents/zone_scanner.py — Orkestrasi scan universe utk sistem baru (VIDYA+SMC
retest-zone conviction, tahap 1-2 di core/ob_engine.py + core/conviction_engine.py).

Pola mengikuti whale_scanner.py/scanner_agent.py: satu universe (doktrin
"satu sumber" — get_catalyst_universe(full_universe=True)), fetch_batch
dgn cache pipeline yang sudah ada, hasil per-ticker jadi dict siap kartu.

TIDAK mengganti DailyEMAEngine — berjalan sbg sistem terpisah sampai UI/
halaman tahap 3 sub-B menentukan bagaimana ia disajikan.
"""

import logging
from datetime import datetime
from typing import Optional

from core.data_feed import DataFeed, get_catalyst_universe, get_pk_set, get_ihsg_regime
from core.conviction_engine import run_conviction, STATE_WATCHING

logger = logging.getLogger(__name__)

MIN_BARS_REQUIRED = 260  # ATR(200) butuh min_periods=200 + swing_size(50) buffer


class ZoneScanner:
    def __init__(self, internal_size: int = 5, swing_size: int = 50):
        self.internal_size = internal_size
        self.swing_size = swing_size
        self.feed = DataFeed(timeframe="1d", period="2y")  # sesuai diagnostik yg terbukti cukup

    def scan(self, tickers: Optional[list] = None, full_universe: bool = True,
             max_workers: int = 8) -> tuple:
        """Return (results: list[dict], ctx: dict). Hanya ticker dgn zona
        WATCHING (conviction>0) yang masuk results — IDLE tak ditampilkan
        (tak ada apa pun utk dilaporkan), tapi SEMUA ticker yg berhasil
        dianalisis tetap di-LOG (utk feedback loop, termasuk yg IDLE)."""
        tickers = tickers or get_catalyst_universe(full_universe=full_universe)
        regime_data = get_ihsg_regime()
        pk_set = get_pk_set()

        logger.info(f"[Zone] Batch downloading {len(tickers)} tickers (period=2y)...")
        data = self.feed.fetch_batch(tickers, max_workers=max_workers)
        logger.info(f"[Zone] Data ready: {len(data)} tickers")

        results = []
        all_scanned = []  # termasuk IDLE — utk logging feedback loop lengkap
        skipped_short = 0
        crashed = 0

        for i, ticker in enumerate(tickers):
            df = data.get(ticker)
            if df is None or len(df) < MIN_BARS_REQUIRED:
                skipped_short += 1
                continue
            if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                df = df.copy()
                df.columns = df.columns.get_level_values(0)

            try:
                states = run_conviction(df, internal_size=self.internal_size,
                                        swing_size=self.swing_size)
            except Exception as exc:
                crashed += 1
                logger.debug(f"[Zone] {ticker}: engine crash — {exc}")
                continue

            latest = states[-1]
            base_ticker = ticker.replace(".JK", "")
            row = {
                "ticker": base_ticker,
                "close": latest.close,
                "status": latest.status,
                "conviction_pct": latest.conviction_pct,
                "zone_top": latest.zone_top,
                "zone_bottom": latest.zone_bottom,
                "formed_bar_index": latest.formed_bar_index,
                "bars_since_formed": (len(states) - 1 - latest.formed_bar_index) if latest.formed_bar_index is not None else None,
                "retest_hold_days": latest.retest_hold_days,
                "base_pct": latest.base_pct, "retest_pct": latest.retest_pct,
                "vidya_pct": latest.vidya_pct, "volume_pct": latest.volume_pct,
                "structure_pct": latest.structure_pct,
                "pk_board": base_ticker in pk_set,
            }
            all_scanned.append(row)
            if latest.status == STATE_WATCHING and latest.conviction_pct > 0:
                results.append(row)

            if (i + 1) % 100 == 0:
                logger.info(f"[Zone] {i+1}/{len(tickers)} | {len(results)} watching")

        results.sort(key=lambda r: -r["conviction_pct"])
        ctx = {
            "regime": regime_data.get("regime", "UNKNOWN"),
            "scan_date": datetime.now().strftime("%Y-%m-%d"),
            "total_universe": len(tickers), "analyzed": len(all_scanned),
            "skipped_short_history": skipped_short, "crashed": crashed,
            "watching_count": len(results),
        }
        logger.info(f"[Zone] Done: {len(results)} watching | {skipped_short} skip(data pendek) | {crashed} crash | {len(all_scanned)} total logged")

        try:
            from agents.scan_logger import log_zone_results
            log_zone_results(all_scanned, ctx)
        except Exception as exc:
            logger.error(f"[Zone] log gagal: {exc}")

        return results, ctx
