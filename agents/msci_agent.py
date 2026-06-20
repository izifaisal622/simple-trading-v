"""
Simple Trading V9 — MSCI Rebalancing Agent
==========================================
Detects active MSCI/IDX index rebalancing windows dan cross-references
dengan whale accumulation signals untuk menghasilkan HIGH CONVICTION alerts.

Logic inti:
  Tanggal efektif MSCI DIKETAHUI jauh hari sebelumnya.
  Index fund HARUS membeli di atau sebelum tanggal efektif.
  → Sinyal whale accumulation di MSCI candidate selama pre-event window
    adalah kombinasi PALING HIGH CONVICTION dalam sistem ini.

Flow:
  Calendar check → Active window? → Cross MSCI candidates × whale results
  × EMA signal → Score → Alert → Save ke logs/msci_alerts.json
"""

import json
import logging
from datetime import date
from pathlib import Path

logger   = logging.getLogger(__name__)
LOGS_DIR = Path(__file__).parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)
ALERTS_FILE  = LOGS_DIR / "msci_alerts.json"
RESULTS_FILE = LOGS_DIR / "daily_results.json"

# ─────────────────────────────────────────────────────────────────────────────
# CALENDAR — update setiap MSCI announcement (Mei & November)
# Sumber: msci.com → Index Rebalancing → Semi-Annual Index Review
#
# Format tiap event: (event_id, index_name, announce_date, effective_date, type)
#
# Aturan tanggal:
#   announce  = Kamis pertama Mei / November (biasanya 1-2 minggu setelah review)
#   effective = Jumat terakhir Mei / November (closing price)
# ─────────────────────────────────────────────────────────────────────────────

MSCI_CALENDAR = [
    # MSCI Semi-Annual Standard Index Review
    ("2026_MAY",  "MSCI_INDONESIA", "2026-05-08", "2026-05-29", "MSCI_SEMI"),
    ("2026_NOV",  "MSCI_INDONESIA", "2026-11-06", "2026-11-28", "MSCI_SEMI"),
    ("2027_MAY",  "MSCI_INDONESIA", "2027-05-13", "2027-05-28", "MSCI_SEMI"),
    ("2027_NOV",  "MSCI_INDONESIA", "2027-11-05", "2027-11-26", "MSCI_SEMI"),
]

# IDX30/LQ45 — Quarterly rebalancing (Feb/Mei/Agu/Nov)
# Effective: hari pertama bulan berikutnya setelah pengumuman BEI
IDX_REBAL_CALENDAR = [
    ("2026_LQ45_Q2", "LQ45_IDX30", "2026-04-17", "2026-05-01", "IDX_QUARTERLY"),
    ("2026_LQ45_Q3", "LQ45_IDX30", "2026-07-17", "2026-08-03", "IDX_QUARTERLY"),
    ("2026_LQ45_Q4", "LQ45_IDX30", "2026-10-16", "2026-11-02", "IDX_QUARTERLY"),
    ("2027_LQ45_Q1", "LQ45_IDX30", "2027-01-15", "2027-02-01", "IDX_QUARTERLY"),
    ("2027_LQ45_Q2", "LQ45_IDX30", "2027-04-16", "2027-05-03", "IDX_QUARTERLY"),
]

ALL_EVENTS = MSCI_CALENDAR + IDX_REBAL_CALENDAR


