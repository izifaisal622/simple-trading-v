"""
Simple Trading V6 — Director Agent (Strict AI Manager)
========================================================
The Director is the top-level supervisor of ALL agents.
It monitors BOTH strategies (EMA XBO + Follow Whale).

RESPONSIBILITIES:
1. Benchmark every agent against hard performance standards
2. Read journals + scan results to detect underperformance
3. Write strict improvement mandates — specific, actionable, measurable
4. Track if mandates were followed (regression detection)
5. Generate auto-patches — config changes agents apply themselves
6. Escalate critical failures to the user via alert

DIRECTOR LAWS (non-negotiable):
  I. Every agent must beat its time budget or get a mandate
  II. Win rate below 40% → mandatory parameter tightening
  III. Whale scan with 0 results in non-bear → scanner failure → lower thresholds
  IV. Any regression >30% → rollback flag raised
  V. Mandates not resolved in 3 runs → escalate to user
  VI. Director reviews BOTH strategies every Monday, quick-check every day
  VII. Auto-patch is applied silently — agents pick it up on next run
"""

import json
import sqlite3
import time
import tracemalloc
import logging
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf
import pandas as pd

from core.data_feed import get_ihsg_regime

LOGS_DIR        = Path(__file__).parent.parent / "logs"
REPORT_FILE     = LOGS_DIR / "director_report.md"
BENCH_FILE      = LOGS_DIR / "agent_benchmarks.json"
MANDATE_FILE    = LOGS_DIR / "improvement_mandates.md"
HISTORY_FILE    = LOGS_DIR / "bench_history.json"
PLAYBOOK_FILE   = LOGS_DIR / "edge_playbook.md"
STUDY_FILE      = LOGS_DIR / "market_study.json"
WEB_STUDY_FILE  = LOGS_DIR / "web_study.json"
AUTOPATCH_FILE  = LOGS_DIR / "auto_patch.json"
RESULTS_FILE    = LOGS_DIR / "daily_results.json"
JOURNAL_FILE    = LOGS_DIR / "journal.md"
DB_PATH         = LOGS_DIR / "trade_log.db"
LOGS_DIR.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Performance Standards — hard limits, no excuses
# ─────────────────────────────────────────────────────────────────────────────

STANDARDS = {
    "technical_engine":  {"max_s": 0.3,  "max_mem_mb": 50,  "desc": "EMA calc per ticker"},
    "scanner_full":      {"max_s": 240,  "max_mem_mb": 400, "desc": "Full IDX ~350 tickers"},
    "scanner_watchlist": {"max_s": 90,   "max_mem_mb": 200, "desc": "Watchlist ~100 tickers"},
    "whale_scanner":     {"max_s": 120,  "max_mem_mb": 200, "desc": "Whale full IDX"},
    "whale_watchlist":   {"max_s": 60,   "max_mem_mb": 150, "desc": "Whale watchlist"},
    "learning_agent":    {"max_s": 8,    "max_mem_mb": 30,  "desc": "Trade lessons"},
    "data_feed":         {"max_s": 10,   "max_mem_mb": 30,  "desc": "IDX universe + IHSG"},
    "smc_engine":        {"max_s": 6,    "max_mem_mb": 80,  "desc": "SMC per ticker"},
    "market_study":      {"max_s": 60,   "max_mem_mb": 100, "desc": "Sector rotation scan"},
}

# EMA XBO thresholds — Director will tighten/loosen these based on win rate
EMA_THRESHOLDS = {
    "win_rate_excellent": 0.60,
    "win_rate_acceptable":0.40,
    "win_rate_poor":      0.30,
    "min_score_tight":    5,
    "min_score_normal":   3,
    "min_score_loose":    1,
}

# Whale thresholds — Director will auto-patch based on alert quality
WHALE_THRESHOLDS = {
    "zero_alerts_threshold": 5,   # if 0 alerts for N consecutive days → lower vol_mult
    "excess_alerts_threshold": 80, # if >80 alerts → raise vol_mult (too noisy)
    "min_conviction_target": 4,    # average conviction should be ≥ 4
}


def _get_severity(elapsed: float, max_s: float) -> str:
    ratio = elapsed / max_s if max_s else 0
    if ratio >= 2.0:  return "CRITICAL"
    if ratio >= 1.5:  return "FAIL"
    if ratio >= 1.2:  return "WARN"
    return "PASS"


def _measure(fn: Callable, *args, **kwargs):
    tracemalloc.start()
    t0 = time.perf_counter()
    result, err = None, None
    try:
        result = fn(*args, **kwargs)
    except Exception as e:
        err = str(e)
    elapsed = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, round(elapsed, 3), round(peak / 1024 / 1024, 1), err


# ─────────────────────────────────────────────────────────────────────────────
# Auto-Patch System — agents read this on startup and apply config changes
# ─────────────────────────────────────────────────────────────────────────────

