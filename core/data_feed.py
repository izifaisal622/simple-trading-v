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

    # ── Auto-blacklist setelah 2x ALL sources failed ──────────────────────────
    # Guard: 1x bisa rate limit. 2x = kemungkinan besar delisted/suspended.
    base = ticker.replace(".JK", "")
    _FAIL_COUNTS[base] = _FAIL_COUNTS.get(base, 0) + 1
    if _FAIL_COUNTS[base] >= 2 and base not in DELISTED_TICKERS:
        DELISTED_TICKERS.add(base)
        _save_delisted(DELISTED_TICKERS, _FAIL_COUNTS)
        logger.warning(
            f"[DataFeed] {base} di-blacklist otomatis (ALL sources failed 2x) "
            f"→ disimpan ke delisted_tickers.json"
        )
    elif _FAIL_COUNTS[base] == 1:
        # Simpan counter tapi belum blacklist
        _save_delisted(DELISTED_TICKERS, _FAIL_COUNTS)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# INCREMENTAL CACHE
# ─────────────────────────────────────────────────────────────────────────────

_CACHE_DIR = Path(__file__).parent.parent / "logs" / "data_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def cleanup_orphan_cache(dry_run: bool = False) -> int:
    """
    [FD-1] Hapus cache file yang dibuat dengan hash berbasis period (format lama).
    Format lama: BBCA_1d_<hash-dari-ticker+period+interval>.pkl
    Format baru: BBCA_1d_<hash-dari-ticker+interval>.pkl
    Keduanya punya nama yang sama dari luar tapi hash berbeda.
    Utility ini bisa dipanggil manual atau sekali saat startup.
    Returns jumlah file yang dihapus (atau kandidat jika dry_run=True).
    """
    if not _CACHE_DIR.exists():
        return 0
    # Hitung hash baru (tanpa period) untuk semua file yang ada
    # File yang hash-nya tidak match format baru = orphan dari format lama
    deleted = 0
    for pkl_file in _CACHE_DIR.glob("*.pkl"):
        stem = pkl_file.stem   # e.g. "BBCA_1d_abc123def456"
        parts = stem.rsplit("_", 2)
        if len(parts) < 3:
            continue
        ticker_base, interval_part, old_hash = parts[0], parts[1], parts[2]
        ticker_jk = f"{ticker_base}.JK"
        expected_hash = hashlib.md5(f"{ticker_jk}_{interval_part}".encode()).hexdigest()[:12]
        if old_hash != expected_hash:
            if not dry_run:
                try:
                    pkl_file.unlink()
                    logger.debug(f"[Cache] Removed orphan: {pkl_file.name}")
                except Exception:
                    pass
            deleted += 1
    if deleted:
        action = "Found" if dry_run else "Removed"
        logger.info(f"[Cache] {action} {deleted} orphan cache file(s)")
    return deleted

_CACHE_TTL   = {"1wk": 6 * 24 * 3600, "1d": 20 * 3600}   # backward compat
_FRESH_DAYS  = {"1wk": 6,  "1d": 1}
_MAX_INC_DAYS = {"1wk": 60, "1d": 14}
_INC_OVERLAP  = 5


