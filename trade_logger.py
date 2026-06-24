"""
Simple Trading V9 — Trade Logger
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

# ── Database path — di luar repo agar tidak terpengaruh git pull/rollover ──
# Windows: C:\Users\<username>\AppData\Local\SimpleTrading\trade_log.db
# Fallback ke logs/ lokal jika APPDATA tidak tersedia (Linux/Mac dev environment)
import os as _os
_APPDATA = _os.environ.get("APPDATA") or _os.environ.get("HOME", "")
if _APPDATA:
    _STV_DATA_DIR = Path(_APPDATA) / "SimpleTrading"
else:
    _STV_DATA_DIR = Path(__file__).parent / "logs"
_STV_DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH  = _STV_DATA_DIR / "trade_log.db"
LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# ── Migrasi otomatis: jika DB lama ada di logs/, pindahkan ke lokasi baru ──
_OLD_DB = LOGS_DIR / "trade_log.db"
if _OLD_DB.exists() and not DB_PATH.exists():
    import shutil as _shutil
    _shutil.copy2(str(_OLD_DB), str(DB_PATH))
    print(f"[TradeLogger] DB migrated: {_OLD_DB} → {DB_PATH}")


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
            signal_score    INTEGER,     -- NEW V4: score saat sinyal diambil
            regime_tag      TEXT,        -- NEW V4: FULL/SPECULATIVE/WATCHLIST_ONLY
            mcf_score       INTEGER,     -- NEW V4: MCF score saat entry
            whale_quality   TEXT,        -- V9: SMART/LIKELY_SMART/UNCERTAIN/DUMB
            whale_conviction INTEGER,    -- V9: conviction score 0-10 saat entry
            notes           TEXT
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
    _migrate_add_column(conn, "manual_trades", "sl_price",        "REAL")
    _migrate_add_column(conn, "manual_trades", "signal_type",     "TEXT")
    _migrate_add_column(conn, "manual_trades", "signal_score",    "INTEGER")
    _migrate_add_column(conn, "manual_trades", "regime_tag",      "TEXT")
    _migrate_add_column(conn, "manual_trades", "mcf_score",       "INTEGER")
    _migrate_add_column(conn, "manual_trades", "whale_quality",   "TEXT")
    _migrate_add_column(conn, "manual_trades", "whale_conviction", "INTEGER")

    conn.commit()
    conn.close()


def _migrate_add_column(conn: sqlite3.Connection, table: str, col: str, col_type: str):
    """Tambah kolom baru jika belum ada — safe upgrade."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
    except sqlite3.OperationalError:
        pass  # Kolom sudah ada


