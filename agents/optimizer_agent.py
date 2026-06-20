"""
Simple Trading V9 — Optimizer Agent V2 (Institutional)
=======================================================
UPGRADE V2:
  • CRITICAL FIX: self.getattr(cfg,...) → getattr(self.cfg,...) — was NameError
  • Removed unused json, datetime.datetime, Optional imports
  • log_signal: typed, all bare-except → logged handlers
  • log_outcome: typed, all bare-except → logged handlers
  • optimize: f-string placeholder fixed
  • No logic/schema changes
"""

import sqlite3
import logging
from pathlib import Path

from config.strategy_config import StrategyConfig

logger   = logging.getLogger(__name__)
LOGS_DIR = Path(__file__).parent.parent / "logs"
DB_PATH  = LOGS_DIR / "trade_log.db"
LOGS_DIR.mkdir(exist_ok=True)


def init_db() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS signals (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker       TEXT,
            signal       TEXT,
            score        INTEGER,
            entry_date   TEXT,
            entry_price  REAL,
            sl_price     REAL,
            tp1_price    REAL,
            risk_pct     REAL,
            rr_ratio     REAL,
            timeframe    TEXT,
            notes        TEXT
        );
        CREATE TABLE IF NOT EXISTS outcomes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id    INTEGER,
            outcome      TEXT,
            exit_price   REAL,
            exit_date    TEXT,
            bars_held    INTEGER,
            pnl_r        REAL,
            pnl_pct      REAL,
            notes        TEXT,
            FOREIGN KEY (signal_id) REFERENCES signals(id)
        );
        CREATE TABLE IF NOT EXISTS manual_trades (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker       TEXT,
            entry_date   TEXT,
            entry_price  REAL,
            exit_date    TEXT,
            exit_price   REAL,
            outcome      TEXT,
            pnl_r        REAL,
            pnl_pct      REAL,
            bars_held    INTEGER,
            strategy     TEXT DEFAULT 'EMA_XBO',
            notes        TEXT
        );
        CREATE TABLE IF NOT EXISTS optimizations (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date     TEXT,
            params       TEXT,
            win_rate     REAL,
            avg_r        REAL,
            total_trades INTEGER
        );
    """)
    conn.commit()
    conn.close()


class OptimizerAgent:

    def __init__(self, config: StrategyConfig) -> None:
        self.cfg = config
        init_db()

    def log_signal(self, result) -> int:
        """Log a SetupResult to signals table. Returns signal ID (-1 on error)."""
        try:
            conn = sqlite3.connect(str(DB_PATH))
            cur  = conn.execute("""
                INSERT INTO signals
                (ticker, signal, score, entry_date, entry_price, sl_price,
                 tp1_price, risk_pct, rr_ratio, timeframe)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                result.ticker, result.signal, result.score,
                result.date, result.close, result.sl_price,
                result.tp1_price, result.risk_pct, result.rr_ratio,
                getattr(self.cfg, "timeframe", "1wk"),   # FIX: was self.getattr(cfg,...)
            ))
            conn.commit()
            signal_id = cur.lastrowid
            conn.close()
            return signal_id or -1
        except Exception as exc:
            logger.error(f"[Optimizer] log_signal: {exc}")
            return -1

    def log_outcome(
        self, signal_id: int, outcome: str, exit_price: float,
        exit_date: str, bars_held: int, notes: str = ""
    ) -> bool:
        try:
            conn = sqlite3.connect(str(DB_PATH))
            row  = conn.execute(
                "SELECT entry_price, sl_price, tp1_price FROM signals WHERE id=?",
                (signal_id,)
            ).fetchone()

            pnl_r = 0.0; pnl_pct = 0.0
            if row:
                entry, sl, _ = row
                risk    = entry - sl if entry > sl else 1.0
                pnl_pct = (exit_price - entry) / entry * 100
                pnl_r   = (exit_price - entry) / risk if risk != 0 else 0.0

            conn.execute("""
                INSERT INTO outcomes
                (signal_id, outcome, exit_price, exit_date, bars_held, pnl_r, pnl_pct, notes)
                VALUES (?,?,?,?,?,?,?,?)
            """, (signal_id, outcome, exit_price, exit_date, bars_held,
                  round(pnl_r, 2), round(pnl_pct, 2), notes))
            conn.commit()
            conn.close()
            return True
        except Exception as exc:
            logger.error(f"[Optimizer] log_outcome: {exc}")
            return False

    def get_stats(self) -> dict:
        try:
            conn = sqlite3.connect(str(DB_PATH))
            rows = conn.execute("""
                SELECT o.outcome, o.pnl_r, o.pnl_pct, o.bars_held, s.signal
                FROM outcomes o JOIN signals s ON o.signal_id = s.id
                WHERE o.outcome != 'OPEN'
            """).fetchall()
            conn.close()

            if not rows:
                return {"total": 0}

            wins   = [r for r in rows if r[0] and "WIN"  in r[0]]
            losses = [r for r in rows if r[0] and "LOSS" in r[0]]
            pnl_rs = [r[1] for r in rows if r[1] is not None]

            return {
                "total":      len(rows),
                "wins":       len(wins),
                "losses":     len(losses),
                "win_rate":   round(len(wins) / len(rows), 3) if rows else 0,
                "avg_r":      round(sum(pnl_rs) / len(pnl_rs), 2) if pnl_rs else 0,
                "total_r":    round(sum(pnl_rs), 2) if pnl_rs else 0,
                "expectancy": round(sum(pnl_rs) / len(rows), 2) if pnl_rs else 0,
            }
        except Exception as exc:
            logger.error(f"[Optimizer] get_stats: {exc}")
            return {"total": 0}

    def print_stats(self) -> None:
        stats = self.get_stats()
        print(f"\n{'='*40}")
        print("  Performance Stats")
        print(f"{'='*40}")
        if stats.get("total", 0) == 0:
            print("  No closed trades logged yet.")
            print("  Use log_outcome() after each trade closes.")
        else:
            print(f"  Total trades : {stats['total']}")
            print(f"  Win rate     : {stats['win_rate']*100:.0f}%")
            print(f"  Avg R        : {stats['avg_r']:.2f}R")
            print(f"  Total R      : {stats['total_r']:.1f}R")
            print(f"  Expectancy   : {stats['expectancy']:.2f}R per trade")
        print(f"{'='*40}\n")

    def optimize(self, data: dict) -> StrategyConfig:
        from core.technical_engine import EMABreakoutEngine

        best_cfg   = self.cfg
        best_score = -999.0

        box_range_grid = [8.0, 10.0, 12.0, 15.0, 18.0]
        vol_mult_grid  = [1.0, 1.2, 1.5, 2.0]

        for box_pct in box_range_grid:
            for vol_mult in vol_mult_grid:
                test_cfg = StrategyConfig.load()
                test_cfg.box_range_pct = box_pct
                test_cfg.vol_mult      = vol_mult

                engine  = EMABreakoutEngine(test_cfg)
                signals = 0
                scores  = []

                for ticker, df in data.items():
                    try:
                        r = engine.analyze(df, ticker)
                        if r and r.signal in ("STRONG_BREAKOUT", "BREAKOUT", "WATCHLIST"):
                            signals += 1
                            scores.append(r.score)
                    except Exception as exc:
                        logger.debug(f"[Optimizer] {ticker}: {exc}")
                        continue

                avg_q = sum(scores) / len(scores) if scores else 0.0
                combo = signals * avg_q

                if combo > best_score:
                    best_score = combo
                    best_cfg   = test_cfg
                    print(f"[Optimizer] New best: box={box_pct}% vol={vol_mult}× "
                          f"→ {signals} signals, avg score {avg_q:.1f}")

        best_cfg.save()
        print(f"[Optimizer] Best params saved → {best_cfg.box_range_pct}% box, "
              f"{best_cfg.vol_mult}× vol")
        return best_cfg
