"""
Simple Trading V8 — Learning Agent V3 (Statistical Inference)
=============================================================
UPGRADE V3 — Sesi A Rewrite:

V1/V2 masalah: hanya hitung WR keseluruhan + tulis 4-5 kalimat hardcoded.
Tidak ada learning — hanya statistics formatter.

V3 approach: baca kombinasi kondisi dari trade metadata →
identifikasi pattern mana yang prediktif → tulis rule konkret per kombinasi.

OUTPUT FORMAT (lessons.md):
  ✅ TRADE THIS:  [kondisi] = N trades, WR X%, avg +Y.YR
  ❌ NEVER AGAIN: [kondisi] = N trades, WR X%, avg -Y.YR
  ⚠ SYSTEMATIC LEAK: [dimensi] konsisten menghasilkan loss
  📋 DERIVED RULES: rule konkret yang bisa langsung dipakai

DATA SOURCES:
  - trade_log.db (manual_trades) — real trades dengan metadata
  - paper_journal.db (paper_trades) — paper trades dengan grade
  - get_loss_attribution() — per-trade attribution dari post-mortem
"""

import sqlite3
import logging
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Optional

logger       = logging.getLogger(__name__)
LOGS_DIR     = Path(__file__).parent.parent / "logs"
DB_PATH      = LOGS_DIR / "trade_log.db"
PAPER_DB     = LOGS_DIR / "paper_journal.db"
LESSONS_FILE = LOGS_DIR / "lessons.md"
LOGS_DIR.mkdir(exist_ok=True)

# Minimum trades per bucket untuk dianggap statistically meaningful
MIN_BUCKET_SIZE = 3
# Win rate threshold: di atas ini = good, di bawah ini = bad
WR_GOOD = 55.0
WR_BAD  = 35.0


def _derive_grade(signal_score: int) -> str:
    """Proxy grade dari signal_score — konsisten dengan Page 06 unified view."""
    s = signal_score or 0
    if s >= 9: return "A+"
    if s >= 7: return "A"
    if s >= 5: return "B"
    if s >= 3: return "C"
    if s >= 1: return "D"
    return "F"


def _load_real_trades() -> list:
    """Load closed real trades dari trade_log.db dengan semua metadata."""
    if not DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT ticker, outcome, pnl_r, pnl_pct, bars_held,
                   signal_type, signal_score, regime_tag, mcf_score,
                   entry_price, sl_price, strategy, notes
            FROM manual_trades
            WHERE outcome IN ('WIN','LOSS','BREAKEVEN')
            AND pnl_r IS NOT NULL
            ORDER BY exit_date DESC
        """).fetchall()
        conn.close()
        trades = [dict(r) for r in rows]
        # Enrich: risk_pct, derived_grade
        for t in trades:
            ep = t.get("entry_price") or 0
            sl = t.get("sl_price") or 0
            t["risk_pct"] = ((ep - sl) / ep * 100) if ep > 0 and sl > 0 else 0
            t["derived_grade"] = _derive_grade(t.get("signal_score") or 0)
            t["_source"] = "REAL"
        return trades
    except Exception as e:
        logger.debug(f"[Learning] load real trades: {e}")
        return []


def _load_paper_trades() -> list:
    """Load closed paper trades dari paper_journal.db."""
    if not PAPER_DB.exists():
        return []
    try:
        conn = sqlite3.connect(str(PAPER_DB))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT ticker, outcome, pnl_r, pnl_pct, days_held as bars_held,
                   ema_score as signal_score, grade, regime, whale_quality,
                   conviction, risk_pct, ema_signal as signal_type
            FROM paper_trades
            WHERE outcome != 'OPEN' AND outcome IS NOT NULL
            AND pnl_r IS NOT NULL
            ORDER BY exit_date DESC
        """).fetchall()
        conn.close()
        trades = [dict(r) for r in rows]
        for t in trades:
            t["regime_tag"]     = t.pop("regime", "UNKNOWN")
            t["derived_grade"]  = t.get("grade") or _derive_grade(t.get("signal_score") or 0)
            t["_source"]        = "PAPER"
        return trades
    except Exception as e:
        logger.debug(f"[Learning] load paper trades: {e}")
        return []


