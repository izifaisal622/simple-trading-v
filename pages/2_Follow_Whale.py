"""
Simple Trading V6 — Follow Whale Dashboard V4
Hengky Adinata Method: Hitung Barang · Floor Price · Pengeringan · Smart Whale
"""
import sys
import streamlit as st
import pandas as pd
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

st.set_page_config(page_title="Follow Whale",
                   page_icon="🐋", layout="wide",
                   initial_sidebar_state="expanded")

from assets_ui import (
    get_page_css, render_sidebar, render_page_header, render_regime_bar,
    render_empty_state, sec_head, sparkline_svg,
    fmt_rp, fmt_pct, fmt_vol, fmt_bn, fmt_conv,
    SIG_COLORS, VP_ZONE_COLORS, REGIME_COLORS, NEON_GREEN,
    BG_CARD, BG_DEEP, TEXT_DIM, TEXT_MUTED, TEXT_MAIN,
    score_badge, vp_zone_pill, signal_badge,
)
_ = (sparkline_svg, fmt_rp, fmt_pct, fmt_vol, fmt_bn, fmt_conv, SIG_COLORS, VP_ZONE_COLORS, REGIME_COLORS, BG_CARD, BG_DEEP, TEXT_DIM, TEXT_MUTED, score_badge, vp_zone_pill, signal_badge)  # used in st.markdown HTML templates
LABEL = "var(--text-secondary)"  # Readable label color — overrides TEXT_MUTED for better contrast
try:
    from agents.ownership_agent import OwnershipAgent, get_broker_html as _get_broker_html
    _own_agent = OwnershipAgent()
    _HAS_OWNERSHIP = True
except Exception:
    _HAS_OWNERSHIP = False
    def _get_broker_html(x): return ""

try:
    from agents.broker_history import get_accumulation_trend, get_multi_period_summary
    from agents.ksei_agent import compute_hengky_math, render_hengky_math_html
    from agents.ksei_agent import save_manual_shareholders, parse_shareholder_csv
    _HAS_BROKER_HIST = True
except Exception:
    _HAS_BROKER_HIST = False

st.markdown(get_page_css("dashboard"), unsafe_allow_html=True)
st.markdown("""
<style>
/* ── INTEL PANEL toggle buttons — professional accordion style ── */
div[data-testid="stButton"] > button[kind="secondary"] {
  font-family: 'Share Tech Mono', monospace !important;
  font-size: 0.72rem !important;
  letter-spacing: 0.1em !important;
  font-weight: 400 !important;
  color: var(--text-secondary) !important;
  background: var(--bg-card) !important;
  border: 1px solid rgba(0,255,102,0.12) !important;
  border-radius: 3px !important;
  padding: 0.6rem 1rem !important;
  text-align: left !important;
  transition: all 0.2s !important;
  width: 100% !important;
}
div[data-testid="stButton"] > button[kind="secondary"]:hover {
  color: var(--accent) !important;
  border-color: rgba(0,255,102,0.35) !important;
  background: rgba(14,19,24,0.95) !important;
}
</style>
""", unsafe_allow_html=True)
st.markdown("""
<style>
.acc-wrap { margin-bottom: 0.4rem; }
.acc-wrap input[type="checkbox"] { display: none; }
.acc-label {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0.65rem 1rem; cursor: pointer;
  background: var(--bg-card); border: 1px solid rgba(0,255,102,0.1);
  border-radius: 3px; font-family: 'Share Tech Mono', monospace;
  font-size: 0.73rem; letter-spacing: 0.08em; color: var(--text-primary);
  transition: border-color 0.2s, color 0.2s; user-select: none;
}
.acc-label:hover { border-color: rgba(0,255,102,0.35); color: var(--accent); }
.acc-label .acc-arrow {
  color: rgba(0,255,102,0.45); font-size: 0.75rem;
  transition: transform 0.25s ease;
  font-family: 'Share Tech Mono', monospace; flex-shrink: 0;
}
.acc-wrap input:checked + .acc-label { color: var(--accent);
  border-color: rgba(0,255,102,0.25); border-radius: 3px 3px 0 0; }
.acc-wrap input:checked + .acc-label .acc-arrow { transform: rotate(90deg); }
.acc-content { display: none; padding: 0.9rem 1rem;
  background: var(--bg-base); border: 1px solid rgba(0,255,102,0.1);
  border-top: none; border-radius: 0 0 3px 3px; }
.acc-wrap input:checked ~ .acc-content { display: block; }
</style>
""", unsafe_allow_html=True)
st.markdown("""
<style>
/* Hide the invisible-label expanders' summary text (shows as blank/⠀) */
.stExpander details > summary > div > p {
  font-size: 0 !important; color: transparent !important;
  line-height: 0 !important; height: 0 !important;
  margin: 0 !important; padding: 0 !important;
}
.stExpander details > summary {
  padding: 0.1rem 0.5rem !important;
  min-height: 0 !important; height: 1px !important;
  overflow: hidden !important; border: none !important;
  background: transparent !important;
}
/* Also hide the toggle icon completely for these */
.stExpander details > summary [data-testid="stExpanderToggleIcon"] {
  display: none !important;
}
</style>
""", unsafe_allow_html=True)

# ── Load data ─────────────────────────────────────────────────────────────────
LOGS_DIR     = Path(__file__).parent.parent / "logs"
RESULTS_FILE = LOGS_DIR / "daily_results.json"
JOURNAL_FILE = LOGS_DIR / "journal.md"
PLAYBOOK     = LOGS_DIR / "edge_playbook.md"
LESSONS      = LOGS_DIR / "lessons.md"
MANDATES     = LOGS_DIR / "improvement_mandates.md"
STUDY_FILE   = LOGS_DIR / "market_study.json"

last = {}
if RESULTS_FILE.exists():
    try: last = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    except Exception: pass

whale_results = last.get("whale_results", [])
ctx           = last.get("whale_context", {})
regime        = last.get("regime", {})
scan_date     = last.get("date","—")[:10] if last.get("date") else "—"

