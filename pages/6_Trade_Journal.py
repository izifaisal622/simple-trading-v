"""Simple Trading V7 — Page 06: Trade Journal & Performance Evaluasi"""
import json
import sys
import sqlite3
import base64
import requests
from pathlib import Path
from datetime import datetime, timedelta

import streamlit as st

ROOT     = Path(__file__).parent.parent
LOGS_DIR = ROOT / "logs"
sys.path.insert(0, str(ROOT))

from assets_ui import (
    get_page_css, render_sidebar, render_page_header,
    score_badge, signal_badge, fmt_rp, TEXT_MUTED, NEON_GREEN,
    C_DANGER, C_WARNING, C_INFO,
)

# ─── page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Trade Journal · STV",
    page_icon="📒",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(get_page_css("dashboard"), unsafe_allow_html=True)

# ─── version badge ────────────────────────────────────────────────────────────
try:
    _vj  = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    _ver = _vj.get("version", "?")
except Exception:
    _ver = "?"

render_sidebar("trade_journal")

# ─── header ───────────────────────────────────────────────────────────────────
render_page_header(
    eyebrow  = "◆ MODULE 06 · TRADE JOURNAL · " + "V" + _ver,
    title    = "SIMPLE TRADING ",
    accent   = "V" + _ver,
    subtitle = "◈ LOG TRADE · PERFORMANCE ANALYTICS · WIN RATE · EXPECTANCY",
)

# ─── helpers ──────────────────────────────────────────────────────────────────
def _mono(txt: str, color: str = "var(--text-secondary)") -> str:
    return f'<span style="font-family:Share Tech Mono,monospace;color:{color}">{txt}</span>'

def _sec(title: str) -> None:
    st.markdown(
        f'<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
        f'letter-spacing:.12em;color:var(--text-muted);border-bottom:1px solid rgba(255,255,255,.08);'
        f'padding-bottom:4px;margin:20px 0 12px">◆ {title}</div>',
        unsafe_allow_html=True,
    )

def _metric_box(label: str, value: str, sub: str = "", color: str = "#e2e8f0") -> str:
    return (
        f'<div style="background:var(--bg-card);border:1px solid rgba(255,255,255,.07);'
        f'border-radius:var(--r-md);padding:12px 16px;text-align:center">'
        f'<div style="font-size:var(--text-2xs);color:var(--text-muted);font-family:Share Tech Mono,monospace;'
        f'letter-spacing:.1em;margin-bottom:4px">{label}</div>'
        f'<div style="font-size:var(--text-xl);font-weight:700;color:{color};font-family:Share Tech Mono,monospace">{value}</div>'
        f'{f"<div style=\'font-size:var(--text-xs);color:var(--text-muted);font-family:Share Tech Mono,monospace\'>{sub}</div>" if sub else ""}'
        f'</div>'
    )

def _outcome_color(outcome: str) -> str:
    return {
        "WIN": "var(--c-success)", "LOSS": "var(--c-danger)",
        "BREAKEVEN": "var(--c-warning)", "OPEN": "var(--c-info)",
    }.get(outcome or "OPEN", "var(--text-muted)")

# ─── import trade_logger ──────────────────────────────────────────────────────
try:
    from trade_logger import (
        init_db, log_trade, log_trade_manual, close_trade,
        delete_trade, get_open_trades, get_closed_trades, get_stats,
    )
    init_db()
    _HAS_DB = True
except ImportError as e:
    st.error(f"trade_logger tidak bisa diimpor: {e}")
    _HAS_DB = False
    st.stop()

# ─── Load scan results for prefill ───────────────────────────────────────────
_prefill_results = []
_prefill_tickers = ["— ketik manual —"]
try:
    _rf = LOGS_DIR / "daily_results.json"
    if _rf.exists():
        _data = json.loads(_rf.read_text(encoding="utf-8"))
        for _src in ["ema_results", "whale_results", "mf_results"]:
            for _r in (_data.get(_src) or []):
                _t = str(_r.get("ticker", "")).replace(".JK", "")
                if _t and _t not in _prefill_tickers:
                    _prefill_tickers.append(_t)
                    _prefill_results.append(_r)
except Exception:
    pass

