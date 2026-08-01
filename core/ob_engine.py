"""
core/ob_engine.py — Tahap 1: Volumatic VIDYA + SMC (subset) walk-forward engine.

Port dari Pine v6 "Volumatic VIDYA + SMC [Combined]" (BigBeluga + LuxAlgo,
CC BY-NC-SA 4.0) — HANYA subset yang dipakai skema conviction retest-zone:

  - VIDYA trend (is_trend_up) + volume delta (up/down_trend_volume)
  - Leg/pivot detection dua skala: internal (5-bar), swing (50-bar default)
  - Kandidat OB bullish internal (replikasi storeOrdeBlock + OB Preview add-on)
  - Trailing top/bottom (utk premium/discount context, tahap 2)

TIDAK diport (di luar scope skema conviction): SMC CHoCH/BOS drawing,
Equal High/Low, Fair Value Gaps, level multi-timeframe, OB bearish/swing.

KONTRAK ANTI-LOOKAHEAD (wajib dipegang semua kontributor kode ini):
Setiap nilai pada bar i HANYA boleh dihitung dari bar 0..i. Simulator berjalan
sebagai walk-forward loop eksplisit meniru model eksekusi Pine per-bar,
BUKAN operasi vectorized yang diam-diam mengintip bar masa depan. Fungsi
run_engine() diuji wajib truncation-invariant: state pada bar i harus
IDENTIK baik dataframe dipotong sampai bar i maupun dipakai penuh.
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


BULLISH = 1
BEARISH = -1


# ─────────────────────────────────────────────────────────────────────────
# Precompute VEKTORIZED yang aman — semua nilai di bar i hanya bergantung
# pada bar 0..i (rolling/ewm pandas secara native causal, tidak lookahead).
# Loop walk-forward tetap dipakai untuk state yang punya "memory" antar-bar
# non-trivial (leg/pivot/crossed/candidate-zone) — itu paling rawan bug
# lookahead kalau divectorize sembarangan, jadi sengaja loop eksplisit.
# ─────────────────────────────────────────────────────────────────────────

def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 200) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    # Pine ta.atr pakai RMA (Wilder smoothing) — alpha = 1/length
    return tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def _vidya_calc(src: pd.Series, length: int, momentum: int) -> pd.Series:
    """Port vidya_calc — CMO-weighted adaptive EMA, lalu SMA(15) smoothing.
    Rekursif (bergantung nilai VIDYA bar sebelumnya) — walk-forward loop,
    causal by construction (tidak ada akses ke src[i+1:])."""
    momentum_diff = src.diff()
    pos_mom = momentum_diff.clip(lower=0.0)
    neg_mom = (-momentum_diff).clip(lower=0.0)
    sum_pos = pos_mom.rolling(momentum).sum()
    sum_neg = neg_mom.rolling(momentum).sum()
    denom = (sum_pos + sum_neg).replace(0, np.nan)
    abs_cmo = (100 * (sum_pos - sum_neg) / denom).abs()
    alpha = 2.0 / (length + 1)

    n = len(src)
    vidya = np.zeros(n)
    src_v = src.values
    cmo_v = abs_cmo.fillna(0).values
    for i in range(n):
        a = alpha * cmo_v[i] / 100.0
        prev = vidya[i - 1] if i > 0 else 0.0
        vidya[i] = a * src_v[i] + (1 - a) * prev
    vidya_s = pd.Series(vidya, index=src.index)
    return vidya_s.rolling(15).mean()


@dataclass
class _LegState:
    """Port fungsi leg(size) — var leg=0 per call-site (internal & swing
    punya instance terpisah, PERSIS semantik Pine: dua pemanggilan leg()
    dgn size berbeda = dua state independen)."""
    leg: int = 0

    def step(self, high_back: float, low_back: float,
              highest_win: float, lowest_win: float) -> int:
        new_leg_high = high_back > highest_win
        new_leg_low = low_back < lowest_win
        if new_leg_high:
            self.leg = BEARISH  # leg berbalik turun setelah high baru
        elif new_leg_low:
            self.leg = BULLISH
        return self.leg


@dataclass
class _PivotState:
    current_level: float = np.nan
    last_level: float = np.nan
    crossed: bool = False
    bar_index: int = -1


@dataclass
class EngineState:
    """Snapshot output di satu bar — inilah yang dikonsumsi tahap 2."""
    bar_index: int
    date: object
    close: float
    is_trend_up: Optional[bool]
    delta_volume_pct: float
    internal_high: _PivotState
    internal_low: _PivotState
    swing_high: _PivotState
    swing_low: _PivotState
    ob_candidate_top: Optional[float]      # kandidat zona bullish internal OB
    ob_candidate_bottom: Optional[float]
    ob_trigger_level: Optional[float]      # = internal_high.current_level saat belum crossed
    trailing_top: float
    trailing_bottom: float
    internal_leg: int = 0   # BULLISH(1)/BEARISH(-1) — arah leg internal terkini
    swing_leg: int = 0      # BULLISH(1)/BEARISH(-1) — arah leg swing terkini
    atr200: float = float("nan")  # v10.4.0: ADITIF — expose ATR yg sudah dihitung causal
    # (rolling/ewm, lihat _compute_atr) sbg output, TANPA ubah komputasi yg
    # sudah ada. Dipakai tahap 2 utk extension-move penalty (seberapa jauh
    # harga sudah lari dari swing low asal leg, dinormalisasi ATR).


class VidyaSmcEngine:
    """Walk-forward simulator. run(df) mengembalikan list[EngineState],
    satu per bar, masing2 HANYA memakai data sampai bar itu (causal)."""

    def __init__(self, vidya_length: int = 10, vidya_momentum: int = 20,
                 band_distance: float = 2.0, internal_size: int = 5,
                 swing_size: int = 50, atr_length: int = 200,
                 vol_filter_mult: float = 2.0):
        self.vidya_length = vidya_length
        self.vidya_momentum = vidya_momentum
        self.band_distance = band_distance
        self.internal_size = internal_size
        self.swing_size = swing_size
        self.atr_length = atr_length
        self.vol_filter_mult = vol_filter_mult

    def run(self, df: pd.DataFrame) -> list:
        """df wajib kolom: Open, High, Low, Close, Volume — index tanggal urut naik."""
        n = len(df)
        high = df["High"]; low = df["Low"]; close = df["Close"]; vol = df["Volume"]

        atr200 = _compute_atr(high, low, close, self.atr_length)
        vidya_val = _vidya_calc(close, self.vidya_length, self.vidya_momentum)
        upper_band = vidya_val + atr200 * self.band_distance
        lower_band = vidya_val - atr200 * self.band_distance

        # Volatility-filtered parsedHigh/parsedLow (dipakai kandidat OB)
        vol_measure = atr200
        high_vol_bar = (high - low) >= (self.vol_filter_mult * vol_measure)
        parsed_high = np.where(high_vol_bar, low, high)
        parsed_low = np.where(high_vol_bar, high, low)

        # Rolling highest/lowest utk leg() — window size mencakup bar saat ini
        int_highest = high.rolling(self.internal_size).max()
        int_lowest = low.rolling(self.internal_size).min()
        swg_highest = high.rolling(self.swing_size).max()
        swg_lowest = low.rolling(self.swing_size).min()

        leg_internal = _LegState()
        leg_swing = _LegState()
        internal_high = _PivotState(); internal_low = _PivotState()
        swing_high = _PivotState(); swing_low = _PivotState()

        # VIDYA trend state (var is_trend_up)
        is_trend_up: Optional[bool] = None
        up_vol = 0.0
        down_vol = 0.0
        prev_trend_up = None

        trailing_top = -np.inf
        trailing_bottom = np.inf

        out = []
        for i in range(n):
            c = float(close.iloc[i])

            # ── VIDYA crossover/crossunder (causal: cuma current vs prev) ──
            if i > 0 and not np.isnan(upper_band.iloc[i]) and not np.isnan(upper_band.iloc[i - 1]):
                prev_c = float(close.iloc[i - 1])
                if prev_c <= upper_band.iloc[i - 1] and c > upper_band.iloc[i]:
                    is_trend_up = True
                if prev_c >= lower_band.iloc[i - 1] and c < lower_band.iloc[i]:
                    is_trend_up = False

            # ── Volume delta — reset saat trend berubah (persis Pine) ──
            trend_changed = (is_trend_up != prev_trend_up)
            if trend_changed:
                up_vol = 0.0
                down_vol = 0.0
            else:
                o = float(df["Open"].iloc[i])
                v = float(vol.iloc[i])
                if c > o:
                    up_vol += v
                elif c < o:
                    down_vol += v
            prev_trend_up = is_trend_up
            avg_delta = (up_vol + down_vol) / 2.0
            delta_pct = ((up_vol - down_vol) / avg_delta * 100.0) if avg_delta > 0 else 0.0

            # ── Leg + pivot: INTERNAL (size=5) ──
            if i >= self.internal_size and not np.isnan(int_highest.iloc[i]):
                back = i - self.internal_size
                hb = float(high.iloc[back]); lb = float(low.iloc[back])
                prev_leg = leg_internal.leg
                new_leg = leg_internal.step(hb, lb, float(int_highest.iloc[i]), float(int_lowest.iloc[i]))
                if new_leg != prev_leg or (i == self.internal_size):
                    if new_leg == BULLISH:
                        internal_low.last_level = internal_low.current_level
                        internal_low.current_level = lb
                        internal_low.crossed = False
                        internal_low.bar_index = back
                    elif new_leg == BEARISH:
                        internal_high.last_level = internal_high.current_level
                        internal_high.current_level = hb
                        internal_high.crossed = False
                        internal_high.bar_index = back

            # ── Leg + pivot: SWING (size=50 default) ──
            if i >= self.swing_size and not np.isnan(swg_highest.iloc[i]):
                back = i - self.swing_size
                hb = float(high.iloc[back]); lb = float(low.iloc[back])
                prev_leg = leg_swing.leg
                new_leg = leg_swing.step(hb, lb, float(swg_highest.iloc[i]), float(swg_lowest.iloc[i]))
                if new_leg != prev_leg or (i == self.swing_size):
                    if new_leg == BULLISH:
                        swing_low.last_level = swing_low.current_level
                        swing_low.current_level = lb
                        swing_low.crossed = False
                        swing_low.bar_index = back
                        trailing_bottom = lb
                    elif new_leg == BEARISH:
                        swing_high.last_level = swing_high.current_level
                        swing_high.current_level = hb
                        swing_high.crossed = False
                        swing_high.bar_index = back
                        trailing_top = hb

            # ── Crossed-state: internal_high ditembus close (BOS/CHoCH) ──
            if (not internal_high.crossed and not np.isnan(internal_high.current_level)
                    and c > internal_high.current_level):
                internal_high.crossed = True

            # ── Kandidat OB bullish internal (replikasi storeOrdeBlock) ──
            ob_top = ob_bottom = ob_trigger = None
            if not internal_high.crossed and not np.isnan(internal_high.current_level):
                ob_trigger = internal_high.current_level
                piv_idx = internal_high.bar_index
                if piv_idx >= 0 and piv_idx < i:
                    window_low = parsed_low[piv_idx:i + 1]
                    window_high = parsed_high[piv_idx:i + 1]
                    cand_rel = int(np.argmin(window_low))
                    ob_top = float(window_high[cand_rel])
                    ob_bottom = float(window_low[cand_rel])

            # Update trailing (dipakai premium/discount tahap 2)
            hi = float(high.iloc[i]); lo = float(low.iloc[i])
            if hi > trailing_top:
                trailing_top = hi
            if lo < trailing_bottom:
                trailing_bottom = lo

            out.append(EngineState(
                bar_index=i, date=df.index[i], close=c,
                is_trend_up=is_trend_up, delta_volume_pct=delta_pct,
                internal_high=_PivotState(**vars(internal_high)),
                internal_low=_PivotState(**vars(internal_low)),
                swing_high=_PivotState(**vars(swing_high)),
                swing_low=_PivotState(**vars(swing_low)),
                ob_candidate_top=ob_top, ob_candidate_bottom=ob_bottom,
                ob_trigger_level=ob_trigger,
                trailing_top=trailing_top, trailing_bottom=trailing_bottom,
                internal_leg=leg_internal.leg, swing_leg=leg_swing.leg,
                atr200=float(atr200.iloc[i]) if not np.isnan(atr200.iloc[i]) else float("nan"),
            ))
        return out


def run_engine(df: pd.DataFrame, **kwargs) -> list:
    return VidyaSmcEngine(**kwargs).run(df)