def _bucket_stats(trades: list) -> Optional[dict]:
    """Hitung statistik dasar dari sekumpulan trades."""
    if len(trades) < MIN_BUCKET_SIZE:
        return None
    wins    = [t for t in trades if t.get("outcome") == "WIN"]
    losses  = [t for t in trades if t.get("outcome") == "LOSS"]
    pnl_rs  = [t["pnl_r"] for t in trades if t.get("pnl_r") is not None]
    wr      = len(wins) / len(trades) * 100
    avg_r   = sum(pnl_rs) / len(pnl_rs) if pnl_rs else 0
    return {
        "n":        len(trades),
        "wins":     len(wins),
        "losses":   len(losses),
        "wr":       round(wr, 1),
        "avg_r":    round(avg_r, 2),
        "is_good":  wr >= WR_GOOD,
        "is_bad":   wr <= WR_BAD,
    }


def _analyze_single_dimension(trades: list) -> dict:
    """
    Analisis WR per satu dimensi:
    regime_tag, derived_grade, signal_score range, risk_pct range, mcf_score range.
    """
    results = {}

    # ── Regime ───────────────────────────────────────────────────────────────
    regimes = {}
    for t in trades:
        r = t.get("regime_tag") or "UNKNOWN"
        regimes.setdefault(r, []).append(t)
    regime_stats = {}
    for r, ts in regimes.items():
        s = _bucket_stats(ts)
        if s:
            regime_stats[r] = s
    results["regime"] = regime_stats

    # ── Grade bucket ─────────────────────────────────────────────────────────
    grades = {}
    for t in trades:
        g = t.get("derived_grade", "?")
        grades.setdefault(g, []).append(t)
    grade_stats = {}
    for g in ["A+", "A", "B", "C", "D", "F"]:
        if g in grades:
            s = _bucket_stats(grades[g])
            if s:
                grade_stats[g] = s
    results["grade"] = grade_stats

    # ── Risk % bucket ─────────────────────────────────────────────────────────
    risk_buckets = {"<10%": [], "10-15%": [], "15-25%": [], ">25%": []}
    for t in trades:
        rp = t.get("risk_pct") or 0
        if rp < 10:   risk_buckets["<10%"].append(t)
        elif rp < 15: risk_buckets["10-15%"].append(t)
        elif rp < 25: risk_buckets["15-25%"].append(t)
        else:         risk_buckets[">25%"].append(t)
    risk_stats = {}
    for k, ts in risk_buckets.items():
        s = _bucket_stats(ts)
        if s:
            risk_stats[k] = s
    results["risk"] = risk_stats

    # ── Holding period ────────────────────────────────────────────────────────
    wins   = [t for t in trades if t.get("outcome") == "WIN"]
    losses = [t for t in trades if t.get("outcome") == "LOSS"]
    bars_w = [t.get("bars_held") or 0 for t in wins   if t.get("bars_held")]
    bars_l = [t.get("bars_held") or 0 for t in losses if t.get("bars_held")]
    results["hold"] = {
        "avg_bars_win":  round(sum(bars_w)/len(bars_w), 1) if bars_w else None,
        "avg_bars_loss": round(sum(bars_l)/len(bars_l), 1) if bars_l else None,
        "holding_leak":  (sum(bars_l)/len(bars_l) > sum(bars_w)/len(bars_w) * 1.3
                          if bars_w and bars_l else False),
    }

    return results