cycle       = ctx.get("cycle",    regime.get("cycle","—"))
ihsg        = ctx.get("ihsg",     regime.get("ihsg", 0))
mom_4w      = ctx.get("mom_4w",   regime.get("mom_4w", 0))
mom_2w      = ctx.get("mom_2w",   regime.get("mom_2w", 0))
pct_from_low= ctx.get("pct_from_low", regime.get("pct_from_low", 0))
mom_13w     = ctx.get("mom_13w",  regime.get("mom_13w", 0))
breadth     = ctx.get("breadth",  regime.get("breadth", 0))
tradeable   = ctx.get("tradeable", True)
mkt_status  = ctx.get("market_status","—")
mkt_advice  = ctx.get("market_advice","Run scan untuk load data")
mkt_color   = ctx.get("market_color","var(--text-muted)")
description = ctx.get("description","—")
sizing      = ctx.get("sizing_advice","—")
min_conv    = ctx.get("min_conviction", 5)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    render_sidebar("whale",
                   ema_total   = last.get("ema_total", 0),
                   whale_total = last.get("whale_total", len(whale_results)),
                   scan_date   = scan_date,
                   regime      = cycle)

    # ── Phase 3: Stockbit token ────────────────────────────────────────────
    if _HAS_OWNERSHIP:
        st.markdown("""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);
        letter-spacing:0.2em;color:var(--text-dim);margin:1rem 0 0.3rem;padding:0 0.75rem">
        ◆ BROKER DATA (PHASE 3)</p>""", unsafe_allow_html=True)

        token_file = Path(__file__).parent.parent / "data" / "stockbit_token.json"
        has_token  = token_file.exists()
        token_age  = ""
        if has_token:
            import json as _json
            try:
                _td = _json.loads(token_file.read_text())
                from datetime import datetime as _dt
                _age = (_dt.now() - _dt.fromisoformat(_td.get("saved_at","2000-01-01"))).total_seconds()/3600
                token_age = f"✅ {_age:.0f}h ago" if _age < 23 else "⚠️ Expired"
            except Exception: token_age = "?"

        _tok_color = "var(--accent)" if "h ago" in token_age else "var(--c-danger)"
        _tok_text  = token_age if has_token else "Not set"
        st.markdown(f"""<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
        color:var(--text-dim);padding:0 0.75rem 0.3rem">
        Stockbit token: <b style="color:{_tok_color}">{_tok_text}</b>
        </div>""", unsafe_allow_html=True)

        if "show_token_input" not in st.session_state:
            st.session_state.show_token_input = False
        _tok_lbl = "[−] INPUT TOKEN" if st.session_state.show_token_input else "[+] INPUT TOKEN"
        if st.button(_tok_lbl, key="btn_token_toggle", width="stretch"):
            st.session_state.show_token_input = not st.session_state.show_token_input
        if st.session_state.show_token_input:
            st.markdown("""<div style="background:var(--bg-base);border:1px solid rgba(0,255,102,0.1);
            border-top:none;border-radius:0 0 3px 3px;padding:0.7rem">""",
            unsafe_allow_html=True)
            with st.form("token_form", clear_on_submit=True):
                new_token = st.text_input("Paste JWT Token", type="password",
                                          placeholder="eyJhbGci...",
                                          key="sb_token_input",
                                          label_visibility="collapsed")
                save_tok = st.form_submit_button("💾 SAVE TOKEN  (atau tekan Enter ↵)",
                                                 use_container_width=True)
                if save_tok:
                    if new_token and new_token.startswith("ey"):
                        _own_agent.save_stockbit_token(new_token)
                        st.session_state.show_token_input = False
                        st.success("✅ Token saved!")
                    elif save_tok:
                        st.error("⚠ Token tidak valid — harus diawali 'ey...'")
            st.markdown("""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);
            color:var(--text-dim);line-height:1.6;margin:0.4rem 0 0">
            1. Login Stockbit di browser<br>
            2. F12 → Network → filter "exodus"<br>
            3. Klik request → Headers<br>
            4. Copy nilai setelah "Bearer "
            </p>""", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

# ── Page header ───────────────────────────────────────────────────────────────
import json as _j; from pathlib import Path as _Pv
try:
    _ver_accent = "V" + _j.loads((_Pv(__file__).parent.parent/"version.json").read_text())["version"]
except Exception:
    _ver_accent = "V6"

render_page_header(
    eyebrow  = "◆ MODULE 02 · SMART MONEY TRACKING",
    title    = "SIMPLE TRADING ",
    accent   = _ver_accent,
    subtitle = "◈ FOLLOW THE WHALE · HENGKY ADINATA · HITUNG BARANG · FLOOR PRICE · ORDER BLOCK",
    scan_date= scan_date,
)

# ── Market Status ─────────────────────────────────────────────────────────────
m13_color = NEON_GREEN if mom_13w > 0 else "var(--c-danger)"
extra_regime = f'<span class="r-label">13W <b style="color:{m13_color}">{mom_13w:+.1f}%</b></span> <span class="r-label">MARKET <b style="color:{mkt_color}">{mkt_status}</b></span>'

if not tradeable:
    st.markdown(f"""
    <div style="background:rgba(26,0,0,0.7);border:1px solid rgba(239,68,68,0.4);
    border-left:3px solid var(--c-danger);border-radius:var(--r-sm);padding:0.8rem 1.4rem;margin-bottom:1rem;
    font-family:Share Tech Mono,monospace">
      <div style="color:var(--c-danger);font-size:var(--text-base);font-weight:700;letter-spacing:0.15em">
        ⛔ {mkt_status} — STOP TRADE
      </div>
      <div style="color:var(--text-muted);font-size:var(--text-sm);margin-top:0.3rem">{mkt_advice}</div>
    </div>""", unsafe_allow_html=True)

render_regime_bar(cycle, ihsg, mom_4w, breadth, scan_date, extra=extra_regime, mom_2w=mom_2w, pct_from_low=pct_from_low)

# ── Session state init (semua panel toggle — satu tempat, tidak ada duplicate) ─
for _panel_key in ("panel_hengky", "panel_director", "panel_journal", "panel_lessons"):
    if _panel_key not in st.session_state:
        st.session_state[_panel_key] = False

# ── Hengky Framework ──────────────────────────────────────────────────────────
_hengky_lbl = "[−] ◈ HENGKY ADINATA FRAMEWORK" if st.session_state.panel_hengky else "[+] ◈ HENGKY ADINATA FRAMEWORK"
if st.button(_hengky_lbl, key="btn_hengky", width="stretch"):
    st.session_state.panel_hengky = not st.session_state.panel_hengky

if st.session_state.panel_hengky:
    rules_l = [
        ("Hitung barang", "Berapa lot beredar? Siapa yang pegang? Di harga berapa? Control score tinggi = supply terpusat = mudah dinaikkan."),
        ("Floor price", "Titik di mana emiten rugi kalau turun lagi. Di sinilah mereka defend. Entry ideal = di floor atau dekat floor."),
        ("Pengeringan barang", "Vol tinggi + harga stagnan = barang berpindah dari retail ke smart money. Makin kering makin siap naik."),
        ("Broker fingerprint", "MG/BK/AK/SQ beli = owner/institusi masuk. ZP/DX jual = retail exit. Supply makin terpusat."),
        ("Order Block", "Compression sebelum displacement = institutional footprint. Price revisit OB zone = entry terbaik."),
    ]
    rules_r = [
        ("Market sepi = stop trade", "Breakout tanpa partisipan = hammer closing. Mubazir."),
        ("IDX long only", "Distribusi = awareness saja. Bukan short signal."),
        ("Smart vs dumb whale", "Smart whale defend waktu turun. Dumb whale biarkan drift."),
        ("Be early", "Kalau sudah ramai dibicarakan, biasanya sudah telat."),
        ("Jangan cinta saham", "Waktunya buang ya buang. Duit bisa cari lagi."),
    ]

    def _cell(title, desc, border):
        return f"""<div style="background:var(--bg-deep);border:1px solid {border};
border-radius:var(--r-sm);padding:0.65rem 0.9rem;height:100%;
display:flex;flex-direction:column">
  <div style="font-family:Orbitron,monospace;font-size:var(--text-xs);font-weight:700;
  color:#00ff66;letter-spacing:0.05em;margin-bottom:4px">{title}</div>
  <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
  color:#94A3B8;line-height:1.55;flex:1">{desc}</div>
</div>"""

    # Pad shorter list so both sides have equal rows
    max_rows = max(len(rules_l), len(rules_r))
    _rules_l = rules_l + [("", "")] * (max_rows - len(rules_l))
    _rules_r = rules_r + [("", "")] * (max_rows - len(rules_r))

    rows_html = ""
    for (lt, ld), (rt, rd) in zip(_rules_l, _rules_r):
        l_html = _cell(lt, ld, "rgba(0,255,102,0.2)") if lt else "<div></div>"
        r_html = _cell(rt, rd, "rgba(0,255,102,0.12)") if rt else "<div></div>"
        rows_html += f"""<div style="display:grid;grid-template-columns:1fr 1fr;
gap:0.5rem;margin-bottom:0.4rem;align-items:stretch">{l_html}{r_html}</div>"""

    headers_html = f"""<div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;
margin-bottom:0.4rem">
  <div style="font-family:Orbitron,monospace;font-size:var(--text-xs);font-weight:700;
  color:#00ff66;letter-spacing:0.12em">◆ ANALISIS SEBELUM MASUK</div>
  <div style="font-family:Orbitron,monospace;font-size:var(--text-xs);font-weight:700;
  color:#00ff66;letter-spacing:0.12em">◆ RULES OF ENGAGEMENT</div>
</div>"""

    st.markdown(headers_html + rows_html, unsafe_allow_html=True)


sec_head("◆ SCAN CONTROLS")
c1,c2,c3,c4,c5 = st.columns([1.6,1.2,1,1.3,1])
with c1: run_scan      = st.button("⟳ RUN ADAPTIVE SCAN", type="primary", width="stretch")
with c2: mode          = st.selectbox("UNIVERSE", ["Full IDX (~350)","Watchlist (~100)"])
with c3: top_n         = st.number_input("TOP N", 10, 100, 30, 10)
with c4: manual_vol    = st.number_input("OVERRIDE VOL× (0=auto)", 0.0, 10.0, 0.0, 0.5)
with c5: min_conv_ui   = st.number_input("MIN CONVICTION", 1, 10, 4, 1)

if run_scan:
    with st.spinner("◈ ADAPTING TO MARKET · FLOOR PRICES · PENGERINGAN · SECTOR CAP..."):
        try:
            from agents.whale_scanner import WhaleScanner
            # None = let adapt_to_market() choose optimal for current regime
            vc = manual_vol if manual_vol > 0 else None
            scanner = WhaleScanner(vol_multiplier=vc, min_value_bn=None)
            results, new_ctx = (scanner.scan_watchlist(top_n=int(top_n))
                                if "Watchlist" in mode else scanner.scan(top_n=int(top_n)))
            best     = scanner.get_best_long(results, min_conviction=int(min_conv_ui))
            peng     = scanner.get_pengeringan(results)
            at_floor = scanner.get_at_floor(results)
            recov    = scanner.get_recovery_watchlist(results)
            distrib  = scanner.get_distribution_watch(results)

            je = (f"\n---\n## 🐋 Whale Scan — {datetime.now().strftime('%d %b %Y %H:%M')}\n"
                  f"- Cycle: **{new_ctx.get('cycle','?')}** | Market: **{new_ctx.get('market_status','?')}**\n"
                  f"- Total: {len(results)} | 🟢 Best: {len(best)} | 💧 Peng: {len(peng)} | "
                  f"🎯 Floor: {len(at_floor)} | 🌅 Recovery: {len(recov)} | 🔴 Distrib: {len(distrib)}\n")

            existing = {}
            if RESULTS_FILE.exists():
                try: existing = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
                except Exception: pass
            existing.update({"whale_results":results,"whale_total":len(results),
                             "whale_context":new_ctx,"date":datetime.now().isoformat()})
            RESULTS_FILE.write_text(json.dumps(existing,indent=2,default=str), encoding="utf-8")
            prev = JOURNAL_FILE.read_text(encoding="utf-8") if JOURNAL_FILE.exists() else "# Journal\n"
            JOURNAL_FILE.write_text(prev+je, encoding="utf-8")
            st.success(f"◈ COMPLETE — {len(results)} alerts | 🟢 {len(best)} best | "
                       f"💧 {len(peng)} peng | 🎯 {len(at_floor)} floor | "
                       f"🌅 {len(recov)} recov | 🔴 {len(distrib)} dist")
            st.rerun()
        except Exception as e:
            st.error(f"ERROR: {e}")
            import traceback; st.code(traceback.format_exc())

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def tags_html(w: dict) -> str:
    t = []
    if w.get("pengeringan_detected"):  t.append('<span class="tag tag-b">💧 pengeringan</span>')
    if w.get("whale_defending"):       t.append('<span class="tag tag-g">🛡 defend</span>')
    z = w.get("entry_zone","")
    if z == "AT_FLOOR":                t.append('<span class="tag tag-g">🎯 at-floor</span>')
    elif z == "NEAR_FLOOR":            t.append('<span class="tag tag-g">✅ near-floor</span>')
    elif z == "MID_RANGE":             t.append('<span class="tag tag-y">◎ mid</span>')
    else:                              t.append('<span class="tag tag-x">✕ far</span>')
    if w.get("pattern")=="SUSTAINED":  t.append('<span class="tag tag-b">📅 sustained</span>')
    mom = w.get("momentum","")
    if mom=="ACCELERATING":            t.append('<span class="tag tag-g">⚡ acc</span>')
    elif mom=="REVERSING":             t.append('<span class="tag tag-y">↗ rev</span>')
    # V4 tags
    if w.get("is_centralized"):        t.append('<span class="tag tag-g">🔒 supply terpusat</span>')
    if w.get("in_ob_zone"):            t.append('<span class="tag tag-g">📦 di OB zone</span>')
    elif w.get("near_ob_zone"):        t.append('<span class="tag tag-y">📦 dekat OB</span>')
    return "".join(t)




def _render_analysis_card(w: dict, tradeable: bool = False) -> None:
    """Render structured analysis card per saham — Hengky framework."""
    import streamlit as st

    ticker   = w.get("ticker","").replace(".JK","")
    signal   = w.get("signal","")
    qual     = w.get("whale_quality","")
    ema_tr   = w.get("ema_trend","")
    close    = w.get("close",0)
    floor_p  = w.get("floor_price",0)
    pct_f    = w.get("pct_above_floor",0)
    zone     = w.get("entry_zone","")
    conv     = w.get("conviction",0)
    ctrl     = w.get("control_score",0)
    ff       = w.get("free_float",100)
    insider  = w.get("pct_insider",0)
    sc       = w.get("supply_control","")
    ob_det   = w.get("ob_detected",False)
    ob_type  = w.get("ob_type","")
    ob_h     = w.get("ob_high",0)
    ob_l     = w.get("ob_low",0)
    in_ob    = w.get("in_ob_zone",False)
    near_ob  = w.get("near_ob_zone",False)
    ob_str   = w.get("ob_strength",0)
    mom5     = w.get("mom_5d",0)
    w52h     = w.get("pct_from_52w_high",0)
    val_bn   = w.get("value_bn",0)
    owner    = w.get("owner_name","")
    peng     = w.get("pengeringan_detected",False)
    peng_d   = w.get("pengeringan_desc","")
    def_     = w.get("whale_defending",False)
    ff_vol   = w.get("ff_adj_vol_ratio", w.get("vol_ratio",0))
    sector   = w.get("sector","")

    # ── Scoring per criterion ─────────────────────────────────────────────────
    def score_icon(ok):
        return ("✅" if ok == "good" else "⚠️" if ok == "warn" else "❌")

    signal_ok  = "good" if signal == "ACCUMULATION"   else "warn" if signal in ("BLOCK_BUY","VOL_SPIKE_UP") else "warn"
    qual_ok    = "good" if qual in ("SMART","LIKELY_SMART") else "warn"
    ema_ok     = "good" if ema_tr == "BULLISH"        else "warn" if ema_tr == "MIXED"  else "bad"
    floor_ok   = "good" if pct_f <= 15                else "warn" if pct_f <= 30        else "bad"
    conv_ok    = "good" if conv >= 7                  else "warn" if conv >= 4          else "bad"
    supply_ok  = "good" if ff <= 20                   else "warn" if ff <= 35           else "bad"
    liq_ok     = "good" if val_bn >= 5                else "warn" if val_bn >= 1        else "bad"

    # ── Entry target ──────────────────────────────────────────────────────────
    entry_low  = floor_p * 1.02
    entry_high = floor_p * 1.12
    if ob_det and ob_l > 0:
        entry_low  = min(entry_low,  ob_l * 1.01)
        entry_high = max(entry_high, ob_h * 0.99)

    # ── Overall verdict ───────────────────────────────────────────────────────
    good_count = sum([
        signal_ok=="good", qual_ok=="good", ema_ok=="good",
        floor_ok=="good",  conv_ok=="good", supply_ok=="good"
    ])
    if good_count >= 5:
        verdict  = "PRIORITAS"
        v_col    = "var(--accent)"
        v_col_hex= "#00FF66"   # resolved hex — dipakai di opacity suffix
        v_bg     = "rgba(0,255,102,0.06)"
        v_border = "rgba(0,255,102,0.3)"
    elif good_count >= 3:
        verdict  = "WATCHLIST AKTIF"
        v_col    = "var(--c-warning)"
        v_col_hex= "#F0B429"
        v_bg     = "rgba(240,180,41,0.04)"
        v_border = "rgba(240,180,41,0.25)"
    else:
        verdict  = "WATCHLIST PASIF"
        v_col    = "var(--text-secondary)"
        v_col_hex= "#64748B"
        v_bg     = "rgba(100,116,139,0.04)"
        v_border = "rgba(100,116,139,0.2)"

    if not tradeable:
        verdict += " (STOP TRADE — build watchlist)"

    # ── Narrative generation ──────────────────────────────────────────────────
    narratives = []

    # 1. Signal + Quality
    if signal == "ACCUMULATION" and qual in ("SMART","LIKELY_SMART"):
        narratives.append(f"**{score_icon(signal_ok)} Signal & Quality:** ACCUMULATION + {qual} — ada smart money aktif mengumpulkan. Bukan sekadar harga turun, ada yang beli diam-diam.")
    else:
        narratives.append(f"**{score_icon(signal_ok)} Signal & Quality:** {signal} + {qual} — sinyal ada tapi belum sekuat ACCUMULATION SMART.")

    # 2. EMA
    if ema_tr == "BULLISH":
        narratives.append(f"**{score_icon(ema_ok)} EMA Trend: BULLISH** — momentum sudah berputar. Harga di atas EMA13 dan EMA89. Konfirmasi teknikal mendukung.")
    elif ema_tr == "MIXED":
        narratives.append(f"**{score_icon(ema_ok)} EMA Trend: MIXED** — harga di atas EMA13 tapi belum menembus EMA89. Tunggu EMA jadi BULLISH untuk konfirmasi lebih kuat.")
    else:
        narratives.append(f"**{score_icon(ema_ok)} EMA Trend: BEARISH** — masih downtrend. Recovery play yang butuh kesabaran ekstra.")

    # 3. Floor price
    if pct_f <= 5:
        narratives.append(f"**{score_icon(floor_ok)} Floor Price: Rp{floor_p:,.0f} — AT FLOOR** ✨ Harga sekarang Rp{close:,.0f} hanya {pct_f:.1f}% di atas floor. Ini zona entry ideal Hengky — R/R terbaik.")
    elif pct_f <= 15:
        narratives.append(f"**{score_icon(floor_ok)} Floor Price: Rp{floor_p:,.0f} — NEAR FLOOR** — Harga {pct_f:.1f}% di atas floor. Masih acceptable. Target entry Rp{entry_low:,.0f}–{entry_high:,.0f}.")
    elif pct_f <= 30:
        narratives.append(f"**{score_icon(floor_ok)} Floor Price: Rp{floor_p:,.0f} — MID RANGE** — Harga sudah {pct_f:.1f}% di atas floor. Belum ideal. Tunggu pullback ke sekitar Rp{entry_low:,.0f}–{entry_high:,.0f}.")
    else:
        narratives.append(f"**{score_icon(floor_ok)} Floor Price: Rp{floor_p:,.0f} — FAR** ❌ Harga {pct_f:.1f}% di atas floor. R/R buruk. Skip atau tunggu koreksi dalam ke Rp{entry_low:,.0f}.")

    # 4. Conviction
    narratives.append(f"**{score_icon(conv_ok)} Conviction {conv}/10 · Control {ctrl}/10** — {'High conviction, setup matang.' if conv>=7 else 'Medium conviction, sizing kecil.' if conv>=4 else 'Low conviction, watchlist saja.'}" +
        (f" Pengeringan aktif: {peng_d.replace('Pengeringan: ','')}" if peng and peng_d else "") +
        (" Whale defend aktif." if def_ else ""))

    # 5. Supply concentration
    if ff > 0:
        if ff <= 15:
            narratives.append(f"**{score_icon(supply_ok)} Supply: Insider {insider:.0f}% · Float {ff:.0f}% — SANGAT KETAT** ✨ " +
                (f"Dikontrol {owner}. " if owner else "") +
                "Float sangat sedikit = kalau owner defend, harga bisa bergerak cepat.")
        elif ff <= 25:
            narratives.append(f"**{score_icon(supply_ok)} Supply: Insider {insider:.0f}% · Float {ff:.0f}% — KETAT** — " +
                (f"Owner: {owner}. " if owner else "") +
                "Supply terkontrol dengan baik.")
        else:
            narratives.append(f"**{score_icon(supply_ok)} Supply: Float {ff:.0f}% — MODERATE/BEBAS** — " +
                (f"Owner: {owner}. " if owner else "") +
                "Supply lebih bebas, harga lebih sulit digerakkan.")
    
    # 6. Order Block
    if ob_det:
        if in_ob:
            narratives.append(f"**{score_icon('good')} Order Block {ob_type}: Rp{ob_l:,.0f}–{ob_h:,.0f} — DI DALAM ZONE** ✨ Harga sekarang di zona institutional footprint. Entry zone paling ideal.")
        elif near_ob:
            narratives.append(f"**{score_icon('warn')} Order Block {ob_type}: Rp{ob_l:,.0f}–{ob_h:,.0f} — MENDEKATI ZONE** — Harga hampir menyentuh OB zone. Kalau pullback masuk zone ini = entry opportunity.")
        else:
            narratives.append(f"**{score_icon('warn')} Order Block {ob_type}: Rp{ob_l:,.0f}–{ob_h:,.0f} — OB TERBENTUK** — Zona institusional ada di sana. Pantau kalau harga revisit.")

    # 7. Liquidity
    if val_bn < 1:
        narratives.append(f"**{score_icon(liq_ok)} Likuiditas: Rp{val_bn*1000:.0f}Jt/hari — TIPIS** ⚠️ Hati-hati sizing. Sulit keluar kalau mau jual jumlah besar.")
    elif val_bn < 5:
        narratives.append(f"**{score_icon(liq_ok)} Likuiditas: Rp{val_bn:.1f}Bn/hari** — Cukup untuk retail sizing.")
    else:
        narratives.append(f"**{score_icon(liq_ok)} Likuiditas: Rp{val_bn:.1f}Bn/hari** ✅ Likuiditas bagus.")

    # 8. Conclusion
    if floor_ok == "bad":
        action = f"**SKIP sekarang.** Harga terlalu jauh dari floor (+{pct_f:.0f}%). Tunggu koreksi ke Rp{entry_low:,.0f}–{entry_high:,.0f} dulu."
    elif ema_ok == "bad":
        action = f"**WATCHLIST PASIF.** EMA masih BEARISH. Masukkan di list, pantau mingguan. Entry kalau EMA berubah BULLISH + pullback ke Rp{entry_low:,.0f}–{entry_high:,.0f}."
    elif ema_ok == "warn" and floor_ok == "warn":
        action = f"**WATCHLIST AKTIF.** Setup menarik tapi dua konfirmasi belum terpenuhi: (1) tunggu EMA jadi BULLISH, (2) harga pullback ke Rp{entry_low:,.0f}–{entry_high:,.0f}. Pasang alert."
    elif floor_ok == "warn":
        action = f"**WATCHLIST AKTIF.** EMA sudah BULLISH, sinyal bagus. Tunggu pullback ke Rp{entry_low:,.0f}–{entry_high:,.0f} untuk entry dengan R/R lebih baik. Kalau breakout dengan volume tinggi bisa kejar dengan sizing 50%."
    else:
        action = f"**ENTRY ZONA** — Semua kriteria terpenuhi. Entry di Rp{entry_low:,.0f}–{entry_high:,.0f}. SL di bawah floor Rp{floor_p*0.97:,.0f}."

    # ── Render ────────────────────────────────────────────────────────────────
    _ = (zone, sc, ob_str, mom5, w52h, ff_vol, ticker, sector, action, v_col, v_bg, v_border)  # template vars
    st.markdown(f"""
    <div style="background:{v_bg};border:1px solid {v_border};border-left:4px solid {v_col};
    border-radius:var(--r-md);padding:1rem 1.2rem;margin-bottom:0.8rem">
      <div style="display:flex;align-items:center;gap:1rem;margin-bottom:0.7rem;
      padding-bottom:0.6rem;border-bottom:1px solid rgba(255,255,255,0.06)">
        <span style="font-family:Orbitron,monospace;font-size:var(--text-xl);font-weight:900;
        color:var(--text-primary)">{ticker}</span>
        <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);
        color:var(--text-muted)">{signal} · {sector}</span>
        <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);
        color:var(--text-primary);font-weight:700">Rp{close:,.0f}</span>
        <span style="background:{v_col_hex}20;border:1px solid {v_col_hex}50;border-radius:var(--r-sm);
        padding:2px 10px;font-family:Orbitron,monospace;font-size:var(--text-xs);
        font-weight:700;color:{v_col};margin-left:auto">{verdict}</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Render narratives as markdown in container
    with st.container():
        for n in narratives:
            st.markdown(f"""<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);
            color:var(--text-secondary);line-height:1.8;padding:0.1rem 0 0.1rem 1.2rem;
            border-left:2px solid rgba(0,255,102,0.08)">{n}</div>""",
            unsafe_allow_html=True)

        # Conclusion box
        st.markdown(f"""<div style="background:rgba(0,0,0,0.3);border:1px solid {v_col_hex}30;
        border-radius:var(--r-sm);padding:0.6rem 1rem;margin-top:0.6rem;
        font-family:Share Tech Mono,monospace;font-size:var(--text-sm);color:var(--text-primary);line-height:1.7">
        <span style="color:{v_col};font-weight:700">→ KESIMPULAN: </span>{action}
        </div>""", unsafe_allow_html=True)



