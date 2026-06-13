"""
Simple Trading V7 — Data Feed V6 (Dynamic Universe)
====================================================
UPGRADE V6:

Changes from V5:
  • Dynamic universe fetcher: fetch_dynamic_movers()
    - Pulls top gainers + top volume IDX tickers via Yahoo Finance Query2 API
    - Butuh token dari logs/stockbit_token.json (auto-refresh via OwnershipAgent)
    - Cache harian, fallback graceful ke IDX_FULL jika Yahoo kosong
    - Cache harian (file-based) — fetch sekali per hari, tidak re-fetch tiap scan
    - Fallback graceful ke [] jika token tidak ada atau semua endpoint gagal
  • get_dynamic_universe(): merger IDX_FULL + movers, deduplicated, cap 200 tickers
  • get_catalyst_universe(): upgraded pakai dynamic universe
  • _fetch_stooq_backup: User-Agent bumped to STV/7.0
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import pickle
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# BACKUP DATA SOURCE  (Stooq)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_stooq_backup(ticker: str, interval: str = "1wk") -> Optional[pd.DataFrame]:
    """
    Backup via Stooq (free, no API key).
    BBCA.JK → BBCA.ID (Stooq IDX format).
    """
    try:
        base          = ticker.replace(".JK", "").upper()
        stooq_ticker  = f"{base}.ID"
        stooq_interval = "w" if interval == "1wk" else "d"
        url = (
            f"https://stooq.com/q/d/l/?s={stooq_ticker.lower()}"
            f"&i={stooq_interval}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "STV/7.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8")
        if "No data" in raw or len(raw) < 100:
            return None
        df = pd.read_csv(io.StringIO(raw), parse_dates=["Date"], index_col="Date")
        df.columns = [c.capitalize() for c in df.columns]
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col not in df.columns:
                if col == "Volume":
                    df["Volume"] = 0
                else:
                    return None
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        df = df[df["Close"] > 0].sort_index()
        if len(df) < 20:
            return None
        logger.debug(f"[DataFeed] {ticker} ✓ Stooq backup: {len(df)} bars")
        return df
    except Exception as exc:
        logger.debug(f"[DataFeed] {ticker} Stooq backup failed: {exc}")
        return None


def _fetch_with_backup(ticker: str, period: str, interval: str) -> Optional[pd.DataFrame]:
    """Primary (yfinance, 3 attempts + backoff) → Backup (Stooq daily+weekly)."""
    import time
    for attempt in range(3):
        try:
            df = yf.download(ticker, period=period, interval=interval,
                             progress=False, auto_adjust=True)
            if df is not None and len(df) >= 20:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                return df
        except Exception as exc:
            logger.debug(f"[DataFeed] {ticker} yfinance attempt {attempt+1}: {exc}")
            if attempt < 2:
                time.sleep(2 ** attempt)  # backoff: 1s, 2s

    logger.info(f"[DataFeed] {ticker} yfinance failed — trying Stooq backup")
    df_backup = _fetch_stooq_backup(ticker, interval)
    if df_backup is not None:
        return df_backup

    logger.warning(f"[DataFeed] {ticker} ALL sources failed")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# INCREMENTAL CACHE
# ─────────────────────────────────────────────────────────────────────────────

_CACHE_DIR = Path(__file__).parent.parent / "logs" / "data_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_CACHE_TTL   = {"1wk": 6 * 24 * 3600, "1d": 20 * 3600}   # backward compat
_FRESH_DAYS  = {"1wk": 6,  "1d": 1}
_MAX_INC_DAYS = {"1wk": 60, "1d": 14}
_INC_OVERLAP  = 5


def _cache_path(ticker: str, period: str, interval: str) -> Path:
    key = hashlib.md5(f"{ticker}_{period}_{interval}".encode()).hexdigest()[:12]
    return _CACHE_DIR / f"{ticker.replace('.JK','').replace(' ','_')}_{interval}_{key}.pkl"


def _cache_load(path: Path, ttl: int) -> Optional[pd.DataFrame]:
    """TTL-based load (compat shim for external callers)."""
    try:
        if not path.exists():
            return None
        age = (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds()
        if age > ttl:
            return None
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _cache_load_any(path: Path) -> Optional[pd.DataFrame]:
    """Load without TTL — freshness managed by date-gap logic."""
    try:
        if not path.exists():
            return None
        with open(path, "rb") as f:
            df = pickle.load(f)
        return df if df is not None and len(df) >= 20 else None
    except Exception:
        return None


def _cache_save(path: Path, df: pd.DataFrame) -> None:
    try:
        with open(path, "wb") as f:
            pickle.dump(df, f, protocol=4)
    except Exception as exc:
        logger.debug(f"[DataFeed] cache save failed: {exc}")


def _get_last_bar_date(df: pd.DataFrame) -> Optional[datetime]:
    try:
        last_idx = df.index[-1]
        if hasattr(last_idx, "to_pydatetime"):
            return last_idx.to_pydatetime().replace(tzinfo=None)
        return pd.Timestamp(last_idx).to_pydatetime().replace(tzinfo=None)
    except Exception:
        return None


def _is_cache_stale_trading(last_date: datetime) -> bool:
    """
    IDX-aware staleness check.
    Cache dianggap stale jika:
    - last_date adalah hari kerja sebelumnya DAN
    - sekarang sudah melewati jam 08:00 WIB hari kerja berikutnya
    Ini memastikan scan hari ini selalu fetch bar terbaru,
    bukan return cache kemarin yang gap-nya 0 hari secara calendar.
    """
    import pytz
    wib = pytz.timezone("Asia/Jakarta")
    now_wib = datetime.now(wib).replace(tzinfo=None)
    now_date = now_wib.date()
    last_date_only = last_date.date()

    # Kalau last_date sudah hari ini → masih fresh
    if last_date_only >= now_date:
        return False

    # Kalau last_date adalah kemarin atau lebih lama
    # dan sekarang sudah jam 08:00 WIB → stale, perlu fetch baru
    if now_wib.hour >= 8:
        return True

    return False


def _fetch_delta(ticker: str, last_date: datetime, interval: str) -> Optional[pd.DataFrame]:
    """Incremental fetch — yfinance primary, Stooq fallback (daily + weekly)."""
    import time
    for attempt in range(3):
        try:
            start_str = (last_date - timedelta(days=_INC_OVERLAP)).strftime("%Y-%m-%d")
            end_str   = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            df = yf.download(
                ticker, start=start_str, end=end_str,
                interval=interval, progress=False, auto_adjust=True
            )
            if df is not None and len(df) > 0:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                return df
        except Exception as exc:
            logger.debug(f"[DataFeed] delta fetch {ticker} attempt {attempt+1}: {exc}")
            if attempt < 2:
                time.sleep(2 ** attempt)  # backoff: 1s, 2s

    # Fallback ke Stooq (support daily & weekly)
    logger.debug(f"[DataFeed] {ticker} delta yfinance failed — Stooq fallback")
    return _fetch_stooq_backup(ticker, interval)


def _merge_incremental(existing: pd.DataFrame, delta: pd.DataFrame) -> pd.DataFrame:
    try:
        merged = pd.concat([existing, delta])
        merged = merged[~merged.index.duplicated(keep="last")]
        return merged.sort_index()
    except Exception:
        return existing


# ─────────────────────────────────────────────────────────────────────────────
# UNIVERSE LISTS  (unchanged from V4)
# ─────────────────────────────────────────────────────────────────────────────

EXCLUDED_TICKERS = {"SRIL", "WSKT", "BKSL", "MPPA"}

# ── Delisted ticker registry ──────────────────────────────────────────────────
# Auto-populated saat fetch_dynamic_movers mendeteksi "possibly delisted".
# Disimpan di logs/delisted_tickers.json agar persistent antar session.
_DELISTED_FILE = Path(__file__).resolve().parent.parent / "logs" / "delisted_tickers.json"

def _load_delisted() -> set:
    try:
        if not _DELISTED_FILE.exists():
            return set()
        return set(json.loads(_DELISTED_FILE.read_text(encoding="utf-8")).get("tickers", []))
    except Exception:
        return set()

def _save_delisted(tickers: set) -> None:
    try:
        _DELISTED_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DELISTED_FILE.write_text(
            json.dumps({"tickers": sorted(tickers)}, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.debug(f"[DataFeed] delisted save failed: {exc}")

DELISTED_TICKERS: set = _load_delisted()

IDX_FULL = [
    "AALI","ACES","ADHI","ADRO","AGII","AKRA","AMRT","ANTM","ARNA","ASII",
    "ASRI","BBCA","BBNI","BBRI","BBTN","BFIN","BJBR","BJTM","BMRI",
    "BMTR","BNGA","BNII","BNLI","BRIS","BRMS","BSDE","BUKA","CPIN","CTRA",
    "DMAS","DSNG","ELSA","EMTK","ERAA","EXCL","FLMC","GGRM","GOTO","HEAL",
    "HMSP","HRUM","ICBP","INCO","INDF","INDY","INKP","INTP","ISAT","ITMG",
    "JSMR","KAEF","KIJA","KLBF","LPKR","LSIP","MAPI","MBMA","MDKA","MEDC",
    "MIKA","MNCN","MTEL","MYOH","MYOR","NISP","PGAS","PGEO","PNLF",
    "PTBA","PTPP","PTRO","PWON","SCMA","SIDO","SMGR","SMRA","SSMS",
    "SSIA","TBIG","TBLA","TINS","TKIM","TLKM","TOWR","TPIA","TRIO","UNTR",
    "UNVR","WIKA","WTON","BMAS","BNBA","BACA","MCAS","BELI","DEWA",
    "FILM","HELI","INET","MAPA","NCKL","RAAM","SGER","SHIP","TOBA",
    "MBSS","UNIC","CUAN","BREN","AMMN","CBDK","DNET","MSIN","RIGS","LEAD",
    "WINS","ASSA","BHAT","MTDL","WOOD","SMMT","PANI","AVIA","CBPE","TELE",
    "BRPT","KJEN","RATU","BUVA","OMRE","BOBA","RAJA","MITI","WIFI","AXIO",
    "CARE","ARKO","HILL","BOAT","ZINC","LABA","NICL",
    "ENRG","AKSI","BUMI","DSSA","KEEN","APEX","BULL","BSSR",
]
IDX_FULL = sorted(list(set(t for t in IDX_FULL if t not in EXCLUDED_TICKERS)))

# ── IDX Extended — seed universe untuk dynamic mover filter ─────────────────
# Berisi ~200 ticker tambahan: IDX80, smallcap liquid, sektor aktif
# Digunakan oleh fetch_dynamic_movers() sebagai scan pool
IDX_EXTENDED = sorted(list(set([
    # Banking mid
    "PNBS","NOBU","BGTG","DNAR","BBMD","BBKP","SDRA","BVIC","MAYA","ARTO",
    "BCIC","BABP","AGRS","BGTG","BBMD",
    # Coal & Mining aktif
    "BUMI","BSSR","BULL","TOBA","MYOH","NCKL","MBSS","ZINC","RAAM","SGER",
    "CTTH","PKPK","FIRE","GEMS","DEWA","GTBO","KKGI","SMMT",
    "BOSS","DOID","MCOL","SMRU","MITI","RIGS","WINS","LEAD",
    # Property & konstruksi
    "MKPI","DART","DILD","PUDP","BKSL",
    # Consumer & Retail smallcap
    "SGRO","SUPA","TRIN","PSKT","JARR","MHKI","BABY","AHAP",
    "FOOD","ROTI","ULTJ","CAMP","CLEO","PZZA","JPFA","MAIN",
    "BISI","MERK","TSPC","SOHO","PYFA","DVLA","IRRA",
    # Infrastruktur utilities
    "BEEF","CPRO","DPUM","HATM","SMBR",
    # Trending smallcap
    "CARE","ARKO","HILL","BOAT","NICL","KEEN","APEX","BULL",
    "FIRE","PKPK","GTBO","KKGI","BOSS","DOID","MCOL","SMRU",
    "BREN","PANI","CBDK","CBPE","WIFI","AXIO","FILM","HELI","INET",
    "FLMC","KJEN","WOOD","TRIO","MAPA","OMRE","RATU","BUVA","BOBA",
    "RAJA","MSIN","TELE","BOAT","LABA","ZINC","ENRG","AKSI","DSSA",
    "KEEN","APEX","BULL","BSSR","EMTK","MNCN","BMTR","SCMA",
    "GOTO","BUKA","MCAS","BELI","DNET","ASSA",
])))

# Gabungan seed untuk mover scan (tidak ada duplikat dengan IDX_FULL)
# ATPK dihapus dari IDX_EXTENDED — confirmed delisted
_MOVER_SEED = sorted(list(set(IDX_FULL + IDX_EXTENDED) - DELISTED_TICKERS - EXCLUDED_TICKERS))



MSCI_CANDIDATES = [
    "BBCA","BBRI","BMRI","TLKM","ASII","BREN","BRPT","AMMN","MDKA","INCO",
    "ADRO","PTBA","ITMG","HRUM","INDY","MEDC","PGAS","ANTM","TINS","MBMA",
    "ICBP","INDF","MYOR","UNVR","KLBF","HEAL","MIKA","GOTO","BUKA","EMTK",
    "EXCL","ISAT","TLKM","TBIG","TOWR","BSDE","CTRA","SMRA","JSMR","PTPP",
    "CUAN","PTRO","BHAT","NCKL","NICL","PGEO","CBDK","PANI","TPIA","MTEL",
    "KJEN","RATU","BUVA","OMRE","BOBA","RAJA",
]

IDX30_LQ45_CANDIDATES = [
    "BBCA","BBRI","BMRI","TLKM","ASII","GOTO","BUKA","BREN","AMMN","MDKA",
    "ADRO","ANTM","INCO","PGAS","PTBA","EXCL","ISAT","TBIG","TOWR","CTRA",
    "SMRA","BSDE","JSMR","PTPP","INDF","ICBP","MYOR","UNVR","KLBF","TPIA",
    "CUAN","PTRO","BRPT","MEDC","HRUM","ITMG","INDY","HEAL","MIKA","EMTK",
]

IDX_WATCHLIST = [
    "BBCA","BBRI","BMRI","TLKM","ASII","UNVR","ICBP","KLBF","SMGR","PTBA",
    "ADRO","ANTM","INCO","PGAS","JSMR","EXCL","ISAT","TBIG","TOWR","BSDE",
    "CTRA","SMRA","PWON","WIKA","PTPP","GOTO","BUKA","EMTK","MNCN","SCMA",
    "INDF","MYOR","SIDO","KAEF","MIKA","HEAL","HRUM","ITMG","INDY","TPIA",
]


def get_idx_universe(mode: str = "full") -> list:
    return IDX_WATCHLIST if mode == "watchlist" else IDX_FULL


def get_universe_info() -> dict:
    return {
        "full_count":       len(IDX_FULL),
        "excluded_count":   len(EXCLUDED_TICKERS),
        "excluded_tickers": list(EXCLUDED_TICKERS),
        "watchlist_count":  len(IDX_WATCHLIST),
    }


# ─────────────────────────────────────────────────────────────────────────────
# DATA VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def validate_dataframe(
    df: Optional[pd.DataFrame],
    ticker: str = "",
    timeframe: str = "1d",
) -> dict:
    """Validate OHLCV DataFrame before analysis."""
    if df is None or len(df) < 10:
        return {"quality_score": 0, "issues": ["Insufficient data"], "valid": False}

    issues:   list[str] = []
    demerits: int       = 0
    close     = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
    total     = len(close)

    # NaN rate
    nan_rate = close.isna().sum() / total
    if nan_rate > 0.15:
        issues.append(f"High NaN rate: {nan_rate*100:.0f}%")
        demerits += 25
    elif nan_rate > 0.05:
        issues.append(f"Moderate NaN rate: {nan_rate*100:.0f}%")
        demerits += 10

    # Price outlier — >50% single-period move (data error)
    pct_chg  = close.pct_change().abs().dropna()
    outliers = int((pct_chg > 0.50).sum())
    if outliers > 0:
        issues.append(f"Price outlier(s): {outliers} bars >50% single-period move")
        demerits += 20 * min(outliers, 3)

    # Corporate action artifacts — >80% single-period (weekly data)
    corp_artifacts = int((pct_chg > 0.80).sum())
    if corp_artifacts > 0:
        issues.append(f"Possible corp action artifact: {corp_artifacts} bars >80% move")
        demerits += 15 * min(corp_artifacts, 2)

    # Flat/zero runs
    flat_runs = (close.diff().abs() < 0.01).rolling(5).sum()
    if bool((flat_runs >= 5).any()):
        issues.append("Flat/zero price runs detected (potential data gap)")
        demerits += 15

    # Volume completeness
    if "Volume" in df.columns:
        vol      = df["Volume"].fillna(0)
        zero_vol = (vol == 0).sum() / total
        if zero_vol > 0.20:
            issues.append(f"High zero-volume rate: {zero_vol*100:.0f}%")
            demerits += 15
        elif zero_vol > 0.10:
            issues.append(f"Some zero-volume bars: {zero_vol*100:.0f}%")
            demerits += 5

    # Negative prices
    if bool((close <= 0).any()):
        issues.append("Negative/zero price detected")
        demerits += 30

    # Insufficient bars — IPO stocks have fewer bars by nature, demerit proportionally
    min_bars = {"1wk": 20, "1d": 10, "1mo": 12}   # lowered: IPO akomodir
    required = min_bars.get(timeframe, 20)
    if total < required:
        issues.append(f"Insufficient bars: {total} < {required} for {timeframe}")
        demerits += max(0, int((required - total) / required * 20))

    quality_score = max(0, 100 - demerits)
    return {
        "quality_score": quality_score,
        "issues":        issues,
        "valid":         quality_score >= 50 and total >= 20,
        "bars":          total,
        "nan_rate":      round(nan_rate * 100, 1),
    }


def check_universe_health(
    tickers: list,
    timeframe: str = "1d",
    sample_size: int = 20,
) -> dict:
    import random
    sample  = random.sample(tickers, min(sample_size, len(tickers)))
    feed    = DataFeed(timeframe=timeframe)
    results = {"checked": 0, "healthy": 0, "warn": 0, "bad": 0, "issues": []}

    for t in sample:
        df = feed.fetch(t)
        if df is None:
            results["bad"] += 1
            results["issues"].append(f"{t}: No data")
            continue
        vr = validate_dataframe(df, t, timeframe)
        results["checked"] += 1
        if vr["quality_score"] >= 80:
            results["healthy"] += 1
        elif vr["quality_score"] >= 50:
            results["warn"] += 1
            if vr["issues"]:
                results["issues"].append(f"{t}: {vr['issues'][0]}")
        else:
            results["bad"] += 1
            results["issues"].append(f"{t} (Q={vr['quality_score']}): {', '.join(vr['issues'][:2])}")

    total = results["checked"]
    results["health_pct"] = round(results["healthy"] / total * 100, 1) if total > 0 else 0
    return results


# ─────────────────────────────────────────────────────────────────────────────
# DATA FEED CLASS
# ─────────────────────────────────────────────────────────────────────────────

class DataFeed:

    def __init__(
        self,
        timeframe: str = "1wk",
        period: Optional[str] = None,
    ) -> None:
        self.timeframe = timeframe
        self.period    = period or ("3y" if timeframe == "1wk" else "1y")

    def fetch(
        self,
        ticker:   str,
        period:   Optional[str] = None,
        interval: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Incremental cache strategy:
          ① gap ≤ FRESH_DAYS  → return cache (0 network calls)
          ② gap ≤ MAX_INC     → delta fetch (few bars)
          ③ gap > MAX_INC     → full re-fetch

        V5: returns None (not stale cache) if quality_score < 30.
        """
        if not ticker.endswith(".JK"):
            ticker += ".JK"

        base_ticker = ticker.replace(".JK", "")
        if base_ticker in EXCLUDED_TICKERS:
            logger.warning(f"[DataFeed] {ticker} in EXCLUDED_TICKERS")

        _period      = period   or self.period
        _interval    = interval or self.timeframe
        cpath        = _cache_path(ticker, _period, _interval)
        fresh_days   = _FRESH_DAYS.get(_interval, 6)
        max_inc_days = _MAX_INC_DAYS.get(_interval, 14)

        cached = _cache_load_any(cpath)
        if cached is not None:
            last_date = _get_last_bar_date(cached)
            if last_date is not None:
                gap = (datetime.now() - last_date).days
                stale = _is_cache_stale_trading(last_date)
                if not stale and gap <= fresh_days:
                    logger.debug(f"[DataFeed] {ticker} ✓ fresh (gap={gap}d)")
                    return cached
                if not stale and gap <= max_inc_days:
                    # Tidak stale, tapi gap cukup → incremental
                    logger.debug(f"[DataFeed] {ticker} ↑ incremental (gap={gap}d)")
                    delta = _fetch_delta(ticker, last_date, _interval)
                    if delta is not None and len(delta) > 0:
                        merged = _merge_incremental(cached, delta)
                        _cache_save(cpath, merged)
                        return merged
                    return cached
                # stale=True ATAU gap > max_inc_days → full re-fetch wajib
                logger.debug(f"[DataFeed] {ticker} stale={stale} gap={gap}d → full re-fetch")

        # Full re-fetch
        try:
            df = _fetch_with_backup(ticker, _period, _interval)
            if df is None or len(df) < 20:
                return cached
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            vr = validate_dataframe(df, ticker, _interval)
            # IPO stocks: data terbatas bukan berarti garbage
            # Skip hanya jika ada indikasi data corrupt (negative price, extreme NaN)
            # bukan karena bar count kurang
            ipo_stock = len(df) < 89  # weekly bars < ~2 tahun
            skip_threshold = 15 if ipo_stock else 30
            if vr["quality_score"] < skip_threshold:
                logger.warning(f"[DataFeed] {ticker} severe quality issue (Q={vr['quality_score']}) — skip")
                return None   # V5: don't use severe garbage data
            for iss in vr["issues"][:2]:
                logger.debug(f"[DataFeed] {ticker} quality: {iss}")

            _cache_save(cpath, df)
            return df
        except Exception as exc:
            logger.debug(f"[DataFeed] {ticker}: {exc}")
            return cached

    def fetch_batch(
        self,
        tickers:     list,
        max_workers: int = 8,
        period:      Optional[str] = None,
        interval:    Optional[str] = None,
    ) -> dict:
        """
        Batch fetch with incremental cache pipeline.
        Pipeline: ① PRE-CLASSIFY → ② FRESH → ③ INCREMENTAL → ④ FULL BATCH
        """
        _period   = period   or self.period
        _interval = interval or self.timeframe

        excluded_in = [t for t in tickers if t in EXCLUDED_TICKERS]
        if excluded_in:
            logger.warning(f"[DataFeed] batch: {excluded_in} in EXCLUDED_TICKERS")

        results      = {}
        needs_full   = []
        needs_incr   = []
        fresh_hits   = 0
        full_tickers = [t if t.endswith(".JK") else t + ".JK" for t in tickers]

        fresh_days   = _FRESH_DAYS.get(_interval, 6)
        max_inc_days = _MAX_INC_DAYS.get(_interval, 14)

        # ① PRE-CLASSIFY
        for t in full_tickers:
            cpath  = _cache_path(t, _period, _interval)
            cached = _cache_load_any(cpath)
            if cached is None:
                needs_full.append(t)
                continue
            last_date = _get_last_bar_date(cached)
            if last_date is None:
                needs_full.append(t)
                continue
            gap = (datetime.now() - last_date).days
            stale = _is_cache_stale_trading(last_date)
            if not stale and gap <= fresh_days:
                results[t] = cached
                fresh_hits += 1
            elif stale or gap > max_inc_days:
                needs_full.append(t)
            else:
                needs_incr.append(t)

        logger.info(
            f"[DataFeed] batch ({_interval}): "
            f"{fresh_hits} fresh | {len(needs_incr)} incr | {len(needs_full)} full"
        )

        # ② INCREMENTAL
        if needs_incr:
            with ThreadPoolExecutor(max_workers=min(max_workers, len(needs_incr))) as exe:
                fut_map = {exe.submit(self.fetch, t, _period, _interval): t for t in needs_incr}
                for fut in as_completed(fut_map):
                    t = fut_map[fut]
                    try:
                        df = fut.result()
                        if df is not None:
                            results[t] = df
                    except Exception as exc:
                        logger.debug(f"[DataFeed] incr {t}: {exc}")

        # ③ FULL BATCH
        if needs_full:
            def _extract_from_raw(raw: Optional[pd.DataFrame], tlist: list) -> dict:
                out = {}
                if raw is None or len(raw) == 0:
                    return out
                for t in tlist:
                    base = t.replace(".JK", "")
                    try:
                        if isinstance(raw.columns, pd.MultiIndex):
                            lvl0 = raw.columns.get_level_values(0)
                            if t    in lvl0: df = raw[t].dropna(how="all")
                            elif base in lvl0: df = raw[base].dropna(how="all")
                            else: continue
                        else:
                            df = raw
                        if df is not None and len(df) >= 20:
                            out[t] = df
                    except Exception as exc:
                        logger.debug(f"[DataFeed] extract {t}: {exc}")
                return out

            def _batch_download(ticker_list: list, p: str) -> dict:
                """Chunk menjadi grup 40 untuk hindari Yahoo rate limit."""
                import time
                _CHUNK = 40
                out = {}
                chunks = [ticker_list[i:i+_CHUNK] for i in range(0, len(ticker_list), _CHUNK)]
                for idx, chunk in enumerate(chunks):
                    if idx > 0:
                        time.sleep(1)  # jeda antar chunk hindari throttle
                    try:
                        raw = yf.download(
                            " ".join(chunk), period=p, interval=_interval,
                            progress=False, auto_adjust=True, group_by="ticker"
                        )
                        out.update(_extract_from_raw(raw, chunk))
                    except Exception as exc:
                        logger.debug(f"[DataFeed] batch chunk {idx+1}/{len(chunks)}: {exc}")
                return out

            batch_res = _batch_download(needs_full, _period)
            missing   = [t for t in needs_full if t not in batch_res]

            if missing:
                fallback_p = "2y" if _period == "3y" else _period
                if fallback_p != _period:
                    logger.info(f"[DataFeed] batch round 2: {len(missing)} → 2y")
                    batch_res.update(_batch_download(missing, fallback_p))
                    missing = [t for t in needs_full if t not in batch_res]

            if missing:
                logger.info(f"[DataFeed] batch round 3: {len(missing)} → individual 1y")
                with ThreadPoolExecutor(max_workers=max_workers) as exe:
                    fut_map = {exe.submit(self.fetch, t, "1y", _interval): t for t in missing}
                    for fut in as_completed(fut_map):
                        t = fut_map[fut]
                        try:
                            df = fut.result()
                            if df is not None:
                                batch_res[t] = df
                        except Exception as exc:
                            logger.debug(f"[DataFeed] round3 {t}: {exc}")

            for t, df in batch_res.items():
                if df is not None and len(df) >= 20:
                    cpath = _cache_path(t, _period, _interval)
                    _cache_save(cpath, df)
                    results[t] = df

        logger.info(f"[DataFeed] fetch_batch done: {len(results)}/{len(full_tickers)}")
        return results


