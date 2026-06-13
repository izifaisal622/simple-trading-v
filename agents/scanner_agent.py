"""
Simple Trading V6 — Scanner Agent V5 (Institutional)
======================================================
UPGRADE V5:
  • Removed unused SetupResult import
  • Removed duplicate pathlib.Path import (line 268)
  • Sort: STRONG_BREAKOUT first, then BREAKOUT, then WATCHLIST
  • daily_scan: BULL_STRONG regime → ihsg_bullish=True
  • Signal log: vp_score, vp_entry_zone added to DB insert
  • All bare-except → logged handlers
  • No logic changes to scan pipeline
"""

import json
import logging
import pandas as pd
import dataclasses
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from config.strategy_config import StrategyConfig
from core.data_feed         import DataFeed, get_ihsg_regime, get_idx_universe, get_dynamic_universe
from core.technical_engine  import (
    EMABreakoutEngine,
    DailyEMAEngine,
    check_daily_entry, analyze_market_structure, compute_mcf,
)

logger   = logging.getLogger(__name__)
LOGS_DIR = Path(__file__).parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)


def _to_dict(result) -> dict | None:
    if result is None:
        return None
    if isinstance(result, dict):
        return result
    if hasattr(result, "__dict__"):
        return dict(result.__dict__)
    try:
        return dataclasses.asdict(result)
    except Exception:
        return {k: getattr(result, k, None) for k in dir(result) if not k.startswith("_")}


def _flatten_multiindex(df: pd.DataFrame) -> pd.DataFrame:
    if df is not None and isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