def _render_broker_ksei_tab(whale_results: list, min_conv: int) -> None:
    """Tab 7: Broker History + KSEI Ownership + Hengky Math."""
    import streamlit as st
    import pandas as pd
    from pathlib import Path as _P7Path

    st.markdown("""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
    color:var(--text-muted);letter-spacing:0.08em;margin-bottom:1rem">
    Akumulasi broker historis · Hengky lot math · Upload data kepemilikan KSEI
    </p>""", unsafe_allow_html=True)

    # P02-D: Onboarding card — tampil jika token belum ada
    _token_file = _P7Path(__file__).parent.parent / "data" / "stockbit_token.json"
    _has_token  = _token_file.exists()
    if not _has_token:
        st.markdown("""
<div style="background:rgba(96,165,250,0.06);border:1px solid rgba(96,165,250,0.25);
border-left:4px solid #60A5FA;border-radius:var(--r-md);padding:1rem 1.2rem;margin-bottom:1rem">
  <div style="font-family:Orbitron,monospace;font-size:var(--text-sm);font-weight:700;
  color:#60A5FA;letter-spacing:0.1em;margin-bottom:0.6rem">🏦 SETUP BROKER DATA</div>
  <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
  color:#94A3B8;line-height:2.0">
    Tab ini menampilkan data akumulasi broker historis dari Stockbit.<br>
    Tanpa token, hanya data KSEI manual yang tersedia.<br><br>
    <b style="color:#E2E8F0">Cara dapat token Stockbit (1x setup, berlaku ~24 jam):</b><br>
    <span style="color:#60A5FA">1.</span> Login ke <b>stockbit.com</b> di browser<br>
    <span style="color:#60A5FA">2.</span> Tekan <b>F12</b> → tab <b>Network</b><br>
    <span style="color:#60A5FA">3.</span> Filter pencarian: ketik <b>exodus</b><br>
    <span style="color:#60A5FA">4.</span> Klik salah satu request → tab <b>Headers</b><br>
    <span style="color:#60A5FA">5.</span> Cari header <b>Authorization</b> → copy nilai setelah <b>"Bearer "</b><br>
    <span style="color:#60A5FA">6.</span> Paste di sidebar kiri → <b>[+] INPUT TOKEN</b>
  </div>
</div>
""", unsafe_allow_html=True)

    if not _HAS_BROKER_HIST:
        st.warning("Module broker_history / ksei_agent tidak tersedia.")
        return

    # ── Section 1: Accumulation Trend ────────────────────────────────────────
    sec_head("◆ AKUMULASI BROKER — MULTI PERIOD")

    tickers = [w.get("ticker","").replace(".JK","") for w in whale_results
               if w.get("conviction",0) >= min_conv][:15]

    if not tickers:
        st.markdown("""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
        color:var(--text-dim)">Tidak ada hasil scan. Jalankan scan dulu.</p>""",
        unsafe_allow_html=True)
    else:
        # Period selector
        period_col, ticker_col = st.columns([1,3])
        with period_col:
            sel_period = st.selectbox("PERIODE", ["1W","1M","3M","6M"],
                                      index=1, key="broker_period")
        with ticker_col:
            sel_ticker = st.selectbox("SAHAM", tickers, key="broker_ticker")

        period_days = {"1W":7,"1M":30,"3M":90,"6M":180}[sel_period]

        if sel_ticker:
            trend = get_accumulation_trend(sel_ticker, period_days)
            if not trend.get("available"):
                st.markdown(f"""<div style="background:rgba(0,0,0,0.2);border:1px solid
                rgba(255,255,255,0.06);border-radius:var(--r-sm);padding:0.8rem 1rem;
                font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--text-muted)">
                📊 Belum ada data broker historis untuk <b style="color:var(--text-primary)">{sel_ticker}</b>.
                <br>Data akan terakumulasi otomatis setiap scan (butuh token Stockbit aktif).
                <br>Atau upload CSV manual di bawah.
                </div>""", unsafe_allow_html=True)
            else:
                acc   = trend["acc_signal"]
                sp    = trend["smart_buy_pct"]
                net   = trend["smart_net_lot"]
                days  = trend["days"]
                acc_col = "var(--accent)" if "ACCUMULATION" in acc else "var(--c-danger)" if "DIST" in acc else "var(--c-warning)"

                _ = (sp, net, days, acc_col)  # template vars
                st.markdown(f"""
                <div style="background:rgba(0,0,0,0.2);border:1px solid rgba(0,255,102,0.1);
                border-left:4px solid {acc_col};border-radius:var(--r-md);padding:0.8rem 1rem;
                margin-bottom:0.6rem">
                  <div style="display:flex;gap:1.5rem;flex-wrap:wrap">
                    <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
                    color:var(--text-dim)">📊 {sel_ticker} · {days} hari data</span>
                    <span style="font-family:Orbitron,monospace;font-size:var(--text-sm);
                    font-weight:700;color:{acc_col}">{acc}</span>
                    <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
                    color:var(--text-primary)">Smart Buy {sp:.0f}% hari</span>
                    <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
                    color:{'var(--accent)' if net>0 else 'var(--c-danger)'}">Net {net:+,.0f} lot</span>
                  </div>
                </div>""", unsafe_allow_html=True)

                # Top smart brokers table
                top_b = trend.get("top_smart_brokers",[])
                if top_b:
                    rows = []
                    for b in top_b:
                        rows.append({
                            "Broker": f"{b['code']} — {b['name']}",
                            "Type":   b["type"],
                            "Buy Lot": b["buy"],
                            "Sell Lot":b["sell"],
                            "Net Lot": b["net"],
                        })
                    df = pd.DataFrame(rows)
                    st.dataframe(df, width="stretch", hide_index=True)

                # Multi-period summary
                st.markdown("""<p style="font-family:Share Tech Mono,monospace;
                font-size:var(--text-xs);color:var(--text-dim);margin:0.6rem 0 0.3rem;
                letter-spacing:0.1em">RANGKUMAN SEMUA PERIODE</p>""",
                unsafe_allow_html=True)
                mp = get_multi_period_summary(sel_ticker)
                mp_rows = []
                for label, pdata in mp["periods"].items():
                    if pdata.get("available"):
                        mp_rows.append({
                            "Periode":    label,
                            "Hari Data":  pdata["days"],
                            "Smart Buy%": f"{pdata['smart_buy_pct']:.0f}%",
                            "Net Lot":    f"{pdata['smart_net_lot']:+,.0f}",
                            "Signal":     pdata["acc_signal"],
                        })
                    else:
                        mp_rows.append({"Periode":label,"Hari Data":0,
                                       "Smart Buy%":"—","Net Lot":"—","Signal":"NO DATA"})
                if mp_rows:
                    st.dataframe(pd.DataFrame(mp_rows), width="stretch", hide_index=True)

    # ── Section 2: KSEI / Hengky Math ────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    sec_head("◆ HENGKY LOT MATH — KSEI OWNERSHIP")

    ksei_ticker = st.selectbox("Pilih Saham", tickers or ["MBSS"], key="ksei_ticker")

    c1,c2 = st.columns(2)
    with c1:
        shares_out = st.number_input("Shares Outstanding (juta)", value=0.0,
                                     step=100.0, key="ksei_shares",
                                     help="Total saham beredar dalam jutaan. Cek di laporan tahunan.")
    with c2:
        ff_override = st.number_input("Free Float Override (%)", value=0.0,
                                      step=1.0, key="ksei_ff",
                                      help="Override free float. 0 = gunakan database default.")

    if st.button("🧮 HITUNG", key="btn_hengky_math", width="content"):
        if ksei_ticker:
            math = compute_hengky_math(
                ksei_ticker,
                shares_outstanding=shares_out * 1e6 if shares_out > 0 else 0,
                free_float_override=ff_override if ff_override > 0 else 0,
            )
            st.markdown(render_hengky_math_html(math), unsafe_allow_html=True)

            if math.get("available"):
                # Show breakdown
                known = math.get("known_holders",[])
                if known:
                    rows = [{"Pemegang": h["name"],
                             "% Hold":  f"{h.get('pct',0):.1f}%",
                             "Lot Terkunci": f"{h.get('lot',0):,.0f}"}
                            for h in known]
                    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    # ── Section 3: Manual Upload ──────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    sec_head("◆ UPLOAD DATA PEMEGANG SAHAM")

    st.markdown("""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
    color:var(--text-muted);line-height:1.8">
    Upload CSV dari laporan tahunan / KSEI / Stockbit dengan kolom:<br>
    <b style="color:var(--text-primary)">name, pct, shares, lot</b>
    (lot = jumlah lot, shares = jumlah saham)<br>
    Contoh baris: <b style="color:var(--accent)">PT Mitrabahtera Segara,79.9,1397250000,2794500</b>
    </p>""", unsafe_allow_html=True)

    up_c1, up_c2 = st.columns([2,1])
    with up_c1:
        uploaded = st.file_uploader("Upload CSV Pemegang Saham",
                                     type=["csv"], key="ksei_upload")
    with up_c2:
        up_ticker = st.text_input("Ticker", value=ksei_ticker or "", key="ksei_up_ticker")

    if uploaded and up_ticker:
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False, suffix='.csv') as tmp:
            tmp.write(uploaded.getvalue())
            tmp_path = tmp.name
        try:
            result = parse_shareholder_csv(tmp_path, up_ticker)
            st.success(f"✅ Tersimpan: {len(result.get('holders',[]))} pemegang saham untuk {up_ticker}")
        except Exception as e:
            st.error(f"Error: {e}")
        finally:
            os.unlink(tmp_path)

    # Manual entry (no CSV)
    st.markdown("""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
    color:var(--text-dim);margin-top:0.6rem">Atau input manual:</p>""", unsafe_allow_html=True)

    man_cols = st.columns([2,1,1,1])
    with man_cols[0]: man_name = st.text_input("Nama Pemegang", key="man_name")
    with man_cols[1]: man_pct  = st.number_input("Persen (%)", 0.0, 100.0, 0.0, key="man_pct")
    with man_cols[2]: man_lot  = st.number_input("Lot", 0, key="man_lot")
    with man_cols[3]: man_tick = st.text_input("Ticker", key="man_tick",
                                               value=ksei_ticker or "")

    if st.button("💾 SIMPAN PEMEGANG", key="btn_save_holder"):
        if man_name and man_tick:
            existing = compute_hengky_math(man_tick)
            holders  = existing.get("holders_data",{}).get("holders",[])
            holders.append({"name": man_name, "pct": man_pct,
                            "shares": man_lot*500, "lot": man_lot})
            save_manual_shareholders(man_tick, holders, "manual_entry")
            st.success(f"✅ Disimpan: {man_name} untuk {man_tick}")
            st.rerun()

    # ── Section 4: Notification settings ─────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    sec_head("◆ NOTIFIKASI SAHAM POTENSIAL")
    st.markdown("""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
    color:var(--text-muted);line-height:1.8">
    Sistem akan highlight saham yang memenuhi kriteria akumulasi selama ≥1 minggu.<br>
    Aktifkan Telegram di <b style="color:var(--text-primary)">config/settings.json</b> untuk push notification.
    </p>""", unsafe_allow_html=True)

    # Show current accumulation streaks
    streaks = []
    for w in whale_results:
        t = w.get("ticker","").replace(".JK","")
        trend = get_accumulation_trend(t, 7)
        if trend.get("available") and trend.get("acc_signal") in ("ACCUMULATION","STRONG_ACCUMULATION"):
            streaks.append({
                "Ticker":   t,
                "Signal":   trend["acc_signal"],
                "Days":     trend["days"],
                "Smart%":   f"{trend['smart_buy_pct']:.0f}%",
                "Net Lot":  f"{trend['smart_net_lot']:+,.0f}",
                "Conv":     w.get("conviction",0),
            })

    if streaks:
        st.markdown("""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
        color:var(--accent);margin-bottom:0.4rem">🔔 Akumulasi terdeteksi berturut-turut:</p>""",
        unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(streaks), width="stretch", hide_index=True)
    else:
        st.markdown("""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
        color:var(--text-dim)">Belum ada data akumulasi multi-hari. Data akan muncul setelah
        beberapa hari scan dengan token Stockbit aktif.</p>""", unsafe_allow_html=True)

