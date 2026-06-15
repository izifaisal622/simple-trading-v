"""Simple Trading V6 — Analisis Saham Spesifik"""
import json, time
from datetime import date
from pathlib import Path
import streamlit as st

st.set_page_config(page_title="Stock Analysis — STV6", page_icon="📡",
                   layout="wide", initial_sidebar_state="expanded")

ROOT     = Path(__file__).parent.parent
LOGS_DIR = ROOT / "logs"
import sys; sys.path.insert(0, str(ROOT))
# Journal agent import (lazy — only when tab used)


from assets_ui import (
    get_page_css, render_sidebar, render_page_header, render_regime_bar,
    REGIME_COLORS, TEXT_MUTED, TEXT_MAIN, TEXT_DIM, NEON_GREEN, BG_CARD,
)
st.markdown(get_page_css("dashboard"), unsafe_allow_html=True)

GREEN  = NEON_GREEN;  YELLOW = "var(--c-warning)";  RED = "var(--c-danger)"
BLUE   = "var(--c-info)";   WHITE  = TEXT_MAIN;  LABEL = "var(--text-secondary)"


def _regime():
    try:
        d = json.loads((LOGS_DIR/"daily_results.json").read_text(encoding="utf-8"))
        rg = d.get("regime", {})
        return rg.get("cycle","UNKNOWN"), rg.get("ihsg",0), rg.get("mom_4w",0), rg.get("breadth",0), d.get("scan_date","—")
    except Exception:
        return "UNKNOWN", 0, 0, 0, "—"

def _gc(g):   return {"A":GREEN,"A+":GREEN,"B":YELLOW,"C":"var(--c-warning)","D":RED,"F":RED}.get(g, TEXT_DIM)
def _gbg(g):  return {"A":"rgba(0,255,102,0.07)","A+":"rgba(0,255,102,0.09)","B":"rgba(240,180,41,0.07)","C":"rgba(249,115,22,0.07)","D":"rgba(239,68,68,0.07)","F":"rgba(239,68,68,0.05)"}.get(g, "rgba(255,255,255,0.02)")
def _sc(s):   return {"BREAKOUT":GREEN,"WATCHLIST":YELLOW,"CORRECTING":BLUE,"DEEP_CORRECT":RED}.get(s, TEXT_DIM)
def _si(s):   return {"BREAKOUT":"◈","WATCHLIST":"◎","CORRECTING":"○","DEEP_CORRECT":"◌"}.get(s, "—")
def _wc(q):   return {"SMART":GREEN,"LIKELY_SMART":YELLOW,"UNCERTAIN":BLUE}.get(q, TEXT_DIM)
def _ac(a):
    return GREEN if a in ("AKUMULASI","PENGERINGAN","BLOCK_BUY","RECOVERY_EARLY") else RED if a in ("DISTRIBUSI","SELL_OFF","DISTRIBUTION") else TEXT_DIM
def _t(v,hi,med): return GREEN if v>=hi else YELLOW if v>=med else RED
def _clr(v):  return RED if v>25 else YELLOW if v>15 else GREEN

def B(text, color=None):   # bold colored span
    c = color or WHITE
    return f'<b style="color:{c}">{text}</b>'

def span(text, color):
    return f'<span style="color:{color}">{text}</span>'

def badge(text, color, bg=None):
    bg = bg or color + "18"
    return (f'<span style="background:{bg};border:1px solid {color}55;border-radius:2px;'
            'padding:2px 8px;font-family:Orbitron,monospace;font-size:var(--text-xs);'
            f'font-weight:700;color:{color}">{text}</span>')

def line(html_str):  # one inline line in the card
    return ('<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);'
            f'color:{LABEL};line-height:1.8;padding:.1rem 0">{html_str}</div>')

def warn_block(text, color):
    return (f'<div style="background:rgba(0,0,0,.2);border-left:3px solid {color};'
            'border-radius:3px;padding:.35rem .75rem;margin:.35rem 0;'
            f'font-family:Share Tech Mono,monospace;font-size:var(--text-sm);color:{color}">{text}</div>')

def sec_div(label, color=None):
    c = color or LABEL
    return ('<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
            f'letter-spacing:.18em;color:{c};margin:.6rem 0 .2rem;'
            f'border-top:1px solid rgba(255,255,255,0.06);padding-top:.45rem">{label}</div>')


# ── sidebar / header ──────────────────────────────────────────────────────────
cycle, ihsg, mom_4w, breadth, scan_date = _regime()
render_sidebar("Stock Analysis", regime=cycle, scan_date=scan_date)
import json as _jv, pathlib as _pv
try:
    _ver_accent = "V" + _jv.loads((_pv.Path(__file__).parent.parent/"version.json").read_text())["version"]
except Exception:
    _ver_accent = "V6"
render_page_header(
    eyebrow  = "◆ MODULE 04 · SINGLE STOCK ANALYSIS · " + _ver_accent,
    title    = "SIMPLE TRADING ",
    accent   = _ver_accent,
    subtitle = "◈ EMA-XBO · FOLLOW WHALE · RATING CARD · SMC ANALYSIS",
)
render_regime_bar(cycle, ihsg, mom_4w, breadth, scan_date)

# ── input ─────────────────────────────────────────────────────────────────────
st.markdown(
    '<div style="background:' + BG_CARD + ';border:1px solid rgba(255,255,255,0.07);'
    'border-radius:6px;padding:.9rem 1.1rem;margin:.7rem 0 .3rem">'
    '<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
    'letter-spacing:.2em;color:' + LABEL + ';margin-bottom:.4rem">◈ INPUT SAHAM</p>',
    unsafe_allow_html=True)

with st.form("sa_form", clear_on_submit=False):
    c1, c2 = st.columns([4,1], gap="small")
    with c1:
        raw = st.text_input("ticker", value=st.session_state.get("sa_val",""),
                            placeholder="BBCA   TLKM   BREN   GOTO   BMRI   ASII",
                            label_visibility="collapsed", key="sa_input")
    with c2:
        run = st.form_submit_button("◈ ANALISIS", use_container_width=True, type="primary")
st.markdown("</div>", unsafe_allow_html=True)

