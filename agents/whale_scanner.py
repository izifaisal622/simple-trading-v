"""
Simple Trading V9 — Whale Scanner (Hengky Adinata Method)
===========================================================
"Semua ada rumus. Hitung barang."
  — Hengky Adinata

FILOSOFI INTI:
  Hengky tidak pernah blind follow. Dia HITUNG dulu siapa yang pegang barang,
  berapa banyak, di harga berapa, dan apakah mereka masih mau defend.

  1. HITUNG BARANG
     Berapa lot beredar? Siapa yang pegang? Di harga berapa mereka masuk?
     Jika emiten masih hold → harga akan didefend.
     Jika emiten sudah jual → jangan diikuti.

  2. FLOOR PRICE
     Titik di mana emiten rugi kalau turun lagi.
     Di sinilah whale pasti defend. Di sinilah entry terbaik.
     Hengky selalu hitung floor price sebelum masuk.
     Kami estimasi dari: cost basis area, support terkuat, vol profile low.

  3. BROKER FINGERPRINT
     Setiap broker punya karakter berbeda:
       MG, BK, AK, YP  → Market Maker / Institusi besar
       YU, HP, CC       → Sering dipakai asing (foreign flow)
       ZP, DX, FZ       → Retail / trader

     Kalau MG yang beli → whale beneran masuk.
     Kalau ZP yang beli → retail, bisa panik kapan saja.
     (Proxy: kita pakai vol pattern & trade size distribution)

  4. PENGERINGAN BARANG
     Ciri khas Hengky: sebelum saham naik, retailnya jual habis dulu.
     Pattern: volume tinggi beberapa hari tapi harga tidak naik banyak
     = barang berpindah dari retail ke smart money (pengeringan).
     Setelah barang kering → siap naik.

  5. SMART WHALE vs DUMB WHALE
     Smart whale: defend harga waktu turun, beli bertahap, tidak impulsif.
     Dumb whale: beli gede tapi tidak defend, barang drift down.
     Hengky: "Whale berduit belum tentu pintar."

  6. BIT-OVER DEFENSE TEST
     Kalau ada yang jual gede dan harga tidak turun jauh → ada yang nampung.
     Itu tanda strong whale defense. Entry ideal.

  7. MARKET SEPI = STOP TRADE
     Kalau market sepi, bahkan setup bagus pun jangan dipaksakan.
     "Breakout tanpa partisipan = hammer closing. Mubazir."

PATCH V3:
  - Free float adjusted volume (FF-adj vol ratio)
  - Fundamental deterioration exclusion (EPS proxy)
  - Sector exposure tracker
  - Floor price decay: if price keeps falling, floor is re-estimated lower
  - Exit signal integration with ExitEngine

SIGNALS (long-only IDX):
  🟢 ACCUMULATION    — Smart whale kumpulin diam-diam. Setup terbaik.
  🔵 BLOCK_BUY       — Beli gede satu kali. Monitor apakah dilanjutkan.
  🌅 RECOVERY_EARLY  — Beaten down >20% + whale buying. Calon pemimpin bull.
  🟡 VOL_SPIKE_UP    — Volume besar + harga naik. Worth monitoring.
  ⚪ VOL_NEUTRAL     — Volume spike, arah tidak jelas. Skip.
  🔴 DISTRIBUTION    — Whale exit. AWARENESS ONLY — IDX no short.
  🟠 BLOCK_SELL      — Jual gede. Hati-hati jika pegang.

SCORING (0–10 Conviction):
  Vol ratio      : 0–3 pts  (semakin tinggi semakin bagus)
  Pengeringan    : 0–2 pts  (multi-day + range sempit)
  Floor proximity: 0–2 pts  (dekat floor = entry ideal)
  EMA alignment  : 0–1 pt
  Whale defense  : 0–1 pt   (dihantam tapi tidak jatuh)
  Momentum       : 0–1 pt
"""

import logging
try:
    _HAS_MS = True
except Exception:
    _HAS_MS = False
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from core.data_feed import DataFeed, get_ihsg_regime, IDX_WATCHLIST
from core.data_feed import MSCI_CANDIDATES, IDX30_LQ45_CANDIDATES, get_catalyst_universe, get_dynamic_universe
try:
    from agents.ownership_agent import OwnershipAgent
    _ownership_agent = OwnershipAgent()
    _HAS_OWNERSHIP = True
except Exception:
    _HAS_OWNERSHIP = False

warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Cycle settings — Hengky adapt to market, bukan paksa masuk
# ─────────────────────────────────────────────────────────────────────────────

