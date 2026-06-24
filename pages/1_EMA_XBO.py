"""
Simple Trading V9 — EMA XBO Dashboard V4
CHANGELOG V4 (Audit Fixes):
  - FIX CRITICAL: MCF JOIN override → ⛔ BEAR REGIME ketika regime_tag = WATCHLIST_ONLY
  - FIX HIGH    : Risk warning badge merah untuk sinyal dengan risk_pct > 15%
  - FIX HIGH    : EMA200 warning badge jika data < 150 bars (tidak reliable)
  - NEW         : "Log Outcome" section — trader bisa log WIN/LOSS dari dashboard
  - NEW         : Performance tracker mini di sidebar — shows closed/30 trades
"""
import sys
import streamlit as st
import pandas as pd
import json
from pathlib import Path
from datetime import datetime, date

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Module-level helper — menggantikan 4x definisi _g() nested ──────────────
def _g(r, key, default=0):
    """Ambil field dari dict atau object secara safe."""
    if isinstance(r, dict):
        return r.get(key, default)
    return getattr(r, key, default)


st.set_page_config(page_title="EMA-XBO Scanner",
                   page_icon="🎯", layout="wide",
                   initial_sidebar_state="expanded")

from assets_ui import (
    get_page_css, render_sidebar, render_page_header, render_regime_bar,
    render_empty_state, sec_head, NEON_GREEN,
    score_badge, vp_zone_pill, signal_badge, SIG_COLORS,
)


# ─────────────────────────────────────────────────────────────────────────────
# FIX V4: MCF render dengan BEAR BLOCKING yang benar
# ─────────────────────────────────────────────────────────────────────────────

def _render_mcf_block(r, lines_out: list) -> None:
    """
    Render MCF block di dalam detail card.

    FIX V4 CRITICAL: Jika regime_tag == WATCHLIST_ONLY DAN mcf_label == JOIN:
    - Override tampilan ke "⛔ BEAR REGIME — JANGAN TRADE"
    - Jangan tampilkan badge hijau "◈ JOIN NOW"
    - Ini mencegah trader salah baca situasi

    Sebelumnya: MCF 8/10 JOIN ditampilkan dengan badge hijau terang
                bahkan saat EMA system bilang WATCHLIST_ONLY (bear market)
    """
    mcf_score   = _g(r, "mcf_score", 0)
    mcf_label   = _g(r, "mcf_label", "")
    mcf_mom     = _g(r, "mcf_momentum", 0)
    mcf_vol     = _g(r, "mcf_volume", 0)
    mcf_fu      = _g(r, "mcf_followup", 0)
    mcf_ok      = _g(r, "mcf_entry_ok", False)
    mcf_detail  = _g(r, "mcf_detail", {})
    regime_tag  = _g(r, "regime_tag", "")
    bear_blocked = _g(r, "mcf_bear_blocked", False)

    # FIX V4: Override jika bear blocked (atau regime_tag WATCHLIST_ONLY + mcf JOIN)
    # Double safety: cek dari dua sumber
    is_bear_blocked = (
        bear_blocked or
        (regime_tag == "WATCHLIST_ONLY" and mcf_label in ("JOIN", "BEAR_BLOCKED"))
    )

    if is_bear_blocked or (regime_tag == "WATCHLIST_ONLY" and mcf_score >= 6):
        # ── BEAR BLOCK DISPLAY ────────────────────────────────────────────────
        # Tidak tampilkan badge hijau. Tampilkan peringatan merah.
        lines_out.append(
            '<div style="background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.35);'
            'border-radius:var(--r-md);padding:0.55rem 0.8rem;margin:0.3rem 0">'
            '<div style="display:flex;align-items:center;gap:0.7rem">'
            '<span style="background:#EF4444;color:#fff;font-weight:700;'
            'font-family:Orbitron,monospace;font-size:var(--text-xs);border-radius:var(--r-sm);'
            'padding:2px 8px">⛔ BEAR REGIME — JANGAN TRADE</span>'
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
            f'color:#EF4444;font-weight:700">MCF {mcf_score}/10 (BLOCKED)</span>'
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:#64748B">'
            'EMA system: WATCHLIST_ONLY</span>'
            '</div>'
            '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
            'color:#94A3B8;margin-top:0.3rem">'
            f'MCF menghasilkan skor {mcf_score}/10 namun regime IHSG = WATCHLIST_ONLY. '
            'Sistem EMA melarang entry di kondisi ini. '
            'Sinyal momentum tidak valid saat pasar bearish. '
            'Tunggu regime berubah ke FULL atau SELECTIVE.'
            '</div>'
            '</div>'
        )
        return

    if not (mcf_score > 0 or mcf_label):
        return

    # ── Normal MCF display (non-bear) ────────────────────────────────────────
    mcf_col = "#00FF66" if mcf_label == "JOIN" else "#F0B429" if mcf_label == "WAIT" else "#EF4444"
    mcf_bg  = ("rgba(0,255,102,0.06)" if mcf_label == "JOIN"
               else "rgba(240,180,41,0.05)" if mcf_label == "WAIT"
               else "rgba(239,68,68,0.04)")

    def _pill(n, max_n=3, col="#00FF66"):
        filled = "█" * n
        empty  = "░" * (max_n - n)
        return f'<b style="color:{col};font-family:monospace">{filled}</b><span style="color:#374151">{empty}</span>'

    mcf_col_m = "#00FF66" if mcf_mom == 3 else "#F0B429" if mcf_mom >= 2 else "#64748B"
    mcf_col_v = "#00FF66" if mcf_vol == 3 else "#F0B429" if mcf_vol >= 2 else "#64748B"
    mcf_col_f = "#00FF66" if mcf_fu == 3 else "#F0B429" if mcf_fu >= 2 else "#64748B"

    det_m = (mcf_detail.get("momentum", "") if isinstance(mcf_detail, dict) else "")[:90]
    det_v = (mcf_detail.get("volume",   "") if isinstance(mcf_detail, dict) else "")[:90]
    det_f = (mcf_detail.get("followup", "") if isinstance(mcf_detail, dict) else "")[:90]
    mcf_mkt = _g(r, "mcf_market_bonus", 0)
    mcf_mkt_str = ("IHSG ↑ +1 bonus" if mcf_mkt > 0
                   else "IHSG ↓ −1 penalti" if mcf_mkt < 0
                   else "market neutral")

    # Badge JOIN hanya muncul jika entry_ok=True DAN bukan bear
    mcf_join_badge = (
        '<span style="background:#00FF66;color:#000;font-weight:700;'
        'font-family:Orbitron,monospace;font-size:var(--text-xs);border-radius:var(--r-sm);'
        'padding:2px 8px;margin-right:0.5rem">◈ JOIN NOW</span>'
        if mcf_ok else ""
    )

    lines_out.append(
        f'<div style="background:{mcf_bg};border:1px solid {mcf_col}30;'
        'border-radius:var(--r-md);padding:0.55rem 0.8rem;margin:0.3rem 0">'
        '<div style="display:flex;align-items:center;gap:0.7rem;margin-bottom:0.4rem">'
        f'{mcf_join_badge}'
        '<span style="font-family:Orbitron,monospace;font-size:var(--text-2xs);'
        f'letter-spacing:0.15em;color:{mcf_col};font-weight:700">'
        f'MCF {mcf_score}/10 — {mcf_label}</span>'
        '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:#374151">'
        f'{mcf_mkt_str}</span>'
        '</div>'
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.4rem">'
        '<div style="background:rgba(0,0,0,0.2);border-radius:var(--r-sm);padding:0.35rem 0.6rem">'
        '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
        f'letter-spacing:0.15em;color:#374151;margin-bottom:2px">MOMENTUM {mcf_mom}/3</div>'
        f'<div>{_pill(mcf_mom, col=mcf_col_m)}</div>'
        f'<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:#64748B;margin-top:2px">{det_m}</div>'
        '</div>'
        '<div style="background:rgba(0,0,0,0.2);border-radius:var(--r-sm);padding:0.35rem 0.6rem">'
        '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
        f'letter-spacing:0.15em;color:#374151;margin-bottom:2px">VOLUME {mcf_vol}/3</div>'
        f'<div>{_pill(mcf_vol, col=mcf_col_v)}</div>'
        f'<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:#64748B;margin-top:2px">{det_v}</div>'
        '</div>'
        '<div style="background:rgba(0,0,0,0.2);border-radius:var(--r-sm);padding:0.35rem 0.6rem">'
        '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
        f'letter-spacing:0.15em;color:#374151;margin-bottom:2px">FOLLOW-UP {mcf_fu}/3</div>'
        f'<div>{_pill(mcf_fu, col=mcf_col_f)}</div>'
        f'<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:#64748B;margin-top:2px">{det_f}</div>'
        '</div>'
        '</div>'
        '</div>'
    )


