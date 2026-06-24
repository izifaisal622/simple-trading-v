"""
Simple Trading V9 — Ownership Agent
=====================================
Phase 1: yfinance major_holders (free, quarterly)
Phase 2: Static broker profiles (manual enrichment)
Phase 3: Stockbit JWT broker summary (daily, free account)
Phase 4: Playwright auto-refresh token

Usage:
    from agents.ownership_agent import OwnershipAgent
    agent = OwnershipAgent()
    data = agent.get_ownership("MBSS.JK")
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

logger = logging.getLogger(__name__)

BASE_DIR    = Path(__file__).parent.parent
DATA_DIR    = BASE_DIR / "data"
LOGS_DIR    = BASE_DIR / "logs"
CONFIG_DIR  = BASE_DIR / "config"
DATA_DIR.mkdir(exist_ok=True)

OWNERSHIP_CACHE = DATA_DIR / "ownership_cache.json"
BROKER_PROFILES = DATA_DIR / "broker_profiles.json"
STOCKBIT_TOKEN  = DATA_DIR / "stockbit_token.json"
BROKER_CACHE    = DATA_DIR / "broker_summary_cache.json"

# ── Broker classification (Hengky's framework) ────────────────────────────────
BROKER_PROFILES_DEFAULT = {
    # Smart Money / Institusi besar
    "SQ": {"name": "BCA Sekuritas",      "type": "OWNER_PROXY",   "signal": "SMART",   "note": "Sering dipakai owner/emiten akumulasi"},
    "MG": {"name": "Semesta Indovest",   "type": "MARKET_MAKER",  "signal": "SMART",   "note": "Market maker besar, sering ikut bandar"},
    "BK": {"name": "JP Morgan",          "type": "FOREIGN_INST",  "signal": "SMART",   "note": "Asing institusional, directional"},
    "AK": {"name": "UBS",                "type": "FOREIGN_INST",  "signal": "SMART",   "note": "Asing institusional"},
    "CC": {"name": "Mandiri Sekuritas",  "type": "LOCAL_INST",    "signal": "SMART",   "note": "Dana kelolaan lokal besar"},
    "NI": {"name": "BNI Sekuritas",      "type": "LOCAL_INST",    "signal": "SMART",   "note": "Dana kelolaan lokal"},
    "OD": {"name": "Danareksa",          "type": "LOCAL_INST",    "signal": "SMART",   "note": "Dana kelolaan lokal"},
    "YU": {"name": "CLSA",              "type": "FOREIGN_INST",  "signal": "SMART",   "note": "Foreign institutional"},
    "GR": {"name": "Trimegah",           "type": "LOCAL_INST",    "signal": "SMART",   "note": "Local institutional"},
    "MS": {"name": "Morgan Stanley",     "type": "FOREIGN_INST",  "signal": "SMART",   "note": "Asing institusional"},
    "CS": {"name": "Credit Suisse",      "type": "FOREIGN_INST",  "signal": "SMART",   "note": "Asing institusional"},
    "KZ": {"name": "CIMB Sekuritas",     "type": "FOREIGN_INST",  "signal": "SMART",   "note": "Regional institutional"},
    "LG": {"name": "Bahana",             "type": "LOCAL_INST",    "signal": "SMART",   "note": "Local institutional"},
    "TP": {"name": "Sinarmas Sekuritas", "type": "LOCAL_INST",    "signal": "NEUTRAL", "note": "Mixed — kadang retail, kadang institusi"},
    "EP": {"name": "RHB Sekuritas",      "type": "LOCAL_INST",    "signal": "NEUTRAL", "note": "Local mixed"},
    "DR": {"name": "OSO Sekuritas",      "type": "GORENGAN",      "signal": "CAUTION", "note": "Sering terlibat pump & dump"},
    "BZ": {"name": "Profindo",           "type": "GORENGAN",      "signal": "CAUTION", "note": "Hati-hati"},
    # Retail
    "YP": {"name": "Indo Premier (IPOT)","type": "RETAIL",        "signal": "RETAIL",  "note": "Platform retail terbesar"},
    "ZP": {"name": "Kim Eng (Maybank)",  "type": "RETAIL",        "signal": "RETAIL",  "note": "Sering retail, contrarian signal"},
    "XA": {"name": "Henan Putihrai",     "type": "RETAIL",        "signal": "RETAIL",  "note": "Retail"},
    "DX": {"name": "Phillip Sekuritas",  "type": "RETAIL",        "signal": "RETAIL",  "note": "Retail, sering late"},
    "FZ": {"name": "Waterfront",         "type": "RETAIL",        "signal": "RETAIL",  "note": "Retail"},
    "KI": {"name": "Ciptadana",          "type": "RETAIL",        "signal": "RETAIL",  "note": "Retail"},
    "AZ": {"name": "Sucorinvest",        "type": "RETAIL",        "signal": "RETAIL",  "note": "Retail"},
    # Market Maker
    "RX": {"name": "Macquarie",          "type": "MARKET_MAKER",  "signal": "NEUTRAL", "note": "Market maker, sering di kedua sisi"},
    "PD": {"name": "Indo Mirae Asset",   "type": "MARKET_MAKER",  "signal": "NEUTRAL", "note": "Market maker"},
    "IF": {"name": "Samuel Sekuritas",   "type": "MARKET_MAKER",  "signal": "NEUTRAL", "note": "Mixed"},
    "BB": {"name": "Deutsche",           "type": "FOREIGN_INST",  "signal": "SMART",   "note": "Asing institusional"},
}

# Per-saham broker profile (known historical patterns)
KNOWN_OWNER_BROKERS = {
    "MBSS": {"owner_broker": "SQ", "owner_name": "PT Mitrabahtera", "confidence": "HIGH"},
    # "UNIC": removed — Unggul Indah Cahaya, owner broker belum terverifikasi
    "BREN": {"owner_broker": "MG", "owner_name": "Barito Renewables", "confidence": "MEDIUM"},
    "CUAN": {"owner_broker": "SQ", "owner_name": "Petrindo Jaya Kreasi", "confidence": "MEDIUM"},
    "PGAS": {"owner_broker": "CC", "owner_name": "PGN (BUMN)", "confidence": "HIGH"},
    "BBCA": {"owner_broker": "BK", "owner_name": "Hartono Family/Djarum", "confidence": "HIGH"},
    "BBRI": {"owner_broker": "CC", "owner_name": "Pemerintah RI", "confidence": "HIGH"},
    "TLKM": {"owner_broker": "CC", "owner_name": "Pemerintah RI (Telkom)", "confidence": "HIGH"},
    "ANTM": {"owner_broker": "NI", "owner_name": "BUMN (MIND ID)", "confidence": "HIGH"},
    "TPIA": {"owner_broker": "SQ", "owner_name": "Prajogo Pangestu", "confidence": "HIGH"},    "AMMN": {"owner_broker": "SQ", "owner_name": "Amman Mineral", "confidence": "MEDIUM"},
    "INTP": {"owner_broker": "BK", "owner_name": "Birchwood Omnia/HeidelbergCement", "confidence": "HIGH"},
    "ASII": {"owner_broker": "GR", "owner_name": "Jardine Matheson", "confidence": "HIGH"},
    "HMSP": {"owner_broker": "BK", "owner_name": "Philip Morris International", "confidence": "HIGH"},
    "UNVR": {"owner_broker": "YU", "owner_name": "Unilever PLC", "confidence": "HIGH"},
}


class OwnershipAgent:
    """
    Multi-phase ownership & broker data agent.
    Falls back gracefully when higher phases not available.
    """

    def __init__(self):
        self._ownership_cache: dict = {}
        self._broker_cache: dict    = {}
        self._load_caches()

    def _load_caches(self):
        if OWNERSHIP_CACHE.exists():
            try: self._ownership_cache = json.loads(OWNERSHIP_CACHE.read_text())
            except: pass
        if BROKER_CACHE.exists():
            try: self._broker_cache = json.loads(BROKER_CACHE.read_text())
            except: pass

    def _save_caches(self):
        OWNERSHIP_CACHE.write_text(json.dumps(self._ownership_cache, indent=2, default=str))
        BROKER_CACHE.write_text(json.dumps(self._broker_cache, indent=2, default=str))

    # ── PHASE 1: yfinance major_holders ──────────────────────────────────────

    def get_yfinance_ownership(self, ticker: str) -> dict:
        """Phase 1: Get ownership data from yfinance (quarterly, free)."""
        t = ticker.replace(".JK","")
        cache_key = f"yf_{t}"

        # Cache valid for 7 days (quarterly data doesn't change often)
        if cache_key in self._ownership_cache:
            cached = self._ownership_cache[cache_key]
            age_days = (datetime.now() - datetime.fromisoformat(cached.get("_fetched","2000-01-01"))).days
            if age_days < 7:
                return cached

        try:
            import yfinance as yf
            import time as _time

            # Retry 3x dengan backoff — Yahoo 401 Invalid Crumb butuh jeda
            stock = None
            for _attempt in range(3):
                try:
                    stock = yf.Ticker(f"{t}.JK")
                    # test akses — kalau crumb expired ini raise 401
                    _test = stock.fast_info
                    break
                except Exception as _e:
                    if "401" in str(_e) or "Crumb" in str(_e) or "Unauthorized" in str(_e):
                        if _attempt < 2:
                            _time.sleep(2 ** _attempt)  # 1s, 2s
                            continue
                    break  # error lain, langsung skip
            if stock is None:
                raise Exception("yfinance session expired (401)")

            # major_holders: DataFrame with pct rows
            mh = stock.major_holders
            pct_insider  = 0.0
            pct_inst     = 0.0
            if mh is not None and not mh.empty:
                for _, row in mh.iterrows():
                    val = str(row.iloc[0]).replace("%","").strip()
                    lbl = str(row.iloc[1]).lower()
                    try:
                        v = float(val)
                        if "insider" in lbl:      pct_insider = v
                        if "institution" in lbl:  pct_inst    = v
                    except: pass

            # institutional_holders: top institutions
            ih   = stock.institutional_holders
            tops = []
            if ih is not None and not ih.empty:
                for _, row in ih.head(5).iterrows():
                    try:
                        name  = str(row.get("Holder", row.iloc[0]))
                        pct   = float(row.get("% Out", row.get("pctHeld", 0))) * 100
                        tops.append({"name": name, "pct": round(pct, 2)})
                    except: pass

            free_float = max(0, 100 - pct_insider - pct_inst)

            result = {
                "ticker":       t,
                "pct_insider":  round(pct_insider, 1),
                "pct_inst":     round(pct_inst, 1),
                "free_float":   round(free_float, 1),
                "top_holders":  tops,
                "source":       "yfinance",
                "_fetched":     datetime.now().isoformat(),
            }
            self._ownership_cache[cache_key] = result
            self._save_caches()
            return result

        except Exception as e:
            logger.debug(f"[Ownership] yfinance {t}: {e}")
            return {"ticker": t, "pct_insider": 0, "free_float": 100,
                    "top_holders": [], "source": "error"}

    # ── PHASE 2: Static broker profiles ──────────────────────────────────────

    def get_static_broker_profile(self, ticker: str) -> dict:
        """Phase 2: Known owner broker from static database."""
        t = ticker.replace(".JK","")

        # Check custom profiles file first
        if BROKER_PROFILES.exists():
            try:
                custom = json.loads(BROKER_PROFILES.read_text())
                if t in custom:
                    return custom[t]
            except: pass

        # Fall back to built-in known profiles
        if t in KNOWN_OWNER_BROKERS:
            profile = KNOWN_OWNER_BROKERS[t].copy()
            broker_code = profile["owner_broker"]
            broker_info = BROKER_PROFILES_DEFAULT.get(broker_code, {})
            profile["broker_name"]   = broker_info.get("name", broker_code)
            profile["broker_type"]   = broker_info.get("type", "UNKNOWN")
            profile["broker_signal"] = broker_info.get("signal", "NEUTRAL")
            profile["broker_note"]   = broker_info.get("note", "")
            return profile

        return {}

    def add_broker_profile(self, ticker: str, owner_broker: str,
                           owner_name: str, notes: str = ""):
        """Phase 2: Add/update broker profile for a ticker."""
        t = ticker.replace(".JK","")
        profiles = {}
        if BROKER_PROFILES.exists():
            try: profiles = json.loads(BROKER_PROFILES.read_text())
            except: pass
        profiles[t] = {
            "owner_broker": owner_broker,
            "owner_name":   owner_name,
            "confidence":   "USER",
            "notes":        notes,
            "updated":      datetime.now().isoformat(),
        }
        BROKER_PROFILES.write_text(json.dumps(profiles, indent=2))
        logger.info(f"[Ownership] Added broker profile: {t} → {owner_broker}")

    # ── PHASE 3: Stockbit broker summary ──────────────────────────────────────

    def get_stockbit_token(self) -> Optional[str]:
        """Phase 3: Load Stockbit JWT token."""
        if STOCKBIT_TOKEN.exists():
            try:
                data = json.loads(STOCKBIT_TOKEN.read_text())
                token = data.get("token","")
                saved = datetime.fromisoformat(data.get("saved_at","2000-01-01"))
                age_hours = (datetime.now() - saved).total_seconds() / 3600
                if age_hours < 23 and token:
                    return token
                else:
                    logger.info("[Stockbit] Token expired (>23h)")
            except: pass
        return None

    def save_stockbit_token(self, token: str):
        """Phase 3: Save Stockbit JWT token."""
        DATA_DIR.mkdir(exist_ok=True)
        STOCKBIT_TOKEN.write_text(json.dumps({
            "token":    token,
            "saved_at": datetime.now().isoformat(),
        }, indent=2))
        logger.info("[Stockbit] Token saved")

    def get_broker_summary_stockbit(self, ticker: str, days: int = 10) -> dict:
        """
        Fetch Stockbit broker summary for a single ticker.
        NON-BLOCKING: skip immediately if no token.
        Called ONLY from enrich_top_results() — never during main scan loop.
        """
        token = self.get_stockbit_token()
        if not token:
            return {"available": False, "reason": "No token"}

        t         = ticker.replace(".JK","")
        cache_key = f"sb_{t}"

        # Cache valid 6 hours — no re-fetch within same session
        if cache_key in self._broker_cache:
            cached  = self._broker_cache[cache_key]
            age_hrs = (datetime.now() - datetime.fromisoformat(
                       cached.get("_fetched","2000-01-01"))).total_seconds() / 3600
            if age_hrs < 6:
                return cached

        try:
            import requests
            url     = f"https://exodus.stockbit.com/broker-summary/{t}"
            headers = {
                "Authorization":   f"Bearer {token}",
                "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept":          "application/json, text/plain, */*",
                "Referer":         "https://stockbit.com/",
                "Origin":          "https://stockbit.com",
            }
            r = requests.get(url, headers=headers, timeout=8)
            if r.status_code == 401:
                return {"available": False, "reason": "Token expired"}
            if r.status_code != 200:
                return {"available": False, "reason": f"HTTP {r.status_code}"}

            result = self._parse_stockbit_broker(t, r.json())
            result["_fetched"] = datetime.now().isoformat()
            self._broker_cache[cache_key] = result
            self._save_caches()
            return result

        except Exception as e:
            logger.debug(f"[Stockbit] {t}: {e}")
            return {"available": False, "reason": str(e)}

    def enrich_top_results(self, results: list, top_n: int = 50,
                            min_conviction: int = 4) -> list:
        """
        Enrichment pass: fetch Stockbit broker data untuk top-N hasil scan.
        SEQUENTIAL + THROTTLED (1 req/detik) — dipanggil setelah scan selesai.
        Hanya jalan kalau token ada. Aman untuk skip kalau token tidak ada.

        V5 fix: top_n dinaikkan 15→50, tambah min_conviction filter.
        Sebelumnya circular dependency — ticker dengan conviction rendah (karena
        missing owner broker data) tidak di-enrich, padahal enrich itulah yang
        bisa naikkan conviction-nya. Fix: enrich semua ticker di atas threshold
        conviction minimum, bukan hanya top 15 saja.

        Args:
            results:        list of whale/scan result dicts, sorted by conviction
            top_n:          max tickers yang di-enrich (default 50)
            min_conviction: skip ticker dengan conviction < threshold (default 4)
        Returns:
            results yang sama, dengan broker_live=True + top_buyers/sellers
            untuk ticker yang berhasil di-fetch
        """
        import time

        token = self.get_stockbit_token()
        if not token:
            logger.debug("[Enrich] No token — skip Stockbit enrichment")
            return results

        # Filter: hanya enrich ticker dengan conviction >= min_conviction
        # Sort by conviction descending, ambil top_n
        eligible   = [r for r in results if r.get("conviction", 0) >= min_conviction]
        sorted_res = sorted(eligible, key=lambda x: x.get("conviction", 0), reverse=True)
        to_enrich  = sorted_res[:top_n]
        ticker_set = {r.get("ticker","").replace(".JK","") for r in to_enrich}

        logger.info(f"[Enrich] Stockbit enrichment: {len(ticker_set)} tickers "                    f"(conviction>={min_conviction}, top {top_n})")

        enriched = 0
        for i, r in enumerate(results):
            t = r.get("ticker","").replace(".JK","")
            if t not in ticker_set:
                continue
            if r.get("broker_live"):
                continue  # sudah ada dari cache

            sb = self.get_broker_summary_stockbit(t)
            if sb.get("available"):
                r["broker_live"]    = True
                r["top_buyers"]     = sb.get("top_buyers", [])
                r["top_sellers"]    = sb.get("top_sellers", [])
                r["smart_buy_pct"]  = sb.get("smart_buy_pct", 0)
                r["bandar_signal"]  = sb.get("bandar_signal", "")
                r["dominant_buyer"] = sb.get("dominant_buyer", {})
                enriched += 1
                logger.debug(f"[Enrich] {t} ✓")

                # FIX: re-compute conviction + whale_quality setelah broker data masuk
                # compute_conviction dan classify_whale_quality membaca broker_live
                # dari result dict — tapi conviction sudah final saat scan.
                # Tanpa re-compute, broker live boost tidak pernah teraplikasi.
                try:
                    from agents.whale_scanner import compute_conviction, classify_whale_quality
                    _vol_ratio = r.get("ff_adj_vol_ratio", r.get("vol_ratio", 1.0))
                    _new_conv  = compute_conviction(r, _vol_ratio)
                    # Re-apply supply freedom cap (konsisten dengan _analyze_ticker)
                    _ff   = r.get("free_float", 100)
                    _ctrl = r.get("control_score", 0)
                    if _ff > 60 and _ctrl <= 3:
                        _new_conv = min(_new_conv, 7)
                    r["conviction"]    = max(0, min(10, _new_conv))
                    r["whale_quality"] = classify_whale_quality(r)
                except Exception as _ce:
                    logger.debug(f"[Enrich] {t} re-compute failed: {_ce}")
            else:
                logger.debug(f"[Enrich] {t} skip: {sb.get('reason','')}")

            # Throttle: 1 req/detik, jangan burst
            if i < len(ticker_set) - 1:
                time.sleep(1.1)

        logger.info(f"[Enrich] Done: {enriched}/{len(ticker_set)} enriched")
        return results

    def _parse_stockbit_broker(self, ticker: str, raw: dict) -> dict:
        """Parse Stockbit broker summary response."""
        try:
            data = raw.get("data", raw)
            buyers  = []
            sellers = []

            # Stockbit returns list of broker transactions
            for item in data if isinstance(data, list) else []:
                code    = item.get("broker_code","?")
                buy_lot = int(item.get("buy_lot", 0))
                sel_lot = int(item.get("sell_lot", 0))
                net_lot = buy_lot - sel_lot
                buy_val = float(item.get("buy_value", 0)) / 1e9
                sel_val = float(item.get("sell_value", 0)) / 1e9

                broker_info = BROKER_PROFILES_DEFAULT.get(code, {})
                entry = {
                    "code":     code,
                    "name":     broker_info.get("name", code),
                    "type":     broker_info.get("type", "UNKNOWN"),
                    "signal":   broker_info.get("signal", "NEUTRAL"),
                    "buy_lot":  buy_lot,
                    "sell_lot": sel_lot,
                    "net_lot":  net_lot,
                    "buy_val":  round(buy_val, 2),
                    "sell_val": round(sel_val, 2),
                }
                if net_lot > 0:   buyers.append(entry)
                elif net_lot < 0: sellers.append(entry)

            buyers.sort(key=lambda x: -x["buy_lot"])
            sellers.sort(key=lambda x: x["net_lot"])

            # Smart money analysis
            smart_buy  = sum(e["buy_lot"]  for e in buyers  if e["signal"]=="SMART")
            _ = sum(e["sell_lot"] for e in sellers if e["signal"]=="SMART")
            retail_sell= sum(e["sell_lot"] for e in sellers if e["signal"]=="RETAIL")

            total_buy = sum(e["buy_lot"] for e in buyers)
            smart_pct = smart_buy / total_buy * 100 if total_buy > 0 else 0

            # Dominant buyer
            dominant = buyers[0] if buyers else {}
            dom_signal = "ACCUMULATION" if dominant.get("signal")=="SMART" else "NEUTRAL"

            return {
                "ticker":       ticker,
                "available":    True,
                "top_buyers":   buyers[:5],
                "top_sellers":  sellers[:5],
                "dominant_buyer": dominant,
                "smart_buy_pct": round(smart_pct, 1),
                "smart_buy_lot": smart_buy,
                "retail_sell_lot": retail_sell,
                "bandar_signal": dom_signal,
                "source":       "stockbit",
            }
        except Exception as e:
            return {"available": False, "reason": f"Parse error: {e}"}

    # ── PHASE 4: Playwright auto-refresh ──────────────────────────────────────

    def auto_refresh_stockbit_token(self, username: str, password: str) -> bool:
        """
        Phase 4: Auto-refresh Stockbit token using Playwright headless.
        Requires: pip install playwright && playwright install chromium
        """
        try:
            from playwright.sync_api import sync_playwright  # type: ignore[import]
        except ImportError:
            logger.error("[Stockbit] playwright not installed. Run: pip install playwright && playwright install chromium")
            return False

        logger.info("[Stockbit] Auto-refreshing token via Playwright...")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx     = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()

                # Capture JWT token from network requests
                token_found = []
                def on_request(request):
                    auth = request.headers.get("authorization","")
                    if auth.startswith("Bearer ") and "stockbit" in request.url:
                        token_found.append(auth.replace("Bearer ",""))
                page.on("request", on_request)

                # Login
                page.goto("https://stockbit.com/#/login", wait_until="networkidle")
                page.fill('input[name="username"]', username)
                page.fill('input[name="password"]', password)
                page.click('button[type="submit"]')
                page.wait_for_load_state("networkidle", timeout=15000)

                # Navigate to trigger API calls
                page.goto("https://stockbit.com/#/symbol/BBCA", wait_until="networkidle")
                page.wait_for_timeout(3000)

                browser.close()

                if token_found:
                    self.save_stockbit_token(token_found[-1])
                    logger.info("[Stockbit] Token auto-refreshed successfully")
                    return True
                else:
                    logger.warning("[Stockbit] No token captured — login may have failed")
                    return False

        except Exception as e:
            logger.error(f"[Stockbit] Auto-refresh failed: {e}")
            return False

    # ── COMBINED: get all ownership info ──────────────────────────────────────

    def get_full_ownership(self, ticker: str) -> dict:
        """
        Get all available ownership data for a ticker.
        Priority: Static DB > yfinance > default
        """
        t = ticker.replace(".JK","")
        result = {"ticker": t}

        # Phase 1a: Static free float DB (more accurate for IDX)
        ff_db_path = BASE_DIR / "data" / "free_float_db.json"
        ff_static  = {}
        if ff_db_path.exists():
            try:
                db = json.loads(ff_db_path.read_text())
                if t in db:
                    ff_static = db[t]
            except: pass

        if ff_static:
            result["pct_insider"]  = ff_static.get("insider", 0)
            result["pct_inst"]     = 0
            result["free_float"]   = ff_static.get("ff", 100)
            result["owner_static"] = ff_static.get("owner","")
            result["top_holders"]  = [{"name": ff_static.get("owner",""), "pct": ff_static.get("insider",0)}]
        else:
            # Phase 1b: yfinance fallback
            yf_data = self.get_yfinance_ownership(t)
            result["pct_insider"]  = yf_data.get("pct_insider", 0)
            result["pct_inst"]     = yf_data.get("pct_inst", 0)
            result["free_float"]   = yf_data.get("free_float", 100)
            result["top_holders"]  = yf_data.get("top_holders", [])

        # Phase 2: static broker profile
        bp = self.get_static_broker_profile(t)
        result["owner_broker"]   = bp.get("owner_broker","")
        result["owner_name"]     = bp.get("owner_name","")
        result["broker_name"]    = bp.get("broker_name","")
        result["broker_type"]    = bp.get("broker_type","")
        result["broker_signal"]  = bp.get("broker_signal","")
        result["broker_conf"]    = bp.get("confidence","")

        # Phase 3: Stockbit (if token available)
        sb = self.get_broker_summary_stockbit(t)
        result["broker_live"]    = sb.get("available", False)
        if sb.get("available"):
            result["top_buyers"]     = sb.get("top_buyers",[])
            result["top_sellers"]    = sb.get("top_sellers",[])
            result["smart_buy_pct"]  = sb.get("smart_buy_pct",0)
            result["bandar_signal"]  = sb.get("bandar_signal","")
            result["dominant_buyer"] = sb.get("dominant_buyer",{})

        # Supply concentration score
        ff = result["free_float"]
        if ff <= 10:   supply_ctrl = "SANGAT KETAT"
        elif ff <= 20: supply_ctrl = "KETAT"
        elif ff <= 35: supply_ctrl = "MODERATE"
        else:          supply_ctrl = "BEBAS"

        result["supply_control"] = supply_ctrl
        result["hengky_score"]   = max(0, 10 - int(ff / 10))  # type: ignore[assignment]  # lower float = higher score

        return result

    def batch_get_ownership(self, tickers: list, max_workers: int = 5) -> dict:
        """Batch fetch ownership for multiple tickers."""
        results = {}
        with ThreadPoolExecutor(max_workers=max_workers) as exe:
            futures = {exe.submit(self.get_yfinance_ownership, t): t for t in tickers}
            for future in as_completed(futures):
                t = futures[future]
                try:
                    results[t.replace(".JK","")] = future.result()
                except: pass
        return results


# ── Broker summary formatter for dashboard ────────────────────────────────────

def format_broker_row(broker: dict, is_buy: bool) -> str:
    """Format one broker row for display."""
    code     = broker.get("code","?")
    name     = broker.get("name", code)
    lot      = broker.get("buy_lot" if is_buy else "sell_lot", 0)
    signal   = broker.get("signal","NEUTRAL")
    sig_col  = {"SMART":"#00ff66","RETAIL":"#ef4444",
                "CAUTION":"#fb8c00","NEUTRAL":"#9ca3af"}.get(signal,"#9ca3af")
    bar_len  = min(20, int(lot / 10000)) if lot > 0 else 0
    bar      = "█" * bar_len

    return (f'<span style="color:{sig_col};font-family:Share Tech Mono,monospace;'
            f'font-size:0.65rem"><b>{code}</b> {name[:18]:<18} '
            f'{lot:>10,} lot {bar}</span>')


def get_broker_html(ownership: dict) -> str:
    """Generate broker section HTML for whale card."""
    lines = []

    # Phase 2: static owner broker
    ob = ownership.get("owner_broker","")
    if ob:
        bn   = ownership.get("broker_name", ob)
        bsig = ownership.get("broker_signal","")
        bcon = ownership.get("broker_conf","")
        sig_col = {"SMART":"#00ff66","RETAIL":"#ef4444",
                   "CAUTION":"#fb8c00","NEUTRAL":"#9ca3af"}.get(bsig,"#9ca3af")
        conf_str = f" ({bcon})" if bcon else ""
        lines.append(
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.62rem;'
            f'color:#6b7280">🔑 OWNER BROKER: '
            f'<b style="color:{sig_col}">{ob} — {bn}</b>'
            f'<span style="color:#4b5563;font-size:0.58rem">{conf_str}</span></div>'
        )

    # Phase 1: free float
    ff = ownership.get("free_float",100)
    pi = ownership.get("pct_insider",0)
    sc = ownership.get("supply_control","")
    ff_col = "#00ff66" if ff<=15 else "#f0b429" if ff<=30 else "#9ca3af"
    if pi > 0 or ff < 100:
        lines.append(
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.6rem;'
            f'color:#6b7280">📊 Insider <b style="color:#e2e8f0">{pi:.1f}%</b> · '
            f'Free Float <b style="color:{ff_col}">{ff:.1f}%</b> · '
            f'<span style="color:{ff_col}">{sc}</span></div>'
        )

    # Phase 3: live broker if available
    if ownership.get("broker_live"):
        top_b = ownership.get("top_buyers",[])[:3]
        top_s = ownership.get("top_sellers",[])[:2]
        sp    = ownership.get("smart_buy_pct",0)
        sp_col= "#00ff66" if sp>=60 else "#f0b429" if sp>=40 else "#ef4444"
        lines.append(
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.6rem;'
            f'color:#6b7280;margin-top:0.2rem">🏦 LIVE BROKER — '
            f'Smart Money Buy <b style="color:{sp_col}">{sp:.0f}%</b></div>'
        )
        for b in top_b:
            lines.append(format_broker_row(b, True))
        if top_s:
            lines.append(
                '<div style="font-family:Share Tech Mono,monospace;font-size:0.58rem;'
                'color:#ef4444;margin-top:2px">SELLERS:</div>'
            )
            for s in top_s:
                lines.append(format_broker_row(s, False))

    if not lines:
        return ""

    return (
        '<div style="background:rgba(0,0,0,0.3);border:1px solid rgba(0,255,102,0.08);'
        'border-radius:3px;padding:0.4rem 0.7rem;margin-top:0.35rem">'
        + "".join(lines) + "</div>"
    )
