"""
Simple Trading V6 — Single Stock Analysis Agent
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
    signal:           str   = "NONE"    # BREAKOUT / WATCHLIST / CORRECTING / DEEP_CORRECT
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

    # Market structure
    ms_label:      str   = ""
    ms_score:      int   = 0
    smc_trend:     str   = ""

    flags:         list  = field(default_factory=list)

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
    from core.data_feed       import DataFeed, get_ihsg_regime
    from core.technical_engine import (
        EMABreakoutEngine, check_daily_entry,
        analyze_market_structure, compute_mcf,
    )
    from config.strategy_config import StrategyConfig

    cfg  = StrategyConfig.load()
    feed = DataFeed(timeframe="1wk", period="3y")
    feed_d = DataFeed(timeframe="1d",  period="60d")

    # Fetch data
    df   = feed.fetch(ticker)
    df_d = feed_d.fetch(ticker)

    if df is None or len(df) < 30:
        a.error = f"Data mingguan tidak cukup untuk {ticker}"
        return

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Regime
    regime_data = get_ihsg_regime()
    regime_tag  = regime_data.get("regime", "UNKNOWN")

    # Weekly analysis
    engine = EMABreakoutEngine(cfg)
    result = engine.analyze(df, ticker, ihsg_df=None, regime=regime_tag)

    if result is None:
        a.error = f"EMA engine tidak bisa analisis {ticker}"
        return

    # ── Isi dari SetupResult ─────────────────────────────────────────────────
    a.signal           = result.signal or "NONE"
    a.ema_score        = result.score
    a.regime_tag       = result.regime_tag or regime_tag
    a.cross_state      = result.cross_state
    a.bars_since_cross = result.bars_since_cross

    a.close     = result.close
    a.ema5      = result.ema5
    a.ema13     = result.ema13
    a.ema89     = result.ema89
    a.ema200    = result.ema200
    a.ema200_reliable = result.ema200_reliable

    a.entry_price = result.entry_price or result.close
    a.sl_price    = result.sl_price
    a.tp1_price   = result.tp1_price
    a.tp2_price   = result.tp2_price
    a.risk_pct    = result.risk_pct
    a.rr_ratio    = result.rr_ratio
    a.risk_sizing_ok = result.risk_sizing_ok

    a.vol_ratio  = result.vol_ratio
    a.rs_vs_ihsg = result.rs_vs_ihsg_4w
    a.rs_signal  = result.rs_signal

    a.smc_trend = result.smc_trend
    a.ms_score  = result.smc_score
    a.flags     = list(result.flags or [])

    # ── Daily entry timing ───────────────────────────────────────────────────
    if df_d is not None and len(df_d) >= 20:
        if isinstance(df_d.columns, pd.MultiIndex):
            df_d.columns = df_d.columns.get_level_values(0)
        daily = check_daily_entry(df_d, str(result.cross_state))
        a.daily_ok      = daily.get("daily_ok", False)
        a.daily_pattern = daily.get("daily_pattern", "")
        a.dual_confirmed = (
            a.daily_ok and result.cross_state in ("ABOVE", "CROSSING")
        )

    # ── MCF ─────────────────────────────────────────────────────────────────
    try:
        mcf_data = compute_mcf(
            close=df["Close"],
            high=df["High"],
            low=df["Low"],
            open_=df["Open"],
            volume=df["Volume"],
            regime_tag=a.regime_tag,
        )
        a.mcf_score        = mcf_data.get("score", 0)
        a.mcf_label        = mcf_data.get("label", "—")
        a.mcf_entry_ok     = mcf_data.get("mcf_entry_ok", False)
        a.mcf_bear_blocked = mcf_data.get("mcf_bear_blocked", False)
    except Exception as exc:
        logger.debug(f"MCF error: {exc}")

    # ── Market Structure ─────────────────────────────────────────────────────
    try:
        ms = analyze_market_structure(
            df["Close"].tolist(),
            ema13_series=None,
            ema89_series=None,
        )
        a.ms_label = ms.get("structure", "")
        a.ms_score = ms.get("conviction_boost", 0)
    except Exception:
        pass


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
# Overall grade computation
# ─────────────────────────────────────────────────────────────────────────────

def _compute_overall(a: StockAnalysis):
    reasons = []
    pts     = 0   # 0–100

    # ── EMA-XBO component (max 40 pts) ──────────────────────────────────────
    # Signal base
    sig_pts = {
        "BREAKOUT": 30, "WATCHLIST": 22, "CORRECTING": 12,
        "DEEP_CORRECT": 6, "NONE": 0,
    }.get(a.signal, 0)
    pts += sig_pts
    if a.signal in ("BREAKOUT","WATCHLIST"):
        reasons.append(f"EMA signal: {a.signal}")

    # Score bonus (each point above 3 = +2)
    score_bonus = max(0, (a.ema_score - 3) * 2)
    pts += min(score_bonus, 10)
    if a.ema_score >= 5:
        reasons.append(f"EMA score tinggi: {a.ema_score}/7")

    # Dual timeframe bonus
    if a.dual_confirmed:
        pts += 5
        reasons.append("Dual-timeframe confirmed")
    elif a.daily_ok:
        pts += 2

    # MCF
    if a.mcf_entry_ok and not a.mcf_bear_blocked:
        mcf_bonus = min(a.mcf_score, 5)
        pts += mcf_bonus
        if a.mcf_score >= 8:
            reasons.append(f"MCF tinggi: {a.mcf_score}/10")
    elif a.mcf_bear_blocked:
        pts -= 5
        reasons.append("⛔ MCF bear-blocked")

    # RS
    if a.rs_vs_ihsg > 5:
        pts += 3
        reasons.append(f"RS vs IHSG: +{a.rs_vs_ihsg:.1f}%")
    elif a.rs_vs_ihsg < -5:
        pts -= 3

    # Regime penalty
    if a.regime_tag == "WATCHLIST_ONLY":
        pts -= 10
        reasons.append("Regime BEAR — entry berisiko")

    # ── Whale component (max 35 pts) ─────────────────────────────────────────
    if a.whale_ok:
        # Quality
        q_pts = {"SMART": 25, "LIKELY_SMART": 18, "UNCERTAIN": 8, "DUMB": 2, "—": 0}.get(a.whale_quality, 0)
        pts += q_pts
        if a.whale_quality in ("SMART", "LIKELY_SMART"):
            reasons.append(f"Whale quality: {a.whale_quality}")

        # Conviction
        conv_pts = min(a.conviction * 1.5, 10)
        pts += conv_pts
        if a.conviction >= 7:
            reasons.append(f"Whale conviction: {a.conviction}/10")

        # Pengeringan bonus
        if a.pengeringan:
            pts += min(a.peng_strength * 2, 5)
            reasons.append("Pengeringan terdeteksi")

        # At floor bonus
        if a.entry_zone == "AT_FLOOR":
            pts += 5
            reasons.append("Harga di floor price")
        elif a.entry_zone == "NEAR_FLOOR":
            pts += 2

        # Penalties
        if a.harga_terlalu_jauh:
            pts -= 8
            reasons.append("⚠ Harga terlalu jauh dari floor")
        if a.market_sepi:
            pts -= 5
            reasons.append("⚠ Market sepi")
        if a.activity_type in ("DISTRIBUSI","SELL_OFF"):
            pts -= 15
            reasons.append("🔴 Distribusi / sell-off terdeteksi")

    # ── MSCI bonus ────────────────────────────────────────────────────────────
    if a.msci_active and a.msci_alert_level == "HIGH_CONVICTION":
        pts += 8
        reasons.append(f"★ MSCI HIGH CONVICTION T-{a.msci_t_minus}")
    elif a.msci_active and a.msci_alert_level == "MEDIUM":
        pts += 4
        reasons.append(f"◈ MSCI MEDIUM T-{a.msci_t_minus}")

    # ── Clamp & grade ─────────────────────────────────────────────────────────
    a.overall_score = max(0, min(100, int(pts)))

    s = a.overall_score
    if s >= 75:
        a.grade = "A"
        a.action_label = "ENTRY NOW" if a.signal in ("BREAKOUT","WATCHLIST") else "STRONG WATCH"
    elif s >= 55:
        a.grade = "B"
        a.action_label = "WATCHLIST KUAT"
    elif s >= 35:
        a.grade = "C"
        a.action_label = "MONITOR"
    elif s >= 15:
        a.grade = "D"
        a.action_label = "TERLALU DINI"
    else:
        a.grade = "F"
        a.action_label = "HINDARI / TIDAK LAYAK"

    a.grade_reasons = reasons[:6]  # max 6 reasons
