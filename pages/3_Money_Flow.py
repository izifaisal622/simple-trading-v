"""Simple Trading V7 — Page 03: Money Flow Scanner"""
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import streamlit as st

ROOT     = Path(__file__).parent.parent
LOGS_DIR = ROOT / "logs"
DATA_DIR = ROOT / "data"
RESULTS_FILE = LOGS_DIR / "daily_results.json"
sys.path.insert(0, str(ROOT))

from assets_ui import (
    get_page_css, render_sidebar, render_page_header, render_regime_bar,
    render_empty_state, sec_head,
    signal_badge, score_badge, fmt_rp, fmt_bn,
    SIG_COLORS, NEON_GREEN, TEXT_MAIN, TEXT_MUTED, TEXT_DIM,
    BG_CARD,
)

# ─── page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Money Flow · STV",
    page_icon="💸",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(get_page_css("dashboard"), unsafe_allow_html=True)

# ─── version ──────────────────────────────────────────────────────────────────
try:
    _vdata    = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    _ver_full = _vdata.get("version", "?")
    _ver_accent = "V" + _ver_full
except Exception:
    _ver_full = "?"; _ver_accent = "V?"

# ─── load context ─────────────────────────────────────────────────────────────
ctx       = {}
scan_date = "—"
regime    = "UNKNOWN"
try:
    if RESULTS_FILE.exists():
        _d = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
        ctx       = _d.get("whale_context", {})
        scan_date = (_d.get("date","")[:10] or "—")
        regime    = ctx.get("cycle", "UNKNOWN")
except Exception:
    pass

# ─── sidebar ──────────────────────────────────────────────────────────────────
render_sidebar("money_flow", scan_date=scan_date, regime=regime)

# Token input di sidebar
with st.sidebar:
    st.markdown('<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:var(--text-muted);letter-spacing:.1em;margin:12px 0 4px">STOCKBIT TOKEN</p>', unsafe_allow_html=True)
    try:
        from agents.ownership_agent import OwnershipAgent
        _oa = OwnershipAgent()
        _tok = _oa.get_stockbit_token()
        _tok_ok = bool(_tok)
        _tok_lbl  = "✅ AKTIF" if _tok_ok else "⚠ TIDAK ADA"
        _tok_color = "var(--c-success)" if _tok_ok else "var(--c-danger)"
    except Exception:
        _oa = None; _tok_ok = False
        _tok_lbl = "⚠ ERROR"; _tok_color = "var(--c-danger)"

    st.markdown(f'<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:{_tok_color};margin-bottom:6px">{_tok_lbl}</div>', unsafe_allow_html=True)

    if "show_mf_token" not in st.session_state:
        st.session_state.show_mf_token = False
    _lbl = "[−] TOKEN" if st.session_state.show_mf_token else "[+] TOKEN"
    if st.button(_lbl, key="mf_tok_toggle", use_container_width=True):
        st.session_state.show_mf_token = not st.session_state.show_mf_token
    if st.session_state.show_mf_token and _oa:
        with st.form("mf_token_form", clear_on_submit=True):
            new_tok = st.text_input("Paste Bearer Token", type="password",
                                    placeholder="eyJhbGci...",
                                    label_visibility="collapsed")
            if st.form_submit_button("💾 SAVE", use_container_width=True):
                if new_tok and new_tok.startswith("ey"):
                    _oa.save_stockbit_token(new_tok)
                    st.session_state.show_mf_token = False
                    st.success("✅ Token saved!")
                    st.rerun()
                else:
                    st.error("Harus diawali 'ey...'")
        st.markdown(
            '<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:var(--text-dim);line-height:1.6">'
            '1. Login Stockbit di browser<br>'
            '2. F12 → Network → filter "exodus"<br>'
            '3. Request apapun → Headers<br>'
            '4. Copy nilai setelah "Bearer "</p>',
            unsafe_allow_html=True,
        )

# ─── page header ──────────────────────────────────────────────────────────────
render_page_header(
    eyebrow  = "◆ MODULE 03 · MONEY FLOW SCANNER",
    title    = "SIMPLE TRADING ",
    accent   = _ver_accent,
    subtitle = "◈ BROKER NET BUY · SMART MONEY · RETAIL MOMENTUM · FLOW TRACKING",
    scan_date= scan_date,
)

# ─── scan controls — setara Whale ─────────────────────────────────────────────
sec_head("◆ SCAN CONTROLS")

