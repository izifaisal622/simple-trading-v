"""
Simple Trading V9 — Alert Watch (Module 04)
============================================
Auto-check setiap 15 menit HANYA saat market IDX aktif.

Jadwal IDX (WIB):
  Pre-opening  08:45 – 09:00  (monitor, 5 menit)
  Sesi 1       09:00 – 12:00  (aktif, 15 menit)
  Istirahat    12:00 – 13:30  (pause)
  Sesi 2       13:30 – 15:49  (aktif, 15 menit)
  Tutup        15:50+          (tidak scan)
  Weekend                      (tidak scan)
"""

import json
from datetime import datetime, timezone, timedelta, time as dtime
from pathlib import Path

import streamlit as st

ROOT     = Path(__file__).parent.parent
LOGS_DIR = ROOT / "logs"
import sys; sys.path.insert(0, str(ROOT))

from assets_ui import render_html_js
from assets_ui import (
    get_page_css, render_sidebar, render_page_header, render_regime_bar,
    REGIME_COLORS, SIG_COLORS, TEXT_MUTED, TEXT_MAIN, TEXT_DIM, NEON_GREEN, BG_CARD,
    score_badge, vp_zone_pill, signal_badge,
)
from agents.alert_watcher import check_alerts

# Load open positions untuk prioritized alerting
_open_positions = []
_open_tickers   = set()
try:
    from trade_logger import get_open_trades as _get_open_trades
    _open_positions = _get_open_trades()
    _open_tickers   = {t.get("ticker","").upper().replace(".JK","") for t in _open_positions}
except Exception:
    pass

