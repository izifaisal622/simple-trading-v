"""
Simple Trading V9 — Single Stock Analysis Agent
================================================
Analisis mendalam untuk SATU saham tertentu.

Menggabungkan:
  1. EMA-XBO Analysis   — trend, signal, score, entry timing, MCF
  2. Follow Whale       — accumulation, conviction, floor price, defense
  3. MSCI Context       — apakah sedang di rebalancing window
  4. Overall Grade      — A/B/C/D berdasarkan gabungan kedua lensa

Dipakai oleh pages/3_Stock_Analysis.py.
Tidak memfilter berdasarkan threshold — selalu kembalikan data penuh.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


logger   = logging.getLogger(__name__)
LOGS_DIR = Path(__file__).parent.parent / "logs"


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StockAnalysis:
    ticker:  str = ""
    date:    str = ""
    error:   str = ""

    # ── EMA-XBO ─────────────────────────────────────────────────────────────
    signal:           str   = "NONE"    # BREAKOUT / WATCHLIST / COMPRESSING / CORRECTING / DEEP_CORRECT
    ema_score:        int   = 0         # 0–7
    regime_tag:       str   = ""        # FULL / SELECTIVE / SPECULATIVE / WATCHLIST_ONLY
    cross_state:      str   = ""        # ABOVE / CROSSING / BELOW
    bars_since_cross: int   = 0

    close:     float = 0.0
    ema5:      float = 0.0
    ema13:     float = 0.0
    ema89:     float = 0.0
    ema200:    float = 0.0
    ema200_reliable: bool = True

    entry_price: float = 0.0
    sl_price:    float = 0.0
    tp1_price:   float = 0.0
    tp2_price:   float = 0.0
    risk_pct:    float = 0.0
    rr_ratio:    float = 0.0
    risk_sizing_ok: bool = True

    vol_ratio:   float = 0.0
    rs_vs_ihsg:  float = 0.0
    rs_signal:   str   = "N/A"

    # Daily entry
    daily_ok:       bool = False
    daily_pattern:  str  = ""
    dual_confirmed: bool = False

    # MCF
    mcf_score:     int   = 0
    mcf_label:     str   = "—"
    mcf_entry_ok:  bool  = False
    mcf_bear_blocked: bool = False

    # Liquidity
    liquidity_bn:  float = 0.0   # avg daily value traded (Rp Bn)

    # Market structure
    ms_label:      str   = ""
    ms_score:      int   = 0
    smc_trend:     str   = ""

    flags:         list  = field(default_factory=list)

    # ── Zone Conviction (v10.1 — REPLACE TOTAL, ganti EMA-XBO lama) ────────────
    zone_status:        str   = "IDLE"   # WATCHING/IDLE/INVALIDATED/EXPIRED/SUPERSEDED
    conviction_pct:     int   = 0        # 0-100
    zone_top:           float = 0.0
    zone_bottom:        float = 0.0
    retest_hold_days:   int   = 0
    zone_base_pct:      int   = 0
    zone_retest_pct:    int   = 0
    zone_vidya_pct:     int   = 0
    zone_volume_pct:    int   = 0
    zone_structure_pct: int   = 0

    # ── Whale ───────────────────────────────────────────────────────────────
    whale_ok:          bool  = False    # True jika data whale tersedia
    activity_type:     str   = "UNKNOWN"
    whale_quality:     str   = "—"
    conviction:        int   = 0        # 0–10
    vol_ratio_whale:   float = 0.0
    floor_price:       float = 0.0
    entry_zone:        str   = "UNKNOWN"
    whale_defending:   bool  = False
    pengeringan:       bool  = False
    peng_strength:     int   = 0
    ema_trend_whale:   str   = "UNKNOWN"
    momentum:          str   = "UNKNOWN"
    harga_terlalu_jauh: bool = False
    market_sepi:       bool  = False
    in_ob_zone:        bool  = False

    # Hitung Barang
    total_lot:         int   = 0
    control_score:     int   = 0
    whale_signal:      str   = "—"

    # ── MSCI ────────────────────────────────────────────────────────────────
    msci_active:       bool  = False
    msci_alert_level:  str   = ""
    msci_conviction:   int   = 0
    msci_t_minus:      int   = 0
    msci_entry_note:   str   = ""

    # ── Overall Grade ────────────────────────────────────────────────────────
    overall_score:  int  = 0     # 0–100
    grade:          str  = "?"   # A / B / C / D / F
    grade_reasons:  list = field(default_factory=list)
    action_label:   str  = "—"   # ENTRY NOW / WATCHLIST / MONITOR / AVOID


# ─────────────────────────────────────────────────────────────────────────────
# Core analysis
# ─────────────────────────────────────────────────────────────────────────────

def analyze_single(ticker: str) -> StockAnalysis:
    """
    Analisis lengkap satu saham. Returns StockAnalysis.
    Tidak memfilter — selalu kembalikan data meski tidak ada sinyal entry.
    """
    from datetime import date as _date
    a = StockAnalysis(ticker=ticker.upper().replace(".JK",""),
                      date=str(_date.today()))

    try:
        _run_ema_xbo(a, ticker)
    except Exception as exc:
        logger.warning(f"[SingleStock] EMA error {ticker}: {exc}")
        a.flags.append(f"EMA ERROR: {exc}")

    try:
        _run_whale(a, ticker)
    except Exception as exc:
        logger.warning(f"[SingleStock] Whale error {ticker}: {exc}")
        a.flags.append(f"WHALE ERROR: {exc}")

    try:
        _run_msci(a)
    except Exception:
        pass  # MSCI optional

    _compute_overall(a)
    return a


# ─────────────────────────────────────────────────────────────────────────────
# EMA-XBO sub-analysis
# ─────────────────────────────────────────────────────────────────────────────

def _run_ema_xbo(a: StockAnalysis, ticker: str):
    """v10.1 — REPLACE TOTAL: technical_engine (DailyEMAEngine/EMABreakoutEngine
    box-breakout+MCF Hengky) diganti core.conviction_engine (VIDYA+SMC
    retest-zone, sama persis dgn zone_scanner.py). Engine lama & seluruh
    turunannya (dual_confirmed, mcf_score, cross_state) tidak lagi punya
    padanan semantik — field StockAnalysis lama itu DIBIARKAN default (0/False)
    utk kompatibilitas struktur, TIDAK diisi lagi. Field zone_* baru menampung
    hasil sistem baru; page 4 UI perlu disesuaikan menampilkan field baru ini
    (belum dikerjakan di sesi ini)."""
    from core.data_feed import DataFeed, get_ihsg_regime
    from core.conviction_engine import run_conviction

    feed_d = DataFeed(timeframe="1d", period="2y")  # sama persis dgn zone_scanner.py
    df_d = feed_d.fetch(ticker)

    if df_d is None or len(df_d) < 260:  # MIN_BARS_REQUIRED sama dgn zone_scanner
        a.error = f"Data harian tidak cukup untuk {ticker} (butuh >=260 bar utk ATR200+swing50)"
        return

    if isinstance(df_d.columns, pd.MultiIndex):
        df_d.columns = df_d.columns.get_level_values(0)

    # v10.1: FIX bug key sama spt page 1 — get_ihsg_regime() pakai key "cycle",
    # bukan "regime" (selalu diam2 balik "UNKNOWN" sebelumnya, tak pernah crash
    # krn .get() dgn default, tapi salah nilai).
    regime_data = get_ihsg_regime()
    a.regime_tag = regime_data.get("cycle", "UNKNOWN")

    try:
        states = run_conviction(df_d, internal_size=5, swing_size=50)
    except Exception as exc:
        a.error = f"Zone engine gagal analisis {ticker}: {exc}"
        return

    latest = states[-1]
    a.close = latest.close
    a.zone_status        = latest.status
    a.conviction_pct      = latest.conviction_pct
    a.zone_top            = latest.zone_top or 0.0
    a.zone_bottom         = latest.zone_bottom or 0.0
    a.retest_hold_days    = latest.retest_hold_days
    a.zone_base_pct       = latest.base_pct
    a.zone_retest_pct     = latest.retest_pct
    a.zone_vidya_pct      = latest.vidya_pct
    a.zone_volume_pct     = latest.volume_pct
    a.zone_structure_pct  = latest.structure_pct

    # a.signal dipertahankan sbg ringkasan sederhana utk kompatibilitas kode
    # lama yg mungkin masih membaca field ini (mis. filter WATCHLIST/BREAKOUT
    # di tempat lain) — dipetakan dari status zona, bukan konsep yg identik.
    a.signal = "WATCHLIST" if latest.status == "WATCHING" and latest.conviction_pct >= 40 else "NONE"


# ─────────────────────────────────────────────────────────────────────────────
# Whale sub-analysis (NO vol threshold filter)
# ─────────────────────────────────────────────────────────────────────────────

def _run_whale(a: StockAnalysis, ticker: str):
    from agents.whale_scanner import (
        estimate_floor_price, detect_pengeringan,
        hitung_barang, test_whale_defense,
        classify_whale_quality, compute_conviction,
        classify_signal, detect_order_block,
    )
    from core.data_feed import DataFeed

    feed = DataFeed(timeframe="1d")
    df   = feed.fetch(ticker, period="90d", interval="1d")

    if df is None or len(df) < 30:
        return

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    required = ["Close","Volume","High","Low","Open"]
    if not all(c in df.columns for c in required):
        return

    df = df[df["Close"] > 0].dropna(subset=["Close","Volume"])
    if len(df) < 30:
        return

    vol   = df["Volume"]
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]

    ma_period = 20
    vol_ma    = float(vol.rolling(ma_period).mean().iloc[-1])
    if vol_ma < 100:
        return

    last_vol  = float(vol.iloc[-1])
    vol_ratio = (last_vol / vol_ma) if vol_ma > 0 else 0.0

    last_close = float(close.iloc[-1])
    chg_pct    = float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100
                       ) if len(close) >= 2 else 0.0

    # ── Core whale calculations ──────────────────────────────────────────────
    floor_data    = estimate_floor_price(close, vol, low)
    floor_price   = floor_data.get("floor_price", last_close * 0.9)
    entry_zone    = floor_data.get("entry_zone", "FAR_FROM_FLOOR")

    peng_data     = detect_pengeringan(close, vol, high, low)
    pengeringan   = peng_data.get("detected", False)
    peng_strength = peng_data.get("strength", 0)

    barang_data   = hitung_barang(vol, close, high, low)
    control_score = barang_data.get("control_score", 0)
    total_lot     = barang_data.get("total_lot_est", 0)

    defense_data  = test_whale_defense(close, vol, low, high)
    defending     = defense_data.get("defending", False)
    defense_days  = defense_data.get("defense_days", 0)

    ob_data       = detect_order_block(close, high, low, vol)
    in_ob_zone    = ob_data.get("in_ob_zone", False)
    near_ob_zone  = ob_data.get("near_ob_zone", False)

    # EMA trend (simple)
    ema13 = float(close.ewm(span=13, adjust=False).mean().iloc[-1])
    ema89 = float(close.ewm(span=89, adjust=False).mean().iloc[-1])
    ema_trend = "BULLISH" if ema13 > ema89 else "BEARISH"

    # Momentum
    mom_window = min(5, len(close))
    if mom_window >= 3:
        recent_vol  = float(vol.iloc[-mom_window:].mean())
        prev_vol    = float(vol.iloc[-mom_window*2:-mom_window].mean()) if len(vol) > mom_window*2 else recent_vol
        recent_chg  = float(close.pct_change().iloc[-mom_window:].mean())
        if recent_vol > prev_vol * 1.3 and recent_chg > 0:
            momentum = "ACCELERATING"
        elif close.iloc[-1] > close.iloc[-2] and close.iloc[-2] < close.iloc[-3]:
            momentum = "REVERSING"
        elif recent_chg < -0.005:
            momentum = "DECLINING"
        else:
            momentum = "NEUTRAL"
    else:
        momentum = "NEUTRAL"

    # Pattern
    if pengeringan and defending:
        pattern = "SUSTAINED"
    elif pengeringan or defending:
        pattern = "EMERGING"
    else:
        pattern = "SINGLE"

    r = {
        "entry_zone":           entry_zone,
        "pengeringan_detected": pengeringan,
        "pengeringan_strength": peng_strength,
        "whale_defending":      defending,
        "defense_days":         defense_days,
        "pattern":              pattern,
        "ema_trend":            ema_trend,
        "momentum":             momentum,
        "control_score":        control_score,
        "in_ob_zone":           in_ob_zone,
        "near_ob_zone":         near_ob_zone,
        "ms_conviction_boost":  0,
    }

    quality    = classify_whale_quality(r)
    conviction   = compute_conviction(r, vol_ratio)
    sig_tuple    = classify_signal(vol_ratio, chg_pct, peng_data, defense_data)
    signal       = sig_tuple[0] if isinstance(sig_tuple, tuple) else str(sig_tuple)

    # Distance from floor
    dist_pct = ((last_close - floor_price) / floor_price * 100) if floor_price > 0 else 999
    too_far  = dist_pct > 25

    # Market liquidity check
    sepi = (vol_ma < 1_000_000 and vol_ratio < 0.8)

    # ── Store results ────────────────────────────────────────────────────────
    a.whale_ok         = True
    a.activity_type    = signal
    a.whale_quality    = quality
    a.conviction       = conviction
    a.vol_ratio_whale  = vol_ratio
    a.floor_price      = floor_price
    a.entry_zone       = entry_zone
    a.whale_defending  = defending
    a.pengeringan      = pengeringan
    a.peng_strength    = peng_strength
    a.ema_trend_whale  = ema_trend
    a.momentum         = momentum
    a.harga_terlalu_jauh = too_far
    a.market_sepi      = sepi
    a.in_ob_zone       = in_ob_zone
    a.total_lot        = total_lot
    a.control_score    = control_score
    a.whale_signal     = signal
    a.liquidity_bn     = round(float((close.tail(5) * vol.tail(5)).mean() / 1e9), 3)


# ─────────────────────────────────────────────────────────────────────────────
# MSCI context
# ─────────────────────────────────────────────────────────────────────────────

def _run_msci(a: StockAnalysis):
    from agents.msci_agent import get_ticker_msci_alert, get_active_events
    active = get_active_events()
    if not active:
        return
    alert = get_ticker_msci_alert(a.ticker)
    if alert:
        a.msci_active      = True
        a.msci_alert_level = alert.get("alert_level", "")
        a.msci_conviction  = alert.get("msci_conviction", 0)
        a.msci_t_minus     = alert.get("t_minus", 0)
        a.msci_entry_note  = alert.get("entry_note", "")
    elif active:
        a.msci_active = True  # window aktif tapi ticker bukan candidate


# ─────────────────────────────────────────────────────────────────────────────
# Overall grade computation — Two-Axis System v8.7.9
# ─────────────────────────────────────────────────────────────────────────────
# Arsitektur: EMA Score (0-50) × Whale Score (0-50) → Grade via matrix 2×2
#
# Prinsip:
#   EMA  Kuat (≥25) + Whale Kuat (≥25) → A  (konfirmasi penuh)
#   EMA  Kuat       + Whale Lemah       → B  (teknikal bagus, tapi tanpa smart money)
#   EMA  Lemah      + Whale Kuat (≥25)  → C  (whale early, tunggu EMA)
#   Keduanya Lemah                      → D/F
#
# Konvergensi dengan Follow Whale:
#   Follow Whale ENTRY VALID → Whale Score hampir pasti ≥25 → minimal Grade C
#   Tidak ada lagi kontradiksi "FW bilang masuk, SA bilang hindari"

def _compute_overall(a: StockAnalysis):
    reasons = []

    # ════════════════════════════════════════════════════════════════════════
    # AXIS 1 — ZONE CONVICTION SCORE (0–50) — v10.1 REPLACE TOTAL
    # conviction_pct (0-100, dari VIDYA+SMC retest-zone engine) sudah
    # komprehensif (base+retest+vidya+volume+struktur) — diskalakan langsung
    # ke 0-50, MENGGANTIKAN seluruh breakdown lama (signal/ema_score/
    # dual_confirmed/mcf_*/rs_vs_ihsg) yg tak lagi punya padanan semantik di
    # sistem baru. Threshold "EMA kuat >=25" kini berarti conviction>=50%
    # (setara: minimal 1 retest hold tercapai, bukan sekadar zona terbentuk).
    # ════════════════════════════════════════════════════════════════════════
    ema_pts = a.conviction_pct * 0.5

    if a.zone_status == "WATCHING":
        reasons.append(f"Zona conviction: {a.conviction_pct}% ({a.retest_hold_days}/2 retest)")
        if a.zone_vidya_pct > 0:
            reasons.append("VIDYA bullish saat retest")
        if a.zone_volume_pct > 0:
            reasons.append("Volume delta menguat")
        if a.zone_structure_pct > 0:
            reasons.append("Struktur internal+swing aligned")
    elif a.zone_status == "INVALIDATED":
        reasons.append("⛔ Zona invalidasi — harga tembus support")
    elif a.zone_status == "EXPIRED":
        reasons.append("Zona kadaluarsa — tak ada retest")

    # MSCI bonus masuk ke axis ini (konfirmasi teknikal institusional) — TIDAK
    # berubah, konsep independen dari engine EMA/zone manapun.
    if a.msci_active and a.msci_alert_level == "HIGH_CONVICTION":
        ema_pts += 8
        reasons.append(f"★ MSCI HIGH CONVICTION T-{a.msci_t_minus}")
    elif a.msci_active and a.msci_alert_level == "MEDIUM":
        ema_pts += 4
        reasons.append(f"◈ MSCI MEDIUM T-{a.msci_t_minus}")

    # Regime penalty — TIDAK berubah
    if a.regime_tag == "WATCHLIST_ONLY":
        ema_pts -= 10
        reasons.append("Regime BEAR — entry berisiko")

    ema_pts = max(0, min(50, ema_pts))

    # ════════════════════════════════════════════════════════════════════════
    # AXIS 2 — WHALE SCORE (0–50)
    # ════════════════════════════════════════════════════════════════════════
    whale_pts = 0

    if a.whale_ok:
        # Quality: max 30 (SMART naik karena whale adalah half the story)
        q_pts = {"SMART": 30, "LIKELY_SMART": 22, "UNCERTAIN": 10, "DUMB": 2, "—": 0}.get(a.whale_quality, 0)
        whale_pts += q_pts
        if a.whale_quality in ("SMART", "LIKELY_SMART"):
            reasons.append(f"Whale: {a.whale_quality}")

        # Conviction: max 12
        whale_pts += min(a.conviction * 1.5, 12)
        if a.conviction >= 7:
            reasons.append(f"Conviction: {a.conviction}/10")

        # Pengeringan: max 8
        if a.pengeringan:
            whale_pts += min(a.peng_strength * 2, 8)
            reasons.append("Pengeringan aktif")

        # Floor bonus: max 7
        if a.entry_zone == "AT_FLOOR":
            whale_pts += 7
            reasons.append("Harga di floor")
        elif a.entry_zone == "NEAR_FLOOR":
            whale_pts += 3

        # Penalties
        if a.harga_terlalu_jauh:
            whale_pts -= 8
            reasons.append("⚠ Terlalu jauh dari floor")
        if a.market_sepi:
            whale_pts -= 5
            reasons.append("⚠ Market sepi")
        if a.activity_type in ("DISTRIBUSI", "SELL_OFF"):
            whale_pts -= 20
            reasons.append("🔴 Distribusi / sell-off")

    whale_pts = max(0, min(50, whale_pts))

    # ════════════════════════════════════════════════════════════════════════
    # MATRIX GRADE — two-axis, definisi "longgar"
    # Whale Kuat = whale_pts ≥ 25 (threshold dikalibrasi: UNCERTAIN+conv7+peng+near = ~27)
    # EMA  Kuat  = ema_pts   ≥ 25 (threshold: BREAKOUT=20 + score bonus ≥5 = 25)
    # ════════════════════════════════════════════════════════════════════════
    _ema_kuat   = ema_pts   >= 25
    _whale_kuat = whale_pts >= 25

    if _ema_kuat and _whale_kuat:
        a.grade = "A"
        a.action_label = "ENTRY NOW" if a.signal in ("BREAKOUT", "WATCHLIST") else "STRONG WATCH"
    elif _ema_kuat and not _whale_kuat:
        a.grade = "B"
        a.action_label = "WATCHLIST KUAT"
    elif not _ema_kuat and _whale_kuat:
        a.grade = "C"
        a.action_label = "MONITOR — tunggu EMA konfirmasi"
    else:
        # Keduanya lemah — gradasi D vs F berdasarkan total
        _total = ema_pts + whale_pts
        if _total >= 15:
            a.grade = "D"
            a.action_label = "TERLALU DINI"
        else:
            a.grade = "F"
            a.action_label = "HINDARI / TIDAK LAYAK"

    # ── overall_score — dikalibrasi agar correlated dengan grade ────────────
    # Sebelumnya: ema_pts + whale_pts (max 100) → Grade A bisa dapat 60 saja
    # Sekarang: score mencerminkan grade band sehingga A=80-100, B=60-79, dst
    #
    # Formula per grade:
    #   A (EMA kuat + Whale kuat): base 80 + bonus dari kelebihan kedua axis
    #   B (EMA kuat only)        : base 60 + bonus dari EMA
    #   C (Whale kuat only)      : base 40 + bonus dari Whale
    #   D                        : base 20 + proporsi total
    #   F                        : base 0  + proporsi total
    if a.grade == "A":
        # Bonus dari kelebihan ema dan whale di atas threshold (25)
        _bonus = min(20, (ema_pts - 25) + (whale_pts - 25))
        a.overall_score = min(100, 80 + _bonus)
    elif a.grade == "B":
        # EMA kuat (>=25), whale lemah — range 60-79
        _bonus = min(19, int((ema_pts - 25) / 25 * 15) + int(whale_pts / 25 * 4))
        a.overall_score = min(79, 60 + _bonus)
    elif a.grade == "C":
        # Whale kuat (>=25), EMA lemah — range 40-59
        _bonus = min(19, int((whale_pts - 25) / 25 * 15) + int(ema_pts / 25 * 4))
        a.overall_score = min(59, 40 + _bonus)
    elif a.grade == "D":
        # Keduanya lemah, total >= 15 — range 20-39
        _total = ema_pts + whale_pts
        a.overall_score = min(39, 20 + int(_total / 50 * 19))
    else:  # F
        _total = ema_pts + whale_pts
        a.overall_score = min(19, int(_total / 30 * 19))

    a.grade_reasons = reasons[:6]