def _analyze_combinations(trades: list) -> list:
    """
    Temukan kombinasi 2 dimensi yang paling prediktif.
    Hanya laporkan kombinasi dengan n >= MIN_BUCKET_SIZE.

    Returns list of dicts: {conditions, stats, verdict}
    """
    findings = []

    def _regime_bucket(t):
        r = t.get("regime_tag") or "UNKNOWN"
        bear = {"BEAR_TREND", "WATCHLIST_ONLY", "BEAR_CONSOLIDATION", "BEAR_WEAK"}
        if r in bear:    return "REGIME:BEAR"
        if r in {"TRANSITION", "SIDEWAYS"}: return "REGIME:TRANSITION"
        return "REGIME:BULL"

    def _grade_bucket(t):
        g = t.get("derived_grade", "?")
        if g in ("A+", "A"): return "GRADE:A"
        if g == "B":          return "GRADE:B"
        return "GRADE:C/D/F"

    def _risk_bucket(t):
        rp = t.get("risk_pct") or 0
        if rp <= 15: return "RISK:OK(≤15%)"
        if rp <= 25: return "RISK:HIGH(15-25%)"
        return "RISK:EXTREME(>25%)"

    def _score_bucket(t):
        s = t.get("signal_score") or 0
        if s >= 7: return "SCORE:HIGH(≥7)"
        if s >= 5: return "SCORE:MED(5-6)"
        if s >= 3: return "SCORE:LOW(3-4)"
        return "SCORE:VERY_LOW(<3)"

    bucket_fns = [_regime_bucket, _grade_bucket, _risk_bucket, _score_bucket]

    # Label setiap trade dengan semua bucket
    for t in trades:
        t["_buckets"] = {fn(t) for fn in bucket_fns}

    # Cari semua kombinasi 2 bucket yang muncul bersama
    combo_groups: dict = {}
    for t in trades:
        buckets = list(t["_buckets"])
        for b1, b2 in combinations(sorted(buckets), 2):
            key = (b1, b2)
            combo_groups.setdefault(key, []).append(t)

    # Filter dan rank
    for (b1, b2), ts in combo_groups.items():
        s = _bucket_stats(ts)
        if not s:
            continue
        verdict = ("TRADE_THIS" if s["is_good"]
                   else "NEVER_AGAIN" if s["is_bad"]
                   else "NEUTRAL")
        findings.append({
            "conditions": f"{b1} + {b2}",
            "stats":      s,
            "verdict":    verdict,
        })

    # Sort: bad findings first (more actionable), then good
    findings.sort(key=lambda x: (
        0 if x["verdict"] == "NEVER_AGAIN" else
        1 if x["verdict"] == "TRADE_THIS"  else 2,
        -x["stats"]["n"]
    ))

    return findings[:12]  # Top 12 kombinasi


def _find_systematic_leaks(trades: list, single_dim: dict) -> list:
    """
    Identifikasi pola leak yang konsisten:
    - Dimensi tunggal yang selalu buruk
    - Leak yang berulang di multiple kombinasi
    """
    leaks = []

    # Regime leak
    for regime, s in single_dim.get("regime", {}).items():
        if s["is_bad"] and s["n"] >= MIN_BUCKET_SIZE:
            leaks.append({
                "type":    "REGIME_LEAK",
                "label":   f"Regime {regime}",
                "detail":  f"{s['n']} trades, WR {s['wr']:.0f}%, avg {s['avg_r']:+.2f}R",
                "rule":    f"RULE: Jangan entry saat regime = {regime}",
                "severity":"CRITICAL" if s["wr"] < 25 else "WARNING",
            })

    # Risk leak
    for bucket, s in single_dim.get("risk", {}).items():
        if s["is_bad"] and ">25%" in bucket:
            leaks.append({
                "type":    "RISK_LEAK",
                "label":   f"Risk {bucket}",
                "detail":  f"{s['n']} trades, WR {s['wr']:.0f}%, avg {s['avg_r']:+.2f}R",
                "rule":    "RULE: Skip semua trade dengan risk > 25%. SL terlalu jauh.",
                "severity":"CRITICAL",
            })
        elif s["is_bad"] and "15-25%" in bucket:
            leaks.append({
                "type":    "RISK_LEAK",
                "label":   f"Risk {bucket}",
                "detail":  f"{s['n']} trades, WR {s['wr']:.0f}%, avg {s['avg_r']:+.2f}R",
                "rule":    "RULE: Sizing 50% jika risk 15-25%.",
                "severity":"WARNING",
            })

    # Grade leak
    for g, s in single_dim.get("grade", {}).items():
        if s["is_bad"] and g in ("C", "D", "F"):
            leaks.append({
                "type":    "GRADE_LEAK",
                "label":   f"Grade {g} trades",
                "detail":  f"{s['n']} trades, WR {s['wr']:.0f}%, avg {s['avg_r']:+.2f}R",
                "rule":    f"RULE: Stop taking Grade {g} setups.",
                "severity":"WARNING",
            })

    # Holding leak
    hold = single_dim.get("hold", {})
    if hold.get("holding_leak"):
        aw = hold.get("avg_bars_win") or 0
        al = hold.get("avg_bars_loss") or 0
        leaks.append({
            "type":    "HOLDING_LEAK",
            "label":   "Holding losers longer than winners",
            "detail":  f"Avg win held {aw:.0f} bars vs avg loss held {al:.0f} bars",
            "rule":    "RULE: Cut losses at SL — no exception. Don't hold hoping for recovery.",
            "severity":"WARNING",
        })

    return leaks


