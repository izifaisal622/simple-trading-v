"""
core/conviction_engine.py — Tahap 2: state machine conviction 20%→100%
di atas core.ob_engine (tahap 1, teruji anti-lookahead).

SKEMA (disepakati eksplisit dgn user, tidak boleh diubah tanpa persetujuan):
  20%  zona terbentuk (kandidat OB bullish internal dari ob_engine)
  40%  retest hold 1 candle  (close >= zona_bottom saat low masuk ke zona)
  60%  retest hold 2 candle  (retest DIHENTIKAN di sini — bukan diperpanjang linear)
  +15% VIDYA is_trend_up=True pada bar retest terakhir
  +15% volume delta positif; kalau retest>=2 hari, delta hari-2 > hari-1 (menguat)
  +10% struktur internal & swing leg SAMA-SAMA bullish pada bar retest terakhir
  Max  100%

ATURAN KERAS (konfirmasi user, verbatim):
  - Retest divalidasi thd HARGA REAL (bukan Heikin Ashi).
  - Retest hold: low bar menyentuh zona (low <= zona_top) DAN close >= zona_bottom.
  - close < zona_bottom kapan pun (bahkan setelah conviction naik) → INVALIDASI
    TOTAL, conviction reset ke 0%, zona dibuang.
  - Zona TIDAK ikut bergeser setelah pertama dibekukan. Kalau muncul low baru
    yang lebih rendah SEBELUM retest pertama terjadi, itu dianggap gagal
    (zona lama tidak pernah diuji) — direset, menunggu pivot/zona baru dari
    engine tahap 1.
  - Kadaluarsa: 5 hari bursa (~1 minggu kalender) sejak zona terbentuk TANPA
    mencapai retest cap (2 hari hold) → EXPIRED, conviction reset ke 0%.
  - Retest adalah SATU-SATUNYA jalur ke conviction tinggi (tidak ada jalur
    breakout-cepat-tanpa-retest yg bisa capai skor tinggi). Trade-off yg
    diterima sadar oleh user: breakout asli tanpa pullback akan selalu
    bernilai rendah dalam skema ini.

KONTRAK ANTI-LOOKAHEAD: sama seperti ob_engine — walk-forward eksplisit,
setiap keputusan di bar i hanya memakai data 0..i. Diuji truncation-invariant.
"""

from dataclasses import dataclass, field as dc_field
from typing import Optional

import pandas as pd

from core.ob_engine import run_engine, BULLISH

RETEST_CAP_DAYS = 2
EXPIRY_BARS = 5  # hari bursa

# v10.3.6 — EXTENSION-MOVE PENALTY (freeze discontinued sadar oleh user utk
# bulan ini, per instruksi eksplisit "bangun sistem terkuat"). Motivasi:
# formula skor SEBELUMNYA memperlakukan retest setelah naik 10% SAMA PERSIS
# dgn retest setelah naik 200%. User menunjukkan kasus nyata (RGAS, retest
# dekat 'Weak High' setelah rally ~3x) di mana conviction 100% terasa tak
# masuk akal scr visual.
#
# extension_atr = (close - origin_low) / atr_saat_zona_terbentuk
# origin_low = trailing_bottom (swing low level SWING/50-bar) SAAT zona
# terbentuk — ini SENGAJA beda skala dgn zona itu sendiri (level internal/
# 5-bar): origin perlu merepresentasikan "dari mana RALLY BESAR dimulai",
# bukan cuma tepi zona retest lokal (sempat dicoba pakai zona.bottom sendiri,
# TERBUKTI salah konsep — retest valid SELALU dekat zona.bottom by definisi,
# jadi penalti jadi nyaris selalu 0, menghapus tujuan fitur ini).
# v10.3.7 KALIBRASI ULANG — berbasis distribusi NYATA 334 zona produksi
# (2026-08-01, lihat diagnose_extension_distribution.py): ambang lama 3.0
# TERBUKTI menghukum 74% populasi (median populasi 4.49x SUDAH di atas
# ambang "aman" 3.0 itu sendiri) — bukan menyaring outlier, tapi menghukum
# perilaku NORMAL. Statistik: P10=1.54 P25=2.92 P50=4.49 P75=7.36 P90=12.07
# max=38.57. Ambang baru 8.0 (~P75) — hanya kuartil paling ekstensif kena
# penalti. Laju per-ATR diturunkan 8->5 spy gradasi lebih halus mengikuti
# ekor distribusi panjang (RGAS dkk sampai 22-38x), tak langsung mentok cap.
# CATATAN: kalibrasi ini dari SATU hari snapshot (334 zona), bukan baseline
# statistik jangka panjang — kandidat kuat utk ditinjau ulang stlh beberapa
# minggu data zone_scans terkumpul, sama spt semangat freeze yg lain.
EXTENSION_SAFE_ATR       = 8.0
EXTENSION_MAX_PENALTY    = 25
EXTENSION_PENALTY_PER_ATR = 5