def _ownership_row(w: dict) -> str:
    """Phase 1-3: Owner broker + free float + live broker data."""
    parts = []

    # Phase 2: Known owner broker (static profile)
    ob  = w.get("owner_broker","")
    obn = w.get("owner_name","")
    bn  = w.get("broker_name","")
    bsig= w.get("broker_signal","")
    btyp= w.get("broker_type","")

    if ob:
        sig_col = {"SMART":"var(--accent)","RETAIL":"var(--c-danger)",
                   "CAUTION":"var(--c-warning)","NEUTRAL":"var(--text-secondary)"}.get(bsig,"var(--text-secondary)")
        typ_col = {"OWNER_PROXY":"var(--accent)","FOREIGN_INST":"var(--c-info)",
                   "LOCAL_INST":"var(--c-info)","MARKET_MAKER":"var(--c-warning)",
                   "RETAIL":"var(--c-danger)","GORENGAN":"var(--c-warning)"}.get(btyp,"var(--text-secondary)")
        parts.append(
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            'color:var(--text-dim)">🔑 OWNER BROKER </span>'
            '<b style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);'
            f'color:{sig_col}">{ob}</b>'
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            f'color:var(--text-muted)"> {bn}</span>'
            f'<span style="background:{typ_col}18;border:1px solid {typ_col}44;'
            'border-radius:var(--r-sm);padding:1px 5px;font-family:Share Tech Mono,monospace;'
            f'font-size:var(--text-2xs);color:{typ_col};margin-left:0.3rem">{btyp.replace("_"," ")}</span>'
        )
        if obn:
            parts.append(
                '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
                f'color:var(--text-dim);margin-left:0.5rem">· {obn}</span>'
            )

    # Phase 1: Free float
    ff = w.get("free_float", 0)
    pi = w.get("pct_insider", 0)
    sc = w.get("supply_control","")
    if ff > 0 or pi > 0:
        ff_col = "var(--accent)" if ff<=15 else "var(--c-warning)" if ff<=30 else "var(--text-secondary)"
        sc_col = "var(--accent)" if sc in ("SANGAT KETAT","KETAT") else "var(--c-warning)" if sc=="MODERATE" else "var(--text-secondary)"
        _margin_left = "0.8rem" if ob else "0"
        _sc_html     = f" · <b style='color:{sc_col}'>{sc}</b>" if sc else ""
        parts.append(
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            f'color:var(--text-dim);margin-left:{_margin_left}">'
            f'📊 Insider <b style="color:var(--text-primary)">{pi:.0f}%</b> · '
            f'Float <b style="color:{ff_col}">{ff:.0f}%</b>'
            f'{_sc_html}'
            '</span>'
        )

    # Phase 3: Live broker data
    if w.get("broker_live"):
        sp     = w.get("smart_buy_pct", 0)
        top_b  = w.get("top_buyers",[])[:3]
        dom    = top_b[0] if top_b else {}
        dom_code = dom.get("code","")
        dom_lot  = dom.get("buy_lot",0)
        bsig2    = dom.get("signal","")
        d_col    = "var(--accent)" if bsig2=="SMART" else "var(--c-danger)" if bsig2=="RETAIL" else "var(--c-warning)"
        parts.append(
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            'color:var(--c-info);margin-left:0.8rem">🏦 LIVE: '
            f'<b style="color:{d_col}">{dom_code}</b> {dom_lot:,} lot · '
            f'Smart {sp:.0f}%</span>'
        )

    if not parts:
        return ""

    return (
        '<div style="background:rgba(0,0,0,0.25);border:1px solid rgba(0,255,102,0.07);' +
        'border-radius:var(--r-sm);padding:0.35rem 0.7rem;margin-top:0.3rem;' +
        'display:flex;flex-wrap:wrap;align-items:center;gap:0.2rem">' +
        "".join(parts) +
        '</div>'
    )

