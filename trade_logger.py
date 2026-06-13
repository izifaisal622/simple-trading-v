"""
Simple Trading V6 — Trade Logger
CHANGELOG V4 (Audit Fixes):
  - FIX CRITICAL: Tambah sl_price kolom agar pnl_r bisa dihitung dengan benar
  - FIX CRITICAL: close_trade() kini hitung pnl_r menggunakan entry_price DAN sl_price
  - NEW: get_stats() — mengembalikan win rate, avg R, expectancy, total trades
  - NEW: get_performance_summary() — untuk Director Agent dan Learning Agent
  - NEW: log_signal_taken() — log sinyal yang DIPILIH untuk di-track (sebelum exit)
  - NEW: update_open_price() — update harga entry aktual (bisa berbeda dari sinyal)

Tabel manual_trades kini punya:
  - sl_price: WAJIB untuk kalkulasi R yang benar
  - signal_score: score dari EMA XBO saat sinyal diambil
  - regime_tag: market regime saat entry
  - signal_type: BREAKOUT / WATCHLIST / CORRECTING
"""

import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional

LOGS_DIR = Path(__file__).parent / "logs"
DB_PATH  = LOGS_DIR / "trade_log.db"
LOGS_DIR.mkdir(exist_ok=True)


def init_db():
    """Inisialisasi schema database. Safe untuk dipanggil berulang kali."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS manual_trades (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker       TEXT    NOT NULL,
            entry_date   TEXT,
            entry_price  REAL,
            sl_price     REAL,           -- FIX V4: WAJIB untuk pnl_r yang benar
            exit_date    TEXT,
            exit_price   REAL,
            outcome      TEXT,           -- OPEN / WIN / LOSS / BREAKEVEN
            pnl_r        REAL,           -- P&L dalam satuan R (1R = risk awal)
            pnl_pct      REAL,           -- P&L dalam % dari entry
            bars_held    INTEGER,
            strategy     TEXT    DEFAULT 'EMA_XBO',
            signal_type  TEXT,           -- NEW V4: BREAKOUT/WATCHLIST/CORRECTING
            signal_score INTEGER,        -- NEW V4: score saat sinyal diambil
            regime_tag   TEXT,           -- NEW V4: FULL/SPECULATIVE/WATCHLIST_ONLY
            mcf_score    INTEGER,        -- NEW V4: MCF score saat entry
            notes        TEXT
        );

        CREATE TABLE IF NOT EXISTS outcomes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT    NOT NULL,
            signal_date TEXT,
            outcome     TEXT,
            pnl_r       REAL,
            logged_at   TEXT    DEFAULT (datetime('now'))
        );
    """)

    # Migrasi: tambah kolom baru jika belum ada (untuk upgrade dari V5)
    _migrate_add_column(conn, "manual_trades", "sl_price",     "REAL")
    _migrate_add_column(conn, "manual_trades", "signal_type",  "TEXT")
    _migrate_add_column(conn, "manual_trades", "signal_score", "INTEGER")
    _migrate_add_column(conn, "manual_trades", "regime_tag",   "TEXT")
    _migrate_add_column(conn, "manual_trades", "mcf_score",    "INTEGER")

    conn.commit()
    conn.close()


def _migrate_add_column(conn: sqlite3.Connection, table: str, col: str, col_type: str):
    """Tambah kolom baru jika belum ada — safe upgrade."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
    except sqlite3.OperationalError:
        pass  # Kolom sudah ada


def log_trade(
    ticker:       str,
    entry_price:  float,
    sl_price:     float,              # FIX V4: parameter wajib
    tp1_price:    float = 0.0,
    signal_type:  str   = "UNKNOWN",  # NEW V4
    signal_score: int   = 0,          # NEW V4
    regime_tag:   str   = "",         # NEW V4
    mcf_score:    int   = 0,          # NEW V4
    strategy:     str   = "EMA_XBO",
    notes:        str   = "",
) -> int:
    """
    Catat trade baru yang DIBUKA.
    Mengembalikan trade_id untuk digunakan saat close_trade().
    """
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute("""
        INSERT INTO manual_trades
        (ticker, entry_date, entry_price, sl_price, outcome,
         signal_type, signal_score, regime_tag, mcf_score, strategy, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        ticker,
        datetime.now().strftime("%Y-%m-%d"),
        entry_price,
        sl_price,
        "OPEN",
        signal_type,
        signal_score,
        regime_tag,
        mcf_score,
        strategy,
        notes,
    ))
    trade_id = cur.lastrowid
    conn.commit()
    conn.close()
    return trade_id