CYCLE_SETTINGS = {
    "BULL_TREND": {
        "vol_mult":       3.0,
        "min_value_bn":   1.0,
        "focus":          "ACCUMULATION",
        "trade_signal":   True,
        "min_conviction": 5,
        "description":    "Bull: agresif. Vol ≥ 3× + akumulasi + EMA bullish = masuk.",
        "sizing_advice":  "Full size. Trailing SL setelah TP1. Let it run.",
        "action":         "TRADE_AGGRESSIVELY",
    },
    "BULL_CONSOLIDATION": {
        "vol_mult":       2.5,
        "min_value_bn":   0.8,
        "focus":          "ROTATION",
        "trade_signal":   True,
        "min_conviction": 6,
        "description":    "Konsolidasi: rotasi sektor. Cari yang baru mulai diakumulasi.",
        "sizing_advice":  "75% size. TP1 dulu, hold half.",
        "action":         "TRADE_SELECTIVE",
    },
    "TRANSITION": {
        "vol_mult":       2.0,
        "min_value_bn":   0.5,
        "focus":          "BOTH",
        "trade_signal":   True,
        "min_conviction": 5,
        "description":    "Transisi: hati-hati. Hanya setup conviction tinggi.",
        "sizing_advice":  "50% size. TP1 saja. SL ketat.",
        "action":         "TRADE_CAREFUL",
    },
    "BEAR_CONSOLIDATION": {
        "vol_mult":       1.3,
        "min_value_bn":   0.2,
        "focus":          "RECOVERY_WATCH",
        "trade_signal":   False,
        "min_conviction": 3,  # Show recovery watchlist candidates
        "description":    "Bear konsolidasi: bangun watchlist calon pemimpin bull berikutnya.",
        "sizing_advice":  "Belum masuk. Kumpul kandidat, pantau daily.",
        "action":         "WATCHLIST_ONLY",
    },
    "BEAR_TREND": {
        "vol_mult":       1.2,
        "min_value_bn":   0.15,
        "focus":          "DISTRIBUTION_WATCH",
        "trade_signal":   False,
        "min_conviction": 3,  # Low threshold — show data for watchlist building
        "description":    "BEAR TREND — STOP TRADE. Hengky: 'Golf dulu, tunggu retailnya colok mata.'",
        "sizing_advice":  "FULL CASH. Tidak ada setup yang cukup bagus di bear trend.",
        "action":         "STOP_TRADE",
    },
    "UNKNOWN": {
        "vol_mult":       2.5,
        "min_value_bn":   0.5,
        "focus":          "BOTH",
        "trade_signal":   True,
        "min_conviction": 5,
        "description":    "Regime belum diketahui. Default settings.",
        "sizing_advice":  "Normal. Update data IHSG dulu.",
        "action":         "TRADE_SELECTIVE",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Market Breadth — "Market sepi = jangan trad" (Hengky)
# ─────────────────────────────────────────────────────────────────────────────

def check_market_breadth(regime: dict) -> dict:
    cycle   = regime.get("cycle", "UNKNOWN")
    breadth = regime.get("breadth", 0)   # 0-6 berapa saham di atas EMA
    mom_4w  = regime.get("mom_4w", 0)

    if cycle == "BULL_TREND" and breadth >= 4 and mom_4w > 1:
        status  = "RAMAI"
        advice  = "Market ramai. Agresif. MG dan asing aktif. Ikut breakout."
        tradeable = True
    elif cycle in ("BULL_TREND","BULL_CONSOLIDATION") and breadth >= 3:
        status  = "NORMAL"
        advice  = "Market normal. Trade selektif, pilih setup terbaik."
        tradeable = True
    elif cycle == "TRANSITION" or (breadth >= 2 and mom_4w > -3):
        status  = "SEPI"
        advice  = "Market sepi. Hengky: 'Breakout tanpa follower = hammer closing.' Hati-hati."
        tradeable = True  # still ok, but be careful
    else:
        status  = "SANGAT_SEPI"
        advice  = "Market sangat sepi / bear. Hengky: STOP TRADE. Tunggu retail colok mata."
        tradeable = False

    color = {"RAMAI":"#00ff88","NORMAL":"#4ade80","SEPI":"#fb8c00","SANGAT_SEPI":"#ef4444"}[status]
    return {
        "status":    status,
        "advice":    advice,
        "color":     color,
        "breadth":   breadth,
        "tradeable": tradeable,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Floor Price Estimation (Hengky's most important concept)
# "Sahamnya bagus, harganya bagus → baru masuk"
# ─────────────────────────────────────────────────────────────────────────────

def estimate_floor_price(
    close: pd.Series,
    vol: pd.Series,
    low: pd.Series,
    vp_val: float = 0.0,
) -> dict:
    """
    Estimasi floor price menggunakan:
    1. Volume Profile VAL (Value Area Low) — jika tersedia dari compute_volume_profile()
       => level batas bawah 70% volume area = defend zone terkuat whale
    2. VWAP 60 hari — proxy cost basis (fallback)
    3. Low 52W x 1.05 — absolute floor buffer

    W-7 fix: support_cluster (pd.cut fragile) diganti dengan vp_val dari VP.
    VP VAL dihitung dari distribusi volume per price bin — jauh lebih akurat
    dari frekuensi harga di equal-width bins.
    """
    current  = float(close.iloc[-1])
    low_52w  = float(low.tail(252).min()) if len(low) >= 252 else float(low.min())
    high_52w = float(close.tail(252).max()) if len(close) >= 252 else float(close.max())

    # VWAP 60 hari — fallback jika VP tidak tersedia
    lookback = min(60, len(close))
    c60      = close.tail(lookback)
    v60      = vol.tail(lookback)
    vwap_60  = float((c60 * v60).sum() / v60.sum()) if v60.sum() > 0 else current

    # Floor layer 1: VP VAL (lebih akurat) atau VWAP (fallback)
    if vp_val > 0 and vp_val < current * 1.10:
        floor_1 = vp_val
    else:
        floor_1 = vwap_60 if vwap_60 < current else current * 0.85

    # Floor layer 2: low 52W + 5% buffer (absolute minimum)
    floor_2 = low_52w * 1.05

    floor = max(floor_1, floor_2)

    # Guard: jika floor >= current, paksa ke low_52w sebagai absolute floor
    if floor >= current:
        floor = max(low_52w, current * 0.70)

    # Proximity to floor (seberapa dekat harga sekarang dengan floor)
    pct_above_floor = (current - floor) / floor * 100 if floor > 0 else 999

    # Entry zone assessment
    if pct_above_floor <= 5:
        zone = "AT_FLOOR"      # harga hampir di floor → entry ideal
        zone_label = "🎯 Di floor — Entry ideal"
    elif pct_above_floor <= 15:
        zone = "NEAR_FLOOR"    # masih dekat floor → entry acceptable
        zone_label = "✅ Dekat floor — Acceptable"
    elif pct_above_floor <= 30:
        zone = "MID_RANGE"     # tidak terlalu jauh
        zone_label = "🟡 Mid range — Hati-hati"
    else:
        zone = "FAR_FROM_FLOOR"  # sudah jauh → risk/reward kurang bagus
        zone_label = f"❌ Jauh dari floor (+{pct_above_floor:.0f}%) — Skip"

    # Range width (pengeringan proxy): semakin sempit = semakin banyak akumulasi
    range_20d    = float(close.tail(20).max() - close.tail(20).min())
    range_pct    = range_20d / current * 100

    return {
        "floor_price":      round(floor, 0),
        "vwap_60d":         round(vwap_60, 0),
        "low_52w":          round(low_52w, 0),
        "high_52w":         round(high_52w, 0),
        "pct_above_floor":  round(pct_above_floor, 1),
        "entry_zone":       zone,
        "entry_zone_label": zone_label,
        "range_20d_pct":    round(range_pct, 1),
        "range_tight":      range_pct < 8,   # < 8% = range sempit = pengeringan
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pengeringan Barang Detection
# "Volume besar + harga tidak naik = barang berpindah dari retail ke smart money"
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# VOLUME PROFILE — Distribusi volume per price level (Hengky: "hitung di harga berapa")
# NEW V6.4
# ─────────────────────────────────────────────────────────────────────────────

def compute_volume_profile(
    close: pd.Series,
    vol: pd.Series,
    high: pd.Series,
    low: pd.Series,
    n_bins: int = 20,
    lookback: int = 60,
) -> dict:
    """
    Volume Profile (VP) — distribusi volume per price level.

    POC = Point of Control: harga dengan volume terbanyak = area defend terkuat whale.
    VAH/VAL = Value Area High/Low: 70% dari total volume ada di range ini.
    Jika harga di VAL atau di bawah → near floor, entry ideal.
    """
    if len(close) < 20:
        return {
            "poc": 0.0, "vah": 0.0, "val": 0.0,
            "current_zone": "UNKNOWN", "pct_from_poc": 0.0,
            "in_value_area": False, "near_val": False,
            "hvn_levels": [], "lvn_levels": [],
            "vp_desc": "",
        }

    n = min(lookback, len(close))
    c  = close.tail(n).values.astype(float)
    v  = vol.tail(n).values.astype(float)
    h  = high.tail(n).values.astype(float)
    lo = low.tail(n).values.astype(float)

    price_min = float(np.min(lo))
    price_max = float(np.max(h))
    if price_max <= price_min:
        price_max = price_min * 1.01

    bin_edges   = np.linspace(price_min, price_max, n_bins + 1)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    bin_vols    = np.zeros(n_bins)

    for i in range(n):
        candle_lo  = lo[i]
        candle_hi  = h[i]
        candle_vol = v[i]
        candle_range = candle_hi - candle_lo
        if candle_range < 1e-8:
            bin_idx = int(np.clip(np.searchsorted(bin_edges, c[i]) - 1, 0, n_bins - 1))
            bin_vols[bin_idx] += candle_vol
            continue
        for b in range(n_bins):
            overlap_lo = max(candle_lo, bin_edges[b])
            overlap_hi = min(candle_hi, bin_edges[b + 1])
            if overlap_hi > overlap_lo:
                frac = (overlap_hi - overlap_lo) / candle_range
                bin_vols[b] += candle_vol * frac

    total_vol = float(np.sum(bin_vols))
    if total_vol <= 0:
        return {
            "poc": 0.0, "vah": 0.0, "val": 0.0,
            "current_zone": "UNKNOWN", "pct_from_poc": 0.0,
            "in_value_area": False, "near_val": False,
            "hvn_levels": [], "lvn_levels": [],
            "vp_desc": "",
        }

    poc_idx = int(np.argmax(bin_vols))
    poc     = float(bin_centers[poc_idx])

    # Value Area: expand from POC until 70% volume captured
    target_vol  = total_vol * 0.70
    accumulated = bin_vols[poc_idx]
    upper_idx   = poc_idx
    lower_idx   = poc_idx

    while accumulated < target_vol:
        up_vol   = bin_vols[upper_idx + 1] if upper_idx + 1 < n_bins else 0.0
        down_vol = bin_vols[lower_idx - 1] if lower_idx - 1 >= 0     else 0.0
        if up_vol == 0 and down_vol == 0:
            break
        if up_vol >= down_vol and upper_idx + 1 < n_bins:
            upper_idx   += 1
            accumulated += bin_vols[upper_idx]
        elif lower_idx - 1 >= 0:
            lower_idx   -= 1
            accumulated += bin_vols[lower_idx]
        else:
            break

    vah = float(bin_edges[min(upper_idx + 1, n_bins)])
    val = float(bin_edges[lower_idx])

    # HVN / LVN
    median_vol = float(np.median(bin_vols[bin_vols > 0])) if np.any(bin_vols > 0) else 1.0
    hvn_levels = sorted([round(float(bin_centers[i]), 0) for i in range(n_bins) if bin_vols[i] > median_vol * 1.5])
    lvn_levels = sorted([round(float(bin_centers[i]), 0) for i in range(n_bins) if 0 < bin_vols[i] < median_vol * 0.5])

    current       = float(close.iloc[-1])
    pct_from_poc  = ((current - poc) / poc * 100) if poc > 0 else 0.0
    in_value_area = val <= current <= vah
    near_val      = (val * 0.98) <= current <= (val * 1.05)

    if current < val:
        current_zone = "BELOW_VALUE"
    elif current <= vah:
        current_zone = "IN_VALUE"
    else:
        current_zone = "ABOVE_VALUE"

    desc_parts = [f"POC Rp{poc:,.0f}"]
    if near_val or current < val:
        desc_parts.append(f"dekat VAL {val:,.0f} — zona akumulasi")
    elif in_value_area:
        desc_parts.append(f"value area {val:,.0f}–{vah:,.0f}")
    else:
        desc_parts.append(f"di atas VAH {vah:,.0f} — extended")

    return {
        "poc":           round(poc, 0),
        "vah":           round(vah, 0),
        "val":           round(val, 0),
        "current_zone":  current_zone,
        "pct_from_poc":  round(pct_from_poc, 1),
        "in_value_area": in_value_area,
        "near_val":      near_val,
        "hvn_levels":    hvn_levels[:5],
        "lvn_levels":    lvn_levels[:5],
        "vp_desc":       " · ".join(desc_parts),
    }


def detect_pengeringan(close: pd.Series, vol: pd.Series, high: pd.Series, low: pd.Series) -> dict:
    """
    Pengeringan = proses akumulasi diam-diam oleh smart money.
    V6.4: Enhanced — volume-price divergence + close position scoring.

    Ciri pengeringan sejati:
    - Volume elevated (tangan berpindah dari retail ke smart money)
    - Range sempit (smart money belum push harga — masih kumpul)
    - Lower wick (ada yang nampung di bawah saat tekanan jual)
    - Close di atas midrange (buyers in control)
    - Vol naik tapi harga stagnan (divergence = absorption)
    """
    vol_ma = float(vol.rolling(20).mean().iloc[-1])

    if vol_ma <= 0:
        return {"detected": False, "strength": 0, "days": 0, "description": "",
                "absorption_score": 0, "close_position_score": 0, "vol_acceleration": 1.0}

    days_elevated     = int((vol.tail(5) > vol_ma * 1.5).sum())
    days_range_sempit = 0
    close_positions   = []

    for i in range(min(5, len(close)-1)):
        day_high  = float(high.iloc[-(i+1)])
        day_low   = float(low.iloc[-(i+1)])
        day_close = float(close.iloc[-(i+1)])
        day_range = day_high - day_low

        if day_range / max(day_close, 1) < 0.03:
            days_range_sempit += 1

        if day_range > 0:
            close_positions.append((day_close - day_low) / day_range)

    avg_close_position = float(np.mean(close_positions)) if close_positions else 0.5

    lower_wicks = []
    for i in range(min(5, len(close)-1)):
        o  = float(close.iloc[-(i+2)] if i+2 <= len(close) else close.iloc[0])
        c  = float(close.iloc[-(i+1)])
        lo = float(low.iloc[-(i+1)])
        body_low = min(o, c)
        wick_low = max(body_low - lo, 0)
        lower_wicks.append(wick_low / max(float(close.iloc[-(i+1)]), 1) * 100)
    avg_lower_wick = float(np.mean(lower_wicks)) if lower_wicks else 0.0

    price_drift = abs(float(close.iloc[-1]) - float(close.iloc[-min(5, len(close))])) / max(float(close.iloc[-1]), 1) * 100

    # V6.4: Volume-price divergence
    vol_5d  = float(vol.tail(5).mean())
    vol_10d = float(vol.tail(10).mean()) if len(vol) >= 10 else vol_5d
    vol_acceleration = (vol_5d / vol_10d) if vol_10d > 0 else 1.0
    price_5d_chg = abs((float(close.iloc[-1]) / max(float(close.iloc[-min(5, len(close))]), 1) - 1) * 100)

    divergence_score = 0
    if vol_acceleration > 1.3 and price_5d_chg < 3:
        divergence_score = 2
    elif vol_acceleration > 1.1 and price_5d_chg < 5:
        divergence_score = 1

    # V6: False pengeringan detection — harga drift down = tidak ada yang beli
    # Pengeringan sejati: harga SIDEWAYS (tidak turun) saat volume turun/stabil
    # False pengeringan: harga DRIFT DOWN perlahan = retail kabur, bukan akumulasi
    last_close  = float(close.iloc[-1])
    close_10d   = float(close.iloc[-min(10, len(close))])
    close_20d   = float(close.iloc[-min(20, len(close))])
    price_trend_10d = (last_close / close_10d - 1) * 100 if close_10d > 0 else 0
    price_trend_20d = (last_close / close_20d - 1) * 100 if close_20d > 0 else 0

    # Drift down > 5% dalam 10 hari = false pengeringan
    # Drift down > 8% dalam 20 hari = false pengeringan
    is_false_pengeringan = (price_trend_10d < -5.0) or (price_trend_20d < -8.0)

    # Lower wick saat drift down bisa tetap ada tapi tidak bermakna
    # Jika false pengeringan, close_position harus sangat tinggi (>0.7) untuk override
    if is_false_pengeringan and avg_close_position < 0.7:
        # Override: reset signal ke false
        return {
            "detected":             False,
            "strength":             0,
            "days_elevated":        days_elevated,
            "days_range_sempit":    days_range_sempit,
            "avg_lower_wick":       round(avg_lower_wick, 2),
            "price_drift_pct":      round(price_drift, 2),
            "absorption_score":     0,
            "close_position_score": round(avg_close_position, 2),
            "vol_acceleration":     round(vol_acceleration, 2),
            "description":          f"False pengeringan — harga drift {price_trend_10d:.1f}% dalam 10h (bukan akumulasi, retail kabur)",
            "is_false":             True,
        }

    strength = 0
    if days_elevated >= 3:       strength += 3
    elif days_elevated >= 2:     strength += 2
    elif days_elevated >= 1:     strength += 1

    if days_range_sempit >= 3:   strength += 2
    elif days_range_sempit >= 2: strength += 1

    if avg_lower_wick > 0.5:     strength += 1
    if price_drift < 3:          strength += 1
    strength += divergence_score
    if avg_close_position > 0.6: strength += 1

    detected = strength >= 3

    desc = ""
    if detected:
        parts = []
        if days_elevated >= 2:       parts.append(f"vol elevated {days_elevated}h")
        if days_range_sempit >= 2:   parts.append(f"range sempit {days_range_sempit}h")
        if avg_lower_wick > 0.5:     parts.append("ada lower wick")
        if price_drift < 3:          parts.append("harga stagnan")
        if divergence_score >= 2:    parts.append("vol spike tanpa harga naik")
        if avg_close_position > 0.6: parts.append("close atas range")
        desc = "Pengeringan: " + " · ".join(parts)

    return {
        "detected":             detected,
        "strength":             min(strength, 7),
        "days_elevated":        days_elevated,
        "days_range_sempit":    days_range_sempit,
        "avg_lower_wick":       round(avg_lower_wick, 2),
        "price_drift_pct":      round(price_drift, 2),
        "absorption_score":     divergence_score,
        "close_position_score": round(avg_close_position, 2),
        "vol_acceleration":     round(vol_acceleration, 2),
        "description":          desc,
        "is_false":             False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Slow Exit Detector — Whale diam-diam keluar saat harga masih naik
# "Jangan masuk saat whale sedang exit" — Hengky
# ─────────────────────────────────────────────────────────────────────────────

def detect_slow_exit(
    close: pd.Series,
    vol: pd.Series,
    high: pd.Series,
    low: pd.Series,
) -> dict:
    """
    Deteksi distribusi bertahap — whale exit pelan-pelan saat harga masih naik.

    Signature slow exit (kebalikan dari akumulasi):
    1. Harga naik tapi volume TURUN bertahap (divergence bearish)
       = tidak ada buyer baru yang masuk, harga naik karena momentum saja
    2. Upper wick makin panjang (rejected at high) — seller aktif di atas
    3. Close makin di lower half candle meski harga range masih tinggi
    4. Vol spike tapi close di lower half = distribusi tersembunyi (dari hitung_barang)

    Returns:
    - detected: bool
    - strength: 0-3
    - description: str
    - price_vol_divergence: bool (harga naik tapi vol turun)
    - upper_wick_dominant: bool
    """
    _empty = {"detected": False, "strength": 0, "description": "",
              "price_vol_divergence": False, "upper_wick_dominant": False}

    if len(close) < 15:
        return _empty

    try:
        last_close = float(close.iloc[-1])

        # 1. Price-volume divergence: harga naik 10 hari tapi vol turun
        price_10d  = (last_close / float(close.iloc[-min(10, len(close))]) - 1) * 100
        vol_ma_5d  = float(vol.tail(5).mean())
        vol_ma_15d = float(vol.tail(15).mean()) if len(vol) >= 15 else vol_ma_5d
        vol_trend  = vol_ma_5d / vol_ma_15d if vol_ma_15d > 0 else 1.0

        # Divergence: harga naik >3% tapi volume turun >15%
        price_vol_div = price_10d > 3.0 and vol_trend < 0.85

        # 2. Upper wick dominance — seller aktif di atas
        upper_wicks = []
        for i in range(min(10, len(close) - 1)):
            c  = float(close.iloc[-(i+1)])
            hi = float(high.iloc[-(i+1)])
            lo = float(low.iloc[-(i+1)])
            o  = float(close.iloc[-(i+2)]) if i+2 <= len(close) else c
            body_high  = max(o, c)
            upper_wick = (hi - body_high) / max(hi - lo, 1) * 100  # % of candle range
            upper_wicks.append(upper_wick)
        avg_upper_wick = float(np.mean(upper_wicks)) if upper_wicks else 0
        upper_wick_dom = avg_upper_wick > 30  # >30% range adalah upper wick = banyak rejection

        # 3. Close position makin turun (lower half) meski harga range masih tinggi
        close_positions = []
        for i in range(min(10, len(close) - 1)):
            c  = float(close.iloc[-(i+1)])
            hi = float(high.iloc[-(i+1)])
            lo = float(low.iloc[-(i+1)])
            candle_range = hi - lo
            pos = (c - lo) / candle_range if candle_range > 0 else 0.5
            close_positions.append(pos)
        avg_close_pos = float(np.mean(close_positions)) if close_positions else 0.5
        close_lower_half = avg_close_pos < 0.45  # close rata-rata di lower 45% candle

        # Strength scoring
        strength = 0
        if price_vol_div:    strength += 1
        if upper_wick_dom:   strength += 1
        if close_lower_half: strength += 1

        detected = strength >= 2  # butuh minimal 2 dari 3 signal

        if detected:
            parts = []
            if price_vol_div:    parts.append(f"harga +{price_10d:.0f}% tapi vol turun {(1-vol_trend)*100:.0f}%")
            if upper_wick_dom:   parts.append(f"upper wick dominan {avg_upper_wick:.0f}% — banyak rejection")
            if close_lower_half: parts.append(f"close di lower half candle ({avg_close_pos:.0%})")
            desc = "⚠️ Slow exit terdeteksi: " + " · ".join(parts)
        else:
            desc = ""

        return {
            "detected":             detected,
            "strength":             strength,
            "description":          desc,
            "price_vol_divergence": price_vol_div,
            "upper_wick_dominant":  upper_wick_dom,
            "avg_upper_wick":       round(avg_upper_wick, 1),
            "avg_close_pos":        round(avg_close_pos, 2),
            "vol_trend":            round(vol_trend, 2),
        }

    except Exception:
        return _empty


# ─────────────────────────────────────────────────────────────────────────────
# TRIGGER CANDLE DETECTION — Sinyal Whale Selesai Akumulasi, Siap Push
# "Beli setelah barang kering, masuk saat pertama kali volume naik kembali" — Hengky
#
# Trigger candle = transisi dari akumulasi ke markup phase:
# Setelah beberapa hari vol drying (pengeringan), muncul satu candle dengan:
# 1. Close di upper 30% range candle (buyer control)
# 2. Volume naik vs kemarin (vol step-up — whale mulai push)
# 3. Close > open (candle hijau / bullish body)
# 4. Price masih dalam entry zone (tidak sudah terlambat)
#
# Bonus signal:
# - Vol spike setelah drying: vol hari ini 2x+ vol rata-rata 3 hari sebelumnya
# - Range expansion: range candle hari ini lebih lebar dari rata-rata 3 hari sebelumnya
#   (compression selesai, expansion dimulai)
# ─────────────────────────────────────────────────────────────────────────────

def detect_trigger_candle(
    close: pd.Series,
    vol:   pd.Series,
    high:  pd.Series,
    low:   pd.Series,
    open_: pd.Series,
    vol_ma: float,
    pengeringan_detected: bool = False,
) -> dict:
    """
    Deteksi trigger candle — momen transisi akumulasi → markup.

    Returns dict dengan:
    - detected:        bool — trigger candle valid terdeteksi
    - strength:        0-4 — makin tinggi makin kuat signal
    - close_position:  float — posisi close dalam candle range (1.0=high, 0.0=low)
    - vol_stepup:      bool — vol hari ini > vol kemarin (step-up)
    - vol_spike:       bool — vol hari ini >= 2x rata-rata 3 hari sebelumnya
    - range_expansion: bool — range hari ini lebih lebar dari rata-rata 3 hari sebelumnya
    - is_bullish_body: bool — close > open (body hijau)
    - description:     str
    """
    _empty = {
        "detected": False, "strength": 0,
        "close_position": 0.5, "vol_stepup": False,
        "vol_spike": False, "range_expansion": False,
        "is_bullish_body": False, "description": "",
    }

    if len(close) < 5:
        return _empty

    try:
        # Candle hari ini (index -1)
        c_today   = float(close.iloc[-1])
        o_today   = float(open_.iloc[-1])
        h_today   = float(high.iloc[-1])
        l_today   = float(low.iloc[-1])
        v_today   = float(vol.iloc[-1])

        # Candle kemarin (index -2)
        v_yest    = float(vol.iloc[-2])

        # Rata-rata 3 hari sebelum hari ini (index -4 s/d -2)
        v_3d_avg  = float(vol.iloc[-4:-1].mean()) if len(vol) >= 4 else v_yest
        r_3d_avg  = float((high.iloc[-4:-1] - low.iloc[-4:-1]).mean()) if len(high) >= 4 else 0.0

        candle_range = h_today - l_today

        # 1. Close position dalam candle range — buyer control jika close di upper 30%
        close_pos = ((c_today - l_today) / candle_range) if candle_range > 0 else 0.5

        # 2. Bullish body
        is_bullish = c_today > o_today

        # 3. Vol step-up — hari ini lebih dari kemarin
        vol_stepup = v_today > v_yest

        # 4. Vol spike setelah drying — hari ini >= 2x rata-rata 3 hari sebelumnya
        vol_spike = (v_3d_avg > 0) and (v_today >= v_3d_avg * 2.0)

        # 5. Range expansion — candle lebih lebar dari 3 hari sebelumnya (compression selesai)
        range_expansion = (r_3d_avg > 0) and (candle_range >= r_3d_avg * 1.3)

        # Scoring
        strength = 0
        if close_pos >= 0.70:  strength += 1   # close di upper 30% = buyer control
        if is_bullish:         strength += 1   # body hijau
        if vol_stepup:         strength += 1   # volume mulai naik
        if vol_spike:          strength += 1   # vol spike setelah drying
        if range_expansion:    strength += 1   # range melebar = compression selesai

        # Bonus: konteks pengeringan sebelumnya memperkuat signal
        # Trigger setelah pengeringan jauh lebih bermakna
        _context_bonus = pengeringan_detected and vol_stepup

        # Minimum requirement: close di upper half + bullish body + vol stepup
        # Tanpa 3 syarat ini, bukan trigger candle — hanya candle hijau biasa
        detected = (close_pos >= 0.60 and is_bullish and vol_stepup and strength >= 3)

        if not detected:
            return {**_empty, "close_position": round(close_pos, 2),
                    "vol_stepup": vol_stepup, "is_bullish_body": is_bullish}

        parts = []
        if close_pos >= 0.70:   parts.append(f"close di {close_pos:.0%} range")
        if vol_spike:           parts.append(f"vol spike {v_today/v_3d_avg:.1f}x rata 3h")
        elif vol_stepup:        parts.append(f"vol naik vs kemarin")
        if range_expansion:     parts.append("range melebar — compression selesai")
        if _context_bonus:      parts.append("setelah pengeringan → timing terbaik")

        desc = "🕯 Trigger candle: " + " · ".join(parts)

        return {
            "detected":        True,
            "strength":        min(strength, 4),
            "close_position":  round(close_pos, 2),
            "vol_stepup":      vol_stepup,
            "vol_spike":       vol_spike,
            "range_expansion": range_expansion,
            "is_bullish_body": is_bullish,
            "description":     desc,
        }

    except Exception:
        return _empty


# ─────────────────────────────────────────────────────────────────────────────
# Gradual Accumulation Detector — Weekly Step-Up Pattern
# Smart whale afiliasi emiten jarang beli sekaligus — mereka naik bertahap
# tiap minggu supaya tidak trigger scanner retail
# ─────────────────────────────────────────────────────────────────────────────

def detect_gradual_accumulation(
    close: pd.Series,
    vol: pd.Series,
    high: pd.Series,
    low: pd.Series,
    min_weeks: int = 4,
) -> dict:
    """
    Detects gradual weekly volume step-up with sideways price — signature
    smart whale afiliasi emiten yang akumulasi diam-diam tanpa trigger scanner.

    Logic (Opsi A — aggregate daily data ke weekly):
    - Resample daily close/vol/high/low ke minggu
    - Cek apakah vol naik tiap minggu selama min_weeks minggu berturut-turut
    - Cek price range tiap minggu < 5% (sideways)
    - Total vol gain dari minggu pertama ke terakhir minimal +20%

    Returns:
    - detected: bool
    - weeks_confirmed: int (berapa minggu step-up terkonfirmasi)
    - vol_gain_pct: float (total vol growth dari minggu 1 ke N)
    - avg_weekly_range_pct: float (rata-rata price range per minggu)
    - strength: int 0-3 (0=none, 1=weak, 2=moderate, 3=strong)
    - description: str
    """
    _empty = {
        "detected": False, "weeks_confirmed": 0,
        "vol_gain_pct": 0.0, "avg_weekly_range_pct": 0.0,
        "strength": 0, "description": ""
    }

    # Butuh minimal 5 minggu data (4 step-up + 1 baseline)
    if len(close) < 35:
        return _empty

    try:
        # Aggregate daily → weekly menggunakan resample
        df_temp = pd.DataFrame({
            "close": close.values,
            "vol":   vol.values,
            "high":  high.values,
            "low":   low.values,
        }, index=close.index)

        weekly = df_temp.resample("W").agg({
            "close": "last",
            "vol":   "sum",
            "high":  "max",
            "low":   "min",
        }).dropna()

        if len(weekly) < min_weeks + 1:
            return _empty

        # Ambil N+1 minggu terakhir (N untuk step-up, 1 baseline sebelumnya)
        look = weekly.tail(min_weeks + 1).reset_index(drop=True)

        # Cek vol step-up tiap minggu berturut-turut
        step_up_count = 0
        weekly_ranges = []
        for i in range(1, len(look)):
            prev_vol = float(look["vol"].iloc[i - 1])
            curr_vol = float(look["vol"].iloc[i])
            if prev_vol > 0 and curr_vol > prev_vol:
                step_up_count += 1

            # Price range minggu ini sebagai % dari close
            w_close = float(look["close"].iloc[i])
            w_high  = float(look["high"].iloc[i])
            w_low   = float(look["low"].iloc[i])
            w_range = ((w_high - w_low) / w_close * 100) if w_close > 0 else 999
            weekly_ranges.append(w_range)

        avg_range = float(np.mean(weekly_ranges)) if weekly_ranges else 999

        # Vol gain dari baseline (minggu pertama) ke minggu terakhir
        base_vol = float(look["vol"].iloc[0])
        last_vol = float(look["vol"].iloc[-1])
        vol_gain_pct = ((last_vol / base_vol - 1) * 100) if base_vol > 0 else 0.0

        # Konfirmasi: semua minggu step-up DAN price sideways DAN vol gain meaningful
        all_stepped_up  = step_up_count >= min_weeks
        price_sideways  = avg_range < 5.0
        vol_meaningful  = vol_gain_pct >= 20.0

        detected = all_stepped_up and price_sideways and vol_meaningful

        # Strength scoring
        if not detected:
            # Partial detection — berapa minggu yang terkonfirmasi step-up
            partial = step_up_count >= (min_weeks - 1) and price_sideways
            strength = 1 if partial else 0
        else:
            if vol_gain_pct >= 80 and avg_range < 3.0:
                strength = 3  # strong: vol naik tajam + range sangat sempit
            elif vol_gain_pct >= 40 or avg_range < 3.5:
                strength = 2  # moderate
            else:
                strength = 1  # weak but confirmed

        # Description
        if detected:
            desc = (f"Gradual akumulasi {step_up_count} minggu berturut-turut — "
                    f"vol naik +{vol_gain_pct:.0f}%, range sempit {avg_range:.1f}%/minggu")
        elif strength == 1:
            desc = (f"Partial step-up {step_up_count}/{min_weeks} minggu — "
                    f"pantau minggu depan")
        else:
            desc = ""

        return {
            "detected":              detected,
            "weeks_confirmed":       step_up_count,
            "vol_gain_pct":          round(vol_gain_pct, 1),
            "avg_weekly_range_pct":  round(avg_range, 1),
            "strength":              strength,
            "description":           desc,
        }

    except Exception:
        return _empty


# ─────────────────────────────────────────────────────────────────────────────
# Pump Fingerprint Detector — Historical Pre-Pump Pattern Recognition
# Reverse-engineer kondisi sebelum pump terjadi dari data historis
# "Market mover ada kepentingan" — kita cari jejaknya di OHLCV
# ─────────────────────────────────────────────────────────────────────────────

def detect_pump_fingerprint(
    ticker: str,
    close_daily: pd.Series,
    vol_daily: pd.Series,
    high_daily: pd.Series,
    low_daily: pd.Series,
    floor_price: float = 0.0,
    pump_threshold_pct: float = 20.0,
    pump_window_days: int = 10,
    pre_pump_days: int = 20,
    min_pumps: int = 1,
) -> dict:
    """
    Detect pump fingerprint dari historis OHLCV.

    Alur:
    1. Aggregate daily → weekly untuk identifikasi pump events (lebih banyak historis)
    2. Untuk setiap pump, analisis 20 hari pre-pump di daily:
       - supply concentration (market_mover_proxy)
       - pengeringan detected
       - vol step-up pattern
       - floor proximity
    3. Build fingerprint dari rata-rata kondisi pre-pump
    4. Bandingkan kondisi hari ini vs fingerprint → similarity_score

    Similarity bobot:
       market_mover_proxy  35%  (supply ketat = ada kepentingan)
       pengeringan         30%  (barang kering = siap digerakkan)
       vol_step_up         20%  (akumulasi gradual)
       floor_proximity     15%  (entry point market mover)

    Confidence:
       HIGH/MEDIUM  jika pump_count >= 2
       LOW          jika pump_count == 1
       None         jika pump_count == 0 → return empty
    """
    _empty = {
        "detected":          False,
        "pump_count":        0,
        "confidence":        "NONE",
        "fingerprint":       "",
        "avg_pre_pump_days": 0,
        "avg_pengeringan":   False,
        "avg_vol_stepup":    False,
        "avg_supply_tight":  0.0,
        "avg_floor_dist":    0.0,
        "currently_matches": False,
        "similarity_score":  0.0,
        "description":       "",
    }

    if len(close_daily) < 60:
        return _empty

    try:
        # ── Step 1: Aggregate daily → weekly, identifikasi pump events ────────
        df_d = pd.DataFrame({
            "close": close_daily.values,
            "vol":   vol_daily.values,
            "high":  high_daily.values,
            "low":   low_daily.values,
        }, index=close_daily.index)

        weekly = df_d.resample("W").agg({
            "close": "last",
            "vol":   "sum",
            "high":  "max",
            "low":   "min",
        }).dropna()

        # Pump = close naik >threshold% dalam 2 minggu (weekly equivalent dari 10 hari)
        pump_events = []  # list of (pump_start_daily_idx, pump_pct)
        pump_window_weeks = max(2, pump_window_days // 5)

        for i in range(pump_window_weeks, len(weekly)):
            prev_close = float(weekly["close"].iloc[i - pump_window_weeks])
            curr_close = float(weekly["close"].iloc[i])
            if prev_close <= 0:
                continue
            ret = (curr_close / prev_close - 1) * 100
            if ret >= pump_threshold_pct:
                # Map weekly pump start back ke daily index
                pump_week_start = weekly.index[i - pump_window_weeks]
                # Cari daily index yang paling dekat dengan tanggal ini
                daily_candidates = close_daily.index[close_daily.index <= pump_week_start]
                if len(daily_candidates) == 0:
                    continue
                daily_idx = len(close_daily.index) - len(close_daily.index[close_daily.index >= daily_candidates[-1]])
                if daily_idx < pre_pump_days:
                    continue  # tidak cukup pre-pump data
                pump_events.append({
                    "daily_idx":  daily_idx,
                    "pump_pct":   round(ret, 1),
                    "pump_date":  str(pump_week_start)[:10],
                })

        # Deduplicate: kalau 2 pump terlalu dekat (< 20 hari), ambil yang lebih besar
        deduped = []
        for ev in pump_events:
            if deduped and (ev["daily_idx"] - deduped[-1]["daily_idx"]) < 20:
                if ev["pump_pct"] > deduped[-1]["pump_pct"]:
                    deduped[-1] = ev
            else:
                deduped.append(ev)
        pump_events = deduped

        pump_count = len(pump_events)
        if pump_count < min_pumps:
            return _empty

        # ── Step 2: Analisis pre-pump conditions untuk setiap pump event ──────
        vol_ma_global = float(vol_daily.rolling(20).mean().iloc[-1])

        fingerprints = []
        for ev in pump_events:
            idx = ev["daily_idx"]
            pre_start = max(0, idx - pre_pump_days)
            pre_end   = idx

            pre_close = close_daily.iloc[pre_start:pre_end]
            pre_vol   = vol_daily.iloc[pre_start:pre_end]
            pre_high  = high_daily.iloc[pre_start:pre_end]
            pre_low   = low_daily.iloc[pre_start:pre_end]

            if len(pre_close) < 10:
                continue

            pre_vol_ma = float(pre_vol.mean())

            # (A) Market mover proxy — supply concentration score (0-1)
            # High vol + flat price days = supply diserap institusi
            accum_days = 0
            distrib_days = 0
            for j in range(len(pre_close) - 1):
                v  = float(pre_vol.iloc[j])
                c  = float(pre_close.iloc[j])
                lo = float(pre_low.iloc[j])
                hi = float(pre_high.iloc[j])
                c_prev = float(pre_close.iloc[j - 1]) if j > 0 else c
                price_move = abs(c - c_prev) / c_prev * 100 if c_prev > 0 else 0
                candle_range = hi - lo
                close_pos = ((c - lo) / candle_range) if candle_range > 0 else 0.5
                if v > pre_vol_ma * 1.5 and price_move < 1.5:
                    if close_pos >= 0.5:
                        accum_days += 1
                    else:
                        distrib_days += 1
            supply_score = max(0.0, min(1.0,
                (accum_days - distrib_days) / max(len(pre_close) * 0.3, 1)
            ))

            # (B) Pengeringan — vol declining + range narrowing (bool)
            vol_first_half = float(pre_vol.iloc[:len(pre_vol)//2].mean())
            vol_second_half = float(pre_vol.iloc[len(pre_vol)//2:].mean())
            range_20d = float((pre_high.max() - pre_low.min()) / float(pre_close.iloc[-1]) * 100) if float(pre_close.iloc[-1]) > 0 else 999
            pengeringan_pre = (vol_second_half < vol_first_half * 0.85 and range_20d < 15)

            # (C) Vol step-up — weekly aggregate dari pre-pump period (bool)
            pre_df_temp = pd.DataFrame({
                "vol": pre_vol.values, "close": pre_close.values
            }, index=pre_vol.index)
            pre_weekly_vol = pre_df_temp["vol"].resample("W").sum().dropna()
            stepup_count = sum(
                1 for k in range(1, len(pre_weekly_vol))
                if float(pre_weekly_vol.iloc[k]) > float(pre_weekly_vol.iloc[k-1])
            )
            vol_stepup_pre = stepup_count >= max(2, len(pre_weekly_vol) - 1)

            # (D) Floor proximity — seberapa dekat harga dari floor saat pre-pump
            last_pre_close = float(pre_close.iloc[-1])
            fp = floor_price if floor_price > 0 else float(pre_low.min())
            floor_dist_pre = ((last_pre_close - fp) / fp * 100) if fp > 0 else 50.0

            fingerprints.append({
                "supply_score":    supply_score,
                "pengeringan":     pengeringan_pre,
                "vol_stepup":      vol_stepup_pre,
                "floor_dist":      floor_dist_pre,
                "pump_pct":        ev["pump_pct"],
            })

        if not fingerprints:
            return _empty

        # ── Step 3: Build aggregate fingerprint ───────────────────────────────
        n = len(fingerprints)
        avg_supply   = float(np.mean([f["supply_score"] for f in fingerprints]))
        avg_peng     = sum(1 for f in fingerprints if f["pengeringan"]) / n >= 0.5
        avg_stepup   = sum(1 for f in fingerprints if f["vol_stepup"]) / n >= 0.5
        avg_floor    = float(np.mean([f["floor_dist"] for f in fingerprints]))
        avg_pump_pct = float(np.mean([f["pump_pct"] for f in fingerprints]))

        # Fingerprint type — lebih spesifik untuk MIXED
        gradual_count = sum(1 for f in fingerprints if f["pengeringan"] and f["vol_stepup"])
        spike_count   = sum(1 for f in fingerprints if not f["pengeringan"] and f["supply_score"] > 0.4)
        goren_count   = sum(1 for f in fingerprints if f["supply_score"] < 0.3 and f["pump_pct"] > 40)

        if avg_supply >= 0.5 and avg_peng:
            fingerprint_type = "GRADUAL_INST"     # institusi akumulasi bertahap
        elif avg_supply >= 0.5 and avg_stepup:
            fingerprint_type = "STEP_UP_INST"     # institusi dengan vol step-up
        elif avg_supply < 0.3 and avg_pump_pct > 40:
            fingerprint_type = "GORENGAN"          # pump cepat tanpa akumulasi
        elif gradual_count > 0 and goren_count > 0:
            fingerprint_type = "MIXED_INST_GOREN"  # sebagian institusi, sebagian gorengan
        elif gradual_count > 0:
            fingerprint_type = "MIXED_INST"        # campuran pola institusi
        else:
            fingerprint_type = "MIXED"             # tidak ada pola dominan

        confidence = "HIGH" if pump_count >= 3 else "MEDIUM" if pump_count >= 2 else "LOW"

        # ── Step 4: Compare kondisi hari ini vs fingerprint ───────────────────
        # Current conditions
        last_20d_close = close_daily.tail(pre_pump_days)
        last_20d_vol   = vol_daily.tail(pre_pump_days)
        last_20d_high  = high_daily.tail(pre_pump_days)
        last_20d_low   = low_daily.tail(pre_pump_days)

        # Current supply score
        cur_accum = cur_distrib = 0
        cur_vol_ma = float(last_20d_vol.mean())
        for j in range(len(last_20d_close) - 1):
            v  = float(last_20d_vol.iloc[j])
            c  = float(last_20d_close.iloc[j])
            lo = float(last_20d_low.iloc[j])
            hi = float(last_20d_high.iloc[j])
            c_prev = float(last_20d_close.iloc[j-1]) if j > 0 else c
            price_move = abs(c - c_prev) / c_prev * 100 if c_prev > 0 else 0
            candle_range = hi - lo
            close_pos = ((c - lo) / candle_range) if candle_range > 0 else 0.5
            if v > cur_vol_ma * 1.5 and price_move < 1.5:
                if close_pos >= 0.5:
                    cur_accum += 1
                else:
                    cur_distrib += 1
        cur_supply = max(0.0, min(1.0,
            (cur_accum - cur_distrib) / max(len(last_20d_close) * 0.3, 1)
        ))

        # Current pengeringan
        v_first = float(last_20d_vol.iloc[:10].mean())
        v_last  = float(last_20d_vol.iloc[10:].mean())
        cur_range = float((last_20d_high.max() - last_20d_low.min()) / float(last_20d_close.iloc[-1]) * 100) if float(last_20d_close.iloc[-1]) > 0 else 999
        cur_peng = (v_last < v_first * 0.85 and cur_range < 15)

        # Current vol step-up (weekly)
        cur_df_temp = pd.DataFrame({"vol": last_20d_vol.values}, index=last_20d_vol.index)
        cur_weekly_vol = cur_df_temp["vol"].resample("W").sum().dropna()
        cur_stepup_count = sum(
            1 for k in range(1, len(cur_weekly_vol))
            if float(cur_weekly_vol.iloc[k]) > float(cur_weekly_vol.iloc[k-1])
        )
        cur_stepup = cur_stepup_count >= max(2, len(cur_weekly_vol) - 1)

        # Current floor proximity
        last_close = float(close_daily.iloc[-1])
        fp_now = floor_price if floor_price > 0 else float(low_daily.tail(60).min())
        cur_floor_dist = ((last_close - fp_now) / fp_now * 100) if fp_now > 0 else 50.0

        # ── Similarity scoring (weighted) ─────────────────────────────────────
        # Market mover proxy (35%): supply score similarity
        supply_sim = 1.0 - min(1.0, abs(cur_supply - avg_supply) / max(avg_supply, 0.1))

        # Pengeringan (30%): boolean match
        peng_sim = 1.0 if (cur_peng == avg_peng) else 0.3

        # Vol step-up (20%): boolean match
        stepup_sim = 1.0 if (cur_stepup == avg_stepup) else 0.3

        # Floor proximity (15%): within 10% of historical floor distance
        floor_diff = abs(cur_floor_dist - avg_floor)
        floor_sim = max(0.0, 1.0 - floor_diff / 20.0)

        similarity_score = (
            supply_sim  * 0.35 +
            peng_sim    * 0.30 +
            stepup_sim  * 0.20 +
            floor_sim   * 0.15
        )

        # LOW confidence → bobot similarity dikurangi 50%
        if confidence == "LOW":
            similarity_score *= 0.5

        currently_matches = similarity_score >= 0.60

        # Description
        match_parts = []
        if cur_supply >= avg_supply * 0.8:
            match_parts.append("supply ketat")
        if cur_peng and avg_peng:
            match_parts.append("pengeringan aktif")
        if cur_stepup and avg_stepup:
            match_parts.append("vol step-up")
        if cur_floor_dist <= avg_floor * 1.2:
            match_parts.append(f"dekat floor ({cur_floor_dist:.0f}%)")

        if currently_matches:
            desc = (f"Mirip pre-pump historis ({pump_count}x pump, avg +{avg_pump_pct:.0f}%) — "
                    f"{', '.join(match_parts) if match_parts else 'pola terkonfirmasi'}")
        else:
            desc = (f"Belum mirip pre-pump historis ({pump_count}x pump) — "
                    f"similarity {similarity_score:.0%}")

        return {
            "detected":           currently_matches,
            "pump_count":         pump_count,
            "confidence":         confidence,
            "fingerprint":        fingerprint_type,
            "avg_pre_pump_days":  pre_pump_days,
            "avg_pengeringan":    avg_peng,
            "avg_vol_stepup":     avg_stepup,
            "avg_supply_tight":   round(avg_supply, 2),
            "avg_floor_dist":     round(avg_floor, 1),
            "avg_pump_pct":       round(avg_pump_pct, 1),
            "currently_matches":  currently_matches,
            "similarity_score":   round(similarity_score, 2),
            "cur_supply":         round(cur_supply, 2),
            "cur_pengeringan":    cur_peng,
            "cur_vol_stepup":     cur_stepup,
            "cur_floor_dist":     round(cur_floor_dist, 1),
            "description":        desc,
        }

    except Exception as _e:
        logger.debug(f"[PumpFP] {ticker} error: {_e}")
        return _empty


# ─────────────────────────────────────────────────────────────────────────────
# Whale Defense Test
# "Kalau dihantam tapi tidak jatuh → ada yang nampung" (Hengky)
# ─────────────────────────────────────────────────────────────────────────────

def hitung_barang(
    close: pd.Series,
    vol: pd.Series,
    high: pd.Series,
    low: pd.Series,
    open_: pd.Series = None,
) -> dict:
    """
    Estimates supply concentration from price + volume behavior.

    Hengky's actual formula requires broker data (SQ/MG lot counts).
    We proxy this from yfinance using:

    1. ACCUMULATION RATIO — what % of total float has been absorbed
       by large buyers over the past 20 days
       Proxy: days where vol > 2× avg AND price barely moved (<1%)
       = barang berpindah dari retail ke institusi tanpa harga naik

    2. SUPPLY TIGHTNESS — how thin the available supply is
       Proxy: vol_ma declining over 20d vs 60d = fewer shares circulating
       = supply makin langka karena udah di-hold

    3. CONTROL SCORE — 0-10
       Hengky: "384K lot dari 3M float = 12.8% = almost nothing left"
       We estimate: berapa % dari average daily vol yang "absorbed"
       oleh buyer institusional (vol spike days with flat price)

    V5: Tambah candle body direction filter.
    Volume tinggi + harga flat bisa = akumulasi ATAU distribusi tersembunyi.
    Bedanya ada di candle body:
    - Close di upper half candle (close > midpoint) = buyer yang nampung → AKUMULASI
    - Close di lower half candle (close < midpoint) = seller yang mendominasi → DISTRIBUSI

    Returns dict with:
    - absorbed_pct: estimated % of float absorbed by smart money
    - supply_tightness: 0-10 (10 = supply sangat langka)
    - control_score: 0-10 (Hengky's math equivalent)
    - hitung_barang_desc: human-readable summary
    - is_centralized: bool (True = supply dominated by 1 party)
    - distribution_days: hari dengan pola distribusi tersembunyi
    """
    if len(close) < 20:
        return {"absorbed_pct": 0, "supply_tightness": 0,
                "control_score": 0, "hitung_barang_desc": "",
                "is_centralized": False, "distribution_days": 0}

    # Fallback open_ jika tidak tersedia
    if open_ is None:
        open_ = close.shift(1).fillna(close)

    vol_ma20 = float(vol.rolling(20).mean().iloc[-1])
    vol_ma60 = float(vol.rolling(60).mean().iloc[-1]) if len(vol) >= 60 else vol_ma20

    # Days where volume was high but price barely moved (accumulation signature)
    accum_days        = 0
    accum_vol_total   = 0.0
    distribution_days = 0  # V5: pola distribusi tersembunyi
    total_vol_20d     = float(vol.tail(20).sum())

    for i in range(min(20, len(close) - 1)):
        v     = float(vol.iloc[-(i+1)])
        c     = float(close.iloc[-(i+1)])
        lo    = float(low.iloc[-(i+1)])
        hi    = float(high.iloc[-(i+1)])
        c_prev= float(close.iloc[-(i+2)])
        price_move = (abs(c - c_prev) / c_prev * 100) if c_prev > 0 else 0.0

        # V5: Candle body direction — close position dalam candle range
        candle_range = hi - lo
        # close_pos: 1.0 = close di high, 0.0 = close di low
        close_pos = ((c - lo) / candle_range) if candle_range > 0 else 0.5

        # High volume + low price movement
        if v > vol_ma20 * 1.5 and price_move < 1.5:
            if close_pos >= 0.5:
                # Close di upper half = buyer yang absorb → AKUMULASI
                accum_days += 1
                accum_vol_total += v
            else:
                # Close di lower half = seller yang mendominasi → DISTRIBUSI TERSEMBUNYI
                distribution_days += 1

    # What % of 20d volume was "absorbed" (accumulation-type days)
    absorbed_pct = (accum_vol_total / total_vol_20d * 100) if total_vol_20d > 0 else 0

    # Supply tightness: vol_ma declining = supply leaving market (being locked up)
    vol_trend = vol_ma20 / vol_ma60 if vol_ma60 > 0 else 1.0
    # vol_trend < 1.0 means volume declining = supply getting absorbed
    tightness_score = max(0, min(10, int((1 - vol_trend) * 20 + 5)))

    # Range contraction: price range narrowing over 20d vs 60d
    _c_last = float(close.iloc[-1])
    range_20d = float((high.tail(20).max() - low.tail(20).min()) / _c_last * 100) if _c_last > 0 else 0.0
    range_60d = (float((high.tail(60).max() - low.tail(60).min()) / _c_last * 100) if (len(close) >= 60 and _c_last > 0) else range_20d)
    range_ratio = (range_20d / range_60d) if range_60d > 0.001 else 1.0
    # range_ratio < 0.5 = price compressed (compression zone = order block forming)

    # Control score (Hengky math proxy)
    control_score = 0
    if absorbed_pct > 40:  control_score += 3
    elif absorbed_pct > 25: control_score += 2
    elif absorbed_pct > 15: control_score += 1

    if tightness_score >= 7: control_score += 3
    elif tightness_score >= 5: control_score += 2
    elif tightness_score >= 3: control_score += 1

    if accum_days >= 5:  control_score += 2
    elif accum_days >= 3: control_score += 1

    if range_ratio < 0.4: control_score += 2  # strong compression
    elif range_ratio < 0.6: control_score += 1

    # V5: Penalti distribusi tersembunyi
    # Kalau lebih banyak distribution_days vs accum_days = sinyal palsu
    if distribution_days > accum_days:
        control_score = max(0, control_score - 2)  # penalti signifikan
    elif distribution_days > 0:
        control_score = max(0, control_score - 1)  # penalti ringan

    control_score = min(control_score, 10)
    is_centralized = control_score >= 6

    # Build description
    parts = []
    if absorbed_pct > 30:
        parts.append(f"~{absorbed_pct:.0f}% vol diserap institusi")
    if accum_days >= 3:
        parts.append(f"akumulasi {accum_days}h tanpa harga naik")
    if distribution_days >= 2:
        parts.append(f"⚠️ {distribution_days}h distribusi tersembunyi terdeteksi")
    if range_ratio < 0.5:
        parts.append(f"range menyempit {range_ratio:.0%} → compression")
    if tightness_score >= 6:
        parts.append("supply makin langka")

    desc = "Hitung barang: " + " · ".join(parts) if parts else ""

    return {
        "absorbed_pct":         round(absorbed_pct, 1),
        "supply_tightness":     tightness_score,
        "control_score":        control_score,
        "range_ratio":          round(range_ratio, 2),
        "accum_days_20d":       accum_days,
        "distribution_days":    distribution_days,
        "vol_trend":            round(vol_trend, 2),
        "hitung_barang_desc":   desc,
        "is_centralized":       is_centralized,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ORDER BLOCK DETECTION — Institutional Footprint
# "Compression → Expansion → Revisit" (Order Block video)
# ─────────────────────────────────────────────────────────────────────────────

def detect_order_block(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    vol: pd.Series,
    atr: "pd.Series | None" = None,
) -> dict:
    """
    Detects institutional order blocks from price behavior.

    Order Block = compression zone before strong displacement.
    "Not just a candle — it's a process: accumulation, manipulation, expansion."

    Algorithm:
    1. Find compression zones: N bars where range < 50% of avg range
    2. Find displacement: strong bar (range > 1.5× ATR) breaking out of compression
    3. Classify: bullish OB (displacement up) or bearish OB (displacement down)
    4. Check if price has REVISITED the OB (rebalancing = entry opportunity)

    Returns:
    - ob_detected: bool
    - ob_type: 'BULLISH' | 'BEARISH' | None
    - ob_high: float (top of order block zone)
    - ob_low: float (bottom of order block zone)
    - ob_strength: 0-10
    - in_ob_zone: bool (current price inside OB = potential entry)
    - ob_desc: description
    """
    if len(close) < 30:
        return {"ob_detected": False, "ob_type": None,
                "ob_high": 0, "ob_low": 0, "ob_strength": 0,
                "in_ob_zone": False, "ob_desc": ""}

    # Compute bar ranges
    ranges     = (high - low).values
    avg_range  = float(np.mean(ranges[-30:].astype(float))) if len(ranges) >= 5 else 1.0
    avg_range  = max(avg_range, 1.0)  # prevent division by zero
    current    = float(close.iloc[-1])

    # ATR proxy if not provided
    if atr is None:
        atr_val = max(avg_range, 1.0)
    else:
        atr_val = float(atr.iloc[-1]) if len(atr) > 0 else avg_range

    best_ob = None
    best_strength = 0

    # Scan last 30 bars for compression → displacement patterns
    for end in range(5, min(30, len(close))):
        # Look for 3-7 bar compression
        for comp_len in range(3, 8):
            start = end - comp_len
            if start < 0:
                continue

            comp_highs  = high.iloc[-end:-end+comp_len] if end > comp_len else high.iloc[:comp_len]
            comp_lows   = low.iloc[-end:-end+comp_len]  if end > comp_len else low.iloc[:comp_len]
            comp_range  = float(comp_highs.max() - comp_lows.min())

            # Compression condition: tight range
            if avg_range <= 0 or comp_range > avg_range * 1.2:
                continue

            # Look for displacement bar right after compression
            disp_idx = -(end - comp_len) - 1
            if abs(disp_idx) > len(close):
                continue

            disp_range = float(high.iloc[disp_idx] - low.iloc[disp_idx])
            disp_close = float(close.iloc[disp_idx])

            # Displacement must be strong (> 1.5× ATR)
            if disp_range < atr_val * 1.2:
                continue

            # Classify direction
            is_bullish = disp_close > float(comp_highs.max())
            is_bearish = disp_close < float(comp_lows.min())

            if not (is_bullish or is_bearish):
                continue

            # OB zone = the compression zone itself
            ob_high = float(comp_highs.max())
            ob_low  = float(comp_lows.min())

            # Strength scoring
            strength = 0
            # Compression tightness
            tightness = (1 - (comp_range / (avg_range * comp_len))
                           if (avg_range > 0 and comp_len > 0) else 0.0)
            strength += min(4, int(tightness * 6))
            # Displacement strength
            disp_mult = (disp_range / atr_val) if atr_val > 0 else 0.0
            strength += min(3, int(disp_mult - 1))
            # Volume during compression (should be lower than avg)
            comp_vols = vol.iloc[-end:-end+comp_len] if end > comp_len else vol.iloc[:comp_len]
            vol_ma    = float(vol.rolling(20).mean().iloc[-1])
            if float(comp_vols.mean()) < vol_ma * 0.8:
                strength += 2  # quiet accumulation
            if float(comp_vols.mean()) < vol_ma * 0.6:
                strength += 1

            strength = min(strength, 10)

            if strength > best_strength:
                best_strength = strength
                best_ob = {
                    "ob_type":   "BULLISH" if is_bullish else "BEARISH",
                    "ob_high":   ob_high,
                    "ob_low":    ob_low,
                    "ob_range":  comp_range,
                    "bars_ago":  end,
                }

    if best_ob is None or best_strength < 3:
        return {"ob_detected": False, "ob_type": None,
                "ob_high": 0, "ob_low": 0, "ob_strength": 0,
                "in_ob_zone": False, "ob_desc": ""}

    # Check if current price is in or near OB zone (revisit = entry signal)
    ob_h = best_ob["ob_high"]
    ob_l = best_ob["ob_low"]
    in_zone   = ob_l <= current <= ob_h
    near_zone = ob_l * 0.97 <= current <= ob_h * 1.03

    # Build description
    zone_str  = "🎯 DI DALAM OB ZONE" if in_zone else ("⬇ MENDEKATI OB" if near_zone else f"OB {best_ob['bars_ago']}b lalu")
    desc = (f"Order Block {best_ob['ob_type']}: "
            f"Rp{ob_l:,.0f}–{ob_h:,.0f} | {zone_str} | "
            f"Strength {best_strength}/10")

    return {
        "ob_detected":   True,
        "ob_type":       best_ob["ob_type"],
        "ob_high":       round(ob_h, 0),
        "ob_low":        round(ob_l, 0),
        "ob_strength":   best_strength,
        "in_ob_zone":    in_zone,
        "near_ob_zone":  near_zone,
        "ob_bars_ago":   best_ob["bars_ago"],
        "ob_desc":       desc,
    }


def test_whale_defense(close: pd.Series, vol: pd.Series, low: pd.Series, high: pd.Series, floor_price: float = 0.0) -> dict:
    """
    Simulates the 'bit-over test' Hengky uses:
    Kalau ada hari di mana volume spike tapi harga tidak jatuh jauh → ada whale yang defend.

    V5: Window diperlebar 5 → 20 hari.
    Smart whale afiliasi emiten biasanya defend bertahap 2-4 minggu, bukan hanya 5 hari.
    Defense dinilai dalam dua tier:
    - Recent (5 hari): bobot lebih tinggi — defend aktif sekarang
    - Extended (6-20 hari): bobot lebih rendah — pola defend historis
    """
    vol_ma = float(vol.rolling(20).mean().iloc[-1])
    if vol_ma <= 0:
        return {"defending": False, "defense_score": 0}

    defense_days_recent   = 0  # 5 hari terakhir
    defense_days_extended = 0  # 6-20 hari terakhir

    window = min(20, len(close) - 2)
    for i in range(window):
        v      = float(vol.iloc[-(i+1)])
        c      = float(close.iloc[-(i+1)])
        lo     = float(low.iloc[-(i+1)])
        hi     = float(high.iloc[-(i+1)])
        prev_c = float(close.iloc[-(i+2)])

        is_heavy_vol  = v > vol_ma * 2.0
        price_dropped = c < prev_c
        recovered     = ((c - lo) / (hi - lo) > 0.5) if (hi - lo) > 0 else False
        defended      = is_heavy_vol and price_dropped and recovered

        if defended:
            if i < 5:
                defense_days_recent += 1
            else:
                defense_days_extended += 1

    defense_days = defense_days_recent + defense_days_extended
    # Recent defense bernilai 3x, extended 1x — reflect urgency temporal
    defense_score = min(defense_days_recent * 3 + defense_days_extended * 1, 5)
    is_defending  = defense_days_recent >= 1 or defense_days_extended >= 2

    if defense_days_recent > 0 and defense_days_extended > 0:
        desc = f"Whale defend {defense_days_recent}x (5h) + {defense_days_extended}x (20h) — pola bertahap"
    elif defense_days_recent > 0:
        desc = f"Whale defend {defense_days_recent}x dalam 5 hari"
    elif defense_days_extended > 0:
        desc = f"Whale defend {defense_days_extended}x dalam 20 hari — akumulasi bertahap"
    else:
        desc = ""

    # V6: Floor proximity gate — defense hanya meaningful jika terjadi dekat floor
    # Defend di random harga = bisa noise/panic buy, bukan smart money
    # Defend di dekat floor (within 15%) = ada kepentingan di level itu
    defense_near_floor = False
    if floor_price > 0 and is_defending:
        last_close_val = float(close.iloc[-1])
        pct_from_floor = (last_close_val / floor_price - 1) * 100 if floor_price > 0 else 999
        defense_near_floor = pct_from_floor <= 15.0
        if not defense_near_floor:
            # Defense terjadi tapi jauh dari floor — kurangi bobot
            defense_score = max(0, defense_score - 2)
            if defense_days_recent == 0 and defense_days_extended <= 1:
                is_defending = False  # terlalu jauh + terlalu lemah = noise
            desc = desc + f" (jauh dari floor +{pct_from_floor:.0f}% — bobot dikurangi)" if desc else ""
    else:
        defense_near_floor = floor_price == 0  # tidak ada floor data = tidak bisa judge

    return {
        "defending":              is_defending,
        "defense_days":           defense_days,
        "defense_days_recent":    defense_days_recent,
        "defense_days_extended":  defense_days_extended,
        "defense_score":          defense_score,
        "defense_near_floor":     defense_near_floor,
        "description":            desc,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Smart Money vs Dumb Money Classification
# ─────────────────────────────────────────────────────────────────────────────

def classify_whale_quality(result: dict) -> str:
    """
    Hengky: "Smart whale defend waktu turun. Dumb whale biarkan drift."

    V4 update: tambah control_score (hitung barang), OB zone, VP zone, free float.
    Threshold disesuaikan karena max score naik dari 13 → 20.
    SMART ≥ 13 | LIKELY_SMART ≥ 8 | UNCERTAIN ≥ 4
    """
    score = 0

    # Floor proximity (0–3)
    zone = result.get("entry_zone", "FAR_FROM_FLOOR")
    if zone == "AT_FLOOR":    score += 3
    elif zone == "NEAR_FLOOR": score += 2
    elif zone == "MID_RANGE":  score += 1

    # Pengeringan (0–3)
    if result.get("pengeringan_detected"):        score += 2
    if result.get("pengeringan_strength",0) >= 4: score += 1

    # Whale defense (0–3)
    if result.get("whale_defending"):          score += 2
    if result.get("defense_days",0) >= 2:      score += 1

    # Accumulation pattern + EMA (0–3)
    if result.get("pattern") == "SUSTAINED":  score += 2
    if result.get("ema_trend") == "BULLISH":  score += 1

    # Momentum (0–2)
    # FIX: REVERSING (mom_5d>0, mom_10d<0) tidak dapat boost — tren 10h masih turun
    mom = result.get("momentum","")
    if mom == "ACCELERATING": score += 1
    # REVERSING sengaja tidak diberi score — false momentum signal

    # V4: Hitung Barang — supply concentration (0–2)
    ctrl = result.get("control_score", 0)
    if ctrl >= 7:   score += 2
    elif ctrl >= 4: score += 1

    # V4: Order Block — institutional footprint (0–2)
    if result.get("in_ob_zone"):    score += 2
    elif result.get("near_ob_zone"): score += 1

    # V4: Volume Profile — price near accumulation zone (0–1)
    if result.get("vp_near_val") or result.get("vp_in_value"): score += 1

    # Free float tight = supply terpusat = lebih mudah naik (0–1)
    ff = result.get("free_float", 100)
    if ff <= 15: score += 1

    # V6: Relative Strength vs IHSG (0–2)
    # Outperform market = ada yang defend/akumulasi diam-diam
    if result.get("rs_ok"):
        rs_20d = result.get("rs_20d", 0)
        if rs_20d > 5:   score += 2   # strong outperform >5%
        else:            score += 1   # mild outperform

    # V5: Gradual accumulation — weekly step-up (0–2)
    if result.get("gradual_accum"):
        ga_strength = result.get("gradual_strength", 1)
        score += min(ga_strength, 2)
    elif result.get("gradual_strength", 0) == 1:
        score += 1

    # Fix A: Trigger candle — whale mulai push (0–2)
    # Sinyal timing terkuat: transisi akumulasi → markup terkonfirmasi hari ini
    # Tidak ada di whale_quality sebelumnya → fungsi berjalan sendiri tanpa memperkuat quality
    if result.get("trigger_candle"):
        score += 2
        # Fix C: combinatorial — pengeringan selesai + trigger = sekuens sempurna
        if result.get("pengeringan_detected") and not result.get("is_false", False):
            score += 1  # sekuens barang kering → push dimulai = konfirmasi terkuat

    # V5: Pump fingerprint — kondisi sekarang mirip pre-pump historis (0–3)
    if result.get("pump_fp_matches"):
        sim  = result.get("pump_fp_similarity", 0.0)
        conf = result.get("pump_fp_confidence", "LOW")
        if conf == "HIGH" and sim >= 0.75:   score += 3
        elif conf in ("HIGH","MEDIUM") and sim >= 0.60: score += 2
        else:                                  score += 1  # LOW confidence match

    # V5: Afiliasi emiten — owner broker diketahui (0–3)
    # Ini signal terkuat: kalau broker owner emiten yang beli = insider accumulation
    owner_broker    = result.get("owner_broker", "")
    broker_signal   = result.get("broker_signal", "")
    broker_type     = result.get("broker_type", "")
    broker_live     = result.get("broker_live", False)
    ownership_data  = result.get("_ownership", {})
    owner_confidence = ownership_data.get("confidence", "") if ownership_data else ""

    if owner_broker:
        # Owner broker diketahui — afiliasi emiten confirmed
        if owner_confidence == "HIGH":   score += 3
        elif owner_confidence == "MEDIUM": score += 2
        else:                              score += 1
        # Bonus: kalau broker live data confirm aktif beli hari ini
        if broker_live and broker_signal == "SMART": score += 1
    elif broker_signal == "SMART":
        # Tidak tahu owner broker-nya, tapi broker yang aktif adalah institusi smart
        score += 1
        if broker_type in ("OWNER_PROXY", "MARKET_MAKER") and broker_live:
            score += 1  # live confirmation dari broker yang biasa dipakai owner

    # V6: Normalisasi + Gate System
    # Max theoretical score ~31 — normalisasi ke 0-100
    MAX_SCORE = 34.0  # Fix A+C: +2 trigger_candle + +1 combinatorial peng+trigger
    score_pct = round(score / MAX_SCORE * 100)

    # Gate variables
    ctrl = result.get("control_score", 0)
    ff   = result.get("free_float", 100)
    has_peng    = result.get("pengeringan_detected", False) and not result.get("is_false", False)
    has_defense = result.get("whale_defending", False)
    has_floor   = result.get("entry_zone", "") in ("AT_FLOOR", "NEAR_FLOOR")

    # V6: Slow exit override — kalau whale sedang exit, score di-cap keras
    # Tidak peduli seberapa bagus sinyal lain, jangan masuk saat distribusi aktif
    slow_exit         = result.get("slow_exit", False)
    slow_exit_strength = result.get("slow_exit_strength", 0)
    if slow_exit and slow_exit_strength >= 2:
        # Strong slow exit: cap di UNCERTAIN maksimum
        if score_pct >= 40: return "UNCERTAIN"
        if score_pct >= 20: return "UNCERTAIN"
        return "DUMB"
    elif slow_exit:
        # Weak slow exit: cap di LIKELY_SMART
        if score_pct >= 60: return "LIKELY_SMART"

    # Free float override: ff>60% cap ctrl ke 3
    if ff > 60 and ctrl > 3:
        ctrl = 3

    # Minimum requirement gate untuk SMART:
    # Wajib ada (pengeringan OR defense) AND floor proximity
    # Ini adalah Hengky core: barang kering + harga di support
    _behavioral_ok  = has_peng or has_defense
    _floor_ok       = has_floor
    _meets_smart_req = _behavioral_ok and _floor_ok

    # Control gate: supply bebas → cap klasifikasi
    if ctrl <= 3:
        # Supply terlalu bebas — cap di LIKELY_SMART
        if score_pct >= 60 and _meets_smart_req: return "LIKELY_SMART"
        if score_pct >= 40:  return "LIKELY_SMART"
        if score_pct >= 20:  return "UNCERTAIN"
        return "DUMB"
    elif ctrl <= 5 and not _behavioral_ok:
        # Supply medium tapi tidak ada konfirmasi behavioral
        if score_pct >= 60:  return "LIKELY_SMART"
        if score_pct >= 40:  return "LIKELY_SMART"
        if score_pct >= 20:  return "UNCERTAIN"
        return "DUMB"
    else:
        # Control OK — terapkan threshold normalisasi + minimum requirement
        # SMART: score >=60% DAN wajib punya pengeringan/defense + floor
        # FIX: tambah gate EMA — EMA bearish tidak bisa SMART (struktur tren berlawanan)
        # Alasan: SMART whale seharusnya sudah push harga ke atas EMA, bukan masih di bawah
        _ema_bearish = result.get("ema_trend", "") == "BEARISH"
        if score_pct >= 60 and _meets_smart_req and not _ema_bearish: return "SMART"
        if score_pct >= 60 and _meets_smart_req and _ema_bearish:    return "LIKELY_SMART"  # bearish EMA cap
        if score_pct >= 60:                        return "LIKELY_SMART"  # score tinggi tapi missing req
        if score_pct >= 40:                        return "LIKELY_SMART"
        if score_pct >= 20:                        return "UNCERTAIN"
        return "DUMB"


# ─────────────────────────────────────────────────────────────────────────────
# Conviction Scoring — Hengky's framework
# ─────────────────────────────────────────────────────────────────────────────

def compute_conviction(r: dict, vol_ratio: float) -> int:
    """
    0–10 conviction score — unified scoring, semua boost dan cap di satu tempat.

    Opsi B refactor: semua post-hoc boost yang sebelumnya tersebar di _analyze_ticker
    dipindahkan ke sini. Cap dijalankan SEKALI di akhir setelah semua boost selesai
    sehingga tidak ada boost yang bisa bypass cap.

    Urutan eksekusi:
    1. Base scores (vol, pengeringan, floor, defense, EMA, momentum)
    2. Supply + OB scores (hitung barang, order block — dengan synergy gate Fix 4)
    3. Signal confirmation (RS, gradual Fix 3, pump fp, afiliasi, trigger)
    4. Context boosts (VP, POC+peng, free float tight, MSCI/LQ45) — dipindah dari _analyze_ticker
    5. CAPS sekali di akhir: slow exit → supply freedom
    """
    score = 0

    # ── 1. Base scores ────────────────────────────────────────────────────────
    score += min(int(vol_ratio / 1.5), 3)           # Vol ratio (cap 3)
    score += min(r.get("pengeringan_strength", 0), 2)  # Pengeringan

    zone = r.get("entry_zone", "FAR_FROM_FLOOR")    # Floor proximity
    if zone == "AT_FLOOR":      score += 2
    elif zone == "NEAR_FLOOR":  score += 1

    if r.get("whale_defending"):            score += 1  # Whale defense
    if r.get("ema_trend") == "BULLISH":     score += 1  # EMA alignment

    mom = r.get("momentum", "")                         # Momentum (REVERSING = 0)
    if mom == "ACCELERATING": score += 1

    # ── 2. Supply + OB scores (Fix 4: synergy gate OB + gradual) ─────────────
    ctrl = r.get("control_score", 0)
    if ctrl >= 7:   score += 2                      # Hitung Barang
    elif ctrl >= 4: score += 1

    _in_ob       = r.get("in_ob_zone", False)
    _near_ob     = r.get("near_ob_zone", False)
    _has_gradual = r.get("gradual_accum", False) or r.get("gradual_strength", 0) >= 1

    # Fix 4: OB + gradual adalah dua view dari satu fenomena (gradual membentuk OB zone)
    # Jika keduanya true → kurangi OB 1 poin + berikan synergy bonus +1 (net sama tapi eksplisit)
    # Jika hanya OB → full score; Jika hanya gradual → handled di section 3
    if _in_ob and _has_gradual:
        score += 1   # OB dikurangi 1 (dari 2→1) + synergy +1 = net +2 (sama, tapi tidak double-count)
        score += 1   # synergy bonus
    elif _near_ob and _has_gradual:
        score += 0   # near_ob dikurangi 1 (dari 1→0) + synergy +1 = net +1
        score += 1   # synergy bonus
    elif _in_ob:
        score += 2   # full OB score tanpa overlap
    elif _near_ob:
        score += 1   # full near_OB score tanpa overlap

    score += r.get("ms_conviction_boost", 0)        # Market Structure boost

    # ── 3. Signal confirmation scores ─────────────────────────────────────────
    if r.get("rs_ok") and r.get("rs_20d", 0) > 3:  # Relative Strength
        score += 1

    # Fix 3: gradual pakai gradual_strength (konsisten dengan classify_whale_quality)
    # Sebelumnya MRS pakai gradual_weeks, di sini gradual_strength = inkonsisten
    if r.get("gradual_accum"):
        score += min(r.get("gradual_strength", 1), 2)
    elif r.get("gradual_strength", 0) == 1:
        score += 1

    if r.get("pump_fp_matches"):                    # Pump fingerprint
        sim  = r.get("pump_fp_similarity", 0.0)
        conf = r.get("pump_fp_confidence", "LOW")
        if conf in ("HIGH","MEDIUM") and sim >= 0.70: score += 2
        else:                                          score += 1

    _owner_broker = r.get("owner_broker", "")       # Afiliasi emiten
    _broker_signal = r.get("broker_signal", "")
    _broker_live   = r.get("broker_live", False)
    _own_data      = r.get("_ownership", {})
    _confidence    = _own_data.get("confidence", "") if _own_data else ""

    if _owner_broker and _confidence == "HIGH":       score += 2
    elif _owner_broker and _confidence == "MEDIUM":   score += 1
    elif _broker_signal == "SMART" and _broker_live:  score += 1

    if r.get("trigger_candle"):                     # Trigger candle
        score += 1
        if r.get("pengeringan_detected") and not r.get("is_false", False):
            score += 1  # combinatorial: peng selesai + push dimulai

    # ── 4. Context boosts (dipindah dari post-hoc di _analyze_ticker) ─────────
    if r.get("free_float", 100) <= 15:              # Float sangat ketat
        score += 1

    if r.get("vp_near_val") or r.get("vp_in_value"):  # VP near accumulation zone
        score += 1

    if (abs(r.get("vp_pct_from_poc", 99)) < 3 and    # Near POC + pengeringan
            r.get("pengeringan_detected") and not r.get("is_false", False)):
        score += 1

    if r.get("is_msci_candidate") or r.get("is_lq45_candidate"):  # Index candidate
        score += 1

    # ── 5. CAPS — sekali di akhir, mencakup semua boost di atas ─────────────
    # Slow exit cap — konsisten dengan classify_whale_quality
    _slow_exit    = r.get("slow_exit", False)
    _slow_exit_st = r.get("slow_exit_strength", 0)
    if _slow_exit and _slow_exit_st >= 2:
        score = min(score, 4)   # cap keras: UNCERTAIN
    elif _slow_exit:
        score = min(score, 6)   # cap ringan: LIKELY_SMART

    # Supply freedom cap — ff>60% + ctrl<=3
    if r.get("free_float", 100) > 60 and r.get("control_score", 0) <= 3:
        score = min(score, 7)

    return max(0, min(10, score))


# ─────────────────────────────────────────────────────────────────────────────
# Signal Classification
# ─────────────────────────────────────────────────────────────────────────────

def classify_signal(vol_ratio: float, chg_pct: float,
                    pengeringan: dict, defense: dict,
                    mom_5d: float = 0.0, mom_10d: float = 0.0) -> Tuple[str, str, str]:
    """
    Signal mengintegrasikan: vol, pergerakan harga, pengeringan, whale defense.
    FIX: tambah structural momentum gate (mom_5d, mom_10d) agar ACCUMULATION
    tidak terpicu saat struktur tren masih turun.
    """
    is_buy     = chg_pct >  0.5
    is_sell    = chg_pct < -0.5
    is_neutral = not is_buy and not is_sell
    is_block   = vol_ratio >= 5.0
    is_heavy   = vol_ratio >= 3.0
    is_moderate= vol_ratio >= 2.0
    pengeringan_ok = pengeringan.get("detected", False)

    # FIX: structural momentum — kedua timeframe harus positif atau setidaknya netral
    # REVERSING (mom_5d>0, mom_10d<0) tidak memenuhi syarat ACCUMULATION
    mom_structural_ok = mom_5d >= 0 and mom_10d >= -2.0  # toleransi -2% untuk 10d

    # Best case: pengeringan + heavy vol + price up/neutral + whale defend
    # FIX: tambah gate momentum struktural — tidak bisa ACCUMULATION saat 10d tren negatif kuat
    if pengeringan_ok and is_heavy and (is_buy or is_neutral) and defense.get("defending") and mom_structural_ok:
        return "ACCUMULATION", "🟢", "#00ff88"
    # Pengeringan tanpa defense — masih bagus, tapi tetap butuh momentum struktural
    if pengeringan_ok and is_heavy and (is_buy or is_neutral) and mom_structural_ok:
        return "ACCUMULATION", "🟢", "#00ff88"
    # Pengeringan tapi momentum struktural negatif — turunkan ke VOL_SPIKE_UP
    if pengeringan_ok and is_heavy and (is_buy or is_neutral) and not mom_structural_ok:
        return "VOL_SPIKE_UP", "🟡", "#f0b429"
    # Block buy — satu kali beli gede
    if is_block and is_buy:
        return "BLOCK_BUY", "🔵", "#60a5fa"
    # Block sell
    if is_block and is_sell:
        return "BLOCK_SELL", "🟠", "#fb8c00"
    # Heavy vol + buy
    if is_heavy and is_buy:
        return "VOL_SPIKE_UP", "🟡", "#f0b429"
    # Heavy vol + sell = distribusi
    if is_heavy and is_sell:
        return "DISTRIBUTION", "🔴", "#ef4444"
    # Moderate vol + buy
    if is_moderate and is_buy:
        return "VOL_SPIKE_UP", "🟡", "#f0b429"
    return "VOL_NEUTRAL", "⚪", "#94a3b8"


# ─────────────────────────────────────────────────────────────────────────────
# W-8: Sector Classification — Full Ticker + 2-char Prefix Fallback
# Layer 1: full ticker lookup (akurat, ~200 saham paling aktif IDX)
# Layer 2: 2-char prefix fallback (catch remaining tickers)
# ─────────────────────────────────────────────────────────────────────────────

_IDX_SECTOR_MAP: dict = {
    # BANKING / KEUANGAN
    "BBCA":"BANKING","BBRI":"BANKING","BMRI":"BANKING","BBNI":"BANKING",
    "BNGA":"BANKING","BDMN":"BANKING","BNII":"BANKING","BJTM":"BANKING",
    "BJBR":"BANKING","BRIS":"BANKING","BTPS":"BANKING","BACA":"BANKING",
    "AGRO":"BANKING","BBKP":"BANKING","MEGA":"BANKING","NISP":"BANKING",
    "PNBN":"BANKING","MAYA":"BANKING","BMAS":"BANKING","NOBU":"BANKING",
    "DNAR":"BANKING","BBYB":"BANKING","ARTO":"BANKING","BANK":"BANKING",
    "BGTG":"BANKING","ADMF":"FINANCE","MFIN":"FINANCE","BFIN":"FINANCE",
    "CFIN":"FINANCE","VRNA":"FINANCE","WOMF":"FINANCE","IMJS":"FINANCE",
    "HDFA":"FINANCE","MAPI":"RETAIL","LPPF":"RETAIL","ACES":"RETAIL",
    # TELCO / TOWER
    "TLKM":"TELCO","EXCL":"TELCO","ISAT":"TELCO","FREN":"TELCO",
    "TBIG":"TELCO","TOWR":"TELCO","MTEL":"TELCO","SUPR":"TELCO",
    # ENERGY / COAL / MINING
    "PTBA":"MINING","ADRO":"MINING","ITMG":"MINING","HRUM":"MINING",
    "BUMI":"MINING","INDY":"MINING","KKGI":"MINING","DOID":"MINING",
    "GEMS":"MINING","BOSS":"MINING","BYAN":"MINING","MCOL":"MINING",
    "ANTM":"MINING","INCO":"MINING","MDKA":"MINING","NICL":"MINING",
    "NCKL":"MINING","TINS":"MINING","PSAB":"MINING",
    "PGAS":"ENERGY","AKRA":"ENERGY","ESSA":"ENERGY","ELSA":"ENERGY",
    "MEDC":"ENERGY","ENRG":"ENERGY","RAJA":"ENERGY","TBLA":"ENERGY",
    # PROPERTY / KONSTRUKSI
    "BSDE":"PROPERTY","CTRA":"PROPERTY","SMRA":"PROPERTY","PWON":"PROPERTY",
    "LPKR":"PROPERTY","ASRI":"PROPERTY","DILD":"PROPERTY","BEST":"PROPERTY",
    "MDLN":"PROPERTY","JRPT":"PROPERTY","GPRA":"PROPERTY","KIJA":"PROPERTY",
    "PPRO":"PROPERTY","APLN":"PROPERTY","RODA":"PROPERTY","MTLA":"PROPERTY",
    "WIKA":"KONSTRUKSI","PTPP":"KONSTRUKSI","WSKT":"KONSTRUKSI",
    "ADHI":"KONSTRUKSI","TOTL":"KONSTRUKSI","ACST":"KONSTRUKSI","NRCA":"KONSTRUKSI",
    # CONSUMER / F&B / TOBACCO
    "UNVR":"CONSUMER","ICBP":"CONSUMER","INDF":"CONSUMER","MYOR":"CONSUMER",
    "SIDO":"CONSUMER","CLEO":"CONSUMER","ULTJ":"CONSUMER","DLTA":"CONSUMER",
    "ROTI":"CONSUMER","SKLT":"CONSUMER","ADES":"CONSUMER","GOOD":"CONSUMER",
    "CAMP":"CONSUMER","CPIN":"CONSUMER","JPFA":"CONSUMER","MAIN":"CONSUMER",
    "GGRM":"CONSUMER","HMSP":"CONSUMER","WIIM":"CONSUMER","RMBA":"CONSUMER",
    # HEALTHCARE / PHARMA
    "KLBF":"HEALTHCARE","KAEF":"HEALTHCARE","MIKA":"HEALTHCARE","HEAL":"HEALTHCARE",
    "SILO":"HEALTHCARE","SRAJ":"HEALTHCARE","DVLA":"HEALTHCARE","PYFA":"HEALTHCARE",
    "TSPC":"HEALTHCARE","PRDA":"HEALTHCARE","BMHS":"HEALTHCARE","MERK":"HEALTHCARE",
    "SOHO":"HEALTHCARE","ARNA":"HEALTHCARE",
    # INFRA / TOLL
    "JSMR":"INFRA","WTON":"INFRA",
    # MATERIAL / CEMENT / CHEMICAL
    "SMGR":"MATERIAL","INTP":"MATERIAL","SMBR":"MATERIAL","SMCB":"MATERIAL",
    "TPIA":"CHEMICAL","BRPT":"CHEMICAL","DPNS":"CHEMICAL",
    # TECH / DIGITAL / MEDIA
    "GOTO":"TECH","BUKA":"TECH","EMTK":"TECH","KIOS":"TECH",
    "DMMX":"TECH","DCII":"TECH","MTDL":"TECH",
    "MNCN":"MEDIA","SCMA":"MEDIA","FILM":"MEDIA",
    # AUTOMOTIVE / MANUFAKTUR
    "ASII":"AUTOMOTIVE","AUTO":"AUTOMOTIVE","SMSM":"AUTOMOTIVE",
    "IMAS":"AUTOMOTIVE","INDS":"AUTOMOTIVE","LPIN":"AUTOMOTIVE",
    # AGRICULTURE / PLANTATION
    "AALI":"AGRI","LSIP":"AGRI","SIMP":"AGRI","SGRO":"AGRI",
    "SMAR":"AGRI","SSMS":"AGRI","PALM":"AGRI","JAWA":"AGRI",
    "DSFI":"AGRI","BWPT":"AGRI",
    # RETAIL / TRADE
    "ERAA":"RETAIL","MIDI":"RETAIL","HERO":"RETAIL","RALS":"RETAIL",
    "TELE":"RETAIL","MPPA":"RETAIL","CSAP":"RETAIL",
}

_IDX_PREFIX_MAP: dict = {
    # Banking
    "BB":"BANKING","BM":"BANKING","BN":"BANKING","BI":"BANKING",
    "BJ":"BANKING","BT":"BANKING","BD":"BANKING","AG":"BANKING",
    "NO":"BANKING","PN":"BANKING",
    # Telco
    "TL":"TELCO","XL":"TELCO","IS":"TELCO","FR":"TELCO","MT":"TELCO",
    # Mining/Energy
    "PT":"MINING","AD":"MINING","IT":"MINING","HR":"MINING",
    "BU":"MINING","GE":"MINING","BY":"MINING","AN":"MINING",
    "PG":"ENERGY","AK":"ENERGY","EL":"ENERGY","ME":"ENERGY","EN":"ENERGY",
    # Property/Konstruksi
    "BS":"PROPERTY","CT":"PROPERTY","SM":"MATERIAL","PW":"PROPERTY",
    "LP":"PROPERTY","AS":"PROPERTY","DI":"PROPERTY",
    "WI":"KONSTRUKSI","WS":"KONSTRUKSI","DH":"KONSTRUKSI","TO":"KONSTRUKSI",
    # Consumer
    "UN":"CONSUMER","IC":"CONSUMER","MY":"CONSUMER","SI":"CONSUMER",
    "CL":"CONSUMER","UL":"CONSUMER","DL":"CONSUMER","RO":"CONSUMER",
    "SK":"CONSUMER","CP":"CONSUMER","JP":"CONSUMER","GG":"CONSUMER",
    "HM":"CONSUMER","WI":"CONSUMER","AD":"CONSUMER",
    # Healthcare
    "KL":"HEALTHCARE","KA":"HEALTHCARE","MI":"HEALTHCARE","HE":"HEALTHCARE",
    "SL":"HEALTHCARE","DV":"HEALTHCARE","PY":"HEALTHCARE","TS":"HEALTHCARE",
    "PR":"HEALTHCARE","SO":"HEALTHCARE","ME":"HEALTHCARE",
    # Infra/Material
    "JS":"INFRA","WO":"INFRA","TP":"CHEMICAL","BR":"CHEMICAL",
    # Tech/Media
    "GO":"TECH","BK":"TECH","EM":"TECH","MN":"MEDIA","SC":"MEDIA","FI":"MEDIA",
    "DC":"TECH","MT":"TECH",
    # Automotive
    "AU":"AUTOMOTIVE","SS":"AUTOMOTIVE","IM":"AUTOMOTIVE","LI":"AUTOMOTIVE",
    # Finance
    "MF":"FINANCE","BF":"FINANCE","CF":"FINANCE","WO":"FINANCE",
    "VR":"FINANCE","HD":"FINANCE",
    # Agri
    "AA":"AGRI","LS":"AGRI","SG":"AGRI","PA":"AGRI","JA":"AGRI",
    # Retail
    "ER":"RETAIL","HE":"RETAIL","RA":"RETAIL","TE":"RETAIL","CS":"RETAIL",
}


# ─────────────────────────────────────────────────────────────────────────────
# Main WhaleScanner Class
# ─────────────────────────────────────────────────────────────────────────────

class WhaleScanner:
    """
    Follow Whale scanner — Hengky Adinata Method.
    IDX only. Long only. Hitung barang. Ikut smart whale.
    """

    def __init__(self,
                 vol_multiplier: float = None,
                 min_value_bn:   float = None,
                 ma_period:      int   = 20,
                 lookback:       str   = "200d"):  # FIX 8.7.7: 90d → 200d agar EMA89 konvergen
        # Apply director auto-patch (only if config has been customized)
        # If vol_multiplier/min_value_bn not explicitly passed,
        # let adapt_to_market() set optimal values for current regime
        # Config patches only apply if explicitly set by director
        try:
            from config.strategy_config import StrategyConfig
            _cfg = StrategyConfig.load()
            # Only override if director has explicitly patched (not default values)
            if vol_multiplier is None and _cfg.whale_vol_multiplier != 2.0:
                vol_multiplier = _cfg.whale_vol_multiplier
            if min_value_bn is None and _cfg.whale_min_value_bn != 0.5:
                min_value_bn = _cfg.whale_min_value_bn
        except Exception:
            pass

        self.ma_period         = ma_period
        self.lookback          = lookback
        self.feed              = DataFeed(timeframe="1d")
        self._manual_vol       = vol_multiplier
        self._manual_val       = min_value_bn
        self.vol_multiplier    = vol_multiplier or 2.5
        self.min_value_bn      = min_value_bn   or 0.5
        self._data_cache       = {}
        self.cycle             = "UNKNOWN"
        self.cycle_settings    = CYCLE_SETTINGS["UNKNOWN"]
        self.market_breadth    = {}
        self.regime            = {}

    def adapt_to_market(self) -> dict:
        try:
            self.regime  = get_ihsg_regime()
            self.cycle   = self.regime.get("cycle", "UNKNOWN")
            s            = CYCLE_SETTINGS.get(self.cycle, CYCLE_SETTINGS["UNKNOWN"])
            self.cycle_settings   = s
            self.market_breadth   = check_market_breadth(self.regime)

            if not self._manual_vol: self.vol_multiplier = s["vol_mult"]
            if not self._manual_val: self.min_value_bn   = s["min_value_bn"]

            logger.info(f"[Whale] {self.cycle} | vol≥{self.vol_multiplier}× | "
                        f"min Rp{self.min_value_bn}Bn | {self.market_breadth['status']}")
            return {
                "cycle":          self.cycle,
                "vol_multiplier": self.vol_multiplier,
                "min_value_bn":   self.min_value_bn,
                "focus":          s["focus"],
                "description":    s["description"],
                "sizing_advice":  s["sizing_advice"],
                "action":         s["action"],
                "min_conviction": s["min_conviction"],
                "trade_signal":   s["trade_signal"],
                "tradeable":      self.market_breadth["tradeable"],
                "market_status":  self.market_breadth["status"],
                "market_advice":  self.market_breadth["advice"],
                "market_color":   self.market_breadth["color"],
                "ihsg":           self.regime.get("ihsg", 0),
                "mom_4w":         self.regime.get("mom_4w", 0),
                "mom_13w":        self.regime.get("mom_13w", 0),
                "breadth":        self.regime.get("breadth", 0),
            }
        except Exception as e:
            logger.warning(f"[Whale] adapt failed: {e}")
            return {"cycle":"UNKNOWN","tradeable":True,"vol_multiplier":self.vol_multiplier,
                    "min_value_bn":self.min_value_bn,"trade_signal":True,"min_conviction":5,
                    "market_status":"UNKNOWN","market_advice":"—","sizing_advice":"Normal",
                    "focus":"BOTH","action":"TRADE_SELECTIVE","description":"—"}

    def _analyze_ticker(self, ticker: str) -> Optional[dict]:
        try:
            # FIX 8.9.4: coba semua variasi key dengan is None check eksplisit
            # JANGAN pakai `or` antar DataFrame — pandas raise ValueError ambiguous truth
            _base = ticker.replace(".JK", "")
            df = self._data_cache.get(_base)
            if df is None:
                df = self._data_cache.get(_base + ".JK")
            if df is None:
                df = self._data_cache.get(ticker)
            if df is None:
                # Hanya fallback fetch jika benar-benar tidak ada di cache
                df = self.feed.fetch(ticker, period=self.lookback, interval="1d")
            if df is None or len(df) < self.ma_period + 20:
                return None

            # ── Validate data quality before any calculation ───────────────
            import pandas as _pd
            if isinstance(df.columns, _pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            required_cols = ["Close", "Volume", "High", "Low"]
            if not all(c in df.columns for c in required_cols):
                return None
            df = df[df["Close"] > 0].dropna(subset=["Close", "Volume"])
            if len(df) < self.ma_period + 10:
                return None

            vol   = df["Volume"]
            close = df["Close"]
            high  = df["High"]
            low   = df["Low"]
            # Open tersedia di yfinance — dipakai untuk candle body direction di hitung_barang
            open_ = df["Open"] if "Open" in df.columns else close.shift(1).fillna(close)

            # Volume baseline
            vol_ma = float(vol.rolling(self.ma_period).mean().iloc[-1])
            if vol_ma < 500:
                return None

            last_vol  = float(vol.iloc[-1])
            vol_ratio = (last_vol / vol_ma) if vol_ma > 0 else 0.0
            if vol_ratio < self.vol_multiplier:
                return None

            # ── V3: Free Float Adjusted Volume ────────────────────────────────
            # Stocks with tiny free float look like vol spikes more easily
            # Proxy: if market cap (shares × price) < Rp500Bn, penalize vol signal
            # Real free float data not available from yfinance — use vol_ma as proxy
            # Low vol_ma = small/illiquid = treat vol spike with more skepticism
            ff_adj_ratio = vol_ratio
            if vol_ma < 5_000_000:          # thin volume stock
                ff_adj_ratio = vol_ratio * 0.7   # penalize 30%
            elif vol_ma < 1_000_000:        # very thin
                ff_adj_ratio = vol_ratio * 0.5   # penalize 50%

            last_close = float(close.iloc[-1])
            prev_close = float(close.iloc[-2])
            chg_pct    = ((last_close - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
            value_bn   = last_vol * last_close / 1e9

            if value_bn < self.min_value_bn:
                return None

            # Filter ex-dividend noise — tapi jangan buang panic sell + whale defense
            # BUG 6 fix: cek defense dulu sebelum skip
            if chg_pct < -3.5 and vol_ratio > 3.0:
                _quick_def = test_whale_defense(close, vol, low, high)
                if not _quick_def.get("defending"):
                    return None  # genuine dump tanpa defender (kemungkinan ex-div / bad news)
                # kalau ada yang defend meski harga turun → biarkan lewat untuk dianalisis

            # ── V3: Fundamental deterioration proxy ────────────────────────────
            # We don't have EPS data from yfinance free tier.
            # Proxy: if stock down >40% from 52W high AND no whale defense
            # AND vol_ma declining 3M vs 6M → likely fundamental issue, skip.
            try:
                if len(close) >= 60:
                    high_52w  = float(close.rolling(252).max().iloc[-1]) if len(close)>=252 else float(close.max())
                    pct_down  = ((float(close.iloc[-1]) / high_52w - 1) * 100) if high_52w > 0 else 0.0
                    vol_3m    = float(vol.tail(60).mean())
                    vol_6m    = float(vol.tail(120).mean()) if len(vol)>=120 else vol_3m
                    vol_decay = vol_3m / vol_6m if vol_6m > 0 else 1.0
                    # Exclude: down >50% + volume declining (retail leaving, no whale)
                    if pct_down < -50 and vol_decay < 0.7:
                        return None
            except Exception:
                pass

            # ── Hengky's analysis pipeline ────────────────────────────────────

            # 1. Volume Profile dulu — VAL dipakai sebagai floor anchor (W-7 fix)
            vp_data     = compute_volume_profile(close, vol, high, low)

            # 2. Floor price — inject vp_val agar floor lebih akurat dari VP VAL
            floor_data  = estimate_floor_price(close, vol, low, vp_val=vp_data.get("val", 0.0))

            # 3. Pengeringan barang
            peng_data   = detect_pengeringan(close, vol, high, low)

            # 4. Whale defense test
            def_data    = test_whale_defense(close, vol, low, high, floor_price=floor_data.get("floor_price", 0.0))

            # 5. V4: Hitung Barang (Hengky supply concentration math)
            hb_data     = hitung_barang(close, vol, high, low, open_)

            # 6. V4: Order Block (institutional footprint / compression zone)
            ob_data     = detect_order_block(close, high, low, vol)

            # 7. V5: Gradual accumulation — weekly step-up pattern (4 minggu)
            ga_data     = detect_gradual_accumulation(close, vol, high, low, min_weeks=4)

            # 8. V6: Slow exit detection
            se_data     = detect_slow_exit(close, vol, high, low)

            # 8b. Trigger candle — transisi akumulasi → markup
            # Deteksi momen whale selesai kumpul dan mulai push
            tc_data = detect_trigger_candle(
                close = close,
                vol   = vol,
                high  = high,
                low   = low,
                open_ = open_,
                vol_ma = vol_ma,
                pengeringan_detected = peng_data.get("detected", False),
            )

            # Fix A: trigger_confirmed — sinyal lebih kuat dari trigger_candle biasa
            # trigger_candle hanya cek 1 candle terakhir — bisa kebetulan
            # trigger_confirmed = trigger hari ini + ada konteks kuat sebelumnya:
            # kemarin vol step-up ATAU pengeringan kuat (strength>=5) ATAU gradual>=2w
            # Artinya: ada "jalan menuju" trigger, bukan muncul tiba-tiba
            _yest_vol_stepup = (len(vol) >= 3 and float(vol.iloc[-2]) > float(vol.iloc[-3]))
            _peng_kuat       = peng_data.get("detected") and peng_data.get("strength", 0) >= 5
            _gradual_cukup   = ga_data.get("detected") or ga_data.get("strength", 0) >= 1
            tc_confirmed = (
                tc_data.get("detected") and
                (_yest_vol_stepup or _peng_kuat or _gradual_cukup)
            )

            # 9. V5: Relative Strength vs IHSG
            # RS > 0 = saham lebih kuat dari market = ada yang defend/beli diam-diam
            rs_5d = rs_20d = 0.0
            rs_ok  = False
            try:
                ihsg_close = getattr(self, "_ihsg_close", None)
                if ihsg_close is not None and len(ihsg_close) >= 20:
                    # FIX #4: align dari ujung (tail) setelah intersection
                    # Sebelumnya: reindex(common_idx) lalu iloc[-5] bisa ambil bar
                    # yang sangat jauh dari hari ini jika common_idx pendek di awal
                    # Fix: ambil 25 hari terakhir dari common_idx saja (cukup untuk rs_20d)
                    common_idx = close.index.intersection(ihsg_close.index)
                    common_idx = common_idx[-25:] if len(common_idx) >= 25 else common_idx
                    if len(common_idx) >= 10:
                        stk  = close.reindex(common_idx)
                        mkt  = ihsg_close.reindex(common_idx)
                        rs_5d  = float((stk.iloc[-1]/stk.iloc[-min(5,len(stk))] - 1) * 100) - \
                                 float((mkt.iloc[-1]/mkt.iloc[-min(5,len(mkt))] - 1) * 100)
                        rs_20d = float((stk.iloc[-1]/stk.iloc[-min(20,len(stk))] - 1) * 100) - \
                                 float((mkt.iloc[-1]/mkt.iloc[-min(20,len(mkt))] - 1) * 100)
                        # RS positif di 5d DAN 20d = outperform konsisten = sinyal defend
                        rs_ok = rs_5d > 0 and rs_20d > 0
            except Exception:
                pass

            # 9. V5: Pump fingerprint — reverse-engineer pre-pump conditions dari historis
            fp_data     = detect_pump_fingerprint(
                ticker       = ticker,
                close_daily  = close,
                vol_daily    = vol,
                high_daily   = high,
                low_daily    = low,
                floor_price  = floor_data.get("floor_price", 0.0),
            )

            # 4. Multi-day accumulation
            accum_days  = int((vol.tail(5) > vol_ma * 1.5).sum())
            pattern     = "SUSTAINED" if accum_days >= 3 else "SINGLE_DAY"

            # 5. Momentum
            mom_5d  = (last_close/float(close.iloc[-5])  - 1)*100 if len(close)>=5  else 0
            mom_10d = (last_close/float(close.iloc[-10]) - 1)*100 if len(close)>=10 else 0
            momentum = ("ACCELERATING" if mom_5d>0 and mom_10d>0 else
                        "REVERSING"    if mom_5d>0 and mom_10d<0 else
                        "DECLINING"    if mom_5d<0 else "FLAT")

            # 6. EMA alignment
            ema13  = float(close.ewm(span=13, adjust=False).mean().iloc[-1])
            ema89  = float(close.ewm(span=89, adjust=False).mean().iloc[-1])
            ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1]) if len(close)>=200 else ema89
            ema_tr = ("BULLISH" if last_close>ema13 and last_close>ema89 else
                      "MIXED"   if last_close>ema13 else "BEARISH")

            # 7. Range metrics
            pct_52w_high = (last_close/floor_data["high_52w"] - 1)*100 if floor_data["high_52w"]>0 else 0

            # ── Build result dict ─────────────────────────────────────────────
            result = {
                "ticker":           ticker,
                "close":            round(last_close, 0),
                "chg_pct":          round(chg_pct, 2),
                "vol_ratio":        round(vol_ratio, 1),
                "value_bn":         round(value_bn, 2),
                "vol_ma20":         round(vol_ma, 0),
                "date":             str(df.index[-1])[:10],
                # Floor price
                "floor_price":      floor_data["floor_price"],
                "vwap_60d":         floor_data["vwap_60d"],
                "low_52w":          floor_data["low_52w"],
                "high_52w":         floor_data["high_52w"],
                "pct_above_floor":  floor_data["pct_above_floor"],
                "entry_zone":       floor_data["entry_zone"],
                "entry_zone_label": floor_data["entry_zone_label"],
                "range_20d_pct":    floor_data["range_20d_pct"],
                "range_tight":      floor_data["range_tight"],
                # Pengeringan
                "pengeringan_detected": peng_data["detected"],
                "pengeringan_strength": peng_data["strength"],
                "pengeringan_desc":     peng_data["description"],
                "accum_days":           accum_days,
                "pattern":              pattern,
                # Whale defense
                "whale_defending":  def_data["defending"],
                "defense_days":     def_data["defense_days"],
                "defense_score":    def_data["defense_score"],
                "defense_desc":     def_data["description"],
                # Momentum + EMA
                "momentum":         momentum,
                "mom_5d":           round(mom_5d, 1),
                "mom_10d":          round(mom_10d, 1),
                "ema_trend":        ema_tr,
                "ema13":            round(ema13, 0),
                "ema89":            round(ema89, 0),
                "ema200":           round(ema200, 0),
                "pct_from_52w_high": round(pct_52w_high, 1),
                # V4: Hitung Barang
                "absorbed_pct":        hb_data["absorbed_pct"],
                "supply_tightness":    hb_data["supply_tightness"],
                "control_score":       hb_data["control_score"],
                "is_centralized":      hb_data["is_centralized"],
                "hitung_barang_desc":  hb_data["hitung_barang_desc"],
                "accum_days_20d":      hb_data["accum_days_20d"],
                "distribution_days":   hb_data.get("distribution_days", 0),
                "range_ratio":         hb_data["range_ratio"],
                # V4: Order Block
                "ob_detected":         ob_data["ob_detected"],
                "ob_type":             ob_data.get("ob_type"),
                "ob_high":             ob_data.get("ob_high", 0),
                "ob_low":              ob_data.get("ob_low", 0),
                "ob_strength":         ob_data.get("ob_strength", 0),
                "in_ob_zone":          ob_data.get("in_ob_zone", False),
                "near_ob_zone":        ob_data.get("near_ob_zone", False),
                "ob_desc":             ob_data.get("ob_desc", ""),
                # V6.4: Volume Profile
                "vp_poc":          vp_data["poc"],
                "vp_vah":          vp_data["vah"],
                "vp_val":          vp_data["val"],
                "vp_zone":         vp_data["current_zone"],
                "vp_pct_from_poc": vp_data["pct_from_poc"],
                "vp_in_value":     vp_data["in_value_area"],
                "vp_near_val":     vp_data["near_val"],
                "vp_hvn":          vp_data["hvn_levels"],
                "vp_lvn":          vp_data["lvn_levels"],
                "vp_desc":         vp_data["vp_desc"],
                # V6.4: Enhanced pengeringan fields
                "peng_absorption":      peng_data.get("absorption_score", 0),
                "peng_close_pos":       peng_data.get("close_position_score", 0.5),
                "peng_vol_accel":       peng_data.get("vol_acceleration", 1.0),
                # V5: Gradual accumulation
                "gradual_accum":        ga_data["detected"],
                "gradual_weeks":        ga_data["weeks_confirmed"],
                "gradual_vol_gain":     ga_data["vol_gain_pct"],
                "gradual_range_pct":    ga_data["avg_weekly_range_pct"],
                "gradual_strength":     ga_data["strength"],
                "gradual_desc":         ga_data["description"],
                # V5: Pump fingerprint
                "pump_fp_detected":     fp_data["detected"],
                "pump_fp_count":        fp_data["pump_count"],
                "pump_fp_confidence":   fp_data["confidence"],
                "pump_fp_type":         fp_data["fingerprint"],
                "pump_fp_similarity":   fp_data["similarity_score"],
                "pump_fp_matches":      fp_data["currently_matches"],
                "pump_fp_avg_pct":      fp_data["avg_pump_pct"],
                "pump_fp_desc":         fp_data["description"],
                "pump_fp_cur_supply":   fp_data["cur_supply"],
                "pump_fp_cur_peng":     fp_data["cur_pengeringan"],
                "pump_fp_cur_stepup":   fp_data["cur_vol_stepup"],
                # V6: Relative Strength vs IHSG
                "rs_5d":               round(rs_5d, 1),
                "rs_20d":              round(rs_20d, 1),
                "rs_ok":               rs_ok,
                # V6: Slow exit
                "slow_exit":           se_data["detected"],
                "slow_exit_strength":  se_data["strength"],
                "slow_exit_desc":      se_data["description"],
                "price_vol_div":       se_data["price_vol_divergence"],
                "upper_wick_dom":      se_data["upper_wick_dominant"],
                # Trigger candle — transisi akumulasi → markup
                "trigger_candle":          tc_data["detected"],
                "trigger_confirmed":       tc_confirmed,  # Fix A: trigger + konteks kuat
                "trigger_strength":        tc_data["strength"],
                "trigger_close_pos":       tc_data["close_position"],
                "trigger_vol_stepup":      tc_data["vol_stepup"],
                "trigger_vol_spike":       tc_data["vol_spike"],
                "trigger_range_expansion": tc_data["range_expansion"],
                "trigger_desc":            tc_data["description"],
            }

            # Phase 1+2: Ownership data (free float + static broker profile)
            # NOTE: Stockbit live broker data (Phase 3) diambil SETELAH scan selesai
            # via _ownership_agent.enrich_top_results() — tidak blocking per-ticker
            if _HAS_OWNERSHIP:
                try:
                    own = _ownership_agent.get_full_ownership(ticker)
                    result["free_float"]     = own.get("free_float", 100)
                    result["pct_insider"]    = own.get("pct_insider", 0)
                    result["supply_control"] = own.get("supply_control","")
                    result["hengky_score"]   = own.get("hengky_score", 0)
                    result["owner_broker"]   = own.get("owner_broker","")
                    result["owner_name"]     = own.get("owner_name","")
                    result["broker_name"]    = own.get("broker_name","")
                    result["broker_type"]    = own.get("broker_type","")
                    result["broker_signal"]  = own.get("broker_signal","")
                    result["broker_live"]    = False   # diisi enrich_top_results
                    result["top_buyers"]     = []      # diisi enrich_top_results
                    result["top_sellers"]    = []      # diisi enrich_top_results
                    result["smart_buy_pct"]  = 0
                    result["_ownership"]     = own
                    # NOTE: ff free_float boost conviction dipindah ke setelah compute_conviction
                except Exception as _e:
                    logger.debug(f"[Whale] {ticker} ownership failed: {_e}")

            # ── W-8: Sector tag — full-ticker lookup + 2-char prefix fallback ──
            _base_t = ticker.replace(".JK","").upper()
            sector  = _IDX_SECTOR_MAP.get(_base_t) or _IDX_PREFIX_MAP.get(_base_t[:2], "OTHER")

            # Signal — FIX: pass structural momentum agar ACCUMULATION tidak terpicu saat tren turun
            signal, emoji, color = classify_signal(vol_ratio, chg_pct, peng_data, def_data,
                                                   mom_5d=mom_5d, mom_10d=mom_10d)

            # Recovery overlay: beaten down + ada bukti whale buying
            # FIX: vol_ratio >= 2.0 saja TIDAK cukup — retail panik juga bisa vol 2x
            # Wajib ada pengeringan ATAU defense sebagai konfirmasi whale behavior nyata
            _has_whale_evidence = (
                peng_data.get("detected") or
                def_data.get("defending")
            )
            if signal not in ("DISTRIBUTION","BLOCK_SELL") and pct_52w_high < -20 and _has_whale_evidence:
                signal = "RECOVERY_EARLY"
                emoji  = "🌅"
                color  = "#fbbf24"

            result.update({
                "signal":         signal,
                "emoji":          emoji,
                "sig_color":      color,
                "is_long_signal": signal in ("ACCUMULATION","BLOCK_BUY","VOL_SPIKE_UP","RECOVERY_EARLY"),
                "sector":         sector,
            })

            # Catalyst flags — WAJIB di-set sebelum compute_conviction
            # karena compute_conviction membaca is_msci_candidate + is_lq45_candidate
            _base = ticker.upper().replace(".JK", "")
            _msci = getattr(self, "_msci_set", set())
            _lq45 = getattr(self, "_lq45_set", set())
            result["is_msci_candidate"] = _base in _msci
            result["is_lq45_candidate"] = _base in _lq45
            result["catalyst_tag"] = ("MSCI" if result.get("is_msci_candidate") else
                                      "LQ45" if result.get("is_lq45_candidate") else "")

            # Whale quality
            result["whale_quality"] = classify_whale_quality(result)

            # Conviction — semua boost dan cap sudah ada di dalam compute_conviction()
            # Post-hoc boosts (ff<=15, vp_near_val, poc+peng, msci/lq45) dipindah ke sana
            # agar cap slow_exit dan supply freedom mencakup semua boost tanpa bocor
            result["ff_adj_vol_ratio"] = round(ff_adj_ratio, 2)
            result["conviction"]       = compute_conviction(result, ff_adj_ratio)

            # ── Reconciliation: quality ↔ conviction (Fix 1) ──────────────────
            # Dijalankan SEKALI setelah conviction final — quality tidak boleh
            # lebih optimis dari yang didukung conviction.
            # Sebelumnya: quality dihitung sebelum conviction, tidak bisa saling validasi.
            _wq  = result.get("whale_quality", "")
            _cnv = result.get("conviction", 0)
            _sig = result.get("signal", "")

            # Fix 2: DISTRIBUTION signal → quality max UNCERTAIN
            # DISTRIBUTION adalah sinyal harian langsung (vol+price). Smart whale
            # tidak mungkin mendistribusikan saham yang kita label "SMART".
            # Slow exit sudah di-cap di conviction, tapi DISTRIBUTION signal belum.
            if _sig == "DISTRIBUTION" and _wq in ("SMART", "LIKELY_SMART"):
                result["whale_quality"] = "UNCERTAIN"
                _wq = "UNCERTAIN"

            # Fix 1: quality harus konsisten dengan conviction
            # SMART dengan conviction <= 4 = kontradiksi (SMART butuh sinyal kuat)
            # LIKELY_SMART dengan conviction <= 2 = terlalu rendah untuk label itu
            if _wq == "SMART" and _cnv <= 4:
                result["whale_quality"] = "LIKELY_SMART"
            elif _wq == "LIKELY_SMART" and _cnv <= 2:
                result["whale_quality"] = "UNCERTAIN"

            # ── Momentum Readiness Score (0–5) ────────────────────────────────
            # Menjawab: "Apakah whale sudah selesai akumulasi dan siap push SEKARANG?"
            # Berbeda dari conviction (kualitas whale) — ini adalah TIMING score.
            # Semua komponen sudah dihitung di pipeline atas, tinggal dikomposit.
            _mrs = 0
            _mrs_parts = []

            # +0-2: Gradual accumulation — Fix 3: pakai gradual_strength (konsisten dengan
            # compute_conviction dan classify_whale_quality yang sudah pakai strength)
            # gradual_weeks masih ditampilkan di label tapi scoring dari strength
            _ga_str   = ga_data.get("strength", 0)
            _ga_weeks = ga_data.get("weeks_confirmed", 0)
            if ga_data.get("detected") and _ga_str >= 2:
                _mrs += 2
                _mrs_parts.append(f"akumulasi kuat {_ga_weeks}w (strength {_ga_str}/3)")
            elif ga_data.get("detected") or _ga_str >= 1:
                _mrs += 1
                _mrs_parts.append(f"akumulasi {_ga_weeks}w (strength {_ga_str}/3)")

            # +1: Pengeringan strength >= 5 = barang sudah sangat kering
            _peng_str = peng_data.get("strength", 0)
            if peng_data.get("detected") and _peng_str >= 5:
                _mrs += 1
                _mrs_parts.append(f"pengeringan kuat ({_peng_str}/7)")
            elif peng_data.get("detected") and _peng_str >= 3:
                _mrs += 0  # pengeringan ada tapi belum cukup kuat untuk timing

            # +1: Trigger candle detected = whale mulai push hari ini
            if tc_data.get("detected"):
                _mrs += 1
                # Fix A: trigger_confirmed = konteks lebih kuat → label berbeda
                if tc_confirmed:
                    _mrs_parts.append("🕯 trigger CONFIRMED (ada konteks sebelumnya)")
                else:
                    _mrs_parts.append("trigger candle hari ini")

                # Fix C: combinatorial bonus di MRS — sekuens pengeringan → trigger = paling kuat
                # Pengeringan (barang kering) + trigger (push dimulai) = konfirmasi urutan sempurna
                # Keduanya terkonfirmasi = bukan hanya noise volume biasa
                if peng_data.get("detected") and not peng_data.get("is_false", False):
                    _mrs += 1
                    _mrs_parts.append("✓ sekuens peng→trigger terkonfirmasi")

            # +1: Range compression — price range menyempit = tekanan akan release
            _range_r = hb_data.get("range_ratio", 1.0)
            if _range_r < 0.4:
                _mrs += 1
                _mrs_parts.append(f"compression {_range_r:.0%}")

            # Bonus setengah point (dibulatkan): vol step-up tanpa trigger candle penuh
            # Artinya ada awal tanda-tanda volume mulai naik kembali
            if tc_data.get("vol_stepup") and not tc_data.get("detected"):
                # Tidak cukup untuk trigger candle, tapi worth dicatat
                _mrs_parts.append("vol mulai step-up")

            # Hard block: slow exit override — tidak ada readiness kalau whale sedang exit
            if se_data.get("detected") and se_data.get("strength", 0) >= 2:
                _mrs = 0
                _mrs_parts = ["⛔ SLOW EXIT OVERRIDE — whale sedang exit, bukan push"]

            _mrs = min(_mrs, 5)

            # Label readiness
            if _mrs >= 4:    _mrs_label = "SIAP ENTRY"
            elif _mrs >= 3:  _mrs_label = "MENDEKATI"
            elif _mrs >= 2:  _mrs_label = "DALAM PROSES"
            elif _mrs >= 1:  _mrs_label = "AKUMULASI AWAL"
            else:            _mrs_label = "BELUM SIAP"

            result["momentum_readiness"]       = _mrs
            result["momentum_readiness_label"] = _mrs_label
            result["momentum_readiness_parts"] = _mrs_parts

            return result

        except Exception as e:
            import traceback
            tb_lines = traceback.format_exc().splitlines()
            # Find the line with "whale_scanner.py"
            file_line = next((l for l in reversed(tb_lines) if 'whale_scanner' in l), tb_lines[-2] if len(tb_lines)>=2 else "")
            logger.warning(f"[Whale] {ticker}: {type(e).__name__}: {e} | {file_line.strip()}")
            return None

    def scan(self,
             tickers:     Optional[List[str]] = None,
             top_n:       int                 = 50,
             max_workers: int                 = 8) -> Tuple[List[dict], dict]:  # FIX #5: 20→8, CPU-bound + GIL

        tickers = tickers or get_catalyst_universe()  # V7: includes daily movers
        # Build fast MSCI/LQ45 lookup sets for flagging — stored as instance attrs
        self._msci_set  = set(t.upper().replace(".JK","") for t in MSCI_CANDIDATES)
        self._lq45_set  = set(t.upper().replace(".JK","") for t in IDX30_LQ45_CANDIDATES)
        start   = datetime.now()
        ctx     = self.adapt_to_market()
        min_conv = self.cycle_settings["min_conviction"]

        print(f"[Whale] {self.cycle} | vol≥{self.vol_multiplier}× | Rp{self.min_value_bn}Bn | "
              f"min conv {min_conv} | {len(tickers)} tickers | {self.market_breadth.get('status','?')}")

        if not ctx.get("tradeable"):
            print(f"[Whale] ⚠️ {ctx.get('market_status')} → scanning for AWARENESS + recovery WL only")

        # Batch pre-fetch all data at once
        # FIX #3: IHSG di-cache di instance var dengan TTL 30 menit
        # Sebelumnya di-fetch fresh setiap scan() dipanggil — 1 network request terbuang
        # FIX #4: IHSG di-fetch dengan period=self.lookback (sama dengan ticker data)
        # Sebelumnya period=self.lookback tapi cache ticker bisa lebih lama dari IHSG fetch
        # → index intersection pendek → rs_5d/rs_20d dihitung dari periode tidak sama
        # Solusi: simpan timestamp fetch terakhir, reuse jika < 30 menit
        import time as _time_ihsg
        _ihsg_cache_age = getattr(self, "_ihsg_fetch_ts", 0)
        _ihsg_needs_refresh = (_time_ihsg.time() - _ihsg_cache_age) > 1800  # 30 menit TTL

        if _ihsg_needs_refresh or getattr(self, "_ihsg_close", None) is None:
            try:
                import yfinance as _yf_ihsg
                _ihsg_df = _yf_ihsg.download("^JKSE", period=self.lookback,
                                              interval="1d", progress=False, auto_adjust=True)
                if _ihsg_df is not None and len(_ihsg_df) >= 20:
                    if hasattr(_ihsg_df.columns, "get_level_values"):
                        _ihsg_df.columns = _ihsg_df.columns.get_level_values(0)
                    self._ihsg_close    = _ihsg_df["Close"]
                    self._ihsg_fetch_ts = _time_ihsg.time()
                    logger.info(f"[Whale] IHSG fetched: {len(_ihsg_df)} bars (period={self.lookback})")
                else:
                    self._ihsg_close = None
            except Exception as _e:
                logger.debug(f"[Whale] IHSG fetch failed: {_e}")
                self._ihsg_close = None
        else:
            logger.info(f"[Whale] IHSG cache hit ({int((_time_ihsg.time()-_ihsg_cache_age)/60)}min old)")

        print(f"[Whale] Batch downloading {len(tickers)} tickers...")
        import time as _time
        _t0 = _time.time()
        self._data_cache = self.feed.fetch_batch(
            tickers, max_workers=4, period=self.lookback, interval="1d"
        )

        # Retry ticker yang gagal (kemungkinan 401 crumb expired)
        _missing = [t for t in tickers if t not in self._data_cache]
        if _missing:
            print(f"[Whale] Retry {len(_missing)} ticker yang gagal (crumb refresh)...")
            _time.sleep(3)  # jeda untuk Yahoo reset session
            import yfinance as _yf
            for _t in _missing:
                try:
                    _df = _yf.download(
                        _t + ".JK", period=self.lookback, interval="1d",
                        progress=False, auto_adjust=True
                    )
                    if _df is not None and len(_df) >= 20:
                        if hasattr(_df.columns, "get_level_values"):
                            _df.columns = _df.columns.get_level_values(0)
                        self._data_cache[_t] = _df
                except Exception:
                    pass
                _time.sleep(0.5)
            print(f"[Whale] Retry selesai: {len(self._data_cache)} ticker tersedia")

        print(f"[Whale] Data ready: {len(self._data_cache)} tickers in {_time.time()-_t0:.0f}s")

        results: List[dict] = []
        with ThreadPoolExecutor(max_workers=max_workers) as exe:
            futures = {exe.submit(self._analyze_ticker, t): t for t in tickers}
            done = 0
            for future in as_completed(futures):
                done += 1
                r = future.result()
                if r is not None:
                    results.append(r)
                if done % 50 == 0:
                    print(f"[Whale] {done}/{len(tickers)} | {len(results)} hits")

        # Sort: long signals first, then by conviction
        sig_order = {
            "ACCUMULATION":0,"BLOCK_BUY":1,"RECOVERY_EARLY":2,
            "VOL_SPIKE_UP":3,"VOL_NEUTRAL":4,
            "DISTRIBUTION":5,"BLOCK_SELL":6,
        }
        results.sort(key=lambda x: (
            sig_order.get(x.get("signal",""), 9),
            -x.get("conviction", 0),
            x.get("pct_above_floor", 999),  # closer to floor = better
        ))
        # ── V3: Sector Correlation Cap ───────────────────────────────────────
        # Max 30% of results from any single sector to avoid sector concentration risk
        MAX_SECTOR_PCT = 0.35
        sector_count: dict = {}
        capped_results = []
        max_per_sector = max(3, int(len(results) * MAX_SECTOR_PCT))
        for r in results:
            sec = r.get("sector", "OTHER")
            cnt = sector_count.get(sec, 0)
            if cnt < max_per_sector:
                capped_results.append(r)
                sector_count[sec] = cnt + 1
        # If cap removed too many, pad back from results
        if len(capped_results) < min(top_n, len(results)):
            seen = set(id(r) for r in capped_results)
            for r in results:
                if id(r) not in seen:
                    capped_results.append(r)
                if len(capped_results) >= top_n:
                    break
        results = capped_results[:top_n]

        # Summary stats
        elapsed    = (datetime.now() - start).seconds
        accum      = [r for r in results if r["signal"]=="ACCUMULATION"]
        block_buy  = [r for r in results if r["signal"]=="BLOCK_BUY"]
        recovery   = [r for r in results if r["signal"]=="RECOVERY_EARLY"]
        distrib    = [r for r in results if not r.get("is_long_signal")]
        smart      = [r for r in results if r.get("whale_quality") in ("SMART","LIKELY_SMART") and r.get("is_long_signal")]
        pengeringan= [r for r in results if r.get("pengeringan_detected") and r.get("is_long_signal")]
        defending  = [r for r in results if r.get("whale_defending") and r.get("is_long_signal")]
        at_floor   = [r for r in results if r.get("entry_zone")=="AT_FLOOR" and r.get("is_long_signal")]

        buy_val    = sum(r["value_bn"] for r in results if r.get("is_long_signal"))
        sell_val   = sum(r["value_bn"] for r in results if not r.get("is_long_signal"))
        total_val  = buy_val + sell_val
        bp         = buy_val/total_val if total_val>0 else 0.5
        bias       = ("STRONG BUY" if bp>=0.65 else "MILD BUY" if bp>=0.55 else
                      "STRONG SELL" if bp<=0.25 else "MILD SELL" if bp<=0.35 else "NEUTRAL")

        sector_breakdown = {}
        for r in results:
            s = r.get("sector","OTHER")
            sector_breakdown[s] = sector_breakdown.get(s, 0) + 1

        ctx.update({
            "total":           len(results),
            "sector_breakdown": sector_breakdown,
            "accumulation":    len(accum),
            "block_buy":       len(block_buy),
            "recovery":        len(recovery),
            "distribution":    len(distrib),
            "smart_whales":    len(smart),
            "pengeringan":     len(pengeringan),
            "defending":       len(defending),
            "at_floor":        len(at_floor),
            "buy_value_bn":    round(buy_val, 1),
            "sell_value_bn":   round(sell_val, 1),
            "market_bias":     bias,
            "top_long":        [r["ticker"].replace(".JK","") for r in smart[:5]],
            "top_recovery":    [r["ticker"].replace(".JK","") for r in recovery[:5]],
            "top_floor":       [r["ticker"].replace(".JK","") for r in at_floor[:5]],
            "scan_time_s":     elapsed,
        })

        print(f"[Whale] ✅ {elapsed}s | {len(results)} total | "
              f"🟢{len(accum)} akumulasi | 🌅{len(recovery)} recovery | "
              f"🔴{len(distrib)} distribusi | 🧠{len(smart)} smart | "
              f"💧{len(pengeringan)} pengeringan | 🛡{len(defending)} defend | "
              f"🎯{len(at_floor)} at-floor")

        # Enrichment pass — Stockbit broker data untuk top 15 by conviction
        # Sequential + throttled (1 req/s), skip otomatis jika tidak ada token
        if _HAS_OWNERSHIP:
            try:
                results = _ownership_agent.enrich_top_results(results)  # V5: top_n=50, min_conviction=4
            except Exception as _ee:
                logger.debug(f"[Whale] Enrichment skipped: {_ee}")

        return results, ctx

    def scan_watchlist(self, **kw) -> Tuple[List[dict], dict]:
        return self.scan(tickers=IDX_WATCHLIST, **kw)

    # ── Convenience filters ───────────────────────────────────────────────────

    def get_best_long(self, results: List[dict], min_conviction: int = 5) -> List[dict]:
        """Setup terbaik: smart whale + accumulation/pengeringan + EMA bullish."""
        return [r for r in results
                if r.get("is_long_signal")
                and r.get("whale_quality") in ("SMART","LIKELY_SMART")
                and r.get("ema_trend") == "BULLISH"
                and r.get("conviction",0) >= min_conviction]

    def get_pengeringan(self, results: List[dict]) -> List[dict]:
        """Saham yang sedang dalam proses pengeringan barang."""
        return [r for r in results
                if r.get("pengeringan_detected") and r.get("is_long_signal")]

    def get_at_floor(self, results: List[dict]) -> List[dict]:
        """Harga mendekati floor price — risk/reward terbaik."""
        return [r for r in results
                if r.get("entry_zone") in ("AT_FLOOR","NEAR_FLOOR")
                and r.get("is_long_signal")]

    def get_recovery_watchlist(self, results: List[dict]) -> List[dict]:
        """Bear market: beaten down >20% dari 52W high + whale buying."""
        return [r for r in results
                if r.get("is_long_signal") and r.get("pct_from_52w_high",0) < -20]

    def get_distribution_watch(self, results: List[dict]) -> List[dict]:
        """Distribusi — awareness only, bukan short signal."""
        return [r for r in results if not r.get("is_long_signal")]
