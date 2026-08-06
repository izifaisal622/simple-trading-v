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
    bars_since_vidya_flip: Optional[int] = None  # v10.5.0 ADITIF — jarak bar
    # dari event vidya_flipped_up TERAKHIR (lihat EngineState di ob_engine.py)
    # ke bar ini. None kalau belum pernah ada flip sepanjang histori sampai
    # bar ini. MURNI INFORMATIF — belum dipakai di _score() sama sekali,
    # skor conviction_pct/vidya_pct TIDAK berubah dari sebelumnya.
    zone_ordinal_since_flip: Optional[int] = None  # v10.5.2 ADITIF — zona
    # KE BERAPA yg terbentuk sejak flip vidya_flipped_up TERAKHIR (1 = zona
    # pertama setelah flip, 2 = zona kedua tanpa ada flip baru di antaranya,
    # dst). None kalau zona ini terbentuk sebelum ada flip sama sekali di
    # histori, atau kalau bar ini tidak sedang di dalam zona aktif mana pun.
    # DIBEKUKAN saat zona terbentuk (persis pola origin_low/origin_atr di
    # _ActiveZone) — tidak berubah lagi sepanjang umur zona itu.
    #
    # LATAR BELAKANG (v10.5.1 -> v10.5.2, koreksi arah): validasi awal
    # bars_since_vidya_flip (v10.5.0/10.5.1) mengurutkan dari angka TERKECIL
    # sbg kandidat "golden setup" -- user cross-check manual ke TradingView
    # (BBCA, flip 12 Jun 2026 -> OB terbentuk 1 Jul -> entry 2 Jul, jarak
    # ~30 bar 4h) dan itu duduk di sekitar MEDIAN (35) distribusi, BUKAN di
    # ekor angka kecil (0-2) yg saya tampilkan sbg "contoh terdekat".
    # bars_since_vidya_flip=0 artinya flip & retest terjadi di bar YANG SAMA
    # (V-turn instan) -- kasus ekstrem, bukan representasi pola user (flip
    # dulu, harga masih lanjut turun bikin koreksi/OB, baru retest belakangan).
    # zone_ordinal_since_flip=1 lebih dekat scr struktural ke pola user:
    # "zona PERTAMA yg terbentuk & di-retest sejak flip terakhir", TERLEPAS
    # dari berapa lama jaraknya scr bar (bisa 10 bar, bisa 50 bar, tergantung
    # dalamnya koreksi) -- beda dari bars_since_vidya_flip yg ukur DURASI,
    # ordinal ini ukur URUTAN. MASIH BELUM dipakai di _score() -- perlu
    # cross-check visual ulang dulu sblm jadi dasar bobot skor apa pun.
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
    zone_ordinal_since_flip: Optional[int] = None  # v10.5.2 — dibekukan SAAT zona terbentuk



def _score(zone: _ActiveZone, current_close: float,
           extension_safe_atr: float = EXTENSION_SAFE_ATR,
           extension_penalty_per_atr: float = EXTENSION_PENALTY_PER_ATR) -> tuple:
    """Hitung breakdown skor. Return (total, base, retest, vidya, vol, struct,
    extension_penalty, extension_atr).

    v10.4.2 BARU: extension_safe_atr & extension_penalty_per_atr kini PARAMETER
    opsional (default = konstanta modul EXTENSION_SAFE_ATR/EXTENSION_PENALTY_
    PER_ATR, sama persis dgn sebelumnya — ZERO perubahan perilaku utk semua
    caller lama/jalur daily produksi). Alasan: studi distribusi extension_atr
    di cadence 4h (5 ticker sample, 2026-08-06) menunjukkan P75=10.65x vs P75
    daily=7.36x yg jadi dasar kalibrasi 8.0 — ambang 8.0 menangkap 42% data
    4h (niat desain aslinya ~25%, lihat 10.3.7). Constraint eksplisit user:
    JANGAN ubah 8.0 di jalur daily (produksi, data historis zone_scans sudah
    dikalibrasi thd itu) — jalur 4h lewatkan nilai sendiri (~10.5, MASIH
    PROVISIONAL, cuma dari 5 ticker vs 334 zona utk kalibrasi daily)."""
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
        excess = max(0.0, extension_atr - extension_safe_atr)
        extension_penalty = min(EXTENSION_MAX_PENALTY, round(excess * extension_penalty_per_atr))

    total = max(0, min(100, base + retest + vidya_pct + volume_pct + struct_pct - extension_penalty))
    return total, base, retest, vidya_pct, volume_pct, struct_pct, extension_penalty, round(extension_atr, 2)