def _v4_row(w: dict) -> str:
    """V4: Hitung Barang + Order Block insight row."""
    parts = []

    # Hitung Barang
    ctrl  = w.get("control_score", 0)
    abs_p = w.get("absorbed_pct", 0)
    hb_desc = w.get("hitung_barang_desc","")
    if ctrl >= 4 or hb_desc:
        ctrl_col = "var(--accent)" if ctrl >= 7 else "var(--c-warning)" if ctrl >= 4 else "var(--text-muted)"
        _hb_text = hb_desc if hb_desc else f"~{abs_p:.0f}% vol diserap institusi"
        parts.append(
            '<div style="display:flex;align-items:center;gap:0.5rem;'
            'background:rgba(0,255,102,0.04);border:1px solid rgba(0,255,102,0.1);'
            'border-radius:var(--r-sm);padding:0.3rem 0.7rem;margin-top:0.3rem">'
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
            'color:var(--text-dim);letter-spacing:0.12em">🧮 HITUNG BARANG</span>'
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);'
            f'color:{ctrl_col};font-weight:700">CONTROL {ctrl}/10</span>'
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            f'color:var(--text-muted)">{_hb_text}</span>'
            '</div>'
        )

    # Order Block
    if w.get("ob_detected"):
        ob_type = w.get("ob_type","")
        ob_h    = w.get("ob_high",0)
        ob_l    = w.get("ob_low",0)
        ob_str  = w.get("ob_strength",0)
        in_zone = w.get("in_ob_zone",False)
        near    = w.get("near_ob_zone",False)
        ob_desc = w.get("ob_desc","")

        ob_col  = "var(--accent)" if in_zone else "var(--c-warning)" if near else "var(--text-muted)"
        zone_lbl= "🎯 DI OB ZONE" if in_zone else "⬇ DEKAT OB" if near else "OB TERBENTUK"
        ob_type_col = "var(--accent)" if ob_type=="BULLISH" else "var(--c-danger)"

        _ = ob_desc  # template var
        parts.append(
            '<div style="display:flex;align-items:center;gap:0.5rem;'
            'background:rgba(96,165,250,0.04);border:1px solid rgba(96,165,250,0.1);'
            'border-radius:var(--r-sm);padding:0.3rem 0.7rem;margin-top:0.25rem">'
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
            'color:var(--text-dim);letter-spacing:0.12em">📦 ORDER BLOCK</span>'
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);'
            f'color:{ob_type_col};font-weight:700">{ob_type}</span>'
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            f'color:var(--text-primary)">Rp{ob_l:,.0f}–{ob_h:,.0f}</span>'
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            f'color:{ob_col};font-weight:600">{zone_lbl}</span>'
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            f'color:var(--text-dim)">str {ob_str}/10</span>'
            '</div>'
        )

    # V6.4: Volume Profile display
    vp_poc   = w.get("vp_poc", 0)
    vp_zone  = w.get("vp_zone", "")
    vp_near  = w.get("vp_near_val", False)
    vp_in    = w.get("vp_in_value", False)
    vp_desc  = w.get("vp_desc", "")
    vp_pct   = w.get("vp_pct_from_poc", 0)
    if vp_poc > 0:
        vp_color = "var(--accent)" if vp_near or vp_in else "var(--c-warning)" if vp_zone == "IN_VALUE" else "var(--text-secondary)"
        vp_label = "🎯 DEKAT VAL" if vp_near else "✅ DI VALUE AREA" if vp_in else ("📈 DI ATAS VAH" if vp_zone == "ABOVE_VALUE" else "📊 VP")
        parts.append(
            '<div style="display:flex;align-items:center;gap:0.5rem;'
            'background:rgba(96,165,250,0.03);border:1px solid rgba(96,165,250,0.08);'
            'border-radius:var(--r-sm);padding:0.3rem 0.7rem;margin-top:0.25rem">'
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
            'color:var(--text-dim);letter-spacing:0.12em">📊 VOL PROFILE</span>'
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            f'color:{vp_color};font-weight:600">{vp_label}</span>'
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            f'color:var(--text-primary)">{vp_desc}</span>'
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            f'color:var(--text-muted)">{vp_pct:+.1f}% from POC</span>'
            '</div>'
        )

    return "".join(parts) if parts else ""


def _trading_summary_row(w: dict) -> str:
    """
    Synthesized trading verdict row — Hengky Method.
    Entry / Wait / Skip + level kunci + reasoning chain.
    """
    close       = w.get("close", 0)
    floor_p     = w.get("floor_price", 0)
    pct_f       = w.get("pct_above_floor", 0)
    conv        = w.get("conviction", 0)
    ctrl        = w.get("control_score", 0)
    ema_tr      = w.get("ema_trend", "")
    signal      = w.get("signal", "")
    qual        = w.get("whale_quality", "")
    peng        = w.get("pengeringan_detected", False)
    defending   = w.get("whale_defending", False)
    ob_det      = w.get("ob_detected", False)
    in_ob       = w.get("in_ob_zone", False)
    near_ob     = w.get("near_ob_zone", False)
    ob_l        = w.get("ob_low", 0)
    ob_h        = w.get("ob_high", 0)
    vp_val      = w.get("vp_val", 0)
    vp_poc      = w.get("vp_poc", 0)
    vp_near_val = w.get("vp_near_val", False)
    range_20d   = w.get("range_20d_pct", 5.0)
    ema13       = w.get("ema13", 0)
    mom5        = w.get("mom_5d", 0)
    ff          = w.get("free_float", 100)
    sc          = w.get("supply_control", "")
    is_dist     = signal in ("DISTRIBUTION", "BLOCK_SELL")
    ff_vol      = w.get("ff_adj_vol_ratio", w.get("vol_ratio", 0))

    if close <= 0 or floor_p <= 0:
        return ""

    # ── Risk levels ──────────────────────────────────────────────────────────
    # SL = floor price (below floor = thesis broken)
    # Buffer: jika harga sudah sangat dekat floor, SL slightly below
    sl_base     = floor_p * 0.97          # 3% buffer below floor
    risk_pct    = (close - sl_base) / close * 100 if close > 0 else 0

    # Entry zone: ideal entry based on context
    if pct_f <= 5:
        entry_lo = close * 0.998          # sudah di floor, entry sekarang
        entry_hi = close * 1.012
    elif pct_f <= 15:
        entry_lo = floor_p * 1.01
        entry_hi = floor_p * 1.06
    else:
        entry_lo = floor_p * 1.02
        entry_hi = floor_p * 1.08

    # TP berbasis range 20d dan conviction
    tp_mult = 1.5 + (conv / 10) * 1.5    # conv 4→1.5x range, conv 8→2.1x range
    range_rp = close * (range_20d / 100)
    tp1      = close + range_rp * 1.2
    tp2      = close + range_rp * tp_mult
    rr       = (tp1 - close) / (close - sl_base) if (close - sl_base) > 0 else 0

    # ── Verdict logic ────────────────────────────────────────────────────────
    # P02-W5: weighted positive_signals — bobot sesuai Hengky priority
    # Defending + ctrl tinggi = bukti terkuat. EMA/vol = konfirmasi saja.
    positive_signals = sum([
        defending * 2,                              # 2pt: whale defend = bukti terkuat
        (ctrl >= 6) * 2,                            # 2pt: control score tinggi
        peng * 1,                                   # 1pt: pengeringan barang
        in_ob * 1,                                  # 1pt: di OB zone
        (vp_near_val or w.get("vp_in_value",False)),# 1pt: di VP value area
        near_ob * 1,                                # 1pt: dekat OB
        (qual in ("SMART","LIKELY_SMART")) * 1,     # 1pt: whale quality
        (ema_tr == "BULLISH") * 1,                  # 1pt: EMA trend
        (ff_vol >= 1.5) * 1,                        # 1pt: volume konfirmasi
        (conv >= 6) * 1,                            # 1pt: conviction
    ])
    # Max score = 12 — normalisasi ke skala 8 untuk kompatibilitas threshold lama
    positive_signals = round(positive_signals * 8 / 12)

    if is_dist:
        verdict      = "DISTRIBUSI"
        verdict_col  = "#EF4444"
        verdict_bg   = "rgba(239,68,68,0.06)"
        verdict_bdr  = "rgba(239,68,68,0.25)"
        verdict_icon = "⚠"
        action_text  = "JANGAN MASUK — distribusi aktif terdeteksi. Tunggu konfirmasi reversal."
        reasons      = ["Signal distribusi/block sell aktif"]
        if ema_tr == "BEARISH":
            reasons.append("EMA bearish")
        if ff_vol < 0.5:
            reasons.append(f"Vol hanya {ff_vol:.1f}× (sepi)")
    elif conv >= 6 and positive_signals >= 3 and pct_f <= 20 and ema_tr in ("BULLISH","MIXED"):
        verdict      = "ENTRY VALID"
        verdict_col  = "#00FF66"
        verdict_bg   = "rgba(0,255,102,0.06)"
        verdict_bdr  = "rgba(0,255,102,0.3)"
        verdict_icon = "⚡"
        action_text  = f"Entry Rp{entry_lo:,.0f}–{entry_hi:,.0f} · SL Rp{sl_base:,.0f} ({risk_pct:.0f}% risk) · TP1 Rp{tp1:,.0f} · TP2 Rp{tp2:,.0f} · R:R {rr:.1f}:1"
        reasons      = []
        if pct_f <= 5:   reasons.append("harga di floor")
        elif pct_f <= 15:reasons.append(f"dekat floor {pct_f:.0f}%")
        if peng:         reasons.append("pengeringan aktif")
        if defending:    reasons.append("whale defend")
        if in_ob:        reasons.append("di OB zone")
        if ctrl >= 6:    reasons.append(f"control {ctrl}/10")
        if sc in ("SANGAT KETAT","KETAT"): reasons.append(f"supply {sc.lower()}")
    elif conv >= 4 and positive_signals >= 2 and pct_f <= 35:
        verdict      = "WATCHLIST"
        verdict_col  = "#F0B429"
        verdict_bg   = "rgba(240,180,41,0.05)"
        verdict_bdr  = "rgba(240,180,41,0.25)"
        verdict_icon = "⏳"
        wait_reasons = []
        if pct_f > 20:        wait_reasons.append(f"harga masih {pct_f:.0f}% above floor")
        if ema_tr == "MIXED": wait_reasons.append("EMA mixed — tunggu konfirmasi")
        if not peng:          wait_reasons.append("belum ada pengeringan")
        if ff_vol < 1.0:      wait_reasons.append(f"vol lemah {ff_vol:.1f}×")
        wait_str = " · ".join(wait_reasons) if wait_reasons else "setup belum matang"
        action_text = f"TUNGGU — {wait_str}. Alert di Rp{entry_lo:,.0f}–{entry_hi:,.0f}"
        reasons     = [f"conv {conv}/10"]
        if peng:    reasons.append("peng ✓")
        if ctrl>=4: reasons.append(f"ctrl {ctrl}/10")
    else:
        verdict      = "SKIP"
        verdict_col  = "#64748B"
        verdict_bg   = "rgba(100,116,139,0.05)"
        verdict_bdr  = "rgba(100,116,139,0.2)"
        verdict_icon = "✕"
        skip_reasons = []
        if conv < 4:       skip_reasons.append(f"conv rendah {conv}/10")
        if pct_f > 35:     skip_reasons.append(f"terlalu jauh dari floor {pct_f:.0f}%")
        if ema_tr=="BEARISH": skip_reasons.append("EMA bearish")
        if ff_vol < 0.5:   skip_reasons.append(f"vol {ff_vol:.1f}× (terlalu sepi)")
        action_text = " · ".join(skip_reasons) if skip_reasons else "tidak memenuhi kriteria entry"
        reasons     = []

    reasons_html = ""
    if reasons:
        reasons_html = "".join([
            f'<span style="background:rgba(255,255,255,0.04);border-radius:3px;'
            f'padding:1px 6px;font-size:var(--text-2xs);color:#94A3B8">{r}</span>'
            for r in reasons
        ])

    return f"""<div style="background:{verdict_bg};border:1px solid {verdict_bdr};
border-radius:var(--r-sm);padding:0.5rem 0.85rem;margin-top:0.45rem;
display:flex;align-items:flex-start;gap:0.7rem;flex-wrap:wrap">
  <span style="font-family:Orbitron,monospace;font-size:var(--text-xs);font-weight:800;
  color:{verdict_col};letter-spacing:0.08em;white-space:nowrap;min-width:90px">
    {verdict_icon} {verdict}</span>
  <div style="flex:1;min-width:0">
    <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);
    color:#E2E8F0;line-height:1.6">{action_text}</div>
    {f'<div style="display:flex;gap:0.3rem;flex-wrap:wrap;margin-top:0.3rem">{reasons_html}</div>' if reasons_html else ""}
  </div>
</div>"""