c1, c2, c3, c4, c5 = st.columns([1.6, 1.2, 1, 1.3, 1])
with c1: run_scan      = st.button("⟳ RUN MONEY FLOW SCAN", type="primary", use_container_width=True)
with c2: mf_mode       = st.selectbox("UNIVERSE", ["Full IDX (~350)", "Watchlist (~100)"], key="mf_mode")
with c3: mf_top_n      = st.number_input("TOP N", 10, 200, 50, 10, key="mf_topn")
with c4: mf_min_vol    = st.number_input("MIN VOL RATIO", 0.5, 10.0, 1.0, 0.5, key="mf_minvol")
with c5: mf_max_work   = st.number_input("WORKERS", 5, 50, 20, 5, key="mf_workers")

# ─── scan results context ─────────────────────────────────────────────────────
_mf_results = st.session_state.get("mf_results", [])
_mf_context = st.session_state.get("mf_context", {})
_mf_time    = st.session_state.get("mf_scan_time", None)

# Filter controls (below scan button, shown only when results exist)
filter_signal = ["WHALE_ACCUMULATION", "INSTITUTIONAL_BUY", "RETAIL_MOMENTUM"]
filter_source = ["stockbit", "proxy_ohlcv"]
if _mf_results:
    fc1, fc2, fc3, fc4 = st.columns([2, 2, 2, 1])
    with fc1:
        filter_signal = st.multiselect("SIGNAL FILTER",
            ["WHALE_ACCUMULATION","INSTITUTIONAL_BUY","RETAIL_MOMENTUM","NEUTRAL","DISTRIBUTION"],
            default=["WHALE_ACCUMULATION","INSTITUTIONAL_BUY","RETAIL_MOMENTUM"],
            key="mf_f_sig", label_visibility="collapsed")
    with fc2:
        filter_source = st.multiselect("SOURCE",
            ["stockbit","proxy_ohlcv"], default=["stockbit","proxy_ohlcv"],
            key="mf_f_src", label_visibility="collapsed")
    with fc3:
        filter_min_vol = st.slider("MIN VOL RATIO FILTER", 0.5, 5.0, 1.0, 0.1, key="mf_f_vol")
    with fc4:
        sort_by = st.selectbox("SORT", ["Vol Ratio","Signal","Source"], key="mf_sort", label_visibility="collapsed")

# ─── run scan ─────────────────────────────────────────────────────────────────
if run_scan:
    with st.spinner("◈ SCANNING MONEY FLOW · BROKER DATA · VOLUME PROXY..."):
        try:
            from agents.flow_scanner import FlowScanner
            scanner = FlowScanner()
            max_t   = int(mf_top_n)
            results = scanner.scan(max_workers=int(mf_max_work), max_tickers=max_t)

            # Apply vol filter
            results = [r for r in results if (r.get("vol_ratio") or 1.0) >= mf_min_vol]

            # Build context
            sig_counts = Counter(r.get("signal") for r in results)
            src_counts = Counter(r.get("source") for r in results)
            buy_flow   = sum(r.get("smart_net", 0) or 0 for r in results if (r.get("smart_net") or 0) > 0)
            sell_flow  = sum(r.get("smart_net", 0) or 0 for r in results if (r.get("smart_net") or 0) < 0)

            mf_ctx = {
                "total": len(results), "sig_counts": dict(sig_counts),
                "src_counts": dict(src_counts),
                "buy_flow": buy_flow, "sell_flow": abs(sell_flow),
                "whale_count": sig_counts.get("WHALE_ACCUMULATION", 0),
                "inst_count":  sig_counts.get("INSTITUTIONAL_BUY", 0),
                "retail_count":sig_counts.get("RETAIL_MOMENTUM", 0),
                "dist_count":  sig_counts.get("DISTRIBUTION", 0),
                "stockbit_count": src_counts.get("stockbit", 0),
                "proxy_count":    src_counts.get("proxy_ohlcv", 0),
            }

            st.session_state.mf_results   = results
            st.session_state.mf_context   = mf_ctx
            st.session_state.mf_scan_time = datetime.now().strftime("%H:%M:%S")

            # Save to daily_results.json
            existing = {}
            if RESULTS_FILE.exists():
                try: existing = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
                except Exception: pass
            existing.update({
                "mf_results": results, "mf_context": mf_ctx,
                "mf_date": datetime.now().isoformat(),
            })
            RESULTS_FILE.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")

            whale_c  = sig_counts.get("WHALE_ACCUMULATION", 0)
            inst_c   = sig_counts.get("INSTITUTIONAL_BUY", 0)
            retail_c = sig_counts.get("RETAIL_MOMENTUM", 0)
            dist_c   = sig_counts.get("DISTRIBUTION", 0)
            st.success(f"◈ DONE — {len(results)} results | 🐋{whale_c} whale | 🏦{inst_c} inst | 👥{retail_c} retail | ⚠{dist_c} dist")
            st.rerun()
        except Exception as e:
            st.error(f"ERROR: {e}")
            import traceback; st.code(traceback.format_exc())