def close_trade(
    trade_id:   int,
    exit_price: float,
    outcome:    str,    # WIN / LOSS / BREAKEVEN
    notes:      str = "",
) -> dict:
    """
    Tutup trade yang sudah open. Hitung pnl_r menggunakan sl_price.

    FIX V4: pnl_r kini dihitung dari sl_price (bukan hardcoded risk).
    Formula: pnl_r = (exit_price - entry_price) / (entry_price - sl_price)
    """
    init_db()
    conn = sqlite3.connect(str(DB_PATH))

    row = conn.execute(
        "SELECT entry_price, sl_price, entry_date FROM manual_trades WHERE id=?",
        (trade_id,)
    ).fetchone()

    if not row:
        conn.close()
        return {"success": False, "error": f"Trade ID {trade_id} tidak ditemukan"}

    entry_price, sl_price, entry_date = row

    # Hitung P&L
    risk = (entry_price - sl_price) if sl_price and sl_price < entry_price else entry_price * 0.05
    pnl_r   = round((exit_price - entry_price) / risk, 2) if risk > 0 else None
    pnl_pct = round((exit_price - entry_price) / entry_price * 100, 2) if entry_price > 0 else None

    # Hitung bars held (hari trading aktual dengan numpy.busday_count — V6.4)
    bars_held = None
    try:
        import numpy as _np
        entry_dt = datetime.strptime(entry_date, "%Y-%m-%d")
        exit_dt  = datetime.now()
        # IDX trading days: Senin-Jumat. numpy.busday_count excludes weekends.
        # Tidak menghitung libur nasional (unavailable from free sources) tapi jauh
        # lebih akurat dari estimasi *5/7 yang salah untuk libur panjang.
        bars_held = max(0, int(_np.busday_count(
            entry_dt.date(),
            exit_dt.date(),
            weekmask="Mon Tue Wed Thu Fri"
        )))
    except Exception as _e:
        # Fallback ke estimasi jika numpy gagal
        try:
            cal_days  = (datetime.now() - datetime.strptime(entry_date, "%Y-%m-%d")).days
            bars_held = max(1, int(round(cal_days * 5 / 7))) if cal_days > 0 else 0
        except Exception:
            pass

    existing_notes = conn.execute(
        "SELECT notes FROM manual_trades WHERE id=?", (trade_id,)
    ).fetchone()
    combined_notes = f"{(existing_notes[0] or '')} | {notes}".strip(" |") if notes else (existing_notes[0] or "")

    conn.execute("""
        UPDATE manual_trades
        SET exit_price=?, exit_date=?, outcome=?, pnl_r=?, pnl_pct=?, bars_held=?, notes=?
        WHERE id=?
    """, (
        exit_price,
        datetime.now().strftime("%Y-%m-%d"),
        outcome,
        pnl_r,
        pnl_pct,
        bars_held,
        combined_notes,
        trade_id,
    ))
    conn.commit()
    conn.close()

    return {
        "success":    True,
        "trade_id":   trade_id,
        "pnl_r":      pnl_r,
        "pnl_pct":    pnl_pct,
        "bars_held":  bars_held,
        "outcome":    outcome,
    }


def get_open_trades() -> list:
    """Ambil semua trade yang masih open."""
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT * FROM manual_trades
        WHERE outcome IS NULL OR outcome = 'OPEN'
        ORDER BY entry_date DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_closed_trades(limit: int = 100) -> list:
    """Ambil trade yang sudah closed, terbaru dulu."""
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT * FROM manual_trades
        WHERE outcome IN ('WIN', 'LOSS', 'BREAKEVEN')
        ORDER BY exit_date DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    """
    Hitung statistik performa dari closed trades.

    NEW V4: Ini adalah fungsi yang kritis untuk mengetahui apakah tool bekerja.
    Tanpa closed trades, semua metrik akan N/A.
    """
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    all_closed = conn.execute("""
        SELECT * FROM manual_trades
        WHERE outcome IN ('WIN', 'LOSS', 'BREAKEVEN')
        AND pnl_r IS NOT NULL
    """).fetchall()

    open_count = conn.execute("""
        SELECT COUNT(*) FROM manual_trades
        WHERE outcome IS NULL OR outcome = 'OPEN'
    """).fetchone()[0]

    conn.close()

    trades = [dict(r) for r in all_closed]
    n = len(trades)

    if n == 0:
        return {
            "total_closed": 0,
            "total_open":   open_count,
            "min_required": 30,
            "sufficient":   False,
            "win_rate":     None,
            "avg_r":        None,
            "expectancy":   None,
            "avg_win_r":    None,
            "avg_loss_r":   None,
            "profit_factor":None,
            "max_consec_loss": None,
            "note": "BELUM ADA DATA. Minimal 30 closed trades diperlukan untuk validasi.",
        }

    wins    = [t for t in trades if t["outcome"] == "WIN"]
    losses  = [t for t in trades if t["outcome"] == "LOSS"]
    n_wins  = len(wins)
    n_loss  = len(losses)

    win_rate    = round(n_wins / n * 100, 1) if n > 0 else 0
    avg_r       = round(sum(t["pnl_r"] for t in trades) / n, 2) if n > 0 else 0
    avg_win_r   = round(sum(t["pnl_r"] for t in wins) / n_wins, 2) if n_wins > 0 else 0
    avg_loss_r  = round(sum(t["pnl_r"] for t in losses) / n_loss, 2) if n_loss > 0 else 0

    # Expectancy: E = (WinRate × AvgWin) + (LossRate × AvgLoss)
    win_rate_dec  = n_wins / n
    loss_rate_dec = n_loss / n
    expectancy    = round(win_rate_dec * avg_win_r + loss_rate_dec * avg_loss_r, 3)

    # Profit factor
    gross_profit = sum(t["pnl_r"] for t in wins)  if wins   else 0
    gross_loss   = abs(sum(t["pnl_r"] for t in losses)) if losses else 0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

    # Max consecutive losses
    max_consec_loss = 0
    curr_consec     = 0
    for t in sorted(trades, key=lambda x: x.get("exit_date") or ""):
        if t["outcome"] == "LOSS":
            curr_consec += 1
            max_consec_loss = max(max_consec_loss, curr_consec)
        else:
            curr_consec = 0

    return {
        "total_closed":    n,
        "total_open":      open_count,
        "total_wins":      n_wins,
        "total_losses":    n_loss,
        "min_required":    30,
        "sufficient":      n >= 30,
        "win_rate":        win_rate,
        "avg_r":           avg_r,
        "expectancy":      expectancy,
        "avg_win_r":       avg_win_r,
        "avg_loss_r":      avg_loss_r,
        "profit_factor":   profit_factor,
        "max_consec_loss": max_consec_loss,
        "note": (
            f"✓ Sufficient data ({n}/30)" if n >= 30
            else f"⚠ Butuh {30-n} trades lagi untuk validasi penuh ({n}/30)"
        ),
    }


