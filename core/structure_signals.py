"""
core/structure_signals.py — ADITIF, murni tambahan baca-saja.

TIDAK mengubah core/ob_engine.py, core/conviction_engine.py, agents/zone_scanner.py,
atau pipeline produksi lain manapun. File ini hanya IMPORT beberapa helper murni
(_LegState, _PivotState, _compute_atr) dari core/ob_engine.py supaya definisi
leg/pivot/ATR identik dengan yang sudah divalidasi di pipeline conviction —
bukan reimplementasi paralel yang bisa drift dari situ.

Port bagian Pine "Volumatic VIDYA + SMC [Combined]" (BigBeluga + LuxAlgo,
CC BY-NC-SA 4.0) yang SENGAJA belum diikutkan ke core/ob_engine.py Fase 1
(lihat docstring modul itu, baris "TIDAK diport"):
  - Internal Bullish BOS / CHoCH   (biru — port dari displayStructure(internal=true))
  - Swing Bullish BOS / CHoCH      (biru — port dari displayStructure(internal=false))
  - Equal Low / EQL                (biru — port dari getCurrentStructure(eq)+drawEqualHighLow())

HANYA sisi bullish/biru yang di-port, sesuai kebutuhan user. Sisi bearish/kuning
(BOS/CHoCH bearish, EQH) SENGAJA tidak diimplementasikan di sini — di luar scope.
Bias trend (internal/swing) tetap dihitung dua arah secara internal karena BOS vs
CHoCH bullish butuh tahu apakah bias sebelumnya BEARISH (→ CHoCH) atau sudah
BULLISH (→ BOS) — persis logika `t_rend.bias` di Pine — tapi event bearish itu
sendiri tidak pernah dikeluarkan sebagai StructureEvent.

Definisi "crossed" (breakout) di sini mengikuti konvensi yang SUDAH dipakai
core/ob_engine.py (bukan ta.crossover Pine yang ketat): "close > level dan
belum pernah crossed" — dipilih supaya konsisten dengan definisi yang sudah
production, bukan mendefinisikan ulang secara berbeda (lihat catatan di
core/ob_engine.py baris ~317-320).

KONTRAK ANTI-LOOKAHEAD: sama seperti ob_engine.py — walk-forward loop eksplisit,
bar i HANYA memakai data 0..i.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from core.ob_engine import _LegState, _PivotState, _compute_atr, BULLISH, BEARISH


@dataclass
class StructureEvent:
    bar_index: int
    date:      object
    kind:      str    # "BOS" | "CHOCH" | "EQL"
    scope:     str    # "internal" | "swing" | ""  (EQL tidak dipisah internal/swing di Pine asli)
    level:     float
    close:     float


@dataclass
class StructureSignals:
    ticker:                   str
    events:                   list = field(default_factory=list)  # urut waktu naik
    internal_trend_bias:      Optional[int] = None   # BULLISH(1)/BEARISH(-1)/None — state akhir
    swing_trend_bias:         Optional[int] = None
    last_internal_high_pivot: Optional[float] = None
    last_swing_high_pivot:    Optional[float] = None
    last_equal_low_pivot:     Optional[float] = None

    def latest(self, kind: Optional[str] = None, scope: Optional[str] = None, n: int = 10) -> list:
        evs = self.events
        if kind:
            evs = [e for e in evs if e.kind == kind]
        if scope is not None:
            evs = [e for e in evs if e.scope == scope]
        return evs[-n:]


def compute_bullish_structure(
    df: pd.DataFrame,
    ticker:        str = "",
    internal_size: int = 5,
    swing_size:    int = 50,
    eq_size:       int = 3,     # = equalHighsLowsLengthInput default Pine
    eq_threshold:  float = 0.1, # = equalHighsLowsThresholdInput default Pine
    atr_length:    int = 200,
) -> Optional[StructureSignals]:
    """
    Walk-forward, mirror displayStructure() + getCurrentStructure(equalHighLow=true)
    + drawEqualHighLow() Pine asli — HANYA sisi bullish (BOS biru, CHoCH biru, EQL biru).

    df wajib kolom Open/High/Low/Close/Volume, index tanggal urut naik (sama
    kontrak dengan core/ob_engine.run_engine()).
    """
    if df is None or len(df) < max(swing_size, internal_size, eq_size) + 5:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)

    high  = df["High"]; low = df["Low"]; close = df["Close"]
    n     = len(df)
    atr200 = _compute_atr(high, low, close, atr_length)

    leg_internal = _LegState()
    leg_swing    = _LegState()
    leg_eq       = _LegState()

    internal_high = _PivotState(); internal_low = _PivotState()
    swing_high    = _PivotState(); swing_low    = _PivotState()
    equal_low     = _PivotState()

    internal_bias: Optional[int] = None
    swing_bias:    Optional[int] = None

    int_highest = high.rolling(internal_size).max(); int_lowest = low.rolling(internal_size).min()
    swg_highest = high.rolling(swing_size).max();    swg_lowest = low.rolling(swing_size).min()
    eq_highest  = high.rolling(eq_size).max();       eq_lowest  = low.rolling(eq_size).min()

    events: list[StructureEvent] = []

    for i in range(n):
        c     = float(close.iloc[i])
        atr_i = float(atr200.iloc[i]) if not np.isnan(atr200.iloc[i]) else 0.0

        # ── Leg + pivot: INTERNAL (size default 5) — identik pola ob_engine.py ──
        if i >= internal_size and not np.isnan(int_highest.iloc[i]):
            back = i - internal_size
            hb = float(high.iloc[back]); lb = float(low.iloc[back])
            prev_leg = leg_internal.leg
            new_leg  = leg_internal.step(hb, lb, float(int_highest.iloc[i]), float(int_lowest.iloc[i]))
            if new_leg != prev_leg or (i == internal_size):
                if new_leg == BULLISH:
                    internal_low.last_level    = internal_low.current_level
                    internal_low.current_level = lb
                    internal_low.crossed       = False
                    internal_low.bar_index     = back
                elif new_leg == BEARISH:
                    internal_high.last_level    = internal_high.current_level
                    internal_high.current_level = hb
                    internal_high.crossed       = False
                    internal_high.bar_index     = back

        # ── Leg + pivot: SWING (size default 50) — identik pola ob_engine.py ──
        if i >= swing_size and not np.isnan(swg_highest.iloc[i]):
            back = i - swing_size
            hb = float(high.iloc[back]); lb = float(low.iloc[back])
            prev_leg = leg_swing.leg
            new_leg  = leg_swing.step(hb, lb, float(swg_highest.iloc[i]), float(swg_lowest.iloc[i]))
            if new_leg != prev_leg or (i == swing_size):
                if new_leg == BULLISH:
                    swing_low.last_level    = swing_low.current_level
                    swing_low.current_level = lb
                    swing_low.crossed       = False
                    swing_low.bar_index     = back
                elif new_leg == BEARISH:
                    swing_high.last_level    = swing_high.current_level
                    swing_high.current_level = hb
                    swing_high.crossed       = False
                    swing_high.bar_index     = back

        # ── Leg + pivot: EQUAL LOW (size default 3, threshold ATR-relatif) ──
        # Port getCurrentStructure(eq_size, equalHighLow=true) — HANYA cabang
        # pivotLow (EQL/biru); cabang pivotHigh (EQH/kuning) sengaja diskip.
        if i >= eq_size and not np.isnan(eq_lowest.iloc[i]):
            back = i - eq_size
            lb = float(low.iloc[back])
            prev_leg = leg_eq.leg
            new_leg  = leg_eq.step(float(high.iloc[back]), lb, float(eq_highest.iloc[i]), float(eq_lowest.iloc[i]))
            if new_leg != prev_leg or (i == eq_size):
                if new_leg == BULLISH:
                    # Bandingkan thd level pivot SEBELUM di-update (persis Pine:
                    # p_ivot.currentLevel dicek dulu, baru ditimpa).
                    if (not np.isnan(equal_low.current_level)
                            and abs(equal_low.current_level - lb) < eq_threshold * atr_i):
                        events.append(StructureEvent(
                            bar_index=i, date=df.index[i], kind="EQL",
                            scope="", level=lb, close=c,
                        ))
                    equal_low.last_level    = equal_low.current_level
                    equal_low.current_level = lb
                    equal_low.crossed       = False
                    equal_low.bar_index     = back
                # cabang BEARISH (equal high) sengaja tidak diproses

        # ── Breakout/BOS-CHoCH INTERNAL — bullish dulu (urutan sama Pine) ──
        if (not internal_high.crossed and not np.isnan(internal_high.current_level)
                and c > internal_high.current_level):
            internal_high.crossed = True
            tag = "CHOCH" if internal_bias == BEARISH else "BOS"
            events.append(StructureEvent(
                bar_index=i, date=df.index[i], kind=tag, scope="internal",
                level=internal_high.current_level, close=c,
            ))
            internal_bias = BULLISH
        # bearish break — HANYA update bias, tidak pernah emit event (kuning, di luar scope)
        if (not internal_low.crossed and not np.isnan(internal_low.current_level)
                and c < internal_low.current_level):
            internal_low.crossed = True
            internal_bias = BEARISH

        # ── Breakout/BOS-CHoCH SWING ──
        if (not swing_high.crossed and not np.isnan(swing_high.current_level)
                and c > swing_high.current_level):
            swing_high.crossed = True
            tag = "CHOCH" if swing_bias == BEARISH else "BOS"
            events.append(StructureEvent(
                bar_index=i, date=df.index[i], kind=tag, scope="swing",
                level=swing_high.current_level, close=c,
            ))
            swing_bias = BULLISH
        if (not swing_low.crossed and not np.isnan(swing_low.current_level)
                and c < swing_low.current_level):
            swing_low.crossed = True
            swing_bias = BEARISH

    events.sort(key=lambda e: e.bar_index)

    return StructureSignals(
        ticker=ticker,
        events=events,
        internal_trend_bias=internal_bias,
        swing_trend_bias=swing_bias,
        last_internal_high_pivot=None if np.isnan(internal_high.current_level) else round(internal_high.current_level, 2),
        last_swing_high_pivot=None if np.isnan(swing_high.current_level) else round(swing_high.current_level, 2),
        last_equal_low_pivot=None if np.isnan(equal_low.current_level) else round(equal_low.current_level, 2),
    )
