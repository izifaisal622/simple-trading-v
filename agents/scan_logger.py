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
    # v9.8.9: migrasi kolom threshold utk DB yang sudah ada (fail-safe idempotent)
    for col in ("vol_multiplier_used REAL", "min_value_bn_used REAL"):
        try:
            conn.execute(f"ALTER TABLE whale_scans ADD COLUMN {col}")
        except Exception:
            pass  # kolom sudah ada
    try:
        conn.execute("ALTER TABLE ema_scans ADD COLUMN score_max INTEGER")
    except Exception:
        pass  # kolom sudah ada / tabel belum ada (dibuat _ensure_ema_table)
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
                float(ctx.get("vol_multiplier_used", 0) or 0),
                float(ctx.get("min_value_bn_used", 0) or 0),
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
             gradual_strength, in_ob_zone, rs_20d, ihsg_regime, broker_live, raw_json,
             vol_multiplier_used, min_value_bn_used)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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


# ============================================================
# TAHAP 2 — Backfill forward returns
# Entry basis: OPEN hari bursa pertama SETELAH scan_date (open H+1).
# Alasan: scan dilakukan setelah pasar tutup; close hari scan tidak
# bisa dieksekusi. Mengukur dari close menggelembungkan hit-rate.
# fwd_ret_Nd  = Close(entry_idx + N) / Open(entry_idx) - 1
# mae_20d     = min(Low[entry..entry+20]) / Open(entry) - 1
# mfe_20d     = max(High[entry..entry+20]) / Open(entry) - 1
# Partial fill: 5d/10d diisi begitu datanya cukup; backfilled_at
# hanya di-set setelah horizon 20d lengkap.
# Throttle: max 1x per hari (tabel meta), supaya hook di scan()
# tidak memukul yfinance berulang.
# ============================================================

IHSG_TICKER = "^JKSE"


def _throttle_ok(conn: sqlite3.Connection) -> bool:
    conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    row = conn.execute("SELECT v FROM meta WHERE k='last_backfill'").fetchone()
    today = datetime.now().strftime("%Y-%m-%d")
    if row and row[0] == today:
        return False
    conn.execute("INSERT OR REPLACE INTO meta (k,v) VALUES ('last_backfill',?)", (today,))
    conn.commit()
    return True


def _horizon_metrics(df, scan_date: str):
    """Return dict metrik forward utk satu ticker, atau None kalau belum ada bar H+1."""
    import pandas as pd
    if df is None or df.empty:
        return None
    idx = df.index
    after = idx[idx > pd.Timestamp(scan_date)]
    if len(after) == 0:
        return None
    e = idx.get_loc(after[0])                      # entry bar (H+1)
    entry_open = float(df["Open"].iloc[e])
    if entry_open <= 0:
        return None
    out = {}
    for n, key in ((5, "fwd_ret_5d"), (10, "fwd_ret_10d"), (20, "fwd_ret_20d")):
        if e + n < len(df):
            out[key] = float(df["Close"].iloc[e + n]) / entry_open - 1.0
    if e + 20 < len(df):
        win = df.iloc[e:e + 21]
        out["mae_20d"] = float(win["Low"].min()) / entry_open - 1.0
        out["mfe_20d"] = float(win["High"].max()) / entry_open - 1.0
    return out or None