# ─────────────────────────────────────────────────────────────────────────────
# IHSG REGIME  (V5 — extended regime tiers)
# ─────────────────────────────────────────────────────────────────────────────

def get_ihsg_regime(period: str = "1y") -> dict:
    """
    Market regime from IHSG (^JKSE).

    V5 added: BULL_STRONG tier — EMA13>EMA89 AND mom_4w > 3% AND breadth > 70%.
    Used by analyst_agent conviction engine for 1.25× sizing.

    V6 fix (8.2.4):
      • [DF-2] breadth: ganti formula invalid (hitung hari naik/turun) dengan
        % bar IHSG di atas EMA13 dalam 20 bar terakhir — trend consistency proxy.
      • [NEW-2] DataFeed default period daily: 60d → 1y agar EMA89 konvergen.
    """
    try:
        df = yf.download("^JKSE", period=period, interval="1wk",
                         progress=False, auto_adjust=True)
        if df is None or len(df) < 20:
            return {"cycle": "UNKNOWN", "ihsg": 0, "mom_4w": 0, "breadth": 0}

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close      = df["Close"]
        ema13      = close.ewm(span=13, adjust=False).mean()
        ema89      = close.ewm(span=89, adjust=False).mean()
        last_close = float(close.iloc[-1])
        last_ema13 = float(ema13.iloc[-1])
        last_ema89 = float(ema89.iloc[-1])
        ema_gap_pct = abs(last_ema13 - last_ema89) / last_ema89 * 100 if last_ema89 > 0 else 0.0

        mom_4w  = ((last_close / float(close.iloc[-5]) - 1) * 100) if len(close) >= 5 else 0.0

        # Trend consistency proxy: % bar di atas EMA13 dalam 20 bar terakhir.
        # Lebih valid dari hitung hari naik/turun — mengukur apakah harga
        # konsisten berada di atas trend line, bukan sekadar momentum sesaat.
        # Catatan: ini bukan market breadth sejati (butuh per-saham data),
        # tapi merupakan proxy terbaik yang tersedia dari single-index IHSG.
        lookback_bars = min(20, len(close))
        above_ema13   = int((close.tail(lookback_bars) > ema13.tail(lookback_bars)).sum())
        breadth       = int(above_ema13 / lookback_bars * 100)

        if last_ema13 > last_ema89:
            if mom_4w > 3.0 and breadth > 70:
                cycle = "BULL_STRONG"
            elif mom_4w > 0:
                cycle = "BULL_TREND"
            else:
                cycle = "BULL_CONSOLIDATION"
        elif last_ema13 <= last_ema89 and mom_4w > 0:
            cycle = "TRANSITION"
        elif last_ema13 <= last_ema89 and ema_gap_pct < 2.0:
            cycle = "BEAR_CONSOLIDATION"
        else:
            cycle = "BEAR_TREND"

        return {
            "cycle":   cycle,
            "ihsg":    round(last_close, 0),
            "mom_4w":  round(mom_4w, 1),
            "breadth": round(breadth, 0),
        }

    except Exception as exc:
        logger.error(f"[DataFeed] IHSG regime error: {exc}")
        return {"cycle": "UNKNOWN", "ihsg": 0, "mom_4w": 0, "breadth": 0}