def _derive_rules(combos: list, leaks: list, single_dim: dict) -> list:
    """
    Derive concrete, actionable rules dari semua temuan.
    Format: bisa langsung dipakai sebagai pre-flight checklist.
    """
    rules = []

    # Rules dari kombinasi GOOD
    for c in combos:
        if c["verdict"] == "TRADE_THIS" and c["stats"]["wr"] >= 60:
            rules.append({
                "type":  "GREEN",
                "rule":  f"FOKUS: {c['conditions']} → WR {c['stats']['wr']:.0f}% ({c['stats']['n']} trades)",
                "action":"Prioritaskan setup dengan kondisi ini. Full size jika regime juga bullish.",
            })
            if len([r for r in rules if r["type"] == "GREEN"]) >= 3:
                break  # Max 3 green rules

    # Rules dari kombinasi BAD
    for c in combos:
        if c["verdict"] == "NEVER_AGAIN" and c["stats"]["wr"] <= 30:
            rules.append({
                "type":  "RED",
                "rule":  f"HINDARI: {c['conditions']} → WR {c['stats']['wr']:.0f}% ({c['stats']['n']} trades)",
                "action":"Skip semua setup dengan kombinasi ini. Masukkan ke pre-flight gate.",
            })
            if len([r for r in rules if r["type"] == "RED"]) >= 3:
                break

    # Rules dari leaks
    for leak in leaks:
        if leak["severity"] == "CRITICAL":
            rules.append({
                "type":  "RED",
                "rule":  leak["rule"],
                "action":f"Data: {leak['detail']}",
            })

    # Best regime
    best_regime = None
    best_wr     = 0
    for reg, s in single_dim.get("regime", {}).items():
        if s["wr"] > best_wr and s["n"] >= MIN_BUCKET_SIZE:
            best_wr    = s["wr"]
            best_regime = reg
    if best_regime and best_wr >= WR_GOOD:
        rules.append({
            "type":  "GREEN",
            "rule":  f"OPTIMAL REGIME: {best_regime} → WR {best_wr:.0f}%",
            "action":"Aggresif di regime ini. Loosening pre-flight threshold acceptable.",
        })

    return rules


