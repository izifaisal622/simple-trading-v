"""
Simple Trading V9 — Page 03: War Room
Position Monitor · Pre-Market Briefing · Exit Signal Engine

Menggantikan Money Flow Scanner (top gainer) yang duplikat fungsi broker app.
War Room = command center untuk posisi yang sudah ada:
  1. Pre-Market Briefing  — regime + regional sentiment sebelum market buka
  2. Position Health      — traffic light per posisi (3-5 saham)
  3. Exit Signal Watch    — surface exit_engine.py yang sudah ada ke UI
"""
import sys
import json
from datetime import datetime, date
from pathlib import Path

import streamlit as st
import pandas as pd

ROOT         = Path(__file__).parent.parent
LOGS_DIR     = ROOT / "logs"
RESULTS_FILE = LOGS_DIR / "daily_results.json"
sys.path.insert(0, str(ROOT))

from assets_ui import (
    get_page_css, render_sidebar, render_page_header,
    sec_head, fmt_rp,
    NEON_GREEN, TEXT_MUTED, TEXT_DIM, TEXT_MAIN,
)

st.set_page_config(
    page_title="War Room · STV",
    page_icon="⚔️",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(get_page_css("dashboard"), unsafe_allow_html=True)

# ── Version ───────────────────────────────────────────────────────────────────
try:
    _ver_accent = "V" + json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"].split(".")[0]
except Exception:
    _ver_accent = "V?"

# ── Load regime context ───────────────────────────────────────────────────────
scan_date = "—"
regime    = "UNKNOWN"
cycle     = "UNKNOWN"
ihsg      = 0
mom_4w    = 0
try:
    if RESULTS_FILE.exists():
        _d      = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
        ctx     = _d.get("whale_context", {})
        regime  = ctx.get("cycle", _d.get("regime", {}).get("cycle", "UNKNOWN"))
        cycle   = regime
        ihsg    = ctx.get("ihsg", _d.get("regime", {}).get("ihsg", 0))
        mom_4w  = ctx.get("mom_4w", _d.get("regime", {}).get("mom_4w", 0))
        scan_date = (_d.get("date", "")[:10] or "—")
except Exception:
    pass

render_sidebar("war_room", scan_date=scan_date, regime=regime)

render_page_header(
    eyebrow  = "◆ MODULE 03 · POSITION COMMAND CENTER",
    title    = "SIMPLE TRADING ",
    accent   = _ver_accent,
    subtitle = "◈ WAR ROOM · PRE-MARKET BRIEFING · POSITION HEALTH · EXIT SIGNAL WATCH",
    scan_date= scan_date,
)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — PRE-MARKET BRIEFING
# ══════════════════════════════════════════════════════════════════════════════
sec_head("◆ PRE-MARKET BRIEFING")

def _fetch_regional() -> dict:
    """Fetch regional market closing prices sebagai proxy market sentiment."""
    import yfinance as yf
    tickers = {
        "IHSG":   "^JKSE",
        "Nikkei": "^N225",
        "HSI":    "^HSI",
        "S&P500": "^GSPC",
        "DXY":    "DX-Y.NYB",
    }
    result = {}
    for name, sym in tickers.items():
        try:
            df = yf.download(sym, period="5d", interval="1d", progress=False, auto_adjust=True)
            if df is None or len(df) < 2:
                result[name] = {"last": 0, "chg": 0}
                continue
            # Flatten MultiIndex columns (yfinance baru return MultiIndex)
            if hasattr(df.columns, "get_level_values") and isinstance(df.columns[0], tuple):
                df.columns = df.columns.get_level_values(0)
            last  = float(df["Close"].iloc[-1])
            prev  = float(df["Close"].iloc[-2])
            chg   = (last - prev) / prev * 100
            result[name] = {"last": last, "chg": round(chg, 2)}
        except Exception:
            result[name] = {"last": 0, "chg": 0}
    return result

# Regime verdict
_REGIME_VERDICT = {
    "BULL_TREND":        ("AGRESIF", "#00FF66",  "Full size. Breakout layak dikejar."),
    "BULL_CONSOLIDATION":("SELEKTIF", "#4ADE80",  "75% size. Rotasi sektor."),
    "TRANSITION":        ("HATI-HATI","#F0B429",  "50% size. Setup conviction tinggi saja."),
    "BEAR_CONSOLIDATION":("DEFENSIVE","#FB923C",  "25% size. Bangun watchlist saja."),
    "BEAR_TREND":        ("STOP TRADE","#EF4444", "FULL CASH. Tunggu regime berubah."),
    "UNKNOWN":           ("UNKNOWN",  "#64748B",  "Update data IHSG dulu."),
}
_vdict = _REGIME_VERDICT.get(cycle, _REGIME_VERDICT["UNKNOWN"])
_verdict_lbl, _verdict_col, _verdict_desc = _vdict

# Pre-market row: regime verdict + refresh button
_pm1, _pm2 = st.columns([4, 1])
with _pm1:
    _mom_col = "#00FF66" if mom_4w > 0 else "#EF4444"
    st.markdown(f"""
<div style="background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.07);
border-left:4px solid {_verdict_col};border-radius:var(--r-md);
padding:0.8rem 1.2rem;margin-bottom:0.5rem;
display:flex;align-items:center;gap:1.5rem;flex-wrap:wrap">
  <div>
    <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);
    color:#94A3B8;letter-spacing:0.15em">MARKET REGIME</div>
    <div style="font-family:Orbitron,monospace;font-size:var(--text-xl);
    font-weight:900;color:{_verdict_col}">{_verdict_lbl}</div>
  </div>
  <div style="border-left:1px solid rgba(255,255,255,0.08);padding-left:1.5rem">
    <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
    color:#CBD5E1">{cycle}</div>
    <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
    color:#CBD5E1;margin-top:2px">{_verdict_desc}</div>
  </div>
  <div style="border-left:1px solid rgba(255,255,255,0.08);padding-left:1.5rem">
    <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);
    color:#94A3B8">IHSG</div>
    <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-base);
    color:#E2E8F0;font-weight:700">{ihsg:,.0f}</div>
  </div>
  <div style="border-left:1px solid rgba(255,255,255,0.08);padding-left:1.5rem">
    <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);
    color:#94A3B8">MOM 4W</div>
    <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-base);
    color:{_mom_col};font-weight:700">{mom_4w:+.1f}%</div>
  </div>
</div>
""", unsafe_allow_html=True)

with _pm2:
    _fetch_regional_btn = st.button("⟳ FETCH REGIONAL", key="btn_fetch_regional",
                                     use_container_width=True)

# Regional market data
if _fetch_regional_btn or "regional_data" not in st.session_state:
    with st.spinner("Fetching regional data..."):
        st.session_state["regional_data"] = _fetch_regional()

_regional = st.session_state.get("regional_data", {})
if _regional:
    _rcols = st.columns(len(_regional))
    for (_rname, _rdata), _rcol in zip(_regional.items(), _rcols):
        _rchg  = _rdata.get("chg", 0)
        _rlast = _rdata.get("last", 0)

        # Warna & sentiment
        if _rchg >= 1.0:
            _clr = "#22C55E"; _bg = "rgba(34,197,94,0.08)"; _brd = "rgba(34,197,94,0.25)"; _arrow = "▲"
        elif _rchg >= 0:
            _clr = "#86EFAC"; _bg = "rgba(34,197,94,0.04)"; _brd = "rgba(34,197,94,0.12)"; _arrow = "▲"
        elif _rchg >= -1.0:
            _clr = "#FCA5A5"; _bg = "rgba(239,68,68,0.04)"; _brd = "rgba(239,68,68,0.12)"; _arrow = "▼"
        else:
            _clr = "#EF4444"; _bg = "rgba(239,68,68,0.10)"; _brd = "rgba(239,68,68,0.30)"; _arrow = "▼"

        # Format angka — DXY pakai 2 desimal, yang lain bulat
        _val_str = f"{_rlast:,.2f}" if _rname == "DXY" else f"{_rlast:,.0f}"

        with _rcol:
            st.markdown(f"""
<div style="background:{_bg};border:1px solid {_brd};border-radius:8px;
padding:1rem 0.8rem;text-align:center;min-height:90px;
display:flex;flex-direction:column;justify-content:center;gap:4px">
  <div style="font-family:Share Tech Mono,monospace;font-size:0.65rem;
  color:#64748B;letter-spacing:0.12em;text-transform:uppercase">{_rname}</div>
  <div style="font-family:Share Tech Mono,monospace;font-size:1.15rem;
  color:#F1F5F9;font-weight:700;line-height:1.1">{_val_str}</div>
  <div style="font-family:Share Tech Mono,monospace;font-size:0.85rem;
  color:{_clr};font-weight:700">{_arrow} {_rchg:+.2f}%</div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1.5 — MOVER ALERT (semi-dynamic dari pool 180 ticker)
# Fetch ringan: Close + Volume 5 hari untuk semua ticker di pool
# Tampilkan top mover hari ini sebagai early attention signal
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("<br>", unsafe_allow_html=True)
sec_head("◆ MOVER ALERT — POOL HARI INI")

@st.cache_data(ttl=1800)  # cache 30 menit — cukup untuk satu sesi pagi
def _fetch_movers() -> list:
    """
    Fetch Close + Volume 5 hari untuk semua ticker di idx_pool.json.
    Return list of dicts sorted by activity_score desc.
    activity_score = vol_ratio * 0.5 + abs(pct_5d) * 0.3 + abs(pct_1d) * 0.2
    """
    import yfinance as yf
    import json as _json
    from pathlib import Path as _Path

    pool_file = _Path(__file__).parent.parent / "data" / "idx_pool.json"
    if not pool_file.exists():
        return []
    tickers = _json.loads(pool_file.read_text())["tickers"]
    full    = [t + ".JK" for t in tickers]

    try:
        raw = yf.download(
            " ".join(full),
            period="1mo", interval="1d",
            progress=False, auto_adjust=True,
            group_by="ticker",
        )
    except Exception:
        return []

    results = []
    for t in tickers:
        tk = t + ".JK"
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                if tk not in raw.columns.get_level_values(0):
                    continue
                df = raw[tk].dropna(how="all")
            else:
                df = raw.dropna(how="all")
            if df is None or len(df) < 5:
                continue

            close  = df["Close"]
            volume = df["Volume"]

            last_close  = float(close.iloc[-1])
            prev_close  = float(close.iloc[-2])
            close_5d    = float(close.iloc[-6]) if len(close) >= 6 else float(close.iloc[0])
            last_vol    = float(volume.iloc[-1])
            vol_ma20    = float(volume.rolling(20).mean().iloc[-1])

            pct_1d  = (last_close - prev_close) / prev_close * 100 if prev_close > 0 else 0
            pct_5d  = (last_close - close_5d)   / close_5d   * 100 if close_5d > 0  else 0
            vol_r   = last_vol / vol_ma20 if vol_ma20 > 0 else 0

            activity = vol_r * 0.5 + abs(pct_5d) * 0.3 + abs(pct_1d) * 0.2

            results.append({
                "ticker":    t,
                "close":     last_close,
                "pct_1d":    pct_1d,
                "pct_5d":    pct_5d,
                "vol_ratio": vol_r,
                "activity":  activity,
            })
        except Exception:
            continue

    results.sort(key=lambda x: x["activity"], reverse=True)
    return results

# ── Render Mover Alert ────────────────────────────────────────────────────────
_col_refresh, _col_info = st.columns([1, 4])
with _col_refresh:
    _do_mover = st.button("◉ CEK MOVER", key="mover_refresh", use_container_width=True)
with _col_info:
    st.markdown(
        "<span style='font-family:Share Tech Mono,monospace;font-size:0.75rem;"
        "color:#475569'>Fetch ringan Close+Vol 5 hari dari pool 180 ticker · "
        "Cache 30 menit · Bukan sinyal entry — hanya early attention</span>",
        unsafe_allow_html=True
    )

if _do_mover or st.session_state.get("mover_loaded"):
    st.session_state["mover_loaded"] = True
    with st.spinner("Fetching mover data..."):
        _movers = _fetch_movers()

    if _movers:
        # Tampilkan top 15
        _top15    = _movers[:15]
        _in_scan  = set()
        try:
            import json as _j
            from pathlib import Path as _pp
            _rf = _pp(__file__).parent.parent / "logs" / "daily_results.json"
            if _rf.exists():
                _rd = _j.loads(_rf.read_text())
                _in_scan = {r.get("ticker","").replace(".JK","")
                            for r in _rd.get("ema_results", [])}
        except Exception:
            pass

        # Build HTML rows
        _rows_html = ""
        for m in _top15:
            t        = m["ticker"]
            pct1     = m["pct_1d"]
            pct5     = m["pct_5d"]
            volr     = m["vol_ratio"]
            close    = m["close"]
            act      = m["activity"]
            in_scan  = t in _in_scan

            _p1col   = "#22C55E" if pct1 >= 0 else "#EF4444"
            _p5col   = "#22C55E" if pct5 >= 0 else "#EF4444"
            _vcol    = "#F59E0B" if volr >= 2 else ("#22C55E" if volr >= 1 else "#64748B")
            _scan_badge = (
                "<span style='background:#166534;color:#4ADE80;padding:1px 6px;"
                "border-radius:4px;font-size:0.65rem'>IN SCAN</span>"
                if in_scan else ""
            )

            _rows_html += f"""
<div style="display:flex;align-items:center;gap:0.6rem;padding:5px 8px;
border-bottom:1px solid #1E293B;font-family:Share Tech Mono,monospace">
  <span style="color:#E2E8F0;font-weight:700;min-width:3.5rem">{t}</span>
  <span style="color:#94A3B8;font-size:0.75rem">Rp{close:,.0f}</span>
  <span style="color:{_p1col};font-size:0.75rem;min-width:4rem">{pct1:+.1f}% 1d</span>
  <span style="color:{_p5col};font-size:0.75rem;min-width:4rem">{pct5:+.1f}% 5d</span>
  <span style="color:{_vcol};font-size:0.75rem;min-width:4rem">vol {volr:.1f}x</span>
  <span style="color:#475569;font-size:0.65rem">act {act:.1f}</span>
  {_scan_badge}
</div>"""

        st.markdown(f"""
<div style="background:#0F172A;border:1px solid #1E293B;border-radius:8px;
padding:0;overflow:hidden;margin-bottom:1rem">
  <div style="background:#1E293B;padding:6px 12px;display:flex;gap:2rem;
  font-family:Share Tech Mono,monospace;font-size:0.7rem;color:#64748B">
    <span>TICKER</span><span>HARGA</span><span>1 HARI</span>
    <span>5 HARI</span><span>VOLUME</span><span>ACTIVITY SCORE</span>
  </div>
  {_rows_html}
</div>
<p style="font-family:Share Tech Mono,monospace;font-size:0.65rem;color:#334155;
margin:0">Top 15 dari {len(_movers)} ticker berhasil di-fetch · 
Sorted by activity score · IN SCAN = sudah ada di hasil scan hari ini</p>
""", unsafe_allow_html=True)
    else:
        st.warning("Tidak ada data mover — coba lagi atau cek koneksi.")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — POSITION HEALTH
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("<br>", unsafe_allow_html=True)
sec_head("◆ POSITION HEALTH MONITOR")

# Load open trades dari trade_logger
_open_trades = []
try:
    from trade_logger import get_open_trades
    _open_trades = get_open_trades()
except Exception:
    pass

def _health_color(pct_to_sl: float, pct_to_tp1: float, exit_urgency: str = "") -> tuple:
    """
    Traffic light berdasarkan jarak ke SL dan TP1.
    P03-W1: NEAR_TP1 dibedakan secara visual dari HEALTHY
    P03-X1: handle case harga sudah DI BAWAH SL (pct_to_sl negatif)
    Opsi-2: exit_urgency dari ExitEngine override warna card jika lebih kritis
    """
    # P03-X1: SL sudah terlewat (harga < SL) — emergency state
    if pct_to_sl <= 0:
        return "#7F1D1D", "🚨 SL TERLEWAT"
    elif pct_to_sl <= 3:
        return "#EF4444", "🔴 NEAR SL"
    elif pct_to_sl <= 8:
        return "#F0B429", "🟡 WATCH"
    elif pct_to_tp1 is not None and pct_to_tp1 <= 5:
        return "#60A5FA", "🔵 NEAR TP1"
    elif pct_to_tp1 is not None and pct_to_tp1 <= 12:
        # Opsi-2: ExitEngine CRITICAL override card hijau → merah
        if exit_urgency == "CRITICAL":
            return "#EF4444", "🔴 EXIT SIGNAL"
        return "#00FF66", "🟢 ON TRACK"
    else:
        # Opsi-2: ExitEngine override card HEALTHY
        if exit_urgency == "CRITICAL":
            return "#EF4444", "🔴 EXIT SIGNAL"
        if exit_urgency == "WARNING":
            return "#F0B429", "🟡 WATCH"
        return "#00FF66", "🟢 HEALTHY"

def _fetch_position_data(ticker: str) -> dict:
    """Fetch current price + EMA data untuk satu posisi."""
    import yfinance as yf
    try:
        sym = ticker if ticker.endswith(".JK") else ticker + ".JK"
        df  = yf.download(sym, period="60d", interval="1d", progress=False, auto_adjust=True)
        if df is None or len(df) < 5:
            return {}
        if hasattr(df.columns, "get_level_values"):
            df.columns = df.columns.get_level_values(0)
        close  = df["Close"]
        volume = df["Volume"]
        last   = float(close.iloc[-1])
        ema13  = float(close.ewm(span=13, adjust=False).mean().iloc[-1])
        ema89  = float(close.ewm(span=89, adjust=False).mean().iloc[-1])
        vol_ma = float(volume.rolling(20).mean().iloc[-1])
        last_v = float(volume.iloc[-1])
        atr14  = float((df["High"] - df["Low"]).rolling(14).mean().iloc[-1])
        data_date = str(df.index[-1])[:10]
        return {
            "last": last, "ema13": ema13, "ema89": ema89,
            "vol_ratio": round(last_v / vol_ma, 2) if vol_ma > 0 else 0,
            "atr14": atr14, "df": df, "data_date": data_date,
        }
    except Exception:
        return {}

# Manual position input
with st.expander("➕ TAMBAH POSISI MANUAL", expanded=not _open_trades):
    _ma1, _ma2, _ma3, _ma4, _ma5, _ma6 = st.columns(6)
    with _ma1: _man_ticker = st.text_input("Ticker", placeholder="BBCA", key="man_ticker").upper()
    with _ma2: _man_entry  = st.number_input("Entry (Rp)", 0.0, step=10.0, key="man_entry")
    with _ma3: _man_sl     = st.number_input("SL (Rp)", 0.0, step=10.0, key="man_sl")
    with _ma4: _man_tp1    = st.number_input("TP1 (Rp)", 0.0, step=10.0, key="man_tp1")
    with _ma5: _man_tp2    = st.number_input("TP2 (Rp)", 0.0, step=10.0, key="man_tp2")
    with _ma6: _man_edate  = st.date_input("Tanggal Entry", value=date.today(),
                                            max_value=date.today(), key="man_edate")
    if st.button("💾 SIMPAN & TRACK", key="btn_save_pos"):
        if _man_ticker and _man_entry > 0 and _man_sl > 0:
            try:
                from trade_logger import log_trade
                _tid = log_trade(
                    ticker      = _man_ticker,
                    entry_price = _man_entry,
                    sl_price    = _man_sl,
                    tp1_price   = _man_tp1,
                    entry_date  = _man_edate.strftime("%Y-%m-%d"),
                    notes       = f"tp2={_man_tp2}" if _man_tp2 > 0 else "",
                )
                st.success(f"✅ {_man_ticker} tersimpan (ID #{_tid})")
                st.rerun()
            except Exception as _e:
                st.error(f"Error: {_e}")
        else:
            st.warning("Isi Ticker, Entry, dan SL dulu.")

# Render position cards
if not _open_trades:
    st.markdown("""
<div style="background:rgba(0,0,0,0.2);border:1px solid rgba(255,255,255,0.06);
border-radius:var(--r-md);padding:1.5rem;text-align:center">
  <div style="font-family:Orbitron,monospace;font-size:var(--text-base);
  color:var(--text-dim);letter-spacing:0.15em">NO OPEN POSITIONS</div>
  <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
  color:var(--text-dim);margin-top:0.4rem">
  Tambah posisi via form di atas atau log trade dari Page 01 EMA XBO
  </div>
</div>
""", unsafe_allow_html=True)
else:
    _fetch_all = st.button("⟳ REFRESH SEMUA HARGA", key="btn_refresh_all",
                            use_container_width=False)

    # P03-X3: fetch semua posisi dulu dalam satu spinner, baru render cards
    if _fetch_all:
        with st.spinner(f"Fetching {len(_open_trades)} posisi..."):
            for _t_pre in _open_trades:
                _tk = _t_pre.get("ticker","").upper()
                st.session_state[f"pos_data_{_tk}"] = _fetch_position_data(_tk)

    _pos_cols = st.columns(min(len(_open_trades), 3))
    for _idx, _trade in enumerate(_open_trades):
        _t      = _trade.get("ticker", "").upper()
        _entry  = _trade.get("entry_price", 0) or 0
        _sl     = _trade.get("sl_price", 0) or 0
        _notes  = _trade.get("notes", "") or ""
        _tid    = _trade.get("id", 0)
        _edate  = _trade.get("entry_date", "") or ""

        # Parse TP dari notes jika ada
        _tp1 = _trade.get("tp1_price", 0) or 0
        _tp2 = 0
        try:
            for _part in _notes.split("|"):
                _part = _part.strip()
                if _part.startswith("tp2="):
                    _tp2 = float(_part.replace("tp2=", "").strip())
                if _part.startswith("tp1="):
                    _tp1 = float(_part.replace("tp1=", "").strip())
        except Exception:
            pass
        # TP1 fallback: entry + 2× risk
        if _tp1 == 0 and _entry > 0 and _sl > 0:
            _tp1 = _entry + 2 * (_entry - _sl)

        # Fetch atau ambil dari cache
        _cache_key = f"pos_data_{_t}"
        if _fetch_all or _cache_key not in st.session_state:
            with st.spinner(f"Fetching {_t}..."):
                st.session_state[_cache_key] = _fetch_position_data(_t)
        _pdata = st.session_state.get(_cache_key, {})

        _last      = _pdata.get("last", 0)
        _ema13     = _pdata.get("ema13", 0)
        _vol_r     = _pdata.get("vol_ratio", 0)
        _data_date       = _pdata.get("data_date", "")
        _data_date_badge = f'<span style="color:#475569">data per {_data_date}</span>' if _data_date else ""

        # Kalkulasi posisi
        _pnl_pct    = ((_last - _entry) / _entry * 100) if _entry > 0 and _last > 0 else 0
        _pct_to_sl  = ((_last - _sl) / _last * 100) if _last > 0 and _sl > 0 else 999
        _pct_to_tp1 = ((_tp1 - _last) / _last * 100) if _last > 0 and _tp1 > 0 else 999
        _ema_ok     = _last > _ema13 * 0.98 if _ema13 > 0 else True

        # Pre-build holding days string untuk card render
        _holding_days_str = "—"
        if _edate:
            try:
                from datetime import date as _cdate
                _holding_days_str = f"{(_cdate.today() - _cdate.fromisoformat(_edate[:10])).days}d"
            except Exception:
                pass

        _pnl_col = "#00FF66" if _pnl_pct >= 0 else "#EF4444"

        # Pre-build colors for SL/TP1 cells — avoid nested ternary inside f-string
        if _pct_to_sl <= 0:
            _sl_col = "#7F1D1D"
        elif _pct_to_sl <= 5:
            _sl_col = "#EF4444"
        elif _pct_to_sl <= 10:
            _sl_col = "#F0B429"
        else:
            _sl_col = "#94A3B8"

        if _pct_to_tp1 <= 5:
            _tp1_col = "#60A5FA"
        elif _pct_to_tp1 <= 12:
            _tp1_col = "#00FF66"
        else:
            _tp1_col = "#94A3B8"
        _ema_badge = (
            '<span style="color:#00FF66;font-size:var(--text-2xs)">EMA ✓</span>'
            if _ema_ok else
            '<span style="color:#EF4444;font-size:var(--text-2xs)">EMA ⚠</span>'
        )
        _vol_col = "#00FF66" if _vol_r >= 1.5 else "#F0B429" if _vol_r >= 0.8 else "#EF4444"

        # Opsi-2: baca exit_signals dari session_state untuk ticker ini
        _cached_sigs  = st.session_state.get("exit_signals", [])
        _ticker_sigs  = [s for s in _cached_sigs if s.ticker == _t]
        _exit_urgency = ""
        _exit_badges  = ""
        if _ticker_sigs:
            _urg_order   = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
            _ticker_sigs.sort(key=lambda s: _urg_order.get(s.urgency, 3))
            _exit_urgency = _ticker_sigs[0].urgency  # worst urgency
            _badge_parts  = []
            _badge_colors = {"CRITICAL": "#EF4444", "WARNING": "#F0B429", "INFO": "#4ADE80"}
            for _s in _ticker_sigs:
                _bc  = _badge_colors.get(_s.urgency, "#64748B")
                _bp  = '<span style="background:' + _bc + '22;border:1px solid ' + _bc + '66;'
                _bp += 'border-radius:3px;padding:1px 6px;font-family:Orbitron,monospace;'
                _bp += 'font-size:var(--text-2xs);font-weight:700;color:' + _bc + ';margin-left:4px">'
                _bp += _s.exit_type + '</span>'
                _badge_parts.append(_bp)
            _exit_badges = " ".join(_badge_parts)

        _health_c, _health_lbl = _health_color(_pct_to_sl, _pct_to_tp1, _exit_urgency)

        with _pos_cols[_idx % 3]:
            st.markdown(f"""
<div style="background:rgba(0,0,0,0.3);border:1px solid {_health_c}40;
border-left:4px solid {_health_c};border-radius:var(--r-md);
padding:0.8rem 1rem;margin-bottom:0.6rem">
  <div style="display:flex;align-items:center;justify-content:space-between;
  margin-bottom:0.5rem;padding-bottom:0.4rem;border-bottom:1px solid rgba(255,255,255,0.06)">
    <span style="font-family:Orbitron,monospace;font-size:var(--text-xl);
    font-weight:900;color:#E2E8F0">{_t}</span>
    <span style="font-family:Orbitron,monospace;font-size:var(--text-xs);
    font-weight:700;color:{_health_c}">{_health_lbl}</span>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.4rem;margin-bottom:0.5rem">
    <div style="background:rgba(255,255,255,0.03);border-radius:4px;padding:0.4rem 0.5rem">
      <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:#94A3B8">HARGA</div>
      <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);color:#E2E8F0;font-weight:700">
        {f"Rp{_last:,.0f}" if _last else "—"}
      </div>
    </div>
    <div style="background:rgba(255,255,255,0.03);border-radius:4px;padding:0.4rem 0.5rem">
      <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:#94A3B8">P&L</div>
      <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);color:{_pnl_col};font-weight:700">
        {f"{_pnl_pct:+.1f}%" if _last else "—"}
      </div>
    </div>
    <div style="background:rgba(255,255,255,0.03);border-radius:4px;padding:0.4rem 0.5rem">
      <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:#94A3B8">→ SL</div>
      <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);
      color:{_sl_col}">
        {f"TERLEWAT" if _pct_to_sl <= 0 else f"{_pct_to_sl:.1f}%" if _last else "—"}
      </div>
    </div>
    <div style="background:rgba(255,255,255,0.03);border-radius:4px;padding:0.4rem 0.5rem">
      <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:#94A3B8">→ TP1</div>
      <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);
      color:{_tp1_col}">
        {f"{_pct_to_tp1:.1f}%" if _last and _tp1 else "—"}
      </div>
    </div>
    <div style="background:rgba(255,255,255,0.03);border-radius:4px;padding:0.4rem 0.5rem">
      <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:#94A3B8">→ TP2</div>
      <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);color:#94A3B8">
        {f"Rp{_tp2:,.0f}" if _tp2 else "—"}
      </div>
    </div>
    <div style="background:rgba(255,255,255,0.03);border-radius:4px;padding:0.4rem 0.5rem">
      <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:#94A3B8">HARI</div>
      <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);color:#CBD5E1">
        {_holding_days_str}
      </div>
    </div>
  </div>
  <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);
  color:#94A3B8;display:flex;gap:0.8rem;align-items:center">
    <span>Entry <b style="color:#E2E8F0">Rp{_entry:,.0f}</b></span>
    <span>SL <b style="color:#EF4444">Rp{_sl:,.0f}</b></span>
    <span>Vol <b style="color:{_vol_col}">{_vol_r:.1f}×</b></span>
    {_ema_badge}
    {_exit_badges}
    {_data_date_badge}
  </div>
