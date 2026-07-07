"""Simple Trading V9 — Page 06: Trade Journal & Performance Evaluasi"""
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
    _ver = _vj.get("version", "9").split(".")[0]
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
        get_loss_attribution,
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
t_log, t_open, t_perf, t_manual, t_history, t_postmortem, t_unified, t_backtest = st.tabs([
    "📥 Log Trade",
    "📋 Open Trades",
    "📊 Performance",
    "✏️ Input Manual",
    "🗂 History",
    "🔬 Post-Mortem",
    "⚖ Paper vs Real",
    "🧪 Backtesting",
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
        if st.button("💾 CATAT TRADE", key="tj_save", width='stretch'):
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
                    if st.button("✓ CLOSE", key=f"tj_close_{tid}", width='stretch'):
                        result = close_trade(tid, exit_p, outcome_sel)
                        if result.get("success"):
                            pnl = result.get("pnl_r", 0) or 0
                            st.success(f"Closed: {outcome_sel} {pnl:+.2f}R")
                            # Auto-trigger post-mortem untuk trade yang baru ditutup
                            st.session_state["pm_trade_id"] = tid
                            st.session_state["pm_auto_show"] = True
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

# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — POST-MORTEM
# ══════════════════════════════════════════════════════════════════════════════
with t_postmortem:
    _sec("POST-MORTEM ANALYSIS")

    GREEN_PM = NEON_GREEN
    RED_PM   = C_DANGER
    YEL_PM   = C_WARNING

    # ── Auto-show banner jika baru saja close trade ───────────────────────────
    _auto_pm  = st.session_state.pop("pm_auto_show", False)
    _auto_tid = st.session_state.get("pm_trade_id")

    if _auto_pm and _auto_tid:
        st.markdown(f"""
<div style="background:rgba(96,165,250,0.08);border:1px solid rgba(96,165,250,0.3);
border-left:4px solid #60A5FA;border-radius:var(--r-md);
padding:0.7rem 1.1rem;margin-bottom:0.8rem;
font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:#60A5FA">
🔬 Trade #{_auto_tid} baru ditutup — Post-mortem otomatis dimuat di bawah.
</div>""", unsafe_allow_html=True)

    # ── Selector: per-trade atau aggregate ────────────────────────────────────
    closed_trades = get_closed_trades(limit=50)
    _pm_mode_opts = ["📊 Aggregate (semua trades)", "🔍 Per Trade (pilih trade)"]
    _pm_mode = st.radio("Mode", _pm_mode_opts, horizontal=True, key="pm_mode",
                         label_visibility="collapsed")

    # ── HELPER: render single post-mortem card ─────────────────────────────
    def _render_pm_card(pm: dict) -> None:
        if not pm.get("available"):
            st.warning(pm.get("reason", "Data tidak tersedia"))
            return

        outcome  = pm.get("outcome", "")
        ticker   = pm.get("ticker", "?")
        pnl_r    = pm.get("pnl_r", 0) or 0
        dims     = pm.get("dims", [])
        primary  = pm.get("primary_cause", "")
        top_rule = pm.get("top_rule", "")
        patterns = pm.get("pattern_hits", [])
        n_sim    = pm.get("similar_losses", 0)
        n_tot    = pm.get("total_losses", 0)
        n_crit   = pm.get("critical_count", 0)
        n_warn   = pm.get("warning_count", 0)

        _oc  = GREEN_PM if outcome == "WIN" else RED_PM if outcome == "LOSS" else YEL_PM
        _obg = "rgba(0,255,102,0.05)" if outcome == "WIN" else "rgba(239,68,68,0.05)" if outcome == "LOSS" else "rgba(240,180,41,0.05)"

        # Header
        st.markdown(f"""
<div style="background:{_obg};border:1px solid {_oc}35;
border-left:4px solid {_oc};border-radius:var(--r-md);
padding:0.8rem 1.1rem;margin-bottom:0.6rem">
  <div style="display:flex;align-items:center;gap:1rem;margin-bottom:0.4rem">
    <span style="font-family:Orbitron,monospace;font-size:var(--text-xl);
    font-weight:900;color:#E2E8F0">{ticker}</span>
    <span style="font-family:Orbitron,monospace;font-size:var(--text-sm);
    font-weight:700;color:{_oc}">{outcome}</span>
    <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);
    color:{_oc};font-weight:700">{pnl_r:+.2f}R</span>
    <span style="margin-left:auto;font-family:Share Tech Mono,monospace;
    font-size:var(--text-2xs);color:var(--text-dim)">
    {n_crit} CRITICAL · {n_warn} WARNING
    </span>
  </div>
</div>
""", unsafe_allow_html=True)

        # Dimension breakdown
        _FLAG_COL = {"CRITICAL": RED_PM, "WARNING": YEL_PM, "OK": GREEN_PM}
        _FLAG_ICO = {"CRITICAL": "✗", "WARNING": "⚠", "OK": "✓"}

        dim_html = ""
        for d in dims:
            _fc  = _FLAG_COL.get(d["flag"], "var(--text-muted)")
            _ico = _FLAG_ICO.get(d["flag"], "·")
            _bg  = (f"rgba(239,68,68,0.06)" if d["flag"] == "CRITICAL"
                    else "rgba(240,180,41,0.04)" if d["flag"] == "WARNING"
                    else "rgba(0,255,102,0.03)")
            dim_html += (
                f'<div style="background:{_bg};border:1px solid {_fc}25;'
                f'border-radius:var(--r-sm);padding:0.4rem 0.8rem;margin-bottom:0.3rem;'
                f'display:flex;gap:0.7rem;align-items:flex-start">'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
                f'color:{_fc};font-weight:700;min-width:90px">{_ico} {d["dim"]}</span>'
                f'<div style="flex:1">'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
                f'color:var(--text-muted)">{d["value"]}</span>'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
                f'color:#94A3B8;margin-left:0.5rem">— {d["finding"]}</span>'
                f'</div>'
                f'</div>'
            )

        st.markdown(f"""
<div style="background:rgba(0,0,0,0.2);border:1px solid rgba(255,255,255,0.06);
border-radius:var(--r-md);padding:0.7rem 0.9rem;margin-bottom:0.6rem">
  <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);
  color:var(--text-dim);letter-spacing:0.12em;margin-bottom:0.5rem">DIMENSI ANALISIS</div>
  {dim_html}
</div>
""", unsafe_allow_html=True)

        # Primary cause + rule
        _prim_col = RED_PM if n_crit > 0 else YEL_PM if n_warn > 0 else GREEN_PM
        st.markdown(f"""
<div style="background:rgba(0,0,0,0.25);border:1px solid {_prim_col}30;
border-left:3px solid {_prim_col};border-radius:var(--r-sm);
padding:0.6rem 0.9rem;margin-bottom:0.4rem">
  <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
  color:var(--text-dim);margin-bottom:0.2rem">PENYEBAB UTAMA</div>
  <div style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);
  color:#E2E8F0;line-height:1.6">{primary}</div>
  {f'<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);color:{_prim_col};margin-top:0.4rem;font-weight:700">{top_rule}</div>' if top_rule else ""}
</div>
""", unsafe_allow_html=True)

        # Pattern match
        if patterns and outcome == "LOSS":
            _pat_str = patterns[0]
            st.markdown(f"""
<div style="background:rgba(239,68,68,0.05);border:1px solid rgba(239,68,68,0.2);
border-radius:var(--r-sm);padding:0.5rem 0.9rem">
  <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
  color:{RED_PM};font-weight:700">⚠ PATTERN BERULANG: </span>
  <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
  color:#94A3B8">{_pat_str}</span>
</div>
""", unsafe_allow_html=True)
        elif outcome == "WIN":
            st.markdown(f"""
<div style="background:rgba(0,255,102,0.04);border:1px solid rgba(0,255,102,0.15);
border-radius:var(--r-sm);padding:0.5rem 0.9rem">
  <span style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
  color:{GREEN_PM}">✓ Trade ini WIN — catat kondisi yang membuatnya berhasil sebagai template.</span>
</div>
""", unsafe_allow_html=True)

    # ── MODE 1: Per Trade ─────────────────────────────────────────────────────
    if "Per Trade" in _pm_mode:
        if not closed_trades:
            st.markdown(_mono("Belum ada closed trades.", "var(--text-muted)"),
                        unsafe_allow_html=True)
        else:
            # Default ke trade yang baru ditutup jika ada
            _trade_options = {
                f"#{t['id']} {t['ticker']} — {t.get('outcome','?')} "
                f"({(t.get('pnl_r') or 0):+.2f}R) · {(t.get('exit_date') or '')[:10]}": t["id"]
                for t in closed_trades
            }
            _default_label = None
            if _auto_tid:
                for lbl, tid_val in _trade_options.items():
                    if tid_val == _auto_tid:
                        _default_label = lbl
                        break

            _opts_list = list(_trade_options.keys())
            _def_idx   = _opts_list.index(_default_label) if _default_label in _opts_list else 0

            sel_label = st.selectbox("Pilih trade", _opts_list,
                                      index=_def_idx, key="pm_sel_trade")
            sel_tid   = _trade_options.get(sel_label)

            if sel_tid and st.button("🔬 ANALISIS TRADE INI", key="pm_run_single",
                                      type="primary"):
                st.session_state["pm_result"] = get_loss_attribution(sel_tid)
                st.session_state["pm_trade_id"] = sel_tid

            # Auto-run jika dari close trigger
            if _auto_pm and _auto_tid and "pm_result" not in st.session_state:
                st.session_state["pm_result"] = get_loss_attribution(_auto_tid)

            pm_result = st.session_state.get("pm_result")
            if pm_result and pm_result.get("trade_id") == st.session_state.get("pm_trade_id"):
                _render_pm_card(pm_result)

    # ── MODE 2: Aggregate ─────────────────────────────────────────────────────
    else:
        if not closed_trades:
            st.markdown(_mono("Belum ada closed trades untuk dianalisis.", "var(--text-muted)"),
                        unsafe_allow_html=True)
        else:
            if st.button("📊 GENERATE AGGREGATE REPORT", key="pm_run_agg", type="primary"):
                st.session_state["pm_agg"] = get_loss_attribution()

            agg = st.session_state.get("pm_agg")
            if agg and agg.get("available"):
                _n_l = agg.get("total_losses", 0)
                _n_w = agg.get("total_wins", 0)
                _n_c = agg.get("total_closed", 0)

                st.markdown(f"""
<div style="background:rgba(0,0,0,0.2);border:1px solid rgba(255,255,255,0.07);
border-radius:var(--r-md);padding:0.7rem 1rem;margin-bottom:0.8rem;
font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
display:flex;gap:2rem;align-items:center;flex-wrap:wrap">
  <span style="color:var(--text-dim)">ANALISIS {_n_c} CLOSED TRADES</span>
  <span style="color:{GREEN_PM}">WIN: {_n_w}</span>
  <span style="color:{RED_PM}">LOSS: {_n_l}</span>
  <span style="color:var(--text-muted)">Top loss regime: <b style="color:{RED_PM}">{agg.get("top_loss_regime","—")}</b></span>
  <span style="color:var(--text-muted)">Top loss score bucket: <b style="color:{RED_PM}">{agg.get("top_loss_score","—")}</b></span>
</div>
""", unsafe_allow_html=True)

                # Win rate tables
                def _wr_table(title: str, rows: list) -> None:
                    if not rows:
                        return
                    st.markdown(f"""<div style="font-family:Share Tech Mono,monospace;
font-size:var(--text-2xs);color:var(--text-dim);letter-spacing:0.12em;
margin:0.8rem 0 0.3rem">{title}</div>""", unsafe_allow_html=True)
                    html = '<div style="display:flex;flex-direction:column;gap:0.25rem">'
                    for row in rows:
                        wr   = row["win_rate"]
                        _bc  = GREEN_PM if wr >= 55 else YEL_PM if wr >= 40 else RED_PM
                        _bar = f'<div style="width:{wr}%;background:{_bc};height:100%;border-radius:2px"></div>'
                        html += (
                            f'<div style="display:flex;align-items:center;gap:0.6rem">'
                            f'<span style="font-family:Share Tech Mono,monospace;'
                            f'font-size:var(--text-xs);color:#94A3B8;min-width:130px">{row["label"]}</span>'
                            f'<div style="flex:1;background:rgba(255,255,255,0.06);'
                            f'border-radius:2px;height:6px">{_bar}</div>'
                            f'<span style="font-family:Share Tech Mono,monospace;'
                            f'font-size:var(--text-xs);color:{_bc};min-width:80px">'
                            f'{wr:.0f}% ({row["total"]} trades)</span>'
                            f'</div>'
                        )
                    html += "</div>"
                    st.markdown(html, unsafe_allow_html=True)

                _wr_table("WIN RATE BY REGIME", agg.get("regime_wr", []))
                _wr_table("WIN RATE BY SIGNAL SCORE", agg.get("score_wr", []))
                _wr_table("WIN RATE BY RISK %", agg.get("risk_wr", []))

# ══════════════════════════════════════════════════════════════════════════════
# TAB 7 — PAPER vs REAL UNIFIED VIEW
# ══════════════════════════════════════════════════════════════════════════════
with t_unified:
    _sec("PAPER vs REAL — UNIFIED COMPARISON")

    st.markdown(
        _mono(
            "Bandingkan performa paper trade (Page 04) dengan real trade (Page 06) "
            "per grade/setup. Grade real trade di-derive dari signal_score.",
            "var(--text-muted)"
        ),
        unsafe_allow_html=True,
    )

    # ── Load data dari kedua sumber ───────────────────────────────────────────
    _paper_closed = []
    try:
        from agents.journal_agent import get_closed_trades as _get_paper_closed
        _paper_closed = _get_paper_closed(limit=500)
    except Exception as _e:
        st.warning(f"Paper journal tidak tersedia: {_e}")

    _real_closed = get_closed_trades(limit=500)

    # ── Derive grade dari signal_score untuk real trades ──────────────────────
    def _derive_grade(signal_score: int) -> str:
        """
        Proxy grade dari signal_score (0-10).
        Mapping dibuat konsisten dengan grading logic di Page 04:
        A+/A = setup terbaik, score tinggi
        B    = setup medium
        C    = setup lemah tapi masih tradeable
        D/F  = below threshold
        """
        s = signal_score or 0
        if s >= 9:  return "A+"
        if s >= 7:  return "A"
        if s >= 5:  return "B"
        if s >= 3:  return "C"
        if s >= 1:  return "D"
        return "F"

    # Enrich real trades dengan derived grade
    for _rt in _real_closed:
        _rt["_derived_grade"] = _derive_grade(_rt.get("signal_score") or 0)
        _rt["_source"]        = "REAL"

    for _pt in _paper_closed:
        _pt["_derived_grade"] = _pt.get("grade") or _derive_grade(_pt.get("ema_score") or 0)
        _pt["_source"]        = "PAPER"

    if not _paper_closed and not _real_closed:
        st.markdown(
            _mono("Belum ada closed trades di kedua database. "
                  "Log dan close trade di tab Log Trade / Paper Trade Journal dulu.",
                  "var(--text-muted)"),
            unsafe_allow_html=True,
        )
    else:
        # ── Summary metric row ────────────────────────────────────────────────
        _p_total  = len(_paper_closed)
        _r_total  = len(_real_closed)
        _p_wins   = sum(1 for t in _paper_closed if t.get("outcome") == "WIN")
        _r_wins   = sum(1 for t in _real_closed  if t.get("outcome") == "WIN")
        _p_wr     = round(_p_wins / _p_total * 100, 1) if _p_total else 0
        _r_wr     = round(_r_wins / _r_total * 100, 1) if _r_total else 0
        _p_exp    = (sum(t.get("pnl_r") or 0 for t in _paper_closed) / _p_total
                     if _p_total else 0)
        _r_exp    = (sum(t.get("pnl_r") or 0 for t in _real_closed) / _r_total
                     if _r_total else 0)

        _um1, _um2, _um3, _um4 = st.columns(4)
        _metrics = [
            (_um1, "PAPER TRADES",    f"{_p_total}",        f"WR {_p_wr:.1f}%",  NEON_GREEN if _p_wr >= 50 else C_WARNING),
            (_um2, "REAL TRADES",     f"{_r_total}",        f"WR {_r_wr:.1f}%",  NEON_GREEN if _r_wr >= 50 else C_WARNING),
            (_um3, "PAPER AVG R",     f"{_p_exp:+.2f}R",    "per trade",          NEON_GREEN if _p_exp > 0 else C_DANGER),
            (_um4, "REAL AVG R",      f"{_r_exp:+.2f}R",    "per trade",          NEON_GREEN if _r_exp > 0 else C_DANGER),
        ]
        for _col, _lbl, _val, _sub, _clr in _metrics:
            with _col:
                st.markdown(_metric_box(_lbl, _val, _sub, _clr), unsafe_allow_html=True)

        # ── Slippage check ────────────────────────────────────────────────────
        if _p_total >= 5 and _r_total >= 5:
            _slip = _r_wr - _p_wr
            _slip_col = NEON_GREEN if _slip >= -5 else C_WARNING if _slip >= -15 else C_DANGER
            _slip_lbl = ("✓ Real sesuai ekspektasi paper" if _slip >= -5
                         else "⚠ Real underperform paper — review sizing / disiplin"
                         if _slip >= -15 else
                         "⛔ Gap besar — paper terlalu optimistis atau eksekusi real bermasalah")
            st.markdown(
                f'<div style="background:rgba(0,0,0,0.2);border:1px solid {_slip_col}30;'
                f'border-left:3px solid {_slip_col};border-radius:var(--r-sm);'
                f'padding:0.5rem 1rem;margin:0.5rem 0;font-family:Share Tech Mono,monospace;'
                f'font-size:var(--text-xs);display:flex;gap:1rem;align-items:center">'
                f'<span style="color:var(--text-dim)">PAPER→REAL SLIPPAGE</span>'
                f'<span style="color:{_slip_col};font-weight:700">{_slip:+.1f}% WR</span>'
                f'<span style="color:#94A3B8">{_slip_lbl}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)
        _sec("WIN RATE PER GRADE — PAPER vs REAL")

        # ── Per-grade comparison ──────────────────────────────────────────────
        _GRADES    = ["A+", "A", "B", "C", "D", "F"]
        _grade_rows = []

        for _g in _GRADES:
            _p_g = [t for t in _paper_closed if t.get("_derived_grade") == _g]
            _r_g = [t for t in _real_closed  if t.get("_derived_grade") == _g]

            if not _p_g and not _r_g:
                continue

            def _gstats(trades):
                if not trades:
                    return None
                _w   = sum(1 for t in trades if t.get("outcome") == "WIN")
                _wr  = round(_w / len(trades) * 100, 1)
                _ar  = round(sum(t.get("pnl_r") or 0 for t in trades) / len(trades), 2)
                return {"n": len(trades), "wr": _wr, "avg_r": _ar, "wins": _w}

            _pg = _gstats(_p_g)
            _rg = _gstats(_r_g)

            _grade_rows.append({"grade": _g, "paper": _pg, "real": _rg})

        if not _grade_rows:
            st.markdown(
                _mono("Belum ada data per grade. Tambah dan close beberapa trade dulu.",
                      "var(--text-muted)"),
                unsafe_allow_html=True,
            )
        else:
            # Header
            _h0, _h1, _h2, _h3 = st.columns([1, 3, 3, 2])
            for _hcol, _hlbl in [(_h0, "GRADE"), (_h1, "📄 PAPER"), (_h2, "💰 REAL"), (_h3, "DELTA WR")]:
                _hcol.markdown(
                    f'<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-2xs);'
                    f'letter-spacing:.15em;color:var(--text-dim);padding:4px 0">{_hlbl}</div>',
                    unsafe_allow_html=True,
                )

            # Grade rows
            for _row in _grade_rows:
                _g   = _row["grade"]
                _pg  = _row["paper"]
                _rg  = _row["real"]

                _gc  = (NEON_GREEN if _g in ("A+","A") else C_WARNING if _g == "B"
                        else C_INFO if _g == "C" else C_DANGER)

                # Delta WR
                if _pg and _rg:
                    _dwr     = _rg["wr"] - _pg["wr"]
                    _dwr_col = NEON_GREEN if _dwr >= -5 else C_WARNING if _dwr >= -15 else C_DANGER
                    _dwr_str = f"{_dwr:+.1f}%"
                elif _rg and not _pg:
                    _dwr_col = C_INFO
                    _dwr_str = "no paper"
                elif _pg and not _rg:
                    _dwr_col = "var(--text-dim)"
                    _dwr_str = "no real"
                else:
                    _dwr_col = "var(--text-dim)"
                    _dwr_str = "—"

                def _cell(stats, source_col: str) -> str:
                    if not stats:
                        return (f'<div style="background:rgba(255,255,255,0.02);'
                                f'border:1px solid rgba(255,255,255,0.05);border-radius:var(--r-sm);'
                                f'padding:0.45rem 0.7rem;font-family:Share Tech Mono,monospace;'
                                f'font-size:var(--text-xs);color:var(--text-dim)">—</div>')
                    _wr_c = NEON_GREEN if stats["wr"] >= 55 else C_WARNING if stats["wr"] >= 40 else C_DANGER
                    _ar_c = NEON_GREEN if stats["avg_r"] > 0 else C_DANGER
                    return (
                        f'<div style="background:rgba(255,255,255,0.03);'
                        f'border:1px solid rgba(255,255,255,0.07);border-radius:var(--r-sm);'
                        f'padding:0.45rem 0.7rem;font-family:Share Tech Mono,monospace">'
                        f'<span style="font-size:var(--text-sm);color:{_wr_c};font-weight:700">'
                        f'{stats["wr"]:.0f}%</span>'
                        f'<span style="font-size:var(--text-xs);color:var(--text-dim);margin:0 0.4rem">WR</span>'
                        f'<span style="font-size:var(--text-xs);color:{_ar_c}">{stats["avg_r"]:+.2f}R</span>'
                        f'<span style="font-size:var(--text-2xs);color:var(--text-dim);margin-left:0.4rem">'
                        f'({stats["n"]} trades)</span>'
                        f'</div>'
                    )

                _rc0, _rc1, _rc2, _rc3 = st.columns([1, 3, 3, 2])
                with _rc0:
                    st.markdown(
                        f'<div style="background:{_gc}18;border:1px solid {_gc}40;'
                        f'border-radius:var(--r-sm);padding:0.45rem 0.5rem;text-align:center;'
                        f'font-family:Orbitron,monospace;font-size:var(--text-base);'
                        f'font-weight:900;color:{_gc}">{_g}</div>',
                        unsafe_allow_html=True,
                    )
                with _rc1:
                    st.markdown(_cell(_pg, NEON_GREEN), unsafe_allow_html=True)
                with _rc2:
                    st.markdown(_cell(_rg, C_INFO), unsafe_allow_html=True)
                with _rc3:
                    st.markdown(
                        f'<div style="padding:0.45rem 0.7rem;font-family:Share Tech Mono,monospace;'
                        f'font-size:var(--text-sm);font-weight:700;color:{_dwr_col}">{_dwr_str}</div>',
                        unsafe_allow_html=True,
                    )

        # ── Insight generator ─────────────────────────────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        _sec("INSIGHTS OTOMATIS")

        _insights = []

        # Grade A win rate comparison
        _pa = [t for t in _paper_closed if t.get("_derived_grade") in ("A+","A")]
        _ra = [t for t in _real_closed  if t.get("_derived_grade") in ("A+","A")]
        if len(_pa) >= 3 and len(_ra) >= 3:
            _pa_wr = sum(1 for t in _pa if t.get("outcome")=="WIN") / len(_pa) * 100
            _ra_wr = sum(1 for t in _ra if t.get("outcome")=="WIN") / len(_ra) * 100
            if _ra_wr >= _pa_wr - 5:
                _insights.append(("✓", NEON_GREEN,
                    f"Grade A setup: paper {_pa_wr:.0f}% vs real {_ra_wr:.0f}% — "
                    f"konsisten. Setup Grade A bisa dipercaya."))
            else:
                _insights.append(("⚠", C_WARNING,
                    f"Grade A setup: paper {_pa_wr:.0f}% vs real {_ra_wr:.0f}% — "
                    f"gap {_pa_wr-_ra_wr:.0f}%. Review eksekusi atau sizing saat Grade A."))

        # Grade B vs A real comparison
        _rb = [t for t in _real_closed if t.get("_derived_grade") == "B"]
        if len(_ra) >= 3 and len(_rb) >= 3:
            _rb_wr = sum(1 for t in _rb if t.get("outcome")=="WIN") / len(_rb) * 100
            _ra_wr2 = sum(1 for t in _ra if t.get("outcome")=="WIN") / len(_ra) * 100
            if _ra_wr2 - _rb_wr > 15:
                _insights.append(("✓", NEON_GREEN,
                    f"Grade A real WR {_ra_wr2:.0f}% vs Grade B {_rb_wr:.0f}% — "
                    f"gap {_ra_wr2-_rb_wr:.0f}%. Filter Grade B dari portfolio."))
            else:
                _insights.append(("·", C_INFO,
                    f"Grade A dan B real WR mirip ({_ra_wr2:.0f}% vs {_rb_wr:.0f}%). "
                    f"Grade filter belum terbukti differentiator kuat."))

        # Low grade trades
        _rdf = [t for t in _real_closed if t.get("_derived_grade") in ("D","F")]
        if _rdf:
            _rdf_loss = sum(1 for t in _rdf if t.get("outcome")=="LOSS")
            _insights.append(("⛔", C_DANGER,
                f"{len(_rdf)} real trade Grade D/F — {_rdf_loss} loss. "
                f"Hapus trades Grade D/F dari strategi."))

        # Overall verdict
        if _r_total >= 10:
            if _r_exp > 0 and _r_wr >= 50:
                _insights.append(("✅", NEON_GREEN,
                    f"Sistem menguntungkan: real WR {_r_wr:.0f}%, avg {_r_exp:+.2f}R/trade. "
                    f"Fokus scale up setup yang sudah proven."))
            elif _r_exp <= 0:
                _insights.append(("⛔", C_DANGER,
                    f"Expectancy negatif ({_r_exp:+.2f}R). Review Post-Mortem tab untuk "
                    f"identifikasi pola loss yang berulang."))

        if not _insights:
            st.markdown(
                _mono("Butuh minimal 5–10 closed trades per sumber untuk generate insights.",
                      "var(--text-muted)"),
                unsafe_allow_html=True,
            )
        else:
            for _ico, _ic, _msg in _insights:
                st.markdown(
                    f'<div style="background:rgba(0,0,0,0.2);border:1px solid {_ic}25;'
                    f'border-left:3px solid {_ic};border-radius:var(--r-sm);'
                    f'padding:0.45rem 0.9rem;margin-bottom:0.35rem;'
                    f'font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
                    f'display:flex;gap:0.7rem;align-items:flex-start">'
                    f'<span style="color:{_ic};font-weight:700;min-width:16px">{_ico}</span>'
                    f'<span style="color:#94A3B8;line-height:1.6">{_msg}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 8 — BACKTESTING: Win Rate per Whale Quality / Conviction / Signal
# ══════════════════════════════════════════════════════════════════════════════
with t_backtest:
    import sqlite3 as _bt_sqlite
    import pandas as _bt_pd

    st.markdown("""<p style="font-family:Share Tech Mono,monospace;font-size:var(--text-xs);
    color:var(--text-muted);letter-spacing:0.08em;margin-bottom:1rem">
    Audit predictive accuracy — win rate per whale quality, conviction bracket, signal type, regime
    </p>""", unsafe_allow_html=True)

    # ── Load closed trades ────────────────────────────────────────────────────
    try:
        _bt_conn = _bt_sqlite.connect(str(DB_PATH))
        _bt_conn.row_factory = _bt_sqlite.Row
        _bt_rows = _bt_conn.execute("""
            SELECT ticker, outcome, pnl_r, pnl_pct, signal_type, signal_score,
                   regime_tag, whale_quality, whale_conviction, strategy,
                   entry_date, exit_date, bars_held
            FROM manual_trades
            WHERE outcome IN ('WIN','LOSS','BREAKEVEN')
            ORDER BY exit_date DESC
        """).fetchall()
        _bt_conn.close()
        _bt_df = _bt_pd.DataFrame([dict(r) for r in _bt_rows])
    except Exception as _bt_e:
        _bt_df = _bt_pd.DataFrame()
        st.error(f"Error load data: {_bt_e}")

    if _bt_df.empty:
        st.info("Belum ada closed trades. Log dan close beberapa trade dulu untuk melihat backtesting analysis.")
    else:
        _bt_total = len(_bt_df)
        _bt_wins  = (_bt_df["outcome"] == "WIN").sum()
        _bt_wr    = _bt_wins / _bt_total * 100
        _bt_exp   = _bt_df["pnl_r"].mean() if "pnl_r" in _bt_df else 0

        # ── Summary metrics ───────────────────────────────────────────────────
        _mc1, _mc2, _mc3, _mc4 = st.columns(4)
        with _mc1:
            st.markdown(_metric_box("Total Trades", str(_bt_total), "closed"), unsafe_allow_html=True)
        with _mc2:
            _wr_col = NEON_GREEN if _bt_wr >= 50 else C_DANGER
            st.markdown(_metric_box("Win Rate", f"{_bt_wr:.0f}%", f"{_bt_wins}W/{_bt_total-_bt_wins}L", _wr_col), unsafe_allow_html=True)
        with _mc3:
            _exp_col = NEON_GREEN if _bt_exp > 0 else C_DANGER
            st.markdown(_metric_box("Expectancy", f"{_bt_exp:+.2f}R", "avg per trade", _exp_col), unsafe_allow_html=True)
        with _mc4:
            _whale_trades = _bt_df[_bt_df["whale_quality"].notna() & (_bt_df["whale_quality"] != "")].shape[0]
            st.markdown(_metric_box("Whale Tracked", str(_whale_trades), f"dari {_bt_total} trades"), unsafe_allow_html=True)

        st.markdown("<div style='margin:1rem 0'></div>", unsafe_allow_html=True)

        # ── Helper: render breakdown table ───────────────────────────────────
        def _bt_breakdown(df: "_bt_pd.DataFrame", col: str, label: str) -> None:
            if col not in df.columns:
                return
            _grp = df[df[col].notna() & (df[col] != "")].groupby(col)
            if _grp.ngroups == 0:
                st.markdown(_mono(f"Tidak ada data {label} tersimpan di trade log."), unsafe_allow_html=True)
                return

            rows_html = ""
            for _val, _g in sorted(_grp, key=lambda x: -len(x[1])):
                _n   = len(_g)
                _w   = (_g["outcome"] == "WIN").sum()
                _wr  = _w / _n * 100 if _n > 0 else 0
                _exp = _g["pnl_r"].mean() if "pnl_r" in _g else 0
                _wr_col  = "#00FF66" if _wr >= 55 else "#F0B429" if _wr >= 45 else "#EF4444"
                _exp_col = "#00FF66" if _exp > 0 else "#EF4444"
                rows_html += (
                    f'<tr>'
                    f'<td style="padding:6px 10px;color:#E2E8F0;font-weight:500">{_val}</td>'
                    f'<td style="padding:6px 10px;color:#94A3B8;text-align:center">{_n}</td>'
                    f'<td style="padding:6px 10px;color:{_wr_col};text-align:center;font-weight:700">{_wr:.0f}%</td>'
                    f'<td style="padding:6px 10px;color:{_exp_col};text-align:center">{_exp:+.2f}R</td>'
                    f'<td style="padding:6px 10px;text-align:center">'
                    f'<div style="background:rgba(0,255,102,0.15);border-radius:3px;height:8px;width:100%;max-width:80px;margin:auto">'
                    f'<div style="background:#00FF66;border-radius:3px;height:8px;width:{min(_wr,100):.0f}%"></div>'
                    f'</div></td>'
                    f'</tr>'
                )

            st.markdown(
                f'<div style="margin-bottom:0.5rem;font-family:Share Tech Mono,monospace;'
                f'font-size:var(--text-xs);color:var(--text-muted);letter-spacing:0.08em">{label}</div>'
                f'<table style="width:100%;border-collapse:collapse;font-family:Share Tech Mono,monospace;font-size:var(--text-xs)">'
                f'<thead><tr style="border-bottom:1px solid rgba(255,255,255,0.08)">'
                f'<th style="padding:6px 10px;color:#64748B;text-align:left">{label}</th>'
                f'<th style="padding:6px 10px;color:#64748B;text-align:center">N</th>'
                f'<th style="padding:6px 10px;color:#64748B;text-align:center">Win Rate</th>'
                f'<th style="padding:6px 10px;color:#64748B;text-align:center">Avg R</th>'
                f'<th style="padding:6px 10px;color:#64748B;text-align:center">WR Bar</th>'
                f'</tr></thead>'
                f'<tbody>{rows_html}</tbody>'
                f'</table>',
                unsafe_allow_html=True
            )

        # ── Breakdown 1: Whale Quality ─────────────────────────────────────
        _sec("◆ WIN RATE PER WHALE QUALITY")
        st.caption("Apakah SMART lebih baik dari LIKELY_SMART? Data ini menjawabnya.")

        _wq_order = {"SMART": 0, "LIKELY_SMART": 1, "UNCERTAIN": 2, "DUMB": 3}
        _bt_wq = _bt_df.copy()
        _bt_wq["_sort"] = _bt_wq["whale_quality"].map(_wq_order).fillna(9)
        _bt_wq = _bt_wq.sort_values("_sort")
        _bt_breakdown(_bt_wq, "whale_quality", "Whale Quality")

        st.markdown("<div style='margin:1.2rem 0'></div>", unsafe_allow_html=True)

        # ── Breakdown 2: Conviction Bracket ───────────────────────────────
        _sec("◆ WIN RATE PER CONVICTION BRACKET")
        st.caption("Apakah conviction tinggi = win rate lebih tinggi?")

        def _conv_bracket(v):
            if _bt_pd.isna(v) or v == 0: return None
            if v >= 8: return "8-10 (High)"
            if v >= 6: return "6-7 (Medium-High)"
            if v >= 4: return "4-5 (Medium)"
            return "1-3 (Low)"

        _bt_cb = _bt_df.copy()
        _bt_cb["conv_bracket"] = _bt_cb["whale_conviction"].apply(_conv_bracket)
        _bt_breakdown(_bt_cb, "conv_bracket", "Conviction Bracket")

        st.markdown("<div style='margin:1.2rem 0'></div>", unsafe_allow_html=True)

        # ── Breakdown 3: Signal Type ──────────────────────────────────────
        _sec("◆ WIN RATE PER SIGNAL TYPE")
        st.caption("ACCUMULATION vs RECOVERY_EARLY vs BLOCK_BUY — mana yang lebih reliabel?")
        _bt_breakdown(_bt_df, "signal_type", "Signal Type")

        st.markdown("<div style='margin:1.2rem 0'></div>", unsafe_allow_html=True)

        # ── Breakdown 4: Regime ───────────────────────────────────────────
        _sec("◆ WIN RATE PER MARKET REGIME")
        st.caption("Setup yang sama bisa berbeda hasilnya di regime yang berbeda.")
        _bt_breakdown(_bt_df, "regime_tag", "Market Regime")

        st.markdown("<div style='margin:1.2rem 0'></div>", unsafe_allow_html=True)

        # ── Breakdown 5: Strategy (FOLLOW_WHALE vs EMA_XBO) ──────────────
        _sec("◆ WIN RATE PER STRATEGY")
        st.caption("Follow Whale vs EMA XBO — mana yang lebih profitable?")
        _bt_breakdown(_bt_df, "strategy", "Strategy")

        st.markdown("<div style='margin:1.2rem 0'></div>", unsafe_allow_html=True)

        # ── Actionable Insights ───────────────────────────────────────────
        _sec("◆ INSIGHTS OTOMATIS")
        _bt_insights = []

        # Insight 1: whale quality terbaik
        _wq_grp = _bt_df[_bt_df["whale_quality"].notna() & (_bt_df["whale_quality"] != "")].groupby("whale_quality")
        for _wq, _wqg in _wq_grp:
            if len(_wqg) >= 5:
                _wqwr = (_wqg["outcome"] == "WIN").sum() / len(_wqg) * 100
                if _wqwr >= 60:
                    _bt_insights.append(("✅", NEON_GREEN,
                        f"Whale quality '{_wq}' win rate {_wqwr:.0f}% dari {len(_wqg)} trades — "
                        f"prioritaskan setup dengan label ini."))
                elif _wqwr < 40:
                    _bt_insights.append(("⛔", C_DANGER,
                        f"Whale quality '{_wq}' win rate hanya {_wqwr:.0f}% dari {len(_wqg)} trades — "
                        f"pertimbangkan skip setup dengan label ini."))

        # Insight 2: conviction sweet spot
        _cb_grp = _bt_cb[_bt_cb["conv_bracket"].notna()].groupby("conv_bracket")
        _best_bracket = None
        _best_wr = 0
        for _cb, _cbg in _cb_grp:
            if len(_cbg) >= 5:
                _cbwr = (_cbg["outcome"] == "WIN").sum() / len(_cbg) * 100
                if _cbwr > _best_wr:
                    _best_wr = _cbwr
                    _best_bracket = _cb
        if _best_bracket and _best_wr >= 55:
            _bt_insights.append(("🎯", "#F0B429",
                f"Conviction sweet spot: '{_best_bracket}' punya win rate tertinggi {_best_wr:.0f}% — "
                f"fokus di range ini."))

        # Insight 3: follow whale vs ema_xbo
        _strat_grp = _bt_df[_bt_df["strategy"].notna()].groupby("strategy")
        _strat_stats = {}
        for _st, _stg in _strat_grp:
            if len(_stg) >= 3:
                _strat_stats[_st] = (_stg["outcome"] == "WIN").sum() / len(_stg) * 100
        if "FOLLOW_WHALE" in _strat_stats and "EMA_XBO" in _strat_stats:
            _diff = _strat_stats["FOLLOW_WHALE"] - _strat_stats["EMA_XBO"]
            if abs(_diff) >= 10:
                _better = "FOLLOW_WHALE" if _diff > 0 else "EMA_XBO"
                _bt_insights.append(("📊", "#94A3B8",
                    f"Strategy '{_better}' outperform {abs(_diff):.0f}% lebih tinggi — "
                    f"alokasikan lebih banyak ke strategy ini."))

        if not _bt_insights:
            if _bt_total < 10:
                st.markdown(_mono(
                    f"Butuh minimal 10 closed trades per kategori untuk generate insights yang reliable. "
                    f"Sekarang ada {_bt_total} trades total.",
                    "var(--text-muted)"), unsafe_allow_html=True)
            else:
                st.markdown(_mono("Belum ada pola yang cukup kuat untuk generate insight. Terus trade dan close posisi.", "var(--text-muted)"), unsafe_allow_html=True)
        else:
            for _ico, _ic, _msg in _bt_insights:
                st.markdown(
                    f'<div style="background:rgba(0,0,0,0.2);border:1px solid {_ic}25;'
                    f'border-left:3px solid {_ic};border-radius:var(--r-sm);'
                    f'padding:0.45rem 0.9rem;margin-bottom:0.35rem;'
                    f'font-family:Share Tech Mono,monospace;font-size:var(--text-xs);'
                    f'display:flex;gap:0.7rem;align-items:flex-start">'
                    f'<span style="color:{_ic};font-weight:700;min-width:16px">{_ico}</span>'
                    f'<span style="color:#94A3B8;line-height:1.6">{_msg}</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )
