"""
Simple Trading V6 — Shared UI Assets V5 (Linear Dark / Refined Cyberpunk)
==========================================================================
UPGRADE V5:
  • Systematic spacing scale: --sp-1 through --sp-8 (4px base)
  • 5-level surface hierarchy: --bg-base/raised/overlay/elevated/float
  • Semantic color tokens: --c-success/warning/danger/info/accent
  • Typography scale: --text-xs through --text-2xl with proper line-heights
  • Card radius 8px (Linear standard)
  • Focus states on all interactive elements
  • CSS custom properties throughout (no hardcoded hex in components)
  • Refined animations: shorter durations (150-200ms), easing curves
  • Score badge system: prominent visual hierarchy for signal strength
  • VP Zone pill: AT_POC / IN_VALUE / ABOVE_VAH distinct colors
  • STRONG_BREAKOUT visually distinct from BREAKOUT
  • Skeleton loader component
  • Improved metric card with depth shadow
  • Tag system applied consistently via CSS classes
"""

# ── Design tokens (Python-side) ───────────────────────────────────────────────
BG_BASE     = "#0A0D10"
BG_CARD     = "#0F1318"
BG_DEEP     = "#070A0D"
BG_RAISED   = "#141A22"
BG_OVERLAY  = "#161D26"

NEON_GREEN  = "var(--accent)"
NEON_BRIGHT = "var(--accent)"
ACCENT      = "var(--accent)"

TEXT_MAIN   = "#E2E8F0"
TEXT_MUTED  = "#64748B"
TEXT_DIM    = "#374151"
LABEL_COLOR = "#94A3B8"

# Semantic
C_SUCCESS = "var(--accent)"
C_WARNING = "#F0B429"
C_DANGER  = "#EF4444"
C_INFO    = "#60A5FA"
C_ACCENT  = "var(--accent)"

BORDER_NEON = "rgba(0,255,102,0.12)"
BORDER_DIM  = "rgba(0,255,102,0.06)"

REGIME_COLORS = {
    "BULL_STRONG":       "var(--accent)",
    "BULL_TREND":        "var(--accent)",
    "BULL_CONSOLIDATION":"#A3E635",
    "TRANSITION":        "var(--c-warning)",
    "BEAR_CONSOLIDATION":"#FB8C00",
    "BEAR_TREND":        "var(--c-danger)",
    "UNKNOWN":           "var(--text-muted)",
}

SIG_COLORS = {
    "STRONG_BREAKOUT":  "var(--accent)",
    "BREAKOUT":         "var(--accent)",
    "WATCHLIST":        "var(--c-warning)",
    "CORRECTING":       "#FB8C00",
    "DEEP_CORRECT":     "var(--c-danger)",
    "ACCUMULATION":     "var(--accent)",
    "BLOCK_BUY":        "#60A5FA",
    "RECOVERY_EARLY":   "#FBBF24",
    "VOL_SPIKE_UP":     "var(--c-warning)",
    "DISTRIBUTION":       "var(--c-danger)",
    "BLOCK_SELL":         "#FB8C00",
    # Money Flow signals
    "WHALE_ACCUMULATION": "var(--accent)",
    "INSTITUTIONAL_BUY":  "#60A5FA",
    "RETAIL_MOMENTUM":    "#FBBF24",
    "NEUTRAL":            "var(--text-dim)",
}

VP_ZONE_COLORS = {
    "AT_POC":    "var(--accent)",
    "IN_VALUE":  "#A3E635",
    "ABOVE_VAH": "#60A5FA",
    "BELOW_VAL": "var(--c-danger)",
    "UNKNOWN":   "var(--text-dim)",
}


# ── Number formatting ─────────────────────────────────────────────────────────
def fmt_rp(v: float, decimals: int = 0) -> str:
    if v == 0: return "—"
    return f"Rp{v:,.{decimals}f}"

def fmt_pct(v: float, show_plus: bool = True) -> str:
    if v == 0: return "0.0%"
    prefix = "+" if (show_plus and v > 0) else ""
    return f"{prefix}{v:.1f}%"

def fmt_vol(v: float) -> str:
    return f"{v:.1f}×"

def fmt_bn(v: float) -> str:
    if v == 0: return "—"
    if v >= 1000: return f"Rp{v/1000:.1f}T"
    if v >= 1:    return f"Rp{v:.1f}Bn"
    return f"Rp{v*1000:.0f}Jt"

def fmt_score_ema(score: int, max_score: int = 8) -> str:
    return f"{score}/{max_score}"

def fmt_conv(v: int) -> str:
    return f"{v}/10"


# ── Sparkline SVG ─────────────────────────────────────────────────────────────
def sparkline_svg(prices: list, width: int = 80, height: int = 28,
                  color: str = "var(--accent)") -> str:
    if not prices or len(prices) < 2:
        return f'<svg width="{width}" height="{height}"></svg>'
    mn = min(prices); mx = max(prices)
    rng = mx - mn if mx != mn else 1
    pts = []
    for i, p in enumerate(prices):
        x = i / (len(prices) - 1) * width
        y = height - ((p - mn) / rng * (height - 4)) - 2
        pts.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(pts)
    trend_color = color if prices[-1] >= prices[0] else "var(--c-danger)"
    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}"
  style="display:inline-block;vertical-align:middle">
  <polyline points="{polyline}" fill="none" stroke="{trend_color}"
    stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.9"/>
  <circle cx="{pts[-1].split(',')[0]}" cy="{pts[-1].split(',')[1]}"
    r="2.5" fill="{trend_color}" opacity="1"/>