</div>
""", unsafe_allow_html=True)

            # Close trade button
            if st.button(f"✓ CLOSE #{_tid}", key=f"close_{_tid}_{_t}",
                         use_container_width=True):
                st.session_state[f"closing_{_tid}"] = True

            if st.session_state.get(f"closing_{_tid}"):
                _cx1, _cx2, _cx3 = st.columns(3)
                with _cx1:
                    _close_price = st.number_input("Exit Price",
                                                    value=float(_last) if _last else 0.0,
                                                    step=10.0, key=f"cp_{_tid}")
                with _cx2:
                    _close_out = st.selectbox("Outcome",
                                               ["WIN", "LOSS", "BREAKEVEN"],
                                               key=f"co_{_tid}")
                with _cx3:
                    if st.button("💾 CONFIRM", key=f"cf_{_tid}"):
                        try:
                            from trade_logger import close_trade
                            _res = close_trade(_tid, _close_price, _close_out)
                            if _res.get("success"):
                                st.success(f"✅ {_t} closed — {_close_out} · {_res.get('pnl_r', 0):+.2f}R")
                                st.session_state.pop(f"closing_{_tid}", None)
                                st.session_state.pop(f"pos_data_{_t}", None)
                                st.rerun()
                        except Exception as _ce:
                            st.error(f"Error: {_ce}")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — EXIT SIGNAL WATCH
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("<br>", unsafe_allow_html=True)
sec_head("◆ EXIT SIGNAL WATCH")

_URGENCY_COLOR = {
    "CRITICAL": "#EF4444",
    "WARNING":  "#F0B429",
    "INFO":     "#4ADE80",
}
_ACTION_COLOR = {
    "EXIT_NOW":   "#EF4444",
    "TIGHTEN_SL": "#F0B429",
    "MOVE_TO_BE": "#4ADE80",
    "MONITOR":    "#64748B",
}
_EXIT_ICON = {
    "SL_HIT":      "🔴",
    "EMA_BREAK":   "🔴",
    "TRAIL_HIT":   "🔴",
    "TIME_STOP":   "🟡",
    "VOL_COLLAPSE":"🟡",
    "TP_HIT":      "🟢",
}

if not _open_trades:
    st.markdown("""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
    color:#94A3B8">Tidak ada posisi open. Tambah posisi di atas untuk mulai monitoring.</p>""",
    unsafe_allow_html=True)