if "sa_hist" not in st.session_state: st.session_state.sa_hist = []
if st.session_state.sa_hist:
    chips = " ".join(
        '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:' + BLUE + ';'
        'background:rgba(96,165,250,0.08);border:1px solid ' + BLUE + '33;'
        'border-radius:3px;padding:1px 7px">' + t + '</span>'
        for t in reversed(st.session_state.sa_hist[-8:])
    )
    st.markdown('<p style="font-size:var(--text-2xs);color:' + LABEL + ';font-family:Share Tech Mono,monospace;margin:.1rem 0 .5rem">RECENT: ' + chips + '</p>', unsafe_allow_html=True)

# ── run ───────────────────────────────────────────────────────────────────────
ticker = raw.strip().upper().replace(".JK","")
if run and ticker:
    st.session_state["sa_val"] = ticker
    if ticker not in st.session_state.sa_hist: st.session_state.sa_hist.append(ticker)
    with st.spinner(f"Menganalisis {ticker}…"):
        t0 = time.time()
        try:
            from agents.single_stock_agent import analyze_single
            r = analyze_single(ticker)
        except Exception as e:
            st.error(f"Error: {e}"); import traceback; st.code(traceback.format_exc()); st.stop()
    st.session_state["sa_r"] = r
    st.session_state["sa_sec"] = round(time.time()-t0, 1)

r = st.session_state.get("sa_r")
if r is None:
    st.markdown('<div style="text-align:center;padding:4rem 0"><p style="font-family:Orbitron,monospace;font-size:var(--text-2xl);color:' + TEXT_MUTED + ';margin-bottom:.5rem">◈</p><p style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);letter-spacing:.2em;color:' + TEXT_DIM + '">MASUKKAN KODE SAHAM DAN KLIK ANALISIS</p><p style="font-size:var(--text-sm);margin-top:.4rem;color:' + TEXT_MUTED + '">Contoh: BBCA · TLKM · BREN · ASII · BMRI</p></div>', unsafe_allow_html=True)
    st.stop()
if r.error: st.error(f"⚠ {r.error}"); st.stop()

sec = st.session_state.get("sa_sec", 0)

# ── pre-compute all display values ────────────────────────────────────────────
g_col   = _gc(r.grade);       g_bg     = _gbg(r.grade)
sig_col = _sc(r.signal);      sig_icon = _si(r.signal)
cross_c = GREEN if r.cross_state=="ABOVE" else YELLOW if r.cross_state=="CROSSING" else RED
ema_c   = _t(r.ema_score,5,3);   wq_c = _wc(r.whale_quality)
conv_c  = _t(r.conviction,7,4);  risk_c = _clr(r.risk_pct)
act_c   = _ac(r.activity_type);  rs_c = GREEN if r.rs_vs_ihsg>0 else RED
reg_col = REGIME_COLORS.get(r.regime_tag, TEXT_DIM)

ema_gap = ((r.ema13 - r.ema89)/r.ema89*100) if r.ema89 else 0
pct_vs13= ((r.close - r.ema13)/r.ema13*100) if r.ema13 else 0
pct_vs89= ((r.close - r.ema89)/r.ema89*100) if r.ema89 else 0
fp_dist = ((r.close - r.floor_price)/r.floor_price*100) if r.floor_price and r.close else 0

vol_lbl = "EKSTREM" if r.vol_ratio>=6 else "SPIKE" if r.vol_ratio>=3 else "ELEVATED" if r.vol_ratio>=1.3 else "NORMAL"
vol_wc  = GREEN if r.vol_ratio>=3 else YELLOW if r.vol_ratio>=1.3 else TEXT_DIM

mcf_col = RED if r.mcf_bear_blocked else GREEN if r.mcf_entry_ok else TEXT_DIM
mcf_lbl = ("⛔ BEAR BLOCKED ("+str(r.mcf_score)+"/10)") if r.mcf_bear_blocked else (("◈ "+r.mcf_label+" ("+str(r.mcf_score)+"/10)") if r.mcf_entry_ok else (r.mcf_label+" ("+str(r.mcf_score)+"/10)"))

reasons_html = "".join(
    '<span style="display:flex;align-items:center;gap:.4rem;padding:.12rem 0;border-bottom:1px solid rgba(255,255,255,0.04)">'
    '<span style="color:'+GREEN+';flex-shrink:0">✓</span>'
    '<span style="font-size:var(--text-xs);color:'+WHITE+'">'+x+'</span></span>'
    for x in r.grade_reasons
) or '<span style="font-size:var(--text-xs);color:'+TEXT_DIM+'">—</span>'

msci_h = ""
if r.msci_active and r.msci_alert_level:
    mc = GREEN if r.msci_alert_level=="HIGH_CONVICTION" else YELLOW
    msci_h = ('<div style="background:rgba(0,255,102,0.07);border:1px solid '+mc+'33;border-radius:3px;padding:.2rem .5rem;margin-top:.3rem">'
              '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:'+mc+';font-weight:700">★ MSCI '+r.msci_alert_level+' T-'+str(r.msci_t_minus)+'</span></div>')