def get_performance_summary() -> str:
    """Kembalikan summary string untuk Director/Learning Agent."""
    stats = get_stats()
    if stats["total_closed"] == 0:
        return "⚠ ZERO CLOSED TRADES — sistem belum bisa belajar apapun."

    n = stats["total_closed"]
    lines = [
        f"📊 PERFORMANCE SUMMARY ({n} closed trades)",
        f"  Win Rate   : {stats['win_rate']:.1f}%",
        f"  Avg R      : {stats['avg_r']:+.2f}R per trade",
        f"  Expectancy : {stats['expectancy']:+.3f}R",
        f"  Avg Win    : +{stats['avg_win_r']:.2f}R | Avg Loss: {stats['avg_loss_r']:.2f}R",
        f"  Profit F.  : {stats['profit_factor'] or 'N/A'}",
        f"  Max Streak : {stats['max_consec_loss']} consecutive losses",
        f"  Status     : {stats['note']}",
    ]

    if stats["win_rate"] is not None:
        if stats["win_rate"] >= 50 and stats["expectancy"] > 0:
            lines.append("  Verdict    : ✅ PROMISING — win rate > 50%, expectancy positif")
        elif stats["expectancy"] > 0:
            lines.append("  Verdict    : ⚠ BORDERLINE — expectancy positif tapi win rate < 50%")
        else:
            lines.append("  Verdict    : ❌ UNPROFITABLE — expectancy negatif")

    return "\n".join(lines)


def delete_trade(trade_id: int) -> dict:
    """
    Hapus trade dari database (bukan close — ini untuk salah input).
    Mengembalikan dict {success, error}.
    NEW V6.3.2
    """
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT ticker, entry_date FROM manual_trades WHERE id=?", (trade_id,)
    ).fetchone()
    if not row:
        conn.close()
        return {"success": False, "error": f"Trade ID {trade_id} tidak ditemukan"}
    conn.execute("DELETE FROM manual_trades WHERE id=?", (trade_id,))
    conn.commit()
    conn.close()
    return {"success": True, "deleted_ticker": row[0], "deleted_date": row[1]}


def log_trade_manual(
    ticker:       str,
    entry_price:  float,
    sl_price:     float,
    entry_date:   str   = "",
    signal_type:  str   = "MANUAL",
    signal_score: int   = 0,
    regime_tag:   str   = "",
    strategy:     str   = "EMA_XBO",
    notes:        str   = "",
) -> int:
    """
    Log trade manual dengan tanggal custom (bisa berbeda dari hari ini).
    Untuk kasus lupa input saat sinyal keluar.
    NEW V6.3.2
    """
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    entry_date_val = entry_date if entry_date else datetime.now().strftime("%Y-%m-%d")
    cur = conn.execute("""
        INSERT INTO manual_trades
        (ticker, entry_date, entry_price, sl_price, outcome,
         signal_type, signal_score, regime_tag, strategy, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        ticker.upper(),
        entry_date_val,
        entry_price,
        sl_price,
        "OPEN",
        signal_type,
        signal_score,
        regime_tag,
        strategy,
        notes,
    ))
    trade_id = cur.lastrowid
    conn.commit()
    conn.close()
    return trade_id