else:
    _run_exit = st.button("⟳ EVALUASI EXIT SIGNALS", key="btn_exit_eval",
                           type="primary", use_container_width=False)
    if _run_exit:
        from core.exit_engine import ExitEngine
        _engine  = ExitEngine()
        _all_sig = []

        with st.spinner("Evaluating exit signals..."):
            for _trade in _open_trades:
                _t     = _trade.get("ticker", "").upper()
                _entry = float(_trade.get("entry_price", 0) or 0)
                _sl    = float(_trade.get("sl_price", 0) or 0)
                _edate = _trade.get("entry_date", "") or ""
                _notes = _trade.get("notes", "") or ""

                # Parse TP
                _tp1, _tp2 = 0.0, 0.0
                try:
                    for _part in _notes.split("|"):
                        _p = _part.strip()
                        if _p.startswith("tp1="): _tp1 = float(_p[4:])
                        if _p.startswith("tp2="): _tp2 = float(_p[4:])
                except Exception:
                    pass
                if _tp1 == 0 and _entry > 0 and _sl > 0:
                    _tp1 = _entry + 2 * (_entry - _sl)
                if _tp2 == 0:
                    # TP2 fallback: entry + 4×risk (lebih realistis dari tp1*1.05)
                    _risk = _entry - _sl if _entry > 0 and _sl > 0 else 0
                    _tp2 = (_entry + 4 * _risk) if _risk > 0 else _tp1 * 1.15

                # Ambil df dari cache jika ada, fetch jika tidak
                _pdata = st.session_state.get(f"pos_data_{_t}", {})
                if not _pdata:
                    _pdata = _fetch_position_data(_t)
                    st.session_state[f"pos_data_{_t}"] = _pdata

                _df   = _pdata.get("df")
                _atr  = _pdata.get("atr14", 0)

                if _df is not None and _entry > 0 and _sl > 0:
                    # P03-W2: derive actual holding days dari entry_date → hari ini
                    _holding_est = 14  # default fallback (2 minggu — lebih realistis dari 10)
                    if _edate:
                        try:
                            from datetime import date as _date
                            _ed = _date.fromisoformat(_edate[:10])
                            _holding_est = max(1, (_date.today() - _ed).days)
                        except Exception:
                            pass
                    sigs = _engine.evaluate(
                        ticker           = _t,
                        entry_price      = _entry,
                        entry_date       = _edate,
                        sl_price         = _sl,
                        tp1_price        = _tp1,
                        tp2_price        = _tp2,
                        df               = _df,
                        atr14            = _atr,
                        holding_days_est = _holding_est,
                    )
                    _all_sig.extend(sigs)

        st.session_state["exit_signals"] = _all_sig

    _exit_signals = st.session_state.get("exit_signals", [])

    if not _exit_signals and "exit_signals" in st.session_state:
        st.markdown("""
<div style="background:rgba(0,255,102,0.04);border:1px solid rgba(0,255,102,0.15);
border-radius:var(--r-md);padding:0.8rem 1.2rem">
  <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);
  color:#00FF66">✅ Tidak ada exit signal — semua posisi masih dalam kondisi aman.</span>
</div>
""", unsafe_allow_html=True)

    elif _exit_signals:
        # Sort: CRITICAL dulu, lalu WARNING, lalu INFO
        _urg_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        _exit_signals.sort(key=lambda s: _urg_order.get(s.urgency, 3))

        _n_critical = sum(1 for s in _exit_signals if s.urgency == "CRITICAL")
        _n_warning  = sum(1 for s in _exit_signals if s.urgency == "WARNING")
        _n_info     = sum(1 for s in _exit_signals if s.urgency == "INFO")

        # Summary bar
        st.markdown(f"""
<div style="background:rgba(0,0,0,0.2);border:1px solid rgba(255,255,255,0.06);
border-radius:var(--r-sm);padding:0.5rem 1rem;margin-bottom:0.8rem;
font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
display:flex;gap:1.5rem;align-items:center">
  <span style="color:#94A3B8">EXIT SIGNALS</span>
  <span style="color:#EF4444;font-weight:700">🔴 CRITICAL: {_n_critical}</span>
  <span style="color:#F0B429;font-weight:700">🟡 WARNING: {_n_warning}</span>
  <span style="color:#4ADE80;font-weight:700">🟢 INFO: {_n_info}</span>
</div>
""", unsafe_allow_html=True)

        for _sig in _exit_signals:
            _uc  = _URGENCY_COLOR.get(_sig.urgency, "#64748B")
            _ac  = _ACTION_COLOR.get(_sig.action, "#64748B")
            _ico = _EXIT_ICON.get(_sig.exit_type, "●")
            _rgb_map = {"#EF4444": "239,68,68", "#F0B429": "240,180,41", "#4ADE80": "74,222,128"}
            _bg  = f"rgba({_rgb_map.get(_uc, '100,116,139')},0.05)"

            st.markdown(f"""
<div style="background:rgba(0,0,0,0.25);border:1px solid {_uc}35;
border-left:4px solid {_uc};border-radius:var(--r-md);
padding:0.65rem 1rem;margin-bottom:0.5rem">
  <div style="display:flex;align-items:center;gap:0.8rem;flex-wrap:wrap;margin-bottom:0.3rem">
    <span style="font-family:Orbitron,monospace;font-size:var(--text-base);
    font-weight:900;color:#E2E8F0">{_sig.ticker}</span>
    <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
    color:{_uc};font-weight:700">{_ico} {_sig.exit_type}</span>
    <span style="background:{_ac}20;border:1px solid {_ac}50;border-radius:3px;
    padding:1px 8px;font-family:Orbitron,monospace;font-size:var(--text-2xs);
    font-weight:700;color:{_ac}">{_sig.action}</span>
    <span style="margin-left:auto;font-family:Share Tech Mono,monospace;
    font-size:var(--text-xs);color:#94A3B8">
    Harga Rp{_sig.current_price:,.0f} · Trigger Rp{_sig.trigger_price:,.0f}
    </span>
  </div>
  <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);
  color:#CBD5E1;line-height:1.6">{_sig.message}</div>
</div>
""", unsafe_allow_html=True)
    else:
        st.markdown("""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
        color:#94A3B8">Klik "EVALUASI EXIT SIGNALS" untuk run exit engine.</p>""",
        unsafe_allow_html=True)