def _ensure_ema_table(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS ema_scans (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker        TEXT NOT NULL,
        scan_date     TEXT NOT NULL,
        scan_ts       TEXT NOT NULL,
        close_price   REAL,
        score         INTEGER,
        signal        TEXT,
        cross_state   TEXT,
        vol_ratio     REAL,
        rs_4w         REAL,
        risk_pct      REAL,
        rr_ratio      REAL,
        entry_price   REAL,
        sl_price      REAL,
        tp1_price     REAL,
        box_high      REAL,
        box_low       REAL,
        regime        TEXT,
        mcf_blocked   INTEGER DEFAULT 0,
        raw_json      TEXT,
        score_max     INTEGER,
        fwd_ret_5d    REAL, fwd_ret_10d REAL, fwd_ret_20d REAL,
        ihsg_ret_5d   REAL, ihsg_ret_10d REAL, ihsg_ret_20d REAL,
        mae_20d       REAL, mfe_20d REAL,
        backfilled_at TEXT,
        created_at    TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(ticker, scan_date)
    );
    """)


def log_ema_results(results: list, regime) -> int:
    """
    v9.8.5 — feedback loop page 1: snapshot hasil EMA XBO scan ke ema_scans.
    Dipanggil di scanner_agent.save_results (backend, satu titik untuk semua
    pemicu: page 1 maupun orchestrator). Kontrak sama dengan whale:
    UNIQUE(ticker, scan_date), fail-safe, fwd_* menunggu backfill.
    """
    if not results:
        return 0
    now = datetime.now()
    scan_date = now.strftime("%Y-%m-%d")
    scan_ts = now.strftime("%Y-%m-%d %H:%M:%S")
    regime_s = str(regime.get("regime", regime) if isinstance(regime, dict) else regime)

    rows = []
    for r in results:
        try:
            rows.append((
                str(r.get("ticker", "")).strip(), scan_date, scan_ts,
                float(r.get("close", 0) or 0),
                int(r.get("score", 0) or 0),
                str(r.get("signal", "")),
                str(r.get("cross_state", "")),
                float(r.get("vol_ratio", 0) or 0),
                float(r.get("rs_vs_ihsg_4w", 0) or 0),
                float(r.get("risk_pct", 0) or 0),
                float(r.get("rr_ratio", 0) or 0),
                float(r.get("entry_price", 0) or 0),
                float(r.get("sl_price", 0) or 0),
                float(r.get("tp1_price", 0) or 0),
                float(r.get("box_high", 0) or 0),
                float(r.get("box_low", 0) or 0),
                regime_s,
                1 if r.get("mcf_bear_blocked") else 0,
                json.dumps(r, default=str, ensure_ascii=False),
                int(r.get("score_max", 8) or 8),  # v9.9.1: baris lama NULL = skala 8
            ))
        except Exception as exc:
            logger.warning(f"[ScanLogger] ema skip {r.get('ticker','?')}: {exc}")
    if not rows:
        return 0
    try:
        conn = _get_conn()
        _ensure_ema_table(conn)
        conn.executemany("""
            INSERT OR REPLACE INTO ema_scans
            (ticker, scan_date, scan_ts, close_price, score, signal, cross_state,
             vol_ratio, rs_4w, risk_pct, rr_ratio, entry_price, sl_price, tp1_price,
             box_high, box_low, regime, mcf_blocked, raw_json, score_max)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        conn.commit()
        conn.close()
        logger.info(f"[ScanLogger] {len(rows)} ema rows tersimpan ({scan_date})")
        return len(rows)
    except Exception as exc:
        logger.error(f"[ScanLogger] ema gagal simpan: {exc}")
        return 0


def _ensure_flow_table(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS flow_scans (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker        TEXT NOT NULL,
        scan_date     TEXT NOT NULL,
        scan_ts       TEXT NOT NULL,
        close_price   REAL,
        signal        TEXT,
        source        TEXT,
        vol_ratio     REAL,
        pct_chg       REAL,
        close_pos     REAL,
        raw_json      TEXT,
        fwd_ret_5d    REAL, fwd_ret_10d REAL, fwd_ret_20d REAL,
        ihsg_ret_5d   REAL, ihsg_ret_10d REAL, ihsg_ret_20d REAL,
        mae_20d       REAL, mfe_20d REAL,
        backfilled_at TEXT,
        created_at    TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(ticker, scan_date)
    );
    """)


def log_flow_results(results: list) -> int:
    """v9.8.8 — feedback loop flow (War Room): snapshot semua sinyal flow.
    Menutup satu-satunya sistem sinyal yang belum terukur."""
    if not results:
        return 0
    now = datetime.now()
    scan_date = now.strftime("%Y-%m-%d")
    scan_ts = now.strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for r in results:
        try:
            rows.append((
                str(r.get("ticker", "")).strip(), scan_date, scan_ts,
                float(r.get("close", r.get("last_price", 0)) or 0),
                str(r.get("signal", "")),
                str(r.get("source", "")),
                float(r.get("vol_ratio", 0) or 0),
                float(r.get("pct_chg", 0) or 0),
                float(r.get("close_pos", 0) or 0),
                json.dumps(r, default=str, ensure_ascii=False),
            ))
        except Exception as exc:
            logger.warning(f"[ScanLogger] flow skip {r.get('ticker','?')}: {exc}")
    if not rows:
        return 0
    try:
        conn = _get_conn()
        _ensure_flow_table(conn)
        conn.executemany("""
            INSERT OR REPLACE INTO flow_scans
            (ticker, scan_date, scan_ts, close_price, signal, source,
             vol_ratio, pct_chg, close_pos, raw_json)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, rows)
        conn.commit()
        conn.close()
        logger.info(f"[ScanLogger] {len(rows)} flow rows tersimpan ({scan_date})")
        return len(rows)
    except Exception as exc:
        logger.error(f"[ScanLogger] flow gagal simpan: {exc}")
        return 0


def _backfill_table(conn, table: str, max_rows: int, pd, yf) -> int:
    """Worker generik backfill satu tabel (whale_scans / ema_scans). Entry basis: open H+1."""
    rows = conn.execute(f"""
        SELECT id, ticker, scan_date FROM {table}
        WHERE backfilled_at IS NULL
          AND julianday('now') - julianday(scan_date) >= 3
        ORDER BY scan_date LIMIT ?
    """, (max_rows,)).fetchall()
    if not rows:
        return 0

    oldest = min(r[2] for r in rows)
    start = (pd.Timestamp(oldest) - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    # ema_scans menyimpan ticker tanpa .JK; whale dengan .JK — seragamkan ke .JK utk download
    def _sym(t):
        return t if t.endswith(".JK") or t.startswith("^") else f"{t}.JK"
    tickers = sorted({_sym(r[1]) for r in rows})

    data = yf.download(tickers + [IHSG_TICKER], start=start, interval="1d",
                       group_by="ticker", auto_adjust=False,
                       progress=False, threads=True)

    def _slice(sym):
        try:
            d = data[sym] if len(tickers) + 1 > 1 else data
            return d.dropna(subset=["Open", "Close"])
        except Exception:
            return None

    ihsg = _slice(IHSG_TICKER)
    updated = 0
    for row_id, tkr, sdate in rows:
        m = _horizon_metrics(_slice(_sym(tkr)), sdate)
        if not m:
            continue
        im = _horizon_metrics(ihsg, sdate) or {}
        sets, vals = [], []
        for col in ("fwd_ret_5d", "fwd_ret_10d", "fwd_ret_20d", "mae_20d", "mfe_20d"):
            if col in m:
                sets.append(f"{col}=?"); vals.append(round(m[col], 6))
        for s_, c_ in (("fwd_ret_5d", "ihsg_ret_5d"), ("fwd_ret_10d", "ihsg_ret_10d"),
                       ("fwd_ret_20d", "ihsg_ret_20d")):
            if s_ in im:
                sets.append(f"{c_}=?"); vals.append(round(im[s_], 6))
        if "fwd_ret_20d" in m:
            sets.append("backfilled_at=?")
            vals.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        if sets:
            vals.append(row_id)
            conn.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=?", vals)
            updated += 1
    logger.info(f"[ScanLogger] backfill {table}: {updated}/{len(rows)} baris ter-update")
    return updated


def backfill_forward_returns(max_rows: int = 500) -> int:
    """
    v9.8.5 — satu mesin backfill, dua tabel (whale_scans + ema_scans).
    Entry basis open H+1, throttle 1x/hari (bersama), fail-safe total.
    """
    try:
        import pandas as pd
        import yfinance as yf

        conn = _get_conn()
        _ensure_ema_table(conn)
        _ensure_flow_table(conn)
        if not _throttle_ok(conn):
            conn.close()
            return 0
        total = 0
        for table in ("whale_scans", "ema_scans", "flow_scans"):
            try:
                total += _backfill_table(conn, table, max_rows, pd, yf)
            except Exception as exc:
                logger.error(f"[ScanLogger] backfill {table} gagal: {exc}")
        conn.commit()
        conn.close()
        return total
    except Exception as exc:
        logger.error(f"[ScanLogger] backfill gagal: {exc}")
        return 0
