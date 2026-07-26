"""
Simple Trading V10 — VIDYA+SMC Retest-Zone Scanner (Page 1, REPLACE TOTAL v10.0.7)
Menggantikan sepenuhnya EMA-XBO (DailyEMAEngine/box-breakout) lama.

Metodologi: port dari indikator Pine "Volumatic VIDYA + SMC" milik user
(BigBeluga VIDYA trend + LuxAlgo SMC internal structure/OB, CC BY-NC-SA 4.0),
dibangun bertahap teruji (core/ob_engine.py tahap 1, core/conviction_engine.py
tahap 2, agents/zone_scanner.py tahap 3) — walk-forward, anti-lookahead
diverifikasi truncation-invariant, diuji thd 5 ticker data IDX nyata sebelum
integrasi halaman ini.

Skema conviction 20%->100% (disepakati eksplisit dgn user):
  20% zona terbentuk | +20%/+20% retest hold 1/2 hari (cap di 60%)
  +15% VIDYA bullish saat retest | +15% volume delta menguat | +10% struktur aligned
Aturan keras: retest divalidasi thd harga REAL; close < zona_bottom kapan pun
= invalidasi total ke 0%; kadaluarsa 5 hari bursa tanpa retest cap; zona usang
begitu pivot internal digantikan pivot baru (mekanisme Pine asli, v10.1 fix).
"""
import sys
import streamlit as st
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

st.set_page_config(page_title="VIDYA+SMC Zone", page_icon="\u25c8", layout="wide",
                   initial_sidebar_state="expanded")

from assets_ui import (
    get_page_css, render_sidebar, render_page_header, render_regime_bar,
    render_empty_state, sec_head,
    C_WARNING, C_DANGER, C_INFO, LABEL_COLOR, NEON_GREEN,
)
_ = C_DANGER

st.markdown(get_page_css("dashboard"), unsafe_allow_html=True)

from core.data_feed import get_ihsg_regime
from agents.zone_scanner import ZoneScanner

regime_data = get_ihsg_regime()

with st.sidebar:
    render_sidebar("zone", ema_total=len(st.session_state.get("zone_results", [])),
                   scan_date=datetime.now().strftime("%Y-%m-%d"),
                   regime=regime_data.get("cycle", "UNKNOWN"))

render_page_header(
    "MODULE 01 - RETEST-ZONE DETECTION", "VIDYA+SMC ", "ZONE",
    "Volumatic VIDYA trend + Internal OB retest + Conviction 20% -> 100% bertahap",
    scan_date=datetime.now().strftime("%Y-%m-%d"),
)
render_regime_bar(
    regime_data.get("cycle", "UNKNOWN"), regime_data.get("ihsg", 0),
    regime_data.get("mom_4w", 0), regime_data.get("breadth", 0),
    datetime.now().strftime("%Y-%m-%d"),
)

sec_head("SCAN CONTROLS")
c1, c2 = st.columns([2, 1])
with c1:
    run_btn = st.button("RUN ZONE SCAN", type="primary")
with c2:
    min_conv_ui = st.number_input("MIN CONVICTION %", 0, 100, 40, 5)

if run_btn:
    with st.spinner("Scanning universe... (~4-6 menit, unduh 2 tahun data harian)"):
        scanner = ZoneScanner()
        results, ctx = scanner.scan()
        st.session_state["zone_results"] = results
        st.session_state["zone_ctx"] = ctx

results = st.session_state.get("zone_results", [])
ctx = st.session_state.get("zone_ctx", {})

if not results and not ctx:
    render_empty_state("\u25c8", "BELUM ADA HASIL SCAN",
                       "Klik RUN ZONE SCAN utk memulai analisis universe.",
                       "python orchestrator.py --mode zone")
    st.stop()

filtered = [r for r in results if r["conviction_pct"] >= min_conv_ui]