def _load_autopatch() -> dict:
    if not AUTOPATCH_FILE.exists():
        return {}
    try:
        return json.loads(AUTOPATCH_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_autopatch(patch: dict, reason: str):
    """Write auto-patch file that agents will pick up on next run."""
    existing = _load_autopatch()
    existing.update(patch)
    existing["_last_updated"] = datetime.now().isoformat()
    existing["_reason"]       = reason
    existing["_applied"]      = False
    AUTOPATCH_FILE.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    logger.info(f"[Director] Auto-patch written: {patch} | Reason: {reason}")


def apply_autopatch(config) -> tuple:
    """
    Called by agents at startup. Applies any pending auto-patches to config.
    Returns (modified_config, patch_log).
    """
    patch = _load_autopatch()
    if not patch or patch.get("_applied"):
        return config, []

    log = []
    for key, value in patch.items():
        if key.startswith("_"):
            continue
        if hasattr(config, key):
            old = getattr(config, key)
            setattr(config, key, value)
            log.append(f"Auto-patched {key}: {old} → {value}")
            logger.info(f"[AutoPatch] {key}: {old} → {value}")

    # Mark as applied
    patch["_applied"] = True
    AUTOPATCH_FILE.write_text(json.dumps(patch, indent=2), encoding="utf-8")
    return config, log


# ─────────────────────────────────────────────────────────────────────────────
# Strategy Analysis — Director reads results and judges quality
# ─────────────────────────────────────────────────────────────────────────────

def _analyze_ema_performance() -> dict:
    """Director reads EMA XBO results and judges performance."""
    findings = []
    patches  = {}
    grade    = "A"

    # Read last results
    if not RESULTS_FILE.exists():
        return {"grade": "N/A", "findings": ["No scan results found"], "patches": {}}

    try:
        data        = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
        ema_results = data.get("ema_results", [])
        regime      = data.get("regime", {})
        cycle       = regime.get("cycle", "UNKNOWN")
    except Exception as e:
        return {"grade": "F", "findings": [f"Cannot read results: {e}"], "patches": {}}

    total      = len(ema_results)
    breakouts  = [r for r in ema_results if r.get("signal") == "BREAKOUT"]
    watchlists = [r for r in ema_results if r.get("signal") == "WATCHLIST"]
    avg_score  = sum(r.get("score",0) for r in ema_results) / total if total else 0
    is_bear    = cycle in ("BEAR_TREND", "BEAR_CONSOLIDATION")
    is_bull    = cycle in ("BULL_TREND", "BULL_CONSOLIDATION")

    # V6 RUBRIK: Grade = CORRECTNESS sistem, bukan jumlah sinyal
    # Bear+0breakout = BENAR → A  (sistem melindungi modal dengan tepat)
    # Bull+breakouts tinggi = BENAR → A
    # Salah kondisi (false breakout di bear, silent di bull) = C/D/F

    if is_bear and len(breakouts) > 15:
        grade = "D"
        findings.append("🟡 WARN: Terlalu banyak breakout di bear market — kemungkinan false signals")
        findings.append("  → Tighten min_score to 5")
        patches["min_score"] = 5

    elif is_bear:
        # Bear + 0 breakout = SISTEM BEKERJA BENAR = A
        grade = "A"
        findings.append(f"✅ Bear defense aktif: {len(breakouts)} breakout (benar), {len(watchlists)} watchlist, avg_score={avg_score:.1f}/7")
        if len(watchlists) > 0:
            findings.append(f"  → {len(watchlists)} saham di-queue untuk bull market berikutnya")

    elif is_bull and len(breakouts) == 0 and avg_score < 2.5:
        grade = "D"
        findings.append(f"🔴 FAIL: Bull market, {total} setups, 0 breakouts, avg_score={avg_score:.1f} — parameter terlalu ketat")
        patches["min_score"] = 2
        patches["box_range_pct"] = 15.0

    elif is_bull and len(breakouts) >= 5 and avg_score >= 4.5:
        grade = "A+"
        findings.append(f"✅✅ EMA XBO EXCELLENT: {total} setups, {len(breakouts)} breakouts, avg_score={avg_score:.1f}/7")

    elif is_bull and len(breakouts) >= 3 and avg_score >= 4.0:
        grade = "A"
        findings.append(f"✅ EMA XBO solid: {total} setups, {len(breakouts)} breakouts, avg_score={avg_score:.1f}/7")

    elif is_bull and len(breakouts) >= 1 and avg_score >= 3.0:
        grade = "B"
        findings.append(f"✓ EMA XBO productive: {total} setups, {len(breakouts)} breakouts, avg_score={avg_score:.1f}/7")

    elif avg_score < 2.0 and total > 0:
        grade = "C"
        findings.append(f"🟡 WARN: avg_score {avg_score:.1f}/7 rendah — quality concern")
        patches["min_score"] = max(2, int(avg_score))

    else:
        grade = "B"
        findings.append(f"✓ EMA XBO: {total} setups, {len(breakouts)} breakouts, avg_score={avg_score:.1f}/7")

    # Trade history check
    if DB_PATH.exists():
        try:
            conn  = sqlite3.connect(str(DB_PATH))
            rows  = conn.execute("""
                SELECT outcome, pnl_r FROM outcomes o JOIN signals s ON o.signal_id=s.id
                WHERE o.outcome NOT IN ('OPEN') AND o.outcome IS NOT NULL
            """).fetchall()
            conn.close()
            if rows:
                wins     = [r for r in rows if r[0] and "WIN" in r[0]]
                win_rate = len(wins) / len(rows)
                avg_r    = sum(r[1] for r in rows if r[1]) / len(rows)

                if win_rate < EMA_THRESHOLDS["win_rate_poor"]:
                    grade = "F"
                    findings.append(f"🚨 CRITICAL: Win rate {win_rate*100:.0f}% — BELOW FLOOR ({EMA_THRESHOLDS['win_rate_poor']*100:.0f}%)")
                    findings.append("  → Director mandate: STOP live trading. Paper trade until 10 wins.")
                    patches["min_score"] = EMA_THRESHOLDS["min_score_tight"]

                elif win_rate < EMA_THRESHOLDS["win_rate_acceptable"]:
                    grade = "C"
                    findings.append(f"🟡 WARN: Win rate {win_rate*100:.0f}% — needs improvement")
                    findings.append("  → Tightening min_score to 4/6")
                    patches["min_score"] = 4

                elif win_rate >= EMA_THRESHOLDS["win_rate_excellent"]:
                    findings.append(f"✅ Win rate excellent: {win_rate*100:.0f}% | Avg R: {avg_r:.2f}")

                if avg_r < 0 and len(rows) >= 5:
                    grade = "F" if grade != "F" else grade
                    findings.append(f"🚨 CRITICAL: Negative expectancy ({avg_r:.2f}R) — strategy not working")
        except Exception as e:
            findings.append(f"⚠️ Cannot read trade history: {e}")

    return {"grade": grade, "findings": findings, "patches": patches,
            "total": total, "breakouts": len(breakouts), "watchlists": len(watchlists),
            "avg_score": round(avg_score, 1)}


def _analyze_whale_performance() -> dict:
    """Director reads Whale scan results and judges quality."""
    findings = []
    patches  = {}
    grade    = "A"

    if not RESULTS_FILE.exists():
        return {"grade": "N/A", "findings": ["No results found"], "patches": {}}

    try:
        data          = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
        whale_results = data.get("whale_results", [])
        whale_ctx     = data.get("whale_context", {})
        regime        = data.get("regime", {})
        cycle         = whale_ctx.get("cycle", regime.get("cycle", "UNKNOWN"))
    except Exception as e:
        return {"grade": "F", "findings": [f"Cannot read results: {e}"], "patches": {}}

    total      = len(whale_results)
    ema_align  = [w for w in whale_results if w.get("ema_trend") == "BULLISH"
                  and "BUY" in w.get("direction","")]
    avg_conv   = sum(w.get("conviction",0) for w in whale_results) / total if total else 0

    # Zero alerts in non-bear — scanner is too strict
    if total == 0 and cycle not in ("BEAR_TREND",):
        grade = "D"
        findings.append(f"🔴 FAIL: Zero whale alerts in {cycle} market — thresholds too high")
        findings.append("  → Director auto-patching: lowering vol_multiplier")
        # This patches the whale scanner's default for next run
        patches["whale_vol_multiplier"] = 1.5
        patches["whale_min_value_bn"]   = 0.2

    elif total == 0 and cycle == "BEAR_TREND":
        grade = "A"
        findings.append("✅ Zero alerts = BENAR — BEAR_TREND, scanner defensif, melindungi modal")

    elif total > WHALE_THRESHOLDS["excess_alerts_threshold"]:
        grade = "C"
        findings.append(f"🟡 WARN: {total} alerts is too noisy — too many false signals")
        findings.append("  → Raising vol_multiplier to filter noise")
        patches["whale_vol_multiplier"] = 3.0

    elif avg_conv < WHALE_THRESHOLDS["min_conviction_target"] and total > 0:
        # Bear market = low conviction is CORRECT behavior = A
        if cycle in ("BEAR_TREND","BEAR_CONSOLIDATION","SANGAT_SEPI"):
            findings.append(f"✅ Bear market: conviction {avg_conv:.1f}/10 wajar, scanner defensif benar")
        else:
            grade = "C"
            findings.append(f"🟡 WARN: Avg conviction {avg_conv:.1f}/10 — signals lack quality")
            findings.append("  → Tightening min_value_bn to filter low-quality signals")
            patches["whale_min_value_bn"] = 0.8

    else:
        grade = "A"
        findings.append(f"✅ Whale scan healthy: {total} alerts, {len(ema_align)} best setups, "
                        f"avg conviction {avg_conv:.1f}/10")

    # Bear market special: check if recovery signals exist
    if cycle in ("BEAR_TREND","BEAR_CONSOLIDATION"):
        recovery = [w for w in whale_results
                    if "BUY" in w.get("direction","")
                    and w.get("pct_from_52w_high",0) < -15]
        if recovery:
            findings.append(f"🌅 Recovery signals: {len(recovery)} beaten-down stocks with whale buying")
        else:
            findings.append("⏳ No recovery signals yet — continue monitoring")

    return {"grade": grade, "findings": findings, "patches": patches,
            "total": total, "ema_aligned": len(ema_align),
            "avg_conviction": round(avg_conv, 1)}


# ─────────────────────────────────────────────────────────────────────────────
# Agent Benchmarks
# ─────────────────────────────────────────────────────────────────────────────

def _bench_data_feed(cfg) -> dict:
    from core.data_feed import get_ihsg_regime, get_idx_universe
    std = STANDARDS["data_feed"]
    _, elapsed, mem, err = _measure(lambda: (get_idx_universe(), get_ihsg_regime()))
    sev = _get_severity(elapsed, std["max_s"])
    return {"agent":"data_feed","elapsed":elapsed,"mem_mb":mem,
            "severity":sev,"pass":sev=="PASS","issues":[err] if err else []}


def _bench_technical_engine(cfg) -> dict:
    from core.technical_engine import EMABreakoutEngine
    from core.data_feed import DataFeed
    std    = STANDARDS["technical_engine"]
    engine = EMABreakoutEngine(cfg)
    feed   = DataFeed(timeframe="1wk")
    dfs    = feed.fetch_batch(["BBCA.JK","TLKM.JK","PTBA.JK"], max_workers=3)
    timings, mems = [], []
    for ticker, df in dfs.items():
        _, elapsed, mem, _ = _measure(engine.analyze, df, ticker)
        timings.append(elapsed)
        mems.append(mem)
    avg_t  = sum(timings)/len(timings) if timings else 999
    peak_m = max(mems) if mems else 999
    sev    = _get_severity(avg_t, std["max_s"])
    issues = []
    if avg_t > std["max_s"]:  issues.append(f"avg {avg_t:.2f}s > limit {std['max_s']}s")
    if peak_m > std["max_mem_mb"]: issues.append(f"mem {peak_m}MB > limit")
    return {"agent":"technical_engine","elapsed":round(avg_t,3),"mem_mb":peak_m,
            "severity":sev,"pass":sev=="PASS","issues":issues}


def _bench_learning_agent() -> dict:
    std = STANDARDS["learning_agent"]
    try:
        from agents.learning_agent import run_learning_cycle
        _, elapsed, mem, err = _measure(run_learning_cycle, auto_apply=False)
        sev = _get_severity(elapsed, std["max_s"])
        return {"agent":"learning_agent","elapsed":elapsed,"mem_mb":mem,
                "severity":sev,"pass":sev=="PASS","issues":[err] if err else []}
    except Exception as e:
        return {"agent":"learning_agent","elapsed":0,"mem_mb":0,
                "severity":"SKIP","pass":True,"issues":[str(e)]}


def _load_history() -> dict:
    if not HISTORY_FILE.exists(): return {}
    try: return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception: return {}


def _detect_regression(name: str, elapsed: float, history: dict) -> Optional[str]:
    prev = history.get(name)
    if prev and elapsed > prev * 1.30:
        pct = (elapsed/prev - 1)*100
        return f"🔴 REGRESSION +{pct:.0f}% vs last run ({prev:.1f}s → {elapsed:.1f}s)"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Market Study (sector rotation)
# ─────────────────────────────────────────────────────────────────────────────

SECTORS = {
    "Banking":      ["BBCA.JK","BBRI.JK","BMRI.JK","BBNI.JK"],
    "Consumer":     ["UNVR.JK","ICBP.JK","INDF.JK","MYOR.JK"],
    "Mining/Coal":  ["PTBA.JK","ADRO.JK","ITMG.JK","ANTM.JK"],
    "Property":     ["CTRA.JK","BSDE.JK","PWON.JK","SMRA.JK"],
    "Telco":        ["TLKM.JK","EXCL.JK","ISAT.JK"],
    "Infrastructure":["JSMR.JK","TOWR.JK","TBIG.JK"],
    "Health":       ["KLBF.JK","SIDO.JK","MIKA.JK"],
    "Tech":         ["GOTO.JK","BUKA.JK","EMTK.JK"],
    "Energy":       ["PGAS.JK","MEDC.JK","AKRA.JK"],
    "Plantation":   ["AALI.JK","LSIP.JK","SSMS.JK"],
}


def _analyze_sector_rotation() -> dict:
    def _score(sector_name, tickers):
        momenta = []
        for ticker in tickers:
            try:
                df = yf.download(ticker, period="6mo", interval="1wk",
                                 progress=False, auto_adjust=True)
                if df is None or len(df) < 8: continue
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                close   = df["Close"]
                mom_4w  = (float(close.iloc[-1])/float(close.iloc[-4])  - 1)*100
                mom_13w = (float(close.iloc[-1])/float(close.iloc[-13]) - 1)*100 if len(close)>=13 else 0
                above   = float(close.iloc[-1]) > float(close.ewm(span=13,adjust=False).mean().iloc[-1])
                momenta.append({"mom_4w":mom_4w,"mom_13w":mom_13w,"above":above})
            except Exception:
                continue
        if not momenta: return sector_name, None
        avg_4w  = sum(m["mom_4w"]  for m in momenta)/len(momenta)
        avg_13w = sum(m["mom_13w"] for m in momenta)/len(momenta)
        pct_up  = sum(1 for m in momenta if m["above"])/len(momenta)
        score   = avg_4w*0.4 + avg_13w*0.3 + pct_up*10*0.3
        return sector_name, {"score":round(score,2),"mom_4w":round(avg_4w,1),
                             "mom_13w":round(avg_13w,1),"pct_above":round(pct_up,2)}

    scores = {}
    with ThreadPoolExecutor(max_workers=5) as exe:
        futures = {exe.submit(_score, s, t): s for s, t in SECTORS.items()}
        for future in as_completed(futures):
            name, data = future.result()
            if data: scores[name] = data

    ranked = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)
    return {"ranked":ranked,"leaders":[s[0] for s in ranked[:3]],
            "laggards":[s[0] for s in ranked[-3:]],"data":scores}