STATE_WATCHING = "WATCHING"
STATE_INVALIDATED = "INVALIDATED"
STATE_EXPIRED = "EXPIRED"
STATE_SUPERSEDED = "SUPERSEDED"  # pivot internal digantikan pivot baru (mekanisme Pine asli)
STATE_IDLE = "IDLE"  # belum ada zona aktif sama sekali


@dataclass
class ConvictionState:
    bar_index: int
    date: object
    close: float
    status: str                       # IDLE / WATCHING / INVALIDATED / EXPIRED
    zone_top: Optional[float] = None
    zone_bottom: Optional[float] = None
    formed_bar_index: Optional[int] = None
    retest_hold_days: int = 0
    conviction_pct: int = 0
    # breakdown transparan — untuk audit & debugging, bukan cuma angka akhir
    base_pct: int = 0
    retest_pct: int = 0
    vidya_pct: int = 0
    volume_pct: int = 0
    structure_pct: int = 0
    extension_penalty: int = 0        # v10.4.0 BARU
    extension_atr: float = 0.0        # v10.4.0 BARU
    note: str = ""


@dataclass
class _ActiveZone:
    top: float
    bottom: float
    formed_bar_index: int
    pivot_bar_index: int   # bar_index internal_high SAAT zona dibekukan — utk deteksi supersesi
    retest_hold_days: int = 0
    retest_deltas: list = dc_field(default_factory=list)  # delta_volume_pct tiap hari retest
    last_vidya_up: Optional[bool] = None
    last_struct_ok: bool = False
    origin_low: float = float("nan")   # v10.4.0 — trailing_bottom SAAT zona terbentuk (dibekukan)
    origin_atr: float = float("nan")   # v10.4.0 — atr200 SAAT zona terbentuk (dibekukan)



def _score(zone: _ActiveZone, current_close: float) -> tuple:
    """Hitung breakdown skor. Return (total, base, retest, vidya, vol, struct,
    extension_penalty, extension_atr)."""
    base = 20
    retest_days_capped = min(zone.retest_hold_days, RETEST_CAP_DAYS)
    retest = 20 * retest_days_capped

    vidya_pct = 0
    if zone.retest_hold_days > 0 and zone.last_vidya_up is True:
        vidya_pct = 15

    volume_pct = 0
    if zone.retest_hold_days > 0:
        if zone.retest_hold_days == 1:
            if zone.retest_deltas and zone.retest_deltas[-1] > 0:
                volume_pct = 15
        else:
            if len(zone.retest_deltas) >= 2 and zone.retest_deltas[-1] > 0 and zone.retest_deltas[-1] > zone.retest_deltas[-2]:
                volume_pct = 15

    struct_pct = 10 if (zone.retest_hold_days > 0 and zone.last_struct_ok) else 0

    extension_atr = 0.0
    extension_penalty = 0
    if zone.origin_atr and zone.origin_atr > 0 and not (zone.origin_atr != zone.origin_atr):
        extension_atr = (current_close - zone.origin_low) / zone.origin_atr
        excess = max(0.0, extension_atr - EXTENSION_SAFE_ATR)
        extension_penalty = min(EXTENSION_MAX_PENALTY, round(excess * EXTENSION_PENALTY_PER_ATR))

    total = max(0, min(100, base + retest + vidya_pct + volume_pct + struct_pct - extension_penalty))
    return total, base, retest, vidya_pct, volume_pct, struct_pct, extension_penalty, round(extension_atr, 2)


