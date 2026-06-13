"""
Simple Trading V6 — Learning Agent V2 (Institutional)
=======================================================
UPGRADE V2:
  • Removed unused json import
  • Fixed f-strings missing placeholders (lines 81, 118)
  • All bare-except → logged handlers
  • Type hints cleaned
  • No logic changes
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path

logger       = logging.getLogger(__name__)
LOGS_DIR     = Path(__file__).parent.parent / "logs"
DB_PATH      = LOGS_DIR / "trade_log.db"
LESSONS_FILE = LOGS_DIR / "lessons.md"
LOGS_DIR.mkdir(exist_ok=True)


def run_learning_cycle(auto_apply: bool = False) -> str:
    if not DB_PATH.exists():
        return "Learning: no trade database found yet — start logging trades"

    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row

        trades = conn.execute("""
            SELECT ticker, entry_date, exit_date, outcome, pnl_r, pnl_pct,
                   bars_held, strategy, notes
            FROM manual_trades
            WHERE outcome IS NOT NULL AND outcome != 'OPEN'
            ORDER BY entry_date DESC
        """).fetchall()

        try:
            outcomes = conn.execute("""
                SELECT o.ticker, o.outcome, o.pnl_r,
                       NULL as bars_held, NULL as signal, NULL as score
                FROM outcomes o
                WHERE o.outcome IS NOT NULL
                ORDER BY rowid DESC
            """).fetchall()
        except Exception as exc:
            logger.debug(f"[Learning] outcomes query: {exc}")
            outcomes = []

        conn.close()

        all_trades = list(trades) + list(outcomes)
        total      = len(all_trades)

        if total == 0:
            return "Learning: 0 closed trades — log outcomes to start learning"

        wins   = [t for t in all_trades if t["outcome"] and "WIN"  in t["outcome"]]
        losses = [t for t in all_trades if t["outcome"] and "LOSS" in t["outcome"]]
        pnl_rs = [t["pnl_r"] for t in all_trades if t["pnl_r"] is not None]

        win_rate   = len(wins) / total if total > 0 else 0
        avg_r      = sum(pnl_rs) / len(pnl_rs) if pnl_rs else 0
        expectancy = sum(pnl_rs) / total       if pnl_rs else 0

        bars_w = [t["bars_held"] for t in wins   if t["bars_held"]]
        bars_l = [t["bars_held"] for t in losses if t["bars_held"]]
        avg_bars_win  = sum(bars_w) / len(bars_w) if bars_w else 0
        avg_bars_loss = sum(bars_l) / len(bars_l) if bars_l else 0

        lessons = [
            "# 📚 Trading Lessons",
            f"*Generated: {datetime.now().strftime('%d %b %Y %H:%M')}*",
            f"*Based on {total} closed trades*",
            "",
            "## Performance Summary",
            f"- **Win rate**: {win_rate*100:.0f}% ({len(wins)}W / {len(losses)}L)",
            f"- **Avg R**: {avg_r:.2f}R | **Expectancy**: {expectancy:.2f}R per trade",
            f"- **Avg hold (wins)**: {avg_bars_win:.0f} bars | **Avg hold (losses)**: {avg_bars_loss:.0f} bars",
            "",
            "## Key Lessons",
        ]

        if win_rate >= 0.6:
            lessons.append("✅ Win rate is strong. Keep doing what you're doing. Don't overtrade.")
        elif win_rate >= 0.45:
            lessons.append("🟡 Win rate is developing. Focus on only taking score 5-8/8 setups.")
        elif total >= 5:
            lessons.append("🔴 Win rate needs improvement. Review entry criteria. Paper trade until 10+ trades.")

        if avg_bars_loss > avg_bars_win and total >= 5:
            lessons.append("⚠️ You hold losers longer than winners. Cut losses at SL — no exceptions.")
        elif avg_bars_win > 0:
            lessons.append("✅ Good trade management — cutting losses faster than winners.")

        if expectancy > 0.5:
            lessons.append(f"✅ Positive expectancy ({expectancy:.2f}R). Strategy is profitable.")
        elif expectancy > 0:
            lessons.append(f"🟡 Marginally positive expectancy ({expectancy:.2f}R). Improve entry timing.")
        elif total >= 5:
            lessons.append(f"🔴 Negative expectancy ({expectancy:.2f}R). Review and paper trade.")

        if total < 10:
            lessons.append(f"📊 Only {total} trades — need 10+ for reliable patterns. Keep logging.")

        lessons += ["", "---", "*Next review: after next 5 trades*"]

        LESSONS_FILE.write_text("\n".join(lessons), encoding="utf-8")

        return (f"Learning: {total} trades | WR {win_rate*100:.0f}% | "
                f"Expectancy {expectancy:.2f}R | Lessons → {LESSONS_FILE.name}")

    except Exception as exc:
        logger.error(f"[Learning] Error: {exc}")
        return f"Learning: error — {exc}"
