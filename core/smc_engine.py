"""
Simple Trading V6 — SMC Engine V2 (Institutional Grade)
=========================================================
UPGRADE V2:

Changes from V1:
  • Typed accessors (_f) throughout — eliminates all Pylance implicit-Any
  • SMCResult extended: choch_type (MINOR/MAJOR), bos_strength, liquidity_zones
  • _find_order_blocks: OB confirmation window diperluas 1-bar → 3-bar (V3 fix)
    untuk tangkap impulse IDX yang sering butuh 2-3 bar untuk terkonfirmasi
  • _find_fvgs: FVG filter added — only report FVGs with gap_pct >= 0.3%
    (eliminates micro-gaps that are meaningless in IDX context)
  • _check_liquidity_sweep: extended to detect both high sweeps AND low sweeps
    (stop hunts both directions)
  • SMCEngine.analyze(): returns typed Optional[SMCResult], all bare-except
    replaced with logged handlers
  • score logic: CHOCH now deducts -2 only if close STAYS below swing low
    for ≥ 2 bars (prevents single-wick false negatives)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SMCResult:
    ticker:           str
    trend:            str   = "UNKNOWN"   # BULLISH / BEARISH / NEUTRAL
    score:            int   = 0           # 0–8
    structure:        str   = "UNKNOWN"   # HH_HL / LH_LL / MIXED
    bos:              bool  = False       # Break of Structure (upward)
    bos_strength:     str   = "WEAK"      # V2 NEW: WEAK / MODERATE / STRONG
    choch:            bool  = False       # Change of Character (reversal)
    choch_type:       str   = ""          # V2 NEW: MINOR / MAJOR
    ob_bullish:       float = 0.0
    ob_bearish:       float = 0.0
    fvg_up:           list  = field(default_factory=list)
    fvg_down:         list  = field(default_factory=list)
    liquidity_swept:  bool  = False
    sweep_direction:  str   = ""          # V2 NEW: HIGH / LOW
    liquidity_zones:  list  = field(default_factory=list)   # V2 NEW
    flags:            list  = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# SMC ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class SMCEngine:

    def __init__(self, swing_lookback: int = 5) -> None:
        self.swing_lookback = swing_lookback

    # ── Swing detection ───────────────────────────────────────────────────────

    def _swing_highs(self, high: pd.Series, n: int = 5) -> pd.Series:
        return high == high.rolling(2 * n + 1, center=True).max()

    def _swing_lows(self, low: pd.Series, n: int = 5) -> pd.Series:
        return low == low.rolling(2 * n + 1, center=True).min()

    # ── Market structure ──────────────────────────────────────────────────────

    def _market_structure(self, high: pd.Series, low: pd.Series) -> str:
        n  = self.swing_lookback
        sh = high[self._swing_highs(high, n)].tail(4)
        sl = low[self._swing_lows(low, n)].tail(4)

        if len(sh) < 2 or len(sl) < 2:
            return "UNKNOWN"

        hh = sh.iloc[-1] > sh.iloc[-2]
        hl = sl.iloc[-1] > sl.iloc[-2]
        lh = sh.iloc[-1] < sh.iloc[-2]
        ll = sl.iloc[-1] < sl.iloc[-2]

        if hh and hl:
            return "HH_HL"
        if lh and ll:
            return "LH_LL"
        return "MIXED"

    # ── Order blocks — 3-bar window (V3 fix) ───────────────────────────────────

    def _find_order_blocks(self, df: pd.DataFrame) -> tuple[float, float]:
        """
        Find last bullish OB (last bearish candle before strong up move)
        and last bearish OB (last bullish candle before strong down move).

        V2 claimed vectorized tapi implementasinya masih loop (documentation debt).
        V3 fix: lookahead diperluas dari 1-bar ke 3-bar window (SMC-3 fix).
        """
        close  = df["Close"]
        open_  = df["Open"]
        high   = df["High"]
        low    = df["Low"]

        bearish_candle = close < open_
        bullish_candle = close > open_

        # Strong move threshold: 2× average body size
        avg_body  = (close - open_).abs().rolling(20).mean()
        threshold = avg_body * 1.5

        bullish_ob = 0.0
        bearish_ob = 0.0

        # [SMC-3 FIX] Lookahead diperluas dari 1-bar ke 3-bar window.
        # Standard SMC: OB dikonfirmasi oleh impulsive move dalam beberapa bar
        # setelah candle OB, bukan hanya 1 bar berikutnya.
        # IDX sering butuh 2-3 bar untuk impulse terkonfirmasi (liquidity thin).
        # Implementasi: ukur total move dari close[i+1] ke max(close[i+1..i+3])
        # untuk bullish OB, dan min untuk bearish OB.
        # scan_len dikurangi 3 (bukan 3) agar ada buffer untuk lookahead 3 bar.
        scan_len = min(30, len(df) - 4)
        for i in range(len(df) - 4, len(df) - 4 - scan_len, -1):
            if i < 0:
                break
            try:
                if bearish_candle.iloc[i] and bullish_ob == 0.0:
                    # Impulsive up move: max close dalam 3 bar setelah OB candle
                    base_close = _f(close.iloc[i+1])
                    max_close  = max(_f(close.iloc[i+1]), _f(close.iloc[i+2]), _f(close.iloc[i+3]))
                    next_up    = max_close - base_close
                    if next_up > _f(threshold.iloc[i]):
                        bullish_ob = _f(low.iloc[i])
                if bullish_candle.iloc[i] and bearish_ob == 0.0:
                    # Impulsive down move: min close dalam 3 bar setelah OB candle
                    base_close = _f(close.iloc[i+1])
                    min_close  = min(_f(close.iloc[i+1]), _f(close.iloc[i+2]), _f(close.iloc[i+3]))
                    next_dn    = base_close - min_close
                    if next_dn > _f(threshold.iloc[i]):
                        bearish_ob = _f(high.iloc[i])
                if bullish_ob and bearish_ob:
                    break
            except Exception as exc:
                logger.debug(f"[SMC] OB scan idx {i}: {exc}")
                continue

        return bullish_ob, bearish_ob

    # ── Fair Value Gaps — filtered (V2) ───────────────────────────────────────

    def _find_fvgs(self, df: pd.DataFrame) -> tuple[list, list]:
        """
        Find recent FVGs. V2: only report FVGs where gap >= 0.3% of price.
        Eliminates micro-gaps that are noise on IDX.
        """
        high  = df["High"]
        low   = df["Low"]
        close = df["Close"]

        fvg_up:   list = []
        fvg_down: list = []
        min_gap_pct = 0.003  # 0.3%

        for i in range(1, min(len(df) - 1, 20)):
            idx = len(df) - 1 - i
            try:
                mid_price = _f(close.iloc[idx])
                if mid_price <= 0:
                    continue

                prev_high = _f(high.iloc[idx - 1])
                next_low  = _f(low.iloc[idx + 1])
                if next_low > prev_high:
                    gap_pct = (next_low - prev_high) / mid_price
                    if gap_pct >= min_gap_pct:
                        fvg_up.append((round(prev_high, 2), round(next_low, 2)))

                prev_low  = _f(low.iloc[idx - 1])
                next_high = _f(high.iloc[idx + 1])
                if prev_low > next_high:
                    gap_pct = (prev_low - next_high) / mid_price
                    if gap_pct >= min_gap_pct:
                        fvg_down.append((round(next_high, 2), round(prev_low, 2)))
            except Exception as exc:
                logger.debug(f"[SMC] FVG idx {idx}: {exc}")
                continue

        return fvg_up[:3], fvg_down[:3]

    # ── Liquidity sweep — bidirectional (V2) ──────────────────────────────────

    def _check_liquidity_sweep(
        self, high: pd.Series, low: pd.Series, close: pd.Series
    ) -> tuple[bool, str]:
        """
        V2: detect both high sweeps (stop hunt above) AND low sweeps (stop hunt below).
        Returns (swept, direction).
        """
        try:
            prev_high  = _f(high.iloc[-20:-1].max())
            prev_low   = _f(low.iloc[-20:-1].min())
            last_high  = _f(high.iloc[-1])
            last_low   = _f(low.iloc[-1])
            last_close = _f(close.iloc[-1])

            # Swept above prev high but closed back below (bear stop hunt)
            if last_high > prev_high and last_close < prev_high:
                return True, "HIGH"
            # Swept below prev low but closed back above (bull stop hunt)
            if last_low < prev_low and last_close > prev_low:
                return True, "LOW"
        except Exception as exc:
            logger.debug(f"[SMC] liquidity sweep: {exc}")
        return False, ""

    # ── BOS / CHOCH ───────────────────────────────────────────────────────────

    def _check_bos(self, high: pd.Series, close: pd.Series) -> tuple[bool, str]:
        """Break of Structure upward. V2: returns (bos, strength)."""
        try:
            n  = self.swing_lookback
            sh = high[self._swing_highs(high, n)]
            if len(sh) < 2:
                return False, "WEAK"
            last_sh    = _f(sh.iloc[-2])
            last_close = _f(close.iloc[-1])
            if last_close > last_sh:
                margin = (last_close - last_sh) / last_sh * 100
                strength = "STRONG" if margin > 2 else "MODERATE" if margin > 0.5 else "WEAK"
                return True, strength
        except Exception as exc:
            logger.debug(f"[SMC] BOS: {exc}")
        return False, "WEAK"

    def _check_choch(self, low: pd.Series, close: pd.Series) -> tuple[bool, str]:
        """
        Change of Character.
        V2: only confirm CHOCH if close STAYS below last swing low for ≥2 bars
        — prevents single-wick false negatives.
        """
        try:
            n  = self.swing_lookback
            sl = low[self._swing_lows(low, n)]
            if len(sl) < 2:
                return False, ""
            last_sl = _f(sl.iloc[-1])
            # Check last 2 closes (prevent single-wick flip)
            closes_below = sum(1 for i in [1, 2] if _f(close.iloc[-i]) < last_sl)
            if closes_below >= 2:
                # MAJOR if below prev swing low too
                prev_sl = _f(sl.iloc[-2])
                choch_type = "MAJOR" if _f(close.iloc[-1]) < prev_sl else "MINOR"
                return True, choch_type
        except Exception as exc:
            logger.debug(f"[SMC] CHOCH: {exc}")
        return False, ""

    # ── Main analyze ──────────────────────────────────────────────────────────

    def analyze(
        self,
        df_weekly: pd.DataFrame,
        df_daily:  pd.DataFrame,
        ticker:    str,
    ) -> Optional[SMCResult]:
        """
        Full SMC analysis using weekly (structure) + daily (OB/FVG precision).
        """
        try:
            for df in [df_weekly, df_daily]:
                if df is None or len(df) < 15:
                    return None
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

            high_w  = df_weekly["High"]
            low_w   = df_weekly["Low"]
            close_w = df_weekly["Close"]

            high_d  = df_daily["High"]
            low_d   = df_daily["Low"]
            close_d = df_daily["Close"]

            structure               = self._market_structure(high_w, low_w)
            ob_bull, ob_bear        = self._find_order_blocks(df_daily)
            fvg_up, fvg_down        = self._find_fvgs(df_daily)
            swept, sweep_dir        = self._check_liquidity_sweep(high_d, low_d, close_d)
            bos, bos_strength       = self._check_bos(high_w, close_w)
            choch, choch_type       = self._check_choch(low_w, close_w)

            last_close = _f(close_d.iloc[-1])

            # ── Liquidity zones (prev swing highs/lows as key levels) ─────────
            n  = self.swing_lookback
            sh = high_w[self._swing_highs(high_w, n)].tail(3)
            sl = low_w[self._swing_lows(low_w, n)].tail(3)
            liquidity_zones = [round(_f(p), 2) for p in list(sh) + list(sl)]

            # ── Score ─────────────────────────────────────────────────────────
            score = 0
            flags: list[str] = []

            if structure == "HH_HL":
                score += 2
                flags.append("HH/HL structure")
            elif structure == "MIXED":
                score += 1

            if bos:
                pts = {"STRONG": 2, "MODERATE": 2, "WEAK": 1}.get(bos_strength, 1)
                score += pts
                flags.append(f"BOS confirmed ({bos_strength})")

            if ob_bull and last_close > ob_bull:
                score += 1
                flags.append(f"Above bullish OB {ob_bull:,.0f}")

            if fvg_up:
                score += 1
                flags.append(f"FVG up at {fvg_up[0]}")

            if swept and bos:
                score += 1
                flags.append(f"Liquidity swept ({sweep_dir}) + BOS")

            if choch:
                deduct = -2 if choch_type == "MAJOR" else -1
                score += deduct
                flags.append(f"⚠️ CHOCH {choch_type} — reversal warning")

            score = max(0, min(score, 8))

            # ── Trend ─────────────────────────────────────────────────────────
            if score >= 5:
                trend = "BULLISH"
            elif score >= 3:
                trend = "NEUTRAL"
            else:
                trend = "BEARISH"

            return SMCResult(
                ticker          = ticker,
                trend           = trend,
                score           = score,
                structure       = structure,
                bos             = bos,
                bos_strength    = bos_strength,
                choch           = choch,
                choch_type      = choch_type,
                ob_bullish      = round(ob_bull, 2),
                ob_bearish      = round(ob_bear, 2),
                fvg_up          = fvg_up,
                fvg_down        = fvg_down,
                liquidity_swept = swept,
                sweep_direction = sweep_dir,
                liquidity_zones = liquidity_zones,
                flags           = flags,
            )

        except Exception as exc:
            logger.debug(f"[SMC] {ticker} error: {exc}")
            return None