def run_conviction(df: pd.DataFrame, **engine_kwargs) -> list:
    """Walk-forward penuh: ob_engine tahap 1 -> state machine conviction.
    Return list[ConvictionState], satu per bar. df wajib kolom OHLCV standar."""
    engine_states = run_engine(df, **engine_kwargs)

    out = []
    active: Optional[_ActiveZone] = None
    last_seen_pivot_bar = -1  # utk deteksi "pivot internal baru" (zona kandidat baru)

    for i, es in enumerate(engine_states):
        close = es.close
        low_i = float(df["Low"].iloc[i])
        status = STATE_IDLE
        note = ""

        # ── 1) Kalau ada zona aktif, evaluasi dulu ──
        if active is not None:
            # v10.1 FIX: cek SUPERSESI dulu — mekanisme Pine asli menimpa
            # internalHigh tanpa syarat begitu leg(5) deteksi puncak baru,
            # TERLEPAS dari apakah pivot lama sudah crossed/retest atau belum.
            # Tanpa cek ini, zona kita bisa menggantung bertahun-tahun (bug
            # nyata: GOTO/ANTM WATCHING 470+ hari) walau di indikator Pine
            # aslinya preview sudah lama berpindah ke pivot yg lebih baru.
            if es.internal_high.bar_index != active.pivot_bar_index:
                active = None
                status = STATE_SUPERSEDED
                note = "pivot internal digantikan pivot baru"
            elif close < active.bottom:
                # INVALIDASI TOTAL — aturan keras user, kapan pun terjadi
                active = None
                status = STATE_INVALIDATED
                note = "close < zona_bottom"
            else:
                is_retest_touch = (low_i <= active.top) and (close >= active.bottom)
                if is_retest_touch and active.retest_hold_days < RETEST_CAP_DAYS:
                    active.retest_hold_days += 1
                    active.retest_deltas.append(es.delta_volume_pct)
                    active.last_vidya_up = es.is_trend_up
                    active.last_struct_ok = (es.internal_leg == BULLISH and es.swing_leg == BULLISH)
                elif is_retest_touch:
                    # sudah di cap 2 hari — tetap update konteks (vidya/vol/struct)
                    # dari bar TERBARU supaya skor mencerminkan kondisi terkini,
                    # tapi retest_hold_days tidak nambah lagi (sudah cap).
                    active.retest_deltas.append(es.delta_volume_pct)
                    active.last_vidya_up = es.is_trend_up
                    active.last_struct_ok = (es.internal_leg == BULLISH and es.swing_leg == BULLISH)

                # Cek kadaluarsa — HANYA kalau belum capai retest cap
                bars_since_formed = i - active.formed_bar_index
                if active.retest_hold_days < RETEST_CAP_DAYS and bars_since_formed >= EXPIRY_BARS:
                    active = None
                    status = STATE_EXPIRED
                    note = f"kadaluarsa {EXPIRY_BARS} hari bursa tanpa retest cap"
                else:
                    status = STATE_WATCHING

        # ── 2) Kalau tidak ada zona aktif, cek apakah engine kasih kandidat baru ──
        if active is None and status not in (STATE_INVALIDATED, STATE_EXPIRED, STATE_SUPERSEDED):
            if (es.ob_candidate_top is not None and es.ob_candidate_bottom is not None
                    and es.internal_high.bar_index != last_seen_pivot_bar):
                # Pivot internal BARU (bar_index berubah) DAN kandidat zona ada
                # → bekukan sebagai zona aktif. Zona TIDAK ikut bergeser lagi
                # setelah titik ini (aturan keras user).
                active = _ActiveZone(
                    top=es.ob_candidate_top, bottom=es.ob_candidate_bottom,
                    formed_bar_index=i, pivot_bar_index=es.internal_high.bar_index,
                    origin_low=es.trailing_bottom, origin_atr=es.atr200,
                )
                last_seen_pivot_bar = es.internal_high.bar_index
                status = STATE_WATCHING
                note = "zona baru terbentuk"


        # ── 3) Hitung skor kalau ada zona aktif ──
        if active is not None:
            total, base, retest, vidya_pct, vol_pct, struct_pct, ext_pen, ext_atr = _score(active, close)
            out.append(ConvictionState(
                bar_index=i, date=es.date, close=close, status=status,
                zone_top=active.top, zone_bottom=active.bottom,
                formed_bar_index=active.formed_bar_index,
                retest_hold_days=active.retest_hold_days,
                conviction_pct=total, base_pct=base, retest_pct=retest,
                vidya_pct=vidya_pct, volume_pct=vol_pct, structure_pct=struct_pct,
                extension_penalty=ext_pen, extension_atr=ext_atr,
                note=note,
            ))
        else:
            out.append(ConvictionState(
                bar_index=i, date=es.date, close=close, status=status,
                conviction_pct=0, note=note,
            ))

    return out