def _render_risk_warning(r, lines_out: list) -> None:
    """
    NEW V4: Risk warning badge untuk sinyal dengan risk > 15%.

    Sebelumnya: 51% sinyal memiliki risk > 25% tanpa peringatan apapun.
    Ini menyebabkan trader bisa over-size posisi tanpa sadar.

    Sekarang: Badge merah + kalkulasi max lot yang aman (1% modal = 10jt default).
    """
    risk_pct      = _g(r, "risk_pct", 0)
    entry_price   = _g(r, "entry_price", _g(r, "close", 0))
    sl_price      = _g(r, "sl_price", 0)

    if risk_pct <= 15:
        return  # Tidak perlu warning

    # Kalkulasi max lot berdasarkan 1% modal
    # Modal dari session_state jika user sudah set, default 100jt
    import streamlit as _st
    modal_default   = int(_st.session_state.get("modal_size", 100_000_000))
    risk_per_trade  = modal_default * 0.01  # 1% modal
    risk_per_lembar = (entry_price - sl_price) if sl_price > 0 and entry_price > sl_price else entry_price * (risk_pct / 100)
    max_lembar      = int(risk_per_trade / risk_per_lembar) if risk_per_lembar > 0 else 0
    max_lot_str     = f"{max_lembar:,} lembar (Rp{max_lembar * entry_price / 1_000_000:.1f}jt)" if max_lembar > 0 else "kalkulasi manual"

    if risk_pct > 35:
        badge_col  = "#EF4444"
        badge_text = f"⛔ RISK {risk_pct:.0f}% — HAMPIR TIDAK TRADEABLE"
        detail     = f"SL terlalu jauh ({risk_pct:.0f}% dari entry). Dengan money management 1%, max sizing Rp{modal_default/1e6:.0f}jt modal: {max_lot_str}."
    elif risk_pct > 25:
        badge_col  = "#EF4444"
        badge_text = f"⚠ RISK {risk_pct:.0f}% — SANGAT LEBAR"
        detail     = f"Risk > 25%. Sizing harus sangat kecil. Max 1% modal: {max_lot_str}."
    else:
        badge_col  = "#F0B429"
        badge_text = f"⚠ RISK {risk_pct:.0f}% — HATI-HATI SIZING"
        detail     = f"Risk melebihi 15%. Kurangi ukuran posisi. Max 1% modal Rp{modal_default/1e6:.0f}jt: {max_lot_str}."

    lines_out.append(
        f'<div style="background:rgba({("239,68,68" if risk_pct > 25 else "240,180,41")},0.08);'
        f'border:1px solid {badge_col}55;border-radius:var(--r-sm);'
        'padding:0.4rem 0.8rem;margin:0.2rem 0">'
        '<span style="font-family:Orbitron,monospace;font-size:var(--text-2xs);'
        f'font-weight:700;color:{badge_col}">{badge_text}</span>'
        ' <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:#94A3B8">'
        f'{detail}</span>'
        '</div>'
    )


def _render_ema200_warning(r, lines_out: list) -> None:
    """
    NEW V4: Warning jika EMA200 tidak reliable karena data tidak cukup.
    """
    ema200_reliable = _g(r, "ema200_reliable", True)
    if ema200_reliable is False:
        lines_out.append(
            '<div style="background:rgba(240,180,41,0.06);border:1px solid rgba(240,180,41,0.25);'
            'border-radius:var(--r-sm);padding:0.35rem 0.8rem;margin:0.2rem 0">'
            '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);color:#F0B429">'
            '⚠ EMA200 tidak reliable — data weekly < 100 bars. '
            'Score point "Price > EMA200" mungkin tidak akurat. '
            'Data historis saham ini terbatas di provider.'
            '</span>'
            '</div>'
        )