# ─────────────────────────────────────────────────────────────────────────────
# Core helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_active_events(today: date = None) -> list:
    """
    Return semua rebalancing events yang aktif hari ini.
    Aktif = hari ini antara announce_date dan effective_date (inklusif).
    """
    today = today or date.today()
    active = []

    for event_id, index, ann_str, eff_str, etype in ALL_EVENTS:
        ann = date.fromisoformat(ann_str)
        eff = date.fromisoformat(eff_str)

        if ann <= today <= eff:
            window_days = max((eff - ann).days, 1)
            t_minus     = (eff - today).days
            t_since_ann = (today - ann).days

            phase = (
                "POST_EVENT" if t_minus < 0  else
                "CRITICAL"   if t_minus <= 3 else
                "ACTIVE"     if t_minus <= 10 else
                "EARLY"
            )

            active.append({
                "event_id":       event_id,
                "index":          index,
                "type":           etype,
                "announce_date":  ann_str,
                "effective_date": eff_str,
                "t_minus":        t_minus,
                "t_since_ann":    t_since_ann,
                "window_days":    window_days,
                "window_pct":     round(t_since_ann / window_days * 100, 1),
                "phase":          phase,
                "is_msci":        "MSCI" in index,
                "is_idx":         "LQ45" in index or "IDX30" in index,
            })

    return sorted(active, key=lambda x: x["t_minus"])


def get_next_event(today: date = None) -> dict | None:
    """Return event berikutnya yang belum aktif (untuk preview)."""
    today = today or date.today()
    upcoming = []

    for event_id, index, ann_str, eff_str, etype in ALL_EVENTS:
        ann = date.fromisoformat(ann_str)
        eff = date.fromisoformat(eff_str)

        if ann > today:
            days_until_ann = (ann - today).days
            upcoming.append({
                "event_id":      event_id,
                "index":         index,
                "type":          etype,
                "announce_date": ann_str,
                "effective_date":eff_str,
                "days_until_announce": days_until_ann,
                "days_until_effective": (eff - today).days,
            })

    return min(upcoming, key=lambda x: x["days_until_announce"]) if upcoming else None


# ─────────────────────────────────────────────────────────────────────────────
# Cross-reference MSCI candidates × whale + EMA signals
# ─────────────────────────────────────────────────────────────────────────────

def _score_alert(whale_r: dict, ema_r: dict | None, event: dict) -> tuple[int, list]:
    """
    Hitung MSCI conviction score (0–12) dan daftar alasan.

    Komponen:
      Whale quality  : 0–4
      Activity type  : 0–2
      T-minus window : 0–2  (optimal window = T-5 to T-15)
      EMA signal     : 0–2
      Volume anomaly : 0–1
      EMA regime     : 0–1  (FULL/SELECTIVE = +1)
    """
    score   = 0
    reasons = []

    # ── Whale quality ──────────────────────────────────────────────────────
    wq = whale_r.get("whale_quality", "")
    wc = whale_r.get("conviction", 0)
    if wq == "SMART":
        score += 4; reasons.append("SMART whale confirmed")
    elif wq == "LIKELY_SMART":
        score += 3; reasons.append("Likely smart money")
    elif wc >= 7:
        score += 2; reasons.append(f"Conviction {wc}/10")
    elif wc >= 5:
        score += 1; reasons.append(f"Conviction {wc}/10")

    # ── Activity type ──────────────────────────────────────────────────────
    act = whale_r.get("activity_type", "")
    if act == "AKUMULASI":
        score += 2; reasons.append("Akumulasi terdeteksi")
    elif act == "PENGERINGAN":
        score += 2; reasons.append("Pengeringan — barang pindah ke smart money")
    elif act in ("RECOVERY_EARLY", "AT_FLOOR"):
        score += 1; reasons.append(f"{act} — potensi reversal")

    # ── T-minus window bonus ───────────────────────────────────────────────
    t = event["t_minus"]
    if 5 <= t <= 15:
        score += 2; reasons.append(f"Optimal window T-{t} hari")
    elif t < 5:
        score += 1; reasons.append(f"Critical window T-{t} — last chance")
    elif 15 < t <= 21:
        score += 1; reasons.append(f"Early window T-{t} hari")

    # ── EMA signal ────────────────────────────────────────────────────────
    if ema_r:
        sig  = ema_r.get("signal", "")
        escore = ema_r.get("score", 0)
        regime = ema_r.get("regime_tag", "")
        if sig == "BREAKOUT":
            score += 2; reasons.append("EMA BREAKOUT confirmed")
        elif sig == "WATCHLIST":
            score += 2; reasons.append("EMA WATCHLIST — setup ready")
        elif sig == "CORRECTING":
            score += 1; reasons.append(f"EMA CORRECTING (score {escore}/7)")
        if regime in ("FULL", "SELECTIVE"):
            score += 1; reasons.append(f"Regime {regime}")

    # ── Volume anomaly ────────────────────────────────────────────────────
    ff_vol = whale_r.get("ff_adj_vol_ratio", 0)
    if ff_vol >= 2.0:
        score += 1; reasons.append(f"Vol {ff_vol:.1f}× free-float adjusted")

    return score, reasons