</svg>"""


# ── Score badge HTML ──────────────────────────────────────────────────────────
def score_badge(score: int, max_score: int = 8) -> str:
    """Prominent score badge with color-graded fill."""
    ratio = score / max_score if max_score > 0 else 0
    if ratio >= 0.75:   col, bg = "var(--accent)", "rgba(0,255,102,0.12)"
    elif ratio >= 0.5:  col, bg = "#A3E635", "rgba(163,230,53,0.10)"
    elif ratio >= 0.37: col, bg = "var(--c-warning)", "rgba(240,180,41,0.10)"
    else:               col, bg = "var(--c-danger)", "rgba(239,68,68,0.09)"
    return (
        f'<span style="background:{bg};border:1px solid {col}40;border-radius:6px;'
        f'padding:2px 8px;font-family:\'Orbitron\',monospace;font-size:var(--text-sm);'
        f'font-weight:700;color:{col};letter-spacing:0.05em;white-space:nowrap">'
        f'{score}<span style="color:{col}60;font-size:var(--text-xs)">/{max_score}</span></span>'
    )


def vp_zone_pill(zone: str) -> str:
    """VP Zone pill: AT_POC / IN_VALUE / ABOVE_VAH / BELOW_VAL."""
    col = VP_ZONE_COLORS.get(zone, VP_ZONE_COLORS["UNKNOWN"])
    labels = {
        "AT_POC":    "⬤ AT POC",
        "IN_VALUE":  "◎ IN VALUE",
        "ABOVE_VAH": "▲ ABOVE VAH",
        "BELOW_VAL": "▼ BELOW VAL",
        "UNKNOWN":   "— VP N/A",
    }
    label = labels.get(zone, zone)
    if zone == "UNKNOWN": return ""
    return (
        f'<span style="background:{col}14;border:1px solid {col}40;border-radius:4px;'
        f'padding:1px 7px;font-family:\'Share Tech Mono\',monospace;font-size:var(--text-2xs);'
        f'letter-spacing:0.08em;color:{col};white-space:nowrap">{label}</span>'
    )


def signal_badge(signal: str) -> str:
    """Signal type badge with appropriate color and icon."""
    icons = {
        "STRONG_BREAKOUT": "🔥", "BREAKOUT": "◈", "WATCHLIST": "◎",
        "CORRECTING": "○", "DEEP_CORRECT": "◌", "ACCUMULATION": "◈",
        "BLOCK_BUY": "▲", "DISTRIBUTION": "▼", "BLOCK_SELL": "◌",
    }
    col = SIG_COLORS.get(signal, "var(--text-muted)")
    icon = icons.get(signal, "—")
    label = signal.replace("_", " ")
    # STRONG_BREAKOUT gets special treatment
    if signal == "STRONG_BREAKOUT":
        return (
            f'<span style="background:rgba(0,255,102,0.10);border:1px solid rgba(0,255,102,0.4);'
            f'border-radius:6px;padding:3px 10px;font-family:\'Orbitron\',monospace;'
            f'font-size:var(--text-xs);font-weight:800;color:var(--accent);letter-spacing:0.1em;'
            f'text-shadow:0 0 10px rgba(0,255,102,0.4)">'
            f'{icon} {label}</span>'
        )
    return (
        f'<span style="background:{col}12;border:1px solid {col}35;border-radius:6px;'
        f'padding:2px 8px;font-family:\'Share Tech Mono\',monospace;font-size:var(--text-xs);'
        f'letter-spacing:0.08em;color:{col}">{icon} {label}</span>'
    )


# ── MASTER CSS ────────────────────────────────────────────────────────────────
def get_page_css(page: str = "dashboard") -> str:
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@400;600;700;900&family=Inter:wght@300;400;500;600&display=swap');

/* ══════════════════════════════════════
   CSS CUSTOM PROPERTIES — DESIGN SYSTEM
══════════════════════════════════════ */
:root {{
  /* Surface hierarchy */
  --bg-base:    {BG_BASE};
  --bg-card:    {BG_CARD};
  --bg-deep:    {BG_DEEP};
  --bg-raised:  {BG_RAISED};
  --bg-overlay: {BG_OVERLAY};

  /* Accent */
  --accent:       {NEON_GREEN};
  --accent-dim:   rgba(0,255,102,0.12);
  --accent-glow:  rgba(0,255,102,0.25);
  --accent-border:rgba(0,255,102,0.18);

  /* Semantic */
  --c-success: {C_SUCCESS};
  --c-warning: {C_WARNING};
  --c-danger:  {C_DANGER};
  --c-info:    {C_INFO};

  /* Text */
  --text-primary: {TEXT_MAIN};
  --text-secondary: {LABEL_COLOR};
  --text-muted:   {TEXT_MUTED};
  --text-dim:     {TEXT_DIM};

  /* Spacing scale (4px base) */
  --sp-1: 0.25rem;  /* 4px */
  --sp-2: 0.5rem;   /* 8px */
  --sp-3: 0.75rem;  /* 12px */
  --sp-4: 1rem;     /* 16px */
  --sp-5: 1.25rem;  /* 20px */
  --sp-6: 1.5rem;   /* 24px */
  --sp-8: 2rem;     /* 32px */
  --sp-10:2.5rem;   /* 40px */

  /* Radius */
  --r-sm:  4px;
  --r-md:  8px;    /* Linear standard */
  --r-lg:  12px;
  --r-xl:  16px;
  --r-pill:999px;

  /* Typography */
  --text-2xs:0.55rem;  /* 8.8px  — micro labels */
  --text-xs: 0.65rem;  /* 10.4px — labels, tags */
  --text-sm: 0.75rem;  /* 12px   — body small */
  --text-base:0.875rem;/* 14px   — body default */
  --text-lg: 1rem;     /* 16px   — emphasized */
  --text-xl: 1.25rem;  /* 20px   — card titles */
  --text-2xl:1.75rem;  /* 28px   — page titles */

  /* Motion */
  --ease-out: cubic-bezier(0.16,1,0.3,1);
  --ease-in:  cubic-bezier(0.7,0,0.84,0);
  --dur-fast: 120ms;
  --dur-base: 180ms;
  --dur-slow: 280ms;

  /* Shadows */
  --shadow-card: 0 1px 3px rgba(0,0,0,0.4), 0 4px 16px rgba(0,0,0,0.25);
  --shadow-hover:0 2px 8px rgba(0,0,0,0.5), 0 0 0 1px rgba(0,255,102,0.15);
  --shadow-glow: 0 0 20px rgba(0,255,102,0.15);
}}

/* ══════════════════════════════════════
   RESET & BASE
══════════════════════════════════════ */
*, *::before, *::after {{ box-sizing: border-box; }}

.stApp {{
  background: var(--bg-base) !important;
  font-family: 'Inter', -apple-system, sans-serif;
  color: var(--text-primary);
  font-size: var(--text-base);
  line-height: 1.6;
}}

/* ── Top accent bar ── */
.stApp::before {{
  content: '';
  position: fixed; top: 0; left: 0; right: 0; height: 2px; z-index: 9999;
  background: linear-gradient(90deg,
    transparent 0%,
    var(--accent) 20%,
    var(--accent) 50%,
    var(--accent) 80%,
    transparent 100%
  );
  animation: accentPulse 8s ease-in-out infinite;
}}
@keyframes accentPulse {{
  0%,100%{{ opacity: 0.8; }}
  50%{{ opacity: 1; filter: brightness(1.2); }}
}}

/* ── Subtle grid ── */
.stApp::after {{
  content: ''; position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background-image:
    linear-gradient(rgba(0,255,102,0.018) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,255,102,0.018) 1px, transparent 1px);
  background-size: 64px 64px;
}}

/* ── Header ── */
header[data-testid="stHeader"] {{ background: transparent !important; }}
[data-testid="stToolbar"] {{ display: none !important; }}

/* ── Main content ── */
.block-container {{
  padding: var(--sp-8) var(--sp-10) var(--sp-8) !important;
  max-width: 1400px !important;
  position: relative; z-index: 1;
}}

/* ══════════════════════════════════════
   SIDEBAR
══════════════════════════════════════ */
section[data-testid="stSidebar"] {{
  background: var(--bg-deep) !important;
  border-right: 1px solid rgba(0,255,102,0.08) !important;
}}
section[data-testid="stSidebar"] > div:first-child {{
  padding-top: 0 !important;
}}

[data-testid="stSidebarNavLink"] {{
  font-family: 'Share Tech Mono', monospace !important;
  font-size: var(--text-xs) !important;
  letter-spacing: 0.1em !important;
  color: var(--text-muted) !important;
  border-radius: var(--r-sm) !important;
  padding: var(--sp-2) var(--sp-3) !important;
  margin: 1px 0 !important;
  transition: all var(--dur-fast) var(--ease-out) !important;
  border-left: 2px solid transparent !important;
}}
[data-testid="stSidebarNavLink"]:hover {{
  color: var(--accent) !important;
  background: var(--accent-dim) !important;
  border-left-color: rgba(0,255,102,0.4) !important;
}}
[data-testid="stSidebarNavLink"][aria-current="page"] {{
  color: var(--accent) !important;
  background: rgba(0,255,102,0.07) !important;
  border-left: 2px solid var(--accent) !important;
}}

/* ══════════════════════════════════════
   BUTTONS
══════════════════════════════════════ */
.stButton > button {{
  font-family: 'Share Tech Mono', monospace !important;
  border-radius: var(--r-sm) !important;
  transition: all var(--dur-base) var(--ease-out) !important;
  outline: none !important;
}}
.stButton > button:focus-visible {{
  box-shadow: 0 0 0 2px var(--bg-base), 0 0 0 4px var(--accent) !important;
}}
.stButton > button[kind="primary"] {{
  font-family: 'Orbitron', monospace !important;
  font-size: var(--text-xs) !important;
  font-weight: 700 !important;
  letter-spacing: 0.15em !important;
  color: var(--accent) !important;
  background: var(--accent-dim) !important;
  border: 1px solid var(--accent-border) !important;
  padding: var(--sp-2) var(--sp-5) !important;
  text-transform: uppercase !important;
}}
.stButton > button[kind="primary"]:hover {{
  background: rgba(0,255,102,0.16) !important;
  border-color: var(--accent) !important;
  box-shadow: var(--shadow-glow) !important;
  transform: translateY(-1px) !important;
}}
.stButton > button[kind="secondary"] {{
  font-size: var(--text-xs) !important;
  letter-spacing: 0.08em !important;
  color: var(--text-secondary) !important;
  background: var(--bg-raised) !important;
  border: 1px solid rgba(255,255,255,0.06) !important;
  padding: var(--sp-2) var(--sp-4) !important;
}}
.stButton > button[kind="secondary"]:hover {{
  color: var(--accent) !important;
  border-color: var(--accent-border) !important;
  background: rgba(0,255,102,0.04) !important;
}}

/* ══════════════════════════════════════
   METRICS
══════════════════════════════════════ */
[data-testid="stMetric"] {{
  background: var(--bg-card) !important;
  border: 1px solid rgba(255,255,255,0.06) !important;
  border-radius: var(--r-md) !important;
  padding: var(--sp-4) var(--sp-5) !important;
  box-shadow: var(--shadow-card) !important;
  transition: border-color var(--dur-base) var(--ease-out),
              box-shadow   var(--dur-base) var(--ease-out) !important;
}}
[data-testid="stMetric"]:hover {{
  border-color: var(--accent-border) !important;
  box-shadow: var(--shadow-hover) !important;
}}
[data-testid="stMetricLabel"] > div {{
  font-family: 'Share Tech Mono', monospace !important;
  font-size: var(--text-2xs) !important;
  letter-spacing: 0.2em !important;
  color: var(--text-dim) !important;
  text-transform: uppercase !important;
}}
[data-testid="stMetricValue"] > div {{
  font-family: 'Orbitron', monospace !important;
  font-size: 1.5rem !important;
  font-weight: 700 !important;
  color: var(--accent) !important;
  line-height: 1.15 !important;
}}
[data-testid="stMetricDelta"] {{
  font-family: 'Share Tech Mono', monospace !important;
  font-size: var(--text-xs) !important;
}}

/* ══════════════════════════════════════
   TABS
══════════════════════════════════════ */
.stTabs [data-baseweb="tab-list"] {{
  background: transparent !important;
  gap: 2px !important;
  border-bottom: 1px solid rgba(255,255,255,0.06) !important;
  padding-bottom: 0 !important;
}}
.stTabs [data-baseweb="tab"] {{
  font-family: 'Share Tech Mono', monospace !important;
  font-size: var(--text-xs) !important;
  letter-spacing: 0.1em !important;
  color: var(--text-muted) !important;
  background: transparent !important;
  border: none !important;
  border-bottom: 2px solid transparent !important;
  border-radius: 0 !important;
  padding: var(--sp-2) var(--sp-4) !important;
  transition: all var(--dur-fast) var(--ease-out) !important;
  text-transform: uppercase !important;
}}
.stTabs [data-baseweb="tab"]:hover {{
  color: var(--text-primary) !important;
  background: rgba(255,255,255,0.03) !important;
}}
.stTabs [aria-selected="true"] {{
  color: var(--accent) !important;
  border-bottom: 2px solid var(--accent) !important;
  background: rgba(0,255,102,0.04) !important;
}}
.stTabs [data-baseweb="tab-panel"] {{
  padding: var(--sp-4) 0 0 !important;
}}

/* ══════════════════════════════════════
   EXPANDERS
══════════════════════════════════════ */
.stExpander {{
  border: 1px solid rgba(255,255,255,0.06) !important;
  border-radius: var(--r-md) !important;
  background: var(--bg-card) !important;
  margin-bottom: var(--sp-2) !important;
  overflow: hidden !important;
  box-shadow: var(--shadow-card) !important;
  transition: border-color var(--dur-base) var(--ease-out) !important;
}}
.stExpander:hover {{
  border-color: var(--accent-border) !important;
}}
.stExpander details summary {{
  padding: var(--sp-3) var(--sp-4) !important;
}}
.stExpander summary p, .stExpander summary span {{
  font-family: 'Share Tech Mono', monospace !important;
  font-size: var(--text-sm) !important;
  letter-spacing: 0.06em !important;
  color: var(--text-primary) !important;
}}
.stExpander [data-testid="stExpanderToggleIcon"] svg {{
  color: rgba(0,255,102,0.5) !important;
  fill: rgba(0,255,102,0.5) !important;
}}
.stExpander details[open] [data-testid="stExpanderToggleIcon"] svg {{
  color: var(--accent) !important;
  fill: var(--accent) !important;
}}

/* ══════════════════════════════════════
   DATAFRAME / TABLE
══════════════════════════════════════ */
[data-testid="stDataFrame"] {{
  border: 1px solid rgba(255,255,255,0.06) !important;
  border-radius: var(--r-md) !important;
  overflow: hidden !important;
  box-shadow: var(--shadow-card) !important;
}}
[data-testid="stDataFrame"] th {{
  background: var(--bg-deep) !important;
  font-family: 'Share Tech Mono', monospace !important;
  font-size: var(--text-2xs) !important;
  letter-spacing: 0.15em !important;
  color: var(--text-dim) !important;
  text-transform: uppercase !important;
  border-bottom: 1px solid rgba(255,255,255,0.06) !important;
  padding: var(--sp-2) var(--sp-3) !important;
}}
[data-testid="stDataFrame"] td {{
  font-family: 'Share Tech Mono', monospace !important;
  font-size: var(--text-sm) !important;
  color: var(--text-secondary) !important;
  padding: var(--sp-2) var(--sp-3) !important;
  border-bottom: 1px solid rgba(255,255,255,0.03) !important;
}}
[data-testid="stDataFrame"] tr:hover td {{
  background: rgba(255,255,255,0.02) !important;
  color: var(--text-primary) !important;
}}

/* ══════════════════════════════════════
   FORM INPUTS
══════════════════════════════════════ */
.stMultiSelect [data-baseweb="select"] > div,
.stSelectbox [data-baseweb="select"] > div {{
  background: var(--bg-card) !important;
  border: 1px solid rgba(255,255,255,0.08) !important;
  border-radius: var(--r-md) !important;
  font-family: 'Share Tech Mono', monospace !important;
  font-size: var(--text-sm) !important;
  color: var(--text-primary) !important;
  transition: border-color var(--dur-fast) !important;
}}
.stMultiSelect [data-baseweb="select"] > div:hover,
.stSelectbox [data-baseweb="select"] > div:hover {{
  border-color: var(--accent-border) !important;
}}
.stMultiSelect [data-baseweb="select"] > div:focus-within,
.stSelectbox [data-baseweb="select"] > div:focus-within {{
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 3px var(--accent-dim) !important;
}}
.stMultiSelect span[data-baseweb="tag"] {{
  background: var(--accent-dim) !important;
  border: 1px solid var(--accent-border) !important;
  font-family: 'Share Tech Mono', monospace !important;
  font-size: var(--text-xs) !important;
  color: var(--accent) !important;
  border-radius: var(--r-sm) !important;
}}
.stNumberInput input, .stTextInput input {{
  background: var(--bg-card) !important;
  border: 1px solid rgba(255,255,255,0.08) !important;
  border-radius: var(--r-md) !important;
  color: var(--text-primary) !important;
  font-family: 'Share Tech Mono', monospace !important;
  font-size: var(--text-sm) !important;
  transition: border-color var(--dur-fast) !important;
}}
.stNumberInput input:focus, .stTextInput input:focus {{
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 3px var(--accent-dim) !important;
  outline: none !important;
}}

/* Slider */
[data-baseweb="slider"] [data-testid="stThumb"] {{
  background: var(--accent) !important;
  border: none !important;
  box-shadow: 0 0 12px var(--accent-glow) !important;
}}

/* Widget labels */
label[data-testid="stWidgetLabel"] p,
label[data-testid="stWidgetLabel"] span {{
  font-family: 'Share Tech Mono', monospace !important;
  font-size: var(--text-2xs) !important;
  letter-spacing: 0.16em !important;
  color: var(--text-dim) !important;
  text-transform: uppercase !important;
}}

/* ══════════════════════════════════════
   ALERTS
══════════════════════════════════════ */
[data-testid="stAlert"] {{
  background: rgba(14,19,24,0.95) !important;
  border-radius: var(--r-md) !important;
  font-family: 'Share Tech Mono', monospace !important;
  font-size: var(--text-sm) !important;
  border-left: 3px solid var(--accent) !important;
}}

/* ══════════════════════════════════════
   SPINNER
══════════════════════════════════════ */
[data-testid="stSpinner"] > div {{
  border-top-color: var(--accent) !important;
  border-right-color: transparent !important;
  border-bottom-color: transparent !important;
  border-left-color: transparent !important;
}}
[data-testid="stSpinner"] p {{
  font-family: 'Share Tech Mono', monospace !important;
  font-size: var(--text-xs) !important;
  letter-spacing: 0.14em !important;
  color: var(--accent) !important;
  opacity: 0.8;
}}

/* ══════════════════════════════════════
   SCROLLBAR
══════════════════════════════════════ */
::-webkit-scrollbar {{ width: 4px; height: 4px; }}
::-webkit-scrollbar-track {{ background: var(--bg-base); }}
::-webkit-scrollbar-thumb {{ background: rgba(255,255,255,0.1); border-radius: 2px; }}
::-webkit-scrollbar-thumb:hover {{ background: rgba(0,255,102,0.3); }}

/* ══════════════════════════════════════
   DIVIDER
══════════════════════════════════════ */
hr {{
  border: none !important;
  border-top: 1px solid rgba(255,255,255,0.05) !important;
  margin: var(--sp-4) 0 !important;
}}

/* ══════════════════════════════════════
   SHARED COMPONENT CLASSES
══════════════════════════════════════ */

/* Section header */
.sec-head {{
  font-family: 'Share Tech Mono', monospace;
  font-size: var(--text-2xs);
  letter-spacing: 0.28em;
  color: rgba(0,255,102,0.5);
  border-bottom: 1px solid rgba(0,255,102,0.06);
  padding-bottom: var(--sp-2);
  margin: var(--sp-6) 0 var(--sp-4);
  text-transform: uppercase;
}}

/* Page header */
.pg-eyebrow {{
  font-family: 'Share Tech Mono', monospace;
  font-size: var(--text-2xs);
  letter-spacing: 0.3em;
  color: rgba(0,255,102,0.5);
  margin: 0 0 var(--sp-1);
}}
.pg-h1 {{
  font-family: 'Orbitron', monospace;
  font-size: 1.85rem;
  font-weight: 900;
  color: var(--text-primary);
  letter-spacing: 0.05em;
  margin: 0 0 var(--sp-1);
  line-height: 1.1;
}}
.pg-h1 .accent {{ color: var(--accent); }}
.pg-sub {{
  font-family: 'Share Tech Mono', monospace;
  font-size: var(--text-xs);
  letter-spacing: 0.12em;
  color: var(--text-muted);
}}

/* Regime bar */
.regime-bar {{
  background: var(--bg-card);
  border: 1px solid rgba(255,255,255,0.06);
  border-left: 3px solid var(--rc, var(--text-dim));
  border-radius: var(--r-md);
  padding: var(--sp-3) var(--sp-6);
  display: flex; gap: var(--sp-6); align-items: center; flex-wrap: wrap;
  font-family: 'Share Tech Mono', monospace;
  font-size: var(--text-xs);
  margin-bottom: var(--sp-5);
  box-shadow: var(--shadow-card);
}}
.regime-bar .r-label {{ color: var(--text-dim); }}
.regime-bar b {{ color: var(--text-primary); }}

/* Card */
.stv-card {{
  background: var(--bg-card);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: var(--r-md);
  padding: var(--sp-4) var(--sp-5);
  box-shadow: var(--shadow-card);
  transition: border-color var(--dur-base) var(--ease-out),
              box-shadow   var(--dur-base) var(--ease-out);
}}
.stv-card:hover {{
  border-color: var(--accent-border);
  box-shadow: var(--shadow-hover);
}}

/* Signal card — stronger left accent */
.signal-card {{
  background: var(--bg-card);
  border: 1px solid rgba(255,255,255,0.06);
  border-left: 3px solid var(--sc, var(--text-dim));
  border-radius: var(--r-md);
  padding: var(--sp-4) var(--sp-5);
  box-shadow: var(--shadow-card);
  margin-bottom: var(--sp-2);
  transition: border-color var(--dur-base), box-shadow var(--dur-base);
}}
.signal-card:hover {{
  border-color: rgba(255,255,255,0.12);
  box-shadow: var(--shadow-hover);
}}
.signal-card.strong-breakout {{
  border-left-color: var(--accent);
  background: linear-gradient(135deg, rgba(0,255,102,0.04) 0%, var(--bg-card) 40%);
}}

/* Metric mini card */
.m-card {{
  background: var(--bg-card);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: var(--r-md);
  padding: var(--sp-3) var(--sp-4);
  box-shadow: var(--shadow-card);
  transition: border-color var(--dur-base), box-shadow var(--dur-base);
}}
.m-card:hover {{
  border-color: var(--accent-border);
  box-shadow: var(--shadow-hover);
}}
.m-lbl {{
  font-family: 'Share Tech Mono', monospace;
  font-size: var(--text-2xs);
  letter-spacing: 0.2em;
  color: var(--text-dim);
  margin-bottom: 3px;
  text-transform: uppercase;
}}
.m-val {{
  font-family: 'Orbitron', monospace;
  font-size: var(--text-xl);
  font-weight: 700;
  line-height: 1.1;
  color: var(--accent);
}}
.m-sub {{
  font-family: 'Share Tech Mono', monospace;
  font-size: var(--text-2xs);
  color: var(--text-muted);
  margin-top: 3px;
  line-height: 1.5;
}}

/* Tag system */
.tag {{
  display: inline-block; border-radius: var(--r-sm);
  padding: 1px 7px;
  font-family: 'Share Tech Mono', monospace;
  font-size: var(--text-2xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  margin-right: 3px;
  line-height: 1.8;
}}
.tag-g {{ background: rgba(0,255,102,0.09);   color: var(--c-success); border: 1px solid rgba(0,255,102,0.22);  }}
.tag-b {{ background: rgba(96,165,250,0.09);  color: var(--c-info);    border: 1px solid rgba(96,165,250,0.22); }}
.tag-y {{ background: rgba(240,180,41,0.09);  color: var(--c-warning); border: 1px solid rgba(240,180,41,0.22); }}
.tag-r {{ background: rgba(239,68,68,0.09);   color: var(--c-danger);  border: 1px solid rgba(239,68,68,0.22);  }}
.tag-x {{ background: rgba(100,116,139,0.09); color: var(--text-muted);border: 1px solid rgba(100,116,139,0.18);}}

/* Bear banner */
.bear-banner {{
  background: rgba(239,68,68,0.06);
  border: 1px solid rgba(239,68,68,0.25);
  border-left: 3px solid var(--c-danger);
  border-radius: var(--r-md);
  padding: var(--sp-3) var(--sp-5);
  margin-bottom: var(--sp-4);
  font-family: 'Share Tech Mono', monospace;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  display: flex; align-items: center; gap: var(--sp-5); flex-wrap: wrap;
}}

/* Empty state */
.empty-state {{
  text-align: center;
  padding: var(--sp-10) var(--sp-8);
  border: 1px dashed rgba(255,255,255,0.06);
  border-radius: var(--r-lg);
  margin: var(--sp-4) 0;
}}
.empty-state .es-icon {{
  font-size: 2rem; margin-bottom: var(--sp-4); opacity: 0.2;
}}
.empty-state .es-title {{
  font-family: 'Orbitron', monospace;
  font-size: var(--text-sm); font-weight: 700;
  color: var(--text-muted); letter-spacing: 0.18em;
  margin-bottom: var(--sp-2);
}}
.empty-state .es-sub {{
  font-family: 'Share Tech Mono', monospace;
  font-size: var(--text-xs); letter-spacing: 0.1em;
  color: var(--text-dim); line-height: 2.0;
}}

/* Sidebar brand */
.sb-brand {{
  padding: var(--sp-5) var(--sp-4) var(--sp-4);
  border-bottom: 1px solid rgba(255,255,255,0.05);
  margin-bottom: var(--sp-2);
}}
.sb-eyebrow {{
  font-family: 'Share Tech Mono', monospace;
  font-size: var(--text-2xs); letter-spacing: 0.28em;
  color: rgba(0,255,102,0.3); margin: 0;
}}
.sb-title {{
  font-family: 'Orbitron', monospace;
  font-size: 0.92rem; font-weight: 700;
  color: var(--text-primary); margin: var(--sp-1) 0 0;
}}
.sb-nav-label {{
  font-family: 'Share Tech Mono', monospace;
  font-size: var(--text-2xs); letter-spacing: 0.24em;
  color: var(--text-dim);
  padding: var(--sp-3) var(--sp-3) var(--sp-1);
  text-transform: uppercase;
}}
.sb-stat {{
  font-family: 'Share Tech Mono', monospace;
  font-size: var(--text-xs); color: var(--text-dim);
  padding: 3px var(--sp-4);
  line-height: 1.8;
}}
.sb-stat b {{ color: var(--accent); font-weight: 400; }}

/* Exit framework card */
.exit-card {{
  background: rgba(4,10,6,0.85);
  border: 1px solid rgba(0,255,102,0.09);
  border-radius: var(--r-md);
  padding: var(--sp-3) var(--sp-4);
  margin-top: var(--sp-3);
}}
.exit-row {{
  display: flex; gap: var(--sp-6); flex-wrap: wrap;
  font-family: 'Share Tech Mono', monospace;
  font-size: var(--text-xs);
}}
.exit-item .ei-label {{ color: var(--text-dim); font-size: var(--text-2xs); letter-spacing: 0.14em; margin-bottom: 2px; }}
.exit-item .ei-val   {{ color: var(--text-primary); font-weight: 600; }}
.exit-item .ei-warn  {{ color: var(--c-danger);  font-weight: 600; }}
.exit-item .ei-ok    {{ color: var(--c-success); font-weight: 600; }}

/* Tooltip */
.tt {{
  display: inline-block;
  font-family: 'Share Tech Mono', monospace;
  font-size: var(--text-2xs); letter-spacing: 0.1em;
  color: rgba(0,255,102,0.35);
  border: 1px solid rgba(0,255,102,0.12);
  border-radius: var(--r-sm);
  padding: 1px 5px; cursor: help; margin-left: 4px;
  vertical-align: middle;
}}

/* Skeleton loader */
.skeleton {{
  background: linear-gradient(
    90deg,
    var(--bg-raised) 25%,
    rgba(255,255,255,0.04) 50%,
    var(--bg-raised) 75%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: var(--r-sm);
}}
@keyframes shimmer {{
  0%  {{ background-position: 200% 0; }}
  100%{{ background-position: -200% 0; }}
}}
.sk-line {{
  height: 12px; margin-bottom: 8px;
  border-radius: var(--r-sm);
}}
.sk-title {{ height: 18px; width: 60%; }}
.sk-text  {{ height: 10px; width: 85%; }}
.sk-short {{ height: 10px; width: 40%; }}

</style>
"""


