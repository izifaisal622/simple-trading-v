"""
agents/scan_logger.py — Whale scan feedback loop, tahap 1 (logging).

Tujuan: setiap hasil scan tersimpan permanen supaya conviction/quality
bisa diuji terhadap forward return aktual (backfill = tahap 2,
halaman evaluasi = tahap 3).

Pola mengikuti agents/journal_agent.py: SQLite di LOGS_DIR, satu modul
satu tabel, CREATE TABLE IF NOT EXISTS.

Kontrak:
- log_scan_results(results, ctx) dipanggil SEKALI di akhir WhaleScanner.scan(),
  setelah capped_results final. Backend-driven — page 2 tidak menulis apa pun.
- UNIQUE(ticker, scan_date) + INSERT OR REPLACE: satu observasi per
  ticker per hari (scan terakhir menang). Mencegah pseudo-replication.
- Kolom fwd_*/mae/mfe NULL saat insert — diisi backfill (tahap 2).
- Logging tidak boleh menggagalkan scan: semua exception ditelan + logged.
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

LOGS_DIR = Path(__file__).parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)
DB_PATH = LOGS_DIR / "scan_history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS whale_scans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker        TEXT NOT NULL,
    scan_date     TEXT NOT NULL,              -- YYYY-MM-DD (tanggal bursa lokal)
    scan_ts       TEXT NOT NULL,              -- timestamp penuh scan terakhir

    -- Snapshot kondisi saat scan
    close_price   REAL,
    conviction    INTEGER,
    quality       TEXT,                       -- SMART / LIKELY_SMART / UNCERTAIN / ...
    signal        TEXT,
    entry_zone    TEXT,
    vol_ratio     REAL,
    pengeringan_strength INTEGER,
    control_score INTEGER,
    gradual_strength     INTEGER,
    in_ob_zone    INTEGER DEFAULT 0,          -- bool 0/1
    rs_20d        REAL,
    ihsg_regime   TEXT,                       -- dari ctx
    broker_live   INTEGER DEFAULT 0,          -- apakah data broker aktif saat scan
    raw_json      TEXT,                       -- full result dict, future-proofing

    -- Forward outcome — NULL sampai backfill (tahap 2)
    fwd_ret_5d    REAL,
    fwd_ret_10d   REAL,
    fwd_ret_20d   REAL,
    ihsg_ret_5d   REAL,
    ihsg_ret_10d  REAL,
    ihsg_ret_20d  REAL,
    mae_20d       REAL,                       -- max adverse excursion (%, negatif)
    mfe_20d       REAL,                       -- max favorable excursion (%)
    backfilled_at TEXT,

    created_at    TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(ticker, scan_date)
);
CREATE INDEX IF NOT EXISTS idx_ws_pending
    ON whale_scans(scan_date) WHERE backfilled_at IS NULL;
"""


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(_SCHEMA)
    return conn


def log_scan_results(results: list, ctx: dict) -> int:
    """
    Simpan snapshot hasil scan. Return jumlah baris tersimpan.
    Tidak pernah raise — kegagalan logging tidak boleh mematikan scan.
    """
    if not results:
        return 0
    now = datetime.now()
    scan_date = now.strftime("%Y-%m-%d")
    scan_ts = now.strftime("%Y-%m-%d %H:%M:%S")
    regime = str(ctx.get("regime", ctx.get("ihsg_regime", "")))

    rows = []
    for r in results:
        try:
            rows.append((
                r.get("ticker", ""), scan_date, scan_ts,
                float(r.get("last_price", r.get("close", 0)) or 0),
                int(r.get("conviction", 0) or 0),
                str(r.get("whale_quality", r.get("quality", ""))),
                str(r.get("signal", "")),
                str(r.get("entry_zone", "")),
                float(r.get("vol_ratio", 0) or 0),
                int(r.get("pengeringan_strength", 0) or 0),
                int(r.get("control_score", 0) or 0),
                int(r.get("gradual_strength", 0) or 0),
                1 if r.get("in_ob_zone") else 0,
                float(r.get("rs_20d", 0) or 0),
                regime,
                1 if r.get("broker_live") else 0,
                json.dumps(r, default=str, ensure_ascii=False),
            ))
        except Exception as exc:  # satu row rusak jangan gugurkan sisanya
            logger.warning(f"[ScanLogger] skip row {r.get('ticker','?')}: {exc}")

    if not rows:
        return 0
    try:
        conn = _get_conn()
        conn.executemany("""
            INSERT OR REPLACE INTO whale_scans
            (ticker, scan_date, scan_ts, close_price, conviction, quality,
             signal, entry_zone, vol_ratio, pengeringan_strength, control_score,
             gradual_strength, in_ob_zone, rs_20d, ihsg_regime, broker_live, raw_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        conn.commit()
        conn.close()
        logger.info(f"[ScanLogger] {len(rows)} scan rows tersimpan ({scan_date})")
        return len(rows)
    except Exception as exc:
        logger.error(f"[ScanLogger] gagal simpan: {exc}")
        return 0


def pending_backfill_count() -> int:
    """Jumlah baris yang belum di-backfill dan sudah cukup umur (>=20 hari kalender kasar)."""
    try:
        conn = _get_conn()
        n = conn.execute("""
            SELECT COUNT(*) FROM whale_scans
            WHERE backfilled_at IS NULL
              AND julianday('now') - julianday(scan_date) >= 30
        """).fetchone()[0]
        conn.close()
        return int(n)
    except Exception:
        return 0
