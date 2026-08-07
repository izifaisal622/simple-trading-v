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


def _compute_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """v10.6.0 ADITIF — derive OHLC Heikin Ashi dari OHLC REAL. Rekursif
    (HA_Open bar i butuh HA_Open & HA_Close bar i-1) — walk-forward loop,
    causal by construction (bar i cuma pakai data 0..i, sama spt _vidya_calc).

    LATAR BELAKANG: user membaca chart pribadinya via tampilan Heikin Ashi
    (candle di-average, garis VIDYA jadi mulus/tidak flicker). Dibuktikan
    scr empiris (toggle chart TradingView Candlestick vs HA, indikator
    VIDYA+SMC yg sama): garis VIDYA MEMANG flicker kalau dihitung dari
    harga real candlestick biasa (candle 12/15/25 Jun 2026 -- tiga event
    crossover terpisah dlm ~2 minggu), TAPI smooth/1x transisi bersih kalau
    dihitung dari HA. Fungsi ini dipakai HANYA utk basis VIDYA/band trend
    (lihat use_ha_trend di VidyaSmcEngine) -- retest, invalidasi, ATR200
    extension-penalty, swing/internal leg pivot TETAP di harga real (hard
    rule lama: entry/exit tidak boleh divalidasi thd harga sintetis yg
    tidak bisa ditransaksikan)."""
    o = df["Open"].to_numpy(dtype=float)
    h = df["High"].to_numpy(dtype=float)
    l = df["Low"].to_numpy(dtype=float)
    c = df["Close"].to_numpy(dtype=float)
    n = len(df)

    ha_close = (o + h + l + c) / 4.0
    ha_open = np.empty(n)
    for i in range(n):
        if i == 0:
            ha_open[i] = (o[i] + c[i]) / 2.0
        else:
            ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2.0
    ha_high = np.maximum(h, np.maximum(ha_open, ha_close))
    ha_low = np.minimum(l, np.minimum(ha_open, ha_close))

    return pd.DataFrame({
        "Open": ha_open, "High": ha_high, "Low": ha_low, "Close": ha_close,
    }, index=df.index)


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
    vidya_flipped_up: bool = False  # v10.5.0: ADITIF — True HANYA di bar
    # crossover is_trend_up False/None->True (event, bukan state). is_trend_up
    # sendiri sudah ada sejak awal tapi cuma expose STATE ("VIDYA lagi hijau
    # atau tidak"), bukan EVENT ("baru saja belok hijau di bar ini"). Dipakai
    # Fase 3 utk beda kan "golden setup" (flip segar dekat retest) vs "sudah
    # hijau lama, retest cuma pullback rutin di tren mapan") — TANPA ubah
    # deteksi crossover yg sudah ada, cuma nambah observasi di titik yg sama.


class VidyaSmcEngine:
    """Walk-forward simulator. run(df) mengembalikan list[EngineState],
    satu per bar, masing2 HANYA memakai data sampai bar itu (causal)."""

    def __init__(self, vidya_length: int = 10, vidya_momentum: int = 20,
                 band_distance: float = 2.0, internal_size: int = 5,
                 swing_size: int = 50, atr_length: int = 200,
                 vol_filter_mult: float = 2.0, use_ha_trend: bool = False):
        self.vidya_length = vidya_length
        self.vidya_momentum = vidya_momentum
        self.band_distance = band_distance
        self.internal_size = internal_size
        self.swing_size = swing_size
        self.atr_length = atr_length
        self.vol_filter_mult = vol_filter_mult
        self.use_ha_trend = use_ha_trend  # v10.6.0 ADITIF — default False = ZERO
        # perubahan perilaku thd semua caller lama/jalur daily produksi. True:
        # VIDYA & band-ATR (yg nentuin is_trend_up/vidya_flipped_up) dihitung
        # dari Heikin Ashi (lihat _compute_heikin_ashi). Swing/internal leg
        # pivot, OB candidate zone, atr200 (extension-penalty), delta volume
        # TETAP dari harga REAL, tidak terpengaruh flag ini sama sekali.

    def run(self, df: pd.DataFrame) -> list:
        """df wajib kolom: Open, High, Low, Close, Volume — index tanggal urut naik."""
        n = len(df)
        high = df["High"]; low = df["Low"]; close = df["Close"]; vol = df["Volume"]

        atr200 = _compute_atr(high, low, close, self.atr_length)  # TETAP real,
        # dipakai vol_measure/parsed_high-low (OB candidate) & EngineState.atr200
        # (extension-penalty Fase 2) -- use_ha_trend TIDAK menyentuh nilai ini.

        if self.use_ha_trend:
            # v10.6.0 ADITIF — VIDYA & band-ATR dari basis Heikin Ashi, supaya
            # is_trend_up/vidya_flipped_up smooth spt yg dibaca user di chart
            # HA-nya (dibuktikan flicker di real candle, lihat changelog).
            ha_df = _compute_heikin_ashi(df)
            trend_close = ha_df["Close"]
            atr_band = _compute_atr(ha_df["High"], ha_df["Low"], ha_df["Close"], self.atr_length)
        else:
            trend_close = close
            atr_band = atr200  # perilaku LAMA persis — band pakai atr200 real

        vidya_val = _vidya_calc(trend_close, self.vidya_length, self.vidya_momentum)
        upper_band = vidya_val + atr_band * self.band_distance
        lower_band = vidya_val - atr_band * self.band_distance

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
            c = float(close.iloc[i])  # real close -- EngineState.close, volume delta, dll TETAP ini

            # ── VIDYA crossover/crossunder (causal: cuma current vs prev) ──
            # v10.6.0: trend_close = HA close kalau use_ha_trend=True, else = c (real,
            # perilaku lama persis). Perbandingan crossover pakai trend_close, BUKAN c,
            # supaya smoothing HA konsisten (harga & band sama-sama basis HA saat aktif).
            tc = float(trend_close.iloc[i])
            vidya_flipped_up = False  # v10.5.0: reset tiap bar, cuma True di bar event-nya sendiri
            if i > 0 and not np.isnan(upper_band.iloc[i]) and not np.isnan(upper_band.iloc[i - 1]):
                prev_tc = float(trend_close.iloc[i - 1])
                if prev_tc <= upper_band.iloc[i - 1] and tc > upper_band.iloc[i]:
                    is_trend_up = True
                    vidya_flipped_up = True
                if prev_tc >= lower_band.iloc[i - 1] and tc < lower_band.iloc[i]:
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
                vidya_flipped_up=vidya_flipped_up,
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