def _cache_path(ticker: str, period: str, interval: str) -> Path:
    # [FD-1 FIX] Hash hanya pakai ticker+interval, bukan period.
    # Sebelumnya: period masuk hash → period berubah (60d→1y) membuat
    # file cache baru, cache lama tidak pernah dibaca/dihapus → orphan accumulation.
    # Fix: cache key = ticker+interval saja. Period hanya menentukan seberapa
    # jauh ke belakang saat full re-fetch, bukan identity file cache.
    key = hashlib.md5(f"{ticker}_{interval}".encode()).hexdigest()[:12]
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

    [DF-3 FIX] Weekend handling:
    - Sabtu/Minggu bukan hari trading → cache Jumat tidak stale saat weekend
    - last_trading_day dihitung mundur dari today, skip Sabtu(5) dan Minggu(6)
    - Cache dianggap fresh jika last_date >= last_trading_day
    """
    import pytz
    wib = pytz.timezone("Asia/Jakarta")
    now_wib      = datetime.now(wib).replace(tzinfo=None)
    now_date     = now_wib.date()
    last_date_only = last_date.date()

    # Hitung last trading day (mundur dari today, skip weekend)
    from datetime import date as _date
    candidate = now_date
    steps = 0
    while candidate.weekday() >= 5:   # 5=Sabtu, 6=Minggu
        candidate = candidate - timedelta(days=1)
        steps += 1
    last_trading_day = candidate

    # Cache masih fresh jika last_date >= last_trading_day
    if last_date_only >= last_trading_day:
        return False

    # Cache adalah bar sebelum last_trading_day → stale jika jam >= 08:00 WIB
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


def _merge_incremental(
    existing: pd.DataFrame,
    delta:    pd.DataFrame,
    ticker:   str = "",
) -> pd.DataFrame | None:
    """
    Merge existing cache dengan delta fetch.

    [FD-3 FIX] Deteksi post-split cache corruption:
    Masalah: auto_adjust=True di yfinance retroaktif adjust harga saat split.
    Cache lama (pre-fetch) punya harga scale lama. Delta (post-split) punya
    scale baru. Merge menghasilkan price jump >50% di junction point.

    Solusi: setelah merge, cek apakah ada single-bar change >50% di 10 bar
    sekitar junction (overlap zone antara existing dan delta).
    Jika ya → return None → caller akan trigger full re-fetch.
    Ini lebih safe daripada mencoba detect split secara eksplisit.
    """
    try:
        merged = pd.concat([existing, delta])
        merged = merged[~merged.index.duplicated(keep="last")]
        merged = merged.sort_index()

        # Cek corruption di junction zone (10 bar terakhir existing ∩ delta)
        if "Close" in merged.columns and len(merged) >= 4:
            # Ambil zona overlap: 10 bar sebelum akhir existing
            junction_end   = existing.index[-1]
            junction_start = existing.index[-min(10, len(existing))]
            zone = merged.loc[junction_start:junction_start + pd.Timedelta(days=20)]
            if len(zone) >= 2:
                close_zone = zone["Close"].dropna()
                if len(close_zone) >= 2:
                    pct_chg = close_zone.pct_change().abs().dropna()
                    if (pct_chg > 0.50).any():
                        logger.warning(
                            f"[DataFeed] {ticker} merge junction outlier >50% detected "
                            f"— possible post-split stale cache. Triggering full re-fetch."
                        )
                        return None  # Signal ke caller untuk full re-fetch

        return merged
    except Exception:
        return existing


# ─────────────────────────────────────────────────────────────────────────────
# UNIVERSE LISTS  (unchanged from V4)
# ─────────────────────────────────────────────────────────────────────────────

# Ticker yang dikecualikan dari scan:
# - Confirmed delisted atau suspended >24 bulan per Jun 2026
# - WIKA: suspended KSEI + gagal bayar obligasi
# - BUMI, ENRG, DEWA: suspended panjang + financial distress
# - KJEN, HEAL, NISP, LEAD, FIRE, WIFI, WOOD, PSKT: tidak ada data yfinance
EXCLUDED_TICKERS = {
    # Original
    "SRIL", "WSKT", "BKSL", "MPPA",
    # Suspended/delisted confirmed Jun 2026
    "WIKA", "BUMI", "ENRG", "DEWA",
    # Tidak ada data yfinance (suspended/private/ticker error)
    "KJEN", "HEAL", "LEAD", "FIRE", "WIFI", "WOOD",
    "RATU", "TRIO", "ZINC", "LABA", "BOAT", "HILL", "ARKO", "CARE",
    "AXIO", "MITI", "RAJA", "OMRE", "BUVA", "KIJA", "FLMC",
}

# ── Delisted ticker registry ──────────────────────────────────────────────────
# Auto-populated saat fetch_dynamic_movers mendeteksi "possibly delisted".
# Disimpan di logs/delisted_tickers.json agar persistent antar session.
_DELISTED_FILE = Path(__file__).resolve().parent.parent / "logs" / "delisted_tickers.json"

def _load_delisted() -> tuple:
    """Return (delisted_set, fail_counter_dict)."""
    try:
        if not _DELISTED_FILE.exists():
            return set(), {}
        data = json.loads(_DELISTED_FILE.read_text(encoding="utf-8"))
        return set(data.get("tickers", [])), data.get("fail_counts", {})
    except Exception:
        return set(), {}

def _save_delisted(tickers: set, fail_counts: dict = None) -> None:
    try:
        _DELISTED_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "tickers":     sorted(tickers),
            "fail_counts": fail_counts or {},
            "note": "Auto-populated saat ALL sources failed >= 2x. Edit manual jika salah."
        }
        _DELISTED_FILE.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.debug(f"[DataFeed] delisted save failed: {exc}")

_delisted_raw, _FAIL_COUNTS = _load_delisted()
DELISTED_TICKERS: set = _delisted_raw

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
        if base_ticker in DELISTED_TICKERS:
            logger.debug(f"[DataFeed] {ticker} in DELISTED_TICKERS — skip fetch")
            return None

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
                        merged = _merge_incremental(cached, delta, ticker=ticker)
                        if merged is None:
                            # [FD-3] Junction outlier detected → force full re-fetch
                            logger.debug(f"[DataFeed] {ticker} merge failed junction check → full re-fetch")
                            pass   # fall through ke full re-fetch di bawah
                        else:
                            _cache_save(cpath, merged)
                            return merged
                    else:
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
                """
                Chunk menjadi grup kecil dengan delay untuk hindari Yahoo rate limit.
                FIX 8.8.3: chunk 15 (dari 40) + delay 3s antar chunk + retry individual
                untuk ticker yang gagal di batch.
                """
                import time
                _CHUNK      = 15   # Lebih kecil dari 40 — Yahoo lebih toleran
                _CHUNK_DELAY = 3.0  # Detik antar chunk — cukup untuk reset throttle
                out = {}
                chunks = [ticker_list[i:i+_CHUNK] for i in range(0, len(ticker_list), _CHUNK)]
                logger.info(f"[DataFeed] batch_download: {len(ticker_list)} tickers → {len(chunks)} chunks @ {_CHUNK} each")
                for idx, chunk in enumerate(chunks):
                    if idx > 0:
                        time.sleep(_CHUNK_DELAY)
                    try:
                        raw = yf.download(
                            " ".join(chunk), period=p, interval=_interval,
                            progress=False, auto_adjust=True, group_by="ticker"
                        )
                        chunk_result = _extract_from_raw(raw, chunk)
                        out.update(chunk_result)
                        failed_in_chunk = [t for t in chunk if t not in chunk_result]
                        if failed_in_chunk:
                            logger.debug(f"[DataFeed] chunk {idx+1}: {len(failed_in_chunk)} gagal → retry individual")
                            time.sleep(1.0)
                            for t in failed_in_chunk:
                                try:
                                    raw_single = yf.download(
                                        t, period=p, interval=_interval,
                                        progress=False, auto_adjust=True
                                    )
                                    if raw_single is not None and len(raw_single) >= 20:
                                        if isinstance(raw_single.columns, pd.MultiIndex):
                                            raw_single.columns = raw_single.columns.get_level_values(0)
                                        out[t] = raw_single
                                except Exception:
                                    pass
                                time.sleep(0.5)
                        logger.debug(f"[DataFeed] chunk {idx+1}/{len(chunks)}: {len(chunk_result)}/{len(chunk)} OK")
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
                # FIX 8.8.3: Round 3 sequential dengan delay 1s per ticker
                # ThreadPoolExecutor parallel di sini justru trigger throttle lebih parah
                import time as _time
                logger.info(f"[DataFeed] batch round 3: {len(missing)} → sequential individual {_period}")
                for t in missing:
                    try:
                        df = self.fetch(t, _period, _interval)
                        if df is not None:
                            batch_res[t] = df
                    except Exception as exc:
                        logger.debug(f"[DataFeed] round3 {t}: {exc}")
                    _time.sleep(1.0)  # 1s antar request — hindari throttle

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

    V7 — Adaptive Multi-Signal Regime (8.5.9):
    Ganti single-gating EMA cross dengan tiga sinyal yang di-weight:
      1. EMA13 vs EMA89 — struktur trend jangka panjang
      2. mom_2w — momentum 2 minggu (lebih responsif dari 4W)
      3. pct_from_52w_low — seberapa jauh dari bottom (objective recovery proxy)

    Regime matrix:
      EMA13 > EMA89, mom_2w > 0, breadth > 55         → BULL_STRONG (jika mom_2w > 3 & breadth > 70)
      EMA13 > EMA89, mom_2w > 0                        → BULL_TREND
      EMA13 > EMA89, mom_2w ≤ 0                        → BULL_CONSOLIDATION
      EMA13 ≤ EMA89, mom_2w > 0, pct_from_low ≥ 8%    → TRANSITION
      EMA13 ≤ EMA89, mom_2w > -3%, pct_from_low ≥ 5%  → BEAR_CONSOLIDATION
      EMA13 ≤ EMA89, else                               → BEAR_TREND

    Alasan perubahan:
    - mom_4w terlalu lambat: IHSG bisa rebound +11% dari bottom tapi
      mom_4w masih -10% karena 4W lalu harga masih tinggi → scanner
      stuck di BEAR_TREND meski ada recovery signals yang valid
    - pct_from_low sebagai recovery proxy: lebih objektif dari momentum
      murni, tidak terpengaruh level harga 4W lalu
    """
    try:
        df = yf.download("^JKSE", period=period, interval="1wk",
                         progress=False, auto_adjust=True)
        if df is None or len(df) < 20:
            return {"cycle": "UNKNOWN", "ihsg": 0, "mom_4w": 0, "mom_2w": 0,
                    "breadth": 0, "pct_from_low": 0}

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close      = df["Close"]
        ema13      = close.ewm(span=13, adjust=False).mean()
        ema89      = close.ewm(span=89, adjust=False).mean()
        last_close = float(close.iloc[-1])
        last_ema13 = float(ema13.iloc[-1])
        last_ema89 = float(ema89.iloc[-1])

        # Signal 1: Momentum 2W (responsif) — ganti 4W yang terlalu lambat
        # 2W = 2 bar weekly
        mom_2w = ((last_close / float(close.iloc[-3]) - 1) * 100) if len(close) >= 3 else 0.0
        # Tetap hitung mom_4w untuk backward compat output
        mom_4w = ((last_close / float(close.iloc[-5]) - 1) * 100) if len(close) >= 5 else 0.0

        # Signal 2: % dari 52W low — recovery proxy paling objektif
        low_52w     = float(close.tail(52).min()) if len(close) >= 52 else float(close.min())
        pct_from_low = ((last_close - low_52w) / low_52w * 100) if low_52w > 0 else 0.0

        # Signal 3: Breadth proxy — % bar IHSG di atas EMA13 dalam 20 bar
        lookback_bars = min(20, len(close))
        above_ema13   = int((close.tail(lookback_bars) > ema13.tail(lookback_bars)).sum())
        breadth       = int(above_ema13 / lookback_bars * 100)

        # ── Adaptive regime matrix ────────────────────────────────────────────
        if last_ema13 > last_ema89:
            # Bull structure — EMA13 sudah di atas EMA89
            if mom_2w > 3.0 and breadth > 70:
                cycle = "BULL_STRONG"
            elif mom_2w > 0:
                cycle = "BULL_TREND"
            else:
                cycle = "BULL_CONSOLIDATION"

        elif mom_2w > 0 and pct_from_low >= 8.0:
            # Bear structure tapi ada recovery nyata:
            # - momentum 2W positif (harga naik dalam 2 minggu terakhir)
            # - sudah ≥8% dari 52W low (bukan sekadar dead cat bounce)
            # → TRANSITION: scanner selektif, sizing 50%, conviction ≥6
            cycle = "TRANSITION"

        elif mom_2w > -3.0 and pct_from_low >= 5.0:
            # Bear tapi konsolidasi — tidak turun agresif, ada sedikit recovery
            # → BEAR_CONSOLIDATION: sizing 25%, hanya Grade A
            cycle = "BEAR_CONSOLIDATION"

        else:
            # Bear aktif — momentum negatif dan/atau belum jauh dari bottom
            cycle = "BEAR_TREND"

        return {
            "cycle":        cycle,
            "ihsg":         round(last_close, 0),
            "mom_4w":       round(mom_4w, 1),       # backward compat
            "mom_2w":       round(mom_2w, 1),        # baru — lebih responsif
            "breadth":      round(breadth, 0),
            "pct_from_low": round(pct_from_low, 1),  # baru — recovery proxy
        }

    except Exception as exc:
        logger.error(f"[DataFeed] IHSG regime error: {exc}")
        return {"cycle": "UNKNOWN", "ihsg": 0, "mom_4w": 0, "mom_2w": 0,
                "breadth": 0, "pct_from_low": 0}


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


