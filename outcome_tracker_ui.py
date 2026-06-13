"""
Simple Trading V6.3.2 — Outcome Tracker UI (Shared Component)
==============================================================
Digunakan oleh:
  - pages/1_EMA_XBO.py
  - pages/2_Follow_Whale.py
  - pages/3_Stock_Analysis.py

Perubahan V6.3.2:
  - Hapus arrow icon (▾/▸), ganti dengan ikon Streamlit native
  - Tambah tombol DELETE trade (bukan close — untuk salah input)
  - Input manual dengan custom date (lupa input)
  - Semua page bisa akses tracker lewat fungsi ini
"""

import streamlit as st
import pandas as pd
from datetime import date, datetime
from pathlib import Path


NEON_GREEN = "#00ff66"
MONO_FONT  = "Share Tech Mono, monospace"


def _mono(text: str, color: str = "#9ca3af", size: str = "0.63rem") -> str:
    return (f'<span style="font-family:{MONO_FONT};font-size:{size};'
            f'letter-spacing:0.04em;color:{color}">{text}</span>')


def render_outcome_tracker(
    prefill_results: list = None,
    default_strategy: str = "EMA_XBO",
    signal_type_opts: list = None,
    page_key: str = "ema",
):
    """
    Render full Outcome Tracker widget.

    Args:
        prefill_results:  list of scan result dicts (untuk auto-fill ticker)
        default_strategy: "EMA_XBO" atau "WHALE_HENGKY"
        signal_type_opts: override daftar signal types
        page_key:         prefix unik untuk session_state keys (hindari clash antar pages)
    """
    try:
        from trade_logger import (
            init_db, log_trade, log_trade_manual, close_trade,
            delete_trade, get_open_trades, get_closed_trades, get_stats,
        )
    except ImportError as e:
        st.warning(f"trade_logger tidak bisa diimpor: {e}")
        return

    init_db()

    if signal_type_opts is None:
        if default_strategy == "WHALE_HENGKY":
            signal_type_opts = ["ACCUMULATION","BLOCK_BUY","RECOVERY_EARLY",
                                "VOL_SPIKE_UP","PENGERINGAN","CUSTOM"]
        else:
            signal_type_opts = ["BREAKOUT","WATCHLIST","CORRECTING","DEEP_CORRECT","CUSTOM"]

    # ── Tab layout ───────────────────────────────────────────────────────
    t1, t2, t3, t4 = st.tabs([
        "📥 Log Trade",
        "📋 Open Trades",
        "📊 Performance",
        "✏️ Input Manual",
    ])

    # ── TAB 1: Log Trade Baru ────────────────────────────────────────────
    with t1:
        st.markdown(_mono("Catat sinyal yang dieksekusi hari ini:"), unsafe_allow_html=True)
        st.markdown("")

        # Ticker selector
        if prefill_results:
            ticker_opts = ["— ketik manual —"] + sorted(set(
                r.get("ticker","").replace(".JK","")
                for r in prefill_results
                if r.get("signal") not in (None, "NONE", "")
            ))
        else:
            ticker_opts = ["— ketik manual —"]

        col_tk, col_sg = st.columns([2, 2])
        with col_tk:
            sel_ticker = st.selectbox("Ticker dari scan", ticker_opts,
                                       key=f"{page_key}_log_ticker")
        with col_sg:
            sel_sig = st.selectbox("Signal type", signal_type_opts,
                                    key=f"{page_key}_log_sig")

        # Manual ticker input jika pilih manual
        manual_ticker = ""
        if sel_ticker == "— ketik manual —":
            manual_ticker = st.text_input("Ticker (ketik manual)",
                                           placeholder="contoh: BBCA",
                                           key=f"{page_key}_manual_tk").upper().strip()

        final_ticker = manual_ticker if sel_ticker == "— ketik manual —" else sel_ticker

        # Auto-fill dari scan result
        prefill = {}
        if prefill_results and final_ticker:
            prefill = next((r for r in prefill_results
                           if r.get("ticker","").replace(".JK","") == final_ticker), {})

        col_e, col_sl, col_tp = st.columns(3)
        with col_e:
            entry_val = float(prefill.get("close", prefill.get("entry_price", 0)))
            entry_price = st.number_input("Entry Price (Rp)",
                                           value=entry_val, min_value=0.0,
                                           key=f"{page_key}_log_entry")
        with col_sl:
            sl_val = float(prefill.get("sl_price", prefill.get("floor_price",
                           entry_val * 0.93 if entry_val else 0)))
            sl_price = st.number_input("Stop Loss (Rp)",
                                        value=sl_val, min_value=0.0,
                                        key=f"{page_key}_log_sl")
        with col_tp:
            tp_val = float(prefill.get("tp1_price", 0))
            tp_price = st.number_input("TP1 (Rp, opsional)",
                                        value=tp_val, min_value=0.0,
                                        key=f"{page_key}_log_tp")

        # Risk display
        if entry_price > 0 and sl_price > 0 and sl_price < entry_price:
            risk_pct = (entry_price - sl_price) / entry_price * 100
            risk_col = ("#ef4444" if risk_pct > 25 else
                        "#f0b429" if risk_pct > 15 else NEON_GREEN)
            st.markdown(_mono(f"Risk: {risk_pct:.1f}% per trade", risk_col),
                         unsafe_allow_html=True)

        notes = st.text_input("Notes (opsional)", placeholder="contoh: floor price kuat, vol 3x",
                               key=f"{page_key}_log_notes")

        if st.button("✅ LOG TRADE", key=f"{page_key}_btn_log", type="primary"):
            if not final_ticker:
                st.error("Masukkan ticker terlebih dahulu.")
            elif entry_price <= 0 or sl_price <= 0:
                st.error("Entry price dan Stop Loss harus diisi.")
            elif sl_price >= entry_price:
                st.error("Stop Loss harus di bawah Entry Price.")
            else:
                score_v  = int(prefill.get("score", prefill.get("conviction", 0)))
                regime_v = prefill.get("regime_tag", "")
                mcf_v    = int(prefill.get("mcf_score", 0))
                trade_id = log_trade(
                    ticker       = final_ticker,
                    entry_price  = entry_price,
                    sl_price     = sl_price,
                    tp1_price    = tp_price,
                    signal_type  = sel_sig,
                    signal_score = score_v,
                    regime_tag   = regime_v,
                    mcf_score    = mcf_v,
                    strategy     = default_strategy,
                    notes        = notes,
                )
                st.success(f"✅ Trade #{trade_id} — {final_ticker} @ Rp{entry_price:,.0f} berhasil di-log!")

    # ── TAB 2: Open Trades ───────────────────────────────────────────────
    with t2:
        open_trades = get_open_trades()

        if not open_trades:
            st.info("Belum ada open trades. Log trade di tab 'Log Trade'.")
        else:
            st.markdown(_mono(f"{len(open_trades)} open trade(s):"), unsafe_allow_html=True)
            st.markdown("")

            for t in open_trades:
                tid     = t["id"]
                tkr     = t.get("ticker", "?")
                ep      = t.get("entry_price", 0)
                sl      = t.get("sl_price", 0)
                ed      = t.get("entry_date", "")
                stype   = t.get("signal_type", "—")
                score   = t.get("signal_score", 0)

                # Header untuk setiap trade card
                with st.container(border=True):
                    hc1, hc2 = st.columns([5, 1])
                    with hc1:
                        st.markdown(
                            f'<span style="font-family:{MONO_FONT};font-size:0.8rem;'
                            f'font-weight:700;color:{NEON_GREEN}">{tkr}</span>'
                            f'<span style="font-family:{MONO_FONT};font-size:0.65rem;'
                            f'color:#9ca3af"> &nbsp;·&nbsp; Entry Rp{ep:,.0f}'
                            f' &nbsp;·&nbsp; {ed}'
                            f' &nbsp;·&nbsp; {stype}</span>',
                            unsafe_allow_html=True
                        )
                    with hc2:
                        # DELETE button (merah, kecil)
                        if st.button("🗑 hapus", key=f"{page_key}_del_{tid}",
                                     help="Hapus trade ini (salah input)"):
                            st.session_state[f"{page_key}_confirm_del_{tid}"] = True

                    # Confirm delete dialog
                    if st.session_state.get(f"{page_key}_confirm_del_{tid}"):
                        st.warning(
                            f"⚠ Hapus trade #{tid} ({tkr})? "
                            "Ini akan menghapus permanen dari database."
                        )
                        dc1, dc2 = st.columns(2)
                        with dc1:
                            if st.button(f"✅ Ya, hapus #{tid}",
                                         key=f"{page_key}_yes_del_{tid}",
                                         type="primary"):
                                res = delete_trade(tid)
                                if res["success"]:
                                    st.success(f"Trade #{tid} dihapus.")
                                    del st.session_state[f"{page_key}_confirm_del_{tid}"]
                                    st.rerun()
                                else:
                                    st.error(res.get("error","Gagal menghapus."))
                        with dc2:
                            if st.button(f"❌ Batal", key=f"{page_key}_no_del_{tid}"):
                                del st.session_state[f"{page_key}_confirm_del_{tid}"]
                                st.rerun()

                    # Metrics row
                    mc1, mc2, mc3 = st.columns(3)
                    mc1.metric("Entry", f"Rp{ep:,.0f}")
                    mc2.metric("Stop Loss", f"Rp{sl:,.0f}")
                    mc3.metric("Score", f"{score}" if score else "—")

                    # Close trade form
                    st.markdown(_mono("Close trade:", "#6b7280", "0.6rem"),
                                 unsafe_allow_html=True)
                    fc1, fc2, fc3 = st.columns([3, 2, 2])
                    with fc1:
                        exit_price = st.number_input(
                            f"Exit Price", min_value=0.0,
                            key=f"{page_key}_exit_{tid}")
                    with fc2:
                        outcome_sel = st.selectbox(
                            "Outcome", ["WIN", "LOSS", "BREAKEVEN"],
                            key=f"{page_key}_oc_{tid}")
                    with fc3:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if st.button(f"✅ Close #{tid}",
                                     key=f"{page_key}_close_{tid}"):
                            if exit_price > 0:
                                result = close_trade(tid, exit_price, outcome_sel)
                                if result["success"]:
                                    pnl_r   = result.get("pnl_r", 0) or 0
                                    pnl_pct = result.get("pnl_pct", 0) or 0
                                    ok_col  = (NEON_GREEN if outcome_sel == "WIN"
                                               else "#ef4444")
                                    st.markdown(
                                        _mono(
                                            f"{outcome_sel}: {pnl_r:+.2f}R "
                                            f"({pnl_pct:+.1f}%)",
                                            ok_col, "0.72rem"
                                        ),
                                        unsafe_allow_html=True,
                                    )
                                    st.rerun()
                                else:
                                    st.error(result.get("error"))
                            else:
                                st.error("Masukkan exit price terlebih dahulu.")

    # ── TAB 3: Performance ───────────────────────────────────────────────
    with t3:
        stats = get_stats()
        n     = stats.get("total_closed", 0)
        n_open = stats.get("total_open", 0)

        # Summary cards
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Closed", f"{n}/30")
        c2.metric("Open",   f"{n_open}")
        c3.metric("Win Rate",
                   f"{stats['win_rate']:.1f}%" if stats.get("win_rate") is not None else "N/A")
        c4.metric("Expectancy",
                   f"{stats['expectancy']:+.3f}R" if stats.get("expectancy") is not None else "N/A")

        # Progress bar
        st.progress(min(n / 30, 1.0),
                     text=f"{n}/30 trades untuk validasi penuh")

        if n == 0:
            st.markdown(
                '<div style="background:rgba(239,68,68,.08);border:1px solid '
                'rgba(239,68,68,.3);border-radius:4px;padding:.9rem 1.1rem;margin-top:1rem">'
                '<div style="font-family:Orbitron,monospace;font-size:.68rem;'
                'font-weight:700;color:#ef4444;margin-bottom:.4rem">'
                '⚠ ZERO CLOSED TRADES</div>'
                '<div style="font-family:Share Tech Mono,monospace;font-size:.6rem;'
                'color:#9ca3af">Mulai catat trade. Minimal 30 closed trades '
                'diperlukan untuk validasi edge.</div></div>',
                unsafe_allow_html=True
            )
        else:
            # Status badge
            if stats.get("sufficient"):
                st.success(f"✅ {stats.get('note','')}")
            else:
                st.warning(f"⚠ {stats.get('note','')}")

            # Extra stats if enough data
            if n >= 3:
                e2a, e2b, e2c = st.columns(3)
                e2a.metric("Avg R", f"{stats['avg_r']:+.2f}R" if stats.get("avg_r") is not None else "N/A")
                e2b.metric("Profit Factor",
                            f"{stats['profit_factor']:.2f}" if stats.get("profit_factor") else "N/A")
                e2c.metric("Max Loss Streak",
                            f"{stats.get('max_consec_loss', 0)}")

            if n >= 5:
                closed = get_closed_trades(30)
                rows = []
                for t in closed:
                    pnl_r = t.get("pnl_r")
                    pnl_p = t.get("pnl_pct")
                    rows.append({
                        "Tanggal": t.get("exit_date", ""),
                        "Ticker":  t.get("ticker", ""),
                        "Outcome": t.get("outcome", ""),
                        "P&L (R)": f"{pnl_r:+.2f}" if pnl_r is not None else "—",
                        "P&L (%)": f"{pnl_p:+.1f}%" if pnl_p is not None else "—",
                        "Signal":  t.get("signal_type", ""),
                        "Score":   t.get("signal_score", ""),
                    })
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    # ── TAB 4: Input Manual (lupa input) ────────────────────────────────
    with t4:
        st.markdown(
            _mono("Gunakan tab ini jika lupa input saat sinyal keluar.", "#9ca3af"),
            unsafe_allow_html=True
        )
        st.markdown(
            _mono("Bisa input tanggal entry di masa lalu.", "#6b7280", "0.6rem"),
            unsafe_allow_html=True
        )
        st.markdown("")

        mc1, mc2 = st.columns([2, 2])
        with mc1:
            m_ticker = st.text_input(
                "Ticker", placeholder="contoh: BBCA",
                key=f"{page_key}_m_ticker"
            ).upper().strip()
        with mc2:
            m_sig = st.selectbox(
                "Signal type", signal_type_opts,
                key=f"{page_key}_m_sig"
            )

        mec1, mec2, mec3, mec4, mec5 = st.columns([1,1,1,1,1])
        with mec1:
            m_entry = st.number_input("Entry Price (Rp)", min_value=0.0,
                                       key=f"{page_key}_m_entry")
        with mec2:
            m_sl = st.number_input("Stop Loss (Rp)", min_value=0.0,
                                    key=f"{page_key}_m_sl")
        with mec3:
            m_date = st.date_input("Tanggal Entry",
                                    value=date.today(),
                                    key=f"{page_key}_m_date")
        with mec4:
            m_strat = st.selectbox("Strategi",
                                    ["EMA_XBO", "WHALE_HENGKY", "MSCI", "CUSTOM"],
                                    index=0 if default_strategy == "EMA_XBO" else 1,
                                    key=f"{page_key}_m_strat")
        with mec5:
            m_score = st.number_input("Score (0–8)", min_value=0, max_value=8,
                                       value=0, step=1,
                                       key=f"{page_key}_m_score",
                                       help="Score EMA XBO atau conviction Whale saat entry")

        m_notes = st.text_input(
            "Notes", placeholder="konteks kenapa lupa input, atau detail setup",
            key=f"{page_key}_m_notes"
        )

        if m_entry > 0 and m_sl > 0 and m_sl < m_entry:
            risk_m = (m_entry - m_sl) / m_entry * 100
            risk_col_m = ("#ef4444" if risk_m > 25 else
                          "#f0b429" if risk_m > 15 else NEON_GREEN)
            st.markdown(_mono(f"Risk: {risk_m:.1f}%", risk_col_m), unsafe_allow_html=True)

        if st.button("✅ SIMPAN INPUT MANUAL", key=f"{page_key}_btn_manual",
                     type="primary"):
            if not m_ticker:
                st.error("Masukkan ticker.")
            elif m_entry <= 0 or m_sl <= 0:
                st.error("Entry price dan Stop Loss harus diisi.")
            elif m_sl >= m_entry:
                st.error("Stop Loss harus di bawah Entry Price.")
            else:
                tid = log_trade_manual(
                    ticker        = m_ticker,
                    entry_price   = m_entry,
                    sl_price      = m_sl,
                    entry_date    = m_date.strftime("%Y-%m-%d"),
                    signal_type   = m_sig,
                    signal_score  = int(m_score),
                    strategy      = m_strat,
                    notes         = m_notes,
                )
                st.success(
                    f"✅ Trade #{tid} — {m_ticker} @ Rp{m_entry:,.0f} "
                    f"(tgl: {m_date}) berhasil disimpan!"
                )