def whale_card(w: dict, border_color: str = NEON_GREEN) -> str:
    ticker  = w.get("ticker","").replace(".JK","")
    chg     = w.get("chg_pct",0)
    conv    = w.get("conviction",0)
    qual    = w.get("whale_quality","?")
    floor_p = w.get("floor_price",0)
    pct_f   = w.get("pct_above_floor",0)
    mom5    = w.get("mom_5d",0)
    ff_vol  = w.get("ff_adj_vol_ratio", w.get("vol_ratio",0))
    sector  = w.get("sector","")
    signal  = w.get("signal","")
    emoji   = w.get("emoji","")
    ema_tr  = w.get("ema_trend","")
    w52h    = w.get("pct_from_52w_high",0)
    val_bn  = w.get("value_bn",0)

    # ── Colors ────────────────────────────────────────────────────────────────
    qual_color = {"SMART":"var(--accent)","LIKELY_SMART":"var(--accent)",
                  "UNCERTAIN":"var(--c-warning)","DUMB":"var(--c-danger)"}.get(qual,"var(--text-secondary)")
    qual_lbl   = {"SMART":"◉ SMART","LIKELY_SMART":"◎ LIKELY SMART",
                  "UNCERTAIN":"? UNCERTAIN","DUMB":"⚠ DUMB"}.get(qual,qual)
    sig_color  = {"ACCUMULATION":"var(--accent)","BLOCK_BUY":"var(--c-info)",
                  "RECOVERY_EARLY":"var(--c-warning)","VOL_SPIKE_UP":"var(--c-warning)",
                  "DISTRIBUTION":"var(--c-danger)","BLOCK_SELL":"var(--c-warning)"}.get(signal,"var(--text-secondary)")
    chg_col = "var(--accent)" if chg >= 0 else "var(--c-danger)"
    m5_col  = "var(--accent)" if mom5 >= 0 else "var(--c-danger)"
    ema_col = "var(--accent)" if ema_tr=="BULLISH" else "var(--c-danger)" if ema_tr=="BEARISH" else "var(--c-warning)"

    # Floor badge
    if pct_f <= 5:
        floor_col, floor_lbl = "var(--accent)", "🎯 AT FLOOR"
    elif pct_f <= 15:
        floor_col, floor_lbl = "var(--accent)", "✅ NEAR FLOOR"
    elif pct_f <= 30:
        floor_col, floor_lbl = "var(--c-warning)", "◎ MID RANGE"
    else:
        floor_col, floor_lbl = "var(--text-muted)", "✕ FAR"

    # Conviction bar
    filled  = round(conv)
    bar     = "█" * filled + "░" * (10 - filled)
    bar_col = "var(--accent)" if conv>=7 else "var(--c-warning)" if conv>=4 else "var(--c-danger)"

    # Format value
    if val_bn >= 1000: val_str = f"Rp{val_bn/1000:.1f}T"
    elif val_bn >= 1:  val_str = f"Rp{val_bn:.1f}Bn"
    else:              val_str = f"Rp{val_bn*1000:.0f}Jt"

    # Tags
    tags = []
    # Catalyst tag — MSCI/LQ45 known candidate (shown first, prominent)
    cat_tag = w.get("catalyst_tag", "")
    if cat_tag == "MSCI":
        tags.append('<span style="background:rgba(251,191,36,0.18);border:1px solid rgba(251,191,36,0.55);border-radius:var(--r-sm);padding:2px 9px;font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--c-warning);font-weight:700">★ MSCI</span>')
    elif cat_tag == "LQ45":
        tags.append('<span style="background:rgba(96,165,250,0.15);border:1px solid rgba(96,165,250,0.45);border-radius:var(--r-sm);padding:2px 9px;font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--c-info);font-weight:700">◆ LQ45</span>')
    if w.get("pengeringan_detected"): tags.append(('<span style="background:rgba(96,165,250,0.12);border:1px solid rgba(96,165,250,0.35);border-radius:var(--r-sm);padding:2px 8px;font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--c-info)">💧 pengeringan</span>'))
    if w.get("whale_defending"):      tags.append(('<span style="background:rgba(0,255,102,0.08);border:1px solid rgba(0,255,102,0.3);border-radius:var(--r-sm);padding:2px 8px;font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--accent)">🛡 defend</span>'))
    zone = w.get("entry_zone","")
    if zone=="AT_FLOOR":    tags.append('<span style="background:rgba(0,255,102,0.08);border:1px solid rgba(0,255,102,0.3);border-radius:var(--r-sm);padding:2px 8px;font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--accent)">🎯 at-floor</span>')
    elif zone=="NEAR_FLOOR":tags.append('<span style="background:rgba(57,255,20,0.08);border:1px solid rgba(57,255,20,0.3);border-radius:var(--r-sm);padding:2px 8px;font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--accent)">✅ near-floor</span>')
    elif zone=="MID_RANGE": tags.append('<span style="background:rgba(240,180,41,0.08);border:1px solid rgba(240,180,41,0.3);border-radius:var(--r-sm);padding:2px 8px;font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--c-warning)">◎ mid</span>')
    if w.get("pattern")=="SUSTAINED": tags.append('<span style="background:rgba(96,165,250,0.08);border:1px solid rgba(96,165,250,0.25);border-radius:var(--r-sm);padding:2px 8px;font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--c-info)">📅 sustained</span>')
    mom = w.get("momentum","")
    if mom=="ACCELERATING": tags.append('<span style="background:rgba(0,255,102,0.08);border:1px solid rgba(0,255,102,0.25);border-radius:var(--r-sm);padding:2px 8px;font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--accent)">⚡ acc</span>')
    elif mom=="REVERSING":  tags.append('<span style="background:rgba(251,191,36,0.08);border:1px solid rgba(251,191,36,0.25);border-radius:var(--r-sm);padding:2px 8px;font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--c-warning)">↗ rev</span>')
    tags_html_str = " ".join(tags)

    sec_html = ('<span style="background:rgba(100,116,139,0.1);border:1px solid rgba(100,116,139,0.2);'
                'border-radius:var(--r-sm);padding:1px 6px;font-family:Share Tech Mono,monospace;'
                f'font-size:var(--text-xs);color:var(--text-muted);letter-spacing:0.04em">{sector}</span>') if sector else ""

    # P02-X3: pre-build ctrl_badge — JANGAN inline di dalam f-string besar (menyebabkan HTML leak)
    _ctrl_score = w.get("control_score", 0)
    ctrl_badge  = (
        f'<span style="background:rgba(0,255,102,0.1);border:1px solid rgba(0,255,102,0.3);'
        f'border-radius:var(--r-sm);padding:1px 6px;font-family:Share Tech Mono,monospace;'
        f'font-size:var(--text-2xs);color:var(--accent);font-weight:700">Ctrl {_ctrl_score}/10</span>'
    ) if _ctrl_score >= 4 else ""

    peng_desc  = w.get("pengeringan_desc","")
    def_desc   = w.get("defense_desc","")

    def metric_cell(label, value, subval, val_color, sub_color):
        return f"""<div style="background:var(--bg-deep);border:1px solid rgba(255,255,255,0.06);
border-radius:var(--r-sm);padding:0.5rem 0.65rem">
  <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);
  letter-spacing:0.14em;color:#94A3B8;margin-bottom:3px;text-transform:uppercase">{label}</div>
  <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-base);
  font-weight:700;color:{val_color};line-height:1.2">{value}</div>
  <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
  color:{sub_color};margin-top:2px">{subval}</div>
</div>"""

    # ── Build HTML via string concatenation — NO large f-string ──────────────
    # Sesuai aturan kerja STV: f-string besar selalu berpotensi leak/corrupt.
    # Semua komponen di-build terpisah lalu di-join.

    # ROW 2 metric cells
    floor_subval = floor_lbl + " " + ("%+.1f%%" % pct_f)
    mom5_subval  = "5D " + ("%+.1f%%" % mom5)
    w52h_subval  = "52W " + ("%+.1f%%" % w52h)

    def mc(label, value, subval, vc, sc):
        return (
            '<div style="background:var(--bg-deep);border:1px solid rgba(255,255,255,0.06);' +
            'border-radius:var(--r-sm);padding:0.5rem 0.65rem">' +
            '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);' +
            'letter-spacing:0.14em;color:#94A3B8;margin-bottom:3px;text-transform:uppercase">' +
            label + '</div>' +
            '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-base);' +
            'font-weight:700;color:' + vc + ';line-height:1.2">' + value + '</div>' +
            '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);' +
            'color:' + sc + ';margin-top:2px">' + subval + '</div></div>'
        )

    row2 = (
        mc("FLOOR PRICE", fmt_rp(floor_p), floor_subval, "var(--text-primary)", floor_col) +
        mc("CONVICTION",  str(conv) + "/10", bar, bar_col, bar_col) +
        mc("FF-VOL",      ("%.1f×" % ff_vol), mom5_subval, "var(--c-info)", m5_col) +
        mc("EMA TREND",   ema_tr, w52h_subval, ema_col, "var(--text-muted)") +
        mc("VALUE",       val_str, "TRADED", "var(--text-secondary)", "var(--text-dim)")
    )

    # ROW 3 tag descriptions (pre-built, no inline conditional)
    peng_span = (
        '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);' +
        'color:var(--c-info);margin-left:0.4rem">' + peng_desc + '</span>'
    ) if peng_desc else ""
    def_span = (
        '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);' +
        'color:var(--accent);margin-left:0.4rem">' + def_desc + '</span>'
    ) if def_desc else ""

    # Close price + chg
    close_str = fmt_rp(w.get("close", 0))
    chg_str   = ("%+.2f%%" % chg)

    # Assemble ROW 1
    row1 = (
        '<div style="display:flex;align-items:center;gap:0.7rem;flex-wrap:wrap;' +
        'margin-bottom:0.55rem;border-bottom:1px solid rgba(255,255,255,0.05);' +
        'padding-bottom:0.55rem">' +
        '<span style="font-family:Orbitron,monospace;font-size:var(--text-xl);' +
        'font-weight:900;color:var(--text-primary);letter-spacing:0.05em">' + ticker + '</span>' +
        '<span style="background:' + sig_color + '15;border:1px solid ' + sig_color + '50;' +
        'border-radius:var(--r-sm);padding:2px 9px;font-family:Share Tech Mono,monospace;' +
        'font-size:var(--text-xs);letter-spacing:0.08em;color:' + sig_color + ';' +
        'font-weight:600">' + emoji + "&nbsp;" + signal + '</span>' +
        '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-base);' +
        'font-weight:700;color:var(--text-primary)">' + close_str + '</span>' +
        '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-base);' +
        'color:' + chg_col + ';font-weight:700">' + chg_str + '</span>' +
        '<span style="margin-left:auto;display:flex;align-items:center;gap:0.5rem">' +
        '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);' +
        'color:' + qual_color + ';font-weight:700">' + qual_lbl + '</span>' +
        ctrl_badge +
        sec_html +
        '</span></div>'
    )

    # Final assembly — pure string concat, zero f-string
    return (
        '<div style="background:#0F1318;border:1px solid ' + border_color + '35;' +
        'border-left:4px solid ' + border_color + ';border-radius:var(--r-md);' +
        'padding:1rem 1.2rem;margin-bottom:0.75rem;' +
        'box-shadow:0 2px 12px rgba(0,0,0,0.35);' +
        'display:flex;flex-direction:column;height:100%;' +
        'transition:border-color 0.2s,background 0.2s">' +
        row1 +
        '<div style="display:grid;grid-template-columns:repeat(5,1fr);' +
        'gap:0.45rem;margin-bottom:0.5rem">' + row2 + '</div>' +
        '<div style="display:flex;align-items:center;gap:0.35rem;flex-wrap:wrap">' +
        tags_html_str + peng_span + def_span + '</div>' +
        _v4_row(w) +
        _ownership_row(w) +
        _trading_summary_row(w) +
        '</div>'
    )

