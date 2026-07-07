"""
Simple Trading V9 — Flow Scanner Agent
=======================================
Scans for money flow using:
- Primary: Stockbit broker net buy (via OwnershipAgent token)
- Fallback: Yahoo Finance volume + price momentum proxy

Signal classification:
  WHALE_ACCUMULATION  — Smart money net buy (SQ/MG/YU/BK dominant)
  INSTITUTIONAL_BUY   — Local/foreign institutional accumulation
  RETAIL_MOMENTUM     — Retail-driven volume spike (no whale filter)
  DISTRIBUTION        — Net selling pressure detected
  NEUTRAL             — Mixed / inconclusive flow
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# Broker type → flow classification
_SMART_BROKERS  = {"SQ","MG","BK","AK","CC","NI","OD","YU","GR","MS","CS","KZ","LG","BB"}
_RETAIL_BROKERS = {"YP","ZP","XA","DX","FZ","KI","AZ"}

# Minimum net buy lot to qualify as signal
_MIN_NET_LOT_SMART   = 50
_MIN_NET_LOT_RETAIL  = 200
_MIN_VOLUME_PROXY    = 1_500_000   # fallback: min daily volume for retail proxy

def _classify_broker_flow(broker_data: dict) -> dict:
    """
    Classify flow from OwnershipAgent broker summary.
    Returns: {signal, smart_net, retail_net, dominant_type, note}
    """
    top_buyers  = broker_data.get("top_buyers", [])
    top_sellers = broker_data.get("top_sellers", [])

    smart_buy_lot  = sum(b["buy_lot"]  for b in top_buyers  if b.get("signal") == "SMART")
    smart_sell_lot = sum(b["sell_lot"] for b in top_sellers if b.get("signal") == "SMART")
    retail_buy_lot = sum(b["buy_lot"]  for b in top_buyers  if b.get("signal") == "RETAIL")

    smart_net  = smart_buy_lot  - smart_sell_lot
    retail_net = retail_buy_lot

    dominant = broker_data.get("dominant_buyer", {})
    dom_type  = dominant.get("type", "UNKNOWN")

    if smart_net >= _MIN_NET_LOT_SMART:
        if dom_type in ("OWNER_PROXY", "MARKET_MAKER"):
            signal = "WHALE_ACCUMULATION"
            note   = f"Smart money net buy {smart_net:,} lot — {dominant.get('code','?')} dominant"
        else:
            signal = "INSTITUTIONAL_BUY"
            note   = f"Institutional net buy {smart_net:,} lot"
    elif smart_net < -_MIN_NET_LOT_SMART:
        signal = "DISTRIBUTION"
        note   = f"Smart money net sell {abs(smart_net):,} lot"
    elif retail_net >= _MIN_NET_LOT_RETAIL and smart_net >= -10:
        signal = "RETAIL_MOMENTUM"
        note   = f"Retail buying {retail_net:,} lot, smart money neutral"
    else:
        signal = "NEUTRAL"
        note   = "Mixed or inconclusive flow"

    return {
        "signal":       signal,
        "smart_net":    smart_net,
        "retail_net":   retail_net,
        "dominant_type": dom_type,
        "note":         note,
        "source":       "stockbit",
    }


def _proxy_flow_from_ohlcv(df, ticker: str) -> dict:
    """
    Proxy flow classification using OHLCV only (no broker data).\n    v9.8.8: label proxy DIBEDAKAN dari label broker-mode — klasifikasi satu bar\n    tidak boleh memakai nama identitas aktor (INSTITUTIONAL_BUY dst).\n    ABSORPTION_HINT / MOMENTUM_SPIKE / SELLING_PRESSURE = deskripsi perilaku\n    harga-volume, bukan klaim siapa pelakunya.
    Uses: volume spike + close position + price change.
    """
    try:
        import pandas as pd
        last    = df.iloc[-1]
        prev    = df.iloc[-2] if len(df) > 1 else last

        vol     = float(last.get("Volume", 0))
        vol_avg = float(df["Volume"].tail(20).mean()) if len(df) >= 20 else vol
        close   = float(last.get("Close", 0))
        open_   = float(last.get("Open",  close))
        high    = float(last.get("High",  close))
        low     = float(last.get("Low",   close))

        pct_chg = (close - float(prev.get("Close", close))) / max(float(prev.get("Close", close)), 1) * 100
        vol_ratio = vol / max(vol_avg, 1)

        # Close position in range (0=low, 1=high)
        rng = high - low
        close_pos = (close - low) / max(rng, 1)

        if vol_ratio >= 2.5 and pct_chg >= 2.0 and close_pos >= 0.7:
            signal = "MOMENTUM_SPIKE"
            note   = f"Vol {vol_ratio:.1f}x avg, +{pct_chg:.1f}%, close near high"
        elif vol_ratio >= 1.5 and pct_chg >= 1.0 and close_pos >= 0.6:
            signal = "MOMENTUM_SPIKE"
            note   = f"Vol {vol_ratio:.1f}x avg, +{pct_chg:.1f}%"
        elif vol_ratio >= 2.0 and pct_chg <= -2.0 and close_pos <= 0.3:
            signal = "SELLING_PRESSURE"
            note   = f"Vol {vol_ratio:.1f}x avg, {pct_chg:.1f}%, close near low"
        elif vol_ratio >= 1.5 and abs(pct_chg) < 0.5 and close_pos >= 0.5:
            signal = "ABSORPTION_HINT"
            note   = f"High vol {vol_ratio:.1f}x, tight range — absorption?"
        else:
            signal = "NEUTRAL"
            note   = f"Vol {vol_ratio:.1f}x avg, {pct_chg:.1f}%"

        return {
            "signal":    signal,
            "smart_net": None,
            "retail_net": None,
            "dominant_type": "UNKNOWN",
            "note":      note,
            "source":    "proxy_ohlcv",
            "vol_ratio": round(vol_ratio, 2),
            "pct_chg":   round(pct_chg, 2),
            "close_pos": round(close_pos, 2),
        }
    except Exception as e:
        logger.debug(f"[FlowScanner] proxy_flow error {ticker}: {e}")
        return {"signal": "NEUTRAL", "note": str(e), "source": "proxy_ohlcv"}


class FlowScanner:
    """
    Scan universe for money flow signals.
    Uses Stockbit broker data when token available, OHLCV proxy otherwise.
    """

    def __init__(self):
        self._ownership: Optional[Any] = None
        self._data_feed = None

    def _get_ownership(self):
        if self._ownership is None:
            try:
                from agents.ownership_agent import OwnershipAgent
                self._ownership = OwnershipAgent()
            except Exception as e:
                logger.warning(f"[FlowScanner] OwnershipAgent unavailable: {e}")
        return self._ownership

    def _get_feed(self):
        if self._data_feed is None:
            from core.data_feed import DataFeed
            self._data_feed = DataFeed(period="60d", interval="1d")
        return self._data_feed

    def scan_ticker(self, ticker: str) -> Optional[dict]:
        """
        Scan single ticker — OHLCV proxy first (fast, always works).
        Stockbit broker data diambil via enrich_top_results() setelah scan selesai,
        bukan di sini (menghindari SSL timeout per-ticker).
        """
        t = ticker.replace(".JK", "").upper()
        try:
            df = self._get_feed().fetch(ticker, interval="1d")
            if df is None or len(df) < 2:
                return None

            flow = _proxy_flow_from_ohlcv(df, t)
            flow["ticker"]    = t
            flow["price"]     = float(df["Close"].iloc[-1])
            flow["pct_chg"]   = flow.get("pct_chg", 0.0)
            flow["vol_ratio"] = flow.get("vol_ratio", 1.0)
            flow["source"]    = "proxy_ohlcv"

            # Check Stockbit cache (CACHE ONLY — tidak trigger network call baru)
            oa = self._get_ownership()
            if oa:
                cache_key = f"sb_{t}"
                cached_sb  = oa._broker_cache.get(cache_key, {})
                if cached_sb.get("available"):
                    broker_flow = _classify_broker_flow(cached_sb)
                    flow["signal"]      = broker_flow.get("signal", flow["signal"])
                    flow["smart_net"]   = broker_flow.get("smart_net")
                    flow["retail_net"]  = broker_flow.get("retail_net")
                    flow["dominant_type"] = broker_flow.get("dominant_type","")
                    flow["note"]        = broker_flow.get("note", flow.get("note",""))
                    flow["source"]      = "stockbit"

            return flow

        except Exception as e:
            logger.debug(f"[FlowScanner] {t}: {e}")
            return None

    def scan(
        self,
        tickers:     Optional[List[str]] = None,
        max_workers: int = 5,   # Stockbit throttles burst — keep low
        min_signal:  Optional[str] = None,   # filter: only return this signal type
    ) -> List[dict]:
        """
        Scan list of tickers for money flow.
        Returns sorted list: WHALE_ACCUMULATION → INSTITUTIONAL → RETAIL → NEUTRAL → DISTRIBUTION
        """
        from core.data_feed import get_dynamic_universe
        tickers = tickers or [t + ".JK" for t in get_dynamic_universe()]

        logger.info(f"[FlowScanner] Scanning {len(tickers)} tickers...")
        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as exe:
            futures = {exe.submit(self.scan_ticker, t): t for t in tickers}
            for fut in as_completed(futures):
                r = fut.result()
                if r is not None:
                    results.append(r)

        # Sort by signal priority
        _rank = {
            "WHALE_ACCUMULATION": 0,
            "INSTITUTIONAL_BUY":  1,
            "ABSORPTION_HINT":    1,   # proxy-mode (v9.8.8)
            "RETAIL_MOMENTUM":    2,
            "MOMENTUM_SPIKE":     2,   # proxy-mode (v9.8.8)
            "NEUTRAL":            3,
            "DISTRIBUTION":       4,
            "SELLING_PRESSURE":   4,   # proxy-mode (v9.8.8)
        }
        results.sort(key=lambda x: (
            _rank.get(x.get("signal", "NEUTRAL"), 3),
            -(x.get("vol_ratio") or 1.0),
        ))

        # v9.8.8: rekam SEMUA hasil flow ke feedback loop sebelum filter
        try:
            from agents.scan_logger import log_flow_results
            log_flow_results(results)
        except Exception as _fe:
            logger.error(f"[FlowScanner] flow log gagal: {_fe}")

        if min_signal:
            results = [r for r in results if r.get("signal") == min_signal]

        logger.info(f"[FlowScanner] Done: {len(results)} results")
        return results