_ = (TEXT_MUTED, TEXT_DIM, score_badge, vp_zone_pill, signal_badge, SIG_COLORS)  # template vars
st.set_page_config(
    page_title="Alert Watch — STV9",
    page_icon="🔔",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(get_page_css("dashboard"), unsafe_allow_html=True)

GREEN = NEON_GREEN; YELLOW = "var(--c-warning)"; RED = "var(--c-danger)"
BLUE  = "var(--c-info)";  WHITE  = TEXT_MAIN; LABEL = "var(--text-secondary)"
WIB   = timezone(timedelta(hours=7))

# ─────────────────────────────────────────────────────────────────────────────
# Market hours helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_market_status(dt=None):
    """
    Returns (status_code, label, description, is_active, interval_ms)
      is_active   = True jika scanning harus berjalan
      interval_ms = refresh interval yang sesuai
    """
    now = dt or datetime.now(WIB)
    wd  = now.weekday()    # 0=Mon … 4=Fri, 5=Sat, 6=Sun
    t   = now.time()

    PRE   = dtime(8, 45)
    S1_O  = dtime(9,  0)
    S1_C  = dtime(12, 0)
    BR_E  = dtime(13, 30)
    S2_C  = dtime(15, 50)

    if wd >= 5:
        next_open = "Senin 09:00 WIB"
        return ("CLOSED_WEEKEND", "🌙 Weekend", next_open, False, None)

    if t < PRE:
        diff = (datetime.combine(now.date(), PRE, tzinfo=WIB) - now)
        mins = int(diff.total_seconds() // 60)
        return ("CLOSED_PREOPEN", "🌙 Belum Buka",
                f"Pre-opening dalam {mins} menit (08:45 WIB)", False, None)

    if PRE <= t < S1_O:
        return ("PRE_OPEN", "🟡 Pre-Opening",
                "08:45 – 09:00 · Negosiasi harga pembukaan",
                True, 5 * 60 * 1000)   # 5 menit saat pre-open

    if S1_O <= t < S1_C:
        return ("OPEN_S1", "🟢 Sesi 1 Aktif",
                "09:00 – 12:00 · Trading berlangsung",
                True, 15 * 60 * 1000)  # 15 menit

    if S1_C <= t < BR_E:
        diff = (datetime.combine(now.date(), BR_E, tzinfo=WIB) - now)
        mins = int(diff.total_seconds() // 60)
        return ("BREAK", "⏸ Istirahat",
                f"12:00 – 13:30 · Sesi 2 dalam {mins} menit",
                False, None)           # Tidak scan saat istirahat

    if BR_E <= t < S2_C:
        return ("OPEN_S2", "🟢 Sesi 2 Aktif",
                "13:30 – 15:49 · Trading berlangsung",
                True, 15 * 60 * 1000)

    # EOD
    return ("CLOSED_EOD", "🔴 Market Tutup",
            "Selesai hari ini · Buka besok 09:00 WIB",
            False, None)


def minutes_until(target_time: dtime) -> int:
    now = datetime.now(WIB)
    target_dt = datetime.combine(now.date(), target_time, tzinfo=WIB)
    if target_dt < now:
        target_dt = target_dt.replace(day=target_dt.day + 1)
    return max(0, int((target_dt - now).total_seconds() // 60))


# ─────────────────────────────────────────────────────────────────────────────
# Market status check
# ─────────────────────────────────────────────────────────────────────────────
status_code, status_label, status_desc, is_active, interval_ms = get_market_status()
now_wib = datetime.now(WIB)

# ─────────────────────────────────────────────────────────────────────────────
# Auto-refresh — HANYA saat market aktif
# ─────────────────────────────────────────────────────────────────────────────
# Pure JS auto-refresh — no external package needed
if is_active and interval_ms:
    render_html_js(
        f"<script>setTimeout(function(){{window.parent.location.reload();}},{interval_ms});</script>",
        height=0
    )

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar + Header
# ─────────────────────────────────────────────────────────────────────────────
def _regime():
    try:
        d  = json.loads((LOGS_DIR/"daily_results.json").read_text(encoding="utf-8"))
        rg = d.get("regime", {})
        return rg.get("cycle","—"), rg.get("ihsg",0), rg.get("mom_4w",0), \
               rg.get("breadth",0), d.get("scan_date","—")
    except Exception:
        return "—", 0, 0, 0, "—"

cycle, ihsg, mom_4w, breadth, scan_date = _regime()
render_sidebar("Alert Watch", regime=cycle, scan_date=scan_date)
import json as _jv, pathlib as _pv
try:
    _ver_accent = "V" + _jv.loads((_pv.Path(__file__).parent.parent/"version.json").read_text(encoding="utf-8"))["version"].split(".")[0]
except Exception:
    _ver_accent = "V9"
render_page_header(
    eyebrow  = "◆ MODULE 05 · REAL-TIME ALERT WATCH · " + _ver_accent,
    title    = "SIMPLE TRADING ",
    accent   = _ver_accent,
    subtitle = "◈ AUTO-CHECK MARKET HOURS · ALERT NOTIFIKASI · SESSION TRACKING",
)
render_regime_bar(cycle, ihsg, mom_4w, breadth, scan_date)

# ─────────────────────────────────────────────────────────────────────────────
# Market status banner
# ─────────────────────────────────────────────────────────────────────────────
status_colors = {
    "OPEN_S1":       (GREEN,  "rgba(0,255,102,0.07)"),
    "OPEN_S2":       (GREEN,  "rgba(0,255,102,0.07)"),
    "PRE_OPEN":      (YELLOW, "rgba(240,180,41,0.07)"),
    "BREAK":         (YELLOW, "rgba(240,180,41,0.05)"),
    "CLOSED_EOD":    (RED,    "rgba(239,68,68,0.05)"),
    "CLOSED_PREOPEN":(LABEL,  "rgba(255,255,255,0.03)"),
    "CLOSED_WEEKEND":(LABEL,  "rgba(255,255,255,0.03)"),
}
sc, sbg = status_colors.get(status_code, (LABEL, "rgba(255,255,255,0.03)"))

time_str = now_wib.strftime("%H:%M:%S")
day_str  = ["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"][now_wib.weekday()]

# Interval label
if is_active and interval_ms:
    intv_lbl = f"Auto-refresh setiap {interval_ms//60000} menit"
else:
    intv_lbl = "Auto-refresh dinonaktifkan"

st.markdown(
    '<div style="background:' + sbg + ';border:1px solid ' + sc + '33;'
    'border-left:4px solid ' + sc + ';border-radius:6px;'
    'padding:.7rem 1.1rem;margin:.5rem 0;'
    'display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.6rem">'

    '<div>'
    '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);'
    'font-weight:700;color:' + sc + '">' + status_label + '</span>'
    '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
    'color:' + LABEL + ';margin-left:.7rem">' + status_desc + '</span>'
    '</div>'

    '<div style="text-align:right">'
    '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:' + WHITE + '">'
    + day_str + ' ' + time_str + ' WIB</div>'
    '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:' + LABEL + ';margin-top:.1rem">'
    + intv_lbl + '</div>'
    '</div>'
    '</div>',
    unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# IDX session timeline bar
# ─────────────────────────────────────────────────────────────────────────────
now_mins = now_wib.hour * 60 + now_wib.minute
# Session colors: active = solid green, inactive = dimmed
_S_GREEN_ACT  = "rgba(0,255,102,0.55)"
_S_GREEN_DIM  = "rgba(0,255,102,0.15)"
_S_YELLOW_ACT = "rgba(240,180,41,0.55)"
_S_YELLOW_DIM = "rgba(240,180,41,0.15)"
_S_GRAY       = "rgba(255,255,255,0.06)"

sessions = [
    (8*60+45,  9*60,    "Pre",      _S_YELLOW_ACT, _S_YELLOW_DIM),
    (9*60,     12*60,   "Sesi 1",   _S_GREEN_ACT,  _S_GREEN_DIM),
    (12*60,    13*60+30,"Istirahat", _S_GRAY,       _S_GRAY),
    (13*60+30, 15*60+50,"Sesi 2",   _S_GREEN_ACT,  _S_GREEN_DIM),
]
day_start, day_end = 8*60+30, 16*60

# Build timeline HTML
bars = ""
for s_min, e_min, lbl, col_act, col_dim in sessions:
    w_pct  = (e_min - s_min) / (day_end - day_start) * 100
    x_pct  = (s_min - day_start) / (day_end - day_start) * 100
    active = s_min <= now_mins < e_min
    bg_col = col_act if active else col_dim
    txt_col = "#E2E8F0" if active else "#64748B"
    border  = "1px solid rgba(0,255,102,0.5)" if (active and "Sesi" in lbl) else "none"
    bars += (
        f'<div style="position:absolute;left:{x_pct:.1f}%;width:{w_pct:.1f}%;'
        f'height:100%;background:{bg_col};border:{border};border-radius:var(--r-sm);'
        f'display:flex;align-items:center;justify-content:center">'
        f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
        f'color:{txt_col};font-weight:600;white-space:nowrap">{lbl}</span>'
        f'</div>'
    )

# Current time cursor
cursor_pct = max(0, min(100, (now_mins - day_start) / (day_end - day_start) * 100))
cursor_html = (
    f'<div style="position:absolute;left:{cursor_pct:.1f}%;top:-4px;bottom:-4px;'
    f'width:2px;background:{WHITE};border-radius:1px;z-index:10">'
    f'<div style="position:absolute;top:-5px;left:50%;transform:translateX(-50%);'
    f'font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:{WHITE};'
    f'white-space:nowrap">{time_str[:5]}</div>'
    f'</div>'
) if 0 <= cursor_pct <= 100 else ""

st.markdown(
    '<div style="margin:.3rem 0 .8rem">'
    '<div style="display:flex;justify-content:space-between;'
    'font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:' + LABEL + ';margin-bottom:.25rem">'
    '<span>08:45</span><span>09:00</span><span>12:00</span><span>13:30</span><span>15:50</span>'
    '</div>'
    '<div style="position:relative;height:16px;background:rgba(255,255,255,0.05);'
    'border-radius:var(--r-sm);overflow:visible">'
    + bars + cursor_html +
    '</div>'
    '</div>',
    unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# MARKET CLOSED state
# ─────────────────────────────────────────────────────────────────────────────
if not is_active and status_code != "PRE_OPEN":
    # Show last known alerts (if any) from history
    # FIX V6.3.4: Lazy evaluation agar minutes_until hanya dipanggil
    # untuk status_code yang relevan. Ini mencegah komputasi waktu yang
    # tidak perlu saat market tutup / weekend.
    _next_map = {
        "CLOSED_PREOPEN":  ("Pre-opening", "08:45", dtime(8,45)),
        "BREAK":           ("Sesi 2",      "13:30", dtime(13,30)),
        "CLOSED_EOD":      ("Besok Sesi 1","09:00", None),
        "CLOSED_WEEKEND":  ("Senin Sesi 1","09:00", None),
    }
    _nm = _next_map.get(status_code, ("—", "—", None))
    _mins_raw = minutes_until(_nm[2]) if _nm[2] is not None and len(_nm) > 2 and _nm[2] is not None else None
    next_session_info = (_nm[0], _nm[1], _mins_raw)

    next_name, next_time, mins_left = next_session_info
    mins_txt = f" ({mins_left} menit lagi)" if mins_left is not None else ""

    st.markdown(
        '<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);'
        'border-radius:6px;padding:2rem;text-align:center;margin:1rem 0">'
        '<div style="font-family:Orbitron,monospace;font-size:var(--text-2xl);color:' + LABEL + ';margin-bottom:.5rem">⏸</div>'
        '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);color:' + WHITE + '">'
        'Scan dinonaktifkan — market tidak aktif</div>'
        '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:' + LABEL + ';margin-top:.35rem">'
        'Berikutnya: ' + next_name + ' jam ' + next_time + ' WIB' + mins_txt + '</div>'
        '</div>',
        unsafe_allow_html=True)

    # Show last alert history
    try:
        hist = json.loads((LOGS_DIR/"alert_history.json").read_text(encoding="utf-8"))
        if hist:
            last = hist[-1]
            st.markdown(
                '<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);'
                'border-radius:6px;padding:.8rem 1.1rem;margin:.5rem 0">'
                '<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:' + LABEL + ';margin-bottom:.3rem">'
                '◈ ALERT TERAKHIR · ' + last.get("timestamp","")[:16] + '</p>'
                + ''.join(
                    '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
                    'color:' + GREEN + ';padding:.15rem 0">⚡ ' + a.get("ticker","") + ' — '
                    'EMA ' + str(a.get("ema_score","")) + '/7 · '
                    'Conviction ' + str(a.get("conviction","")) + '/10</div>'
                    for a in last.get("alerts",[])[:5]
                )
                + '</div>',
                unsafe_allow_html=True)
    except Exception:
        pass

    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# MARKET ACTIVE — Settings + Check
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(
    '<div style="background:' + BG_CARD + ';border:1px solid rgba(255,255,255,.07);'
    'border-radius:6px;padding:.8rem 1.1rem;margin:.4rem 0">',
    unsafe_allow_html=True)
st.markdown(
    '<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
    'letter-spacing:.2em;color:' + LABEL + ';margin-bottom:.4rem">◈ THRESHOLD</p>',
    unsafe_allow_html=True)

sc1, sc2, sc3 = st.columns(3, gap="medium")
with sc1:
    ema_min   = st.slider("EMA Score min",      1, 7,  5, key="ema_min_s")
with sc2:
    whale_min = st.slider("Whale Conviction min",1, 10, 7, key="whale_min_s")
with sc3:
    floor_pct = st.slider("Floor Distance %",   1, 25, 10, key="floor_pct_s")
st.markdown("</div>", unsafe_allow_html=True)

# Countdown JS — WAJIB pakai render_html_js (JS-capable), bukan st.markdown
# Streamlit strips <script> dari unsafe_allow_html → script tidak pernah dieksekusi
if is_active and interval_ms:
    secs = interval_ms // 1000
    render_html_js(
        f"""<style>
          @keyframes _pulse{{0%,100%{{opacity:1}}50%{{opacity:.25}}}}
          #_cdrow{{display:flex;align-items:center;gap:8px;
            font-family:'Share Tech Mono',monospace;font-size:11px;color:{LABEL};margin:2px 0 6px}}
          #_cddot{{width:7px;height:7px;border-radius:50%;background:{GREEN};
            animation:_pulse 2s ease-in-out infinite;flex-shrink:0}}
        </style>
        <div id="_cdrow">
          <div id="_cddot"></div>
          <span>LIVE &nbsp;&middot;&nbsp; next refresh in <span id="_cd">--:--</span></span>
        </div>
        <script>
          (function(){{
            var left={secs}, el=document.getElementById('_cd');
            function tick(){{
              var m=Math.floor(left/60), s=left%60;
              el.textContent = m + ':' + (s<10?'0':'') + s;
              if(left>0){{ left--; setTimeout(tick,1000); }}
              else{{ el.textContent='Refreshing...'; }}
            }}
            tick();
          }})();
        </script>""",
        height=28,
    )

# ─────────────────────────────────────────────────────────────────────────────
# Run alert check
# ─────────────────────────────────────────────────────────────────────────────
with st.spinner("Memeriksa kondisi…"):
    result = check_alerts(
        ema_score_min  = ema_min,
        whale_conv_min = whale_min,
        floor_dist_pct = float(floor_pct),
    )

alerts    = result.get("alerts",    [])
watchlist = result.get("watchlist", [])
stats     = result.get("stats",     {})
error     = result.get("error")
ts        = result.get("timestamp","—")

if error:
    st.warning(f"⚠ Data belum tersedia: {error}. Jalankan scan dulu via EMA-XBO page.")
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# Notification JS (only during market hours)
# ─────────────────────────────────────────────────────────────────────────────
if alerts:
    ticker_str = ", ".join(a["ticker"] for a in alerts[:5])
    # WAJIB render_html_js (JS-capable) — st.markdown strips <script> tags
    render_html_js(
        f"""<script>
          (function(){{
            var msg="{len(alerts)} ALERT: {ticker_str}";
            if("Notification" in window){{
              Notification.requestPermission().then(function(p){{
                if(p==="granted"){{
                  new Notification("⚡ Simple Trading Alert!",{{body:msg,requireInteraction:true}});
                }}
              }});
            }}
            try{{
              var ac=new(window.AudioContext||window.webkitAudioContext)();
              [{{"f":880,"t":0}},{{"f":1100,"t":160}},{{"f":880,"t":320}}].forEach(function(x){{
                setTimeout(function(){{
                  var o=ac.createOscillator(),g=ac.createGain();
                  o.connect(g);g.connect(ac.destination);
                  o.frequency.value=x.f;g.gain.value=0.1;
                  o.start();o.stop(ac.currentTime+0.12);
                }},x.t);
              }});
            }}catch(e){{}}
            var orig=window.parent.document.title, blink=true,
              iv=setInterval(function(){{
                window.parent.document.title=blink?"⚡ ALERT: {ticker_str[:30]}":orig;
                blink=!blink;
              }},800);
            setTimeout(function(){{clearInterval(iv);window.parent.document.title=orig;}},20000);
          }})();
        </script>""",
        height=0,
    )
    st.toast(f"⚡ {len(alerts)} ALERT: {ticker_str}", icon="🔔")

# ─────────────────────────────────────────────────────────────────────────────
# Stats header
# ─────────────────────────────────────────────────────────────────────────────
h1, h2, h3, h4 = st.columns(4)
def _hstat(col, val, label, color):
    col.markdown(
        '<div style="background:' + BG_CARD + ';border:1px solid rgba(255,255,255,.07);'
        'border-radius:6px;padding:.6rem .9rem;text-align:center">'
        '<div style="font-family:Orbitron,monospace;font-size:var(--text-2xl);font-weight:900;'
        'color:' + color + ';line-height:1">' + str(val) + '</div>'
        '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
        'color:' + LABEL + ';margin-top:.15rem">' + label + '</div>'
        '</div>', unsafe_allow_html=True)

_hstat(h1, len(alerts),               "ALERTS",      RED    if alerts    else LABEL)
_hstat(h2, len(watchlist),            "WATCHLIST",   YELLOW if watchlist else LABEL)
_hstat(h3, stats.get("ema_total",0),  "EMA SETUPS",  BLUE)
_hstat(h4, stats.get("whale_total",0),"WHALE ALERTS",BLUE)

st.markdown(
    '<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:' + LABEL + ';margin:.3rem 0">'
    'Diperiksa: ' + ts + ' WIB · Scan data: ' + result.get("scan_date","—") + '</p>',
    unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Card renderer
# ─────────────────────────────────────────────────────────────────────────────
def _card(a: dict, is_alert: bool) -> str:
    """Upgraded alert card using design system CSS vars."""
    reg = a.get("regime","")
    rc  = REGIME_COLORS.get(reg, "var(--text-muted)")
    cl  = a.get("close", 0)
    fp  = a.get("floor_price", 0)
    fd  = a.get("floor_dist_pct", 999)
    ticker     = a.get("ticker","")
    ema_score  = a.get("ema_score", 0)
    ema_signal = a.get("ema_signal", "")
    conviction = a.get("conviction", 0)
    wq         = a.get("whale_quality","—")
    near_floor = a.get("near_floor", False)
    pengeringan= a.get("pengeringan", False)
    vp_zone    = a.get("vp_zone","")
    reasons_ema   = a.get("ema_reasons", [])
    reasons_whale = a.get("whale_reasons", [])

    if is_alert:
        lev_col="var(--c-danger)"; lev_bg="rgba(239,68,68,0.08)"; lev_bdr="rgba(239,68,68,0.3)"; lev_lbl="⚡ ALERT"
    else:
        lev_col="var(--c-warning)"; lev_bg="rgba(240,180,41,0.06)"; lev_bdr="rgba(240,180,41,0.25)"; lev_lbl="👁 WATCH"

    floor_col = "var(--accent)" if near_floor else "var(--c-warning)" if fd < 20 else "var(--text-dim)"
    filled    = min(round(conviction), 10)
    conv_bar  = "█" * filled + "░" * (10 - filled)
    conv_col  = "var(--accent)" if conviction >= 7 else "var(--c-warning)" if conviction >= 4 else "var(--c-danger)"

    tags = []
    if pengeringan: tags.append('<span class="tag tag-b">💧 PENG</span>')
    if near_floor:  tags.append('<span class="tag tag-g">🎯 AT FLOOR</span>')
    if wq in ("SMART","LIKELY_SMART"): tags.append(f'<span class="tag tag-g">◉ {wq}</span>')
    if vp_zone and vp_zone not in ("UNKNOWN",""): tags.append(f'<span class="tag tag-b">{vp_zone}</span>')
    tags_html   = " ".join(tags)
    reason_str  = " · ".join((reasons_ema + reasons_whale)[:3])
    score_html  = score_badge(ema_score) if ema_score else ""
    reason_html = f'<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:var(--text-dim);margin-top:0.3rem">{reason_str}</div>' if reason_str else ""

    return f"""<div style="background:{lev_bg};border:1px solid {lev_bdr};border-left:3px solid {lev_col};border-radius:var(--r-md);padding:0.75rem 1rem;margin-bottom:0.4rem">
  <div style="display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap;margin-bottom:0.4rem">
    <span style="font-family:Orbitron,monospace;font-size:var(--text-lg);font-weight:900;color:var(--text-primary)">{ticker}</span>
    <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);font-weight:700;color:{lev_col};background:{lev_bg};border:1px solid {lev_bdr};border-radius:var(--r-md);padding:1px 7px">{lev_lbl}</span>
    {tags_html}
    <span style="margin-left:auto;font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:{rc}">{reg}</span>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;margin-bottom:0.4rem">
    <div><div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);letter-spacing:0.16em;color:var(--text-dim);margin-bottom:3px">EMA</div>
      <div style="display:flex;align-items:center;gap:0.4rem">
        <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--text-primary)">{ema_signal.replace("_"," ")}</span>{score_html}</div></div>
    <div><div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);letter-spacing:0.16em;color:var(--text-dim);margin-bottom:3px">CONVICTION</div>
      <span style="font-family:monospace;font-size:var(--text-sm);color:{conv_col}">{conv_bar}</span>
      <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:{conv_col}"> {conviction}/10</span></div>
  </div>
  <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--text-muted)">
    PRICE <b style="color:var(--text-primary)">Rp{cl:,.0f}</b>
    &nbsp;·&nbsp; FLOOR <b style="color:{floor_col}">Rp{fp:,.0f}</b>
    <span style="font-size:var(--text-2xs)"> ({"AT " if near_floor else ""}±{fd:.0f}%)</span>
  </div>
  {reason_html}
</div>"""
# ── Split alerts berdasarkan posisi aktif ────────────────────────────────────
# Tier 1: alert untuk saham yang sedang di-hold (paling kritis)
# Tier 2: alert biasa (universe)
# Tier 3: watchlist
_all_alert_tickers = {a.get("ticker","").replace(".JK","").upper() for a in alerts}
_pos_alerts  = [a for a in alerts    if a.get("ticker","").replace(".JK","").upper() in _open_tickers]
_other_alerts= [a for a in alerts    if a.get("ticker","").replace(".JK","").upper() not in _open_tickers]
_pos_watch   = [a for a in watchlist if a.get("ticker","").replace(".JK","").upper() in _open_tickers]
_other_watch = [a for a in watchlist if a.get("ticker","").replace(".JK","").upper() not in _open_tickers]

# ── Posisi Aktif Banner (selalu tampil jika ada open positions) ───────────────
if _open_positions:
    _pos_ticker_strs = []
    for _pt in _open_positions:
        _ptn  = _pt.get("ticker","").upper()
        _flag = "⚡" if _ptn in _all_alert_tickers else ("👁" if _ptn in {a.get("ticker","").replace(".JK","").upper() for a in watchlist} else "·")
        _col  = RED if _flag == "⚡" else YELLOW if _flag == "👁" else LABEL
        _pos_ticker_strs.append(f'<span style="color:{_col};font-weight:700">{_flag} {_ptn}</span>')

    _pos_html = " &nbsp;·&nbsp; ".join(_pos_ticker_strs)
    st.markdown(
        f'<div style="background:rgba(96,165,250,0.06);border:1px solid rgba(96,165,250,0.25);'
        f'border-left:4px solid #60A5FA;border-radius:var(--r-md);'
        f'padding:0.55rem 1rem;margin:0.4rem 0;'
        f'font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
        f'display:flex;align-items:center;gap:1rem;flex-wrap:wrap">'
        f'<span style="color:#60A5FA;font-weight:700;letter-spacing:0.1em">🎯 POSISI AKTIF</span>'
        f'<span style="color:var(--text-dim)">({len(_open_positions)} saham)</span>'
        f'{_pos_html}'
        f'<span style="margin-left:auto;color:var(--text-dim);font-size:var(--text-2xs)">'
        f'⚡=alert · 👁=watch · ·=aman</span>'
        f'</div>',
        unsafe_allow_html=True)

# ── Card renderer khusus posisi aktif (border lebih tebal + badge POSISI) ─────
def _card_position(a: dict, is_alert: bool, trade_data: dict) -> str:
    """Card dengan badge POSISI AKTIF dan konteks trade (entry, P&L)."""
    base_card = _card(a, is_alert)
    entry_p   = trade_data.get("entry_price", 0) or 0
    sl_p      = trade_data.get("sl_price", 0) or 0
    cur_p     = a.get("close", 0) or 0
    pnl_pct   = ((cur_p - entry_p) / entry_p * 100) if entry_p > 0 and cur_p > 0 else 0
    pct_to_sl = ((cur_p - sl_p) / cur_p * 100) if cur_p > 0 and sl_p > 0 else 0
    _pnl_col  = GREEN if pnl_pct >= 0 else RED
    _sl_col   = RED if pct_to_sl <= 5 else YELLOW if pct_to_sl <= 10 else LABEL

    _pos_badge = (
        f'<div style="background:rgba(96,165,250,0.08);border:1px solid rgba(96,165,250,0.3);'
        f'border-radius:var(--r-sm);padding:0.35rem 0.8rem;margin-bottom:0.3rem;'
        f'font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
        f'display:flex;gap:1rem;align-items:center">'
        f'<span style="color:#60A5FA;font-weight:700">📍 POSISI AKTIF</span>'
        f'<span style="color:var(--text-dim)">Entry <b style="color:#E2E8F0">Rp{entry_p:,.0f}</b></span>'
        f'<span style="color:{_pnl_col};font-weight:700">P&L {pnl_pct:+.1f}%</span>'
        + (f'<span style="color:{_sl_col}">→ SL {pct_to_sl:.1f}%</span>' if sl_p > 0 else "")
        + f'</div>'
    )
    # Insert badge setelah opening div tag dari base_card
    insert_after = '<div style="background:'
    idx = base_card.find(insert_after)
    if idx >= 0:
        # Find closing > of first div
        close_idx = base_card.find('>', idx) + 1
        return base_card[:close_idx] + _pos_badge + base_card[close_idx:]
    return _pos_badge + base_card

# Build posisi lookup dict untuk card renderer
_pos_lookup = {t.get("ticker","").upper().replace(".JK",""): t for t in _open_positions}

# ── Tabs ─────────────────────────────────────────────────────────────────────
_n_pos_alert = len(_pos_alerts)
_n_pos_watch = len(_pos_watch)
alert_lbl = f"⚡  Alerts  ({len(alerts)})" + (f" 🎯{_n_pos_alert}" if _n_pos_alert else "")
watch_lbl = f"👁  Watchlist  ({len(watchlist)})" + (f" 🎯{_n_pos_watch}" if _n_pos_watch else "")

tab_alerts, tab_watch = st.tabs([alert_lbl, watch_lbl])

with tab_alerts:
    # Posisi aktif yang alert — tampil paling atas dengan styling berbeda
    if _pos_alerts:
        st.markdown(
            f'<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            f'letter-spacing:.18em;color:#60A5FA;margin:.5rem 0 .25rem">'
            f'🎯 POSISI AKTIF — PERLU PERHATIAN ({len(_pos_alerts)})</p>',
            unsafe_allow_html=True)
        for a in sorted(_pos_alerts, key=lambda x: (-x.get("conviction",0),)):
            _ticker_key = a.get("ticker","").replace(".JK","").upper()
            st.markdown(_card_position(a, True, _pos_lookup.get(_ticker_key, {})),
                        unsafe_allow_html=True)
        if _other_alerts:
            st.markdown(
                f'<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
                f'letter-spacing:.18em;color:{RED};margin:.8rem 0 .25rem">'
                f'⚡ ALERTS — UNIVERSE ({len(_other_alerts)})</p>',
                unsafe_allow_html=True)

    elif alerts:
        st.markdown(
            f'<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            f'letter-spacing:.18em;color:{RED};margin:.5rem 0 .25rem">'
            f'⚡ ALERTS — KEDUA KONDISI TERPENUHI ({len(alerts)})</p>',
            unsafe_allow_html=True)

    for a in sorted(_other_alerts, key=lambda x: (x.get("urgency",0), x.get("conviction",0)), reverse=True):
        st.markdown(_card(a, True), unsafe_allow_html=True)

    if not alerts:
        st.markdown(
            '<div style="background:rgba(60,207,122,.03);border:1px solid rgba(60,207,122,.1);'
            'border-radius:6px;padding:.75rem 1.1rem;margin:.5rem 0;text-align:center">'
            '<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);color:' + GREEN + '">'
            '✓ Tidak ada alert · Threshold belum terpenuhi</p>'
            '</div>',
            unsafe_allow_html=True)

with tab_watch:
    # Posisi aktif yang di watchlist — tampil dulu
    if _pos_watch:
        st.markdown(
            f'<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            f'letter-spacing:.18em;color:#60A5FA;margin:.5rem 0 .25rem">'
            f'🎯 POSISI AKTIF — MONITOR ({len(_pos_watch)})</p>',
            unsafe_allow_html=True)
        for a in sorted(_pos_watch, key=lambda x: -x.get("conviction",0)):
            _ticker_key = a.get("ticker","").replace(".JK","").upper()
            st.markdown(_card_position(a, False, _pos_lookup.get(_ticker_key, {})),
                        unsafe_allow_html=True)
        if _other_watch:
            st.markdown(
                f'<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
                f'letter-spacing:.18em;color:{YELLOW};margin:.8rem 0 .25rem">'
                f'👁 WATCHLIST — UNIVERSE ({len(_other_watch)})</p>',
                unsafe_allow_html=True)

    elif watchlist:
        st.markdown(
            f'<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            f'letter-spacing:.18em;color:{YELLOW};margin:.5rem 0 .25rem">'
            f'👁 WATCHLIST — SATU KONDISI TERPENUHI ({len(watchlist)})</p>',
            unsafe_allow_html=True)

    for a in sorted(_other_watch, key=lambda x: (x.get("urgency",0), x.get("ema_score",0),
                                                    -x.get("floor_dist_pct",999)), reverse=True)[:20]:
        st.markdown(_card(a, False), unsafe_allow_html=True)

    if not watchlist:
        st.markdown(
            '<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.06);'
            'border-radius:6px;padding:.75rem 1.1rem;margin:.5rem 0;text-align:center">'
            '<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);color:' + LABEL + '">'
            'Tidak ada watchlist · Jalankan scan EMA-XBO dan Follow Whale dulu</p>'
            '</div>',
            unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Save alert log + browser notif permission
# ─────────────────────────────────────────────────────────────────────────────
if alerts:
    try:
        log_file = LOGS_DIR / "alert_history.json"
        history  = json.loads(log_file.read_text()) if log_file.exists() else []
        history.append({
            "timestamp": datetime.now(WIB).isoformat(),
            "session":   status_code,
            "alerts":    [{"ticker": a["ticker"], "ema_score": a["ema_score"],
                           "conviction": a["conviction"]} for a in alerts[:10]],
            "count":     len(alerts),
        })
        log_file.write_text(json.dumps(history[-100:], indent=2), encoding="utf-8")
    except Exception:
        pass

st.markdown("""
<div style="margin-top:.8rem">
<button onclick="(function(){if('Notification' in window)Notification.requestPermission().then(function(p){document.getElementById('nb').textContent=p==='granted'?'✓ Notifikasi aktif':'✗ Diblokir — cek settings browser';});})()"
style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);padding:.3rem .8rem;
background:rgba(74,158,255,.12);border:1px solid rgba(74,158,255,.25);
border-radius:var(--r-sm);color:var(--c-info);cursor:pointer">
🔔 Izinkan Notifikasi Browser
</button>
<span id="nb" style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:var(--text-secondary);margin-left:.5rem"></span>
</div>
""", unsafe_allow_html=True)
