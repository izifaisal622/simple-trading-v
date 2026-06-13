"""
KSEI Ownership Agent — STV6
=============================
Fetches public ownership data from BEI/KSEI:
- Major shareholders >1% (public PDF/Excel from IDX)
- Hengky exact lot math
- Manual upload support
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger  = logging.getLogger(__name__)
BASE    = Path(__file__).parent.parent
DATA    = BASE / "data"
DATA.mkdir(exist_ok=True)
KSEI_DB = DATA / "ksei_ownership.json"

# ── Load/save cache ────────────────────────────────────────────────────────────

def _load_db() -> dict:
    if KSEI_DB.exists():
        try: return json.loads(KSEI_DB.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}

def _save_db(db: dict):
    KSEI_DB.write_text(json.dumps(db, indent=2, ensure_ascii=False, default=str))

# ── Fetch from IDX public endpoint ────────────────────────────────────────────

def fetch_idx_shareholders(ticker: str) -> dict:
    """
    Fetch major shareholders from IDX public API.
    IDX publishes ownership >5% and directors/commissioners.
    """
    t = ticker.replace(".JK","").upper()
    db = _load_db()

    # Cache valid 7 days
    if t in db:
        age = (datetime.now() - datetime.fromisoformat(
               db[t].get("_fetched","2000-01-01"))).days
        if age < 7:
            return db[t]

    try:
        import requests
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://idx.co.id/",
        }

        # Try IDX company profile endpoint (public, no auth needed)
        urls = [
            f"https://idx.co.id/api/company-profile?company_code={t}",
            f"https://idx.co.id/umbraco/Surface/Helper/GetCompanyProfiles?inCode={t}",
        ]

        for url in urls:
            try:
                r = requests.get(url, headers=headers, timeout=10)
                if r.status_code == 200 and r.text.strip().startswith("{"):
                    raw = r.json()
                    result = _parse_idx_profile(t, raw)
                    if result.get("holders"):
                        result["_fetched"] = datetime.now().isoformat()
                        result["source"]   = "idx_api"
                        db[t] = result
                        _save_db(db)
                        return result
            except Exception:
                pass

        # Fallback: try Stockbit company info endpoint
        # (doesn't need broker token, just basic endpoint)
        try:
            url = f"https://exodus.stockbit.com/fundamental/shareholder/{t}"
            r   = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                raw    = r.json()
                result = _parse_stockbit_holders(t, raw)
                if result.get("holders"):
                    result["_fetched"] = datetime.now().isoformat()
                    result["source"]   = "stockbit_fundamental"
                    db[t] = result
                    _save_db(db)
                    return result
        except Exception:
            pass

    except Exception as e:
        logger.debug(f"[KSEI] {t}: {e}")

    return {"ticker": t, "holders": [], "available": False}

def _parse_idx_profile(ticker: str, raw: dict) -> dict:
    """Parse IDX company profile API response."""
    holders = []
    try:
        # IDX returns shareholders in various formats depending on endpoint
        sh_data = (raw.get("Shareholders") or raw.get("shareholders") or
                   raw.get("MajorShareholders") or [])
        for sh in sh_data:
            name  = (sh.get("name") or sh.get("Name") or sh.get("shareholder","")).strip()
            pct   = float(sh.get("percentage") or sh.get("Percentage") or
                          sh.get("pct",0))
            shares= int(sh.get("shares") or sh.get("Shares") or 0)
            if name and pct > 0:
                holders.append({"name": name, "pct": pct, "shares": shares})
    except Exception:
        pass
    return {"ticker": ticker, "holders": holders, "available": bool(holders)}

def _parse_stockbit_holders(ticker: str, raw: dict) -> dict:
    """Parse Stockbit shareholder data."""
    holders = []
    try:
        data = raw.get("data", raw)
        for sh in data if isinstance(data, list) else []:
            name  = sh.get("name","").strip()
            pct   = float(sh.get("percentage") or sh.get("pct",0))
            shares= int(sh.get("shares") or sh.get("amount",0))
            if name:
                holders.append({"name": name, "pct": pct, "shares": shares})
    except Exception:
        pass
    return {"ticker": ticker, "holders": holders, "available": bool(holders)}

# ── Manual upload ──────────────────────────────────────────────────────────────

def save_manual_shareholders(ticker: str, holders: list, source: str = "manual"):
    """
    Save manually entered or uploaded shareholder data.
    holders = [{"name": str, "pct": float, "shares": int, "lot": int}]
    """
    t  = ticker.replace(".JK","").upper()
    db = _load_db()

    # Calculate lots if not provided
    for h in holders:
        if "lot" not in h and "shares" in h and h["shares"] > 0:
            h["lot"] = h["shares"] // 500
        elif "lot" not in h:
            h["lot"] = 0

    db[t] = {
        "ticker":   t,
        "holders":  holders,
        "available":True,
        "source":   source,
        "_fetched": datetime.now().isoformat(),
    }
    _save_db(db)
    logger.info(f"[KSEI] Saved {len(holders)} holders for {t}")
    return db[t]

def parse_shareholder_csv(filepath: str, ticker: str) -> dict:
    """Parse manually uploaded CSV of shareholders."""
    import csv
    holders = []
    with open(filepath, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name   = (row.get("name") or row.get("Name") or row.get("Nama","")).strip()
            pct    = float(str(row.get("pct") or row.get("percentage") or
                              row.get("Persen","0")).replace("%","").replace(",","") or 0)
            shares = int(str(row.get("shares") or row.get("Shares") or
                             row.get("Saham","0")).replace(",","") or 0)
            lot    = int(str(row.get("lot") or row.get("Lot","0")).replace(",","") or 0)
            if not lot and shares: lot = shares // 500
            if name:
                holders.append({"name": name, "pct": pct, "shares": shares, "lot": lot})
    return save_manual_shareholders(ticker, holders, "csv_upload")

# ── Hengky math engine ────────────────────────────────────────────────────────

def compute_hengky_math(ticker: str,
                        shares_outstanding: float = 0,
                        free_float_override: float = 0) -> dict:
    """
    Compute Hengky's exact supply math for a ticker.
    Uses KSEI/IDX data if available, static DB as fallback.
    """
    from agents.broker_history import hengky_lot_math
    t  = ticker.replace(".JK","").upper()
    db = _load_db()

    # Get shareholder data
    own_data = db.get(t, {})
    if not own_data.get("holders"):
        own_data = fetch_idx_shareholders(t)

    holders  = own_data.get("holders", [])

    # Get shares outstanding and free float
    if not shares_outstanding:
        # Try from free_float_db
        ff_db = DATA / "free_float_db.json"
        if ff_db.exists():
            ffdata = json.loads(ff_db.read_text()).get(t, {})
            free_float_override = free_float_override or ffdata.get("ff", 0)

    ff = free_float_override or 20.0  # default 20% if unknown

    # Build known holders list for Hengky math
    known = []
    for h in holders:
        if h.get("pct",0) >= 1.0:  # only >1% per KSEI disclosure rules
            lot = h.get("lot", int(h.get("shares",0) / 500))
            if lot == 0 and shares_outstanding > 0:
                lot = int(shares_outstanding * h["pct"] / 100 / 500)
            known.append({"name": h["name"], "lot": lot, "pct": h["pct"]})

    if not shares_outstanding:
        return {
            "available": False,
            "reason": "Shares outstanding tidak diketahui — input manual diperlukan",
            "ticker": t,
            "holders_found": len(known),
        }

    result = hengky_lot_math(t, shares_outstanding, ff, known)
    result["holders_data"] = own_data
    result["available"]    = True
    return result


# ── Dashboard HTML renderer ───────────────────────────────────────────────────

def render_hengky_math_html(math: dict) -> str:
    """Render Hengky math as HTML card for dashboard."""
    if not math.get("available"):
        return (
            f'<div style="background:rgba(0,0,0,0.2);border:1px solid rgba(255,255,255,0.06);'
            f'border-radius:3px;padding:0.6rem 1rem;font-family:Share Tech Mono,monospace;'
            f'font-size:0.62rem;color:#4b5563">'
            f'🧮 Hengky Math: {math.get("reason","Data tidak tersedia")} '
            f'— Upload data pemegang saham di tab KSEI</div>'
        )

    ctrl   = math["control_pct"]
    free   = math["free_lot"]
    total  = math["total_float_lot"]
    label  = math["supply_label"]
    ctrl_col = "#00ff66" if ctrl>=70 else "#f0b429" if ctrl>=40 else "#9ca3af"

    steps_html = "".join([
        f'<div style="font-family:Share Tech Mono,monospace;font-size:0.6rem;'
        f'color:#6b7280;line-height:1.8">{s}</div>'
        for s in math["steps"]
    ])

    return f"""
<div style="background:rgba(0,255,102,0.03);border:1px solid rgba(0,255,102,0.1);
border-radius:3px;padding:0.6rem 0.9rem;margin-top:0.3rem">
  <div style="display:flex;align-items:center;gap:0.8rem;margin-bottom:0.4rem">
    <span style="font-family:Share Tech Mono,monospace;font-size:0.58rem;
    color:#4b5563;letter-spacing:0.14em">🧮 HENGKY MATH</span>
    <span style="font-family:Share Tech Mono,monospace;font-size:0.72rem;
    font-weight:700;color:{ctrl_col}">CONTROL {ctrl:.0f}%</span>
    <span style="font-family:Share Tech Mono,monospace;font-size:0.62rem;
    color:{ctrl_col}">{label}</span>
    <span style="font-family:Share Tech Mono,monospace;font-size:0.6rem;
    color:#4b5563;margin-left:auto">Sisa bebas: {free:,.0f} lot / {total:,.0f} lot</span>
  </div>
  {steps_html}
</div>"""