def _render_ema_detail(r) -> None:
    """EMA detail V4 — dengan MCF bear blocking, risk warning, EMA200 flag."""

    ticker   = _g(r, "ticker","").replace(".JK","")  # noqa: F841
    signal   = _g(r, "signal","")
    cross    = _g(r, "cross_state","")
    close    = _g(r, "close",0)
    vol      = _g(r, "vol_ratio",0)
    score    = _g(r, "score",0)
    regime   = _g(r, "regime_tag","")
    rs       = _g(r, "rs_vs_ihsg_4w",0)
    ema13    = _g(r, "ema13",0)
    ema89    = _g(r, "ema89",0)
    sl       = _g(r, "sl_price",0)
    tp1      = _g(r, "tp1_price",0)
    tp2      = _g(r, "tp2_price",0)
    rr       = _g(r, "rr_ratio",0)
    risk     = _g(r, "risk_pct",0)

    ema_gap_pct  = ((ema13 - ema89) / ema89 * 100) if ema89 > 0 else 0
    pct_vs_ema13 = ((close - ema13) / ema13 * 100) if ema13 > 0 else 0
    pct_vs_ema89 = ((close - ema89) / ema89 * 100) if ema89 > 0 else 0
    ema_crossed  = cross in ("ABOVE", "CROSSING")

    # Pre-build color variables — hindari ternary inline di dalam f-string
    _ema_gap_col    = "#00FF66" if ema_gap_pct > 0 else "#EF4444"
    _ema13_diff_col = "#00FF66" if pct_vs_ema13 > 0 else "#EF4444"

    # ── Market Structure Phase ────────────────────────────────────────────────
    if not ema_crossed:
        phase,phase_col = "BELOW_EMA","#EF4444"
        phase_desc = f"EMA13 Rp{ema13:,.0f} belum melewati EMA89 Rp{ema89:,.0f}. Gap {ema_gap_pct:+.1f}%. Belum ada setup."
    elif cross == "CROSSING":
        phase,phase_col = "GOLDEN_CROSS","#00FF66"
        phase_desc = f"EMA13 baru melewati EMA89 (gap {ema_gap_pct:+.1f}%). Early entry — risiko lebih tinggi tapi potensi besar."
    elif 0 <= pct_vs_ema13 <= 3:
        if vol >= 1.3:
            phase,phase_col = "PULLBACK_TO_EMA_CONFIRMED","#00FF66"
            phase_desc = f"Harga di EMA13 support ({pct_vs_ema13:+.1f}%) + volume naik {vol:.1f}×. Re-entry terbaik dalam uptrend."
        else:
            phase,phase_col = "PULLBACK_TO_EMA_WATCH","#F0B429"
            phase_desc = f"Harga di EMA13 ({pct_vs_ema13:+.1f}%) tapi volume belum konfirmasi ({vol:.1f}×). Tunggu volume ≥1.5×."
    elif -3 <= pct_vs_ema13 < 0:
        if pct_vs_ema89 > 0:
            phase,phase_col = "PULLBACK_BELOW_EMA13","#F0B429"
            phase_desc = f"Harga {pct_vs_ema13:+.1f}% di bawah EMA13 tapi masih di atas EMA89. Trend besar intact — tunggu bounce kembali ke EMA13 Rp{ema13:,.0f}."
        else:
            phase,phase_col = "BELOW_EMA13_AND_EMA89","#EF4444"
            phase_desc = f"Harga {pct_vs_ema13:+.1f}% di bawah EMA13 DAN EMA89. Jangan entry."
    elif 3 < pct_vs_ema13 <= 12:
        if vol >= 3.0:
            phase,phase_col = "BREAKOUT_CONFIRMED","#00FF66"
            phase_desc = f"Harga {pct_vs_ema13:+.1f}% di atas EMA13 + vol {vol:.1f}×. Breakout terkonfirmasi institusi."
        elif vol >= 1.3:
            phase,phase_col = "TREND_WITH_MOMENTUM","#00FF66"
            phase_desc = f"Harga {pct_vs_ema13:+.1f}% di atas EMA13, vol {vol:.1f}×. Uptrend sehat. Entry masih bisa, R/R lebih tipis."
        else:
            phase,phase_col = "TREND_NORMAL","#F0B429"
            phase_desc = f"Harga {pct_vs_ema13:+.1f}% di atas EMA13, vol normal. Tunggu pullback ke EMA13 Rp{ema13:,.0f}."
    elif 12 < pct_vs_ema13 <= 25:
        if vol >= 6.0:
            phase,phase_col = "INSTITUTIONAL_SPIKE","#00FF66"
            phase_desc = f"Harga extended {pct_vs_ema13:+.1f}% + vol EKSTREM {vol:.1f}×. Institutional block buy."
        else:
            phase,phase_col = "EXTENDED_WAIT_PULLBACK","#F0B429"
            phase_desc = f"Harga {pct_vs_ema13:+.1f}% di atas EMA13 — mulai stretched. Tunggu pullback ke EMA13 Rp{ema13:,.0f}."
    elif pct_vs_ema13 > 25:
        if vol >= 6.0:
            phase,phase_col = "BLOWOFF_VOLUME","#F0B429"
            phase_desc = f"Harga {pct_vs_ema13:+.1f}% di atas EMA13 + vol {vol:.1f}×. Potensi climax. Hati-hati."
        else:
            phase,phase_col = "POST_RUN_CORRECTION","#94A3B8"
            phase_desc = f"Harga {pct_vs_ema13:+.1f}% di atas EMA13. Fase koreksi. Jangan kejar."
    elif pct_vs_ema13 < -3:
        if pct_vs_ema89 > 0:
            phase,phase_col = "DEEP_PULLBACK_EMA_INTACT","#F0B429"
            phase_desc = f"Di bawah EMA13 ({pct_vs_ema13:+.1f}%) tapi masih di atas EMA89 ({pct_vs_ema89:+.1f}%). Trend besar masih valid."
        else:
            phase,phase_col = "TREND_BREAK","#EF4444"
            phase_desc = "Di bawah EMA13 DAN EMA89. Trend bullish terancam."
    else:
        phase,phase_col = "WATCH","#64748B"
        phase_desc = "Monitor."

    # ── Verdict ───────────────────────────────────────────────────────────────
    # FIX V4: WATCHLIST_ONLY → verdict override ke BEAR WATCH
    if regime == "WATCHLIST_ONLY":
        v_col,v_bg = "#EF4444","rgba(239,68,68,0.04)"
        verdict    = "⛔ BEAR — WATCH ONLY"
    elif signal in ("BREAKOUT", "STRONG_BREAKOUT") or phase in {"GOLDEN_CROSS","PULLBACK_TO_EMA_CONFIRMED",
                                            "BREAKOUT_CONFIRMED","TREND_WITH_MOMENTUM","INSTITUTIONAL_SPIKE"}:
        v_col,v_bg = "#00FF66","rgba(0,255,102,0.06)"
        verdict    = "ENTRY VALID"
    elif phase in {"PULLBACK_TO_EMA_WATCH","TREND_NORMAL","EXTENDED_WAIT_PULLBACK","DEEP_PULLBACK_EMA_INTACT"}:
        v_col,v_bg = "#F0B429","rgba(240,180,41,0.04)"
        verdict    = "WATCHLIST"
    else:
        v_col,v_bg = "#94A3B8","rgba(100,116,139,0.04)"  # noqa: F841
        verdict    = "WAIT / SKIP"

    # ── Build lines ───────────────────────────────────────────────────────────
    lines_out = []

    # Phase line
    lines_out.append(
        f'<span style="background:{phase_col}18;border:1px solid {phase_col}55;'
        'border-radius:var(--r-sm);padding:2px 8px;font-family:Orbitron,monospace;'
        f'font-size:var(--text-xs);font-weight:700;color:{phase_col}">{phase}</span> '
        f'{phase_desc}'
    )

    # EMA line
    lines_out.append(
        f'<b>EMA:</b> EMA13 <b style="color:#E2E8F0">Rp{ema13:,.0f}</b> · '
        f'EMA89 <b style="color:#94A3B8">Rp{ema89:,.0f}</b> · '
        f'Gap <b style="color:{_ema_gap_col}">{ema_gap_pct:+.1f}%</b> · '
        f'vs EMA13 <b style="color:{_ema13_diff_col}">{pct_vs_ema13:+.1f}%</b>'
    )

    # Volume line
    vol_col = "#00FF66" if vol>=3 else "#F0B429" if vol>=1.3 else "#94A3B8"
    vol_lbl = "EKSTREM" if vol>=6 else "SPIKE" if vol>=3 else "ELEVATED" if vol>=1.3 else "NORMAL"
    # Pre-build color vars untuk volume line
    _score_col  = "#00FF66" if score >= 5 else "#F0B429" if score >= 3 else "#94A3B8"
    _rs_col     = "#00FF66" if rs > 0 else "#EF4444"
    _regime_col = "#EF4444" if regime == "WATCHLIST_ONLY" else "#64748B"

    lines_out.append(
        f'<b>Volume:</b> <b style="color:{vol_col}">{vol:.1f}× — {vol_lbl}</b> · '
        f'Score <b style="color:{_score_col}">{score}/10</b> · '
        f'RS <b style="color:{_rs_col}">{rs:+.1f}%</b>'
        + (f' · Regime <b style="color:{_regime_col}">{regime}</b>' if regime else '')
    )

    # Risk line
    if sl > 0 and tp1 > 0:
        lines_out.append(
            f'<b>Risk:</b> Entry Rp{close:,.0f} · '
            f'SL <b style="color:#EF4444">Rp{sl:,.0f}</b> ({risk:.0f}%) · '
            f'TP1 <b style="color:#00FF66">Rp{tp1:,.0f}</b> · '
            f'TP2 Rp{tp2:,.0f} · R:R {rr:.1f}:1'
        )

    # FIX V4: Risk warning badge
    _render_risk_warning(r, lines_out)

    # FIX V4: EMA200 reliability warning
    _render_ema200_warning(r, lines_out)

    # FIX V4: MCF dengan bear blocking yang benar
    _render_mcf_block(r, lines_out)

    # Dual-timeframe row
    daily_ok      = _g(r, "daily_ok", False)
    daily_pattern = _g(r, "daily_pattern", "")
    daily_note    = _g(r, "daily_entry_note", "")
    ema13d_v      = _g(r, "ema13d", 0)
    ema89d_v      = _g(r, "ema89d", 0)
    ema5d_v       = _g(r, "ema5d", 0)
    pct_ema13d    = _g(r, "pct_vs_ema13d", 0)
    vol_d         = _g(r, "vol_ratio_d", 0)
    dual_ok       = _g(r, "dual_confirmed", False)

    if daily_pattern:
        d_col    = "#00FF66" if daily_ok else "#F0B429" if "WAIT" in daily_pattern else "#94A3B8"
        dual_badge = ('<span style="background:#00FF66;color:#000;font-weight:700;'
                      'font-family:Orbitron,monospace;font-size:var(--text-2xs);border-radius:var(--r-sm);'
                      'padding:1px 7px;margin-right:0.4rem">✦ DUAL CONFIRM</span>' if dual_ok else "")
        ema5_str = f'EMA5d <b style="color:#E2E8F0">Rp{ema5d_v:,.0f}</b> · ' if ema5d_v else ""
        # Pre-build color vars untuk daily line — hindari ternary inline di f-string
        _ema13d_diff_col = "#00FF66" if pct_ema13d >= 0 else "#EF4444"
        _vol_d_col       = "#00FF66" if vol_d >= 1.5 else "#F0B429"
        lines_out.append(
            f'{dual_badge}<b>EMA Daily:</b> {ema5_str}'
            f'EMA13d <b style="color:#E2E8F0">Rp{ema13d_v:,.0f}</b> · '
            f'EMA89d <b style="color:#94A3B8">Rp{ema89d_v:,.0f}</b> · '
            f'vs EMA13d <b style="color:{_ema13d_diff_col}">{pct_ema13d:+.1f}%</b> · '
            f'Vol <b style="color:{_vol_d_col}">{vol_d:.1f}×</b> · '
            f'<b style="color:{d_col}">{daily_pattern}</b>'
            + (f' — {daily_note}' if daily_note else '')
        )

    # Market Structure row
    ms_struct  = _g(r, "ms_structure","")
    ms_age     = _g(r, "ms_age_label","")
    ms_slope   = _g(r, "ms_slope_label","")
    ms_boost   = _g(r, "ms_conviction_boost",0)
    ms_support = _g(r, "ms_nearest_support",0)
    ms_sup_d   = _g(r, "ms_support_dist_pct",0)

    if ms_struct:
        sc = ("#00FF66" if ms_struct in ("HH_HL","TRENDING_UP") else
              "#F0B429" if ms_struct in ("LH_HL","RECOVERING","HH_LL") else
              "#EF4444" if ms_struct in ("LH_LL","TRENDING_DOWN") else "#94A3B8")
        boost_str = (f' <b style="color:#00FF66">+{ms_boost} conv</b>' if ms_boost>0 else
                     f' <b style="color:#EF4444">{ms_boost} conv</b>' if ms_boost<0 else "")
        lines_out.append(
            f'<b>Market Structure:</b> <b style="color:{sc}">{ms_struct}</b>{boost_str} · '
            f'{ms_age} · {ms_slope}'
            + (f' · Support Rp{ms_support:,.0f} ({ms_sup_d:.1f}% away)' if ms_support>0 else '')
        )

    # ── MSCI Alert block ──────────────────────────────────────────────────
    _ticker_upper = _g(r, "ticker","").replace(".JK","").upper()
    _ma = _msci_alerts_by_ticker.get(_ticker_upper)
    if _ma:
        _lv   = _ma.get("alert_level","")
        _t    = _ma.get("t_minus", 0)
        _idx  = _ma.get("index","")
        _eff  = _ma.get("effective_date","")
        _mc   = _ma.get("msci_conviction", 0)
        _note = _ma.get("entry_note","")
        _reasons = _ma.get("reasons", [])

        _lcol = ("#00FF66" if _lv == "HIGH_CONVICTION" else
                 "#F0B429" if _lv == "MEDIUM" else "#60A5FA")
        _lbg  = ("rgba(0,255,102,0.06)" if _lv == "HIGH_CONVICTION" else
                 "rgba(240,180,41,0.05)" if _lv == "MEDIUM" else "rgba(74,158,255,0.04)")
        _reasons_str = " · ".join(_reasons[:4]) if _reasons else ""

        # BUG-07 FIX: Multi-line build — ganti flat single-line concat
        _msci_lines = [
            f'<div style="background:{_lbg};border:1px solid {_lcol}40;'
            'border-radius:var(--r-md);padding:.5rem .8rem;margin:.3rem 0">',
            '<div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.25rem">',
            f'<span style="font-family:Orbitron,monospace;font-size:var(--text-2xs);'
            f'font-weight:800;color:{_lcol}">◈ {_idx}</span>',
            f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
            f'color:{_lcol}">{_lv} · T-{_t} · Conv {_mc}/12</span>',
            f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
            f'color:#64748B">Eff: {_eff}</span>',
            '</div>',
            f'<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            f'color:#94A3B8">{_reasons_str}</div>',
            f'<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
            f'color:{_lcol};margin-top:.2rem">{_note}</div>',
            '</div>',
        ]
        lines_out.append("".join(_msci_lines))

    # Action
    if regime == "WATCHLIST_ONLY":
        action = ("<b>⛔ BEAR REGIME — JANGAN ENTRY.</b> "
                  "EMA system mendeteksi WATCHLIST_ONLY. "
                  "Simpan di watchlist. Entry hanya setelah regime berubah ke FULL.")
    elif phase == "POST_RUN_CORRECTION":
        action = f"<b>FASE KOREKSI — JANGAN BELI.</b> Tunggu test EMA13 Rp{ema13:,.0f} + vol naik."
    elif phase == "PULLBACK_TO_EMA_CONFIRMED":
        action = f"<b>RE-ENTRY SEKARANG.</b> EMA13 Rp{ema13:,.0f} support + vol konfirmasi. SL di bawah EMA89 Rp{ema89*0.97:,.0f}."
    elif phase in ("BREAKOUT_CONFIRMED","TREND_WITH_MOMENTUM","GOLDEN_CROSS"):
        action = ("<b>ENTRY VALID.</b> "
                  + (f"Entry Rp{close:,.0f}, SL Rp{sl:,.0f} ({risk:.0f}%), TP1 Rp{tp1:,.0f}."
                     if sl>0 and tp1>0 else
                     f"Entry Rp{close:,.0f}, SL di EMA13 Rp{ema13*0.97:,.0f}."))
    elif phase == "PULLBACK_TO_EMA_WATCH":
        action = f"<b>HAMPIR — TUNGGU VOL.</b> Harga di EMA13 tapi vol {vol:.1f}×. Alert kalau vol ≥1.5×."
    elif phase == "EXTENDED_WAIT_PULLBACK":
        action = f"<b>TUNGGU PULLBACK.</b> Entry terbaik di EMA13 Rp{ema13:,.0f}–{ema13*1.04:,.0f}."
    elif phase == "BELOW_EMA":
        action = f"<b>BELUM SETUP.</b> EMA13 Rp{ema13:,.0f} belum melewati EMA89 Rp{ema89:,.0f}."
    else:
        action = f"<b>MONITOR.</b> Score {score}/10."  # noqa: F841

    # Render
    rows_html = "".join([  # noqa: F841
        f'<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);'
        f'color:#94A3B8;line-height:2.1;padding:2px 0 2px var(--sp-3);'
        f'border-left:2px solid rgba(255,255,255,0.04)">{ln}</div>'
        for ln in lines_out
    ])

    # Build card via string concat — rows_html dan action tidak masuk f-string
    _card_header = (
        '<div style="background:' + v_bg + ';border:1px solid rgba(255,255,255,0.08);'
        'border-left:4px solid ' + v_col + ';border-radius:var(--r-md);padding:0.9rem 1.1rem;margin:0.3rem 0 0.8rem 0">'
        '<div style="display:flex;align-items:center;gap:0.8rem;margin-bottom:0.6rem;'
        'padding-bottom:0.5rem;border-bottom:1px solid rgba(255,255,255,0.05)">'
        '<span style="font-family:Orbitron,monospace;font-size:var(--text-lg);font-weight:900;'
        'color:#E2E8F0">' + ticker + '</span>'
        '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
        'color:#374151">EMA-XBO · Score ' + str(score) + '/10 · Vol ' + f"{vol:.1f}" + '×</span>'
        '<span style="background:' + v_col + '18;border:1px solid ' + v_col + '45;border-radius:var(--r-sm);'
        'padding:2px 10px;font-family:Orbitron,monospace;font-size:var(--text-xs);'
        'font-weight:700;color:' + v_col + ';margin-left:auto">' + verdict + '</span>'
        '</div>'
    )
    _card_action = (
        '<div style="background:rgba(0,0,0,0.25);border:1px solid ' + phase_col + '30;'
        'border-radius:var(--r-sm);padding:0.55rem 0.9rem;margin-top:0.6rem;'
        'font-family:Share Tech Mono,monospace;font-size:var(--text-sm);'
        'color:#E2E8F0;line-height:1.8">'
        '<span style="color:' + phase_col + ';font-weight:700">→ </span>'
        + action +
        '</div></div>'
    )
    st.markdown(_card_header + rows_html + _card_action, unsafe_allow_html=True)