def run_learning_cycle(auto_apply: bool = False) -> str:
    """
    V3 Learning cycle — statistical inference dari trade history.

    1. Load semua closed trades (real + paper)
    2. Analisis single dimension (regime, grade, risk, holding)
    3. Temukan kombinasi 2-dimensi yang prediktif
    4. Identifikasi systematic leaks
    5. Derive concrete rules
    6. Tulis ke lessons.md dalam format actionable
    """
    real_trades  = _load_real_trades()
    paper_trades = _load_paper_trades()
    all_trades   = real_trades + paper_trades
    total        = len(all_trades)

    if total == 0:
        msg = "Learning V3: 0 closed trades — log dan close trade dulu untuk mulai belajar"
        LESSONS_FILE.write_text(
            f"# 📚 Trading Lessons V3\n\n"
            f"*Generated: {datetime.now().strftime('%d %b %Y %H:%M')}*\n\n"
            f"⏳ **Belum ada data** — log dan close minimal {MIN_BUCKET_SIZE} trades "
            f"untuk generate insights.\n\n"
            f"Data yang dibutuhkan per trade:\n"
            f"- `signal_score` (dari Page 01 EMA score atau Page 04 grade)\n"
            f"- `regime_tag` (market regime saat entry)\n"
            f"- `risk_pct` (dari entry/SL price)\n"
            f"- `outcome` WIN/LOSS/BREAKEVEN + `pnl_r`\n",
            encoding="utf-8"
        )
        return msg

    if total < MIN_BUCKET_SIZE * 2:
        msg = (f"Learning V3: {total} trades — butuh minimal "
               f"{MIN_BUCKET_SIZE * 2} untuk pattern detection")
        LESSONS_FILE.write_text(
            f"# 📚 Trading Lessons V3\n\n"
            f"*Generated: {datetime.now().strftime('%d %b %Y %H:%M')} "
            f"| {len(real_trades)} real + {len(paper_trades)} paper trades*\n\n"
            f"⏳ **Data terlalu sedikit** — butuh minimal {MIN_BUCKET_SIZE * 2} closed trades "
            f"untuk pattern detection. Sekarang: {total}.\n",
            encoding="utf-8"
        )
        return msg

    # Run analysis
    try:
        single_dim = _analyze_single_dimension(all_trades)
        combos     = _analyze_combinations(all_trades)
        leaks      = _find_systematic_leaks(all_trades, single_dim)
        rules      = _derive_rules(combos, leaks, single_dim)
    except Exception as e:
        logger.error(f"[Learning V3] analysis error: {e}")
        return f"Learning V3: analysis error — {e}"

    # Overall stats
    wins  = [t for t in all_trades if t.get("outcome") == "WIN"]
    losses= [t for t in all_trades if t.get("outcome") == "LOSS"]
    pnl_rs= [t["pnl_r"] for t in all_trades if t.get("pnl_r") is not None]
    wr    = len(wins) / total * 100 if total else 0
    avg_r = sum(pnl_rs) / len(pnl_rs) if pnl_rs else 0
    exp   = sum(pnl_rs) / total if pnl_rs else 0

    # Write lessons.md
    now = datetime.now().strftime("%d %b %Y %H:%M")
    lines = [
        "# 📚 Trading Lessons V3 — Statistical Inference",
        f"*Generated: {now} | {len(real_trades)} real + {len(paper_trades)} paper trades*",
        "",
        "---",
        "## 📊 Overview",
        f"- **Total closed**: {total} trades ({len(wins)}W / {len(losses)}L)",
        f"- **Win Rate**: {wr:.1f}%",
        f"- **Avg R/trade**: {avg_r:+.2f}R | **Expectancy**: {exp:+.3f}R",
        "",
    ]

    # System verdict
    if exp > 0.3 and wr >= WR_GOOD:
        lines += [
            "### ✅ SYSTEM STATUS: PROFITABLE",
            f"> Expectancy positif ({exp:+.2f}R) + WR {wr:.0f}% — sistem bekerja.",
            "> Fokus: scale up setup yang sudah proven, jangan ganti yang tidak perlu.",
            "",
        ]
    elif exp > 0:
        lines += [
            "### 🟡 SYSTEM STATUS: MARGINALLY PROFITABLE",
            f"> Expectancy {exp:+.2f}R — positif tapi tipis. WR {wr:.0f}%.",
            "> Fokus: eliminasi systematic leaks di bawah untuk improve expectancy.",
            "",
        ]
    elif total >= 10:
        lines += [
            "### 🔴 SYSTEM STATUS: UNPROFITABLE",
            f"> Expectancy {exp:+.2f}R — negatif. Immediate action required.",
            "> Review leaks dan derived rules di bawah. Paper trade sampai WR ≥ 50%.",
            "",
        ]
    else:
        lines += [
            f"### ⏳ SYSTEM STATUS: INSUFFICIENT DATA ({total}/{MIN_BUCKET_SIZE * 2} minimum)",
            "> Terus log trades. Pattern baru akan muncul setelah lebih banyak data.",
            "",
        ]

    # Systematic leaks
    if leaks:
        lines += ["---", "## ⚠ SYSTEMATIC LEAKS — Perbaiki Ini Dulu", ""]
        for leak in leaks:
            sev_icon = "🚨" if leak["severity"] == "CRITICAL" else "⚠️"
            lines += [
                f"### {sev_icon} {leak['label']}",
                f"- **Data**: {leak['detail']}",
                f"- **{leak['rule']}**",
                "",
            ]

    # Combination findings
    trade_this  = [c for c in combos if c["verdict"] == "TRADE_THIS"]
    never_again = [c for c in combos if c["verdict"] == "NEVER_AGAIN"]

    if trade_this:
        lines += ["---", "## ✅ TRADE THIS — Kombinasi yang Profitable", ""]
        for c in trade_this[:4]:
            s = c["stats"]
            lines += [
                f"**{c['conditions']}**",
                f"- {s['n']} trades | WR **{s['wr']:.0f}%** | Avg **{s['avg_r']:+.2f}R**",
                f"- {s['wins']}W / {s['losses']}L",
                "",
            ]

    if never_again:
        lines += ["---", "## ❌ NEVER AGAIN — Kombinasi yang Konsisten Rugi", ""]
        for c in never_again[:4]:
            s = c["stats"]
            lines += [
                f"**{c['conditions']}**",
                f"- {s['n']} trades | WR **{s['wr']:.0f}%** | Avg **{s['avg_r']:+.2f}R**",
                f"- {s['wins']}W / {s['losses']}L",
                "",
            ]

    # Win rate by dimension tables
    lines += ["---", "## 📈 WIN RATE PER DIMENSI", ""]

    # Regime table
    regime_st = single_dim.get("regime", {})
    if regime_st:
        lines.append("**By Regime:**")
        for r, s in sorted(regime_st.items(), key=lambda x: -x[1]["wr"]):
            bar = "█" * int(s["wr"] / 10) + "░" * (10 - int(s["wr"] / 10))
            icon = "✅" if s["is_good"] else "❌" if s["is_bad"] else "🟡"
            lines.append(f"- {icon} `{r}`: {bar} {s['wr']:.0f}% ({s['n']} trades, avg {s['avg_r']:+.2f}R)")
        lines.append("")

    # Grade table
    grade_st = single_dim.get("grade", {})
    if grade_st:
        lines.append("**By Grade (derived dari signal_score):**")
        for g in ["A+", "A", "B", "C", "D", "F"]:
            if g in grade_st:
                s = grade_st[g]
                bar  = "█" * int(s["wr"] / 10) + "░" * (10 - int(s["wr"] / 10))
                icon = "✅" if s["is_good"] else "❌" if s["is_bad"] else "🟡"
                lines.append(f"- {icon} Grade `{g}`: {bar} {s['wr']:.0f}% ({s['n']} trades, avg {s['avg_r']:+.2f}R)")
        lines.append("")

    # Risk table
    risk_st = single_dim.get("risk", {})
    if risk_st:
        lines.append("**By Risk %:**")
        for k in ["<10%", "10-15%", "15-25%", ">25%"]:
            if k in risk_st:
                s    = risk_st[k]
                bar  = "█" * int(s["wr"] / 10) + "░" * (10 - int(s["wr"] / 10))
                icon = "✅" if s["is_good"] else "❌" if s["is_bad"] else "🟡"
                lines.append(f"- {icon} Risk `{k}`: {bar} {s['wr']:.0f}% ({s['n']} trades, avg {s['avg_r']:+.2f}R)")
        lines.append("")

    # Derived rules
    if rules:
        lines += ["---", "## 📋 DERIVED RULES — Langsung Pakai", ""]
        green_rules = [r for r in rules if r["type"] == "GREEN"]
        red_rules   = [r for r in rules if r["type"] == "RED"]
        if green_rules:
            lines.append("**✅ Lakukan ini:**")
            for r in green_rules:
                lines += [f"- {r['rule']}", f"  *{r['action']}*", ""]
        if red_rules:
            lines.append("**❌ Hindari ini:**")
            for r in red_rules:
                lines += [f"- {r['rule']}", f"  *{r['action']}*", ""]

    # Holding analysis
    hold = single_dim.get("hold", {})
    if hold.get("avg_bars_win") and hold.get("avg_bars_loss"):
        lines += [
            "---",
            "## ⏱ HOLDING PATTERN",
            f"- Avg win held: **{hold['avg_bars_win']:.0f} bars**",
            f"- Avg loss held: **{hold['avg_bars_loss']:.0f} bars**",
        ]
        if hold.get("holding_leak"):
            lines += [
                "- ⚠️ **HOLDING LEAK**: kamu hold loser lebih lama dari winner.",
                "  → Cut losses at SL — no exceptions. Don't hope.",
            ]
        else:
            lines += ["- ✅ Trade management bagus: cut losses lebih cepat dari winners."]
        lines.append("")

    lines += [
        "---",
        f"*Learning V3 — Next update: setelah 5 trades berikutnya*",
        f"*Data: {len(real_trades)} real trades + {len(paper_trades)} paper trades*",
    ]

    LESSONS_FILE.write_text("\n".join(lines), encoding="utf-8")

    n_leaks  = len(leaks)
    n_rules  = len(rules)
    n_combos = len(trade_this) + len(never_again)

    return (
        f"Learning V3: {total} trades | WR {wr:.0f}% | Expectancy {exp:+.2f}R | "
        f"{n_leaks} leaks | {n_combos} combo patterns | {n_rules} derived rules"
    )
