"""
Simple Trading V6 — Exit Engine V4 (Institutional Grade)
=========================================================
UPGRADE V4:

Changes from V3:
  • Typed accessors (_f) — eliminates Pylance implicit-Any
  • ExitSignal extended: reason_code for programmatic filtering
  • ExitEngine.evaluate():
    - Vol collapse: require held_days >= 3 AND close > entry (prevent false alarm)
    - Time stop: threshold raised to 2.5× (not 2×) — IDX often slow starters
    - SL hit: explicit check moved before ATR trail (priority ordering)
    - All bare-except → logged handlers
  • calc_position_size: no logic change, typed + lot_size configurable
  • REGIME_SIZE_PCT: added BULL_STRONG tier (1.25× for strong uptrend)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, List

import pandas as pd

logger = logging.getLogger(__name__)


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# EXIT SIGNAL
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ExitSignal:
    ticker:        str
    exit_type:     str   # TRAIL_HIT / EMA_BREAK / TIME_STOP / VOL_COLLAPSE / TP_HIT / SL_HIT
    urgency:       str   # CRITICAL / WARNING / INFO
    current_price: float
    trigger_price: float
    message:       str
    action:        str   # EXIT_NOW / TIGHTEN_SL / MOVE_TO_BE / MONITOR
    reason_code:   str = ""   # V4 NEW — for programmatic filtering / alerting


# ─────────────────────────────────────────────────────────────────────────────
# EXIT ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class ExitEngine:
    """
    Evaluates open positions for exit signals.
    All signals are ALERTS only — no automatic execution.
    """

    def evaluate(
        self,
        ticker:           str,
        entry_price:      float,
        entry_date:       str,
        sl_price:         float,
        tp1_price:        float,
        tp2_price:        float,
        df:               pd.DataFrame,
        atr14:            float,
        holding_days_est: int = 10,
    ) -> List[ExitSignal]:

        signals: List[ExitSignal] = []

        if df is None or len(df) < 5:
            return signals

        try:
            close     = df["Close"]
            volume    = df["Volume"]
            high      = df["High"]

            last_close = _f(close.iloc[-1])
            last_vol   = _f(volume.iloc[-1])
            vol_ma20   = _f(volume.rolling(20).mean().iloc[-1])
            ema13      = _f(close.ewm(span=13, adjust=False).mean().iloc[-1])

            # ── Holding days ──────────────────────────────────────────────────
            try:
                from datetime import date as _dt_date
                _entry_d  = pd.to_datetime(entry_date).date()
                held_days = (_dt_date.today() - _entry_d).days
            except Exception:
                held_days = 0

            gain_pct = (last_close - entry_price) / entry_price * 100 if entry_price > 0 else 0.0

            # ── Priority 1: SL HIT (check first — unconditional exit) ─────────
            if last_close <= sl_price:
                signals.append(ExitSignal(
                    ticker        = ticker,
                    exit_type     = "SL_HIT",
                    urgency       = "CRITICAL",
                    current_price = last_close,
                    trigger_price = sl_price,
                    message       = f"SL Rp{sl_price:,.0f} tertembus. Exit tanpa kompromi.",
                    action        = "EXIT_NOW",
                    reason_code   = "SL_BREACH",
                ))

            # ── Priority 2: TP hits ───────────────────────────────────────────
            if last_close >= tp2_price:
                signals.append(ExitSignal(
                    ticker        = ticker,
                    exit_type     = "TP_HIT",
                    urgency       = "INFO",
                    current_price = last_close,
                    trigger_price = tp2_price,
                    message       = f"TP2 Rp{tp2_price:,.0f} tercapai. Trailing SL 1×ATR (Rp{last_close - atr14:,.0f}).",
                    action        = "TIGHTEN_SL",
                    reason_code   = "TP2_HIT",
                ))
            elif last_close >= tp1_price:
                signals.append(ExitSignal(
                    ticker        = ticker,
                    exit_type     = "TP_HIT",
                    urgency       = "INFO",
                    current_price = last_close,
                    trigger_price = tp1_price,
                    message       = f"TP1 Rp{tp1_price:,.0f} tercapai. Geser SL ke entry (breakeven). Hold untuk TP2.",
                    action        = "MOVE_TO_BE",
                    reason_code   = "TP1_HIT",
                ))

            # ── Priority 3: EMA13 Breakdown ───────────────────────────────────
            ema_exit = round(ema13 * 0.98, 0)
            if last_close < ema_exit:
                signals.append(ExitSignal(
                    ticker        = ticker,
                    exit_type     = "EMA_BREAK",
                    urgency       = "CRITICAL",
                    current_price = last_close,
                    trigger_price = ema_exit,
                    message       = f"Close Rp{last_close:,.0f} < EMA13×0.98 (Rp{ema_exit:,.0f}). Trend structure rusak.",
                    action        = "EXIT_NOW",
                    reason_code   = "EMA_BREAKDOWN",
                ))

            # ── Priority 4: ATR Trailing Stop ─────────────────────────────────
            # FIX 8.7.5: peak diambil sejak entry_date, bukan 60 candle blind
            # Sebelumnya high.iloc[-60:].max() bisa mencakup high historis sebelum posisi dibuka
            # → trail_sl > entry_price → TRAIL_HIT CRITICAL false positive untuk posisi baru
            try:
                _entry_ts  = pd.to_datetime(entry_date)
                _high_since = high[df.index >= _entry_ts]
                peak_price  = _f(_high_since.max()) if not _high_since.empty else last_close
            except Exception:
                peak_price  = _f(high.iloc[-60:].max()) if len(high) >= 60 else _f(high.max())
            trail_sl   = round(peak_price - 2.0 * atr14, 0)

            if last_close < trail_sl and gain_pct < 5.0:
                signals.append(ExitSignal(
                    ticker        = ticker,
                    exit_type     = "TRAIL_HIT",
                    urgency       = "CRITICAL",
                    current_price = last_close,
                    trigger_price = trail_sl,
                    message       = f"Trailing SL Rp{trail_sl:,.0f} tertembus. Peak={peak_price:,.0f}, 2×ATR={atr14*2:,.0f}.",
                    action        = "EXIT_NOW",
                    reason_code   = "TRAIL_BREACH",
                ))

            # ── Priority 5: Time Stop ─────────────────────────────────────────
            # V4: threshold raised 2× → 2.5× (IDX can be slow, patience matters)
            max_hold = int(holding_days_est * 2.5)
            if held_days > max_hold and gain_pct < 3.0:
                signals.append(ExitSignal(
                    ticker        = ticker,
                    exit_type     = "TIME_STOP",
                    urgency       = "WARNING",
                    current_price = last_close,
                    trigger_price = entry_price,
                    message       = (f"Sudah {held_days} hari (est {holding_days_est}d×2.5), "
                                     f"gain hanya {gain_pct:+.1f}%. Modal bisa dialokasikan ulang."),
                    action        = "MONITOR",
                    reason_code   = "TIME_STOP",
                ))

            # ── Priority 6: Volume Collapse ───────────────────────────────────
            # V4: require held >= 3 AND profitable — prevents day-1 false alarms
            if (vol_ma20 > 0
                    and last_vol / vol_ma20 < 0.5
                    and held_days >= 3
                    and gain_pct > 0):
                signals.append(ExitSignal(
                    ticker        = ticker,
                    exit_type     = "VOL_COLLAPSE",
                    urgency       = "WARNING",
                    current_price = last_close,
                    trigger_price = last_close,
                    message       = (f"Volume turun ke {last_vol/vol_ma20:.1f}× MA20 (hari {held_days}). "
                                     f"Interest memudar. Pertimbangkan partial exit atau perketat SL."),
                    action        = "TIGHTEN_SL",
                    reason_code   = "VOL_COLLAPSE",
                ))

        except Exception as exc:
            logger.debug(f"[ExitEngine] {ticker}: {exc}")

        return signals


# ─────────────────────────────────────────────────────────────────────────────
# POSITION SIZING  (V4 — typed, lot_size configurable)
# ─────────────────────────────────────────────────────────────────────────────

REGIME_SIZE_PCT: dict[str, float] = {
    "BULL_STRONG":       1.25,   # V4 NEW — for very strong trend confirmation
    "BULL_TREND":        1.00,
    "BULL_CONSOLIDATION":0.75,
    "TRANSITION":        0.50,
    "BEAR_CONSOLIDATION":0.25,
    "BEAR_TREND":        0.00,   # FULL CASH
    "UNKNOWN":           0.50,
}


def calc_position_size(
    portfolio_value:  float,
    entry_price:      float,
    sl_price:         float,
    regime:           str   = "UNKNOWN",
    risk_per_trade:   float = 0.02,
    sector_exposure:  float = 0.00,
    max_sector_pct:   float = 0.30,
    lot_size:         int   = 100,          # V4: IDX lot = 100 shares
) -> dict:
    """
    Kelly-lite position sizing, regime-adjusted, sector-capped.
    Rounds to nearest lot (100 shares by default for IDX).
    """
    if sl_price >= entry_price or entry_price <= 0:
        return {
            "shares": 0, "value": 0, "risk_value": 0, "size_pct": 0,
            "note": "Invalid SL/entry",
        }

    regime_mult = REGIME_SIZE_PCT.get(regime, 0.5)

    if regime_mult == 0:
        return {
            "shares": 0, "value": 0, "risk_value": 0, "size_pct": 0,
            "note": "BEAR TREND — FULL CASH. Tidak ada posisi.",
        }

    risk_per_share  = entry_price - sl_price
    max_risk_value  = portfolio_value * risk_per_trade * regime_mult
    raw_shares      = max_risk_value / risk_per_share
    raw_value       = raw_shares * entry_price

    remaining_sector = max(0.0, (max_sector_pct - sector_exposure) * portfolio_value)
    capped_value     = min(raw_value, remaining_sector)
    note             = (
        f"Sector cap {max_sector_pct*100:.0f}% → size dikurangi"
        if capped_value < raw_value
        else f"Regime {regime} ({regime_mult*100:.0f}% size)"
    )

    final_shares = int(capped_value / entry_price / lot_size) * lot_size
    final_value  = final_shares * entry_price
    final_risk   = final_shares * risk_per_share
    size_pct     = final_value / portfolio_value * 100 if portfolio_value > 0 else 0.0

    return {
        "shares":     final_shares,
        "value":      round(final_value, 0),
        "risk_value": round(final_risk, 0),
        "size_pct":   round(size_pct, 1),
        "note":       note,
    }