# ─────────────────────────────────────────────────────────────────────────────
# Main page layout (simplified — integrasi dengan existing page)
# ─────────────────────────────────────────────────────────────────────────────

st.markdown(get_page_css("dashboard"), unsafe_allow_html=True)

LOGS_DIR     = Path(__file__).parent.parent / "logs"
RESULTS_FILE = LOGS_DIR / "daily_results.json"
PLAYBOOK     = LOGS_DIR / "edge_playbook.md"

# MSCI alert status
_msci_status = {}
try:
    _mf = LOGS_DIR / "msci_alerts.json"
    if _mf.exists():
        _msci_status = json.loads(_mf.read_text(encoding="utf-8"))
except Exception as _e:
    import logging as _log; _log.getLogger(__name__).debug(f"[EMA_XBO] msci_alerts.json load: {_e}")
_msci_alerts_by_ticker = {
    a["ticker"].upper(): a
    for a in _msci_status.get("alerts", [])
}
_msci_active_events = _msci_status.get("active_events", [])

last = {}
if RESULTS_FILE.exists():
    try: last = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    except Exception as _e:
        import logging as _log; _log.getLogger(__name__).debug(f"[EMA_XBO] results.json load: {_e}")

ema_results = last.get("ema_results", [])
regime      = last.get("regime", {})
scan_date   = last.get("date", "—")[:10] if last.get("date") else "—"

cycle   = regime.get("cycle", "—")
ihsg    = regime.get("ihsg", 0)
mom_4w      = regime.get("mom_4w", 0)
mom_2w      = regime.get("mom_2w", 0)
pct_from_low= regime.get("pct_from_low", 0)
breadth = regime.get("breadth", 0)