# ─── display results ──────────────────────────────────────────────────────────
if not _mf_results:
    render_empty_state(
        icon     = "💸",
        title    = "NO FLOW DATA",
        subtitle = "Klik RUN MONEY FLOW SCAN untuk mulai.\nStockbit token aktif → broker net buy realtime.\nToken tidak ada → proxy dari volume + price movement.",
        command  = "python orchestrator.py --mode flow",
    )
else:
    # ── Summary stats (setara Whale 8-box) ────────────────────────────────────
    mf_ctx = _mf_context
    _whale_c  = mf_ctx.get("whale_count", 0)
    _inst_c   = mf_ctx.get("inst_count", 0)
    _retail_c = mf_ctx.get("retail_count", 0)
    _dist_c   = mf_ctx.get("dist_count", 0)
    _sb_c     = mf_ctx.get("stockbit_count", 0)
    _px_c     = mf_ctx.get("proxy_count", 0)
    _total    = mf_ctx.get("total", len(_mf_results))

    cols8 = st.columns(8)
    mdata = [
        ("TOTAL",        _total,    TEXT_MAIN),
        ("🐋 WHALE",     _whale_c,  NEON_GREEN),
        ("🏦 INST. BUY", _inst_c,   "var(--c-info)"),
        ("👥 RETAIL",    _retail_c, "var(--c-warning)"),
        ("⚠ DISTRIBUSI", _dist_c,  "var(--c-danger)"),
        ("🟢 STOCKBIT",  _sb_c,     NEON_GREEN),
        ("🟡 PROXY",     _px_c,     "var(--c-warning)"),
        ("⏱ SCAN",       _mf_time or "—", "var(--text-muted)"),
    ]
    for col, (lbl, val, clr) in zip(cols8, mdata):
        with col:
            st.markdown(
                f'<div class="m-card" style="padding:0.55rem 0.7rem">'
                f'<div class="m-lbl" style="font-size:var(--text-2xs)">{lbl}</div>'
                f'<div class="m-val" style="color:{clr};font-size:var(--text-xl)">{val}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── Bias strip ────────────────────────────────────────────────────────────
    buy_val  = mf_ctx.get("buy_flow", 0)
    sell_val = mf_ctx.get("sell_flow", 0)
    if buy_val > sell_val * 1.5:
        bias, bias_color = "STRONG BUY", NEON_GREEN
    elif buy_val > sell_val:
        bias, bias_color = "BUY", "var(--c-success)"
    elif sell_val > buy_val * 1.5:
        bias, bias_color = "STRONG SELL", "var(--c-danger)"
    elif sell_val > buy_val:
        bias, bias_color = "SELL", "var(--c-danger)"
    else:
        bias, bias_color = "NEUTRAL", "var(--text-muted)"

    sig_breakdown = "  ·  ".join([
        f'<b style="color:var(--text-primary)">{k.replace("_"," ")}</b> '
        f'<span style="color:{SIG_COLORS.get(k,NEON_GREEN)}">{v}</span>'
        for k, v in sorted(mf_ctx.get("sig_counts", {}).items(), key=lambda x: -x[1])
    ]) or "—"

    st.markdown(f"""
    <div style="background:var(--bg-card);border:1px solid rgba(0,255,102,0.06);border-radius:var(--r-sm);
    padding:0.55rem 1.2rem;margin:0.6rem 0;font-family:Share Tech Mono,monospace;
    font-size:var(--text-xs);display:flex;gap:2rem;align-items:center;flex-wrap:wrap">
      <span style="color:var(--text-muted)">FLOW BIAS</span>
      <span style="font-family:Orbitron,monospace;font-size:var(--text-base);font-weight:700;color:{bias_color}">{bias}</span>
      <span style="color:var(--text-muted)">SIGNALS: {sig_breakdown}</span>
      <span style="color:var(--text-muted);margin-left:auto">SCAN: {_mf_time or "—"}</span>
    </div>
    """, unsafe_allow_html=True)

    # ── Filter & sort ─────────────────────────────────────────────────────────
    filtered = [r for r in _mf_results
                if r.get("signal") in filter_signal
                and r.get("source") in filter_source
                and (r.get("vol_ratio") or 1.0) >= filter_min_vol]

    # Sort
    sort_by_val = st.session_state.get("mf_sort", "Vol Ratio")
    if sort_by_val == "Vol Ratio":
        filtered.sort(key=lambda x: -(x.get("vol_ratio") or 0))
    elif sort_by_val == "Signal":
        _rank = {"WHALE_ACCUMULATION":0,"INSTITUTIONAL_BUY":1,"RETAIL_MOMENTUM":2,"NEUTRAL":3,"DISTRIBUTION":4}
        filtered.sort(key=lambda x: _rank.get(x.get("signal","NEUTRAL"),3))
    elif sort_by_val == "Source":
        filtered.sort(key=lambda x: x.get("source",""))

    st.markdown(
        f'<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--text-muted)">'
        f'SHOWING {len(filtered)} OF {len(_mf_results)}</p>',
        unsafe_allow_html=True,
    )

    # ── Copy tickers ──────────────────────────────────────────────────────────
    if filtered:
        if st.button(f"📋 COPY {len(filtered)} TICKERS", key="mf_copy"):
            st.code(", ".join(r.get("ticker","") for r in filtered))

    # ── Tabs by signal type ────────────────────────────────────────────────────
    _wh = [r for r in filtered if r.get("signal") == "WHALE_ACCUMULATION"]
    _in = [r for r in filtered if r.get("signal") == "INSTITUTIONAL_BUY"]
    _re = [r for r in filtered if r.get("signal") == "RETAIL_MOMENTUM"]
    _ne = [r for r in filtered if r.get("signal") == "NEUTRAL"]
    _di = [r for r in filtered if r.get("signal") == "DISTRIBUTION"]

    tab_wh, tab_in, tab_re, tab_ne, tab_di, tab_all = st.tabs([
        f"🐋 WHALE ({len(_wh)})",
        f"🏦 INST. ({len(_in)})",
        f"👥 RETAIL ({len(_re)})",
        f"◯ NEUTRAL ({len(_ne)})",
        f"⚠ DIST. ({len(_di)})",
        f"◆ SEMUA ({len(filtered)})",
    ])

    def _render_cards(items: list) -> None:
        if not items:
            st.markdown('<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--text-muted)">Tidak ada data untuk filter ini.</p>', unsafe_allow_html=True)
            return
        lc, rc = st.columns(2)
        for i, r in enumerate(items):
            (lc if i % 2 == 0 else rc).markdown(_flow_card(r), unsafe_allow_html=True)

    with tab_wh:  _render_cards(_wh)
    with tab_in:  _render_cards(_in)
    with tab_re:  _render_cards(_re)
    with tab_ne:  _render_cards(_ne)
    with tab_di:  _render_cards(_di)
    with tab_all: _render_cards(filtered)


# ─── card renderer ────────────────────────────────────────────────────────────
def _source_badge(source: str) -> str:
    if source == "stockbit":
        c, lbl = NEON_GREEN, "🟢 STOCKBIT"
    else:
        c, lbl = "var(--c-warning)", "🟡 PROXY"
    return (f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            f'color:{c};border:1px solid {c};padding:2px 7px;border-radius:3px">{lbl}</span>')

def _conv_bar(ratio: float, max_ratio: float = 5.0) -> str:
    pct    = min(ratio / max_ratio, 1.0)
    filled = int(pct * 12)
    empty  = 12 - filled
    color  = NEON_GREEN if ratio >= 2.0 else "var(--c-warning)" if ratio >= 1.5 else "var(--text-dim)"
    return (f'<span style="font-family:monospace;color:{color};letter-spacing:-1px">'
            f'{"█"*filled}<span style="color:var(--bg-raised)">{"█"*empty}</span></span>')

def _flow_card(r: dict) -> str:
    ticker    = r.get("ticker", "?")
    signal    = r.get("signal", "NEUTRAL")
    note      = r.get("note", "")
    source    = r.get("source", "proxy_ohlcv")
    price     = r.get("price")
    pct_chg   = r.get("pct_chg") or 0.0
    vol_ratio = r.get("vol_ratio") or 1.0
    smart_net = r.get("smart_net")
    retail_net= r.get("retail_net")
    dom_type  = r.get("dominant_type", "")
    sector    = r.get("sector", "")
    val_bn    = r.get("val_bn")
    pct_52w   = r.get("pct_52w_high")

    sig_color  = SIG_COLORS.get(signal, "#6b7280")
    price_str  = fmt_rp(price) if price else "—"
    pct_color  = "var(--c-success)" if pct_chg >= 0 else "var(--c-danger)"
    pct_str    = f"+{pct_chg:.1f}%" if pct_chg >= 0 else f"{pct_chg:.1f}%"
    vol_color  = NEON_GREEN if vol_ratio >= 2 else "var(--c-warning)" if vol_ratio >= 1.5 else "var(--text-muted)"

    # meta
    meta = []
    if sector: meta.append(f'<span style="color:var(--text-muted)">{sector}</span>')
    if val_bn:  meta.append(f'<span style="color:var(--text-muted)">Rp{val_bn:.1f}Bn</span>')
    if pct_52w is not None:
        c52 = ("var(--c-success)" if pct_52w >= -10 else "var(--c-warning)" if pct_52w >= -30 else "var(--c-danger)")
        meta.append(f'<span style="color:{c52}">52W {pct_52w:+.1f}%</span>')
    meta_html = " · ".join(meta)

    # flow row (stockbit only)
    flow_row = ""
    if source == "stockbit" and (smart_net is not None or retail_net is not None):
        sc = "var(--c-success)" if (smart_net or 0) > 0 else "var(--c-danger)" if (smart_net or 0) < 0 else "var(--text-muted)"
        flow_row = (
            f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:8px 0;'
            f'padding:8px;background:rgba(255,255,255,.03);border-radius:5px">'
            f'<div><div style="font-size:var(--text-2xs);color:var(--text-muted);font-family:Share Tech Mono,monospace">SMART NET</div>'
            f'<div style="font-size:var(--text-sm);color:{sc};font-family:Share Tech Mono,monospace">'
            f'{f"{smart_net:+,} lot" if smart_net is not None else "—"}</div></div>'
            f'<div><div style="font-size:var(--text-2xs);color:var(--text-muted);font-family:Share Tech Mono,monospace">RETAIL NET</div>'
            f'<div style="font-size:var(--text-sm);color:var(--text-secondary);font-family:Share Tech Mono,monospace">'
            f'{f"{retail_net:+,} lot" if retail_net is not None else "—"}</div></div>'
            f'</div>'
        )

    return f"""
<div style="background:var(--bg-card);border:1px solid rgba(255,255,255,.07);
  border-left:3px solid {sig_color};border-radius:var(--r-md);
  padding:var(--sp-4);margin-bottom:var(--sp-3)">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:6px">
    <div>
      <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xl);
        color:#e2e8f0;font-weight:700;letter-spacing:.04em">{ticker}</span>
      {f'<span style="font-size:var(--text-xs);color:var(--text-muted);margin-left:8px;font-family:Share Tech Mono,monospace">{dom_type}</span>' if dom_type else ""}
    </div>
    <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
      {signal_badge(signal)}
      {_source_badge(source)}
    </div>
  </div>
  {f'<div style="font-size:var(--text-xs);font-family:Share Tech Mono,monospace;color:var(--text-muted);margin-bottom:8px">{meta_html}</div>' if meta_html else ""}
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:8px">
    <div style="padding:7px;background:rgba(255,255,255,.03);border-radius:5px;text-align:center">
      <div style="font-size:var(--text-2xs);color:var(--text-muted);font-family:Share Tech Mono,monospace">HARGA</div>
      <div style="font-size:var(--text-md);color:#e2e8f0;font-family:Share Tech Mono,monospace">{price_str}</div>
    </div>
    <div style="padding:7px;background:rgba(255,255,255,.03);border-radius:5px;text-align:center">
      <div style="font-size:var(--text-2xs);color:var(--text-muted);font-family:Share Tech Mono,monospace">CHG</div>
      <div style="font-size:var(--text-md);color:{pct_color};font-family:Share Tech Mono,monospace">{pct_str}</div>
    </div>
    <div style="padding:7px;background:rgba(255,255,255,.03);border-radius:5px;text-align:center">
      <div style="font-size:var(--text-2xs);color:var(--text-muted);font-family:Share Tech Mono,monospace">VOL RATIO</div>
      <div style="font-size:var(--text-md);color:{vol_color};font-family:Share Tech Mono,monospace">{vol_ratio:.1f}×</div>
    </div>
  </div>
  <div style="margin-bottom:6px">
    <div style="font-size:var(--text-2xs);color:var(--text-muted);font-family:Share Tech Mono,monospace;margin-bottom:2px">VOL CONVICTION</div>
    {_conv_bar(vol_ratio)} <span style="font-size:var(--text-2xs);color:var(--text-muted);margin-left:6px;font-family:Share Tech Mono,monospace">{vol_ratio:.1f}× avg</span>
  </div>
  {flow_row}
  <div style="font-size:var(--text-xs);color:var(--text-muted);font-family:Share Tech Mono,monospace;
    border-top:1px solid rgba(255,255,255,.05);padding-top:6px;margin-top:4px">{note}</div>
</div>
"""