def scan_candidates(
    whale_results: list,
    ema_results:   list,
    active_events: list,
    min_score:     int = 4,
) -> list:
    """
    Cross-reference MSCI/IDX30 candidates dengan whale + EMA results.
    Returns list of alert dicts, sorted by msci_conviction desc.
    """
    from core.data_feed import MSCI_CANDIDATES, IDX30_LQ45_CANDIDATES

    msci_set = set(t.upper() for t in MSCI_CANDIDATES)
    idx_set  = set(t.upper() for t in IDX30_LQ45_CANDIDATES)

    # Index whale results by ticker for O(1) lookup
    whale_by_ticker = {
        r.get("ticker","").replace(".JK","").upper(): r
        for r in whale_results
    }
    ema_by_ticker = {
        r.get("ticker","").replace(".JK","").upper(): r
        for r in ema_results
    }

    alerts = []

    for event in active_events:
        # Determine candidate set for this event
        if event["is_msci"]:
            candidates = msci_set
        else:
            candidates = idx_set

        for ticker in candidates:
            whale_r = whale_by_ticker.get(ticker)
            ema_r   = ema_by_ticker.get(ticker)

            # Need at least whale data to score
            if whale_r is None:
                continue

            # Skip distribution / sell-off
            act = whale_r.get("activity_type", "")
            if act in ("DISTRIBUSI", "SELL_OFF", "DEFEND"):
                continue

            conv_score, reasons = _score_alert(whale_r, ema_r, event)

            if conv_score < min_score:
                continue

            # Alert level
            level = (
                "HIGH_CONVICTION" if conv_score >= 8 else
                "MEDIUM"          if conv_score >= 5 else
                "WATCH"
            )

            # Entry viability
            t = event["t_minus"]
            if t <= 1:
                entry_note = "⛔ T-1 atau sudah lewat — terlambat untuk entry baru"
            elif t <= 3:
                entry_note = "⚠ T-3 — harga mungkin sudah run, sizing ketat"
            elif t <= 10:
                entry_note = f"✅ T-{t} — window optimal, entry masih make sense"
            else:
                entry_note = f"👁 T-{t} — early window, bisa accumulate bertahap"

            alerts.append({
                "ticker":           ticker,
                "event_id":         event["event_id"],
                "index":            event["index"],
                "event_type":       event["type"],
                "announce_date":    event["announce_date"],
                "effective_date":   event["effective_date"],
                "t_minus":          t,
                "phase":            event["phase"],
                "alert_level":      level,
                "msci_conviction":  conv_score,
                "whale_quality":    whale_r.get("whale_quality", ""),
                "whale_conviction": whale_r.get("conviction", 0),
                "activity_type":    act,
                "ff_vol_ratio":     round(whale_r.get("ff_adj_vol_ratio", 0), 2),
                "ema_signal":       ema_r.get("signal", "NO_EMA") if ema_r else "NO_EMA",
                "ema_score":        ema_r.get("score", 0) if ema_r else 0,
                "regime_tag":       ema_r.get("regime_tag", "") if ema_r else "",
                "reasons":          reasons,
                "entry_note":       entry_note,
                "close":            whale_r.get("close", 0),
                "floor_price":      whale_r.get("floor_price", 0),
                "is_msci":          event["is_msci"],
            })

    # Sort: HIGH_CONVICTION dulu, lalu by conviction score
    alerts.sort(key=lambda x: (
        0 if x["alert_level"] == "HIGH_CONVICTION" else
        1 if x["alert_level"] == "MEDIUM" else 2,
        -x["msci_conviction"],
        x["t_minus"],
    ))

    return alerts


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_msci_scan(cfg=None) -> str:
    """
    Main entry point dipanggil oleh orchestrator.
    Loads whale + EMA results, runs scan, saves alerts.
    Returns summary string.
    """

    today         = date.today()
    active_events = get_active_events(today)
    next_event    = get_next_event(today)

    # Load existing scan results
    whale_results = []
    ema_results   = []
    try:
        data          = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
        whale_results = data.get("whale_results", [])
        ema_results   = data.get("ema_results",   [])
    except Exception as e:
        logger.warning(f"[MSCI] Cannot load scan results: {e}")

    if not active_events:
        # No active window — just save status and return
        status = {
            "date":          today.isoformat(),
            "active_events": [],
            "alerts":        [],
            "next_event":    next_event,
        }
        ALERTS_FILE.write_text(json.dumps(status, indent=2), encoding="utf-8")

        if next_event:
            d = next_event["days_until_announce"]
            return (f"[MSCI] No active window. "
                    f"Next: {next_event['index']} announce in {d} days "
                    f"({next_event['announce_date']})")
        return "[MSCI] No active rebalancing event."

    # Active window — run cross-reference
    print(f"\n[MSCI] Active events: "
          f"{', '.join(e['index'] + ' T-' + str(e['t_minus']) for e in active_events)}")

    alerts = scan_candidates(whale_results, ema_results, active_events)

    # Save to file
    status = {
        "date":          today.isoformat(),
        "active_events": active_events,
        "alerts":        alerts,
        "next_event":    next_event,
        "summary": {
            "total":           len(alerts),
            "high_conviction": sum(1 for a in alerts if a["alert_level"] == "HIGH_CONVICTION"),
            "medium":          sum(1 for a in alerts if a["alert_level"] == "MEDIUM"),
            "watch":           sum(1 for a in alerts if a["alert_level"] == "WATCH"),
        },
    }
    ALERTS_FILE.write_text(json.dumps(status, indent=2, default=str), encoding="utf-8")

    # Console output
    high = [a for a in alerts if a["alert_level"] == "HIGH_CONVICTION"]
    med  = [a for a in alerts if a["alert_level"] == "MEDIUM"]

    print(f"[MSCI] {len(alerts)} alerts | "
          f"★ HIGH: {len(high)} | ◎ MED: {len(med)}")

    if high:
        tickers_str = ", ".join(f"{a['ticker']} ({a['index']} T-{a['t_minus']})" for a in high[:5])
        print(f"[MSCI] HIGH CONVICTION: {tickers_str}")

    return (f"MSCI: {len(active_events)} active events | "
            f"{len(alerts)} alerts | "
            f"HIGH: {len(high)} — "
            + (", ".join(a['ticker'] for a in high[:3]) if high else "none"))


def get_msci_status() -> dict:
    """
    Load dan return status MSCI terbaru dari file.
    Dipanggil oleh UI (gate.py, 1_EMA_XBO.py).
    """
    try:
        if ALERTS_FILE.exists():
            return json.loads(ALERTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"active_events": [], "alerts": [], "next_event": None}


def get_ticker_msci_alert(ticker: str) -> dict | None:
    """
    Return MSCI alert untuk ticker spesifik (untuk badge di EMA_XBO).
    """
    status = get_msci_status()
    t = ticker.upper().replace(".JK", "")
    return next((a for a in status.get("alerts", []) if a["ticker"] == t), None)