class ScannerAgent:

    def __init__(self, config: StrategyConfig) -> None:
        self.cfg    = config
        self.engine = EMABreakoutEngine(config)   # weekly engine (kept for fallback)
        self.daily_engine = DailyEMAEngine(config)  # NEW: daily primary engine
        self.feed   = DataFeed(timeframe="1wk")
        self.feed_d = DataFeed(timeframe="1d")
        self._cache:   dict = {}
        self._cache_d: dict = {}

        try:
            import yfinance as yf
            self._ihsg_df = yf.download(
                "^JKSE", period="3y", interval="1wk",
                progress=False, auto_adjust=True,
            )
            self._ihsg_df = _flatten_multiindex(self._ihsg_df)
        except Exception as exc:
            logger.debug(f"[Scanner] IHSG fetch: {exc}")
            self._ihsg_df = None

        self._mkt_bull: bool = True

    def _scan_ticker(self, ticker: str, regime: str) -> dict | None:
        t    = ticker if ticker.endswith(".JK") else ticker + ".JK"
        df   = self._cache.get(t)    # weekly — untuk context
        df_d = self._cache_d.get(t)  # daily  — primary engine

        if df is None or len(df) == 0:
            df = _flatten_multiindex(self.feed.fetch(ticker))
        if df_d is None or len(df_d) == 0:
            df_d = _flatten_multiindex(self.feed_d.fetch(ticker))

        # ── Daily engine sebagai primary ──────────────────────────────────────
        # Minimal 30 bar daily (~6 minggu) — fallback ke weekly kalau tidak ada
        if df_d is not None and len(df_d) >= 30:
            r = self.daily_engine.analyze(
                df_daily  = df_d,
                ticker    = ticker,
                df_weekly = df,
                ihsg_df   = self._ihsg_df,
                regime    = regime,
            )
        elif df is not None and len(df) >= 10:
            # Fallback: weekly engine (saham tanpa data daily cukup)
            result = self.engine.analyze(df, ticker, ihsg_df=self._ihsg_df, regime=regime)
            r = _to_dict(result)
        else:
            return None

        if not isinstance(r, dict):
            return None

        sig = r.get("signal", "")
        if not sig or sig == "NONE":
            return None
        if r.get("score", 0) < 3:
            return None

        # ── Dual-timeframe ───────────────────────────────────────────────────
        # Kalau dari DailyEMAEngine, daily fields sudah diisi — skip check_daily_entry
        # Kalau dari fallback weekly engine, jalankan check_daily_entry seperti biasa
        if r.get("daily_pattern") != "DAILY_PRIMARY":
            weekly_cross = r.get("cross_state", "")
            daily_data   = check_daily_entry(df_d, str(weekly_cross))
            r.update({
                "daily_ok":         daily_data.get("daily_ok", False),
                "daily_pattern":    daily_data.get("daily_pattern", ""),
                "daily_cross":      daily_data.get("daily_cross", ""),
                "fresh_cross":      daily_data.get("fresh_cross", False),
                "ema5_cross":       daily_data.get("ema5_cross", False),
                "ema5d":            daily_data.get("ema5d", 0),
                "ema13d":           daily_data.get("ema13d", 0),
                "ema89d":           daily_data.get("ema89d", 0),
                "pct_vs_ema13d":    daily_data.get("pct_vs_ema13d", 0),
                "pct_vs_ema89d":    daily_data.get("pct_vs_ema89d", 0),
                "vol_ratio_d":      daily_data.get("vol_ratio_d", 0),
                "daily_entry_note": daily_data.get("daily_entry_note", ""),
                "dual_confirmed":   (daily_data.get("daily_ok", False)
                                     and weekly_cross in ("ABOVE", "CROSSING")),
            })

        # ── Market Structure ─────────────────────────────────────────────────
        try:
            # Pakai daily data untuk MS kalau tersedia, otherwise weekly
            ms_df   = df_d if (df_d is not None and len(df_d) >= 30) else df
            close_s = ms_df["Close"]
            ema13_s = close_s.ewm(span=13, adjust=False).mean()
            ema89_s = close_s.ewm(span=89, adjust=False).mean()
            ms = analyze_market_structure(
                close        = close_s,
                high         = ms_df["High"],
                low          = ms_df["Low"],
                vol          = ms_df["Volume"],
                ema13        = float(r.get("ema13") or 0),
                ema89        = float(r.get("ema89") or 0),
                ema13_series = ema13_s,
                ema89_series = ema89_s,
            )
            r.update(ms)
            boost      = ms.get("ms_conviction_boost", 0)
            score_pre  = r.get("score", 0)
            score_post = max(0, min(8, score_pre + boost))
            r["score"] = score_post

            # [SA-1 FIX] Flag jika MS penalty drop signal yang sudah lolos filter.
            # Tanpa flag ini, saham bisa hilang dari hasil scan secara silent —
            # score turun di bawah 3 setelah filter score >= 3 sudah lewat.
            # Solusi: jangan drop dari hasil, tapi flag agar user sadar.
            if boost < 0 and score_post < 3:
                flags = r.get("flags", [])
                flags.append(
                    f"⚠ MS penalty {boost:+d} → score {score_pre}→{score_post} "
                    f"(struktur: {ms.get('ms_structure','?')})"
                )
                r["flags"] = flags
                # Pertahankan signal tapi downgrade ke WATCHLIST
                if r.get("signal") in ("BREAKOUT", "STRONG_BREAKOUT"):
                    r["signal"] = "WATCHLIST"
                    flags.append("MS downgrade → WATCHLIST")
        except Exception as exc:
            logger.debug(f"[Scanner] {ticker} MS boost: {exc}")

        # ── MCF ──────────────────────────────────────────────────────────────
        regime_tag = r.get("regime_tag", "FULL")
        try:
            _df = df_d if (df_d is not None and len(df_d) >= 14) else df
            mcf = compute_mcf(
                close          = _df["Close"],
                high           = _df["High"],
                low            = _df["Low"],
                volume         = _df["Volume"],
                open_          = _df["Open"] if "Open" in _df.columns else None,
                market_bullish = self._mkt_bull,
                regime_tag     = regime_tag,
            )
            r.update(mcf)
            r["mcf_bear_blocked"] = mcf.get("mcf_bear_blocked", False)
        except Exception as exc:
            logger.debug(f"[Scanner] {ticker} MCF: {exc}")

        # ── Signal log to DB ─────────────────────────────────────────────────
        try:
            import sqlite3
            conn = sqlite3.connect(str(LOGS_DIR / "trade_log.db"))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker      TEXT,
                    signal      TEXT,
                    score       INTEGER,
                    regime_tag  TEXT,
                    mcf_score   INTEGER,
                    mcf_label   TEXT,
                    mcf_blocked INTEGER,
                    risk_pct    REAL,
                    vp_score    INTEGER,
                    vp_zone     TEXT,
                    logged_at   TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                INSERT INTO signals
                (ticker, signal, score, regime_tag, mcf_score, mcf_label,
                 mcf_blocked, risk_pct, vp_score, vp_zone)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                r.get("ticker", ""),   r.get("signal", ""),
                r.get("score", 0),     r.get("regime_tag", ""),
                r.get("mcf_score", 0), r.get("mcf_label", ""),
                1 if r.get("mcf_bear_blocked") else 0,
                r.get("risk_pct", 0),
                r.get("vp_score", 0),  r.get("vp_entry_zone", ""),
            ))
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.debug(f"[Scanner] {ticker} DB log: {exc}")

        return r

    def daily_scan(self, mode: str = "full") -> list:
        regime_data  = get_ihsg_regime()
        cycle        = regime_data.get("cycle", "UNKNOWN")
        ihsg_bullish = cycle in (
            "BULL_STRONG", "BULL_TREND", "BULL_CONSOLIDATION", "TRANSITION"
        )
        self._mkt_bull = ihsg_bullish

        universe = get_dynamic_universe() if mode == "full" else get_idx_universe(mode)
        logger.info(f"[Scanner] Regime: {cycle} | Universe: {len(universe)} | Bull: {ihsg_bullish}")

        logger.info("[Scanner] Fetching weekly data (3y)...")
        weekly_batch = self.feed.fetch_batch(universe, max_workers=8)
        self._cache  = {k: _flatten_multiindex(v) for k, v in weekly_batch.items()}

        logger.info("[Scanner] Fetching daily data (60d)...")
        daily_batch   = self.feed_d.fetch_batch(universe, max_workers=8)
        self._cache_d = {k: _flatten_multiindex(v) for k, v in daily_batch.items()}

        results: list = []
        with ThreadPoolExecutor(max_workers=12) as exe:
            fut_map = {exe.submit(self._scan_ticker, t, cycle): t for t in universe}
            for fut in as_completed(fut_map):
                try:
                    r = fut.result()
                    if r is not None:
                        results.append(r)
                except Exception as exc:
                    logger.debug(f"[Scanner] {fut_map[fut]}: {exc}")

        # Sort: STRONG_BREAKOUT → BREAKOUT → WATCHLIST → score desc
        _sig_rank = {"STRONG_BREAKOUT": 0, "BREAKOUT": 1, "WATCHLIST": 2}
        results.sort(key=lambda x: (
            _sig_rank.get(x.get("signal", ""), 3),
            -x.get("score", 0),
        ))

        self.save_results(results, regime_data)

        n_strong  = sum(1 for r in results if r.get("signal") == "STRONG_BREAKOUT")
        n_bo      = sum(1 for r in results if r.get("signal") == "BREAKOUT")
        n_blocked = sum(1 for r in results if r.get("mcf_bear_blocked"))
        logger.info(
            f"[Scanner] Done: {len(results)} setups | "
            f"{n_strong} STRONG_BO | {n_bo} BREAKOUT | "
            f"{n_blocked} MCF bear-blocked | Regime: {cycle}"
        )
        return results

    def save_results(self, results: list, regime: dict) -> None:
        results_file = LOGS_DIR / "daily_results.json"
        try:
            existing: dict = {}
            if results_file.exists():
                try:
                    existing = json.loads(results_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            existing["regime"]      = regime
            existing["date"]        = datetime.now().strftime("%Y-%m-%d")
            existing["ema_total"]   = len(results)
            existing["ema_results"] = results
            results_file.write_text(
                json.dumps(existing, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error(f"[Scanner] save_results: {exc}")