def run_conviction(df: pd.DataFrame,
                   extension_safe_atr: float = EXTENSION_SAFE_ATR,
                   extension_penalty_per_atr: float = EXTENSION_PENALTY_PER_ATR,
                   **engine_kwargs) -> list:
    """Walk-forward penuh: ob_engine tahap 1 -> state machine conviction.
    Return list[ConvictionState], satu per bar. df wajib kolom OHLCV standar.

    v10.4.2: extension_safe_atr/extension_penalty_per_atr diteruskan ke
    _score() — default TIDAK berubah dari sebelumnya (backward compatible
    penuh utk jalur daily). Lihat docstring _score() utk alasan lengkap."""
    engine_states = run_engine(df, **engine_kwargs)

    out = []
    active: Optional[_ActiveZone] = None
    last_seen_pivot_bar = -1  # utk deteksi "pivot internal baru" (zona kandidat baru)
    last_flip_bar: Optional[int] = None  # v10.5.0 ADITIF — bar_index event vidya_flipped_up terakhir
    ordinal_flip_ref: Optional[int] = None  # v10.5.2 ADITIF — last_flip_bar SAAT ordinal counter terakhir dipakai
    ordinal_counter: int = 0  # v10.5.2 ADITIF — zona ke berapa sejak ordinal_flip_ref

    for i, es in enumerate(engine_states):
        close = es.close
        low_i = float(df["Low"].iloc[i])
        status = STATE_IDLE
        note = ""

        # v10.5.0 ADITIF — update penanda flip TERAKHIR, hitung jaraknya ke bar ini
        if getattr(es, "vidya_flipped_up", False):
            last_flip_bar = i
        bars_since_flip = (i - last_flip_bar) if last_flip_bar is not None else None

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
                # v10.5.2 ADITIF — hitung ordinal zona sejak flip terakhir, dibekukan
                if last_flip_bar is None:
                    zone_ordinal = None
                elif last_flip_bar == ordinal_flip_ref:
                    ordinal_counter += 1
                    zone_ordinal = ordinal_counter
                else:
                    ordinal_flip_ref = last_flip_bar
                    ordinal_counter = 1
                    zone_ordinal = ordinal_counter

                active = _ActiveZone(
                    top=es.ob_candidate_top, bottom=es.ob_candidate_bottom,
                    formed_bar_index=i, pivot_bar_index=es.internal_high.bar_index,
                    origin_low=es.trailing_bottom, origin_atr=es.atr200,
                    zone_ordinal_since_flip=zone_ordinal,
                )
                last_seen_pivot_bar = es.internal_high.bar_index
                status = STATE_WATCHING
                note = "zona baru terbentuk"


        # ── 3) Hitung skor kalau ada zona aktif ──
        if active is not None:
            total, base, retest, vidya_pct, vol_pct, struct_pct, ext_pen, ext_atr = _score(
                active, close, extension_safe_atr, extension_penalty_per_atr)
            out.append(ConvictionState(
                bar_index=i, date=es.date, close=close, status=status,
                zone_top=active.top, zone_bottom=active.bottom,
                formed_bar_index=active.formed_bar_index,
                retest_hold_days=active.retest_hold_days,
                conviction_pct=total, base_pct=base, retest_pct=retest,
                vidya_pct=vidya_pct, volume_pct=vol_pct, structure_pct=struct_pct,
                extension_penalty=ext_pen, extension_atr=ext_atr,
                bars_since_vidya_flip=bars_since_flip,
                zone_ordinal_since_flip=active.zone_ordinal_since_flip,
                note=note,
            ))
        else:
            out.append(ConvictionState(
                bar_index=i, date=es.date, close=close, status=status,
                conviction_pct=0, bars_since_vidya_flip=bars_since_flip, note=note,
            ))

    return out