# ── Sidebar component ─────────────────────────────────────────────────────────
def render_sidebar(page: str, ema_total: int = 0, whale_total: int = 0,
                   scan_date: str = "—", regime: str = "—"):
    import streamlit as st
    import json as _json
    from pathlib import Path as _Path
    from datetime import datetime, date

    regime_color = REGIME_COLORS.get(regime, TEXT_MUTED)

    _vf = _Path(__file__).parent / "version.json"
    _ver = "6"; _ver_full = "6"
    try:
        _vdata    = _json.loads(_vf.read_text(encoding="utf-8"))
        _ver_full = _vdata.get("version", "6")
        _ver      = _ver_full.split(".")[0]
    except Exception:
        pass

    st.markdown(f"""
    <div class="sb-brand">
      <p class="sb-eyebrow">◈ SIMPLE TRADING V{_ver_full}</p>
      <p class="sb-title">STV{_ver}</p>
    </div>
    <p class="sb-nav-label">Navigation</p>
    """, unsafe_allow_html=True)

    if st.button("← BACK TO GATE", key="nav_gate", width="stretch"):
        st.switch_page("gate.py")

    # Scan staleness
    try:
        scan_d = datetime.strptime(scan_date[:10], "%Y-%m-%d").date() if scan_date and scan_date != "—" else None
        if scan_d:
            delta = (date.today() - scan_d).days
            if delta == 0:   stale = '<span style="color:var(--c-success);font-size:var(--text-xs)">● TODAY</span>'
            elif delta == 1: stale = '<span style="color:var(--c-warning);font-size:var(--text-xs)">● YESTERDAY</span>'
            else:            stale = f'<span style="color:var(--c-danger);font-size:var(--text-xs)">⚠ {delta}D AGO</span>'
            st.markdown(f"""<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);
            color:var(--text-dim);padding:2px 0 0 4px">DATA {stale}</div>""",
            unsafe_allow_html=True)
    except Exception:
        pass

    st.markdown(f"""
    <p class="sb-nav-label" style="margin-top:var(--sp-4)">Market</p>
    <div class="sb-stat">REGIME <b style="color:{regime_color}">{regime}</b></div>
    <div class="sb-stat">LAST SCAN <b>{scan_date}</b></div>
    <div class="sb-stat">EMA SIGNALS <b>{ema_total}</b></div>
    <div class="sb-stat">WHALE ALERTS <b>{whale_total}</b></div>
    <p class="sb-nav-label" style="margin-top:var(--sp-4)">System</p>
    <div class="sb-stat" style="color:var(--text-dim);font-size:var(--text-2xs);letter-spacing:0.1em">
      IDX · LONG ONLY · HENGKY METHOD
    </div>
    """, unsafe_allow_html=True)