# Sidebar
with st.sidebar:
    render_sidebar("ema",
                   ema_total   = last.get("ema_total", len(ema_results)),
                   whale_total = last.get("whale_total", 0),
                   scan_date   = scan_date,
                   regime      = cycle)

    # NEW V4: Mini performance tracker di sidebar
    try:
        from trade_logger import get_stats
        stats = get_stats()
        n = stats.get("total_closed", 0)
        wr = stats.get("win_rate")
        st.markdown("---")
        _span_col = '#00FF66' if n>=30 else '#F0B429' if n>0 else '#EF4444'
        _wr_str   = f' &middot; WR {wr:.0f}%' if wr is not None else ' &middot; WR N/A'
        st.markdown(
            f'<div style="font-family:Share Tech Mono,monospace;font-size:12px;color:#374151">'
            f'OUTCOME TRACKER<br>'
            f'<span style="color:{_span_col};font-size:14px">{n}/30 closed</span>'
            f'{_wr_str}</div>',
            unsafe_allow_html=True
        )
    except Exception:
        pass

    # Modal size input untuk risk calculator
    st.markdown("---")
    st.markdown(
        '<div style="font-family:Share Tech Mono,monospace;font-size:11px;color:#374151;margin-bottom:4px">'
        'MODAL SIZE (RISK CALC)</div>',
        unsafe_allow_html=True
    )
    _modal_input = st.number_input(
        "Modal (Rp juta)",
        min_value=10, max_value=10000,
        value=int(st.session_state.get("modal_size", 100_000_000) / 1_000_000),
        step=10, key="modal_input_jt",
        label_visibility="collapsed",
        help="Modal aktif untuk kalkulasi max lot di risk warning. Default 100jt."
    )
    st.session_state["modal_size"] = _modal_input * 1_000_000

# Page header
import json as _jv, pathlib as _pv
try:
    _ver_accent = "V" + _jv.loads((_pv.Path(__file__).parent.parent/"version.json").read_text())["version"].split(".")[0]
except Exception:
    _ver_accent = "V9"

render_page_header(
    eyebrow  = "◆ MODULE 01 · BREAKOUT DETECTION",
    title    = "SIMPLE TRADING ",
    accent   = _ver_accent,
    subtitle = "◈ EMA-XBO SCANNER · ATR DYNAMIC BOX · RS FILTER · MCF BEAR-SAFE",
    scan_date= scan_date,
)

render_regime_bar(cycle, ihsg, mom_4w, breadth, scan_date, mom_2w=mom_2w, pct_from_low=pct_from_low)

# ── DATE GUARD — stale data warning ──────────────────────────────────────────
_today_str = datetime.now().strftime("%Y-%m-%d")
_is_weekend = datetime.now().weekday() >= 5  # Sabtu=5, Minggu=6
if scan_date and scan_date != "—":
    _scan_dt   = None
    try:
        from datetime import datetime as _dtparse
        _scan_dt = _dtparse.strptime(scan_date, "%Y-%m-%d")
    except Exception:
        pass
    if _scan_dt:
        _days_old  = (datetime.now() - _scan_dt).days
        _stale     = _days_old >= 1 and not _is_weekend
        _very_stale = _days_old >= 3
        if _very_stale:
            _stale_bg  = "rgba(239,68,68,0.10)"
            _stale_bdr = "rgba(239,68,68,0.45)"
            _stale_ico = "⛔"
            _stale_col = "#EF4444"
            _stale_msg = f"Data scan sudah <b>{_days_old} hari</b> yang lalu. Sinyal ini TIDAK mencerminkan kondisi pasar hari ini."
        elif _stale:
            _stale_bg  = "rgba(240,180,41,0.08)"
            _stale_bdr = "rgba(240,180,41,0.40)"
            _stale_ico = "⚠"
            _stale_col = "#F0B429"
            _stale_msg = f"Data scan dari <b>{scan_date}</b> — bukan hari ini. Jalankan scan ulang untuk sinyal terkini."
        else:
            _stale     = False
        if _stale or _very_stale:
            st.markdown(
                f'<div style="background:{_stale_bg};border:1px solid {_stale_bdr};'
                f'border-left:4px solid {_stale_col};border-radius:6px;'
                f'padding:0.65rem 1rem;margin:0.5rem 0 0.8rem 0">'
                f'<span style="font-family:Orbitron,monospace;font-size:11px;'
                f'font-weight:800;color:{_stale_col}">{_stale_ico} DATA STALE — {scan_date}</span>'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:11px;'
                f'color:#94A3B8;margin-left:1rem">{_stale_msg}</span>'
                f'</div>',
                unsafe_allow_html=True
            )

# Summary metrics
breakouts  = [r for r in ema_results if r.get("signal") in ("STRONG_BREAKOUT","BREAKOUT")]
watchlists = [r for r in ema_results if r.get("signal") == "WATCHLIST"]
correcting = [r for r in ema_results if r.get("signal") in ("CORRECTING","DEEP_CORRECT")]
compressing = [r for r in ema_results if r.get("signal") == "COMPRESSING"]
universe   = last.get("universe", len(ema_results))

bear_blocked_count = sum(1 for r in ema_results if r.get("mcf_bear_blocked"))
mcf_join    = [r for r in ema_results if r.get("mcf_label") == "JOIN" and not r.get("mcf_bear_blocked")]

# ── Cross-state audit — data untuk keputusan Sesi 2 (hard gate EMA cross) ────
_cross_above  = sum(1 for r in ema_results if r.get("cross_state") == "ABOVE")
_cross_below  = sum(1 for r in ema_results if r.get("cross_state") == "BELOW")
_cross_cross  = sum(1 for r in ema_results if r.get("cross_state") == "CROSSING")
# Sinyal actionable (BREAKOUT/WATCHLIST) yang cross_state bukan ABOVE
_actionable_no_cross = [
    r for r in ema_results
    if r.get("signal") in ("STRONG_BREAKOUT", "BREAKOUT", "WATCHLIST")
    and r.get("cross_state") != "ABOVE"
]

c1,c2,c3,c4,c5,c6,c7 = st.columns(7)
metrics = [
    (c1, "TOTAL SETUPS",   len(ema_results),    "#E2E8F0", "SCANNED TODAY"),
    (c2, "◉ BREAKOUTS",    len(breakouts),      NEON_GREEN,"HIGH CONVICTION"),
    (c3, "◎ WATCHLIST",    len(watchlists),     "#F0B429", "MONITORING"),
    (c4, "◌ CORRECTING",   len(correcting),     "#F0B429", "PULLBACK"),
    (c5, "◈ MCF JOIN",     len(mcf_join),       NEON_GREEN,"VALID (non-bear)"),
    (c6, "⛔ BEAR BLOCKED", bear_blocked_count,  "#EF4444", "MCF overridden"),
    (c7, "UNIVERSE",       universe,            "#E2E8F0", "STOCKS"),
]
for col, label, val, color, sub in metrics:
    with col:
        st.markdown(f"""
        <div class="m-card">
          <div class="m-lbl">{label}</div>
          <div class="m-val" style="color:{color}">{val}</div>
          <div class="m-sub">{sub}</div>
        </div>""", unsafe_allow_html=True)

# ── Cross-state audit expander ────────────────────────────────────────────────
if ema_results:
    _pct_above = round(_cross_above / len(ema_results) * 100) if ema_results else 0
    with st.expander(
        f"◈ AUDIT: {_cross_above}/{len(ema_results)} ticker sudah EMA cross ABOVE "
        f"({_pct_above}%) — {len(_actionable_no_cross)} actionable tanpa cross",
        expanded=False
    ):
        _a1, _a2, _a3, _a4 = st.columns(4)
        _a1.metric("CROSS ABOVE", _cross_above, help="EMA13 > EMA89")
        _a2.metric("CROSSING", _cross_cross, help="EMA13 ≈ EMA89 (gap <1%)")
        _a3.metric("BELOW", _cross_below, help="EMA13 < EMA89")
        _a4.metric("COMPRESSING", len(compressing), help="BELOW tapi gap menyempit ≥25%")
        if _actionable_no_cross:
            st.markdown(
                '<div style="font-family:Share Tech Mono,monospace;font-size:11px;'
                'color:#F0B429;margin-top:0.5rem">'
                f'⚠ {len(_actionable_no_cross)} ticker dengan signal BREAKOUT/WATCHLIST '
                f'tapi cross_state bukan ABOVE — akan hilang jika hard gate aktif di Sesi 2:'
                '</div>',
                unsafe_allow_html=True
            )
            _audit_rows = [
                {"Ticker": r.get("ticker","").replace(".JK",""),
                 "Signal": r.get("signal",""),
                 "Cross": r.get("cross_state",""),
                 "Score": r.get("score",0)}
                for r in _actionable_no_cross
            ]
            st.dataframe(_audit_rows, use_container_width=True, hide_index=True)
        else:
            st.success("✅ Semua sinyal actionable sudah cross ABOVE — hard gate aman diterapkan.")

# Run Scan
sec_head("◆ SCAN CONTROLS")
cb, ci = st.columns([1, 3])
with cb:
    run_scan = st.button("⟳ RUN NEW SCAN", type="primary", width="stretch")
with ci:
    st.markdown("""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
    letter-spacing:0.1em;color:#64748B;margin-top:0.65rem;line-height:1.7">
    Full two-tier EMA scan · IDX universe · ~3-5 min · Auto-save<br>
    <span style="color:#374151">V4: EWM optimized · MCF bear-safe · EMA200 3y data · Risk warnings</span>
    </p>""", unsafe_allow_html=True)