# ─────────────────────────────────────────────────────────────────────────────
# DYNAMIC UNIVERSE — Top Movers Fetcher
# ─────────────────────────────────────────────────────────────────────────────

# Cache file: 1 fetch per trading day, stored in logs/ alongside daily_results.json
_MOVERS_CACHE_PATH = Path(__file__).resolve().parent.parent / "logs" / "movers_cache.json"
_MOVERS_MAX        = 80   # max movers dari dynamic filter
_UNIVERSE_CAP      = 300  # IDX_FULL ~155 + movers up to 80 = ~235, headroom OK


def _is_movers_cache_fresh() -> bool:
    """Return True if movers_cache.json was written today (IDX trading day aware)."""
    try:
        if not _MOVERS_CACHE_PATH.exists():
            return False
        raw   = json.loads(_MOVERS_CACHE_PATH.read_text(encoding="utf-8"))
        today = datetime.now().strftime("%Y-%m-%d")
        return raw.get("date") == today
    except Exception:
        return False


def _load_movers_cache() -> list:
    """Load tickers from today's movers cache. Returns [] on any error."""
    try:
        raw = json.loads(_MOVERS_CACHE_PATH.read_text(encoding="utf-8"))
        return raw.get("tickers", [])
    except Exception:
        return []


def _save_movers_cache(tickers: list) -> None:
    try:
        _MOVERS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _MOVERS_CACHE_PATH.write_text(
            json.dumps({"date": datetime.now().strftime("%Y-%m-%d"), "tickers": tickers}, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning(f"[Movers] Cannot save cache: {exc}")


def fetch_dynamic_movers(max_tickers: int = _MOVERS_MAX) -> list:
    """
    Opsi B: Dynamic mover filter berbasis OHLCV.

    Algoritma:
    1. Download 5d 1d-interval OHLCV untuk semua _MOVER_SEED (~300 ticker) via yf.download bulk
    2. Hitung pct_change 1d dan vol_ratio (volume hari ini / avg 5d)
    3. Filter: vol_ratio >= 2.0 ATAU abs(pct_chg) >= 3%
    4. Rank by combined score = vol_ratio * abs(pct_chg)
    5. Return top max_tickers — cache 1 hari

    Keunggulan vs static IDX_FULL:
    - Tangkap BABY, CTTH, AHAP, MHKI dll yang tidak ada di IDX_FULL
    - Self-updating setiap hari berdasarkan aktivitas market riil
    - Tidak butuh external API / token
    - Satu yf.download bulk call = ~10-15 detik untuk 300 ticker
    """
    # Cache hit
    if _is_movers_cache_fresh():
        cached = _load_movers_cache()
        logger.info(f"[Movers] Cache hit: {len(cached)} tickers")
        return cached

    logger.info(f"[Movers] Scanning {len(_MOVER_SEED)} seed tickers for movers...")

    try:
        symbols = [f"{t}.JK" for t in _MOVER_SEED]

        # Bulk download 5d — satu call, efisien
        df_raw = yf.download(
            symbols,
            period   = "5d",
            interval = "1d",
            group_by = "ticker",
            auto_adjust = True,
            progress = False,
            threads  = True,
        )

        movers = []
        newly_delisted: set = set()

        for t in _MOVER_SEED:
            sym = f"{t}.JK"
            try:
                # Handle multi-ticker vs single-ticker yfinance output
                if len(symbols) > 1:
                    lvl0 = df_raw.columns.get_level_values(0)
                    if sym not in lvl0:
                        # Tidak ada data sama sekali → kandidat delisted
                        newly_delisted.add(t)
                        continue
                    df = df_raw[sym].dropna(how="all")
                else:
                    df = df_raw.dropna(how="all")

                if df is None or len(df) < 2:
                    # Data ada tapi kosong → juga kandidat delisted
                    newly_delisted.add(t)
                    continue

                close   = df["Close"]
                volume  = df["Volume"]

                pct_chg   = float((close.iloc[-1] - close.iloc[-2]) / max(close.iloc[-2], 1) * 100)
                avg_vol   = float(volume.iloc[:-1].mean())  # avg dari 4 hari sebelumnya
                vol_ratio = float(volume.iloc[-1]) / max(avg_vol, 1)

                # Filter: aktif hari ini
                if vol_ratio >= 2.0 or abs(pct_chg) >= 3.0:
                    score = vol_ratio * (1 + abs(pct_chg) / 10)
                    movers.append({
                        "ticker":    t,
                        "pct_chg":   round(pct_chg, 2),
                        "vol_ratio": round(vol_ratio, 2),
                        "score":     round(score, 3),
                    })

            except Exception:
                continue

        # Rank by score descending
        movers.sort(key=lambda x: -x["score"])
        result = [m["ticker"] for m in movers[:max_tickers]]

        # Auto-register newly delisted tickers — skip yang punya data valid
        active_tickers = {m["ticker"] for m in movers}
        confirmed_delisted = newly_delisted - active_tickers
        if confirmed_delisted:
            DELISTED_TICKERS.update(confirmed_delisted)
            _save_delisted(DELISTED_TICKERS)
            logger.info(f"[Movers] Auto-delisted: {sorted(confirmed_delisted)} — skip future scans")

        if result:
            _save_movers_cache(result)
            top5 = [(m["ticker"], f"{m['pct_chg']:+.1f}%", f"{m['vol_ratio']:.1f}x")
                    for m in movers[:5]]
            logger.info(f"[Movers] {len(result)} movers found — top5: {top5}")
        else:
            logger.info("[Movers] No movers detected — market quiet or all below threshold")

        return result

    except Exception as e:
        logger.warning(f"[Movers] Dynamic scan error: {e}")
        return []


def get_dynamic_universe(include_movers: bool = True) -> list:
    """
    Merged universe: IDX_FULL (static) + top movers (dynamic), deduplicated, capped.

    Args:
        include_movers: set False to skip dynamic fetch (e.g. offline mode).

    Returns list of bare tickers (no .JK suffix).
    """
    base    = list(IDX_FULL)
    movers  = fetch_dynamic_movers() if include_movers else []

    # Movers first so they get priority in ordering (scanner sorts by signal anyway)
    combined = list(dict.fromkeys(movers + base))[:_UNIVERSE_CAP]  # movers priority
    new_tickers = [t for t in movers if t not in set(IDX_FULL)]

    if new_tickers:
        logger.info(f"[Universe] +{len(new_tickers)} new tickers from movers: {new_tickers}")

    return combined


# ─────────────────────────────────────────────────────────────────────────────
# UNIVERSE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_msci_candidates() -> list:
    seen, out = set(), []
    for t in MSCI_CANDIDATES:
        if t not in seen:
            seen.add(t)
            out.append(t + ".JK")
    return out


def get_catalyst_universe() -> list:
    """
    Full catalyst universe: dynamic movers + IDX_FULL + MSCI + LQ45, deduplicated.
    Upgraded in V6 to include daily top movers for remora sensitivity.
    """
    # Get dynamic base (movers + IDX_FULL merged)
    dynamic_base = get_dynamic_universe(include_movers=True)

    seen: set  = set(dynamic_base)
    out:  list = [t + ".JK" for t in dynamic_base]

    # Append MSCI + LQ45 not already covered
    for t in list(MSCI_CANDIDATES) + list(IDX30_LQ45_CANDIDATES):
        if t not in seen:
            seen.add(t)
            out.append(t + ".JK")

    return out