# ════════════════════════════════════════════════════════════════════════════
# GRADE BANNER
# ════════════════════════════════════════════════════════════════════════════
st.markdown(
    '<div style="background:'+g_bg+';border:1px solid '+g_col+'44;border-radius:8px;padding:1.1rem 1.4rem;margin:.6rem 0">'
    '<div style="display:flex;align-items:flex-start;gap:1.2rem;flex-wrap:wrap">'

    '<div style="text-align:center;min-width:68px">'
    '<div style="font-family:Orbitron,monospace;font-size:var(--text-2xl);font-weight:900;color:'+g_col+';line-height:1">'+r.grade+'</div>'
    '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:'+g_col+'">'+str(r.overall_score)+'/100</div>'
    '</div>'

    '<div style="flex:1;min-width:180px">'
    '<div style="font-family:Orbitron,monospace;font-size:var(--text-xl);font-weight:700;color:'+WHITE+'">'+r.ticker
    +'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:'+LABEL+'"> · '+r.date+' · '+str(sec)+'s</span></div>'
    '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);font-weight:700;color:'+g_col+';margin:.3rem 0">'+r.action_label+'</div>'
    '<div style="background:rgba(255,255,255,0.07);border-radius:3px;height:4px;width:100%;margin:.3rem 0">'
    '<div style="width:'+str(r.overall_score)+'%;background:'+g_col+';height:100%;border-radius:3px"></div></div>'
    '<div style="display:flex;flex-direction:column;margin-top:.3rem">'+reasons_html+'</div>'
    '</div>'

    '<div style="min-width:140px;font-family:Share Tech Mono,monospace;display:flex;flex-direction:column;gap:.18rem">'
    '<div style="display:flex;justify-content:space-between"><span style="font-size:var(--text-2xs);color:'+LABEL+'">SIGNAL</span><span style="font-size:var(--text-xs);font-weight:600;color:'+sig_col+'">'+sig_icon+' '+r.signal+'</span></div>'
    '<div style="display:flex;justify-content:space-between"><span style="font-size:var(--text-2xs);color:'+LABEL+'">EMA SCORE</span><span style="font-size:var(--text-xs);font-weight:600;color:'+ema_c+'">'+str(r.ema_score)+'/7</span></div>'
    '<div style="display:flex;justify-content:space-between"><span style="font-size:var(--text-2xs);color:'+LABEL+'">WHALE</span><span style="font-size:var(--text-xs);font-weight:600;color:'+wq_c+'">'+r.whale_quality+'</span></div>'
    '<div style="display:flex;justify-content:space-between"><span style="font-size:var(--text-2xs);color:'+LABEL+'">CONVICTION</span><span style="font-size:var(--text-xs);font-weight:600;color:'+conv_c+'">'+str(r.conviction)+'/10</span></div>'
    '<div style="display:flex;justify-content:space-between"><span style="font-size:var(--text-2xs);color:'+LABEL+'">REGIME</span><span style="font-size:var(--text-xs);color:'+reg_col+'">'+reg_col.replace("#","")[:0]+r.regime_tag+'</span></div>'
    +msci_h+
    '</div></div></div>',
    unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════
# COMPACT CARD — EMA-XBO style inline
# ════════════════════════════════════════════════════════════════════════════

# Verdict
if r.regime_tag == "WATCHLIST_ONLY":
    v_col, v_bg, verdict = RED, "rgba(239,68,68,0.04)", "⛔ BEAR — WATCH ONLY"
elif r.signal == "BREAKOUT":
    v_col, v_bg, verdict = GREEN, "rgba(0,255,102,0.06)", "ENTRY VALID"
elif r.signal == "WATCHLIST":
    v_col, v_bg, verdict = YELLOW, "rgba(240,180,41,0.04)", "WATCHLIST"
else:
    v_col, v_bg, verdict = TEXT_DIM, "rgba(100,116,139,0.04)", "MONITOR / WAIT"

html = (
    '<div style="background:'+BG_CARD+';border:1px solid rgba(255,255,255,0.07);'
    'border-left:3px solid '+v_col+';border-radius:6px;padding:1rem 1.2rem;margin:.4rem 0">'

    # Header row
    '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.6rem">'
    '<div><span style="font-family:Orbitron,monospace;font-size:var(--text-xl);font-weight:800;color:'+WHITE+'">'+r.ticker+'</span>'
    '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:'+LABEL+';margin-left:.6rem">'
    'EMA-XBO · Score '+str(r.ema_score)+'/7 · Vol '+f"{r.vol_ratio:.1f}"+'×</span></div>'
    '<div style="background:'+v_bg+';border:1px solid '+v_col+'55;border-radius:3px;padding:.25rem .7rem;'
    'font-family:Share Tech Mono,monospace;font-size:var(--text-xs);font-weight:700;color:'+v_col+'">'+verdict+'</div>'
    '</div>'
)

# Phase badge + description
if r.cross_state == "BELOW":
    phase_c, phase_lbl = RED, "BELOW EMA"
    phase_desc = "EMA13 belum melewati EMA89. Gap "+f"{ema_gap:+.1f}%"+"."
elif r.cross_state == "CROSSING":
    phase_c, phase_lbl = GREEN, "GOLDEN CROSS"
    phase_desc = "EMA13 baru melewati EMA89. Early entry, risiko lebih tinggi."
elif abs(pct_vs13) <= 3 and r.vol_ratio >= 1.3:
    phase_c, phase_lbl = GREEN, "PULLBACK CONFIRMED"
    phase_desc = f"Di EMA13 support ({pct_vs13:+.1f}%) + vol {r.vol_ratio:.1f}×. Re-entry terbaik."
elif abs(pct_vs13) <= 3:
    phase_c, phase_lbl = YELLOW, "PULLBACK WATCH"
    phase_desc = f"Di EMA13 ({pct_vs13:+.1f}%) tapi vol belum konfirmasi ({r.vol_ratio:.1f}×)."
elif 3 < pct_vs13 <= 12 and r.vol_ratio >= 3:
    phase_c, phase_lbl = GREEN, "BREAKOUT CONFIRMED"
    phase_desc = f"{pct_vs13:+.1f}% di atas EMA13 + vol {r.vol_ratio:.1f}×. Institutional."
elif pct_vs13 > 12:
    phase_c, phase_lbl = YELLOW, "EXTENDED"
    phase_desc = f"Harga {pct_vs13:+.1f}% di atas EMA13. Tunggu pullback ke Rp{r.ema13:,.0f}."
elif pct_vs13 < -3 and pct_vs89 > 0:
    phase_c, phase_lbl = YELLOW, "DEEP PULLBACK"
    phase_desc = f"Di bawah EMA13 ({pct_vs13:+.1f}%) tapi di atas EMA89 ({pct_vs89:+.1f}%). Trend besar valid."
elif pct_vs13 < -3:
    phase_c, phase_lbl = RED, "TREND BREAK"
    phase_desc = "Di bawah EMA13 dan EMA89. Trend bullish terancam."
else:
    phase_c, phase_lbl = TEXT_DIM, "WATCH"
    phase_desc = "Monitor."

html += line(badge(phase_lbl, phase_c) + " " + phase_desc)

# EMA line
html += line(
    B("EMA:") + " EMA13 " + B("Rp"+f"{r.ema13:,.0f}", WHITE) + " · "
    + "EMA89 " + B("Rp"+f"{r.ema89:,.0f}", "var(--text-secondary)") + " · "
    + "Gap " + B(f"{ema_gap:+.1f}%", GREEN if ema_gap>0 else RED) + " · "
    + "vs EMA13 " + B(f"{pct_vs13:+.1f}%", GREEN if pct_vs13>0 else RED)
    + (" · EMA200 " + B("Rp"+f"{r.ema200:,.0f}", YELLOW if not r.ema200_reliable else "var(--text-secondary)") if r.ema200 else "")
)

# Vol + score + RS line
html += line(
    B("Volume:") + " " + B(f"{r.vol_ratio:.1f}× — {vol_lbl}", vol_wc) + " · "
    + "Score " + B(str(r.ema_score)+"/7", ema_c) + " · "
    + "RS " + B(f"{r.rs_vs_ihsg:+.1f}%", rs_c)
    + (" · Regime " + B(r.regime_tag, reg_col) if r.regime_tag else "")
)

# Risk line
if r.sl_price:
    html += line(
        B("Risk:") + " Entry Rp"+f"{r.entry_price:,.0f}" + " · "
        + "SL " + B("Rp"+f"{r.sl_price:,.0f}", RED) + " ("+f"{r.risk_pct:.0f}%"+")" + " · "
        + "TP1 " + B("Rp"+f"{r.tp1_price:,.0f}", GREEN)
        + (" · TP2 Rp"+f"{r.tp2_price:,.0f}" if r.tp2_price else "") + " · "
        + "R:R " + B(f"{r.rr_ratio:.1f}:1", GREEN if r.rr_ratio>=2 else YELLOW if r.rr_ratio>=1.5 else RED)
    )

# Risk / EMA200 warnings
if r.risk_pct > 25:
    html += warn_block("⚠ RISK "+f"{r.risk_pct:.0f}%"+" — TERLALU LEBAR. Max 1% modal = " +
                       ("Rp" + f"{100_000_000/(r.risk_pct/100)/r.entry_price*100:,.0f}" if r.entry_price else "?") +
                       " lembar", RED)
elif r.risk_pct > 15:
    html += warn_block("⚠ RISK "+f"{r.risk_pct:.0f}%"+" — Hati-hati sizing. Kurangi ukuran posisi.", YELLOW)
if not r.ema200_reliable:
    html += warn_block("⚠ EMA200 tidak reliable — data weekly < 150 bars.", YELLOW)

# MCF line
html += line(B("MCF") + " " + B(mcf_lbl, mcf_col))

# Daily timing
html += line(
    B("Daily:") + " EMA13d Rp"+f"{r.ema13:,.0f}" +
    " · " + ("✓ OK" if r.daily_ok else "✗ BELUM") + " · " +
    (r.daily_pattern or "—") +
    (" · " + B("DUAL CONFIRMED", GREEN) if r.dual_confirmed else "")
)

# ── Whale section ─────────────────────────────────────────────────────────────
html += sec_div("FOLLOW WHALE — HENGKY METHOD", YELLOW)

if not r.whale_ok:
    html += line("Data whale tidak tersedia untuk saham ini.")
else:
    wvol_c = GREEN if r.vol_ratio_whale>=2 else TEXT_DIM
    html += line(
        badge(r.activity_type or "—", act_c) + " " +
        B(r.whale_quality, wq_c) + " · " +
        "Conviction " + B(str(r.conviction)+"/10", conv_c) + " · " +
        "Vol " + B(f"{r.vol_ratio_whale:.1f}×", wvol_c)
    )
    fp_c = RED if r.harga_terlalu_jauh else GREEN if fp_dist < 10 else YELLOW
    html += line(
        B("Floor:") + " Rp"+f"{r.floor_price:,.0f}" + " · " +
        B(f"+{fp_dist:.1f}% di atas floor", fp_c) + " · " +
        "Zone " + B(r.entry_zone or "—", GREEN if r.entry_zone in ("AT_FLOOR","NEAR_FLOOR") else TEXT_DIM)
    )
    html += line(
        B("Defend:") + " " + B("✓ AKTIF" if r.whale_defending else "— TIDAK", GREEN if r.whale_defending else TEXT_DIM) +
        " · Pengeringan " + B("✓ ("+str(r.peng_strength)+"/5)" if r.pengeringan else "—", GREEN if r.pengeringan else TEXT_DIM) +
        " · EMA " + B(r.ema_trend_whale or "—", GREEN if r.ema_trend_whale=="BULLISH" else RED) +
        " · Momentum " + B(r.momentum or "—", GREEN if r.momentum in ("ACCELERATING","REVERSING") else RED if r.momentum=="DECLINING" else TEXT_DIM)
    )
    html += line(
        B("Barang:") + " Control " + B(str(r.control_score)+"/10", _t(r.control_score,7,4)) +
        " · OB Zone " + B("✓" if r.in_ob_zone else "—", GREEN if r.in_ob_zone else TEXT_DIM) +
        " · Lot Est. " + (f"{r.total_lot:,}" if r.total_lot else "—")
    )
    if r.harga_terlalu_jauh:
        html += warn_block("⚠ Harga terlalu jauh dari floor — risiko tinggi jika entry sekarang", RED)
    if r.market_sepi:
        html += warn_block("⚠ Market sepi — volume tipis, breakout bisa false", YELLOW)
    if r.activity_type in ("DISTRIBUSI","SELL_OFF","DISTRIBUTION"):
        html += warn_block("🔴 Distribusi/Sell-off terdeteksi — smart money keluar. JANGAN ENTRY.", RED)

# MSCI block
if r.msci_active and r.msci_alert_level:
    mc = GREEN if r.msci_alert_level=="HIGH_CONVICTION" else YELLOW
    html += (
        '<div style="background:rgba(0,255,102,0.05);border:1px solid '+mc+'33;'
        'border-left:3px solid '+mc+';border-radius:3px;padding:.4rem .7rem;margin:.5rem 0">'
        '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);font-weight:700;color:'+mc+'">'
        '★ MSCI '+r.msci_alert_level+'</span>'
        '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:'+WHITE+';margin-left:.5rem">'+r.msci_entry_note+'</span>'
        '</div>'
    )

html += '</div>'
st.markdown(html, unsafe_allow_html=True)

# ── Action bar ─────────────────────────────────────────────────────────────────
st.markdown(
    '<div style="background:'+BG_CARD+';border:1px solid '+g_col+'33;border-radius:6px;'
    'padding:.7rem 1.2rem;margin:.4rem 0;display:flex;align-items:center;'
    'justify-content:space-between;flex-wrap:wrap;gap:.5rem">'
    '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:'+LABEL+'">REKOMENDASI</span>'
    '<span style="font-family:Orbitron,monospace;font-size:var(--text-lg);font-weight:800;color:'+g_col+'">'+r.action_label+'</span>'
    '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:'+g_col+'">'
    'Grade '+r.grade+'  ·  Score '+str(r.overall_score)+'/100  ·  EMA '+str(r.ema_score)+'/7  ·  Whale '+str(r.conviction)+'/10</span>'
    '</div>',
    unsafe_allow_html=True)

# ── Pre-Flight Checklist ──────────────────────────────────────────────────────
# Checklist wajib sebelum LOG TRADE — mencegah entry impulsif
# Semua item harus centang sebelum log trade bisa dilakukan

st.markdown("<br>", unsafe_allow_html=True)

# Hitung nilai checklist dari data analisis
_pf_regime_ok   = r.regime_tag not in ("WATCHLIST_ONLY", "BEAR_TREND", "BEAR_WEAK", "BEAR_CONSOLIDATION", "")
_pf_ema_ok      = r.ema_score >= 4
_pf_conv_ok     = r.conviction >= 6
_pf_floor_ok    = fp_dist <= 20
_pf_risk_ok     = r.risk_pct <= 25
_pf_vol_ok      = r.vol_ratio >= 1.3
_pf_dist_ok     = r.activity_type not in ("DISTRIBUSI", "SELL_OFF", "DISTRIBUTION")
_pf_signal_ok   = r.signal not in ("CORRECTING", "DEEP_CORRECT", "")

_pf_all_pass    = all([_pf_regime_ok, _pf_ema_ok, _pf_conv_ok, _pf_floor_ok,
                        _pf_risk_ok, _pf_vol_ok, _pf_dist_ok, _pf_signal_ok])
_pf_pass_count  = sum([_pf_regime_ok, _pf_ema_ok, _pf_conv_ok, _pf_floor_ok,
                        _pf_risk_ok, _pf_vol_ok, _pf_dist_ok, _pf_signal_ok])

# Colors
_pf_head_col = "#00FF66" if _pf_all_pass else "#F0B429" if _pf_pass_count >= 6 else "#EF4444"
_pf_head_bg  = ("rgba(0,255,102,0.05)" if _pf_all_pass else
                "rgba(240,180,41,0.05)" if _pf_pass_count >= 6 else
                "rgba(239,68,68,0.05)")
_pf_head_lbl = ("✅ CLEAR FOR ENTRY" if _pf_all_pass else
                f"⚠ {8 - _pf_pass_count} KRITERIA BELUM TERPENUHI" if _pf_pass_count >= 6 else
                f"⛔ JANGAN ENTRY ({8 - _pf_pass_count} critical miss)")

# Build checklist items
def _pf_row(ok: bool, label: str, value: str, rule: str) -> str:
    _ic  = "✓" if ok else "✗"
    _col = "#00FF66" if ok else "#EF4444"
    _bg  = "rgba(0,255,102,0.03)" if ok else "rgba(239,68,68,0.05)"
    _bdr = "rgba(0,255,102,0.12)" if ok else "rgba(239,68,68,0.2)"
    return (
        f'<div style="background:{_bg};border:1px solid {_bdr};'
        f'border-radius:var(--r-sm);padding:0.3rem 0.7rem;margin-bottom:0.25rem;'
        f'display:flex;align-items:center;gap:0.7rem">'
        f'<span style="font-family:Orbitron,monospace;font-size:var(--text-sm);'
        f'color:{_col};font-weight:900;min-width:16px">{_ic}</span>'
        f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
        f'color:#94A3B8;min-width:160px">{label}</span>'
        f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
        f'color:{_col};font-weight:700">{value}</span>'
        f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
        f'color:var(--text-dim);margin-left:auto">{rule}</span>'
        f'</div>'
    )

_pf_rows = (
    _pf_row(_pf_regime_ok,  "REGIME",        r.regime_tag or "UNKNOWN",
             "Bukan BEAR/WATCHLIST_ONLY")
    + _pf_row(_pf_ema_ok,   "EMA SCORE",     f"{r.ema_score}/7",
               "≥ 4 untuk entry")
    + _pf_row(_pf_conv_ok,  "CONVICTION",    f"{r.conviction}/10",
               "≥ 6 untuk full size")
    + _pf_row(_pf_floor_ok, "FLOOR DIST",    f"{fp_dist:.1f}%",
               "≤ 20% dari floor")
    + _pf_row(_pf_risk_ok,  "RISK %",        f"{r.risk_pct:.1f}%",
               "≤ 25% per trade")
    + _pf_row(_pf_vol_ok,   "VOL RATIO",     f"{r.vol_ratio:.1f}×",
               "≥ 1.3× konfirmasi")
    + _pf_row(_pf_dist_ok,  "SINYAL ARAH",   r.activity_type or r.signal or "—",
               "Bukan distribusi/sell-off")
    + _pf_row(_pf_signal_ok,"EMA SIGNAL",    r.signal or "—",
               "Bukan CORRECTING/DEEP")
)

# Session state untuk override checklist (trader tetap bisa force entry)
if "pf_override" not in st.session_state:
    st.session_state["pf_override"] = False

_pf_col1, _pf_col2 = st.columns([5, 1])
with _pf_col1:
    st.markdown(f"""
<div style="background:{_pf_head_bg};border:1px solid {_pf_head_col}30;
border-left:4px solid {_pf_head_col};border-radius:var(--r-md);
padding:0.7rem 1rem;margin-bottom:0.4rem">
  <div style="display:flex;align-items:center;gap:1rem;margin-bottom:0.5rem">
    <span style="font-family:Orbitron,monospace;font-size:var(--text-sm);
    font-weight:800;color:{_pf_head_col};letter-spacing:0.1em">
    ◈ PRE-FLIGHT CHECKLIST</span>
    <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
    color:{_pf_head_col};font-weight:700">{_pf_head_lbl}</span>
    <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);
    color:var(--text-dim);margin-left:auto">{_pf_pass_count}/8 pass</span>
  </div>
  {_pf_rows}
</div>
""", unsafe_allow_html=True)

with _pf_col2:
    st.markdown("<br><br>", unsafe_allow_html=True)
    if not _pf_all_pass:
        _override_lbl = "🔓 OVERRIDE ON" if st.session_state["pf_override"] else "⚠ FORCE ENTRY"
        if st.button(_override_lbl, key="pf_override_btn", use_container_width=True):
            st.session_state["pf_override"] = not st.session_state["pf_override"]
            st.rerun()
        if st.session_state["pf_override"]:
            st.markdown(
                '<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
                'color:#EF4444;text-align:center">Override aktif —<br>log trade atas<br>risiko sendiri</p>',
                unsafe_allow_html=True)

# Store checklist state untuk dipakai di form log trade
_pf_entry_allowed = _pf_all_pass or st.session_state.get("pf_override", False)

# ── Tabs: Paper Trade Journal + Ringkasan + System Flags ─────────────────────
tab_labels = ["📋 Paper Trade Journal", "◈ Ringkasan Analisis", "⚙ System Flags"]
tab_journal, tab_ringkasan, tab_flags = st.tabs(tab_labels)

with tab_journal:
    from agents.journal_agent import (
        add_paper_trade, get_open_trades,
        compute_performance, close_paper_trade, get_pending_exit_prompts,
    )

    # ── Pending exit prompts ──────────────────────────────────────────────────
    prompts = get_pending_exit_prompts(14)
    if prompts:
        st.markdown(f'<div style="background:rgba(240,180,41,.08);border-left:3px solid {YELLOW};border-radius:3px;padding:.5rem .8rem;margin:.3rem 0;font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:{YELLOW}">⚠ {len(prompts)} paper trade sudah >14 hari — catat outcome-nya!</div>', unsafe_allow_html=True)
        for p in prompts:
            st.markdown(f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:{LABEL}">{p["ticker"]} (masuk {p["entry_date"]}, {p["days_open"]} hari)</span>', unsafe_allow_html=True)

    # ── Log new paper trade ──────────────────────────────────────────────────
    st.markdown(f'<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);letter-spacing:.15em;color:{BLUE};margin:.5rem 0 .3rem">◈ LOG PAPER TRADE — {r.ticker}</p>', unsafe_allow_html=True)

    with st.form("journal_form", clear_on_submit=True):
        jc1, jc2 = st.columns(2, gap="small")
        with jc1:
            j_entry = st.number_input("Entry Price", value=float(r.entry_price or r.close or 0), step=1.0, format="%.0")
            j_sl    = st.number_input("Stop Loss", value=float(r.sl_price or 0), step=1.0, format="%.0")
        with jc2:
            j_tp1   = st.number_input("TP1", value=float(r.tp1_price or 0), step=1.0, format="%.0")
            j_notes = st.text_input("Notes (opsional)", placeholder="Setup notes, catalyst, dll", label_visibility="visible")
        # Pre-flight gate: disabled jika checklist belum pass dan belum di-override
        _btn_label = "◈ LOG PAPER TRADE" if _pf_entry_allowed else f"⛔ LOG DIBLOKIR ({8-_pf_pass_count} kriteria gagal)"
        _btn_type  = "primary" if _pf_entry_allowed else "secondary"
        log_btn = st.form_submit_button(_btn_label, use_container_width=True, type=_btn_type,
                                         disabled=not _pf_entry_allowed)
        if log_btn:
            if j_entry > 0 and j_sl > 0:
                tid = add_paper_trade(
                    ticker=r.ticker, entry_price=j_entry, sl_price=j_sl,
                    tp1_price=j_tp1, risk_pct=r.risk_pct, rr_ratio=r.rr_ratio,
                    ema_score=r.ema_score, ema_signal=r.signal,
                    whale_quality=r.whale_quality, conviction=r.conviction,
                    regime=r.regime_tag, grade=r.grade, notes=j_notes,
                    source="module03",
                )
                st.success(f"✅ Paper trade #{tid} logged — {r.ticker} @ Rp{j_entry:,.0f}")
            else:
                st.error("Entry dan SL harus diisi")

    # ── Performance stats ─────────────────────────────────────────────────────
    perf = compute_performance()
    if perf.get("total", 0) > 0:
        st.markdown(f'<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);letter-spacing:.15em;color:{YELLOW};margin:.6rem 0 .3rem">◈ PAPER PERFORMANCE — {perf["total"]} CLOSED TRADES</p>', unsafe_allow_html=True)
        p1, p2, p3, p4 = st.columns(4)
        def _pstat(col, label, value, color):
            col.markdown(f'<div style="background:{BG_CARD};border:1px solid rgba(255,255,255,.07);border-radius:4px;padding:.6rem .8rem;text-align:center"><div style="font-family:Orbitron,monospace;font-size:var(--text-xl);font-weight:800;color:{color}">{value}</div><div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:{LABEL}">{label}</div></div>', unsafe_allow_html=True)
        wr = perf["win_rate"]
        ev = perf["expectancy"]
        _pstat(p1, "WIN RATE",   f"{wr:.0f}%",    GREEN if wr>=50 else RED)
        _pstat(p2, "EXPECTANCY", f"{ev:+.2f}R",   GREEN if ev>0 else RED)
        _pstat(p3, "TOTAL R",    f"{perf['total_r']:+.1f}R", GREEN if perf['total_r']>0 else RED)
        _pstat(p4, "VERDICT",    perf["verdict"][:6], GREEN if "POSITIVE" in perf["verdict"] else RED)

        if perf.get("grade_stats"):
            st.markdown(f'<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:{LABEL};margin:.5rem 0 .2rem">WIN RATE BY GRADE</p>', unsafe_allow_html=True)
            for g, gs in perf["grade_stats"].items():
                wrc = gs["win_rate"]
                bar_c = GREEN if wrc >= 55 else YELLOW if wrc >= 40 else RED
                st.markdown(f'<div style="display:flex;align-items:center;gap:.6rem;margin:.15rem 0"><span style="font-family:Orbitron,monospace;font-size:var(--text-xs);font-weight:800;color:{bar_c};width:20px">{"A" if g in ("A","A+") else g}</span><div style="flex:1;background:rgba(255,255,255,.06);border-radius:2px;height:5px"><div style="width:{wrc}%;background:{bar_c};height:100%;border-radius:2px"></div></div><span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:{bar_c}">{wrc:.0f}% ({gs["total"]} trades, {gs["avg_r"]:+.2f}R avg)</span></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:{LABEL}">Belum ada closed paper trade. Log trade di atas → setelah 14 hari → catat outcome.</p>', unsafe_allow_html=True)

    # ── Open trades table ─────────────────────────────────────────────────────
    open_trades = get_open_trades()
    if open_trades:
        st.markdown(f'<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);letter-spacing:.15em;color:{GREEN};margin:.5rem 0 .3rem">◈ OPEN PAPER TRADES ({len(open_trades)})</p>', unsafe_allow_html=True)
        for ot in open_trades:
            days = (date.today() - date.fromisoformat(ot["entry_date"])).days
            st.markdown(f'<div style="display:flex;justify-content:space-between;align-items:center;padding:.3rem 0;border-bottom:1px solid rgba(255,255,255,.04);font-family:Share Tech Mono,monospace;font-size:var(--text-xs)"><span style="color:{WHITE}">{ot["ticker"]}</span><span style="color:{LABEL}">masuk Rp{ot["entry_price"]:,.0f} · SL Rp{ot["sl_price"]:,.0f} · {days}d</span><span style="color:{YELLOW if ot.get('grade','') in ('A','B') else LABEL}">Grade {ot.get("grade","?")}</span></div>', unsafe_allow_html=True)

        # Close trade form
        st.markdown(f'<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:{LABEL};margin:.4rem 0 .2rem">TUTUP PAPER TRADE</p>', unsafe_allow_html=True)
        with st.form("close_form", clear_on_submit=True):
            cc1, cc2, cc3 = st.columns([2,2,2], gap="small")
            with cc1:
                close_id = st.selectbox("Trade ID", [t["id"] for t in open_trades], format_func=lambda x: f"#{x} {next(t['ticker'] for t in open_trades if t['id']==x)}")
            with cc2:
                close_price = st.number_input("Exit Price", value=0.0, step=1.0, format="%.0")
            with cc3:
                close_reason = st.selectbox("Alasan", ["MANUAL","SL_HIT","TP1_HIT","TP2_HIT","TIME_STOP"])
            close_btn = st.form_submit_button("✓ TUTUP TRADE")
            if close_btn and close_id and close_price > 0:
                result = close_paper_trade(close_id, close_price, close_reason)
                oc = GREEN if result.get("outcome")=="WIN" else RED
                st.markdown(f'<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:{oc}">{"✅" if result.get("outcome")=="WIN" else "❌"} {result.get("outcome","")} — {result.get("pnl_r",0):+.2f}R ({result.get("pnl_pct",0):+.1f}%)</div>', unsafe_allow_html=True)

with tab_ringkasan:
    # ── Ringkasan Analisis — Framework Hengky: Signal → EMA → Floor → Conviction → Supply → Action
    st.markdown(
        '<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
        'letter-spacing:.15em;color:' + LABEL + ';margin:.3rem 0 .2rem">'
        'Framework Hengky: Signal → EMA → Floor → Conviction → Supply → Action</p>',
        unsafe_allow_html=True)

    # ── Header card: ticker + signal + price + action ──────────────────────
    _hb = (
        '<div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);'
        'border-left:4px solid ' + g_col + ';border-radius:6px;padding:.75rem 1.1rem;'
        'margin:.4rem 0;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.5rem">'
        '<div style="display:flex;align-items:center;gap:.8rem">'
        '<span style="font-family:Orbitron,monospace;font-size:var(--text-xl);font-weight:800;color:' + WHITE + '">' + r.ticker + '</span>'
        '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:' + sig_col + '">' + (r.signal or '—') + '</span>'
        '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:' + LABEL + '">Rp' + f'{r.close:,.0f}' + '</span>'
        '</div>'
        '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);font-weight:700;'
        'background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);'
        'border-radius:3px;padding:3px 10px;color:' + g_col + '">' + r.action_label + '</span>'
        '</div>'
    )
    st.markdown(_hb, unsafe_allow_html=True)

    # ── Hengky framework points ──────────────────────────────────────────
    def _rpoint(icon, color, label, text):
        return (
            '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);'
            'color:' + LABEL + ';line-height:1.85;padding:.05rem 0">'
            + icon + ' <b style="color:' + color + '">' + label + '</b> ' + text
            + '</div>'
        )

    _pts = []

    # 1. Signal & Quality
    _sq_strong = r.signal in ("ACCUMULATION","BLOCK_BUY") and r.whale_quality == "SMART"
    _sq_ok     = r.signal in ("ACCUMULATION","BLOCK_BUY","RECOVERY_EARLY") or r.whale_quality in ("SMART","LIKELY_SMART")
    _sq_icon   = "✅" if _sq_strong else "⚠"
    _sq_col    = GREEN if _sq_strong else YELLOW if _sq_ok else RED
    _sq_note   = (
        "Sinyal kuat — ACCUMULATION SMART, idealnya untuk entry." if _sq_strong else
        f"{r.signal or '—'} + {r.whale_quality or '—'} — sinyal ada tapi belum sekuat ACCUMULATION SMART." if _sq_ok else
        f"Sinyal lemah ({r.signal or '—'} + {r.whale_quality or '—'}) — hati-hati entry."
    )
    _pts.append(_rpoint(_sq_icon, _sq_col, f"Signal & Quality: {r.signal or '—'} + {r.whale_quality or '—'} —", _sq_note))

    # 2. EMA Trend
    _ema_ok  = r.ema_trend in ("BULLISH",) if hasattr(r,"ema_trend") else getattr(r,"ema_trend_whale","") == "BULLISH"
    _ema_val = getattr(r,"ema_trend", None) or getattr(r,"ema_trend_whale","UNKNOWN")
    _ema_icon = "✅" if _ema_ok else "⚠"
    _ema_col  = GREEN if _ema_ok else YELLOW if _ema_val == "MIXED" else RED
    if _ema_ok:
        _ema_note = "EMA BULLISH — price di atas EMA13 dan EMA89. Konfirmasi tren kuat."
    elif _ema_val == "MIXED":
        _ema_note = "EMA MIXED — harga di atas EMA13 tapi belum menembus EMA89. Tunggu EMA jadi BULLISH."
    else:
        _ema_note = f"EMA {_ema_val} — tren belum mendukung. Entry prematur."
    _pts.append(_rpoint(_ema_icon, _ema_col, f"EMA Trend: {_ema_val} —", _ema_note))

    # 3. Floor Price
    _fp_ok   = fp_dist <= 10
    _fp_mid  = fp_dist <= 20
    _fp_icon = "✅" if _fp_ok else "⚠"
    _fp_col  = GREEN if _fp_ok else YELLOW if _fp_mid else RED
    _fp_zone = getattr(r, "entry_zone", None) or ("AT_FLOOR" if _fp_ok else "MID_RANGE" if _fp_mid else "FAR_FROM_FLOOR")
    if _fp_ok:
        _fp_note = f"Harga dekat floor ({fp_dist:.1f}% di atas Rp{r.floor_price:,.0f}). Zona ideal entry."
    elif _fp_mid:
        _target = round(r.floor_price * 1.05) if r.floor_price else 0
        _fp_note = f"Harga {fp_dist:.1f}% di atas floor (Rp{r.floor_price:,.0f}). Belum ideal. Tunggu pullback ke sekitar Rp{_target:,.0f}."
    else:
        _fp_note = f"Harga {fp_dist:.1f}% di atas floor — terlalu jauh. Risiko tinggi jika entry sekarang."
    _pts.append(_rpoint(_fp_icon, _fp_col, f"Floor Price: Rp{r.floor_price:,.0f} – {_fp_zone} —", _fp_note))

    # 4. Conviction & Control
    _cv_ok = r.conviction >= 7 and r.control_score >= 7
    _cv_med = r.conviction >= 5 or r.control_score >= 5
    _cv_icon = "✅" if _cv_ok else "⚠"
    _cv_col  = GREEN if _cv_ok else YELLOW if _cv_med else RED
    _peng_str = ""
    if getattr(r, "pengeringan", False):
        _peng_str = " · Pengeringan aktif ✓"
    if _cv_ok:
        _cv_note = "Conviction dan control tinggi. Sizing bisa normal."
    else:
        _cv_note = f"Conviction {r.conviction}/10 · Control {r.control_score}/10 — " + \
                   ("medium conviction, sizing kecil." if _cv_med else "conviction rendah, skip atau sizing sangat kecil.") + _peng_str
    _pts.append(_rpoint(_cv_icon, _cv_col, f"Conviction {r.conviction}/10 · Control {r.control_score}/10 —", _cv_note))

    # 5. Supply (insider/float)
    _ins = getattr(r, "insider_pct", 0) or 0
    _flt = getattr(r, "float_pct", 100) or 100
    _sup_ok  = _ins >= 60 or _flt <= 30
    _sup_icon = "✅" if _sup_ok else "⚠"
    _sup_col  = GREEN if _sup_ok else YELLOW
    _owner_str = f" · Owner: {r.major_holder}" if getattr(r,"major_holder",None) else ""
    if _sup_ok:
        _sup_note = f"Insider {_ins:.0f}% · Float {_flt:.0f}% — supply terkontrol dengan baik.{_owner_str}"
    else:
        _sup_note = f"Insider {_ins:.0f}% · Float {_flt:.0f}% — supply tersebar, perlu perhatian extra."
    _pts.append(_rpoint(_sup_icon, _sup_col, f"Supply: Insider {_ins:.0f}% · Float {_flt:.0f}% —", _sup_note))

    # 6. Liquidity
    _liq = getattr(r, "liquidity_bn", 0) or getattr(r, "value_bn", 0) or 0
    _liq_ok  = _liq >= 10
    _liq_icon = "✅" if _liq_ok else "⚠"
    _liq_col  = GREEN if _liq_ok else YELLOW if _liq >= 1 else RED
    if _liq_ok:
        _liq_note = f"Rp{_liq:.1f}Bn/hari ✅ Likuiditas bagus."
    elif _liq >= 1:
        _liq_note = f"Rp{_liq:.1f}Bn/hari — likuiditas cukup, hati-hati slippage."
    else:
        _liq_note = f"Rp{_liq:.2f}Bn/hari — likuiditas tipis, risiko susah exit."
    _pts.append(_rpoint(_liq_icon, _liq_col, f"Likuiditas: Rp{_liq:.1f}Bn/hari —", _liq_note))

    # Render semua points
    _html_pts = '<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);border-radius:6px;padding:.8rem 1.1rem;margin:.4rem 0">'
    _html_pts += "".join(_pts)
    _html_pts += "</div>"
    st.markdown(_html_pts, unsafe_allow_html=True)

    # ── KESIMPULAN ──────────────────────────────────────────────────────────
    _pass_count = sum([_sq_ok, _ema_ok, _fp_ok, _cv_ok, _sup_ok, _liq_ok])
    _strong_pass = sum([_sq_strong, _ema_ok, _fp_ok, _cv_ok])

    if _strong_pass >= 4:
        _kesimpulan = f"🟢 <b style='color:{GREEN}'>ENTRY SEKARANG.</b> Semua kriteria Hengky terpenuhi — {_pass_count}/6 pass. Sizing normal."
    elif _pass_count >= 4:
        _miss = []
        if not _ema_ok:   _miss.append("tunggu EMA jadi BULLISH")
        if not _fp_ok:    _miss.append(f"harga pullback ke Rp{round(r.floor_price*1.05):,.0f}" if r.floor_price else "harga dekat floor")
        if not _cv_ok:    _miss.append("conviction naik ke 7+")
        if not _sq_strong: _miss.append("sinyal upgrade ke ACCUMULATION SMART")
        _miss_str = "; ".join(f"({i+1}) {m}" for i,m in enumerate(_miss[:2]))
        _kesimpulan = f"🟡 <b style='color:{YELLOW}'>WATCHLIST AKTIF.</b> Setup menarik tapi belum semua terpenuhi: {_miss_str}. Pasang alert."
    elif _pass_count >= 2:
        _kesimpulan = f"🟡 <b style='color:{YELLOW}'>WATCHLIST PASIF.</b> {_pass_count}/6 kriteria terpenuhi. Pantau dari jauh, jangan masuk dulu."
    else:
        _kesimpulan = f"🔴 <b style='color:{RED}'>SKIP / JANGAN ENTRY.</b> Hanya {_pass_count}/6 kriteria terpenuhi. Terlalu banyak risiko."

    st.markdown(
        '<div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);'
        'border-radius:6px;padding:.65rem 1.1rem;margin:.4rem 0;'
        'font-family:Share Tech Mono,monospace;font-size:var(--text-sm);color:' + WHITE + '">'
        '→ <b>KESIMPULAN:</b> ' + _kesimpulan + '</div>',
        unsafe_allow_html=True)

with tab_flags:
    if r.flags:
        for fl in r.flags:
            st.markdown('<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:'+LABEL+'">'+fl+'</p>', unsafe_allow_html=True)
    else:
        st.markdown(f'<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:{LABEL}">Tidak ada flags.</p>', unsafe_allow_html=True)
