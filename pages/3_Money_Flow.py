"""Simple Trading V8 — Page 03: Money Flow · Daily Top Mover Scanner"""
import json
import sys
from datetime import datetime
from pathlib import Path
from collections import Counter

import streamlit as st

ROOT         = Path(__file__).parent.parent
LOGS_DIR     = ROOT / "logs"
RESULTS_FILE = LOGS_DIR / "daily_results.json"
sys.path.insert(0, str(ROOT))

from assets_ui import (
    get_page_css, render_sidebar, render_page_header,
    render_empty_state, sec_head,
    signal_badge, fmt_rp,
    SIG_COLORS, NEON_GREEN, TEXT_MAIN, TEXT_MUTED, TEXT_DIM,
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
    _vdata      = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    _ver_accent = "V" + _vdata.get("version", "?")
except Exception:
    _ver_accent = "V?"

# ─── load context (sidebar regime) ────────────────────────────────────────────
scan_date = "—"
regime    = "UNKNOWN"
try:
    if RESULTS_FILE.exists():
        _d        = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
        ctx       = _d.get("whale_context", {})
        scan_date = (_d.get("date", "")[:10] or "—")
        regime    = ctx.get("cycle", "UNKNOWN")
except Exception:
    pass

render_sidebar("money_flow", scan_date=scan_date, regime=regime)

# ─── page header ──────────────────────────────────────────────────────────────
render_page_header(
    eyebrow  = "◆ MODULE 03 · MONEY FLOW SCANNER",
    title    = "SIMPLE TRADING ",
    accent   = _ver_accent,
    subtitle = "◈ DAILY TOP MOVER · VOLUME SPIKE · PRICE MOMENTUM · IDX UNIVERSE",
    scan_date= scan_date,
)

# ─── scan controls ────────────────────────────────────────────────────────────
sec_head("◆ SCAN CONTROLS")

c1, c2, c3, c4, c5 = st.columns([1.6, 1, 1, 1.2, 1])
with c1: run_scan    = st.button("⟳ RUN MONEY FLOW SCAN", type="primary", use_container_width=True)
with c2: top_n       = st.number_input("TOP N", 10, 100, 30, 5, key="mf_topn")
with c3: min_vol     = st.number_input("MIN VOL RATIO", 0.5, 10.0, 1.5, 0.5, key="mf_minvol")
with c4: min_val     = st.number_input("MIN VALUE (Bn)", 1.0, 50.0, 5.0, 1.0, key="mf_minval")
with c5: max_workers = st.number_input("WORKERS", 5, 50, 20, 5, key="mf_workers")

# ─── run scan ─────────────────────────────────────────────────────────────────
if run_scan:
    with st.spinner("◈ SCANNING DAILY MOVERS · VOLUME · PRICE MOMENTUM..."):
        try:
            from agents.whale_scanner import WhaleScanner
            from core.data_feed import get_dynamic_universe

            scanner          = WhaleScanner()
            scanner.min_value_bn = float(min_val)
            universe         = [t + ".JK" for t in get_dynamic_universe()]

            raw_results, ctx = scanner.scan(
                tickers     = universe,
                top_n       = 200,
                max_workers = int(max_workers),
            )

            # Filter by vol ratio
            results = [r for r in raw_results if (r.get("vol_ratio") or 0) >= float(min_vol)]

            # Sort by chg_pct descending — top gainer first
            results.sort(key=lambda x: -(x.get("chg_pct") or 0))

            # Cap to top_n
            results = results[:int(top_n)]

            # Build sector breakdown
            sector_counts = Counter(r.get("sector", "OTHER") for r in results)

            mf_ctx = {
                "total":          len(results),
                "scan_time":      datetime.now().strftime("%H:%M:%S"),
                "sector_counts":  dict(sector_counts),
                "top_gainer_pct": results[0].get("chg_pct", 0) if results else 0,
                "avg_vol_ratio":  round(
                    sum(r.get("vol_ratio", 1) for r in results) / max(len(results), 1), 1
                ),
            }

            st.session_state["mf_results"] = results
            st.session_state["mf_context"] = mf_ctx

            # Save to daily_results.json
            existing = {}
            if RESULTS_FILE.exists():
                try: existing = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
                except Exception: pass
            existing.update({
                "mf_results": results,
                "mf_context": mf_ctx,
                "mf_date":    datetime.now().isoformat(),
            })
            RESULTS_FILE.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")

            st.success(f"◈ DONE — {len(results)} movers | top gainer +{mf_ctx['top_gainer_pct']:.1f}% | avg vol {mf_ctx['avg_vol_ratio']:.1f}×")

        except Exception as e:
            import traceback
            st.error(f"ERROR: {e}")
            st.code(traceback.format_exc())


# ─── card builder ─────────────────────────────────────────────────────────────
def _build_card(r: dict) -> str:
    ticker    = r.get("ticker", "?").replace(".JK", "")
    signal    = r.get("signal", "NEUTRAL")
    sector    = r.get("sector", "OTHER")
    close     = r.get("close")
    chg_pct   = r.get("chg_pct") or 0.0
    vol_ratio = r.get("vol_ratio") or 1.0
    value_bn  = r.get("value_bn") or 0.0
    floor_pct = r.get("pct_above_floor")
    pct_52w   = r.get("pct_52w_high") or r.get("pct_above_floor")
    momentum  = r.get("momentum", "")
    note      = r.get("pengeringan_desc") or r.get("note", "")
    vol_ma    = r.get("vol_ma20") or 0

    sig_color  = SIG_COLORS.get(signal, "#6b7280")
    price_str  = fmt_rp(close) if close else "—"
    chg_color  = NEON_GREEN if chg_pct >= 0 else "var(--c-danger)"
    chg_str    = f"+{chg_pct:.2f}%" if chg_pct >= 0 else f"{chg_pct:.2f}%"
    vol_color  = NEON_GREEN if vol_ratio >= 2 else "var(--c-warning)" if vol_ratio >= 1.5 else TEXT_MUTED

    # Conviction bar
    filled = min(int(vol_ratio / 5.0 * 12), 12)
    empty  = 12 - filled
    bar    = (f'<span style="font-family:monospace;color:{vol_color};letter-spacing:-1px">'
              f'{"█"*filled}'
              f'<span style="color:var(--bg-raised)">{"█"*empty}</span></span>')

    # Signal badge pre-built
    sig_badge = signal_badge(signal)

    # Sector pill
    sec_pill = (f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
                f'color:var(--text-muted);border:1px solid rgba(255,255,255,.1);'
                f'padding:1px 6px;border-radius:3px">{sector}</span>')

    # Momentum tag
    mom_color = {"ACCELERATING": NEON_GREEN, "REVERSING": "var(--c-warning)",
                 "DECLINING": "var(--c-danger)", "FLAT": TEXT_DIM}.get(momentum, TEXT_DIM)
    mom_tag = (f'<span style="font-size:var(--text-2xs);color:{mom_color};'
               f'font-family:Share Tech Mono,monospace">{momentum}</span>') if momentum else ""

    # 52w position
    pct52_html = ""
    if pct_52w is not None:
        c52 = ("var(--c-success)" if pct_52w >= -10 else
               "var(--c-warning)" if pct_52w >= -30 else "var(--c-danger)")
        pct52_html = (f'<span style="font-size:var(--text-2xs);color:{c52};'
                      f'font-family:Share Tech Mono,monospace">52W {pct_52w:+.1f}%</span>')

    return f"""
<div style="background:var(--bg-card);border:1px solid rgba(255,255,255,.07);
  border-left:3px solid {sig_color};border-radius:var(--r-md);
  padding:var(--sp-4);margin-bottom:var(--sp-3)">

  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:6px">
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
      <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xl);
        color:#e2e8f0;font-weight:700;letter-spacing:.04em">{ticker}</span>
      {sec_pill}
      {mom_tag}
    </div>
    <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
      {sig_badge}
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;margin-bottom:8px">
    <div style="padding:7px;background:rgba(255,255,255,.03);border-radius:5px;text-align:center">
      <div style="font-size:var(--text-2xs);color:var(--text-muted);font-family:Share Tech Mono,monospace">HARGA</div>
      <div style="font-size:var(--text-sm);color:#e2e8f0;font-family:Share Tech Mono,monospace">{price_str}</div>
    </div>
    <div style="padding:7px;background:rgba(255,255,255,.03);border-radius:5px;text-align:center">
      <div style="font-size:var(--text-2xs);color:var(--text-muted);font-family:Share Tech Mono,monospace">CHG 1D</div>
      <div style="font-size:var(--text-sm);color:{chg_color};font-family:Share Tech Mono,monospace;font-weight:700">{chg_str}</div>
    </div>
    <div style="padding:7px;background:rgba(255,255,255,.03);border-radius:5px;text-align:center">
      <div style="font-size:var(--text-2xs);color:var(--text-muted);font-family:Share Tech Mono,monospace">VOL RATIO</div>
      <div style="font-size:var(--text-sm);color:{vol_color};font-family:Share Tech Mono,monospace">{vol_ratio:.1f}×</div>
    </div>
    <div style="padding:7px;background:rgba(255,255,255,.03);border-radius:5px;text-align:center">
      <div style="font-size:var(--text-2xs);color:var(--text-muted);font-family:Share Tech Mono,monospace">VALUE</div>
      <div style="font-size:var(--text-sm);color:var(--text-secondary);font-family:Share Tech Mono,monospace">Rp{value_bn:.1f}Bn</div>
    </div>
  </div>

  <div style="margin-bottom:6px">
    <div style="font-size:var(--text-2xs);color:var(--text-muted);font-family:Share Tech Mono,monospace;margin-bottom:2px">
      VOL CONVICTION {pct52_html}
    </div>
    {bar} <span style="font-size:var(--text-2xs);color:var(--text-muted);margin-left:6px;font-family:Share Tech Mono,monospace">{vol_ratio:.1f}× avg</span>
  </div>

  <div style="font-size:var(--text-xs);color:var(--text-muted);font-family:Share Tech Mono,monospace;
    border-top:1px solid rgba(255,255,255,.05);padding-top:6px;margin-top:4px;line-height:1.5">{note}</div>
</div>
"""

# ─── read results fresh ────────────────────────────────────────────────────────
_results = st.session_state.get("mf_results", [])
_ctx     = st.session_state.get("mf_context", {})

# ─── display ──────────────────────────────────────────────────────────────────
if not _results:
    render_empty_state(
        icon     = "💸",
        title    = "NO FLOW DATA",
        subtitle = "Klik RUN MONEY FLOW SCAN untuk mulai.\nScan universe IDX → sort by % gain harian + volume spike.",
        command  = "python orchestrator.py --mode flow",
    )
else:
    # ── Summary bar ───────────────────────────────────────────────────────────
    _scan_time  = _ctx.get("scan_time", "—")
    _total      = _ctx.get("total", len(_results))
    _top_gain   = _ctx.get("top_gainer_pct", 0)
    _avg_vol    = _ctx.get("avg_vol_ratio", 0)
    _sec_counts = _ctx.get("sector_counts", {})

    cols5 = st.columns(5)
    _summary = [
        ("TOTAL MOVERS", _total,              TEXT_MAIN),
        ("TOP GAINER",   f"+{_top_gain:.1f}%", NEON_GREEN),
        ("AVG VOL RATIO", f"{_avg_vol:.1f}×",  NEON_GREEN),
        ("SECTORS",       len(_sec_counts),    TEXT_MUTED),
        ("⏱ SCAN",        _scan_time,          TEXT_MUTED),
    ]
    for col, (lbl, val, clr) in zip(cols5, _summary):
        with col:
            st.markdown(
                f'<div class="m-card" style="padding:0.55rem 0.7rem">'
                f'<div class="m-lbl" style="font-size:var(--text-2xs)">{lbl}</div>'
                f'<div class="m-val" style="color:{clr};font-size:var(--text-xl)">{val}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── Filters ───────────────────────────────────────────────────────────────
    all_sectors = sorted(set(r.get("sector", "OTHER") for r in _results))
    fc1, fc2, fc3 = st.columns([2, 2, 1])
    with fc1:
        sel_sectors = st.multiselect(
            "FILTER SEKTOR", all_sectors, default=all_sectors,
            key="mf_sectors", label_visibility="collapsed",
        )
    with fc2:
        sort_by = st.selectbox(
            "SORT BY", ["% Gain", "Vol Ratio", "Value (Bn)"],
            key="mf_sort", label_visibility="collapsed",
        )
    with fc3:
        min_chg = st.number_input("MIN CHG %", -10.0, 20.0, 0.0, 0.5, key="mf_minchg")

    # ── Apply filters ─────────────────────────────────────────────────────────
    filtered = [
        r for r in _results
        if r.get("sector", "OTHER") in sel_sectors
        and (r.get("chg_pct") or 0) >= min_chg
    ]

    sort_key = {
        "% Gain":      lambda x: -(x.get("chg_pct") or 0),
        "Vol Ratio":   lambda x: -(x.get("vol_ratio") or 0),
        "Value (Bn)":  lambda x: -(x.get("value_bn") or 0),
    }.get(sort_by, lambda x: -(x.get("chg_pct") or 0))
    filtered.sort(key=sort_key)

    st.markdown(
        f'<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
        f'color:var(--text-muted)">SHOWING {len(filtered)} OF {len(_results)}</p>',
        unsafe_allow_html=True,
    )

    # ── Copy tickers ──────────────────────────────────────────────────────────
    if filtered:
        if st.button(f"📋 COPY {len(filtered)} TICKERS", key="mf_copy"):
            tickers_str = ", ".join(r.get("ticker", "").replace(".JK", "") for r in filtered)
            st.code(tickers_str)

    # ── Cards ─────────────────────────────────────────────────────────────────
    if filtered:
        lc, rc = st.columns(2)
        for i, r in enumerate(filtered):
            card_html = _build_card(r)
            (lc if i % 2 == 0 else rc).markdown(card_html, unsafe_allow_html=True)
    else:
        st.markdown(
            '<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            'color:var(--text-muted)">Tidak ada data untuk filter ini.</p>',
            unsafe_allow_html=True,
        )