def log_trade(
    ticker:           str,
    entry_price:      float,
    sl_price:         float,              # FIX V4: parameter wajib
    tp1_price:        float = 0.0,
    signal_type:      str   = "UNKNOWN",  # NEW V4
    signal_score:     int   = 0,          # NEW V4
    regime_tag:       str   = "",         # NEW V4
    mcf_score:        int   = 0,          # NEW V4
    whale_quality:    str   = "",         # V9: SMART/LIKELY_SMART/UNCERTAIN/DUMB
    whale_conviction: int   = 0,          # V9: conviction score 0-10
    strategy:         str   = "EMA_XBO",
    notes:            str   = "",
    entry_date:       str   = "",         # FIX 8.7.4: support custom entry date
) -> int:
    """
    Catat trade baru yang DIBUKA.
    Mengembalikan trade_id untuk digunakan saat close_trade().
    """
    entry_date_val = entry_date if entry_date else datetime.now().strftime("%Y-%m-%d")
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute("""
        INSERT INTO manual_trades
        (ticker, entry_date, entry_price, sl_price, outcome,
         signal_type, signal_score, regime_tag, mcf_score,
         whale_quality, whale_conviction, strategy, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        ticker,
        entry_date_val,
        entry_price,
        sl_price,
        "OPEN",
        signal_type,
        signal_score,
        regime_tag,
        mcf_score,
        whale_quality,
        whale_conviction,
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


def update_trade(
    trade_id:  int,
    sl_price:  float = None,
    tp1_price: float = None,
    tp2_price: float = None,
    notes:     str   = None,
) -> dict:
    """
    Revisi SL / TP1 / TP2 / Notes pada trade yang masih open.
    - sl_price  → kolom sl_price (ada di schema)
    - tp1_price → disimpan di notes sebagai 'tp1=xxxx'
    - tp2_price → disimpan di notes sebagai 'tp2=xxxx'
    - notes     → append ke notes bestehend
    """
    init_db()
    conn = sqlite3.connect(str(DB_PATH))

    row = conn.execute(
        "SELECT id, notes FROM manual_trades WHERE id=? AND outcome='OPEN'",
        (trade_id,)
    ).fetchone()

    if not row:
        conn.close()
        return {"success": False, "error": f"Trade #{trade_id} tidak ditemukan atau sudah closed"}

    _, existing_notes = row
    existing_notes = existing_notes or ""

    sets, vals = [], []

    # sl_price: kolom langsung
    if sl_price is not None:
        sets.append("sl_price=?")
        vals.append(sl_price)

    # tp1_price: update kolom tp1_price jika ada, selalu simpan ke notes juga
    if tp1_price is not None:
        # Coba update kolom tp1_price (mungkin ada di DB lama)
        try:
            conn.execute("UPDATE manual_trades SET tp1_price=? WHERE id=?", (tp1_price, trade_id))
        except Exception:
            pass  # kolom tidak ada — tidak apa, notes sudah cukup
        # Simpan ke notes string: ganti tp1= yang lama atau append
        parts = [p.strip() for p in existing_notes.split("|") if p.strip() and not p.strip().startswith("tp1=")]
        parts.append(f"tp1={tp1_price:.0f}")
        existing_notes = " | ".join(parts)

    # tp2_price: simpan ke notes string
    if tp2_price is not None:
        parts = [p.strip() for p in existing_notes.split("|") if p.strip() and not p.strip().startswith("tp2=")]
        parts.append(f"tp2={tp2_price:.0f}")
        existing_notes = " | ".join(parts)

    # notes tambahan: append
    if notes and notes.strip():
        existing_notes = f"{existing_notes} | {notes.strip()}".strip(" |")

    # Selalu update notes (karena tp1/tp2 disimpan di sana)
    sets.append("notes=?")
    vals.append(existing_notes)

    if not sets:
        conn.close()
        return {"success": False, "error": "Tidak ada field yang diubah"}

    vals.append(trade_id)
    conn.execute(f"UPDATE manual_trades SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()
    return {"success": True, "trade_id": trade_id}


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


def get_loss_attribution(trade_id: int = None) -> dict:
    """
    Post-mortem attribution untuk satu trade atau semua closed trades.

    Untuk satu trade (trade_id diberikan):
      - Breakdown per dimensi: regime, signal_score, risk_pct, mcf_score
      - Pattern match: apakah kondisi ini sama dengan loss sebelumnya?
      - Rule suggestion: aturan spesifik yang seharusnya mencegah loss ini

    Untuk semua trades (trade_id = None):
      - Agregat: dimensi mana yang paling sering muncul di loss
      - Win rate per bucket (regime, score range, risk range)
    """
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    all_closed = [dict(r) for r in conn.execute("""
        SELECT * FROM manual_trades
        WHERE outcome IN ('WIN','LOSS','BREAKEVEN')
        ORDER BY exit_date DESC
    """).fetchall()]

    if not all_closed:
        conn.close()
        return {"available": False, "reason": "Belum ada closed trades"}

    losses = [t for t in all_closed if t.get("outcome") == "LOSS"]
    wins   = [t for t in all_closed if t.get("outcome") == "WIN"]

    # ── Single trade post-mortem ──────────────────────────────────────────────
    if trade_id is not None:
        trade = conn.execute(
            "SELECT * FROM manual_trades WHERE id=?", (trade_id,)
        ).fetchone()
        conn.close()

        if not trade:
            return {"available": False, "reason": f"Trade #{trade_id} tidak ditemukan"}

        trade = dict(trade)
        outcome     = trade.get("outcome", "")
        sig_score   = trade.get("signal_score") or 0
        regime      = trade.get("regime_tag") or "UNKNOWN"
        risk_pct    = ((trade.get("entry_price",0) - trade.get("sl_price",0))
                       / max(trade.get("entry_price",0), 1) * 100) if trade.get("sl_price") else 0
        mcf_score   = trade.get("mcf_score") or 0
        sig_type    = trade.get("signal_type") or "UNKNOWN"
        pnl_r       = trade.get("pnl_r") or 0

        # Dimensi check — tiap dimensi: apakah ada warning flag?
        dims = []

        # 1. Regime
        _bear_regimes = {"BEAR_TREND", "WATCHLIST_ONLY", "BEAR_CONSOLIDATION", "BEAR_WEAK"}
        _risky_regimes = {"TRANSITION", "SIDEWAYS"}
        if regime in _bear_regimes:
            dims.append({
                "dim": "REGIME",
                "flag": "CRITICAL",
                "value": regime,
                "finding": f"Regime {regime} = bear/watchlist. Seharusnya tidak entry.",
                "rule": "RULE: Jangan entry saat regime BEAR/WATCHLIST_ONLY.",
            })
        elif regime in _risky_regimes:
            dims.append({
                "dim": "REGIME",
                "flag": "WARNING",
                "value": regime,
                "finding": f"Regime {regime} = transisi/sideways. Sizing seharusnya 50%.",
                "rule": "RULE: Sizing 50% saat regime TRANSITION/SIDEWAYS.",
            })
        else:
            dims.append({
                "dim": "REGIME",
                "flag": "OK",
                "value": regime,
                "finding": f"Regime {regime} = bullish. Bukan faktor loss.",
                "rule": "",
            })

        # 2. Signal score
        if sig_score < 3:
            dims.append({
                "dim": "SIGNAL SCORE",
                "flag": "CRITICAL",
                "value": f"{sig_score}/10",
                "finding": f"Score {sig_score} terlalu rendah. Setup belum matang.",
                "rule": "RULE: Jangan entry jika score < 4.",
            })
        elif sig_score < 5:
            dims.append({
                "dim": "SIGNAL SCORE",
                "flag": "WARNING",
                "value": f"{sig_score}/10",
                "finding": f"Score {sig_score} medium. Harusnya sizing lebih kecil.",
                "rule": "RULE: Sizing 50% jika score 4–5. Full size hanya score ≥ 6.",
            })
        else:
            dims.append({
                "dim": "SIGNAL SCORE",
                "flag": "OK",
                "value": f"{sig_score}/10",
                "finding": f"Score {sig_score} acceptable. Bukan faktor utama loss.",
                "rule": "",
            })

        # 3. Risk %
        if risk_pct > 25:
            dims.append({
                "dim": "RISK %",
                "flag": "CRITICAL",
                "value": f"{risk_pct:.1f}%",
                "finding": f"Risk {risk_pct:.1f}% — terlalu lebar. SL tidak rasional.",
                "rule": "RULE: Skip jika risk > 25%. Cari entry lebih dekat SL.",
            })
        elif risk_pct > 15:
            dims.append({
                "dim": "RISK %",
                "flag": "WARNING",
                "value": f"{risk_pct:.1f}%",
                "finding": f"Risk {risk_pct:.1f}% — di atas threshold. Sizing terlalu besar.",
                "rule": "RULE: Kurangi sizing 50% jika risk 15–25%.",
            })
        else:
            dims.append({
                "dim": "RISK %",
                "flag": "OK",
                "value": f"{risk_pct:.1f}%",
                "finding": f"Risk {risk_pct:.1f}% — dalam batas wajar.",
                "rule": "",
            })

        # 4. MCF
        if mcf_score > 0:
            if mcf_score < 4:
                dims.append({
                    "dim": "MCF SCORE",
                    "flag": "WARNING",
                    "value": f"{mcf_score}/10",
                    "finding": f"MCF {mcf_score} lemah. Momentum tidak mendukung entry.",
                    "rule": "RULE: Jangan entry jika MCF < 5.",
                })
            else:
                dims.append({
                    "dim": "MCF SCORE",
                    "flag": "OK",
                    "value": f"{mcf_score}/10",
                    "finding": f"MCF {mcf_score} — momentum mendukung saat entry.",
                    "rule": "",
                })

        # ── Pattern match dari historical losses ──────────────────────────────
        pattern_hits = []
        similar_losses = []

        for lt in losses:
            if lt.get("id") == trade_id:
                continue
            lt_regime = lt.get("regime_tag") or "UNKNOWN"
            lt_score  = lt.get("signal_score") or 0
            lt_risk   = ((lt.get("entry_price",0) - lt.get("sl_price",0))
                         / max(lt.get("entry_price",0),1) * 100) if lt.get("sl_price") else 0
            matches = 0
            if lt_regime == regime:               matches += 1
            if abs(lt_score - sig_score) <= 1:    matches += 1
            if abs(lt_risk - risk_pct) <= 5:      matches += 1
            if matches >= 2:
                similar_losses.append(lt)

        if similar_losses:
            pattern_hits.append(
                f"{len(similar_losses)} dari {len(losses)} loss sebelumnya punya kondisi serupa "
                f"(regime={regime}, score≈{sig_score}, risk≈{risk_pct:.0f}%)"
            )

        # ── Derive top causes ─────────────────────────────────────────────────
        critical_dims = [d for d in dims if d["flag"] == "CRITICAL"]
        warning_dims  = [d for d in dims if d["flag"] == "WARNING"]

        if critical_dims:
            primary_cause = critical_dims[0]["finding"]
            top_rule      = critical_dims[0]["rule"]
        elif warning_dims:
            primary_cause = warning_dims[0]["finding"]
            top_rule      = warning_dims[0]["rule"]
        else:
            primary_cause = "Kondisi entry dalam batas normal — loss karena market noise atau timing."
            top_rule      = "Tidak ada rule yang dilanggar. Review price action saat exit."

        return {
            "available":       True,
            "trade_id":        trade_id,
            "ticker":          trade.get("ticker", "?"),
            "outcome":         outcome,
            "pnl_r":           pnl_r,
            "dims":            dims,
            "primary_cause":   primary_cause,
            "top_rule":        top_rule,
            "pattern_hits":    pattern_hits,
            "similar_losses":  len(similar_losses),
            "total_losses":    len(losses),
            "critical_count":  len(critical_dims),
            "warning_count":   len(warning_dims),
        }

    # ── Aggregate attribution (semua trades) ─────────────────────────────────
    conn.close()

    def _wr_bucket(trades_list, key_fn, label_fn):
        """Win rate per bucket."""
        from collections import defaultdict
        buckets = defaultdict(lambda: {"win": 0, "loss": 0, "total": 0})
        for t in trades_list:
            k = key_fn(t)
            buckets[k]["total"] += 1
            if t.get("outcome") == "WIN":   buckets[k]["win"] += 1
            elif t.get("outcome") == "LOSS": buckets[k]["loss"] += 1
        result = []
        for k, v in sorted(buckets.items()):
            wr = v["win"] / v["total"] * 100 if v["total"] > 0 else 0
            result.append({
                "label":  label_fn(k),
                "total":  v["total"],
                "win":    v["win"],
                "loss":   v["loss"],
                "win_rate": round(wr, 1),
            })
        return result

    regime_wr  = _wr_bucket(all_closed,
        lambda t: t.get("regime_tag") or "UNKNOWN",
        lambda k: k)

    score_wr   = _wr_bucket(all_closed,
        lambda t: "0-3" if (t.get("signal_score") or 0) <= 3
                  else "4-5" if (t.get("signal_score") or 0) <= 5
                  else "6-7" if (t.get("signal_score") or 0) <= 7
                  else "8-10",
        lambda k: f"Score {k}")

    risk_wr    = _wr_bucket(all_closed,
        lambda t: "<10%" if ((t.get("entry_price",0)-t.get("sl_price",0))/max(t.get("entry_price",1),1)*100) < 10
                  else "10-15%" if ((t.get("entry_price",0)-t.get("sl_price",0))/max(t.get("entry_price",1),1)*100) < 15
                  else "15-25%" if ((t.get("entry_price",0)-t.get("sl_price",0))/max(t.get("entry_price",1),1)*100) < 25
                  else ">25%",
        lambda k: f"Risk {k}")

    # Most common loss conditions
    loss_regime_counts = {}
    loss_score_counts  = {}
    for lt in losses:
        r = lt.get("regime_tag") or "UNKNOWN"
        s = lt.get("signal_score") or 0
        loss_regime_counts[r] = loss_regime_counts.get(r, 0) + 1
        bucket = "0-3" if s<=3 else "4-5" if s<=5 else "6-7" if s<=7 else "8-10"
        loss_score_counts[bucket] = loss_score_counts.get(bucket, 0) + 1

    top_loss_regime = max(loss_regime_counts, key=loss_regime_counts.get) if loss_regime_counts else "—"
    top_loss_score  = max(loss_score_counts,  key=loss_score_counts.get)  if loss_score_counts  else "—"

    return {
        "available":        True,
        "trade_id":         None,
        "total_closed":     len(all_closed),
        "total_losses":     len(losses),
        "total_wins":       len(wins),
        "regime_wr":        regime_wr,
        "score_wr":         score_wr,
        "risk_wr":          risk_wr,
        "top_loss_regime":  top_loss_regime,
        "top_loss_score":   top_loss_score,
        "loss_regime_dist": loss_regime_counts,
        "loss_score_dist":  loss_score_counts,
    }