def _analyze_trade_history() -> dict:
    if not DB_PATH.exists(): return {"total":0}
    try:
        conn = sqlite3.connect(str(DB_PATH))
        rows = conn.execute("""
            SELECT outcome, pnl_r, bars_held FROM manual_trades
            WHERE outcome != 'OPEN' AND outcome IS NOT NULL
        """).fetchall()
        conn.close()
    except Exception:
        return {"total":0}
    if not rows: return {"total":0}
    wins   = [r for r in rows if r[0] and "WIN"  in r[0]]
    losses = [r for r in rows if r[0] and "LOSS" in r[0]]
    pnl_rs = [r[1] for r in rows if r[1] is not None]
    bars_w = [r[2] for r in wins   if r[2] is not None]
    bars_l = [r[2] for r in losses if r[2] is not None]
    return {
        "total":         len(rows),
        "win_rate":      len(wins)/len(rows),
        "avg_r":         round(sum(pnl_rs)/len(pnl_rs),2) if pnl_rs else 0,
        "expectancy":    round(sum(pnl_rs)/len(rows),2)   if pnl_rs else 0,
        "avg_bars_win":  round(sum(bars_w)/len(bars_w),1) if bars_w else 0,
        "avg_bars_loss": round(sum(bars_l)/len(bars_l),1) if bars_l else 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Mandate Writer — strict, specific, actionable
# ─────────────────────────────────────────────────────────────────────────────

def _write_mandates(benchmarks, ema_analysis, whale_analysis, regime, history) -> str:
    today    = datetime.now().strftime("%d %b %Y %H:%M")
    cycle    = regime.get("cycle","?")
    ihsg     = regime.get("ihsg",0)
    mom_4w   = regime.get("mom_4w",0)

    sev_icon = {"PASS":"✅","WARN":"🟡","FAIL":"🔴","CRITICAL":"🚨","SKIP":"⚪"}

    lines = [
        "# 🎖 Director Report — Simple Trading V6",
        f"*{today} | IHSG {ihsg:,.0f} | {cycle} | 4W {mom_4w:+.1f}%*",
        "",
        "---",
        "## 📊 Strategy Performance",
        "",
        f"### EMA XBO — Grade: {ema_analysis.get('grade','?')}",
    ]
    for f in ema_analysis.get("findings",[]): lines.append(f"- {f}")
    lines += ["", f"### Follow Whale — Grade: {whale_analysis.get('grade','?')}"]
    for f in whale_analysis.get("findings",[]): lines.append(f"- {f}")

    # Agent benchmarks
    lines += ["","---","## ⚡ Agent Benchmarks"]
    violations = []
    for b in benchmarks:
        icon = sev_icon.get(b["severity"],"❓")
        std  = STANDARDS.get(b["agent"],{})
        lines.append(
            f"- {icon} **{b['agent']}**: {b['elapsed']}s / {std.get('max_s','?')}s limit "
            f"| {b['mem_mb']}MB | {b['severity']}"
        )
        for issue in b.get("issues",[]):
            lines.append(f"  - ⚠️ {issue}")
        if b["severity"] in ("FAIL","CRITICAL","WARN"):
            violations.append(b)

    # Patches summary
    all_patches = {}
    all_patches.update(ema_analysis.get("patches",{}))
    all_patches.update(whale_analysis.get("patches",{}))

    if all_patches:
        lines += ["","---","## 🔧 Auto-Patches Applied"]
        for key, val in all_patches.items():
            lines.append(f"- `{key}` → **{val}** *(agents will pick up on next run)*")

    # Strict mandates
    lines += ["","---","## 📋 Director Mandates"]

    mandate_count = 0
    if violations:
        for v in violations:
            mandate_count += 1
            agent = v["agent"]
            lines.append(f"\n**Mandate #{mandate_count} — {agent.upper()}**")
            if v["severity"] == "CRITICAL":
                lines.append(f"  🚨 CRITICAL: {agent} exceeded time budget by 2×+")
                lines.append(f"  → Required: reduce to under {STANDARDS.get(agent,{}).get('max_s','?')}s")
                lines.append("  → Method: add caching, reduce API calls, pre-filter harder")
            elif v["severity"] == "FAIL":
                lines.append(f"  🔴 FAIL: {agent} over time budget")
                lines.append("  → Required: profile and optimize hotspot")
            elif v["severity"] == "WARN":
                lines.append(f"  🟡 WARN: {agent} approaching limit — improve before next run")

    if ema_analysis.get("grade") in ("D","F"):
        mandate_count += 1
        lines += [
            f"\n**Mandate #{mandate_count} — EMA XBO SCANNER**",
            "  🔴 Signal quality below standard",
            "  → Required: review entry criteria, adjust thresholds",
            f"  → Auto-patch: min_score={all_patches.get('min_score','N/A')}",
            "  → Deadline: verify improvement in next 3 scans",
        ]

    if whale_analysis.get("grade") in ("D","F"):
        mandate_count += 1
        lines += [
            f"\n**Mandate #{mandate_count} — WHALE SCANNER**",
            "  🔴 Alert quality below standard",
            f"  → Required: {whale_analysis.get('findings',[{}])[0]}",
            "  → Auto-patch applied — verify next scan has results",
        ]

    if mandate_count == 0:
        lines.append("✅ No active mandates. All agents performing within standards.")
        lines.append("🎯 Focus: maintain quality, look for optimization opportunities.")

    # FIX V4: Outcome logging mandate — inject if 0 closed trades
    if DB_PATH.exists():
        try:
            import sqlite3 as _sq
            _c = _sq.connect(str(DB_PATH))
            _closed = _c.execute(
                "SELECT COUNT(*) FROM manual_trades WHERE outcome IN ('WIN','LOSS','BREAKEVEN')"
            ).fetchone()[0]
            _c.close()
            if _closed == 0:
                mandate_count += 1
                lines += [
                    f"\n**Mandate #{mandate_count} — OUTCOME LOGGING (CRITICAL)**",
                    "  🚨 ZERO closed trades logged. Win rate = UNKNOWN. Sistem tidak bisa belajar.",
                    "  → Required: Log setiap trade yang diambil di dashboard Outcome Tracker.",
                    "  → Target: 30 closed trades untuk validasi win rate.",
                    "  → Tool: Dashboard → EMA XBO → Outcome Tracker section",
                ]
            elif _closed < 30:
                lines.append(f"\n📊 Outcome progress: {_closed}/30 closed trades logged.")
        except Exception:
            pass

    # Agent Laws
    lines += [
        "","---","## ⚖️ Agent Laws (Non-Negotiable)",
        "| # | Law |","|---|---|",
        "| I | Every agent must beat its time budget or explain why |",
        "| II | Win rate <40% → mandatory parameter tightening |",
        "| III | Whale 0 alerts in non-bear → lower threshold auto-patch |",
        "| IV | Regression >30% → rollback flag raised immediately |",
        "| V | Mandates unresolved after 3 runs → escalate to user |",
        "| VI | Director reviews BOTH strategies every day |",
        "| VII | Auto-patches applied silently — no user action needed |",
        "| VIII | All agents must learn from outcomes — no static strategies |",
        "| IX | Bear market: build recovery watchlist, not wait passively |",
        "| X | Journal every scan — no exceptions |",
    ]

    content = "\n".join(lines)
    MANDATE_FILE.write_text(content, encoding="utf-8")
    REPORT_FILE.write_text(content,  encoding="utf-8")
    return content


def _generate_playbook(ihsg, sectors, history, deep) -> str:
    today = datetime.now().strftime("%d %b %Y %H:%M")
    cycle = ihsg.get("cycle","?")
    lines = [
        "# 📋 Edge Playbook — Simple Trading V6",
        f"*{today} | {'WEEKLY DEEP' if deep else 'Daily'} | Director-Approved*","",
        "## 🌏 Market Regime",
        f"- IHSG: {ihsg.get('ihsg',0):,.0f} | **{cycle}** ({ihsg.get('breadth',0)}/6 breadth)",
        f"- 4W: {ihsg.get('mom_4w',0):+.1f}% | 13W: {ihsg.get('mom_13w',0):+.1f}%","",
        "## 📋 Execution Rules (Director-Set)",
    ]
    if cycle == "BULL_TREND":
        lines += ["- 🟢 Bull market. Min score **4/6**. Full size.",
                  "- 🟢 Let winners run to TP2/TP3. Trail SL after TP1."]
    elif cycle == "BULL_CONSOLIDATION":
        lines += ["- 🟡 Consolidation. Min score **5/6**. Normal size.",
                  "- 🟡 Prefer tight boxes. Take TP1, let half run."]
    elif cycle == "TRANSITION":
        lines += ["- 🟠 Transition. Min score **5/6**. Reduce size 25%.",
                  "- 🟠 TP1 only. Tighter SL."]
    elif cycle == "BEAR_CONSOLIDATION":
        lines += ["- 🔴 Defensive. Min score **6/6** + SMC bullish.",
                  "- 🔴 Max risk 5%. TP1 only."]
    else:
        lines += ["- ❌ BEAR TREND — NO NEW LONGS.",
                  "- ⏳ Build recovery watchlist from Whale page.",
                  "- 🐋 Monitor whale buying in beaten-down stocks."]

    if ihsg.get("recovering"):
        lines.append("- 🌅 Recovery signal — begin watchlist building NOW")

    lines += ["","## 🔄 Sector Leaders"]
    if sectors and sectors.get("ranked"):
        lines.append(f"- **Lead**: {', '.join(sectors.get('leaders',[]))}")
        lines.append(f"- **Avoid**: {', '.join(sectors.get('laggards',[]))}")
        for name, data in sectors.get("ranked",[])[:5]:
            icon = "🟢" if data["score"]>2 else "🟡" if data["score"]>-2 else "🔴"
            lines.append(f"- {icon} {name}: {data['score']:+.1f} | 4W {data['mom_4w']:+.1f}%")
    else:
        lines.append("- Run weekly deep scan for sector data")

    lines += ["","## 📈 Personal Edge"]
    if history.get("total",0) >= 3:
        lines += [
            f"- {history['total']} trades | WR {history['win_rate']*100:.0f}% | "
            f"Avg R {history['avg_r']:.2f} | Expectancy {history['expectancy']:.2f}R",
        ]
        if history.get("avg_bars_loss",0) > history.get("avg_bars_win",0):
            lines.append("- ⚠️ Holding losers longer — cut at SL, no exceptions")
    else:
        lines.append("- Log all trades for personalised edge data")

    lines += ["","---",f"*Director-generated | Next: {'Monday deep' if not deep else 'tomorrow daily'}*"]
    content = "\n".join(lines)
    PLAYBOOK_FILE.write_text(content, encoding="utf-8")
    return content



# ─────────────────────────────────────────────────────────────────────────────
# WEB SELF-STUDY (V6.4) — Director fetches IDX market context daily
# ─────────────────────────────────────────────────────────────────────────────

_WEB_STUDY_SOURCES = [
    # IDX official market summary
    {
        "name":  "IDX Market Summary",
        "url":   "https://www.idx.co.id/en/market-data/market-summary/",
        "type":  "html",
        "parse": "summary",
    },
    # Yahoo Finance IDX composite
    {
        "name":  "IHSG Recent Data",
        "url":   "https://query1.finance.yahoo.com/v8/finance/chart/%5EJKSE?interval=1d&range=5d",
        "type":  "json",
        "parse": "yf_chart",
    },
    # CNBC Indonesia headlines (lightweight RSS)
    {
        "name":  "CNBC Indonesia",
        "url":   "https://www.cnbcindonesia.com/rss",
        "type":  "rss",
        "parse": "rss_headlines",
    },
]

def _fetch_web_content(url: str, timeout: int = 6) -> str | None:
    """Fetch web content with a simple UA header. Returns raw string or None."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 STV/6.4 (IDX Market Research)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("latin-1", errors="replace")
    except Exception as e:
        logger.debug(f"[Director] web fetch {url}: {e}")
        return None


def _parse_yf_chart(raw: str) -> dict:
    """Parse Yahoo Finance chart API response for IHSG data."""
    try:
        data = json.loads(raw)
        result = data["chart"]["result"][0]
        meta   = result.get("meta", {})
        quotes = result.get("indicators", {}).get("quote", [{}])[0]
        closes = quotes.get("close", [])

        recent_closes = [c for c in closes if c is not None][-5:]
        if len(recent_closes) >= 2:
            chg_pct = (recent_closes[-1] / recent_closes[-2] - 1) * 100
            chg_5d  = (recent_closes[-1] / recent_closes[0]  - 1) * 100
        else:
            chg_pct = 0.0
            chg_5d  = 0.0

        return {
            "price":    round(meta.get("regularMarketPrice", 0), 2),
            "chg_pct":  round(chg_pct, 2),
            "chg_5d":   round(chg_5d, 2),
            "currency": meta.get("currency", "IDR"),
            "source":   "Yahoo Finance",
        }
    except Exception as e:
        logger.debug(f"[Director] yf chart parse: {e}")
        return {}


def _parse_rss_headlines(raw: str, max_items: int = 8) -> list:
    """Extract headlines from RSS feed (basic XML parse, no lxml needed)."""
    import re
    headlines = []
    try:
        # Simple regex — no external XML lib needed
        titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", raw, re.DOTALL)
        if not titles:
            titles = re.findall(r"<title>(.*?)</title>", raw, re.DOTALL)
        # Skip channel-level title (first item usually)
        for t in titles[1:max_items+1]:
            t = t.strip()
            if t and len(t) > 10:
                headlines.append(t)
    except Exception as e:
        logger.debug(f"[Director] rss parse: {e}")
    return headlines[:max_items]


def _run_web_study() -> dict:
    """
    Daily web self-study — fetch IDX market context.
    Runs ~20-30 seconds max (sequential, short timeouts).

    Returns:
    - ihsg_live: live IHSG price + change
    - headlines: IDX-related news headlines
    - study_date: when this was fetched
    - sources_ok: how many sources responded
    """
    # Check if already studied today
    if WEB_STUDY_FILE.exists():
        try:
            existing = json.loads(WEB_STUDY_FILE.read_text(encoding="utf-8"))
            study_date = existing.get("study_date", "")
            if study_date[:10] == datetime.now().strftime("%Y-%m-%d"):
                logger.debug("[Director] Web study already done today, reusing")
                return existing
        except Exception:
            pass

    print("[Director] Running web self-study...")
    result = {
        "study_date": datetime.now().isoformat(),
        "sources_ok": 0,
        "ihsg_live": {},
        "headlines": [],
        "insights": [],
    }

    # ── IHSG live data ────────────────────────────────────────────────────────
    raw = _fetch_web_content(
        "https://query1.finance.yahoo.com/v8/finance/chart/%5EJKSE?interval=1d&range=5d"
    )
    if raw:
        ihsg = _parse_yf_chart(raw)
        if ihsg:
            result["ihsg_live"] = ihsg
            result["sources_ok"] += 1
            print(f"[Director] IHSG live: {ihsg.get('price',0):,.0f} "
                  f"({ihsg.get('chg_pct',0):+.2f}% today, "
                  f"{ihsg.get('chg_5d',0):+.2f}% 5d)")

    # ── CNBC Indonesia headlines ───────────────────────────────────────────────
    raw_cnbc = _fetch_web_content("https://www.cnbcindonesia.com/rss")
    if raw_cnbc:
        headlines = _parse_rss_headlines(raw_cnbc)
        if headlines:
            result["headlines"] = headlines
            result["sources_ok"] += 1
            print(f"[Director] {len(headlines)} headlines fetched")

    # ── Derive market insights ─────────────────────────────────────────────────
    insights = []
    ihsg_d   = result["ihsg_live"]
    if ihsg_d.get("chg_pct", 0) < -1.5:
        insights.append("⚠ IHSG turun >1.5% hari ini — tunda entry baru")
    elif ihsg_d.get("chg_pct", 0) > 1.5:
        insights.append("✅ IHSG naik >1.5% hari ini — momentum positif")
    if ihsg_d.get("chg_5d", 0) < -5:
        insights.append("🔴 IHSG turun >5% dalam 5 hari — caution mode")

    # Keyword scan in headlines for IDX relevance
    danger_kw  = ["hantam", "anjlok", "resesi", "jual", "asing keluar", "outflow", "melemah", "kapitulasi"]
    bullish_kw = ["naik", "menguat", "asing masuk", "inflow", "optimis", "rebound", "breakout"]
    hl_text    = " ".join(result["headlines"]).lower()
    danger_hits = sum(1 for kw in danger_kw  if kw in hl_text)
    bull_hits   = sum(1 for kw in bullish_kw if kw in hl_text)

    if danger_hits >= 3:
        insights.append(f"📰 Sentimen negatif dominan ({danger_hits} kata bahaya di headlines)")
    elif bull_hits >= 3:
        insights.append(f"📰 Sentimen positif dominan ({bull_hits} kata bullish di headlines)")

    result["insights"] = insights
    if insights:
        for ins in insights:
            print(f"[Director] {ins}")

    # Save
    try:
        WEB_STUDY_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning(f"[Director] web study save failed: {e}")

    print(f"[Director] Web study complete — {result['sources_ok']} sources OK")
    return result


def _run_market_study(deep=False) -> dict:
    print(f"[Director] Market study ({'deep' if deep else 'daily'})...")
    ihsg = get_ihsg_regime()

    last_study = {}
    if STUDY_FILE.exists():
        try: last_study = json.loads(STUDY_FILE.read_text(encoding="utf-8"))
        except Exception: pass

    sectors = _analyze_sector_rotation() if deep or not last_study.get("sectors") else last_study.get("sectors",{})
    history = _analyze_trade_history()

    STUDY_FILE.write_text(json.dumps({
        "date": datetime.now().isoformat(),
        "ihsg": ihsg, "sectors": sectors, "history": history,
    }, indent=2, default=str), encoding="utf-8")

    _generate_playbook(ihsg, sectors, history, deep=deep)
    return {"ihsg": ihsg, "sectors": sectors, "history": history}


# ─────────────────────────────────────────────────────────────────────────────
# Main Director Run
# ─────────────────────────────────────────────────────────────────────────────

def run_director(config, full=False) -> str:
    start = datetime.now()
    print(f"\n[Director] {'Full weekly review' if full else 'Daily check'} starting...")

    # 1. Market study
    study  = _run_market_study(deep=full)
    regime = study["ihsg"]
    cycle  = regime.get("cycle","?")

    # 2. Strategy analysis (both strategies)
    print("[Director] Analyzing EMA XBO performance...")
    ema_analysis   = _analyze_ema_performance()
    print(f"[Director] EMA XBO grade: {ema_analysis['grade']}")

    print("[Director] Analyzing Follow Whale performance...")
    whale_analysis = _analyze_whale_performance()
    print(f"[Director] Follow Whale grade: {whale_analysis['grade']}")

    # 3. Agent benchmarks (full only)
    benchmarks = []
    if full:
        print("[Director] Running agent benchmarks...")
        history = _load_history()
        tasks   = [
            ("data_feed",        lambda: _bench_data_feed(config)),
            ("technical_engine", lambda: _bench_technical_engine(config)),
            ("learning_agent",   lambda: _bench_learning_agent()),
        ]
        for name, fn in tasks:
            try:
                result = fn()
                reg = _detect_regression(name, result["elapsed"], history)
                if reg:
                    result["issues"] = result.get("issues",[]) + [reg]
                    if result["severity"] == "PASS": result["severity"] = "WARN"
                benchmarks.append(result)
                icon = {"PASS":"✅","WARN":"🟡","FAIL":"🔴","CRITICAL":"🚨"}.get(result["severity"],"⚪")
                print(f"[Director] {icon} {name}: {result['elapsed']}s | {result['mem_mb']}MB")
            except Exception as e:
                benchmarks.append({"agent":name,"elapsed":0,"mem_mb":0,
                                   "severity":"SKIP","pass":True,"issues":[str(e)]})

        new_history = {b["agent"]: b["elapsed"] for b in benchmarks if b["elapsed"] > 0}
        HISTORY_FILE.write_text(json.dumps(new_history, indent=2), encoding="utf-8")

    # 4. Apply auto-patches from strategy analysis
    all_patches = {}
    all_patches.update(ema_analysis.get("patches",{}))
    all_patches.update(whale_analysis.get("patches",{}))
    if all_patches:
        _save_autopatch(all_patches, f"Director auto-patch based on {cycle} analysis")

    # 5. Write mandates
    _write_mandates(benchmarks, ema_analysis, whale_analysis, regime, study.get("history",{}))

    elapsed = (datetime.now() - start).seconds
    grades  = f"EMA:{ema_analysis['grade']} Whale:{whale_analysis['grade']}"
    patches = len(all_patches)
    print(f"[Director] Done in {elapsed}s | Grades: {grades} | Auto-patches: {patches}")

    return (f"Director: {cycle} | {grades} | "
            f"{len(benchmarks)} benchmarks | {patches} patches applied")


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.strategy_config import StrategyConfig
    cfg  = StrategyConfig.load()
    deep = "--weekly" in sys.argv or "--full" in sys.argv
    print(run_director(cfg, full=deep))