if run_scan:
    # ── Progress UI untuk long-running scan ──────────────────────────────────
    from agents.scanner_agent import ScannerAgent
    from config.strategy_config import StrategyConfig
    from core.data_feed import get_ihsg_regime

    # Cek apakah ada checkpoint hari ini (resume)
    import json as _json
    from pathlib import Path as _Path
    from datetime import datetime as _dt
    _ckpt_file  = _Path("logs/scan_checkpoint.json")
    _ckpt       = {}
    _is_resume  = False
    if _ckpt_file.exists():
        try:
            _ckpt = _json.loads(_ckpt_file.read_text(encoding="utf-8"))
            if _ckpt.get("date") == _dt.now().strftime("%Y-%m-%d") and _ckpt.get("status") == "in_progress":
                _is_resume = True
        except Exception:
            pass

    _resume_label = " (RESUME)" if _is_resume else ""
    st.info(
        f"◈ **SCANNING IDX UNIVERSE{_resume_label}** — ~179 ticker · "
        "Rate-limit safe mode · **Jangan tutup atau refresh tab ini.**",
        icon="⏳"
    )

    # Progress bar + status placeholder
    _prog_bar  = st.progress(0, text="Memulai scan...")
    _prog_text = st.empty()

    try:
        cfg     = StrategyConfig.load()
        scanner = ScannerAgent(cfg)

        def _on_progress(done: int, total: int, ticker: str, found: int):
            pct  = done / total if total > 0 else 0
            eta_s = int((total - done) * 4)  # estimasi 4 detik per ticker
            eta_m = eta_s // 60
            eta_s = eta_s % 60
            _prog_bar.progress(
                pct,
                text=f"◈ {done}/{total} — {ticker} — {found} signal ditemukan"
            )
            _prog_text.markdown(
                f"<span style='font-family:monospace;font-size:0.8rem;color:#94A3B8'>"
                f"Selesai: **{done}** / {total} ticker · "
                f"Signal: **{found}** · "
                f"ETA: ~{eta_m}m {eta_s:02d}s"
                f"</span>",
                unsafe_allow_html=True,
            )

        results = scanner.daily_scan(progress_cb=_on_progress)
        _prog_bar.progress(1.0, text="✓ Scan selesai!")
        _prog_text.empty()
        regime_ = get_ihsg_regime()
        # Merge: preserve whale_results dari scan sebelumnya
        existing = {}
        if RESULTS_FILE.exists():
            try: existing = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
            except Exception: pass
        existing.update({
            "date":        datetime.now().strftime("%Y-%m-%d"),
            "scan_date":   datetime.now().strftime("%Y-%m-%d"),
            "regime":      regime_,
            "ema_total":   len(results),
            "universe":    len(results),
            "ema_results": results,
        })
        # Preserve whale keys if not updated this session
        existing.setdefault("whale_results", [])
        existing.setdefault("whale_total", 0)
        existing.setdefault("whale_context", {})
        RESULTS_FILE.write_text(json.dumps(existing, default=str, indent=2), encoding="utf-8")
        st.success(f"✅ Scan selesai: {len(results)} setups ditemukan.")
        st.rerun()
    except Exception as e:
        st.error(f"Error: {e}")
        import traceback; traceback.print_exc()