# ── Page header ───────────────────────────────────────────────────────────────
def render_page_header(eyebrow: str, title: str, accent: str, subtitle: str,
                       scan_date: str = "—"):
    import streamlit as st
    st.markdown(f"""
    <div style="margin-bottom:var(--sp-5)">
      <p class="pg-eyebrow">{eyebrow}</p>
      <h1 class="pg-h1">{title}<span class="accent">{accent}</span></h1>
      <p class="pg-sub">{subtitle}</p>
    </div>
    """, unsafe_allow_html=True)


# ── Regime bar ────────────────────────────────────────────────────────────────
def render_regime_bar(cycle: str, ihsg: float, mom_4w: float,
                      breadth: int, scan_date: str = "—", extra: str = ""):
    import streamlit as st
    rc = REGIME_COLORS.get(cycle, TEXT_MUTED)
    mc = C_SUCCESS if mom_4w > 0 else C_DANGER

    bear_html = ""
    if cycle == "BEAR_TREND":
        bear_html = """
        <div class="bear-banner">
          <span style="color:var(--c-danger);font-weight:700;font-size:var(--text-base)">⛔ BEAR TREND ACTIVE</span>
          <span>ALL LONG SIGNALS = SPECULATIVE ONLY · MAX 25% SIZE · PREFER CASH</span>
        </div>"""
    elif cycle == "BEAR_CONSOLIDATION":
        bear_html = """
        <div class="bear-banner" style="border-color:rgba(251,140,0,0.25);border-left-color:var(--c-warning);background:rgba(251,140,0,0.04)">
          <span style="color:var(--c-warning);font-weight:700">⚠ BEAR CONSOLIDATION</span>
          <span>SELECTIVE ONLY · BUILD WATCHLIST · WAIT FOR CONFIRMATION</span>
        </div>"""
    elif cycle == "BULL_STRONG":
        bear_html = """
        <div class="bear-banner" style="border-color:rgba(0,255,102,0.2);border-left-color:var(--c-success);background:rgba(0,255,102,0.03)">
          <span style="color:var(--c-success);font-weight:700">✦ BULL STRONG</span>
          <span style="color:var(--text-muted)">FULL SIZE ALLOWED · AGGRESSIVE BREAKOUT MODE · FOLLOW SMART MONEY</span>
        </div>"""

    st.markdown(f"""
    {bear_html}
    <div class="regime-bar" style="--rc:{rc}">
      <span style="color:{rc};font-family:Orbitron,monospace;font-size:var(--text-base);font-weight:700;letter-spacing:0.06em">⬤ {cycle}</span>
      <span class="r-label">IHSG <b>{ihsg:,.0f}</b></span>
      <span class="r-label">4W <b style="color:{mc}">{mom_4w:+.1f}%</b></span>
      <span class="r-label">BREADTH <b>{breadth}/6</b></span>
      {extra}
      <span style="color:var(--text-dim);margin-left:auto;font-family:Share Tech Mono,monospace;
      font-size:var(--text-2xs);letter-spacing:0.1em">SCAN: {scan_date}</span>
    </div>
    """, unsafe_allow_html=True)


