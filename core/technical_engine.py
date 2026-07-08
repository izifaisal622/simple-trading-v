"""
Simple Trading V9 — Technical Engine V5 (Institutional Grade)
==============================================================
UPGRADE V5 (Core Institutional):

Architecture changes:
  • Typed accessors (_f, _s) — eliminates all Pylance implicit-Any errors
  • SetupResult extended with VP fields (poc, vah, val, vp_score)
  • VolumeProfileResult dataclass — structured VP output
  • compute_volume_profile() — POC/VAH/VAL/HVN/LVN with configurable bins
  • VP scoring boost integrated into EMABreakoutEngine.analyze()
    - VP is a SCORER, not a hard gate (per design decision)
    - Entry near VAL/POC earns +1 score, breakout above VAH earns +1
  • EMABreakoutEngine improvements:
    - STRONG_BREAKOUT signal: vol >= 3× AND score >= 6 AND cross == ABOVE
    - Box detection: replaced arbitrary ATR cap with statistical percentile
    - Score cap: hard-enforced at 8 in ALL paths (no bonus overflow)
    - EMA200 guard: score awarded only when ema200_reliable == True
    - bars_held: numpy.busday_count (already in V4, kept)
  • analyze_market_structure: typed params, removed hidden EMA recompute
  • compute_mcf: typed, bear_blocked logic preserved and clarified
  • check_daily_entry: no changes needed (already clean in V4)
  • All bare-except replaced with logged handlers
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# TYPED ACCESSORS  (eliminates Pylance reportArgumentType errors)
# ─────────────────────────────────────────────────────────────────────────────

def _f(v: Any, default: float = 0.0) -> float:
    """Safe float cast."""
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _s(v: Any, default: str = "") -> str:
    """Safe str cast."""
    return str(v) if v is not None else default


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class VolumeProfileResult:
    """
    Volume Profile output — one per analysis window.

    poc  = Price Of Control   (price level with most volume)
    vah  = Value Area High    (70% of volume above this = rare)
    val  = Value Area Low     (70% of volume below this = rare)
    hvn  = High Volume Nodes  (list of price clusters, sorted desc by vol)
    lvn  = Low Volume Nodes   (price gaps / distribution holes)
    vp_score = 0..3 scoring boost for technical_engine
    """
    poc:         float
    vah:         float
    val:         float
    hvn:         list[float] = field(default_factory=list)
    lvn:         list[float] = field(default_factory=list)
    vp_score:    int         = 0
    entry_zone:  str         = "UNKNOWN"   # AT_POC / IN_VALUE / ABOVE_VAH / BELOW_VAL

    def near_poc(self, price: float, atr: float) -> bool:
        """True if price is within 0.5×ATR of POC."""
        return abs(price - self.poc) <= 0.5 * atr if atr > 0 else False

    def in_value_area(self, price: float) -> bool:
        return self.val <= price <= self.vah

    def above_vah(self, price: float) -> bool:
        return price > self.vah


@dataclass
class SetupResult:
    ticker:           str
    signal:           str   = "NONE"
    score:            int   = 0
    date:             str   = ""
    regime_tag:       str   = ""

    # Price
    close:            float = 0.0
    open_:            float = 0.0
    high:             float = 0.0
    low:              float = 0.0

    # Standard EMAs
    ema5:             float = 0.0
    ema13:            float = 0.0
    ema89:            float = 0.0
    ema200:           float = 0.0
    ema200_reliable:  bool  = True

    # Volume-weighted EMAs
    vwema13:          float = 0.0
    vwema89:          float = 0.0

    # Cross state
    cross_state:      str   = "NONE"
    bars_since_cross: int   = 0

    # Box / consolidation
    box_high:         float = 0.0
    box_low:          float = 0.0
    box_range_pct:    float = 0.0
    box_atr_multiple: float = 0.0
    bars_in_range:    int   = 0

    # Volume
    volume:           float = 0.0
    vol_ma20:         float = 0.0
    vol_ratio:        float = 0.0

    # Relative Strength vs IHSG
    rs_vs_ihsg_4w:    float = 0.0
    rs_signal:        str   = "N/A"

    # Exit framework
    atr14:            float = 0.0
    trail_stop_1atr:  float = 0.0
    trail_stop_2atr:  float = 0.0
    exit_ema_break:   float = 0.0
    holding_days_est: int   = 0

    # Risk management
    entry_price:      float = 0.0
    sl_price:         float = 0.0
    tp1_price:        float = 0.0
    tp2_price:        float = 0.0
    tp3_price:        float = 0.0
    risk_pct:         float = 0.0
    rr_ratio:         float = 0.0
    risk_sizing_ok:   bool  = True

    # SMC overlay
    smc_trend:        str   = "UNKNOWN"
    smc_score:        int   = 0

    # Volume Profile fields (V5 NEW)
    vp_poc:           float = 0.0
    vp_vah:           float = 0.0
    vp_val:           float = 0.0
    vp_score:         int   = 0
    vp_entry_zone:    str   = "UNKNOWN"

    # Pengeringan / absorption (from scanner_agent V6.4)
    pengeringan_detected: bool  = False
    absorption_score:     float = 0.0

    # IPO / data-limited flag
    data_limited:     bool  = False   # True jika bar < 89 (IPO / saham baru)
    ipo_mode:         bool  = False   # True jika bar < 30 — analisa EMA5/13 only

    # Score transparency
    score_raw:        int   = 0       # Score sebelum regime cap — potensi saham jika regime membaik
    score_capped:     bool  = False   # True jika score di-cap oleh regime (SPECULATIVE/WATCHLIST_ONLY)

    # Flags
    flags:            list  = field(default_factory=list)

    # Breakout type transparency (v9.7.0 — additive, "signal" tetap tidak berubah
    # untuk backward-compat trade_log.db, director_agent auto-tuning, alert_agent)
    # "BOX"      = breakout dari box_detected=True (thesis asli EMA_XBO)
    # "MOMENTUM" = breakout tanpa box terbentuk — new-high + volume + cross
    # ""         = signal bukan (STRONG_)BREAKOUT, tidak relevan
    breakout_type:    str   = ""


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def compute_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def vwema(close: pd.Series, volume: pd.Series, span: int) -> pd.Series:
    """Volume-Weighted EMA — more responsive to institutional moves."""
    pv     = close * volume
    pv_ema = pv.ewm(span=span, adjust=False).mean()
    v_ema  = volume.ewm(span=span, adjust=False).mean()
    return pv_ema / v_ema.replace(0, np.nan)


# ─────────────────────────────────────────────────────────────────────────────
# VOLUME PROFILE  (V5 NEW)
# ─────────────────────────────────────────────────────────────────────────────

def compute_volume_profile(
    high:   pd.Series,
    low:    pd.Series,
    close:  pd.Series,
    volume: pd.Series,
    bins:   int = 30,
    value_area_pct: float = 0.70,
) -> VolumeProfileResult:
    """
    Compute Volume Profile (POC / VAH / VAL / HVN / LVN).

    Algorithm:
      1. Divide price range into `bins` equal buckets.
      2. Distribute each bar's volume across buckets it spans (VWAP weighting).
      3. POC = bucket with highest cumulative volume.
      4. VAH/VAL = expand outward from POC until 70% of total volume covered.
      5. HVN = top-3 buckets by volume (excluding POC).
      6. LVN = bottom-3 buckets by volume (in price range).

    Returns VolumeProfileResult with vp_score already computed.
    Score logic (used as boost in EMABreakoutEngine):
      +1 if close is within value area (VAL ≤ close ≤ VAH)  — healthy demand zone
      +1 if close is within 0.5×ATR of POC                  — highest conviction level
      +1 if close just crossed above VAH (breakout of value) — institutional breakout
    """
    default = VolumeProfileResult(poc=0.0, vah=0.0, val=0.0)

    try:
        if len(close) < 10:
            return default

        close_arr  = close.values.astype(float)
        high_arr   = high.values.astype(float)
        low_arr    = low.values.astype(float)
        vol_arr    = volume.values.astype(float)

        price_min  = float(np.nanmin(low_arr))
        price_max  = float(np.nanmax(high_arr))
        if price_max <= price_min:
            return default

        bucket_size = (price_max - price_min) / bins
        vol_buckets = np.zeros(bins)
        mid_prices  = np.array([price_min + (i + 0.5) * bucket_size for i in range(bins)])

        for i in range(len(close_arr)):
            lo = low_arr[i]
            hi = high_arr[i]
            v  = vol_arr[i]
            if np.isnan(lo) or np.isnan(hi) or np.isnan(v) or v <= 0:
                continue
            b_lo = max(0, int((lo - price_min) / bucket_size))
            b_hi = min(bins - 1, int((hi - price_min) / bucket_size))
            span = max(1, b_hi - b_lo + 1)
            for b in range(b_lo, b_hi + 1):
                vol_buckets[b] += v / span

        # POC = bucket with max volume
        poc_idx    = int(np.argmax(vol_buckets))
        poc        = float(mid_prices[poc_idx])
        total_vol  = float(vol_buckets.sum())

        if total_vol <= 0:
            return default

        # Value Area: expand from POC outward until 70% covered
        target_vol  = total_vol * value_area_pct
        covered_vol = vol_buckets[poc_idx]
        lo_idx, hi_idx = poc_idx, poc_idx

        while covered_vol < target_vol:
            can_go_lo = lo_idx > 0
            can_go_hi = hi_idx < bins - 1
            if not can_go_lo and not can_go_hi:
                break
            add_lo = vol_buckets[lo_idx - 1] if can_go_lo else 0.0
            add_hi = vol_buckets[hi_idx + 1] if can_go_hi else 0.0
            if add_hi >= add_lo:
                hi_idx    += 1
                covered_vol += vol_buckets[hi_idx]
            else:
                lo_idx     -= 1
                covered_vol += vol_buckets[lo_idx]

        vah = float(mid_prices[hi_idx] + bucket_size / 2)
        val = float(mid_prices[lo_idx] - bucket_size / 2)

        # HVN: top-3 non-POC buckets
        sorted_idx = np.argsort(vol_buckets)[::-1]
        hvn_prices = [float(mid_prices[i]) for i in sorted_idx if i != poc_idx][:3]

        # LVN: bottom-3 buckets within value area (demand gaps)
        lvn_sorted = np.argsort(vol_buckets)
        lvn_prices = []
        for i in lvn_sorted:
            p = float(mid_prices[i])
            if val <= p <= vah and len(lvn_prices) < 3:
                lvn_prices.append(p)

        # VP score vs current price
        last_close  = float(close_arr[-1])
        prev_close  = float(close_arr[-2]) if len(close_arr) >= 2 else last_close

        # [TE-1 FIX] ATR yang benar: max(H-L, |H-prevC|, |L-prevC|) per bar, bukan H-L saja.
        # H-L saja underestimate ATR untuk saham IDX yang sering gap, menyebabkan
        # threshold near_poc terlalu sempit → terlalu sedikit saham dapat +1 VP score.
        if len(high_arr) >= 15:
            _h   = high_arr[-14:]
            _l   = low_arr[-14:]
            _c   = close_arr[-15:-1]   # prev close untuk 14 bar terakhir
            _tr  = np.maximum(
                _h - _l,
                np.maximum(np.abs(_h - _c), np.abs(_l - _c))
            )
            atr_est = float(np.nanmean(_tr))
        else:
            atr_est = bucket_size

        vp_score = 0
        if val <= last_close <= vah:
            vp_score += 1
        if abs(last_close - poc) <= 0.5 * atr_est:
            vp_score += 1
        if prev_close <= vah < last_close:
            vp_score += 1  # just broke above value area

        # Entry zone label
        if abs(last_close - poc) <= 0.5 * atr_est:
            entry_zone = "AT_POC"
        elif val <= last_close <= vah:
            entry_zone = "IN_VALUE"
        elif last_close > vah:
            entry_zone = "ABOVE_VAH"
        else:
            entry_zone = "BELOW_VAL"

        return VolumeProfileResult(
            poc        = round(poc, 2),
            vah        = round(vah, 2),
            val        = round(val, 2),
            hvn        = [round(p, 2) for p in hvn_prices],
            lvn        = [round(p, 2) for p in lvn_prices],
            vp_score   = vp_score,
            entry_zone = entry_zone,
        )

    except Exception as exc:
        logger.debug(f"[VP] compute_volume_profile error: {exc}")
        return default


# ─────────────────────────────────────────────────────────────────────────────
# EMA BREAKOUT ENGINE  (V5)
# ─────────────────────────────────────────────────────────────────────────────

class EMABreakoutEngine:

    def __init__(self, config: Any) -> None:
        self.cfg = config

    def _ema(self, series: pd.Series, span: int) -> pd.Series:
        return series.ewm(span=span, adjust=False).mean()

    def analyze(
        self,
        df: pd.DataFrame,
        ticker: str,
        ihsg_df: Optional[pd.DataFrame] = None,
        regime: str = "UNKNOWN",
    ) -> Optional[SetupResult]:
        try:
            if df is None or len(df) < 10:
                return None

            if isinstance(df.columns, pd.MultiIndex):
                df = df.copy()
                df.columns = df.columns.get_level_values(0)

            df = df.dropna(subset=["Close"])
            if len(df) < 10:
                return None

            close  = df["Close"]
            high   = df["High"]
            low    = df["Low"]
            volume = df["Volume"]
            n_bars = len(df)

            # IPO / data-limited flags
            ipo_mode     = n_bars < 30    # hanya EMA5/13, EMA89/200 tidak reliable
            data_limited = n_bars < 89    # EMA89 belum konvergen

            # ── Standard EMAs ─────────────────────────────────────────────────
            ema5_s   = self._ema(close, 5)
            ema13_s  = self._ema(close, 13)
            ema89_s  = self._ema(close, 89)
            ema200_s = self._ema(close, 200)

            last_close  = _f(close.iloc[-1])
            last_ema5   = _f(ema5_s.iloc[-1])
            last_ema13  = _f(ema13_s.iloc[-1])
            last_ema89  = _f(ema89_s.iloc[-1])
            last_ema200 = _f(ema200_s.iloc[-1])
            ema200_reliable = n_bars >= 100

            # IPO: EMA89/200 tidak reliable jika bar < 89
            # Untuk saham IPO, gunakan EMA5/EMA13 cross sebagai primary signal
            ema89_reliable  = n_bars >= 52   # minimal ~1 tahun weekly
            if ipo_mode:
                # Fallback: EMA89/200 → gunakan nilai EMA13 untuk comparison
                last_ema89  = last_ema13
                last_ema200 = last_ema13
            elif data_limited and not ema89_reliable:
                # Partial: EMA89 ada tapi belum konvergen — downweight
                pass  # tetap pakai nilai EMA89 yg ada, flagged di output

            # ── Volume-Weighted EMAs ──────────────────────────────────────────
            vw13 = vwema(close, volume, 13)
            vw89 = vwema(close, volume, 89)
            last_vwema13 = _f(vw13.iloc[-1]) if not vw13.isna().iloc[-1] else last_ema13
            last_vwema89 = _f(vw89.iloc[-1]) if not vw89.isna().iloc[-1] else last_ema89

            # ── Volume ────────────────────────────────────────────────────────
            vol_window = min(20, n_bars)
            vol_ma20  = _f(volume.rolling(vol_window).mean().iloc[-1])
            if vol_ma20 == 0 and n_bars >= 3:
                vol_ma20 = _f(volume.iloc[-vol_window:].mean())
            last_vol  = _f(volume.iloc[-1])
            vol_ratio = (last_vol / vol_ma20) if vol_ma20 > 0 else 0.0

            # ── ATR-14 ────────────────────────────────────────────────────────
            atr_series = compute_atr(high, low, close, 14)
            last_atr   = _f(atr_series.iloc[-1]) if not atr_series.isna().iloc[-1] else last_close * 0.02
            atr_pct    = last_atr / last_close * 100 if last_close > 0 else 2.0

            # ── Cross state — vectorized ──────────────────────────────────────
            cross_state      = "BELOW"
            bars_since_cross = 0

            if last_ema13 > last_ema89:
                cross_state = "ABOVE"
                above_mask  = ema13_s.values > ema89_s.values
                false_idx   = np.where(~above_mask)[0]
                bars_since_cross = (
                    n_bars if len(false_idx) == 0
                    else n_bars - 1 - int(false_idx[-1])
                )
            elif abs(last_ema13 - last_ema89) / max(last_ema89, 1) < 0.01:
                cross_state = "CROSSING"

            # ── Box detection — statistically-grounded ────────────────────────
            roll_w = min(20, n_bars)
            rolling_range_pct = (
                (high.rolling(roll_w).max() - low.rolling(roll_w).min())
                / low.rolling(roll_w).min() * 100
            ).dropna()
            range_p80     = float(rolling_range_pct.quantile(0.80)) if len(rolling_range_pct) > 0 else 10.0
            dynamic_box_pct = max(2.5, min(atr_pct * 2.5, range_p80 * 0.75))

            lookback    = min(self.cfg.box_max_bars, n_bars - 1)
            recent_high = _f(high.iloc[-lookback:].max())
            recent_low  = _f(low.iloc[-lookback:].min())
            box_range_pct = (recent_high - recent_low) / recent_low * 100 if recent_low > 0 else 999.0
            box_atr_mult  = box_range_pct / atr_pct if atr_pct > 0 else 99.0

            bars_in_range = 0
            box_high      = recent_high
            box_low       = recent_low

            box_detected = (box_range_pct <= dynamic_box_pct and box_atr_mult <= 3.5)

            if box_detected:
                for i in range(n_bars - 1, max(n_bars - lookback, 0), -1):
                    c = _f(close.iloc[i])
                    if box_low <= c <= box_high:
                        bars_in_range += 1
                    else:
                        break
                box_detected = box_detected and bars_in_range >= self.cfg.box_min_bars

            # ── Breakout detection ────────────────────────────────────────────
            prev_box_high = _f(high.iloc[-lookback:-1].max()) if lookback > 1 else box_high
            breaking_out  = (
                last_close > prev_box_high
                and vol_ratio >= self.cfg.vol_mult
                and cross_state == "ABOVE"
            )
            strong_breaking_out = breaking_out and vol_ratio >= 3.0

            # ── Relative Strength vs IHSG ─────────────────────────────────────
            rs_4w  = 0.0
            rs_sig = "N/A"
            if ihsg_df is not None and len(ihsg_df) >= 20:
                try:
                    ihsg_close = ihsg_df["Close"] if "Close" in ihsg_df.columns else ihsg_df.iloc[:, 0]
                    common     = close.index.intersection(ihsg_close.index)
                    if len(common) >= 20:
                        stk_ret  = _f(close.loc[common[-1]] / close.loc[common[-20]] - 1) * 100
                        ihsg_ret = _f(ihsg_close.loc[common[-1]] / ihsg_close.loc[common[-20]] - 1) * 100
                        rs_4w    = round(stk_ret - ihsg_ret, 1)
                        rs_sig   = ("STRONG" if rs_4w > 3 else "WEAK" if rs_4w < -3 else "NEUTRAL")
                except Exception as exc:
                    logger.debug(f"[Engine] RS calc {ticker}: {exc}")

            # ── Regime tag ────────────────────────────────────────────────────
            regime_tag = {
                "BULL_TREND":        "FULL",
                "BULL_CONSOLIDATION":"FULL",
                "TRANSITION":        "SELECTIVE",
                "BEAR_CONSOLIDATION":"SPECULATIVE",
                "BEAR_TREND":        "WATCHLIST_ONLY",
            }.get(regime, "FULL")

            is_bear = regime_tag in ("WATCHLIST_ONLY", "SPECULATIVE")

            # ── Volume Profile ────────────────────────────────────────────────
            vp = compute_volume_profile(high, low, close, volume)

            # ── SCORE ─────────────────────────────────────────────────────────
            score = 0
            flags: list[str] = []

            # IPO / data-limited warnings
            if ipo_mode:
                flags.append(f"⚡ IPO MODE: {n_bars} bars — EMA5/13 cross only")
            elif data_limited:
                flags.append(f"⚠ DATA TERBATAS: {n_bars} bars (<89wk) — EMA89 belum konvergen")

            # (1) EMA cross — untuk IPO mode, gunakan EMA5>EMA13 cross
            if ipo_mode:
                if last_ema5 > last_ema13:
                    score += 2   # bobot lebih tinggi karena satu-satunya signal
                    flags.append("EMA5>EMA13 (IPO)")
            elif last_ema13 > last_ema89:
                score += 1
                flags.append("EMA13>EMA89")

            # (2) VWEMA confirmation
            if last_vwema13 > last_vwema89:
                score += 1
                flags.append("VWEMA confirmed")

            # (3) Price above EMA89
            if last_close > last_ema89:
                score += 1
                flags.append("Price>EMA89")

            # (4) Price above EMA200 — only if reliable
            # Opsi 1: jika data < 100 bars weekly, EMA200 tidak reliable →
            # skip sepenuhnya (tidak award, tidak flag negatif).
            # EMA89 sudah cukup sebagai long-term anchor untuk saham baru.
            if not ipo_mode and ema200_reliable and last_close > last_ema200:
                score += 1
                flags.append("Price>EMA200")
            # EMA89 sebagai long-term anchor jika EMA200 tidak reliable
            elif not ipo_mode and not ema200_reliable and last_close > last_ema89:
                flags.append("Price>EMA89 (anchor, EMA200 N/A)")

            # (5) Box / consolidation
            if box_detected:
                score += 1
                flags.append(f"Box {box_range_pct:.1f}% ({box_atr_mult:.1f}×ATR)")

            # (6) Volume
            if vol_ratio >= self.cfg.vol_mult:
                score += 1
                flags.append(f"Vol {vol_ratio:.1f}×")

            # (7) RS vs IHSG
            if rs_sig == "STRONG":
                score += 1
                flags.append(f"RS+{rs_4w:.1f}% vs IHSG")

            # (8) Volume Profile boost — VP as scorer (not hard gate)
            if vp.vp_score > 0:
                score += min(vp.vp_score, 1)   # max +1 from VP per design
                flags.append(f"VP {vp.entry_zone} (+{min(vp.vp_score,1)})")

            # ── Regime adjustments ────────────────────────────────────────────
            if is_bear and rs_4w < 0:
                score = max(0, score - 1)
                flags.append(f"⚠ RS negatif di bear ({rs_4w:.1f}%) —1")

            if is_bear:
                try:
                    atr_w  = _f((df["High"] - df["Low"]).rolling(14).mean().iloc[-1])
                    sl_est = last_close - 2 * atr_w
                    risk_e = ((last_close - sl_est) / last_close * 100) if sl_est > 0 else 0
                    if risk_e > 25:
                        score = max(0, score - 1)
                        flags.append(f"⚠ SL terlalu lebar ({risk_e:.0f}%) bear —1")
                except Exception as exc:
                    logger.debug(f"[Engine] bear risk calc {ticker}: {exc}")

            # ── Fix v9.7.0 [Audit finding #6]: bull bonus DIHAPUS ──────────────
            # Sebelumnya: score>=5 + rs_sig=="STRONG" + vol_ratio>=2.0 → +1.
            # Masalah: rs_sig=="STRONG" sudah dihitung di komponen (7), dan
            # vol_ratio>=2.0 nyaris identik dengan syarat komponen (6)
            # (vol_ratio>=self.cfg.vol_mult, default juga 2.0). Bonus ini
            # menguji ulang bukti yang sama, bukan bukti independen baru —
            # efeknya cuma mendorong marginal score=5 ke score=6, melewati
            # ambang STRONG_BREAKOUT tanpa faktor konfirmasi tambahan asli.

            # ── HARD CAP: score never exceeds 10 ─────────────────────────────
            score = min(score, 10)

            # ── Regime score cap (after hard cap) ────────────────────────────
            # Simpan score_raw sebelum cap — dipakai di UI untuk komunikasi ke trader
            score_raw = score
            score_capped = False
            if regime_tag == "WATCHLIST_ONLY" and score > 3:
                flags.append("⚠ BEAR: score capped 3")
                score = min(score, 3)
                score_capped = True
            elif regime_tag == "SPECULATIVE" and score > 4:
                flags.append("⚠ BEAR_CONSOL: score capped 4")
                score = min(score, 4)
                score_capped = True

            # ── Signal classification ─────────────────────────────────────────
            if ipo_mode:
                # IPO: signal berdasar EMA5/EMA13 cross saja
                if last_ema5 > last_ema13 and vol_ratio >= self.cfg.vol_mult and score >= 3:
                    signal = "BREAKOUT"
                elif last_ema5 > last_ema13 and score >= 2:
                    signal = "WATCHLIST"
                elif last_ema5 > last_ema13:
                    signal = "CORRECTING"
                else:
                    signal = "NONE"
            elif strong_breaking_out and score >= 6 and regime_tag != "WATCHLIST_ONLY":
                signal = "STRONG_BREAKOUT"
            elif breaking_out and score >= 3 and regime_tag != "WATCHLIST_ONLY":
                signal = "BREAKOUT"
            elif cross_state == "ABOVE" and box_detected and score >= 3:
                signal = "WATCHLIST"
            elif cross_state in ("ABOVE", "CROSSING") and last_close > last_ema89 * 0.95:
                signal = "CORRECTING"
            elif cross_state == "ABOVE" and last_close < last_ema89:
                signal = "DEEP_CORRECT"
            else:
                # ── Compression detection (EMA13 < EMA89 tapi gap menyempit) ──
                # Kondisi: EMA13 di bawah EMA89, tapi:
                # 1. Gap menyempit >= 30% dalam 3 bar terakhir (momentum reversal)
                # 2. EMA89 slope masih positif (long-term trend intact)
                # 3. EMA13 slope positif (short-term momentum mulai balik)
                # Signal: COMPRESSING — antara CORRECTING dan WATCHLIST
                _is_compressing = False
                try:
                    if (cross_state == "BELOW"
                            and len(ema13_s) >= 4
                            and len(ema89_s) >= 4):
                        _gap_now   = last_ema89 - last_ema13
                        _gap_3ago  = float(ema89_s.iloc[-4]) - float(ema13_s.iloc[-4])
                        _ema89_slope = float(ema89_s.iloc[-1]) - float(ema89_s.iloc[-4])
                        _ema13_slope = float(ema13_s.iloc[-1]) - float(ema13_s.iloc[-4])
                        _gap_shrink  = (_gap_3ago - _gap_now) / max(_gap_3ago, 1)

                        _is_compressing = (
                            _gap_now    > 0            # EMA13 masih di bawah EMA89
                            and _gap_shrink >= 0.25    # gap menyempit >= 25% dalam 3 bar
                            and _ema89_slope >= 0      # EMA89 tidak turun
                            and _ema13_slope > 0       # EMA13 mulai naik
                        )
                except Exception:
                    pass

                if _is_compressing:
                    signal = "COMPRESSING"
                    flags.append(f"Gap EMA menyempit {_gap_shrink*100:.0f}% dalam 3 bar")
                else:
                    signal = "NONE"

            # ── Breakout type transparency (v9.7.0, additive — signal string TIDAK berubah) ──
            breakout_type = ""
            if signal in ("STRONG_BREAKOUT", "BREAKOUT"):
                breakout_type = "BOX" if box_detected else "MOMENTUM"
                flags.append(f"Breakout type: {breakout_type}")

            # RS downgrade
            if signal == "BREAKOUT" and rs_sig == "WEAK":
                signal = "WATCHLIST"
                breakout_type = ""
                flags.append("RS weak → downgrade WATCHLIST")

            # ── Risk levels ───────────────────────────────────────────────────
            entry_price = last_close
            sl_price    = (box_low * 0.99 if box_detected else entry_price - 2.0 * last_atr)
            risk        = max(entry_price - sl_price, last_atr * 0.5)
            risk_pct    = (risk / entry_price * 100) if entry_price > 0 else 0.0
            tp1_price   = entry_price + risk * _f(self.cfg.tp1_rr)
            tp2_price   = entry_price + risk * _f(self.cfg.tp2_rr)
            tp3_price   = entry_price + risk * _f(self.cfg.tp3_rr)
            rr_ratio    = round(_f(self.cfg.tp1_rr), 1)
            risk_sizing_ok = risk_pct <= 15.0

            if risk_pct > 25:
                flags.append(f"⚠ RISK {risk_pct:.0f}% — sizing sangat kecil")
            elif risk_pct > 15:
                flags.append(f"⚠ RISK {risk_pct:.0f}% — perlu hati-hati")

            # Exit framework
            trail_1atr  = round(last_close - 1.0 * last_atr, 0)
            trail_2atr  = round(last_close - 2.0 * last_atr, 0)
            exit_ema    = round(last_ema13 * 0.98, 0)
            dist_to_tp1 = tp1_price - entry_price
            hold_days   = int(dist_to_tp1 / last_atr) if last_atr > 0 else 10

            return SetupResult(
                ticker            = ticker,
                signal            = signal,
                score             = score,
                regime_tag        = regime_tag,
                date              = str(df.index[-1])[:10],
                close             = round(last_close, 2),
                open_             = round(_f(df["Open"].iloc[-1]), 2),
                high              = round(_f(high.iloc[-1]), 2),
                low               = round(_f(low.iloc[-1]), 2),
                ema5              = round(last_ema5, 2),
                ema13             = round(last_ema13, 2),
                ema89             = round(last_ema89, 2),
                ema200            = round(last_ema200, 2),
                ema200_reliable   = ema200_reliable,
                vwema13           = round(last_vwema13, 2),
                vwema89           = round(last_vwema89, 2),
                cross_state       = cross_state,
                bars_since_cross  = bars_since_cross,
                box_high          = round(box_high, 2),
                box_low           = round(box_low, 2),
                box_range_pct     = round(box_range_pct, 1),
                box_atr_multiple  = round(box_atr_mult, 1),
                bars_in_range     = bars_in_range,
                volume            = round(last_vol, 0),
                vol_ma20          = round(vol_ma20, 0),
                vol_ratio         = round(vol_ratio, 2),
                rs_vs_ihsg_4w     = rs_4w,
                rs_signal         = rs_sig,
                atr14             = round(last_atr, 2),
                trail_stop_1atr   = trail_1atr,
                trail_stop_2atr   = trail_2atr,
                exit_ema_break    = exit_ema,
                holding_days_est  = hold_days,
                entry_price       = round(entry_price, 2),
                sl_price          = round(sl_price, 2),
                tp1_price         = round(tp1_price, 2),
                tp2_price         = round(tp2_price, 2),
                tp3_price         = round(tp3_price, 2),
                risk_pct          = round(risk_pct, 1),
                rr_ratio          = rr_ratio,
                risk_sizing_ok    = risk_sizing_ok,
                vp_poc            = vp.poc,
                vp_vah            = vp.vah,
                vp_val            = vp.val,
                vp_score          = vp.vp_score,
                vp_entry_zone     = vp.entry_zone,
                flags             = flags,
                data_limited      = data_limited,
                ipo_mode          = ipo_mode,
                score_raw         = score_raw,
                score_capped      = score_capped,
                breakout_type     = breakout_type,
            )

        except Exception as exc:
            logger.debug(f"[Engine] {ticker} error: {exc}")
            return None


# ─────────────────────────────────────────────────────────────────────────────
# DAILY ENTRY CHECK  (unchanged from V4 — already clean)
# ─────────────────────────────────────────────────────────────────────────────

def check_daily_entry(df_daily: pd.DataFrame, weekly_cross: str) -> dict:
    """
    Dual-timeframe entry check.
    EMA13 series computed once; yesterday = iloc[-2].
    """
    if df_daily is None or len(df_daily) < 10:
        return {"daily_ok": False, "daily_pattern": "NO_DATA"}

    if weekly_cross not in ("ABOVE", "CROSSING"):
        return {"daily_ok": False, "daily_pattern": "WEEKLY_NOT_OK"}

    try:
        if isinstance(df_daily.columns, pd.MultiIndex):
            df_daily = df_daily.copy()
            df_daily.columns = df_daily.columns.get_level_values(0)

        close = df_daily["Close"].dropna()
        vol   = df_daily["Volume"].dropna()

        if len(close) < 30:
            return {"daily_ok": False, "daily_pattern": "INSUFFICIENT_DATA"}

        ema5_s  = close.ewm(span=5,  adjust=False).mean()
        ema13_s = close.ewm(span=13, adjust=False).mean()
        ema89_s = close.ewm(span=89, adjust=False).mean()

        ema5d       = _f(ema5_s.iloc[-1])
        ema13d      = _f(ema13_s.iloc[-1])
        ema89d      = _f(ema89_s.iloc[-1])
        ema5d_prev  = _f(ema5_s.iloc[-2])
        ema13d_prev = _f(ema13_s.iloc[-2])
        ema89d_prev = _f(ema89_s.iloc[-2])
        last        = _f(close.iloc[-1])

        d_cross     = "ABOVE" if ema13d > ema89d else ("BELOW" if ema13d < ema89d else "EQUAL")
        fresh_cross = ema13d > ema89d and ema13d_prev <= ema89d_prev
        ema5_cross  = ema5d > ema13d and ema5d_prev <= ema13d_prev

        vol_ma20  = _f(vol.rolling(20).mean().iloc[-1])
        vol_ratio = _f(vol.iloc[-1]) / vol_ma20 if vol_ma20 > 0 else 0.0

        pct_vs_ema13d = ((last - ema13d) / ema13d * 100) if ema13d > 0 else 0.0
        pct_vs_ema89d = ((last - ema89d) / ema89d * 100) if ema89d > 0 else 0.0

        if fresh_cross and vol_ratio >= 1.3:
            pattern, daily_ok = "DAILY_GOLDEN_CROSS_CONFIRMED", True
            entry_note = f"Golden cross harian + vol {vol_ratio:.1f}×"
        elif fresh_cross:
            pattern, daily_ok = "DAILY_GOLDEN_CROSS", True
            entry_note = "Golden cross harian (EMA13d baru melewati EMA89d)"
        elif d_cross == "ABOVE" and ema5_cross and vol_ratio >= 1.3:
            pattern, daily_ok = "DAILY_EMA5_CROSS_VOL", True
            entry_note = f"EMA5d cross EMA13d + vol {vol_ratio:.1f}× — momentum akselerasi"
        elif d_cross == "ABOVE" and abs(pct_vs_ema13d) <= 3 and vol_ratio >= 1.2:
            pattern, daily_ok = "DAILY_PULLBACK_ENTRY", True
            entry_note = f"Harga di EMA13d support ({pct_vs_ema13d:+.1f}%) + vol naik"
        elif d_cross == "ABOVE" and pct_vs_ema89d >= 0 and vol_ratio >= 3.0:
            pattern, daily_ok = "DAILY_VOLUME_SPIKE", True
            entry_note = f"Vol spike {vol_ratio:.1f}× + daily trend bullish"
        elif d_cross == "BELOW" and pct_vs_ema89d >= -5 and vol_ratio >= 1.5:
            pattern, daily_ok = "DAILY_NEAR_EMA89_REVERSAL", True
            entry_note = f"Harga {pct_vs_ema89d:+.1f}% dari EMA89d + vol {vol_ratio:.1f}×"
        elif d_cross == "ABOVE":
            pattern, daily_ok = "DAILY_ABOVE_EMA_WAIT", False
            entry_note = "Daily bullish tapi belum ada konfirmasi entry"
        else:
            pattern, daily_ok = "DAILY_BELOW_EMA", False
            entry_note = f"EMA13d {ema13d:,.0f} di bawah EMA89d {ema89d:,.0f} — belum siap"

        return {
            "daily_ok":         daily_ok,
            "daily_pattern":    pattern,
            "daily_cross":      d_cross,
            "fresh_cross":      fresh_cross,
            "ema5_cross":       ema5_cross,
            "ema5d":            round(ema5d, 0),
            "ema13d":           round(ema13d, 0),
            "ema89d":           round(ema89d, 0),
            "pct_vs_ema13d":    round(pct_vs_ema13d, 1),
            "pct_vs_ema89d":    round(pct_vs_ema89d, 1),
            "vol_ratio_d":      round(vol_ratio, 2),
            "daily_entry_note": entry_note,
        }

    except Exception as exc:
        return {"daily_ok": False, "daily_pattern": f"ERROR: {exc}"}


# ─────────────────────────────────────────────────────────────────────────────
# MARKET STRUCTURE ANALYSIS  (typed, no hidden recompute)
# ─────────────────────────────────────────────────────────────────────────────

def analyze_market_structure(
    close: pd.Series,
    high:  pd.Series,
    low:   pd.Series,
    vol:   pd.Series,
    ema13: float,
    ema89: float,
    ema13_series: Optional[pd.Series] = None,
    ema89_series: Optional[pd.Series] = None,
    cross_date_bars: int = 0,
) -> dict:
    """
    Market structure analysis.
    If ema13_series / ema89_series provided (from engine.analyze),
    uses them directly — no recomputation.
    """
    if len(close) < 30:
        return {"ms_conviction_boost": 0, "ms_summary": "insufficient data"}

    try:
        n = len(close)
        c = close.values.astype(float)
        v = vol.values.astype(float)

        # 1. Price structure
        def find_swings(arr: np.ndarray, window: int = 5):
            highs, lows = [], []
            for i in range(window, len(arr) - window):
                if (all(arr[i] >= arr[i-j] for j in range(1, window+1)) and
                        all(arr[i] >= arr[i+j] for j in range(1, window+1))):
                    highs.append((i, arr[i]))
                if (all(arr[i] <= arr[i-j] for j in range(1, window+1)) and
                        all(arr[i] <= arr[i+j] for j in range(1, window+1))):
                    lows.append((i, arr[i]))
            return highs, lows

        swing_highs, swing_lows = find_swings(c[-60:] if n >= 60 else c)
        structure = "UNKNOWN"
        structure_score = 0

        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            hh = swing_highs[-1][1] > swing_highs[-2][1]
            hl = swing_lows[-1][1]  > swing_lows[-2][1]
            lh = swing_highs[-1][1] < swing_highs[-2][1]
            ll = swing_lows[-1][1]  < swing_lows[-2][1]
            if hh and hl:
                structure, structure_score = "HH_HL", 2
            elif hh:
                structure, structure_score = "HH_LL", 0
            elif lh and hl:
                structure, structure_score = "LH_HL", 1
            elif lh and ll:
                structure, structure_score = "LH_LL", -2
            elif hl:
                structure, structure_score = "RECOVERING", 1
        elif len(swing_highs) >= 1 and len(swing_lows) >= 1:
            structure = "TRENDING_UP" if c[-1] > c[-20] else "TRENDING_DOWN"
            structure_score = 1 if structure == "TRENDING_UP" else -1

        # 2. Trend age
        if ema13_series is not None and ema89_series is not None:
            _ema13 = ema13_series
            _ema89 = ema89_series
        else:
            s = pd.Series(c)
            _ema13 = s.ewm(span=13, adjust=False).mean()
            _ema89 = s.ewm(span=89, adjust=False).mean()

        diff = _ema13 - _ema89
        cross_bars_ago = 0
        for i in range(1, min(n, 100)):
            if diff.iloc[-i] * diff.iloc[-(i+1)] < 0:
                cross_bars_ago = i
                break
        if cross_bars_ago == 0:
            cross_bars_ago = 100

        if cross_bars_ago <= 5:
            age_score, age_label = 2, f"FRESH ({cross_bars_ago}b lalu)"
        elif cross_bars_ago <= 15:
            age_score, age_label = 1, f"BARU ({cross_bars_ago}b lalu)"
        elif cross_bars_ago <= 40:
            age_score, age_label = 0, f"MATANG ({cross_bars_ago}b lalu)"
        else:
            age_score, age_label = -1, f"TUA ({cross_bars_ago}b lalu)"

        # 3. EMA slope
        if len(_ema13) >= 5:
            ema13_now  = _f(_ema13.iloc[-1])
            ema13_5ago = _f(_ema13.iloc[-5])
            ema89_now  = _f(_ema89.iloc[-1])
            ema89_5ago = _f(_ema89.iloc[-5])
            slope13    = ((ema13_now - ema13_5ago) / ema13_5ago * 100) if ema13_5ago > 0 else 0.0
            slope89    = ((ema89_now - ema89_5ago) / ema89_5ago * 100) if ema89_5ago > 0 else 0.0
            slope_diff = slope13 - slope89
        else:
            slope13 = slope89 = slope_diff = 0.0

        if slope13 > 2 and slope_diff > 1:
            slope_score, slope_label = 2, f"STEEP RISE +{slope13:.1f}%/5bar"
        elif slope13 > 0.5:
            slope_score, slope_label = 1, f"RISING +{slope13:.1f}%/5bar"
        elif slope13 > -0.5:
            slope_score, slope_label = 0, f"FLAT {slope13:+.1f}%/5bar"
        else:
            slope_score, slope_label = -1, f"DECLINING {slope13:+.1f}%/5bar"

        # 4. Volume trend
        if n >= 20:
            vol_ma10 = float(np.mean(v[-10:]))
            vol_ma20 = float(np.mean(v[-20:]))
            vtr = vol_ma10 / vol_ma20 if vol_ma20 > 0 else 1.0
            if vtr >= 1.3:
                vol_trend_score, vol_trend_label = 1, f"VOL NAIK ({vtr:.1f}×)"
            elif vtr >= 0.8:
                vol_trend_score, vol_trend_label = 0, f"VOL STABIL ({vtr:.1f}×)"
            else:
                vol_trend_score, vol_trend_label = -1, f"VOL TURUN ({vtr:.1f}×)"
        else:
            vol_trend_score, vol_trend_label = 0, "VOL UNKNOWN"

        # 5. S/R levels
        current = float(c[-1])
        nearest_support = max((sl[1] for sl in swing_lows if sl[1] < current), default=0.0)
        support_dist    = ((current - nearest_support) / current * 100) if nearest_support > 0 else 100.0
        nearest_resist  = min((sh[1] for sh in swing_highs if sh[1] > current), default=current * 1.5)
        resist_dist     = ((nearest_resist - current) / current * 100)
        sr_score        = 1 if support_dist <= 5 else 0

        # 6. Conviction boost
        raw_boost = (
            structure_score * 1.0 +
            age_score       * 0.8 +
            slope_score     * 0.6 +
            vol_trend_score * 0.4 +
            sr_score        * 0.4
        )
        conviction_boost = max(-3, min(3, round(raw_boost)))

        parts = []
        if structure in ("HH_HL",):
            parts.append(f"Struktur {structure} ✓")
        elif structure == "LH_LL":
            parts.append(f"⚠️ Struktur {structure} — dead cat risk")
        elif structure in ("LH_HL", "RECOVERING"):
            parts.append(f"Struktur {structure}")
        parts.append(age_label)
        parts.append(slope_label)
        if vol_trend_score != 0:
            parts.append(vol_trend_label)

        return {
            "ms_conviction_boost": conviction_boost,
            "ms_structure":        structure,
            "ms_structure_score":  structure_score,
            "ms_cross_bars_ago":   cross_bars_ago,
            "ms_age_label":        age_label,
            "ms_age_score":        age_score,
            "ms_slope13":          round(slope13, 2),
            "ms_slope_label":      slope_label,
            "ms_slope_score":      slope_score,
            "ms_vol_trend":        vol_trend_label,
            "ms_vol_trend_score":  vol_trend_score,
            "ms_nearest_support":  round(nearest_support, 0),
            "ms_support_dist_pct": round(support_dist, 1),
            "ms_nearest_resist":   round(nearest_resist, 0),
            "ms_resist_dist_pct":  round(resist_dist, 1),
            "ms_summary":          " · ".join(parts),
        }

    except Exception as exc:
        return {"ms_conviction_boost": 0, "ms_summary": f"error: {exc}"}


# ─────────────────────────────────────────────────────────────────────────────
# MOMENTUM CONFLUENCE FILTER  (V5 — typed, bear_blocked preserved)
# ─────────────────────────────────────────────────────────────────────────────

def compute_mcf(
    close:          pd.Series,
    high:           pd.Series,
    low:            pd.Series,
    volume:         pd.Series,
    open_:          Optional[pd.Series] = None,
    market_bullish: bool                = True,
    regime_tag:     str                 = "FULL",
) -> dict:
    """
    Momentum Confluence Filter (MCF) V5.

    Bear blocking: if regime_tag == WATCHLIST_ONLY and MCF score would be JOIN,
    label is overridden to BEAR_BLOCKED and mcf_entry_ok = False.

    No logic changes from V4 — only typed accessors replacing bare float().
    """
    _default: dict = {
        "mcf_score": 0, "mcf_label": "SKIP",
        "mcf_momentum": 0, "mcf_volume": 0, "mcf_followup": 0,
        "mcf_entry_ok": False, "mcf_detail": {},
        "mcf_roc_atr": 0.0, "mcf_vol_ratio": 0.0,
        "mcf_vol_trend": 0.0, "mcf_close_pos": 0.0,
        "mcf_upper_wick": 0.0, "mcf_consec_up": 0,
        "mcf_market_bonus": 0, "mcf_bear_blocked": False,
    }

    try:
        n = len(close)
        if n < 14:
            _default["mcf_detail"] = {"error": "need ≥14 bars"}
            return _default

        atr_s = compute_atr(high, low, close, 14)
        atr   = _f(atr_s.iloc[-1])
        if np.isnan(atr) or atr <= 0:
            atr = _f(close.iloc[-1]) * 0.015

        ema13_s      = close.ewm(span=13, adjust=False).mean()
        ema13_now    = _f(ema13_s.iloc[-1])
        ema13_4ag    = _f(ema13_s.iloc[-5]) if n >= 5 else ema13_now
        ema13_rising = ema13_now > ema13_4ag

        last  = _f(close.iloc[-1])
        prev4 = _f(close.iloc[-5]) if n >= 5 else _f(close.iloc[0])
        above   = last > ema13_now
        roc_atr = (last - prev4) / atr if atr > 0 else 0.0

        consec = 0
        cv = close.values
        for i in range(1, min(5, n)):
            if cv[-i] > cv[-(i+1)]:
                consec += 1
            else:
                break

        if above and roc_atr >= 1.5 and consec >= 3 and ema13_rising:
            p1, p1_desc = 3, f"KUAT — +{roc_atr:.1f}× ATR/4bar, {consec} candle naik, EMA13 ↑"
        elif above and (roc_atr >= 0.8 or consec >= 2) and ema13_rising:
            p1, p1_desc = 2, f"MODERATE — +{roc_atr:.1f}× ATR, {consec} candle naik"
        elif above and roc_atr > 0:
            p1, p1_desc = 1, f"LEMAH/AWAL — di atas EMA13, +{roc_atr:.1f}× ATR"
        else:
            p1, p1_desc = 0, f"TIDAK ADA — {'di bawah EMA13' if not above else f'turun {roc_atr:.1f}× ATR'}"

        v      = volume.values.astype(float)
        v_t    = float(v[-1])
        v_ma20 = float(np.nanmean(v[-20:])) if n >= 20 else float(np.nanmean(v))
        v_ma10 = float(np.nanmean(v[-10:])) if n >= 10 else v_ma20
        v_ma50 = float(np.nanmean(v[-50:])) if n >= 50 else v_ma20
        ratio   = v_t    / v_ma20 if v_ma20 > 0 else 1.0
        trend   = v_ma10 / v_ma20 if v_ma20 > 0 else 1.0
        sustain = v_ma10 / v_ma50 if v_ma50 > 0 else 1.0

        if ratio >= 2.0 and trend >= 1.2 and sustain >= 1.05:
            p2, p2_desc = 3, f"EKSPANSI — {ratio:.1f}× avg, trend 10d {trend:.1f}×"
        elif ratio >= 1.5 or (ratio >= 1.2 and trend >= 1.15):
            p2, p2_desc = 2, f"ELEVATED — {ratio:.1f}× avg, trend {trend:.1f}×"
        elif ratio >= 0.7:
            p2, p2_desc = 1, f"NORMAL — {ratio:.1f}× avg"
        else:
            p2, p2_desc = 0, f"KERING — {ratio:.1f}× avg — smart money absen"

        h1 = _f(high.iloc[-1])
        l1 = _f(low.iloc[-1])
        c1 = _f(close.iloc[-1])
        o1 = _f(open_.iloc[-1]) if (open_ is not None and len(open_) >= 1) else (
             _f(close.iloc[-2]) if n >= 2 else c1)

        if n >= 2:
            h2 = _f(high.iloc[-2])
            l2 = _f(low.iloc[-2])
            c2 = _f(close.iloc[-2])
            o2 = _f(open_.iloc[-2]) if (open_ is not None and len(open_) >= 2) else (
                 _f(close.iloc[-3]) if n >= 3 else c2)
        else:
            h2 = h1; l2 = l1; c2 = c1; o2 = o1

        r1       = max(h1 - l1, atr * 0.05)
        close_p  = (c1 - l1) / r1
        upwick1  = (h1 - max(c1, o1)) / r1
        bull1    = c1 >= o1

        r2       = max(h2 - l2, atr * 0.05)
        close_p2 = (c2 - l2) / r2
        bull2    = c2 >= o2

        if close_p >= 0.75 and upwick1 <= 0.15 and bull1 and close_p2 >= 0.60 and bull2:
            p3, p3_desc = 3, f"KUAT — close {close_p:.0%} range, 2 candle bullish"
        elif close_p >= 0.60 and bull1 and upwick1 <= 0.30:
            p3, p3_desc = 2, f"BAGUS — close {close_p:.0%} range, wick {upwick1:.0%}"
        elif close_p >= 0.40:
            p3, p3_desc = 1, f"LEMAH — close {close_p:.0%} range"
        else:
            p3, p3_desc = 0, f"BEARISH — close {close_p:.0%}, seller control"

        mkt_bonus = 1 if market_bullish else -1
        raw       = p1 + p2 + p3 + mkt_bonus
        total     = max(0, min(10, raw))
        label     = "JOIN" if total >= 6 else "WAIT" if total >= 4 else "SKIP"

        bear_blocked = (regime_tag == "WATCHLIST_ONLY") and (label == "JOIN")
        entry_ok     = (total >= 6) and not bear_blocked

        if bear_blocked:
            label = "BEAR_BLOCKED"

        return {
            "mcf_score":        total,
            "mcf_label":        label,
            "mcf_momentum":     p1,
            "mcf_volume":       p2,
            "mcf_followup":     p3,
            "mcf_entry_ok":     entry_ok,
            "mcf_roc_atr":      round(roc_atr,  2),
            "mcf_vol_ratio":    round(ratio,    2),
            "mcf_vol_trend":    round(trend,    2),
            "mcf_close_pos":    round(close_p,  2),
            "mcf_upper_wick":   round(upwick1,  2),
            "mcf_consec_up":    consec,
            "mcf_market_bonus": mkt_bonus,
            "mcf_bear_blocked": bear_blocked,
            "mcf_detail": {
                "momentum": p1_desc,
                "volume":   p2_desc,
                "followup": p3_desc,
            },
        }

    except Exception as exc:
        return {**_default, "mcf_detail": {"error": str(exc)}}


# ─────────────────────────────────────────────────────────────────────────────
# DAILY EMA ENGINE  (V1) — Primary daily, weekly for trend context only
# ─────────────────────────────────────────────────────────────────────────────

# v9.9.5: ambang RR minimum untuk verdict ENTRY (user: perketat ke 2.0).
# Turunkan bila rezim SANGAT_SEPI mengosongkan entry terlalu agresif.
RR_MIN_ENTRY = 2.0


class DailyEMAEngine:
    """
    EMA Breakout Engine berbasis daily data sebagai primary.

    Perbedaan dari EMABreakoutEngine (weekly):
      - EMA13/89/200 dihitung dari df_daily (data harian)
      - Box detection berdasar daily bar (lookback 20 hari)
      - Breakout = close > box_high 20 hari + vol ≥ vol_mult × vol_ma20 daily
      - Weekly df hanya dipakai untuk weekly_cross_state (konteks trend besar)
      - Hasil refresh setiap hari karena daily bar selalu update

    Output: dict yang identik dengan EMABreakoutEngine._to_dict(result) —
    semua field SetupResult tersedia agar scanner_agent tidak perlu diubah.
    """

    def __init__(self, config: Any) -> None:
        self.cfg = config

    def _ema(self, series: pd.Series, span: int) -> pd.Series:
        return series.ewm(span=span, adjust=False).mean()

    def analyze(
        self,
        df_daily:  pd.DataFrame,
        ticker:    str,
        df_weekly: Optional[pd.DataFrame] = None,
        ihsg_df:   Optional[pd.DataFrame] = None,
        regime:    str = "UNKNOWN",
    ) -> Optional[dict]:
        """
        Returns dict (bukan SetupResult) agar caller tidak perlu dataclass import.
        Field keys identik dengan SetupResult sehingga scanner_agent bisa drop-in.
        """
        try:
            if df_daily is None or len(df_daily) < 30:
                return None

            if isinstance(df_daily.columns, pd.MultiIndex):
                df_daily = df_daily.copy()
                df_daily.columns = df_daily.columns.get_level_values(0)

            df_daily = df_daily.dropna(subset=["Close"])
            if len(df_daily) < 30:
                return None

            close  = df_daily["Close"]
            high   = df_daily["High"]
            low    = df_daily["Low"]
            volume = df_daily["Volume"]
            n_bars = len(df_daily)

            # [TE-2 FIX] Threshold yang benar untuk daily data:
            # - ipo_mode  : < 30 bar (sama dengan weekly engine, ~1.5 bulan daily)
            # - data_limited: < 89 bar — EMA89 butuh tepat 89 bar untuk konvergen,
            #   bukan 180. 180 terlalu konservatif dan menyebabkan range 89-179 bar
            #   tidak masuk ipo_mode maupun data_limited padahal EMA89 belum konvergen.
            # - ema200_reliable tetap 250 bar (~1 tahun daily) — tidak berubah.
            ipo_mode     = n_bars < 30    # < 30 bar: hanya EMA5/13, konsisten dengan weekly engine
            data_limited = n_bars < 89    # EMA89 belum konvergen jika bar < 89

            # ── Standard EMAs (daily) ─────────────────────────────────────────
            ema5_s   = self._ema(close, 5)
            ema13_s  = self._ema(close, 13)
            ema89_s  = self._ema(close, 89)
            ema200_s = self._ema(close, 200)

            last_close  = _f(close.iloc[-1])
            last_ema5   = _f(ema5_s.iloc[-1])
            last_ema13  = _f(ema13_s.iloc[-1])
            last_ema89  = _f(ema89_s.iloc[-1])
            last_ema200 = _f(ema200_s.iloc[-1])
            ema200_reliable = n_bars >= 250  # ~1 tahun daily

            if ipo_mode:
                last_ema89  = last_ema13
                last_ema200 = last_ema13

            # ── VWEMA (daily) ─────────────────────────────────────────────────
            vw13 = vwema(close, volume, 13)
            vw89 = vwema(close, volume, 89)
            last_vwema13 = _f(vw13.iloc[-1]) if not vw13.isna().iloc[-1] else last_ema13
            last_vwema89 = _f(vw89.iloc[-1]) if not vw89.isna().iloc[-1] else last_ema89

            # ── Volume (daily) ────────────────────────────────────────────────
            vol_window = min(20, n_bars)
            vol_ma20   = _f(volume.rolling(vol_window).mean().iloc[-1])
            if vol_ma20 == 0 and n_bars >= 3:
                vol_ma20 = _f(volume.iloc[-vol_window:].mean())
            last_vol  = _f(volume.iloc[-1])
            vol_ratio = (last_vol / vol_ma20) if vol_ma20 > 0 else 0.0

            # ── ATR-14 (daily) ────────────────────────────────────────────────
            atr_series = compute_atr(high, low, close, 14)
            last_atr   = _f(atr_series.iloc[-1]) if not atr_series.isna().iloc[-1] else last_close * 0.015
            atr_pct    = last_atr / last_close * 100 if last_close > 0 else 1.5

            # ── Daily cross state ─────────────────────────────────────────────
            cross_state      = "BELOW"
            bars_since_cross = 0

            if last_ema13 > last_ema89:
                cross_state = "ABOVE"
                above_mask  = ema13_s.values > ema89_s.values
                false_idx   = np.where(~above_mask)[0]
                bars_since_cross = (
                    n_bars if len(false_idx) == 0
                    else n_bars - 1 - int(false_idx[-1])
                )
            elif abs(last_ema13 - last_ema89) / max(last_ema89, 1) < 0.005:
                cross_state = "CROSSING"

            # ── Weekly cross context (optional — untuk konfirmasi trend besar) ─
            weekly_cross = "UNKNOWN"
            if df_weekly is not None and len(df_weekly) >= 30:
                try:
                    if isinstance(df_weekly.columns, pd.MultiIndex):
                        df_weekly = df_weekly.copy()
                        df_weekly.columns = df_weekly.columns.get_level_values(0)
                    wc = df_weekly["Close"].dropna()
                    wema13 = _f(wc.ewm(span=13, adjust=False).mean().iloc[-1])
                    wema89 = _f(wc.ewm(span=89, adjust=False).mean().iloc[-1])
                    if wema13 > wema89:
                        weekly_cross = "ABOVE"
                    elif abs(wema13 - wema89) / max(wema89, 1) < 0.01:
                        weekly_cross = "CROSSING"
                    else:
                        weekly_cross = "BELOW"
                except Exception:
                    pass

            # ── Box detection (daily — lookback 20 hari) ──────────────────────
            lookback = min(20, n_bars - 1)

            roll_w = min(20, n_bars)
            rolling_range_pct = (
                (high.rolling(roll_w).max() - low.rolling(roll_w).min())
                / low.rolling(roll_w).min() * 100
            ).dropna()
            range_p80       = float(rolling_range_pct.quantile(0.80)) if len(rolling_range_pct) > 0 else 8.0
            dynamic_box_pct = max(2.0, min(atr_pct * 3.0, range_p80 * 0.75))

            recent_high   = _f(high.iloc[-lookback:].max())
            recent_low    = _f(low.iloc[-lookback:].min())
            box_range_pct = (recent_high - recent_low) / recent_low * 100 if recent_low > 0 else 999.0
            box_atr_mult  = box_range_pct / atr_pct if atr_pct > 0 else 99.0
            box_high      = recent_high
            box_low       = recent_low

            box_detected = (box_range_pct <= dynamic_box_pct and box_atr_mult <= 4.0)

            bars_in_range = 0
            if box_detected:
                for i in range(n_bars - 1, max(n_bars - lookback, 0), -1):
                    c = _f(close.iloc[i])
                    if box_low <= c <= box_high:
                        bars_in_range += 1
                    else:
                        break
                box_detected = box_detected and bars_in_range >= self.cfg.box_min_bars

            # ── Breakout detection (daily) ────────────────────────────────────
            prev_box_high     = _f(high.iloc[-lookback:-1].max()) if lookback > 1 else box_high
            breaking_out      = (
                last_close > prev_box_high
                and vol_ratio >= self.cfg.vol_mult
                and cross_state == "ABOVE"
            )
            strong_breaking_out = breaking_out and vol_ratio >= 3.0

            # ── RS vs IHSG ────────────────────────────────────────────────────
            rs_4w  = 0.0
            rs_sig = "N/A"
            if ihsg_df is not None and len(ihsg_df) >= 20:
                try:
                    if isinstance(ihsg_df.columns, pd.MultiIndex):
                        ihsg_df = ihsg_df.copy()
                        ihsg_df.columns = ihsg_df.columns.get_level_values(0)
                    ihsg_close = ihsg_df["Close"] if "Close" in ihsg_df.columns else ihsg_df.iloc[:, 0]
                    common = close.index.intersection(ihsg_close.index)
                    if len(common) >= 20:
                        stk_ret  = _f(close.loc[common[-1]] / close.loc[common[-20]] - 1) * 100
                        ihsg_ret = _f(ihsg_close.loc[common[-1]] / ihsg_close.loc[common[-20]] - 1) * 100
                        rs_4w    = round(stk_ret - ihsg_ret, 1)
                        rs_sig   = "STRONG" if rs_4w > 3 else "WEAK" if rs_4w < -3 else "NEUTRAL"
                except Exception:
                    pass

            # ── Regime tag ────────────────────────────────────────────────────
            regime_tag = {
                "BULL_TREND":        "FULL",
                "BULL_CONSOLIDATION":"FULL",
                "TRANSITION":        "SELECTIVE",
                "BEAR_CONSOLIDATION":"SPECULATIVE",
                "BEAR_TREND":        "WATCHLIST_ONLY",
            }.get(regime, "FULL")

            is_bear = regime_tag in ("WATCHLIST_ONLY", "SPECULATIVE")

            # ── Volume Profile ────────────────────────────────────────────────
            vp = compute_volume_profile(high, low, close, volume)

            # ── SCORE ─────────────────────────────────────────────────────────
            score = 0
            flags: list = []

            if ipo_mode:
                flags.append(f"⚡ IPO MODE daily: {n_bars} bars")
            elif data_limited:
                flags.append(f"⚠ DATA TERBATAS: {n_bars} daily bars (<89)")

            # (1) EMA cross daily
            if ipo_mode:
                if last_ema5 > last_ema13:
                    score += 2
                    flags.append("EMA5>EMA13 daily (IPO)")
            elif last_ema13 > last_ema89:
                score += 1
                flags.append("EMA13d>EMA89d")

            # (2) VWEMA confirmation daily
            if last_vwema13 > last_vwema89:
                score += 1
                flags.append("VWEMA13d>VWEMA89d")

            # (3) Price above EMA89 daily
            if last_close > last_ema89:
                score += 1
                flags.append("Price>EMA89d")

            # (4) Price above EMA200 daily
            if not ipo_mode and last_close > last_ema200:
                if ema200_reliable:
                    score += 1
                    flags.append("Price>EMA200d")
                else:
                    flags.append("⚠ EMA200d unstable (<250 bars)")

            # (5) Box / consolidation daily
            if box_detected:
                score += 1
                flags.append(f"Box daily {box_range_pct:.1f}% ({box_atr_mult:.1f}×ATR)")

            # (6) Volume daily
            if vol_ratio >= self.cfg.vol_mult:
                score += 1
                flags.append(f"Vol daily {vol_ratio:.1f}×")

            # (7) RS vs IHSG
            if rs_sig == "STRONG":
                score += 1
                flags.append(f"RS+{rs_4w:.1f}% vs IHSG")

            # (8) Volume Profile
            if vp.vp_score > 0:
                score += min(vp.vp_score, 1)
                flags.append(f"VP {vp.entry_zone} (+{min(vp.vp_score,1)})")

            # Weekly alignment bonus (+1 kalau weekly juga bullish)
            if weekly_cross == "ABOVE" and cross_state == "ABOVE":
                score += 1
                flags.append("Weekly+Daily aligned ✦")

            # ── Regime adjustments ────────────────────────────────────────────
            if is_bear and rs_4w < 0:
                score = max(0, score - 1)
                flags.append(f"⚠ RS negatif bear ({rs_4w:.1f}%) -1")

            if is_bear:
                try:
                    sl_est = last_close - 2 * last_atr
                    risk_e = ((last_close - sl_est) / last_close * 100) if sl_est > 0 else 0
                    if risk_e > 25:
                        score = max(0, score - 1)
                        flags.append(f"⚠ SL terlalu lebar ({risk_e:.0f}%) bear -1")
                except Exception:
                    pass

            # ── Fix v9.7.0 [Audit finding #6]: bull bonus DIHAPUS — sama
            # alasan seperti EMABreakoutEngine (lihat komentar di sana):
            # rs_sig STRONG + vol_ratio>=2.0 sudah dihitung di komponen (6)/(7),
            # bonus ini menguji ulang bukti yang sama, bukan konfirmasi baru.

            score = min(score, 10)

            # Simpan score_raw sebelum cap — dipakai di UI untuk komunikasi ke trader
            score_raw = score
            score_capped = False
            # ── (9)(10) v9.9.1: skala skor 8 → 10 ────────────────────────
            # (9) Struktur pasar HH_HL — sumbu swing, independen dari 4 slot EMA
            _ms_resist = 0.0
            try:
                _ms91 = analyze_market_structure(
                    close=close, high=high, low=low, vol=volume,
                    ema13=float(last_ema13), ema89=float(last_ema89),
                    ema13_series=close.ewm(span=13, adjust=False).mean(),
                    ema89_series=close.ewm(span=89, adjust=False).mean(),
                )
                if _ms91.get("structure") == "HH_HL":
                    score += 1
                    flags.append("Struktur HH_HL")
                _ms_resist = float(_ms91.get("ms_nearest_resist", 0) or 0)  # v9.9.5: reuse utk RR aktual
            except Exception:
                pass
            # (10) Konfirmasi dual timeframe — sumbu lintas-TF, satu-satunya
            if cross_state == "ABOVE" and weekly_cross == "ABOVE":
                score += 1
                flags.append("DUAL TF ✓")

            if regime_tag == "WATCHLIST_ONLY" and score > 4:
                flags.append("⚠ BEAR: score capped 3")
                score = min(score, 3)
                score_capped = True
            elif regime_tag == "SPECULATIVE" and score > 5:
                flags.append("⚠ BEAR_CONSOL: score capped 4")
                score = min(score, 4)
                score_capped = True

            # ── Signal classification ─────────────────────────────────────────
            if ipo_mode:
                if last_ema5 > last_ema13 and vol_ratio >= self.cfg.vol_mult and score >= 4:
                    signal = "BREAKOUT"
                elif last_ema5 > last_ema13 and score >= 3:
                    signal = "WATCHLIST"
                elif last_ema5 > last_ema13:
                    signal = "CORRECTING"
                else:
                    signal = "NONE"
            elif strong_breaking_out and score >= 7 and regime_tag != "WATCHLIST_ONLY":
                signal = "STRONG_BREAKOUT"
            elif breaking_out and score >= 4 and regime_tag != "WATCHLIST_ONLY":
                signal = "BREAKOUT"
            elif cross_state == "ABOVE" and box_detected and score >= 4:
                signal = "WATCHLIST"
            elif cross_state in ("ABOVE", "CROSSING") and last_close > last_ema89 * 0.95:
                signal = "CORRECTING"
            elif cross_state == "ABOVE" and last_close < last_ema89:
                signal = "DEEP_CORRECT"
            else:
                signal = "NONE"

            # ── Breakout type transparency (v9.7.0, additive — signal string TIDAK berubah) ──
            breakout_type = ""
            if signal in ("STRONG_BREAKOUT", "BREAKOUT"):
                breakout_type = "BOX" if box_detected else "MOMENTUM"
                flags.append(f"Breakout type: {breakout_type}")

            # RS downgrade
            if signal == "BREAKOUT" and rs_sig == "WEAK":
                signal = "WATCHLIST"
                breakout_type = ""
                flags.append("RS weak → downgrade WATCHLIST")

            # ── Risk levels ───────────────────────────────────────────────────
            entry_price = last_close
            sl_price    = (box_low * 0.99 if box_detected else entry_price - 2.0 * last_atr)
            risk        = max(entry_price - sl_price, last_atr * 0.5)
            risk_pct    = (risk / entry_price * 100) if entry_price > 0 else 0.0
            tp1_price   = entry_price + risk * _f(self.cfg.tp1_rr)
            tp2_price   = entry_price + risk * _f(self.cfg.tp2_rr)
            tp3_price   = entry_price + risk * _f(self.cfg.tp3_rr)
            rr_ratio    = round(_f(self.cfg.tp1_rr), 1)
            risk_sizing_ok = risk_pct <= 15.0

            # ── v9.9.5: RR AKTUAL dari resistance nyata (bukan echo config) ──
            # rr_ratio lama = konstanta tp1_rr digemakan balik → semua kartu 1.5.
            # RR aktual = (resistance terdekat − entry) / risk. Setup dengan
            # headroom mepet kini ketahuan RR rendahnya.
            rr_actual = 0.0
            if _ms_resist > entry_price and risk > 0:
                rr_actual = round((_ms_resist - entry_price) / risk, 2)
            # Filter RR_MIN_ENTRY: BREAKOUT di bawah ambang TIDAK dibuang,
            # tapi diturunkan ke WATCHLIST — visibilitas tetap, entry ditutup.
            if signal == "BREAKOUT" and rr_actual > 0 and rr_actual < RR_MIN_ENTRY:
                signal = "WATCHLIST"
                breakout_type = ""
                flags.append(f"RR aktual {rr_actual:.1f} < {RR_MIN_ENTRY} → WATCHLIST")

            if risk_pct > 25:
                flags.append(f"⚠ RISK {risk_pct:.0f}% — sizing sangat kecil")

            # ── Fix v9.6.9 [Audit finding #1]: daily_ok sebelumnya hardcoded
            # False permanen di sini — field ini TIDAK PERNAH dihitung untuk
            # path DailyEMAEngine (yang notabene default engine untuk hampir
            # semua ticker). Akibatnya kolom "Daily?" dan color indicator di
            # UI selalu mati walau signal/score tetap benar (dual_confirmed
            # dihitung terpisah, tidak kena bug ini).
            # Fix: reuse check_daily_entry() yang sudah ada — bukan
            # reimplementasi logic baru, supaya semantik identik dengan
            # path weekly-fallback di scanner_agent.py.
            _daily_entry = check_daily_entry(df_daily, weekly_cross)

            # ── Assemble result dict ──────────────────────────────────────────
            return {
                # Identity
                "ticker":          ticker,
                "signal":          signal,
                "score":           score,
                "date":            str(df_daily.index[-1])[:10],  # tanggal bar daily terakhir
                "regime_tag":      regime_tag,

                # Price
                "close":           last_close,
                "open_":           _f(df_daily["Open"].iloc[-1]) if "Open" in df_daily.columns else 0.0,
                "high":            _f(high.iloc[-1]),
                "low":             _f(low.iloc[-1]),

                # EMAs (daily)
                "ema5":            last_ema5,
                "ema13":           last_ema13,
                "ema89":           last_ema89,
                "ema200":          last_ema200,
                "ema200_reliable": ema200_reliable,
                "vwema13":         last_vwema13,
                "vwema89":         last_vwema89,

                # Cross state (daily primary)
                "cross_state":     cross_state,
                "bars_since_cross":bars_since_cross,
                "weekly_cross":    weekly_cross,   # konteks, bukan primary

                # Box
                "box_high":        box_high,
                "box_low":         box_low,
                "box_range_pct":   box_range_pct,
                "box_atr_multiple":box_atr_mult,
                "bars_in_range":   bars_in_range,

                # Volume
                "volume":          last_vol,
                "vol_ma20":        vol_ma20,
                "vol_ratio":       vol_ratio,

                # RS
                "rs_vs_ihsg_4w":   rs_4w,
                "rs_signal":       rs_sig,

                # ATR / exit
                # [TE-6 FIX] holding_days_est: pakai dist_to_tp1 / ATR seperti
                # EMABreakoutEngine, bukan formula 3/atr_pct yang tidak masuk akal.
                # Formula lama: ATR 2% → 3/0.02 = 150 hari (terlalu besar).
                # Formula baru: dist ke TP1 dibagi ATR per bar = estimasi hari wajar.
                "atr14":           last_atr,
                "trail_stop_1atr": entry_price - last_atr,
                "trail_stop_2atr": entry_price - 2 * last_atr,
                # Fix v9.6.9 [Audit finding #3]: exit_ema_break sebelumnya
                # last_ema13 tanpa buffer — beda dari EMABreakoutEngine yang
                # pakai buffer 2% (round(last_ema13*0.98,0)) supaya tidak
                # whipsaw. Disamakan di sini karena DailyEMAEngine adalah
                # engine primary — exit warning jangan lebih agresif dari
                # desain aslinya cuma karena engine berbeda.
                "exit_ema_break":  round(last_ema13 * 0.98, 0),
                "holding_days_est":int((tp1_price - entry_price) / last_atr) if last_atr > 0 else 10,

                # Risk
                "entry_price":     entry_price,
                "sl_price":        sl_price,
                "tp1_price":       tp1_price,
                "tp2_price":       tp2_price,
                "tp3_price":       tp3_price,
                "risk_pct":        risk_pct,
                "rr_ratio":        rr_ratio,
                "rr_actual":       rr_actual,
                "risk_sizing_ok":  risk_sizing_ok,

                # SMC (placeholder — scanner_agent runs MS separately)
                "smc_trend":       "UNKNOWN",
                "smc_score":       0,

                # Volume Profile
                "vp_poc":          vp.poc,
                "vp_vah":          vp.vah,
                "vp_val":          vp.val,
                "vp_score":        vp.vp_score,
                "vp_entry_zone":   vp.entry_zone,

                # Flags / notes
                "flags":           flags,
                "data_limited":    data_limited,
                "ipo_mode":        ipo_mode,
                "score_raw":       score_raw,
                "score_capped":    score_capped,
                "breakout_type":   breakout_type,

                # daily fields — sekarang dihitung sungguhan via check_daily_entry(),
                # bukan stub. "engine_source" (bukan "daily_pattern") dipakai
                # sebagai marker routing di scanner_agent.py, supaya daily_pattern
                # tetap berisi nilai deskriptif asli (DAILY_GOLDEN_CROSS dkk)
                # yang memang diharapkan UI (page 1 cek substring "WAIT" di sana).
                "engine_source":   "DAILY_PRIMARY",
                "daily_ok":        _daily_entry.get("daily_ok", False),
                "daily_pattern":   _daily_entry.get("daily_pattern", "DAILY_PRIMARY"),
                "daily_cross":     _daily_entry.get("daily_cross", cross_state),
                "fresh_cross":     _daily_entry.get("fresh_cross", bars_since_cross == 1),
                "ema5_cross":      _daily_entry.get("ema5_cross", False),
                "ema5d":           _daily_entry.get("ema5d", last_ema5),
                "ema13d":          _daily_entry.get("ema13d", last_ema13),
                "ema89d":          _daily_entry.get("ema89d", last_ema89),
                "pct_vs_ema13d":   _daily_entry.get("pct_vs_ema13d",
                                       ((last_close - last_ema13) / last_ema13 * 100) if last_ema13 > 0 else 0.0),
                "pct_vs_ema89d":   _daily_entry.get("pct_vs_ema89d",
                                       ((last_close - last_ema89) / last_ema89 * 100) if last_ema89 > 0 else 0.0),
                "vol_ratio_d":     _daily_entry.get("vol_ratio_d", vol_ratio),
                "daily_entry_note":_daily_entry.get("daily_entry_note", "Daily engine — EMA13/89 daily primary"),
                "dual_confirmed":  (cross_state == "ABOVE" and weekly_cross == "ABOVE"),
                "score_max":       10,  # v9.9.1
            }

        except Exception as exc:
            import logging as _lg
            _lg.getLogger(__name__).debug(f"[DailyEMAEngine] {ticker}: {exc}")
            return None