# ── Performance summary footer ────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
sec_head("◆ PERFORMANCE TRACKER")
try:
    from trade_logger import get_stats
    _stats = get_stats()
    _n     = _stats.get("total_closed", 0)
    _wr    = _stats.get("win_rate")
    _exp   = _stats.get("expectancy")
    _avg_r = _stats.get("avg_r")
    _note  = _stats.get("note", "")

    _stat_color = "#00FF66" if _n >= 30 else "#F0B429" if _n > 0 else "#64748B"
    _wr_str     = f"{_wr:.1f}%" if _wr is not None else "N/A"
    _exp_str    = f"{_exp:+.3f}R" if _exp is not None else "N/A"
    _avgr_str   = f"{_avg_r:+.2f}R" if _avg_r is not None else "N/A"

    _sc = st.columns(5)
    for _col, (_lbl, _val, _clr) in zip(_sc, [
        ("CLOSED TRADES", f"{_n}/30",  _stat_color),
        ("OPEN TRADES",   _stats.get("total_open", 0), TEXT_MAIN),
        ("WIN RATE",      _wr_str,     "#00FF66" if (_wr or 0) >= 50 else "#F0B429"),
        ("EXPECTANCY",    _exp_str,    "#00FF66" if (_exp or 0) > 0 else "#EF4444"),
        ("AVG R/TRADE",   _avgr_str,   "#00FF66" if (_avg_r or 0) > 0 else "#EF4444"),
    ]):
        with _col:
            st.markdown(f"""
<div class="m-card" style="padding:0.55rem 0.7rem">
  <div class="m-lbl" style="font-size:var(--text-2xs)">{_lbl}</div>
  <div class="m-val" style="color:{_clr};font-size:var(--text-xl)">{_val}</div>
</div>""", unsafe_allow_html=True)

    if _note:
        st.markdown(f"""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
        color:var(--text-muted);margin-top:0.3rem">{_note}</p>""", unsafe_allow_html=True)
except Exception:
    st.markdown("""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
    color:#94A3B8">Trade logger tidak tersedia.</p>""", unsafe_allow_html=True)
