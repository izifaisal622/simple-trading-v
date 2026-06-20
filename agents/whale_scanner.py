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
    }


# ─────────────────────────────────────────────────────────────────────────────
# Whale Defense Test
# "Kalau dihantam tapi tidak jatuh → ada yang nampung" (Hengky)
# ─────────────────────────────────────────────────────────────────────────────

def hitung_barang(
    close: pd.Series,
    vol: pd.Series,
    high: pd.Series,
    low: pd.Series,
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

    Returns dict with:
    - absorbed_pct: estimated % of float absorbed by smart money
    - supply_tightness: 0-10 (10 = supply sangat langka)
    - control_score: 0-10 (Hengky's math equivalent)
    - hitung_barang_desc: human-readable summary
    - is_centralized: bool (True = supply dominated by 1 party)
    """
    if len(close) < 20:
        return {"absorbed_pct": 0, "supply_tightness": 0,
                "control_score": 0, "hitung_barang_desc": "",
                "is_centralized": False}

    vol_ma20 = float(vol.rolling(20).mean().iloc[-1])
    vol_ma60 = float(vol.rolling(60).mean().iloc[-1]) if len(vol) >= 60 else vol_ma20

    # Days where volume was high but price barely moved (accumulation signature)
    accum_days = 0
    accum_vol_total = 0.0
    total_vol_20d = float(vol.tail(20).sum())

    for i in range(min(20, len(close) - 1)):
        v     = float(vol.iloc[-(i+1)])
        c     = float(close.iloc[-(i+1)])
        c_prev= float(close.iloc[-(i+2)])
        price_move = (abs(c - c_prev) / c_prev * 100) if c_prev > 0 else 0.0

        # High volume + low price movement = accumulation (pengeringan proxy)
        if v > vol_ma20 * 1.5 and price_move < 1.5:
            accum_days += 1
            accum_vol_total += v

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

    control_score = min(control_score, 10)
    is_centralized = control_score >= 6

    # Build description
    parts = []
    if absorbed_pct > 30:
        parts.append(f"~{absorbed_pct:.0f}% vol diserap institusi")
    if accum_days >= 3:
        parts.append(f"akumulasi {accum_days}h tanpa harga naik")
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


def test_whale_defense(close: pd.Series, vol: pd.Series, low: pd.Series, high: pd.Series) -> dict:
    """
    Simulates the 'bit-over test' Hengky uses:
    Kalau ada hari di mana volume spike tapi harga tidak jatuh jauh → ada whale yang defend.
    """
    vol_ma = float(vol.rolling(20).mean().iloc[-1])
    if vol_ma <= 0:
        return {"defending": False, "defense_score": 0}

    defense_days = 0
    for i in range(min(5, len(close)-2)):
        v      = float(vol.iloc[-(i+1)])
        c      = float(close.iloc[-(i+1)])
        lo     = float(low.iloc[-(i+1)])
        hi     = float(high.iloc[-(i+1)])
        prev_c = float(close.iloc[-(i+2)])

        is_heavy_vol  = v > vol_ma * 2.0
        price_dropped = c < prev_c                    # harga turun
        recovered     = ((c - lo) / (hi - lo) > 0.5) if (hi - lo) > 0 else False   # guard flat candle
        defended      = is_heavy_vol and price_dropped and recovered
        if defended:
            defense_days += 1

    defense_score = min(defense_days * 3, 5)
    return {
        "defending":     defense_days >= 1,
        "defense_days":  defense_days,
        "defense_score": defense_score,
        "description":   f"Whale defend {defense_days}x dalam 5 hari" if defense_days > 0 else "",
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
    mom = result.get("momentum","")
    if mom == "ACCELERATING": score += 1
    if mom == "REVERSING":    score += 1

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

    # Threshold adjusted: max score ~20
    if score >= 13:  return "SMART"
    if score >= 8:   return "LIKELY_SMART"
    if score >= 4:   return "UNCERTAIN"
    return "DUMB"


# ─────────────────────────────────────────────────────────────────────────────
# Conviction Scoring — Hengky's framework
# ─────────────────────────────────────────────────────────────────────────────

def compute_conviction(r: dict, vol_ratio: float) -> int:
    """
    0–10 conviction score V4 — Hengky framework + Order Block.

    Volume ratio     (0–3)
    Pengeringan      (0–2)
    Floor proximity  (0–2)
    Whale defense    (0–1)
    EMA alignment    (0–1)
    Momentum         (0–1)
    --- V4 additions ---
    Hitung Barang    (0–2): supply centralized = easier to push up
    Order Block      (0–2): price at/near institutional OB zone
    """
    score = 0

    # Vol ratio (cap 3)
    score += min(int(vol_ratio / 1.5), 3)

    # Pengeringan
    score += min(r.get("pengeringan_strength", 0), 2)

    # Floor proximity
    zone = r.get("entry_zone", "FAR_FROM_FLOOR")
    if zone == "AT_FLOOR":      score += 2
    elif zone == "NEAR_FLOOR":  score += 1

    # Whale defense
    if r.get("whale_defending"):    score += 1

    # EMA
    if r.get("ema_trend") == "BULLISH": score += 1

    # Momentum
    mom = r.get("momentum", "")
    if mom in ("ACCELERATING", "REVERSING"): score += 1

    # V4: Hitung Barang — supply concentration bonus
    ctrl = r.get("control_score", 0)
    if ctrl >= 7:   score += 2
    elif ctrl >= 4: score += 1

    # V4: Order Block — institutional zone bonus
    if r.get("in_ob_zone"):    score += 2
    elif r.get("near_ob_zone"): score += 1

    # V4: Market Structure boost from scanner (if available)
    ms_boost = r.get("ms_conviction_boost", 0)
    score += ms_boost

    return max(0, min(10, score))


# ─────────────────────────────────────────────────────────────────────────────
# Signal Classification
# ─────────────────────────────────────────────────────────────────────────────

def classify_signal(vol_ratio: float, chg_pct: float,
                    pengeringan: dict, defense: dict) -> Tuple[str, str, str]:
    """
    Signal mengintegrasikan: vol, pergerakan harga, pengeringan, whale defense.
    """
    is_buy     = chg_pct >  0.5
    is_sell    = chg_pct < -0.5
    is_neutral = not is_buy and not is_sell
    is_block   = vol_ratio >= 5.0
    is_heavy   = vol_ratio >= 3.0
    is_moderate= vol_ratio >= 2.0
    pengeringan_ok = pengeringan.get("detected", False)

    # Best case: pengeringan + heavy vol + price up + whale defend
    if pengeringan_ok and is_heavy and (is_buy or is_neutral) and defense.get("defending"):
        return "ACCUMULATION", "🟢", "#00ff88"
    # Pengeringan tanpa defense — masih bagus
    if pengeringan_ok and is_heavy and (is_buy or is_neutral):
        return "ACCUMULATION", "🟢", "#00ff88"
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
            def_data    = test_whale_defense(close, vol, low, high)

            # 5. V4: Hitung Barang (Hengky supply concentration math)
            hb_data     = hitung_barang(close, vol, high, low)

            # 6. V4: Order Block (institutional footprint / compression zone)
            ob_data     = detect_order_block(close, high, low, vol)

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

            # Signal
            signal, emoji, color = classify_signal(vol_ratio, chg_pct, peng_data, def_data)

            # Recovery overlay: beaten down + ada bukti whale buying
            # BUG 5 fix: VOL_NEUTRAL tanpa whale evidence TIDAK di-override ke RECOVERY_EARLY
            _has_whale_evidence = (
                peng_data.get("detected") or
                def_data.get("defending") or
                vol_ratio >= 2.0
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

            # Whale quality
            result["whale_quality"] = classify_whale_quality(result)

            # V3: Conviction uses free-float adjusted ratio
            result["ff_adj_vol_ratio"] = round(ff_adj_ratio, 2)
            result["conviction"]    = compute_conviction(result, ff_adj_ratio)

            # Free float tight → supply terpusat → boost conviction (BUG 2 fix: dipindah ke sini)
            _ff_now = result.get("free_float", 100)
            if _ff_now <= 15 and result["conviction"] < 10:
                result["conviction"] = min(10, result["conviction"] + 1)

            # V6.4: Boost conviction if price is near Volume Profile VAL (near accumulation zone)
            if vp_data.get("near_val") and result["conviction"] < 10:
                result["conviction"] = min(10, result["conviction"] + 1)
            # Near POC with pengeringan = strong setup
            if abs(vp_data.get("pct_from_poc", 99)) < 3 and peng_data.get("detected"):
                result["conviction"] = min(10, result["conviction"] + 1)

            # Catalyst flags — MSCI/LQ45 membership boosts visibility
            _base = ticker.upper().replace(".JK", "")
            _msci = getattr(self, "_msci_set", set())
            _lq45 = getattr(self, "_lq45_set", set())
            result["is_msci_candidate"] = _base in _msci
            result["is_lq45_candidate"] = _base in _lq45
            if result.get("is_msci_candidate") or result.get("is_lq45_candidate"):
                result["catalyst_tag"] = "MSCI" if result.get("is_msci_candidate") else "LQ45"
                # Give a small conviction boost — known index candidate
                result["conviction"] = min(10, result["conviction"] + 1)
            else:
                result["catalyst_tag"] = ""

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
             max_workers: int                 = 20) -> Tuple[List[dict], dict]:

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
        # FIX 8.9.0: max_workers 30→4 untuk hindari HTTP 401 Invalid Crumb
        # (Yahoo expire session saat >10 request paralel simultan)
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
                results = _ownership_agent.enrich_top_results(results, top_n=15)
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
