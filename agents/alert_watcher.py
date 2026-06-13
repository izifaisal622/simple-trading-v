"""
Simple Trading V6 — Alert Watcher Agent V2 (Institutional)
============================================================
UPGRADE V2:
  • Removed unused Optional import
  • check_alerts: ema_score display updated 7→8
  • urgency formula updated: vp_score added as factor
  • STRONG_BREAKOUT gets urgency boost (+10)
  • market hours logic unchanged (correct)
"""

import json
import logging
from datetime import datetime, time as _time
from pathlib import Path

import pytz

logger   = logging.getLogger(__name__)
LOGS_DIR = Path(__file__).parent.parent / "logs"

# Floor estimation — lazy import to avoid circular dep
def _get_floor_for_ticker(ticker: str) -> float:
    """Fetch floor price on-demand for tickers not in whale_results."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from core.data_feed import DataFeed
        from agents.whale_scanner import estimate_floor_price
        df = DataFeed("1d", "6mo")
        data = df.fetch(ticker)
        if data is None or len(data) < 20:
            return 0.0
        close = data["Close"].dropna()
        vol   = data["Volume"].dropna()
        low   = data["Low"].dropna()
        result = estimate_floor_price(close, vol, low)
        return float(result.get("floor_price", 0))
    except Exception:
        return 0.0

DEFAULT_EMA_SCORE_MIN  = 5
DEFAULT_WHALE_CONV_MIN = 7
DEFAULT_FLOOR_DIST_PCT = 10.0

_WIB = pytz.timezone("Asia/Jakarta")

MARKET_SESSIONS = [
    (_time(8, 30),  _time(12, 0)),
    (_time(13, 30), _time(16, 15)),
]


def is_market_open(now=None) -> tuple:
    if now is None:
        now = datetime.now(_WIB)
    weekday = now.weekday()
    if weekday >= 5:
        day_name  = "Sabtu" if weekday == 5 else "Minggu"
        return False, f"Weekend ({day_name})", "Senin 08:30 WIB"
    t = now.time()
    for start, end in MARKET_SESSIONS:
        if start <= t <= end:
            if t < _time(9, 0):
                return True, "PRE-OPENING (08:30–09:00)", ""
            elif t < _time(12, 0):
                return True, "SESI 1 (09:00–12:00)", ""
            elif t < _time(14, 0):
                return True, "SESI 2 (13:30–16:00)", ""
            else:
                return True, "PRE-CLOSING (16:00–16:15)", ""
    if t < _time(8, 30):
        next_open = "Hari ini 08:30 WIB"
    elif _time(12, 0) < t < _time(13, 30):
        next_open = "Sesi 2 — 13:30 WIB"
    else:
        next_day  = "Besok" if weekday < 4 else "Senin"
        next_open = f"{next_day} 08:30 WIB"
    return False, "CLOSED", next_open


def check_alerts(
    ema_score_min:  int   = DEFAULT_EMA_SCORE_MIN,
    whale_conv_min: int   = DEFAULT_WHALE_CONV_MIN,
    floor_dist_pct: float = DEFAULT_FLOOR_DIST_PCT,
) -> dict:
    try:
        data = json.loads(
            (LOGS_DIR / "daily_results.json").read_text(encoding="utf-8")
        )
    except Exception as exc:
        logger.warning(f"[AlertWatcher] Cannot load daily_results: {exc}")
        return {"error": str(exc), "alerts": [], "watchlist": []}

    ema_results   = data.get("ema_results",   [])
    whale_results = data.get("whale_results", [])
    regime        = data.get("regime", {}).get("cycle", "UNKNOWN")
    scan_date     = data.get("scan_date", "—")

    whale_by_ticker: dict = {}
    for w in whale_results:
        t = w.get("ticker", "").replace(".JK", "").upper()
        whale_by_ticker[t] = w

    ema_by_ticker: dict = {}
    for e in ema_results:
        t = e.get("ticker", "").replace(".JK", "").upper()
        ema_by_ticker[t] = e

    alerts:    list = []
    watchlist: list = []
    all_tickers = set(ema_by_ticker) | set(whale_by_ticker)

    for ticker in all_tickers:
        ema_r   = ema_by_ticker.get(ticker)
        whale_r = whale_by_ticker.get(ticker)

        ema_score    = ema_r.get("score", 0)       if ema_r else 0
        ema_close    = ema_r.get("close", 0)        if ema_r else 0
        ema_signal   = ema_r.get("signal", "")      if ema_r else ""
        ema_regime   = ema_r.get("regime_tag", "")  if ema_r else ""
        vp_score     = ema_r.get("vp_score", 0)     if ema_r else 0
        vp_zone      = ema_r.get("vp_entry_zone", "") if ema_r else ""

        whale_floor  = whale_r.get("floor_price", 0) if whale_r else 0
        close_price  = ema_close or (whale_r.get("close", 0) if whale_r else 0)

        # Fallback: estimate floor dari data live jika whale scan belum dijalankan
        if whale_floor <= 0 and close_price > 0:
            whale_floor = _get_floor_for_ticker(ticker)

        floor_dist = 999.0
        if whale_floor > 0 and close_price > 0:
            floor_dist = abs((close_price - whale_floor) / whale_floor * 100)

        near_floor = floor_dist <= floor_dist_pct

        ema_cond    = (ema_score >= ema_score_min) or near_floor
        ema_reasons = []
        if ema_score >= ema_score_min:
            ema_reasons.append(f"EMA score {ema_score}/8")
        if near_floor and ema_r:
            ema_reasons.append(f"Harga ±{floor_dist:.1f}% dari floor")

        conviction    = whale_r.get("conviction", 0)      if whale_r else 0
        whale_quality = whale_r.get("whale_quality", "—") if whale_r else "—"
        activity_type = whale_r.get("activity_type", "")  if whale_r else ""
        entry_zone    = whale_r.get("entry_zone", "")      if whale_r else ""
        pengeringan   = whale_r.get("pengeringan_detected", False) if whale_r else False

        whale_cond    = (conviction >= whale_conv_min) or near_floor
        whale_reasons = []
        if conviction >= whale_conv_min:
            whale_reasons.append(f"Conviction {conviction}/10")
        if near_floor and whale_r:
            whale_reasons.append(f"Harga ±{floor_dist:.1f}% dari floor")

        if not ema_r and not whale_r:
            continue
        if ema_signal == "NONE" and ema_score == 0 and not whale_r:
            continue

        if ema_cond and whale_cond and ema_r and whale_r:
            level = "ALERT"
        elif (ema_cond and ema_r) or (whale_cond and whale_r):
            level = "WATCH"
        else:
            continue

        urgency = (
            (ema_score * 3)
            + (conviction * 2)
            + (10 if near_floor else 0)
            + (5  if pengeringan else 0)
            + (8  if whale_quality in ("SMART", "LIKELY_SMART") else 0)
            + (10 if ema_signal == "STRONG_BREAKOUT" else 0)  # V2 NEW
            + (vp_score * 3)                                   # V2 NEW: VP boost
        )

        entry = {
            "ticker":         ticker,
            "level":          level,
            "urgency":        urgency,
            "close":          round(close_price, 0),
            "floor_price":    round(whale_floor, 0),
            "floor_dist_pct": round(floor_dist, 1),
            "near_floor":     near_floor,
            "ema_score":      ema_score,
            "ema_signal":     ema_signal,
            "ema_regime":     ema_regime,
            "vp_score":       vp_score,
            "vp_zone":        vp_zone,
            "ema_cond":       ema_cond,
            "ema_reasons":    ema_reasons,
            "conviction":     conviction,
            "whale_quality":  whale_quality,
            "activity_type":  activity_type,
            "entry_zone":     entry_zone,
            "pengeringan":    pengeringan,
            "whale_cond":     whale_cond,
            "whale_reasons":  whale_reasons,
            "regime":         ema_regime or regime,
        }

        if level == "ALERT":
            alerts.append(entry)
        else:
            watchlist.append(entry)

    alerts.sort(key=lambda x: -x["urgency"])
    watchlist.sort(key=lambda x: -x["urgency"])

    open_now, session_label, next_open = is_market_open()

    return {
        "timestamp":     datetime.now().strftime("%H:%M:%S"),
        "scan_date":     scan_date,
        "regime":        regime,
        "market_open":   open_now,
        "session_label": session_label,
        "next_open":     next_open,
        "alerts":        alerts[:20] if open_now else [],
        "watchlist":     watchlist[:30] if open_now else [],
        "stats": {
            "ema_total":   len(ema_results),
            "whale_total": len(whale_results),
            "alert_count": len(alerts),
            "watch_count": len(watchlist),
        },
    }


def get_alert_summary(result: dict) -> str:
    alerts = result.get("alerts", [])
    if not alerts:
        return "Tidak ada alert."
    tickers = ", ".join(a["ticker"] for a in alerts[:5])
    return (f"{len(alerts)} ALERT: {tickers}" + (" ..." if len(alerts) > 5 else ""))
