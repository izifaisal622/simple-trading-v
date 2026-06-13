"""
Simple Trading V6 — Paper Trade Journal Agent V2 (Institutional)
=================================================================
UPGRADE V2:
  • Removed unused json, datetime.datetime, dataclass, asdict, field imports
  • All bare-except → logged handlers
  • Type hints cleaned
  • No logic/schema changes
"""

import sqlite3
import logging
from datetime import date, timedelta
from pathlib import Path

logger   = logging.getLogger(__name__)
LOGS_DIR = Path(__file__).parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)
DB_PATH  = LOGS_DIR / "paper_journal.db"


def _init_db() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
    CREATE TABLE IF NOT EXISTS paper_trades (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker      TEXT NOT NULL,
        entry_date  TEXT NOT NULL,
        entry_price REAL NOT NULL,
        sl_price    REAL NOT NULL,
        tp1_price   REAL,
        tp2_price   REAL,
        risk_pct    REAL,
        rr_ratio    REAL,
        ema_score   INTEGER,
        ema_signal  TEXT,
        whale_quality TEXT,
        conviction  INTEGER,
        regime      TEXT,
        grade       TEXT,
        source      TEXT DEFAULT 'manual',
        notes       TEXT DEFAULT '',
        exit_date   TEXT,
        exit_price  REAL,
        outcome     TEXT,
        pnl_r       REAL,
        pnl_pct     REAL,
        days_held   INTEGER,
        exit_reason TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    )""")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS journal_stats_cache (
        id          INTEGER PRIMARY KEY,
        updated_at  TEXT,
        stats_json  TEXT
    )""")
    conn.commit()
    conn.close()


_init_db()


def add_paper_trade(
    ticker: str, entry_price: float, sl_price: float,
    tp1_price: float = 0, tp2_price: float = 0,
    risk_pct: float = 0, rr_ratio: float = 0,
    ema_score: int = 0, ema_signal: str = "",
    whale_quality: str = "", conviction: int = 0,
    regime: str = "", grade: str = "", notes: str = "",
    source: str = "manual",
) -> int:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.execute("""
        INSERT INTO paper_trades
            (ticker, entry_date, entry_price, sl_price, tp1_price, tp2_price,
             risk_pct, rr_ratio, ema_score, ema_signal, whale_quality, conviction,
             regime, grade, source, notes, outcome)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'OPEN')
        """, (
            ticker.upper().replace(".JK", ""),
            str(date.today()),
            entry_price, sl_price, tp1_price, tp2_price,
            risk_pct, rr_ratio, ema_score, ema_signal,
            whale_quality, conviction, regime, grade, source, notes,
        ))
        trade_id = cur.lastrowid
        conn.commit()
        logger.info(f"[Journal] Paper trade added: {ticker} #{trade_id}")
        return trade_id or 0
    except Exception as exc:
        logger.error(f"[Journal] add_paper_trade: {exc}")
        return 0
    finally:
        conn.close()


def close_paper_trade(
    trade_id: int, exit_price: float, exit_reason: str = "MANUAL", notes: str = ""
) -> dict:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        row = conn.execute(
            "SELECT entry_price, sl_price, tp1_price, entry_date FROM paper_trades WHERE id=?",
            (trade_id,)
        ).fetchone()
        if not row:
            return {"error": f"Trade #{trade_id} not found"}

        entry_price, sl_price, _, entry_date = row
        exit_date = str(date.today())
        pnl_pct   = (exit_price - entry_price) / entry_price * 100
        risk_amt  = entry_price - sl_price
        pnl_r     = ((exit_price - entry_price) / risk_amt) if risk_amt > 0 else 0.0

        try:
            days_held = (date.today() - date.fromisoformat(entry_date)).days
        except Exception:
            days_held = 0

        outcome = "WIN" if pnl_r >= 0.5 else "LOSS" if pnl_r < -0.5 else "SCRATCH"
        if exit_reason == "SL_HIT":
            outcome = "LOSS"
        elif exit_reason in ("TP1_HIT", "TP2_HIT"):
            outcome = "WIN"

        conn.execute("""
        UPDATE paper_trades SET
            exit_date=?, exit_price=?, outcome=?, pnl_r=?, pnl_pct=?,
            days_held=?, exit_reason=?, notes=notes||?
        WHERE id=?
        """, (
            exit_date, exit_price, outcome, round(pnl_r, 2), round(pnl_pct, 2),
            days_held, exit_reason,
            (" | " + notes) if notes else "",
            trade_id,
        ))
        conn.commit()
        result = {
            "trade_id": trade_id, "outcome": outcome,
            "pnl_r": round(pnl_r, 2), "pnl_pct": round(pnl_pct, 2),
            "days_held": days_held, "exit_reason": exit_reason,
        }
        logger.info(f"[Journal] Trade #{trade_id} closed: {outcome} {pnl_r:+.2f}R")
        return result
    except Exception as exc:
        logger.error(f"[Journal] close_paper_trade #{trade_id}: {exc}")
        return {"error": str(exc)}
    finally:
        conn.close()