# Results
if ema_results:
    # ── MSCI Active Window Banner ──────────────────────────────────────────
    if _msci_active_events:
        _msci_high = [a for a in _msci_status.get("alerts",[])
                      if a.get("alert_level") == "HIGH_CONVICTION"]
        for _ev in _msci_active_events:
            _t    = _ev.get("t_minus", 0)
            _idx  = _ev.get("index","")
            _eff  = _ev.get("effective_date","")
            _ph   = _ev.get("phase","")
            _pcol = "#EF4444" if _ph=="CRITICAL" else "#F0B429" if _ph=="ACTIVE" else "#60A5FA"
            _pbg  = ("rgba(239,68,68,0.08)" if _ph=="CRITICAL" else
                     "rgba(240,180,41,0.08)" if _ph=="ACTIVE" else "rgba(74,158,255,0.06)")
            _high_str = ""
            if _msci_high:
                _high_tickers = " · ".join(
                    f"{a['ticker']} ({a['whale_quality']} {a['msci_conviction']}/12)"
                    for a in _msci_high[:5]
                )
                _high_str = ('<div style="font-family:Share Tech Mono,monospace;'
                             'font-size:var(--text-xs);color:#00FF66;margin-top:.25rem">'
                             f'★ HIGH CONVICTION: {_high_tickers}</div>')
            # Build via string concat — _high_str tidak masuk f-string
            _msci_banner = (
                '<div style="background:' + _pbg + ';border:1px solid ' + _pcol + '55;border-left:4px solid ' + _pcol + ';'
                'border-radius:var(--r-md);padding:.7rem 1rem;margin:.5rem 0">'
                '<div style="display:flex;align-items:center;gap:.8rem;flex-wrap:wrap">'
                '<span style="font-family:Orbitron,monospace;font-size:var(--text-xs);font-weight:800;'
                'color:' + _pcol + '">◈ ' + _idx + ' REBALANCING WINDOW</span>'
                '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:' + _pcol + '">'
                'T-' + str(_t) + ' HARI · EFFECTIVE ' + _eff + ' · ' + _ph + '</span>'
                '<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:#64748B">'
                + str(len(_msci_high)) + ' high conviction alerts</span>'
                '</div>'
                + _high_str +
                '</div>'
            )
            st.markdown(_msci_banner, unsafe_allow_html=True)

    # Show bear market notice
    if cycle in ("BEAR_TREND", "WATCHLIST_ONLY"):
        st.markdown("""<div style="background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.4);
        border-left:4px solid #EF4444;border-radius:var(--r-md);padding:0.8rem 1rem;margin:1rem 0">
        <span style="font-family:Orbitron,monospace;font-size:var(--text-xs);font-weight:800;color:#EF4444">
        ⛔ BEAR REGIME AKTIF</span><br>
        <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:#94A3B8">
        Regime WATCHLIST_ONLY: EMA system melarang semua entry. Semua sinyal MCF JOIN
        otomatis di-block. Gunakan waktu ini untuk mempersiapkan watchlist saja.
        </span></div>""", unsafe_allow_html=True)

    # Breakouts section
    if breakouts:
        n_strong = sum(1 for r in breakouts if r.get("signal")=="STRONG_BREAKOUT")
        n_normal = sum(1 for r in breakouts if r.get("signal")=="BREAKOUT")
        _bo_lbl = f"◉ BREAKOUT SIGNALS — {len(breakouts)} total"
        if n_strong: _bo_lbl += f" ({n_strong} STRONG)"
        sec_head(_bo_lbl)

        # P01-A: Min score filter + copy tickers
        _bh1, _bh2, _bh3 = st.columns([1, 1, 2])
        with _bh1:
            _bo_min_score = st.slider("Min Score", 1, 10, 3, key="bo_min_score",
                                      help="Filter breakout berdasarkan minimum score")
        with _bh2:
            _bo_max_risk = st.slider("Max Risk %", 5, 50, 30, 5, key="bo_max_risk",
                                     help="Filter breakout berdasarkan maximum risk %")
        with _bh3:
            _bo_filtered = [r for r in breakouts
                            if r.get("score", 0) >= _bo_min_score
                            and r.get("risk_pct", 0) <= _bo_max_risk]
            _bo_hidden   = len(breakouts) - len(_bo_filtered)
            _tickers_str = ", ".join(r.get("ticker","").replace(".JK","") for r in _bo_filtered)
            _copy_lbl    = f"📋 COPY {len(_bo_filtered)} TICKERS"
            if _bo_hidden:
                st.markdown(f'<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
                            f'color:var(--text-muted);margin-top:1.6rem">'
                            f'{len(_bo_filtered)} shown · {_bo_hidden} filtered</p>',
                            unsafe_allow_html=True)
            if st.button(_copy_lbl, key="bo_copy_tickers"):
                st.code(_tickers_str)

        for r in _bo_filtered:
            ticker = r.get("ticker","").replace(".JK","")
            score  = r.get("score",0)
            vol    = r.get("vol_ratio",0)
            risk   = r.get("risk_pct",0)
            mcf_lbl = r.get("mcf_label","")
            regime_tag = r.get("regime_tag","")

            # Risk warning color for card border — computed in _border_col below
            risk_badge = ""
            if risk > 25:
                risk_badge = f'<span style="background:rgba(239,68,68,0.15);color:#EF4444;border:1px solid #EF444455;border-radius:4px;padding:1px 6px;font-size:11px;margin-left:0.4rem">&#9888; RISK {risk:.0f}%</span>'
            elif risk > 15:
                risk_badge = f'<span style="background:rgba(240,180,41,0.15);color:#F0B429;border:1px solid #F0B42955;border-radius:4px;padding:1px 6px;font-size:11px;margin-left:0.4rem">&#9888; RISK {risk:.0f}%</span>'

            _sig       = r.get("signal", "BREAKOUT")
            _vp        = r.get("vp_entry_zone", "")
            _dual      = r.get("dual_confirmed", False)
            _is_strong = _sig == "STRONG_BREAKOUT"
            _sig_col   = SIG_COLORS.get(_sig, "#00FF66")
            # BUG-04 FIX: STRONG_BREAKOUT gets thicker border + distinct styling
            _border_col   = "#00FF66" if risk <= 15 else "#F0B429" if risk <= 25 else "#EF4444"
            _border_width = "3px" if _is_strong else "1px"
            _card_bg      = "rgba(0,255,102,0.03)" if _is_strong else "#0F1318"
            _strong_label = (
                '<span style="background:#00FF66;color:#000;font-family:Orbitron,monospace;'
                'font-size:10px;font-weight:900;border-radius:3px;padding:1px 7px;'
                'letter-spacing:0.12em;margin-right:0.3rem">STRONG</span>'
                if _is_strong else ""
            )

            # Pre-build all badge strings
            _sig_badge   = signal_badge(_sig)
            _score_badge = score_badge(score)
            _vp_badge    = vp_zone_pill(_vp)
            _dual_tag    = '<span style="background:rgba(0,255,102,0.08);border:1px solid rgba(0,255,102,0.2);border-radius:4px;padding:1px 6px;font-family:Share Tech Mono,monospace;font-size:11px;color:#00FF66">&#10003; DUAL</span>' if _dual else ""

            # Build complete card HTML as single string
            _card_html = (
                f'<div style="background:{_card_bg};border:{_border_width} solid rgba(255,255,255,0.06);'
                f'border-left:{_border_width} solid {_border_col};border-radius:8px;'
                f'padding:0.6rem 0.8rem;margin-bottom:4px">'
                f'<div style="display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap">'
                f'{_strong_label}'
                f'<span style="font-family:Orbitron,monospace;font-size:18px;font-weight:900;color:#E2E8F0;letter-spacing:0.03em">{ticker}</span>'
                f'{_sig_badge}'
                f'{_score_badge}'
                f'{_vp_badge}'
                f'{_dual_tag}'
                f'{risk_badge}'
                f'<span style="margin-left:auto;font-family:Share Tech Mono,monospace;font-size:12px;color:#64748B">Vol {vol:.1f}&#215; &#183; Risk {risk:.0f}%</span>'
                f'</div>'
                f'</div>'
            )

            # Single column layout — button below card, no column split
            st.markdown(_card_html, unsafe_allow_html=True)
            if "open_breakouts" not in st.session_state:
                st.session_state.open_breakouts = set()
            is_open = ticker in st.session_state.open_breakouts
            lbl = "▾ HIDE" if is_open else "▸ SHOW"
            if st.button(lbl, key=f"bo_{ticker}"):
                if is_open:
                    st.session_state.open_breakouts.discard(ticker)
                else:
                    st.session_state.open_breakouts.add(ticker)
                st.rerun()

            if is_open:
                _render_ema_detail(r)

            # P01-B: Inline outcome logging — satu klik dari breakout card
            with st.expander(f"📝 LOG TRADE — {ticker}", expanded=False):
                _oc1, _oc2, _oc3, _oc4, _oc5 = st.columns(5)
                with _oc1:
                    _log_entry = st.number_input("Entry Price", value=float(r.get("close", 0)),
                                                  step=10.0, key=f"log_entry_{ticker}")
                with _oc2:
                    _log_sl = st.number_input("SL Price", value=float(r.get("sl_price", 0)),
                                               step=10.0, key=f"log_sl_{ticker}")
                with _oc3:
                    _log_entry_date = st.date_input("Tanggal Entry", value=date.today(),
                                                     max_value=date.today(),
                                                     key=f"log_edate_{ticker}")
                with _oc4:
                    _log_outcome = st.selectbox("Outcome", ["OPEN", "WIN", "LOSS", "BREAKEVEN"],
                                                 key=f"log_out_{ticker}")
                with _oc5:
                    _log_exit = st.number_input("Exit Price (0=skip)", value=0.0,
                                                 step=10.0, key=f"log_exit_{ticker}")
                _log_notes = st.text_input("Notes (opsional)", key=f"log_note_{ticker}",
                                            placeholder="contoh: TP1 hit, exit manual")
                # P01-X2: quick pre-flight gate sebelum simpan
                # Pakai data yang sudah ada dari result dict (r)
                _pf_quick_regime = r.get("regime_tag","") not in ("BEAR_TREND","WATCHLIST_ONLY","BEAR_WEAK")
                _pf_quick_score  = int(r.get("score",0)) >= 5
                _pf_quick_risk   = float(r.get("risk_pct",0)) <= 25
                _pf_quick_pass   = _pf_quick_regime and _pf_quick_score and _pf_quick_risk
                _pf_quick_fails  = []
                if not _pf_quick_regime: _pf_quick_fails.append(f"Regime={r.get('regime_tag','?')}")
                if not _pf_quick_score:  _pf_quick_fails.append(f"Score={r.get('score',0)}/10 (<5)")
                if not _pf_quick_risk:   _pf_quick_fails.append(f"Risk={r.get('risk_pct',0):.0f}% (>25%)")

                if not _pf_quick_pass:
                    st.warning(f"⚠ Pre-flight: {' · '.join(_pf_quick_fails)} — override di Page 04 untuk analisis lengkap")

                _save_lbl = "💾 SIMPAN TRADE" if _pf_quick_pass else "⚠ SIMPAN (ada warning)"
                if st.button(_save_lbl, key=f"log_save_{ticker}",
                             type="primary" if _pf_quick_pass else "secondary"):
                    try:
                        from trade_logger import log_trade, close_trade
                        # P01-W1 fix: pass tp1_price agar War Room bisa hitung pct_to_tp1
                        _tp1_val = _log_exit if _log_outcome == "OPEN" and _log_exit > 0 else 0.0
                        _tid = log_trade(
                            ticker       = ticker,
                            entry_price  = _log_entry,
                            sl_price     = _log_sl,
                            tp1_price    = _tp1_val,
                            entry_date   = _log_entry_date.strftime("%Y-%m-%d"),
                            signal_type  = r.get("signal", "BREAKOUT"),
                            signal_score = int(r.get("score", 0)),
                            regime_tag   = r.get("regime_tag", ""),
                            mcf_score    = int(r.get("mcf_score", 0)),
                            notes        = _log_notes,
                        )
                        if _log_outcome != "OPEN" and _log_exit > 0:
                            close_trade(_tid, _log_exit, _log_outcome, _log_notes)
                        st.success(f"✅ Trade {ticker} tersimpan (ID #{_tid}) — outcome: {_log_outcome}")
                    except Exception as _le:
                        st.error(f"Error log trade: {_le}")

    # ── ALL SETUPS with filter controls ──────────────────────────────────────
    rest = [r for r in ema_results if r.get("signal") not in ("BREAKOUT", "STRONG_BREAKOUT")]
    if rest:
        sec_head("◆ ALL SETUPS")

        # ── FILTER CONTROLS ────────────────────────────────────────────────────
        # PENTING: Apply preset SEBELUM widget di-buat.
        # Streamlit melarang set session_state[widget_key] setelah widget rendered.
        # Pattern: tombol → set f_preset → rerun → apply f_preset → buat widget.
        _preset = st.session_state.pop("f_preset", None)
        if _preset == "safe":
            st.session_state["f_risk"]  = 15
            st.session_state["f_score"] = 1
        elif _preset == "high_score":
            st.session_state["f_score"] = 5
            st.session_state["f_risk"]  = 50
        elif _preset == "correcting":
            st.session_state["f_sig"]   = ["CORRECTING"]
        elif _preset == "reset":
            for _k in ("f_score", "f_risk", "f_sig", "f_sort"):
                st.session_state.pop(_k, None)

        # rs_pos dan mcf_ok adalah toggle non-widget, bisa di-set kapanpun
        rs_pos_only = st.session_state.pop("f_rs_pos", False)
        mcf_ok_only = st.session_state.pop("f_mcf_ok", False)
        # P01-X3: RS minimum threshold — bukan hanya binary > 0
        _rs_min = st.session_state.get("f_rs_min", 0.0)

        with st.container():
            st.markdown("""<div style="font-family:Share Tech Mono,monospace;
            font-size:var(--text-2xs);letter-spacing:.15em;color:#374151;
            margin-bottom:.4rem">◆ FILTER CONTROLS</div>""",
            unsafe_allow_html=True)

            fc1, fc2, fc3, fc4 = st.columns(4)

            with fc1:
                sig_filter = st.multiselect(
                    "Signal Type",
                    ["WATCHLIST", "CORRECTING", "DEEP_CORRECT"],
                    default=st.session_state.get("f_sig",
                        ["WATCHLIST","CORRECTING","DEEP_CORRECT"]),
                    key="f_sig",
                    label_visibility="collapsed",
                )
            with fc2:
                min_score = st.slider(
                    "Min Score", min_value=1, max_value=10,
                    value=st.session_state.get("f_score", 1),
                    key="f_score", label_visibility="collapsed",
                    help="Min Score (1–7)",
                )
            with fc3:
                max_risk = st.slider(
                    "Max Risk %", min_value=5, max_value=50,
                    value=st.session_state.get("f_risk", 50),
                    step=5, key="f_risk", label_visibility="collapsed",
                    help="Max Risk % per trade",
                )
            with fc4:
                sort_col = st.selectbox(
                    "Sort by",
                    ["Score ↓","RS% ↓","MCF ↓","Risk% ↑","Vol× ↓"],
                    key="f_sort", label_visibility="collapsed",
                )

        # Quick filter buttons — hanya set f_preset, TIDAK set widget key langsung
        qf1, qf2, qf3, qf4, qf5, qf_reset = st.columns(6)
        with qf1:
            if st.button("🟢 SAFE (<15%R)", key="qf_safe"):
                st.session_state["f_preset"] = "safe"
                st.rerun()
        with qf2:
            if st.button("⭐ HIGH SCORE (≥5)", key="qf_hs"):
                st.session_state["f_preset"] = "high_score"
                st.rerun()
        with qf3:
            if st.button("📈 RS POSITIVE", key="qf_rs"):
                st.session_state["f_rs_pos"] = True
                st.rerun()
        with qf4:
            if st.button("◈ MCF JOIN/WAIT", key="qf_mc"):
                st.session_state["f_mcf_ok"] = True
                st.rerun()
        with qf5:
            if st.button("◌ CORRECTING only", key="qf_corr"):
                st.session_state["f_preset"] = "correcting"
                st.rerun()
        with qf_reset:
            if st.button("✕ RESET", key="qf_reset"):
                st.session_state["f_preset"] = "reset"
                st.rerun()

        # ── Apply filters ───────────────────────────────────────────────────────
        sig_filter_val = st.session_state.get("f_sig", ["WATCHLIST","CORRECTING","DEEP_CORRECT"])
        min_score_val  = st.session_state.get("f_score", 1)
        max_risk_val   = st.session_state.get("f_risk", 50)

        filtered = rest
        filtered = [r for r in filtered if r.get("signal","") in sig_filter_val]
        filtered = [r for r in filtered if r.get("score", 0) >= min_score_val]
        filtered = [r for r in filtered if r.get("risk_pct", 0) <= max_risk_val]
        if rs_pos_only:
            # P01-X3: minimum RS threshold — bukan hanya > 0
            filtered = [r for r in filtered if r.get("rs_vs_ihsg_4w", 0) >= _rs_min]
        if mcf_ok_only:
            filtered = [r for r in filtered if r.get("mcf_label","") in ("JOIN","WAIT")]

        # Sort
        sort_map = {
            "Score ↓":  lambda r: -r.get("score", 0),
            "RS% ↓":    lambda r: -r.get("rs_vs_ihsg_4w", 0),
            "MCF ↓":    lambda r: -r.get("mcf_score", 0),
            "Risk% ↑":  lambda r:  r.get("risk_pct", 0),
            "Vol× ↓":   lambda r: -r.get("vol_ratio", 0),
        }
        sort_key = st.session_state.get("f_sort", "Score ↓")
        # P01-X3: RS min threshold slider — hanya tampil jika RS filter aktif
        if rs_pos_only:
            _rs_min_new = st.slider("Min RS% vs IHSG", 0.0, 20.0,
                                    float(st.session_state.get("f_rs_min", 0.0)),
                                    0.5, key="rs_min_slider",
                                    help="Hanya tampilkan saham dengan RS ≥ X% vs IHSG 4W")
            st.session_state["f_rs_min"] = _rs_min_new
            _rs_min = _rs_min_new
            filtered = [r for r in filtered if r.get("rs_vs_ihsg_4w", 0) >= _rs_min]
        filtered.sort(key=sort_map.get(sort_key, sort_map["Score ↓"]))

        # Filter stats
        hidden = len(rest) - len(filtered)
        _hidden_html = f'<span style="color:#F0B429">{hidden} tersembunyi oleh filter</span>' if hidden else ''
        _sep = ' &middot; ' if hidden else ''
        _stats_html = (
            f'<div style="font-family:Share Tech Mono,monospace;font-size:12px;'
            f'color:#374151;margin:.3rem 0 .5rem">'
            f'Menampilkan <b style="color:#E2E8F0">{len(filtered)}</b> / {len(rest)} setups'
            f'{_sep}{_hidden_html}'
            f' &middot; Sort: <b style="color:#60A5FA">{sort_key}</b>'
            f'</div>'
        )
        st.markdown(_stats_html, unsafe_allow_html=True)

        # ── Build table ─────────────────────────────────────────────────────────
        sig_icons = {"WATCHLIST":"◎","CORRECTING":"◌","DEEP_CORRECT":"◍"}
        rows = []
        for r in filtered:
            sig    = r.get("signal","")
            icon   = sig_icons.get(sig,"◯")
            rs     = r.get("rs_vs_ihsg_4w", 0)
            risk_v = r.get("risk_pct", 0)
            risk_flag = "⚠" if risk_v > 25 else "!" if risk_v > 15 else "✓"
            _t = r.get("ticker","").replace(".JK","").upper()
            _ma = _msci_alerts_by_ticker.get(_t)
            msci_badge = ""
            if _ma:
                _lv = _ma.get("alert_level","")
                msci_badge = ("★" if _lv == "HIGH_CONVICTION" else
                              "◈" if _lv == "MEDIUM" else "·")
            rows.append({
                "Signal":  f"{icon} {sig}",
                "MSCI":    msci_badge,
                "Ticker":  r.get("ticker","").replace(".JK",""),
                "Score":   r.get("score",0),
                "Close":   r.get("close",0),
                "Vol×":    round(r.get("vol_ratio",0), 2),
                "RS%":     round(rs, 1),
                "MCF":     r.get("mcf_score",0),
                "MCF?":    r.get("mcf_label","—"),
                "Bear?":   "⛔" if r.get("mcf_bear_blocked") else "",
                "Risk%":   round(risk_v, 1),
                "Risk":    risk_flag,
                "EMA13d":  r.get("ema13d", 0),
                "Daily?":  "✓" if r.get("daily_ok") else "",
                "Regime":  r.get("regime_tag",""),
            })

        df_table = pd.DataFrame(rows)
        st.dataframe(
            df_table, hide_index=True,
            column_config={
                "Score":  st.column_config.NumberColumn("Score", format="%d/10"),
                "Close":  st.column_config.NumberColumn("Close", format="Rp%,.0f"),
                "EMA13d": st.column_config.NumberColumn("EMA13d", format="Rp%,.0f"),
                "Vol×":   st.column_config.NumberColumn("Vol×",  format="%.2f×"),
                "RS%":    st.column_config.NumberColumn("RS%",   format="%+.1f%%"),
                "MCF":    st.column_config.NumberColumn("MCF",   format="%d/10"),
                "Risk%":  st.column_config.NumberColumn("Risk%", format="%.1f%%"),
            }
        )

        # ── Detail analysis ─────────────────────────────────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        sec_head("◆ ANALISIS DETAIL")
        ticker_opts = ["— Pilih saham —"] + [
            r.get("ticker","").replace(".JK","") for r in filtered
        ]
        sel = st.selectbox("Saham:", ticker_opts, key="ema_detail_sel",
                           label_visibility="collapsed")
        if sel and sel != "— Pilih saham —":
            match = next((r for r in filtered if r.get("ticker","").replace(".JK","") == sel), None)
            if match:
                _render_ema_detail(match)


else:
    render_empty_state(
        icon     = "◎",
        title    = "NO SCAN DATA",
        subtitle = "Run a new scan to detect EMA crossover setups.\nResults auto-save and persist between sessions.",
        command  = "python orchestrator.py --mode ema"
    )