# ── Empty state ───────────────────────────────────────────────────────────────
def render_empty_state(icon: str = "◎", title: str = "NO DATA",
                       subtitle: str = "Run a scan to populate this view.",
                       command: str = ""):
    import streamlit as st
    cmd_html = (
        f'<div style="margin-top:var(--sp-4);font-size:var(--text-xs);color:var(--text-dim)">'
        f'<code style="background:rgba(0,255,102,0.04);padding:2px 10px;'
        f'border:1px solid rgba(0,255,102,0.08);border-radius:var(--r-sm)">{command}</code></div>'
        if command else ""
    )
    st.markdown(f"""
    <div class="empty-state">
      <div class="es-icon">{icon}</div>
      <div class="es-title">{title}</div>
      <div class="es-sub">{subtitle}</div>
      {cmd_html}
    </div>
    """, unsafe_allow_html=True)


# ── Section head ──────────────────────────────────────────────────────────────
def sec_head(label: str):
    import streamlit as st
    st.markdown(f'<p class="sec-head">{label}</p>', unsafe_allow_html=True)


# ── Skeleton loader ───────────────────────────────────────────────────────────
def render_skeleton(rows: int = 3):
    import streamlit as st
    html = '<div style="padding:var(--sp-4)">'
    for _ in range(rows):
        html += '<div class="skeleton sk-line sk-title"></div>'
        html += '<div class="skeleton sk-line sk-text"></div>'
        html += '<div class="skeleton sk-line sk-short" style="margin-bottom:var(--sp-4)"></div>'
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)