def _save_movers_cache(tickers: list, extra: dict | None = None) -> None:
    """
    Simpan movers cache ke disk.
    extra: dict tambahan yang ikut disimpan (mis. delisted_candidates).
    [FD-4 FIX] _save_movers_cache sebelumnya hanya simpan date+tickers,
    sehingga delisted_candidates yang diupdate di memory tidak pernah persist.
    """
    try:
        _MOVERS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload: dict = {"date": datetime.now().strftime("%Y-%m-%d"), "tickers": tickers}
        if extra:
            payload.update(extra)
        _MOVERS_CACHE_PATH.write_text(
            json.dumps(payload, indent=2),
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

        # [DF-4 FIX] Auto-register delisted — dengan threshold konfirmasi.
        # Bug lama: ticker yang gagal fetch karena network error / Yahoo timeout
        # langsung di-blacklist permanen. Untuk IDX dengan 300 ticker, intermittent
        # error saat bulk download cukup umum → saham valid masuk blacklist.
        #
        # Fix: hanya blacklist jika newly_delisted muncul di >= 2 scan berturut-turut.
        # Implementasi: simpan "candidate_delisted" di movers_cache.json (count),
        # baru pindah ke DELISTED_TICKERS setelah count >= 2.
        active_tickers = {m["ticker"] for m in movers}
        confirmed_delisted_raw = newly_delisted - active_tickers

        if confirmed_delisted_raw:
            # Load kandidat dari cache sebelumnya
            try:
                raw_cache = json.loads(_MOVERS_CACHE_PATH.read_text(encoding="utf-8")) if _MOVERS_CACHE_PATH.exists() else {}
            except Exception:
                raw_cache = {}
            candidates: dict = raw_cache.get("delisted_candidates", {})

            to_blacklist: set = set()
            for t in confirmed_delisted_raw:
                count = candidates.get(t, 0) + 1
                if count >= 2:
                    to_blacklist.add(t)
                    candidates.pop(t, None)   # keluar dari kandidat, masuk blacklist
                else:
                    candidates[t] = count     # pertama kali gagal — tunggu konfirmasi

            # [FD-4 FIX] Simpan kandidat ke disk segera — jangan tunggu _save_movers_cache
            # karena _save_movers_cache dipanggil kondisional (if result:) dan
            # sebelumnya tidak membawa delisted_candidates sama sekali.
            raw_cache["delisted_candidates"] = candidates
            try:
                _MOVERS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                _MOVERS_CACHE_PATH.write_text(
                    json.dumps(raw_cache, indent=2), encoding="utf-8"
                )
            except Exception as _e:
                logger.debug(f"[Movers] candidates persist failed: {_e}")

            if to_blacklist:
                DELISTED_TICKERS.update(to_blacklist)
                _save_delisted(DELISTED_TICKERS)
                logger.info(f"[Movers] Confirmed delisted (2x): {sorted(to_blacklist)}")

            if candidates:
                logger.debug(f"[Movers] Delisted candidates (1x, pending): {sorted(candidates.keys())}")

        # [FD-4 FIX] Kumpulkan extra data (termasuk delisted_candidates) untuk disimpan bersama.
        # raw_cache mungkin tidak ter-inisialisasi jika confirmed_delisted_raw kosong.
        extra_payload: dict = {}
        try:
            _rc = json.loads(_MOVERS_CACHE_PATH.read_text(encoding="utf-8")) if _MOVERS_CACHE_PATH.exists() else {}
            if "delisted_candidates" in _rc:
                extra_payload["delisted_candidates"] = _rc["delisted_candidates"]
        except Exception:
            pass

        if result:
            _save_movers_cache(result, extra=extra_payload if extra_payload else None)
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
    Dynamic universe dari idx_pool.json (LQ45+IDX80+IDXKompas100+IDXGrowth30+midcap).
    Fallback ke IDX_FULL jika file tidak ada.

    FIX 8.8.4: ganti hardcode IDX_FULL 126 ticker dengan pool JSON 179 ticker.
    Pool di-update manual di data/idx_pool.json saat ada IPO baru / delisting.
    """
    # ── Load dari idx_pool.json ───────────────────────────────────────────────
    _pool_file = Path(__file__).resolve().parent.parent / "data" / "idx_pool.json"
    pool_tickers = []
    if _pool_file.exists():
        try:
            _pool_data   = json.loads(_pool_file.read_text(encoding="utf-8"))
            pool_tickers = _pool_data.get("tickers", [])
            # Buang yang ada di EXCLUDED_TICKERS
            pool_tickers = [t for t in pool_tickers if t not in EXCLUDED_TICKERS]
            logger.info(f"[Universe] idx_pool.json: {len(pool_tickers)} ticker valid")
        except Exception as exc:
            logger.warning(f"[Universe] idx_pool.json load failed: {exc} → fallback IDX_FULL")

    base = pool_tickers if pool_tickers else list(IDX_FULL)

    # ── Tambah movers dari hari ini (opsional) ────────────────────────────────
    movers = fetch_dynamic_movers() if include_movers else []
    new_tickers = [t for t in movers if t not in set(base)]
    if new_tickers:
        logger.info(f"[Universe] +{len(new_tickers)} movers baru: {new_tickers}")

    combined = list(dict.fromkeys(movers + base))[:_UNIVERSE_CAP]
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