# ─── TABS ─────────────────────────────────────────────────────────────────────
t_log, t_open, t_perf, t_manual, t_history = st.tabs([
    "📥 Log Trade",
    "📋 Open Trades",
    "📊 Performance",
    "✏️ Input Manual",
    "🗂 History",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — LOG TRADE
# ══════════════════════════════════════════════════════════════════════════════
with t_log:
    _sec("CATAT TRADE BARU")
    st.markdown(
        _mono("Catat sinyal yang dieksekusi. Semakin cepat dicatat, semakin akurat evaluasi.", "var(--text-muted)"),
        unsafe_allow_html=True,
    )
    st.markdown("")

    c1, c2 = st.columns([2, 2])
    with c1:
        sel_ticker = st.selectbox("Ticker dari scan", _prefill_tickers, key="tj_log_ticker")
    with c2:
        sel_sig = st.selectbox("Signal type",
            ["BREAKOUT","WATCHLIST","RECOVERY_EARLY","ACCUMULATION","VOL_SPIKE_UP","CORRECTING","CUSTOM"],
            key="tj_log_sig")

    manual_ticker = ""
    if sel_ticker == "— ketik manual —":
        manual_ticker = st.text_input("Ticker (manual)", placeholder="contoh: BBCA", key="tj_manual_tk").upper().strip()

    _ticker_final = manual_ticker if sel_ticker == "— ketik manual —" else sel_ticker

    # Prefill price dari scan results
    _match = next((r for r in _prefill_results
                   if r.get("ticker","").replace(".JK","") == _ticker_final), None)
    _def_price = float(_match.get("last_close") or _match.get("price") or 0) if _match else 0.0
    _def_sl    = float(_match.get("sl_price") or _def_price * 0.93)           if _match else 0.0
    _def_score = int(_match.get("score") or _match.get("conviction") or 0)    if _match else 0

    cp1, cp2, cp3 = st.columns(3)
    with cp1:
        entry_price = st.number_input("Entry Price (Rp)", value=_def_price, min_value=0.0, step=1.0, format="%.0f", key="tj_entry")
    with cp2:
        sl_price    = st.number_input("SL Price (Rp)", value=_def_sl, min_value=0.0, step=1.0, format="%.0f", key="tj_sl")
    with cp3:
        tp1_price   = st.number_input("TP1 Price (Rp)", value=entry_price * 1.06, min_value=0.0, step=1.0, format="%.0f", key="tj_tp1")

    ce1, ce2, ce3 = st.columns(3)
    with ce1:
        sig_score   = st.number_input("Signal Score", value=_def_score, min_value=0, max_value=10, step=1, key="tj_score")
    with ce2:
        regime_opts = ["BULL_STRONG","BULL_WEAK","SIDEWAYS","BEAR_WEAK","BEAR_TREND","UNKNOWN"]
        regime_tag  = st.selectbox("Regime", regime_opts, key="tj_regime")
    with ce3:
        strategy    = st.selectbox("Strategy", ["EMA_XBO","WHALE_HENGKY","RECOVERY","MONEY_FLOW","CUSTOM"], key="tj_strat")

    notes = st.text_area("Notes (optional)", placeholder="Setup notes, catalyst, alasan entry...", key="tj_notes", height=60)

    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        if st.button("💾 CATAT TRADE", key="tj_save", use_container_width=True):
            if _ticker_final and entry_price > 0 and sl_price > 0:
                tid = log_trade(
                    ticker=_ticker_final, entry_price=entry_price, sl_price=sl_price,
                    tp1_price=tp1_price, signal_type=sel_sig, signal_score=sig_score,
                    regime_tag=regime_tag, strategy=strategy, notes=notes,
                )
                st.success(f"✅ Trade #{tid} — {_ticker_final} @ Rp{entry_price:,.0f} dicatat!")
            else:
                st.error("Isi Ticker, Entry Price, dan SL Price")

    if _ticker_final and entry_price > 0 and sl_price > 0:
        risk_r   = entry_price - sl_price
        rr_ratio = (tp1_price - entry_price) / risk_r if risk_r > 0 else 0
        risk_pct = risk_r / entry_price * 100
        with col_info:
            st.markdown(
                _mono(f"Risk: Rp{risk_r:,.0f} ({risk_pct:.1f}%) · R:R ke TP1 = {rr_ratio:.2f}",
                      "var(--c-warning)"),
                unsafe_allow_html=True,
            )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — OPEN TRADES
# ══════════════════════════════════════════════════════════════════════════════
with t_open:
    _sec("OPEN POSITIONS")
    open_trades = get_open_trades()

    if not open_trades:
        st.markdown(_mono("Tidak ada open trade saat ini.", "var(--text-muted)"), unsafe_allow_html=True)
    else:
        st.markdown(_mono(f"{len(open_trades)} open position(s):", "var(--text-muted)"), unsafe_allow_html=True)
        for trade in open_trades:
            tid    = trade.get("id")
            ticker = trade.get("ticker","?")
            entry  = trade.get("entry_price") or 0
            sl     = trade.get("sl_price") or 0
            tp1    = trade.get("tp1_price") or 0
            sig    = trade.get("signal_type","?")
            edate  = (trade.get("entry_date") or "")[:10]
            risk_r = entry - sl if sl > 0 else 0
            rr     = (tp1 - entry) / risk_r if risk_r > 0 else 0

            st.markdown(
                f'<div style="background:var(--bg-card);border:1px solid rgba(255,255,255,.07);'
                f'border-left:3px solid var(--c-info);border-radius:var(--r-md);'
                f'padding:12px 16px;margin-bottom:8px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px">'
                f'<div>'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-lg);color:#e2e8f0;font-weight:700">{ticker}</span>'
                f'<span style="font-size:var(--text-xs);color:var(--text-muted);margin-left:8px;font-family:Share Tech Mono,monospace">#{tid} · {edate}</span>'
                f'</div>'
                f'<div style="display:flex;gap:16px;flex-wrap:wrap">'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);color:#e2e8f0">Entry: {fmt_rp(entry)}</span>'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);color:var(--c-danger)">SL: {fmt_rp(sl)}</span>'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);color:var(--c-success)">TP1: {fmt_rp(tp1)}</span>'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--text-muted)">R:R {rr:.2f} · {sig}</span>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            # Close trade controls
            with st.expander(f"Close / Hapus #{tid} — {ticker}", expanded=False):
                cx1, cx2, cx3 = st.columns([2, 1, 1])
                with cx1:
                    exit_p = st.number_input("Exit Price (Rp)", value=float(entry), step=1.0, format="%.0f", key=f"tj_exit_{tid}")
                with cx2:
                    outcome_sel = st.selectbox("Outcome", ["WIN","LOSS","BREAKEVEN"], key=f"tj_outcome_{tid}")
                with cx3:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("✓ CLOSE", key=f"tj_close_{tid}", use_container_width=True):
                        result = close_trade(tid, exit_p, outcome_sel)
                        if result.get("success"):
                            pnl = result.get("pnl_r", 0) or 0
                            st.success(f"Closed: {outcome_sel} {pnl:+.2f}R")
                            st.rerun()
                        else:
                            st.error(result.get("error","Error"))
                if st.button(f"🗑 Hapus #{tid}", key=f"tj_del_{tid}"):
                    delete_trade(tid)
                    st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — PERFORMANCE
# ══════════════════════════════════════════════════════════════════════════════
with t_perf:
    _sec("PERFORMANCE ANALYTICS")
    stats = get_stats()

    total_c = stats.get("total_closed", 0)
    total_o = stats.get("total_open", 0)

    # Top metrics row
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    with m1:
        st.markdown(_metric_box("CLOSED TRADES", str(total_c), f"min 30 req"), unsafe_allow_html=True)
    with m2:
        st.markdown(_metric_box("OPEN", str(total_o)), unsafe_allow_html=True)

    if total_c == 0:
        st.markdown(
            f'<div style="background:rgba(255,165,0,.08);border:1px solid rgba(255,165,0,.3);'
            f'border-radius:var(--r-md);padding:16px;margin:16px 0;font-family:Share Tech Mono,monospace;'
            f'font-size:var(--text-sm);color:var(--c-warning)">'
            f'⚠ Belum ada closed trade. Minimal 30 diperlukan untuk validasi edge.<br>'
            f'<span style="font-size:var(--text-xs);color:var(--text-muted)">Catat trade di tab Log Trade, kemudian close setelah exit.</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        win_rate = stats.get("win_rate")
        avg_r    = stats.get("avg_r")
        exp      = stats.get("expectancy")
        pf       = stats.get("profit_factor")
        avg_win  = stats.get("avg_win_r")
        avg_loss = stats.get("avg_loss_r")
        max_loss = stats.get("max_consec_loss")

        sufficient = stats.get("sufficient", False)
        wr_color   = "var(--c-success)" if (win_rate or 0) >= 55 else "var(--c-warning)" if (win_rate or 0) >= 40 else "var(--c-danger)"
        exp_color  = "var(--c-success)" if (exp or 0) > 0 else "var(--c-danger)"
        pf_color   = "var(--c-success)" if (pf or 0) >= 1.5 else "var(--c-warning)" if (pf or 0) >= 1.0 else "var(--c-danger)"

        with m3:
            st.markdown(_metric_box("WIN RATE", f"{win_rate:.1f}%" if win_rate else "N/A",
                        "target ≥55%", wr_color), unsafe_allow_html=True)
        with m4:
            st.markdown(_metric_box("AVG R", f"{avg_r:+.2f}R" if avg_r else "N/A",
                        "per closed trade", exp_color), unsafe_allow_html=True)
        with m5:
            st.markdown(_metric_box("EXPECTANCY", f"{exp:+.3f}R" if exp else "N/A",
                        "E[profit per trade]", exp_color), unsafe_allow_html=True)
        with m6:
            st.markdown(_metric_box("PROFIT FACTOR", f"{pf:.2f}" if pf else "N/A",
                        "target ≥1.5", pf_color), unsafe_allow_html=True)

        st.markdown("")

        # Second row
        r1, r2, r3, r4 = st.columns(4)
        with r1:
            st.markdown(_metric_box("AVG WIN", f"{avg_win:+.2f}R" if avg_win else "N/A",
                        "", "var(--c-success)"), unsafe_allow_html=True)
        with r2:
            st.markdown(_metric_box("AVG LOSS", f"{avg_loss:.2f}R" if avg_loss else "N/A",
                        "", "var(--c-danger)"), unsafe_allow_html=True)
        with r3:
            st.markdown(_metric_box("MAX CONSEC LOSS", str(max_loss) if max_loss else "0",
                        "berturut-turut", "var(--c-warning)"), unsafe_allow_html=True)
        with r4:
            valid = "✅ VALID" if sufficient else f"⚠ {total_c}/30"
            v_color = "var(--c-success)" if sufficient else "var(--c-warning)"
            st.markdown(_metric_box("SAMPLE SIZE", valid, "30 trades = valid edge", v_color), unsafe_allow_html=True)

        # Verdict
        st.markdown("")
        if sufficient:
            if (exp or 0) > 0 and (win_rate or 0) >= 50:
                verdict_color = "var(--c-success)"
                verdict = "✅ EDGE VALID — Sistem menghasilkan alpha positif. Lanjutkan dengan sizing sesuai regime."
            elif (exp or 0) > 0:
                verdict_color = "var(--c-warning)"
                verdict = "⚠ EDGE LEMAH — Expectancy positif tapi win rate rendah. Perlu review setup criteria."
            else:
                verdict_color = "var(--c-danger)"
                verdict = "❌ EDGE NEGATIF — Expectancy < 0. Stop dan review sistem sebelum trade lebih lanjut."

            st.markdown(
                f'<div style="background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.1);'
                f'border-left:4px solid {verdict_color};border-radius:var(--r-md);padding:12px 16px;'
                f'font-family:Share Tech Mono,monospace;font-size:var(--text-sm);color:{verdict_color}">'
                f'{verdict}</div>',
                unsafe_allow_html=True,
            )

        # Recent closed trades table
        _sec("LAST 20 CLOSED TRADES")
        recent = get_closed_trades(20)
        if recent:
            rows_html = ""
            for t in recent:
                oc     = t.get("outcome","?")
                oc_c   = _outcome_color(oc)
                pnl    = t.get("pnl_r")
                pnl_s  = f"{pnl:+.2f}R" if pnl is not None else "—"
                pnl_c  = "var(--c-success)" if (pnl or 0) > 0 else "var(--c-danger)" if (pnl or 0) < 0 else "var(--text-muted)"
                rows_html += (
                    f'<tr style="border-bottom:1px solid rgba(255,255,255,.05)">'
                    f'<td style="padding:6px 8px;font-family:Share Tech Mono,monospace;color:#e2e8f0">{t.get("ticker","?")}</td>'
                    f'<td style="padding:6px 8px;font-family:Share Tech Mono,monospace;color:var(--text-muted)">{(t.get("exit_date") or "")[:10]}</td>'
                    f'<td style="padding:6px 8px;font-family:Share Tech Mono,monospace;color:var(--text-muted)">{t.get("strategy","?")}</td>'
                    f'<td style="padding:6px 8px;font-family:Share Tech Mono,monospace;color:var(--text-muted)">{t.get("signal_type","?")}</td>'
                    f'<td style="padding:6px 8px;font-family:Share Tech Mono,monospace;color:{oc_c}">{oc}</td>'
                    f'<td style="padding:6px 8px;font-family:Share Tech Mono,monospace;color:{pnl_c};text-align:right">{pnl_s}</td>'
                    f'<td style="padding:6px 8px;font-family:Share Tech Mono,monospace;color:var(--text-muted);text-align:right">{t.get("bars_held","?")}</td>'
                    f'</tr>'
                )
            st.markdown(
                f'<table style="width:100%;border-collapse:collapse;font-size:var(--text-xs)">'
                f'<thead><tr style="border-bottom:2px solid rgba(255,255,255,.1)">'
                f'<th style="padding:6px 8px;color:var(--text-muted);text-align:left;font-family:Share Tech Mono,monospace">TICKER</th>'
                f'<th style="padding:6px 8px;color:var(--text-muted);text-align:left;font-family:Share Tech Mono,monospace">EXIT DATE</th>'
                f'<th style="padding:6px 8px;color:var(--text-muted);text-align:left;font-family:Share Tech Mono,monospace">STRATEGY</th>'
                f'<th style="padding:6px 8px;color:var(--text-muted);text-align:left;font-family:Share Tech Mono,monospace">SIGNAL</th>'
                f'<th style="padding:6px 8px;color:var(--text-muted);text-align:left;font-family:Share Tech Mono,monospace">OUTCOME</th>'
                f'<th style="padding:6px 8px;color:var(--text-muted);text-align:right;font-family:Share Tech Mono,monospace">P&L (R)</th>'
                f'<th style="padding:6px 8px;color:var(--text-muted);text-align:right;font-family:Share Tech Mono,monospace">BARS</th>'
                f'</thead><tbody>{rows_html}</tbody></table>',
                unsafe_allow_html=True,
            )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — INPUT MANUAL
# ══════════════════════════════════════════════════════════════════════════════
with t_manual:
    _sec("INPUT MANUAL — TRADE HISTORIS")
    st.markdown(
        _mono("Untuk mencatat trade yang sudah selesai (historical entry).", "var(--text-muted)"),
        unsafe_allow_html=True,
    )
    st.markdown("")

    m1, m2 = st.columns(2)
    with m1:
        m_ticker  = st.text_input("Ticker", placeholder="BBCA", key="tj_m_tk").upper().strip()
        m_entry   = st.number_input("Entry Price (Rp)", value=0.0, step=1.0, format="%.0f", key="tj_m_entry")
        m_sl      = st.number_input("SL Price (Rp)", value=0.0, step=1.0, format="%.0f", key="tj_m_sl")
        m_exit    = st.number_input("Exit Price (Rp)", value=0.0, step=1.0, format="%.0f", key="tj_m_exit")
    with m2:
        m_outcome = st.selectbox("Outcome", ["WIN","LOSS","BREAKEVEN"], key="tj_m_oc")
        m_sig     = st.selectbox("Signal type", ["BREAKOUT","WATCHLIST","RECOVERY_EARLY","ACCUMULATION","CORRECTING","CUSTOM"], key="tj_m_sig")
        m_strat   = st.selectbox("Strategy", ["EMA_XBO","WHALE_HENGKY","RECOVERY","MONEY_FLOW","CUSTOM"], key="tj_m_strat")
        m_bars    = st.number_input("Bars Held", value=5, min_value=1, max_value=500, step=1, key="tj_m_bars")
        m_score   = st.number_input("Signal Score", value=5, min_value=0, max_value=10, step=1, key="tj_m_score")

    m_notes = st.text_area("Notes", key="tj_m_notes", height=60)

    if st.button("💾 SIMPAN TRADE MANUAL", key="tj_manual_save"):
        if m_ticker and m_entry > 0 and m_sl > 0:
            try:
                tid = log_trade_manual(
                    ticker=m_ticker, entry_price=m_entry, sl_price=m_sl,
                    exit_price=m_exit, outcome=m_outcome, bars_held=m_bars,
                    signal_type=m_sig, signal_score=m_score, strategy=m_strat, notes=m_notes,
                )
                st.success(f"✅ Trade manual #{tid} — {m_ticker} ({m_outcome}) disimpan!")
            except Exception as ex:
                st.error(f"Error: {ex}")
        else:
            st.error("Isi Ticker, Entry Price, dan SL Price")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — HISTORY (ALL TRADES)
# ══════════════════════════════════════════════════════════════════════════════
with t_history:
    _sec("TRADE HISTORY LENGKAP")

    h_days = st.slider("Tampilkan N hari terakhir", 7, 365, 90, key="tj_h_days")
    all_trades = get_closed_trades(999)  # get all, filter by date client side

    cutoff = (datetime.now() - timedelta(days=h_days)).strftime("%Y-%m-%d")
    shown  = [t for t in all_trades if (t.get("exit_date") or "9999") >= cutoff]

    if not shown:
        st.markdown(_mono(f"Tidak ada closed trade dalam {h_days} hari terakhir.", "var(--text-muted)"), unsafe_allow_html=True)
    else:
        # Aggregate by strategy
        by_strat: dict = {}
        for t in shown:
            s = t.get("strategy","?")
            by_strat.setdefault(s, []).append(t)

        st.markdown(_mono(f"{len(shown)} closed trades · {h_days} hari terakhir", "var(--text-muted)"), unsafe_allow_html=True)
        st.markdown("")

        # Per-strategy breakdown
        for strat, trades in sorted(by_strat.items()):
            wins    = [t for t in trades if t.get("outcome") == "WIN"]
            losses  = [t for t in trades if t.get("outcome") == "LOSS"]
            pnl_sum = sum(t.get("pnl_r") or 0 for t in trades)
            wr      = len(wins) / len(trades) * 100 if trades else 0
            pnl_c   = "var(--c-success)" if pnl_sum > 0 else "var(--c-danger)"

            st.markdown(
                f'<div style="background:var(--bg-card);border:1px solid rgba(255,255,255,.07);'
                f'border-radius:var(--r-md);padding:10px 14px;margin-bottom:8px;'
                f'display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);color:#e2e8f0">{strat}</span>'
                f'<div style="display:flex;gap:16px">'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--text-muted)">{len(trades)} trades</span>'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--c-success)">{len(wins)}W</span>'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--c-danger)">{len(losses)}L</span>'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:var(--text-muted)">WR {wr:.0f}%</span>'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);color:{pnl_c}">{pnl_sum:+.1f}R</span>'
                f'</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown("")
        # Download as CSV
        if st.button("📥 Export CSV", key="tj_export"):
            rows = []
            for t in shown:
                rows.append(",".join(str(t.get(k,"")) for k in
                    ["id","ticker","entry_date","entry_price","sl_price","exit_date","exit_price",
                     "outcome","pnl_r","pnl_pct","bars_held","strategy","signal_type","signal_score","notes"]))
            header = "id,ticker,entry_date,entry_price,sl_price,exit_date,exit_price,outcome,pnl_r,pnl_pct,bars_held,strategy,signal_type,signal_score,notes"
            csv_data = header + "\n" + "\n".join(rows)
            st.download_button("⬇ Download trade_history.csv", csv_data,
                               file_name="trade_history.csv", mime="text/csv")