def get_open_trades() -> list:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        rows = conn.execute("""
        SELECT id, ticker, entry_date, entry_price, sl_price, tp1_price, tp2_price,
               risk_pct, rr_ratio, ema_score, grade, regime, conviction, notes
        FROM paper_trades WHERE outcome='OPEN' ORDER BY entry_date DESC
        """).fetchall()
        cols = ["id","ticker","entry_date","entry_price","sl_price","tp1_price","tp2_price",
                "risk_pct","rr_ratio","ema_score","grade","regime","conviction","notes"]
        return [dict(zip(cols, r)) for r in rows]
    except Exception as exc:
        logger.error(f"[Journal] get_open_trades: {exc}")
        return []
    finally:
        conn.close()


def get_closed_trades(limit: int = 100) -> list:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        rows = conn.execute("""
        SELECT id, ticker, entry_date, exit_date, entry_price, exit_price,
               outcome, pnl_r, pnl_pct, days_held, ema_score, grade, regime,
               whale_quality, conviction, exit_reason
        FROM paper_trades WHERE outcome != 'OPEN'
        ORDER BY exit_date DESC LIMIT ?
        """, (limit,)).fetchall()
        cols = ["id","ticker","entry_date","exit_date","entry_price","exit_price",
                "outcome","pnl_r","pnl_pct","days_held","ema_score","grade","regime",
                "whale_quality","conviction","exit_reason"]
        return [dict(zip(cols, r)) for r in rows]
    except Exception as exc:
        logger.error(f"[Journal] get_closed_trades: {exc}")
        return []
    finally:
        conn.close()


def compute_performance() -> dict:
    closed = get_closed_trades(limit=500)
    if not closed:
        return {"total": 0, "message": "No closed paper trades yet"}

    wins   = [t for t in closed if t["outcome"] == "WIN"]
    losses = [t for t in closed if t["outcome"] == "LOSS"]
    total  = len(closed)

    win_rate   = len(wins) / total
    avg_win_r  = sum(t["pnl_r"] for t in wins)   / len(wins)   if wins   else 0.0
    avg_loss_r = sum(t["pnl_r"] for t in losses)  / len(losses) if losses else 0.0
    expectancy = win_rate * avg_win_r + (1 - win_rate) * avg_loss_r
    total_r    = sum(t["pnl_r"] for t in closed)

    grade_stats: dict = {}
    for g in ("A", "A+", "B", "C", "D", "F"):
        gt = [t for t in closed if t.get("grade", "?") == g]
        if gt:
            gw = [t for t in gt if t["outcome"] == "WIN"]
            grade_stats[g] = {
                "total":    len(gt),
                "win_rate": round(len(gw) / len(gt) * 100, 1),
                "avg_r":    round(sum(t["pnl_r"] for t in gt) / len(gt), 2),
            }

    regime_stats: dict = {}
    for r in closed:
        reg = r.get("regime", "UNKNOWN")
        if reg not in regime_stats:
            regime_stats[reg] = {"total": 0, "wins": 0, "total_r": 0.0}
        regime_stats[reg]["total"]   += 1
        regime_stats[reg]["total_r"] += r["pnl_r"]
        if r["outcome"] == "WIN":
            regime_stats[reg]["wins"] += 1

    return {
        "total":        total,
        "wins":         len(wins),
        "losses":       len(losses),
        "win_rate":     round(win_rate * 100, 1),
        "avg_win_r":    round(avg_win_r, 2),
        "avg_loss_r":   round(avg_loss_r, 2),
        "expectancy":   round(expectancy, 3),
        "total_r":      round(total_r, 2),
        "grade_stats":  grade_stats,
        "regime_stats": regime_stats,
        "verdict": (
            "POSITIVE EV ✓" if expectancy > 0 and total >= 10 else
            "NEGATIVE EV ✗" if expectancy < 0 and total >= 10 else
            "INSUFFICIENT DATA"
        ),
    }


def get_pending_exit_prompts(days_threshold: int = 14) -> list:
    conn   = sqlite3.connect(str(DB_PATH))
    cutoff = (date.today() - timedelta(days=days_threshold)).isoformat()
    try:
        rows = conn.execute("""
        SELECT id, ticker, entry_date, entry_price, sl_price, tp1_price, grade
        FROM paper_trades
        WHERE outcome='OPEN' AND entry_date <= ?
        ORDER BY entry_date
        """, (cutoff,)).fetchall()
        cols   = ["id","ticker","entry_date","entry_price","sl_price","tp1_price","grade"]
        result = []
        for r in rows:
            row = dict(zip(cols, r))
            try:
                row["days_open"] = (date.today() - date.fromisoformat(r[2])).days
            except Exception:
                row["days_open"] = 0
            result.append(row)
        return result
    except Exception as exc:
        logger.error(f"[Journal] get_pending_exit_prompts: {exc}")
        return []
    finally:
        conn.close()