sc1, sc2, sc3, sc4, sc5 = st.columns(5)
sc1.metric("UNIVERSE", ctx.get("total_universe", 0))
sc2.metric("DIANALISIS", ctx.get("analyzed", 0))
sc3.metric("WATCHING (semua)", ctx.get("watching_count", 0))
sc4.metric(f">={min_conv_ui}% CONVICTION", len(filtered))
sc5.metric("CONVICTION 100%", sum(1 for r in results if r["conviction_pct"] == 100))

if ctx.get("skipped_short_history") or ctx.get("crashed"):
    st.caption(f"Skip data pendek: {ctx.get('skipped_short_history',0)} | "
              f"Crash: {ctx.get('crashed',0)}")

st.markdown("<br>", unsafe_allow_html=True)
sec_head(f"ZONA AKTIF -- {len(filtered)} setup (filter conviction >={min_conv_ui}%)")

if not filtered:
    render_empty_state("\u25ce", f"NO SETUP CONVICTION >= {min_conv_ui}%",
                       "Turunkan ambang MIN CONVICTION, atau tunggu scan berikutnya.",
                       "")
else:
    def _conv_color(pct):
        if pct >= 75:
            return NEON_GREEN
        if pct >= 40:
            return C_WARNING
        return LABEL_COLOR

    def _badge(label, val, active_color):
        col = active_color if val > 0 else LABEL_COLOR
        opacity = "1" if val > 0 else "0.35"
        return ('<span style="opacity:' + opacity + ';border:1px solid ' + col +
               ';color:' + col + ';border-radius:3px;padding:1px 6px;' +
               'font-size:var(--text-2xs);font-family:Share Tech Mono,monospace;' +
               'margin-right:4px">' + label + ' ' + str(val) + '%</span>')

    cols = st.columns(2)
    for idx, r in enumerate(filtered):
        col = cols[idx % 2]
        with col:
            cc = _conv_color(r["conviction_pct"])
            pk_tag = ('<span class="tag" style="border-color:#F0B429;color:#F0B429">'
                     'papan pemantauan</span>') if r.get("pk_board") else ""
            zona_str = ("Rp{:,.0f} - Rp{:,.0f}".format(r["zone_bottom"], r["zone_top"])
                       if r["zone_top"] else "-")
            badges = (
                _badge("BASE", r["base_pct"], NEON_GREEN) +
                _badge("RETEST", r["retest_pct"], NEON_GREEN) +
                _badge("VIDYA", r["vidya_pct"], C_INFO) +
                _badge("VOL", r["volume_pct"], C_INFO) +
                _badge("STRUCT", r["structure_pct"], C_WARNING)
            )
            card_html = (
                '<div style="background:var(--bg-card);border:1px solid ' + cc + '55;'
                'border-left:4px solid ' + cc + ';border-radius:var(--r-md);'
                'padding:1rem 1.2rem;margin-bottom:0.8rem">'
                '<div style="display:flex;justify-content:space-between;align-items:center">'
                '<span style="font-family:Orbitron,monospace;font-size:var(--text-lg);'
                'font-weight:800;color:#E2E8F0">' + r['ticker'] + '</span>'
                '<span style="font-family:Orbitron,monospace;font-size:var(--text-xl);'
                'font-weight:900;color:' + cc + '">' + str(r['conviction_pct']) + '%</span>'
                '</div>'
                '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);'
                'color:var(--text-muted);margin:0.4rem 0">'
                'Close Rp' + '{:,.0f}'.format(r['close']) + ' | Zona ' + zona_str +
                ' | Retest ' + str(r['retest_hold_days']) + '/2 hari' +
                ' | ' + str(r['bars_since_formed'] or 0) + ' hari sejak terbentuk ' + pk_tag +
                '</div>'
                '<div style="margin-top:0.5rem">' + badges + '</div>'
                '</div>'
            )
            st.markdown(card_html, unsafe_allow_html=True)

st.markdown("<br><br>", unsafe_allow_html=True)
st.caption("Retest-only path: breakout tanpa pullback akan selalu bernilai conviction "
          "rendah dalam skema ini -- trade-off yang disengaja demi menyaring false breakout.")