# ══════════════════════════════════════════════════════════════════════════════
# DATA DISPLAY
# ══════════════════════════════════════════════════════════════════════════════
if whale_results:
    accum_list   = [w for w in whale_results if w["signal"]=="ACCUMULATION"]
    blkbuy_list  = [w for w in whale_results if w["signal"]=="BLOCK_BUY"]
    recov_list   = [w for w in whale_results if w["signal"]=="RECOVERY_EARLY"]
    distrib_list = [w for w in whale_results if not w.get("is_long_signal",True)]
    smart_list   = sorted(
        [w for w in whale_results if w.get("whale_quality") in ("SMART","LIKELY_SMART") and w.get("is_long_signal")],
        # P02-X2: prioritaskan SMART whale yang di OB/VP zone — setup terkuat Hengky method
        key=lambda w: (
            -(w.get("in_ob_zone",False) or w.get("vp_near_val",False) or w.get("vp_in_value",False)),
            -w.get("conviction",0),
             w.get("pct_above_floor",999),
        )
    )
    peng_list    = [w for w in whale_results if w.get("pengeringan_detected") and w.get("is_long_signal")]
    def_list     = [w for w in whale_results if w.get("whale_defending") and w.get("is_long_signal")]
    floor_list   = [w for w in whale_results if w.get("entry_zone") in ("AT_FLOOR","NEAR_FLOOR") and w.get("is_long_signal")]
    # Pre-compute conviction-filtered counts (used by both metrics and tab counts)
    # These need min_conv_ui which is defined in scan controls above
    _peng_c_raw  = len([w for w in peng_list  if w.get("conviction",0) >= min_conv_ui])
    _floor_c_raw = len([w for w in floor_list if w.get("conviction",0) >= min_conv_ui])
    _rec_c_raw   = len([w for w in recov_list if w.get("conviction",0) >= min_conv_ui])
    # In bear market: allow MIXED EMA too (recovery plays)
    _ema_ok = ["BULLISH"] if tradeable else ["BULLISH", "MIXED"]
    _best_c_raw  = len([w for w in smart_list
                        if w.get("ema_trend") in _ema_ok
                        and w.get("conviction",0) >= min_conv_ui])
    buy_val      = sum(w.get("value_bn",0) for w in whale_results if w.get("is_long_signal"))
    sell_val     = sum(w.get("value_bn",0) for w in whale_results if not w.get("is_long_signal"))
    bias         = ctx.get("market_bias","—")
    bias_color   = {"STRONG BUY":NEON_GREEN,"MILD BUY":"var(--accent)","NEUTRAL":"var(--text-secondary)",
                    "MILD SELL":"var(--c-warning)","STRONG SELL":"var(--c-danger)"}.get(bias,"var(--text-muted)")

    # ── Metrics ───────────────────────────────────────────────────────────────
    cols8 = st.columns(8)
    _conv_note = f"≥{min_conv_ui}" if min_conv_ui > 1 else ""
    mdata = [
        ("TOTAL",      len(whale_results),  TEXT_MAIN),
        ("◉ AKUMUL.",  len(accum_list),    NEON_GREEN),
        ("◎ BLK BUY",  len(blkbuy_list),   "var(--c-info)"),
        (f"🌅 RECOV {_conv_note}",  _rec_c_raw,   "var(--c-warning)"),
        ("⚠ DISTRIB",  len(distrib_list),  "var(--c-danger)"),
        ("🧠 SMART",   len(smart_list),    NEON_GREEN),
        (f"💧 PENG {_conv_note}",   _peng_c_raw,  "var(--c-info)"),
        (f"🎯 FLOOR {_conv_note}",  _floor_c_raw, NEON_GREEN),
    ]
    for col, (lbl, val, clr) in zip(cols8, mdata):
        with col:
            st.markdown(f"""
            <div class="m-card" style="padding:0.55rem 0.7rem">
              <div class="m-lbl" style="font-size:var(--text-2xs)">{lbl}</div>
              <div class="m-val" style="color:{clr};font-size:var(--text-xl)">{val}</div>
            </div>""", unsafe_allow_html=True)

    # Bias strip + sector breakdown
    sec_bkd   = ctx.get("sector_breakdown", {})
    # P02-W4: rebuild sector_breakdown dari hasil scan saat ini (tidak pakai stale ctx)
    # Hitung ulang dari whale_results yang baru di-render
    if whale_results:
        from collections import Counter as _Counter
        _sec_live = _Counter(w.get("sector","OTHER") for w in whale_results
                             if w.get("is_long_signal") and w.get("sector","OTHER") != "OTHER")
        sec_bkd   = dict(_sec_live) if _sec_live else sec_bkd  # fallback ke ctx jika kosong
    sec_str  = "  ·  ".join(
        f'<b style="color:var(--text-primary)">{s}</b> <span style="color:var(--accent)">{c}</span>'
        for s, c in sorted(sec_bkd.items(), key=lambda x:-x[1])[:6]
    ) if sec_bkd else "—"

    st.markdown(f"""
    <div style="background:var(--bg-card);border:1px solid rgba(0,255,102,0.06);border-radius:var(--r-sm);
    padding:0.55rem 1.2rem;margin:0.6rem 0;font-family:Share Tech Mono,monospace;
    font-size:var(--text-xs);display:flex;gap:2rem;align-items:center;flex-wrap:wrap">
      <span style="color:var(--text-muted)">MARKET BIAS</span>
      <span style="font-family:Orbitron,monospace;font-size:var(--text-base);
      font-weight:700;color:{bias_color}">{bias}</span>
      <span style="color:var(--text-muted)">BUY <b style="color:var(--accent)">{fmt_bn(buy_val)}</b></span>
      <span style="color:var(--text-muted)">SELL <b style="color:var(--c-danger)">{fmt_bn(sell_val)}</b></span>
      <span style="color:var(--text-muted)">DEFEND <b style="color:var(--text-primary)">{len(def_list)}</b></span>
      <span style="color:var(--text-muted);margin-left:auto">SECTORS: {sec_str}</span>
    </div>
    """, unsafe_allow_html=True)

    # ── Tabs ──────────────────────────────────────────────────────────────────
    _best_c  = _best_c_raw
    _peng_c  = _peng_c_raw
    _floor_c = _floor_c_raw
    _rec_c   = _rec_c_raw
    _dist_c  = len(distrib_list)
    _all_c   = len(whale_results)

    tab1,tab2,tab3,tab4,tab5,tab6,tab7 = st.tabs([
        f"◉ BEST LONG ({_best_c})",
        f"💧 PENGERINGAN ({_peng_c})",
        f"🎯 AT FLOOR ({_floor_c})",
        f"🌅 RECOVERY ({_rec_c})",
        f"⚠ DISTRIBUSI ({_dist_c})",
        f"◆ SEMUA ({_all_c})",
        "🏦 BROKER · KSEI",
    ])

    with tab1:
        best = [w for w in smart_list
                if w.get("ema_trend") in _ema_ok
                and w.get("conviction",0) >= min_conv_ui]
        _tradeable_str = '· TRADEABLE ✓' if tradeable else '· ⛔ WATCHLIST ONLY'
        # P02-X1: sort selectbox hanya render jika best tidak kosong
        _best_sort = "Conviction"  # default jika best kosong
        if best:
            _t1h, _t1s, _t1c = st.columns([3, 1, 1])
            with _t1h:
                st.markdown(f"""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
                color:var(--text-muted);letter-spacing:0.08em;margin-bottom:0.3rem">
                {len(best)} SETUP · SMART WHALE + EMA BULLISH + CONVICTION ≥ {min_conv_ui}
                {_tradeable_str}</p>""", unsafe_allow_html=True)
            with _t1s:
                _best_sort = st.selectbox("Sort", ["Conviction", "% Above Floor", "Control Score", "Vol Ratio"],
                                           key="best_sort", label_visibility="collapsed")
            with _t1c:
                _ticker_list = ", ".join(w["ticker"].replace(".JK","") for w in best)
                if st.button("📋 COPY TICKERS", key="copy_best", width="stretch"):
                    st.session_state["_clipboard"] = _ticker_list
                    st.toast(f"✅ Copied: {_ticker_list[:60]}", icon="📋")
        _best_sort_fn = {
            "Conviction":    lambda x: (-x.get("conviction",0),   x.get("pct_above_floor",999)),
            "% Above Floor": lambda x: ( x.get("pct_above_floor",999), -x.get("conviction",0)),
            "Control Score": lambda x: (-x.get("control_score",0), -x.get("conviction",0)),
            "Vol Ratio":     lambda x: (-x.get("ff_adj_vol_ratio", x.get("vol_ratio",0)),),
        }.get(_best_sort, lambda x: (-x.get("conviction",0), x.get("pct_above_floor",999)))
        best.sort(key=_best_sort_fn)

        if best:
            # 2-column layout
            # BUG FIX: st.columns + st.markdown HTML + st.button dalam block yang sama
            # menyebabkan HTML bocor — pisahkan dengan st.container()
            left_col, right_col = st.columns(2)
            for i, w in enumerate(best):
                with (left_col if i % 2 == 0 else right_col):
                    with st.container():
                        st.markdown(whale_card(w, NEON_GREEN), unsafe_allow_html=True)
                    t = w["ticker"].replace(".JK","")
                    wl_key = f"wl_{t}_{i}"
                    # Load watchlist
                    wl_file = LOGS_DIR / "watchlist.json"
                    wl = json.loads(wl_file.read_text()) if wl_file.exists() else []
                    in_wl = t in wl
                    wl_lbl = "★ WATCHLISTED" if in_wl else "☆ ADD TO WATCHLIST"
                    if st.button(wl_lbl, key=wl_key, width="stretch"):
                        if in_wl: wl.remove(t)
                        else: wl.append(t)
                        wl_file.write_text(json.dumps(wl, indent=2))
                        st.rerun()

            sec_head("◆ FLOOR PRICE DETAILS")
            rows = [{"Ticker":  w["ticker"].replace(".JK",""),
                     "Price":   w.get("close",0),
                     "Floor":   w.get("floor_price",0),
                     "VWAP60":  w.get("vwap_60d",0),
                     "%↑Floor": round(w.get("pct_above_floor",0),1),
                     "Zone":    w.get("entry_zone_label",""),
                     "Conv":    w.get("conviction",0),
                     "FF-Vol×": round(w.get("ff_adj_vol_ratio",w.get("vol_ratio",0)),1),
                     "Sector":  w.get("sector",""),
                     "Whale":   w.get("whale_quality","")}
                    for w in best]
            try:
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True,
                    column_config={
                        "Price":   st.column_config.NumberColumn("Price",  format="Rp%,.0f"),
                        "Floor":   st.column_config.NumberColumn("Floor",  format="Rp%,.0f"),
                        "VWAP60":  st.column_config.NumberColumn("VWAP60", format="Rp%,.0f"),
                        "%↑Floor": st.column_config.NumberColumn("%↑Floor",format="%+.1f%%"),
                        "Conv":    st.column_config.NumberColumn("Conv",   format="%d/10"),
                        "FF-Vol×": st.column_config.NumberColumn("FF-Vol×",format="%.1f×"),
                    })
            except Exception:
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

            # ── RINGKASAN ANALISIS ─────────────────────────────────────────────
            st.markdown("<br>", unsafe_allow_html=True)
            sec_head("◆ RINGKASAN ANALISIS")
            st.markdown("""<p style="font-family:Share Tech Mono,monospace;
            font-size:var(--text-xs);color:var(--text-muted);letter-spacing:0.08em;margin-bottom:1rem">
            Framework Hengky: Signal → EMA → Floor → Conviction → Supply → Action
            </p>""", unsafe_allow_html=True)
            for _w in best:
                _render_analysis_card(_w, tradeable)

        else:
            render_empty_state("◉",f"NO SETUP CONVICTION ≥ {min_conv_ui}",
                               "Lower min conviction or run a new scan.",
                               "python orchestrator.py --mode whale")

    with tab2:
        _ph, _ps, _pc = st.columns([3, 1, 1])
        with _ph:
            st.markdown("""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
            color:var(--text-muted);letter-spacing:0.08em;margin-bottom:0.3rem">
            VOL ELEVATED + RANGE SEMPIT = SMART MONEY ACCUMULATING FROM RETAIL</p>""",
            unsafe_allow_html=True)
        with _ps:
            _peng_sort = st.selectbox("Sort", ["Peng. Strength", "Conviction", "% Above Floor"],
                                       key="peng_sort", label_visibility="collapsed")
        _peng_sort_fn = {
            "Peng. Strength": lambda x: (-x.get("pengeringan_strength",0), -x.get("conviction",0)),
            "Conviction":     lambda x: (-x.get("conviction",0), -x.get("pengeringan_strength",0)),
            "% Above Floor":  lambda x: (x.get("pct_above_floor",999), -x.get("conviction",0)),
        }.get(_peng_sort, lambda x: (-x.get("pengeringan_strength",0), -x.get("conviction",0)))
        peng = sorted([w for w in peng_list if w.get("conviction",0) >= min_conv_ui],
                       key=_peng_sort_fn)
        with _pc:
            if peng and st.button("📋 COPY", key="copy_peng", width="stretch"):
                st.toast(", ".join(w["ticker"].replace(".JK","") for w in peng), icon="📋")
        if peng:
            l,r = st.columns(2)
            for i,w in enumerate(peng):
                with (l if i%2==0 else r):
                    st.markdown(whale_card(w,"var(--c-info)"), unsafe_allow_html=True)
        else:
            render_empty_state("💧","NO PENGERINGAN","Tidak ada pengeringan barang terdeteksi saat ini.")

    with tab3:
        _fh, _fs = st.columns([4, 1])
        with _fh:
            st.markdown("""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
            color:var(--text-muted);letter-spacing:0.08em;margin-bottom:0.6rem">
            MENDEKATI FLOOR PRICE = R/R TERBAIK · DI SINILAH EMITEN DEFEND</p>""",
            unsafe_allow_html=True)
        with _fs:
            _floor_sort = st.selectbox("Sort", ["% Above Floor", "Conviction", "Vol Ratio"],
                                        key="floor_sort", label_visibility="collapsed")
        _floor_sort_fn = {
            "% Above Floor": lambda x: (x.get("pct_above_floor",999), -x.get("conviction",0)),
            "Conviction":    lambda x: (-x.get("conviction",0), x.get("pct_above_floor",999)),
            "Vol Ratio":     lambda x: (-x.get("ff_adj_vol_ratio", x.get("vol_ratio",0))),
        }.get(_floor_sort, lambda x: (x.get("pct_above_floor",999), -x.get("conviction",0)))
        at_fl = sorted([w for w in floor_list if w.get("conviction",0) >= min_conv_ui],
                        key=_floor_sort_fn)
        if at_fl:
            l,r = st.columns(2)
            for i,w in enumerate(at_fl):
                with (l if i%2==0 else r):
                    st.markdown(whale_card(w, NEON_GREEN), unsafe_allow_html=True)
        else:
            render_empty_state("🎯","NO AT FLOOR","Tidak ada setup mendekati floor saat ini.")

    with tab4:
        lbl = "RECOVERY WATCHLIST" if not tradeable else "EARLY RECOVERY PLAYS"
        _rh, _rs = st.columns([4, 1])
        with _rh:
            st.markdown(f"""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
            color:var(--text-muted);letter-spacing:0.08em;margin-bottom:0.6rem">
            {lbl} · BEATEN DOWN >20% DARI 52W HIGH + WHALE BUYING</p>""", unsafe_allow_html=True)
        with _rs:
            _rec_sort = st.selectbox("Sort", ["Conviction", "% dari 52W High", "Vol Ratio"],
                                      key="rec_sort", label_visibility="collapsed")
        _rec_sort_fn = {
            "Conviction":       lambda x: (-x.get("conviction",0), x.get("pct_from_52w_high",0)),
            "% dari 52W High":  lambda x: (x.get("pct_from_52w_high",0), -x.get("conviction",0)),
            "Vol Ratio":        lambda x: (-x.get("ff_adj_vol_ratio", x.get("vol_ratio",0))),
        }.get(_rec_sort, lambda x: (-x.get("conviction",0), x.get("pct_from_52w_high",0)))
        rec = sorted([w for w in recov_list if w.get("conviction",0) >= min_conv_ui],
                      key=_rec_sort_fn)
        if rec:
            l,r = st.columns(2)
            for i,w in enumerate(rec):
                with (l if i%2==0 else r):
                    st.markdown(whale_card(w,"var(--c-warning)"), unsafe_allow_html=True)
        else:
            render_empty_state("🌅","NO RECOVERY","Belum ada recovery signal.")

    with tab5:
        # P02-W3: tambah sort toggle + copy tickers — konsisten dengan tab lain
        _d5h, _d5s, _d5c = st.columns([3, 1, 1])
        with _d5h:
            st.markdown("""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
            color:var(--c-danger);letter-spacing:0.08em;margin-bottom:0.6rem">
            ⚠ IDX LONG ONLY — DISTRIBUSI = AWARENESS ONLY. BUKAN SHORT SIGNAL.</p>""",
            unsafe_allow_html=True)
        with _d5s:
            _dist_sort = st.selectbox("Sort", ["Vol Ratio", "Conviction", "% Above Floor"],
                                       key="dist_sort", label_visibility="collapsed")
        _dist_sort_fn = {
            "Vol Ratio":     lambda x: -x.get("vol_ratio",0),
            "Conviction":    lambda x: -x.get("conviction",0),
            "% Above Floor": lambda x:  x.get("pct_above_floor",999),
        }.get(_dist_sort, lambda x: -x.get("vol_ratio",0))
        dist = sorted(distrib_list, key=_dist_sort_fn)
        with _d5c:
            if dist and st.button("📋 COPY", key="copy_dist", width="stretch"):
                _dist_tickers = ", ".join(w["ticker"].replace(".JK","") for w in dist)
                st.toast(f"✅ {len(dist)} dist tickers", icon="📋")
                st.session_state["_dist_clip"] = _dist_tickers
        if dist:
            l,r = st.columns(2)
            for i,w in enumerate(dist):
                with (l if i%2==0 else r):
                    st.markdown(whale_card(w,"var(--c-danger)"), unsafe_allow_html=True)
        else:
            render_empty_state("◉","NO DISTRIBUTION","Smart money belum exit. Good.",)

    with tab6:
        cf1,cf2,cf3,cf4 = st.columns(4)
        with cf1:
            sig_f = st.multiselect("SIGNAL",
                ["ACCUMULATION","BLOCK_BUY","RECOVERY_EARLY","VOL_SPIKE_UP",
                 "VOL_NEUTRAL","DISTRIBUTION","BLOCK_SELL"],
                default=["ACCUMULATION","BLOCK_BUY","RECOVERY_EARLY","VOL_SPIKE_UP"])
        with cf2:
            zone_f = st.multiselect("ZONE",
                ["AT_FLOOR","NEAR_FLOOR","MID_RANGE","FAR_FROM_FLOOR"],
                default=["AT_FLOOR","NEAR_FLOOR","MID_RANGE"])
        with cf3:
            qual_f = st.multiselect("WHALE TYPE",
                ["SMART","LIKELY_SMART","UNCERTAIN","DUMB"],
                default=["SMART","LIKELY_SMART","UNCERTAIN"])
        with cf4:
            sort_f = st.selectbox("SORT BY",
                ["Conviction","Vol Ratio","% Above Floor","Value",
                 "Control Score","% Smart","Sector"])

        filtered = [w for w in whale_results
                    if w.get("signal") in sig_f
                    and w.get("entry_zone","") in zone_f
                    and w.get("whale_quality","") in qual_f]
        ks = {"Conviction":     lambda x: -x.get("conviction",0),
              "Vol Ratio":      lambda x: -x.get("vol_ratio",0),
              "% Above Floor":  lambda x:  x.get("pct_above_floor",999),
              "Value":          lambda x: -x.get("value_bn",0),
              "Control Score":  lambda x: -x.get("control_score",0),
              "% Smart":        lambda x: 0 if x.get("whale_quality","") in ("SMART","LIKELY_SMART") else 1,
              "Sector":         lambda x:  x.get("sector","~")}
        filtered.sort(key=ks[sort_f])

        _sa_col, _sc_col = st.columns([4,1])
        with _sa_col:
            st.markdown(f"""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
            color:var(--text-muted);letter-spacing:0.12em;margin-bottom:0.3rem">
            SHOWING {len(filtered)} OF {len(whale_results)}</p>""", unsafe_allow_html=True)
        with _sc_col:
            _semi_tickers = ", ".join(w["ticker"].replace(".JK","") for w in filtered)
            if st.button("📋 COPY", key="copy_semua", width="stretch"):
                st.toast(f"✅ {len(filtered)} tickers", icon="📋")
                st.session_state["_semua_clip"] = _semi_tickers

        if filtered:
            rows = [{"Ticker":   w["ticker"].replace(".JK",""),
                     "Signal":   f"{w.get('emoji','')} {w.get('signal','')}",
                     "Whale":    w.get("whale_quality",""),
                     "Conv":     w.get("conviction",0),
                     "Ctrl":     w.get("control_score",0),
                     "Price":    w.get("close",0),
                     "Chg%":     round(w.get("chg_pct",0),1),
                     "FF-Vol×":  round(w.get("ff_adj_vol_ratio",w.get("vol_ratio",0)),1),
                     "Floor":    w.get("floor_price",0),
                     "%↑Floor":  round(w.get("pct_above_floor",0),1),
                     "Zone":     w.get("entry_zone",""),
                     "Peng.":    "✓" if w.get("pengeringan_detected") else "—",
                     "Def.":     "✓" if w.get("whale_defending") else "—",
                     "OB/VP":    "✓" if (w.get("in_ob_zone") or w.get("vp_near_val")) else "—",
                     "EMA":      w.get("ema_trend",""),
                     "5D%":      round(w.get("mom_5d",0),1),
                     "52Wh%":    round(w.get("pct_from_52w_high",0),1),
                     "Sector":   w.get("sector",""),
                     "Val(Bn)":  round(w.get("value_bn",0),2)}
                    for w in filtered]
            try:
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True,
                    column_config={
                        "Conv":     st.column_config.NumberColumn("Conv",    format="%d/10"),
                        "Ctrl":     st.column_config.NumberColumn("Ctrl",    format="%d/10",
                                        help="Control Score (hitung barang) — makin tinggi makin terpusat"),
                        "Price":    st.column_config.NumberColumn("Price",   format="Rp%,.0f"),
                        "Chg%":     st.column_config.NumberColumn("Chg%",   format="%+.1f%%"),
                        "FF-Vol×":  st.column_config.NumberColumn("FF-Vol×",format="%.1f×"),
                        "Floor":    st.column_config.NumberColumn("Floor",   format="Rp%,.0f"),
                        "%↑Floor":  st.column_config.NumberColumn("%↑Floor",format="%+.1f%%"),
                        "5D%":      st.column_config.NumberColumn("5D%",    format="%+.1f%%"),
                        "52Wh%":    st.column_config.NumberColumn("52Wh%",  format="%+.1f%%"),
                        "Val(Bn)":  st.column_config.NumberColumn("Val(Bn)",format="%.2f"),
                    })
            except Exception:
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    # ── Intel Panel ───────────────────────────────────────────────────────────
    sec_head("◆ INTEL PANEL")

    # ── Session state toggles (init sudah dilakukan di atas halaman) ──────

    cd, cj, cs = st.columns(3)

    # ── Director Mandates ──────────────────────────────────────────────────
    with cd:
        if st.button(
            "[−] ◈ DIRECTOR MANDATES" if st.session_state.panel_director else "[+] ◈ DIRECTOR MANDATES",
            key="btn_director", width="stretch"
        ):
            st.session_state.panel_director = not st.session_state.panel_director
        if st.session_state.panel_director:
            st.markdown("""<div style="background:var(--bg-base);border:1px solid rgba(0,255,102,0.12);
            border-top:none;border-radius:0 0 3px 3px;padding:0.8rem 1rem">""",
            unsafe_allow_html=True)
            if MANDATES.exists():
                content_md = MANDATES.read_text(encoding="utf-8")
                st.markdown(content_md)
            else:
                st.markdown('<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--text-muted)">Run orchestrator first.</p>', unsafe_allow_html=True)
            if STUDY_FILE.exists():
                try:
                    study  = json.loads(STUDY_FILE.read_text(encoding="utf-8"))
                    ranked = study.get("sectors",{}).get("ranked",[])
                    if ranked:
                        sec_head("◆ SEKTOR ROTATION")
                        rows_s = [{"Sektor":n,"Score":f"{d.get('score',0):+.1f}",
                                   "4W":fmt_pct(d.get('mom_4w',0)),"13W":fmt_pct(d.get('mom_13w',0))}
                                  for n,d in ranked[:7]]
                        st.dataframe(pd.DataFrame(rows_s), width="stretch", hide_index=True)
                except Exception: pass
            st.markdown("</div>", unsafe_allow_html=True)

    # ── Trading Journal ────────────────────────────────────────────────────
    with cj:
        if st.button(
            "[−] ◈ TRADING JOURNAL" if st.session_state.panel_journal else "[+] ◈ TRADING JOURNAL",
            key="btn_journal", width="stretch"
        ):
            st.session_state.panel_journal = not st.session_state.panel_journal
        if st.session_state.panel_journal:
            st.markdown("""<div style="background:var(--bg-base);border:1px solid rgba(0,255,102,0.12);
            border-top:none;border-radius:0 0 3px 3px;padding:0.8rem 1rem">""",
            unsafe_allow_html=True)
            if JOURNAL_FILE.exists():
                txt = JOURNAL_FILE.read_text(encoding="utf-8")
                st.markdown(txt[-4000:] if len(txt) > 4000 else txt)
            else:
                st.markdown('<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--text-muted)">No journal yet.</p>', unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

    # ── Lessons + Playbook ─────────────────────────────────────────────────
    with cs:
        if st.button(
            "[−] ◈ LESSONS + PLAYBOOK" if st.session_state.panel_lessons else "[+] ◈ LESSONS + PLAYBOOK",
            key="btn_lessons", width="stretch"
        ):
            st.session_state.panel_lessons = not st.session_state.panel_lessons
        if st.session_state.panel_lessons:
            st.markdown("""<div style="background:var(--bg-base);border:1px solid rgba(0,255,102,0.12);
            border-top:none;border-radius:0 0 3px 3px;padding:0.8rem 1rem">""",
            unsafe_allow_html=True)
            if LESSONS.exists():
                st.markdown(LESSONS.read_text(encoding="utf-8"))
            if PLAYBOOK.exists():
                st.markdown(PLAYBOOK.read_text(encoding="utf-8"))
            st.markdown("</div>", unsafe_allow_html=True)






    # ── OUTCOME TRACKER — LOG WHALE TRADE ──────────────────────────────────── V6.3.2
    st.markdown("<br>", unsafe_allow_html=True)
    sec_head("◆ OUTCOME TRACKER — LOG WHALE TRADE")
    st.markdown("""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
    letter-spacing:0.08em;color:var(--text-muted);margin-bottom:1rem">
    Catat trade Hengky method yang diambil. Minimal 30 closed trades untuk validasi win rate.<br>
    <span style="color:var(--text-dim)">Setiap trade = data point. Tanpa ini, win rate tetap UNKNOWN.</span>
    </p>""", unsafe_allow_html=True)

    # Outcome logging → lihat page 6 Trade Journal

    # ── TAB 7: BROKER HISTORY + KSEI ─────────────────────────────────────────
    with tab7:
        _render_broker_ksei_tab(whale_results, min_conv_ui)

else:
    render_empty_state(
        icon     = "🐋",
        title    = "NO WHALE DATA",
        subtitle = "Run an adaptive scan to detect smart money movements.\nHengky: 'Hitung barang dulu sebelum masuk.'",
        command  = "python orchestrator.py --mode whale"
    )
