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
import pandas as pd
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
from agents.golden_setup_scanner import GoldenSetupScanner4H
from agents.structure_scanner import StructureFreshScanner


def _bars_since_segment(val, label="hari sejak terbentuk", prefix=" | "):
    """v10.3.9 FIX: satu sumber kebenaran utk render bars_since_formed.
    Sebelum ini, kartu utama pakai `val or 0` (None jadi terbaca "0 hari" --
    tertukar dgn zona yg BENAR baru terbentuk hari ini) sementara panel
    detail (Ringkasan Analisis) sudah benar sembunyikan segmen kalau None.
    Root cause: dua jalur render terpisah tanpa helper bersama -> drift.
    None (data lama sblm migrasi kolom zone_scans) HARUS beda tampilan dr
    0 (data valid, memang baru terbentuk hari ini)."""
    if val is None:
        return ""
    return f"{prefix}{val} {label}"


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

def _load_latest_from_db():
    """v10.1.2: page dibuka -> tampilkan hasil scan TERAKHIR dari zone_scans
    (bukan re-run otomatis — scan penuh makan ~4 menit, memaksa itu tiap
    buka halaman bukan UX yang baik). Tombol RUN ZONE SCAN tetap tersedia
    utk data terbaru. Fail-safe: return (None, None) kalau DB/tabel kosong
    atau belum ada (mis. instalasi baru, belum pernah scan)."""
    try:
        import sqlite3
        conn = sqlite3.connect("logs/scan_history.db")
        latest_date = conn.execute(
            "SELECT MAX(scan_date) FROM zone_scans"
        ).fetchone()[0]
        if not latest_date:
            conn.close()
            return None, None

        rows = conn.execute("""
            SELECT ticker, close_price, status, conviction_pct, zone_top, zone_bottom,
                   bars_since_formed, retest_hold_days, base_pct, retest_pct,
                   vidya_pct, volume_pct, structure_pct, pk_board
            FROM zone_scans WHERE scan_date = ?
        """, (latest_date,)).fetchall()

        analyzed = len(rows)
        results = []
        for r in rows:
            (ticker, close, status, conv, ztop, zbot, bars_since, retest_days,
             base_pct, retest_pct, vidya_pct, vol_pct, struct_pct, pk) = r
            if status == "WATCHING" and conv and conv > 0:
                results.append({
                    "ticker": ticker, "close": close, "status": status,
                    "conviction_pct": conv, "zone_top": ztop, "zone_bottom": zbot,
                    "formed_bar_index": None, "bars_since_formed": bars_since,
                    "retest_hold_days": retest_days, "base_pct": base_pct,
                    "retest_pct": retest_pct, "vidya_pct": vidya_pct,
                    "volume_pct": vol_pct, "structure_pct": struct_pct,
                    "pk_board": bool(pk),
                })
        conn.close()
        results.sort(key=lambda r: -r["conviction_pct"])
        ctx = {
            "regime": regime_data.get("cycle", "UNKNOWN"), "scan_date": latest_date,
            "total_universe": analyzed, "analyzed": analyzed,
            "skipped_short_history": 0, "crashed": 0,
            "watching_count": len(results),
        }
        return results, ctx
    except Exception:
        return None, None


sec_head("SCAN CONTROLS")
c1, c2 = st.columns([2, 1])
with c1:
    run_btn = st.button("RUN ZONE SCAN", type="primary")
with c2:
    min_conv_ui = st.number_input("MIN CONVICTION %", 0, 100, 80, 5)

if run_btn:
    with st.spinner("Scanning universe... (~4-6 menit, unduh 2 tahun data harian)"):
        scanner = ZoneScanner()
        results, ctx = scanner.scan()
        st.session_state["zone_results"] = results
        st.session_state["zone_ctx"] = ctx

# v10.1.2: kalau belum pernah klik RUN sesi ini, muat hasil scan terakhir
# dari DB dulu (bukan biarkan kosong "belum ada hasil scan").
if "zone_results" not in st.session_state:
    _db_results, _db_ctx = _load_latest_from_db()
    if _db_results is not None:
        st.session_state["zone_results"] = _db_results
        st.session_state["zone_ctx"] = _db_ctx

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


def _floor_price_row(ticker: str, price_df) -> dict:
    """v10.3.5: hitung Floor Price/VWAP/%Floor/FF-Vol/Sector — REUSE
    estimate_floor_price() dari whale_scanner.py (fungsi murni, sudah teruji
    di produksi page 2), BUKAN reimplementasi baru. Sengaja TIDAK sertakan
    klasifikasi Whale (classify_whale_quality) — itu butuh 10+ field dari
    pipeline deteksi whale_scanner yg sama sekali tak dihasilkan engine
    VIDYA+SMC, beban komputasi dobel yg tak sepadan (disepakati bersama user)."""
    from agents.whale_scanner import estimate_floor_price, _IDX_SECTOR_MAP, _IDX_PREFIX_MAP
    close, vol, low = price_df["Close"], price_df["Volume"], price_df["Low"]
    fp = estimate_floor_price(close, vol, low)
    vol_ma20 = vol.rolling(20).mean()
    ff_vol = float(vol.iloc[-1] / vol_ma20.iloc[-1]) if vol_ma20.iloc[-1] > 0 else 0.0
    base_t = ticker.replace(".JK", "")
    sector = _IDX_SECTOR_MAP.get(base_t) or _IDX_PREFIX_MAP.get(base_t[:2], "OTHER")
    return {
        "floor_price": fp["floor_price"], "vwap_60d": fp["vwap_60d"],
        "pct_above_floor": fp["pct_above_floor"], "entry_zone": fp["entry_zone"],
        "entry_zone_label": fp["entry_zone_label"], "ff_vol": ff_vol, "sector": sector,
    }


if filtered:
    sec_head("FLOOR PRICE DETAILS")
    from core.data_feed import DataFeed
    _feed = DataFeed(timeframe="1d", period="2y")
    floor_rows = []
    for r in filtered:
        try:
            df = _feed.fetch(f"{r['ticker']}.JK")
            if df is None or len(df) < 21:
                continue
            if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                df = df.copy()
                df.columns = df.columns.get_level_values(0)
            fm = _floor_price_row(r["ticker"], df)
            floor_rows.append((r, fm))
        except Exception:
            continue

    if floor_rows:
        # v10.3.8: kembalikan entry_zone_label ASLI (dgn ikon ✅/❌/🎯/🟡 +
        # bahasa "Skip"/"Acceptable") sesuai permintaan user — pertimbangan
        # filosofis dari 10.3.6 (verdict floor-whale vs breakout-retest
        # VIDYA+SMC bisa saling bertentangan, lihat RGAS) TETAP berlaku scr
        # konsep, tapi user sudah paham konteks itu dan memilih tetap ingin
        # lihat info floor apa adanya sbg referensi tambahan, bukan dihapus.
        df_table = pd.DataFrame([
            {
                "Ticker": r["ticker"], "Price": r["close"], "Floor": fm["floor_price"],
                "VWAP60": fm["vwap_60d"], "%↑Floor": fm["pct_above_floor"],
                "Zone": fm["entry_zone_label"], "Conv": r["conviction_pct"],
                "FF-Vol×": fm["ff_vol"], "Sector": fm["sector"],
            }
            for r, fm in floor_rows
        ])
        # v10.3.8 BARU: st.dataframe native sortable (klik header kolom utk
        # urutkan) — ganti dari tabel HTML statis. Kolom numerik tetap
        # bertipe angka asli (bukan string pre-formatted) supaya sort-nya
        # numerik benar, formatting tampilan diatur via column_config.
        st.dataframe(
            df_table, hide_index=True, width="stretch",
            column_config={
                "Price": st.column_config.NumberColumn(format="Rp%d"),
                "Floor": st.column_config.NumberColumn(format="Rp%d"),
                "VWAP60": st.column_config.NumberColumn(format="Rp%d"),
                "%↑Floor": st.column_config.NumberColumn(format="%.1f%%"),
                "Conv": st.column_config.NumberColumn(format="%d%%"),
                "FF-Vol×": st.column_config.NumberColumn(format="%.1f×"),
            },
        )

    st.markdown("<br>", unsafe_allow_html=True)
    sec_head("RINGKASAN ANALISIS")
    st.caption("Framework Hengky: Signal -> EMA -> Floor -> Conviction -> Supply -> Action")
    _tickers_for_select = [r["ticker"] for r in filtered]
    _selected_ticker = st.selectbox(
        "Pilih saham untuk lihat ringkasan analisis",
        options=["-- pilih saham --"] + _tickers_for_select,
        index=0,
    )
    if _selected_ticker != "-- pilih saham --":
        _sel_r = next((r for r, _ in floor_rows if r["ticker"] == _selected_ticker), None)
        _sel_fm = next((fm for r, fm in floor_rows if r["ticker"] == _selected_ticker), None)
        if _sel_r and _sel_fm:
            zona_str = ("Rp{:,.0f} - Rp{:,.0f}".format(_sel_r["zone_bottom"], _sel_r["zone_top"])
                       if _sel_r["zone_top"] else "-")
            ext_pen = _sel_r.get("extension_penalty", 0) or 0
            ext_atr = _sel_r.get("extension_atr", 0) or 0
            ext_line = (
                f'<br><span style="color:{C_WARNING}">\u26a0 Extended move: '
                f'-{ext_pen} poin (harga {ext_atr:.1f}x ATR dari swing low awal)</span>'
                if ext_pen > 0 else ""
            )
            # v10.3.8 BARU: "in depth" — breakdown skor lengkap (BASE/RETEST/
            # VIDYA/VOL/STRUCT/EXT) sama spt di kartu utama, + info bars_since_
            # formed, ditambahkan ke Ringkasan Analisis (sebelumnya cuma
            # ringkasan angka final, tak ada rincian per-komponen di sini).
            def _mini_badge(label, val, color):
                op = "1" if val > 0 else "0.35"
                return (f'<span style="opacity:{op};border:1px solid {color};color:{color};'
                        f'border-radius:3px;padding:2px 8px;font-size:var(--text-xs);'
                        f'font-family:Share Tech Mono,monospace;margin-right:5px">'
                        f'{label} {val}%</span>')
            breakdown_html = (
                _mini_badge("BASE", _sel_r["base_pct"], NEON_GREEN) +
                _mini_badge("RETEST", _sel_r["retest_pct"], NEON_GREEN) +
                _mini_badge("VIDYA", _sel_r["vidya_pct"], C_INFO) +
                _mini_badge("VOL", _sel_r["volume_pct"], C_INFO) +
                _mini_badge("STRUCT", _sel_r["structure_pct"], C_WARNING) +
                (f'<span style="opacity:1;border:1px solid {C_DANGER};color:{C_DANGER};'
                 f'border-radius:3px;padding:2px 8px;font-size:var(--text-xs);'
                 f'font-family:Share Tech Mono,monospace;margin-right:5px">'
                 f'\u26a0 EXT -{ext_pen}%</span>' if ext_pen > 0 else "")
            )
            bars_since = _sel_r.get("bars_since_formed")
            bars_line = _bars_since_segment(bars_since, label="hari sejak zona terbentuk")
            detail_html = (
                '<div style="background:var(--bg-card);border-left:4px solid var(--accent);'
                'border-radius:var(--r-md);padding:1rem 1.2rem">'
                '<div style="display:flex;justify-content:space-between;align-items:center;'
                'flex-wrap:wrap;gap:0.5rem">'
                '<span style="font-family:Orbitron,monospace;font-size:var(--text-lg);'
                'font-weight:800">' + _sel_r["ticker"] + '</span>'
                '<span style="font-family:Share Tech Mono,monospace;color:var(--text-muted)">'
                'Rp' + '{:,.0f}'.format(_sel_r["close"]) + ' | Status: ' + _sel_r["status"] + '</span>'
                '</div>'
                '<div style="margin-top:0.6rem;font-family:Share Tech Mono,monospace;'
                'font-size:var(--text-sm);line-height:1.8">'
                f'Conviction: <b>{_sel_r["conviction_pct"]}%</b> | '
                f'Zona retest: {zona_str} | Retest {_sel_r["retest_hold_days"]}/2 hari{bars_line}{ext_line}<br>'
                f'Floor: Rp{_sel_fm["floor_price"]:,.0f} | VWAP60: Rp{_sel_fm["vwap_60d"]:,.0f} | '
                f'{_sel_fm["entry_zone_label"]} ({_sel_fm["pct_above_floor"]:+.1f}%)<br>'
                f'Sector: {_sel_fm["sector"]} | FF-Vol: {_sel_fm["ff_vol"]:.1f}\u00d7'
                '</div>'
                '<div style="margin-top:0.8rem;padding-top:0.6rem;border-top:1px solid rgba(255,255,255,0.08)">'
                + breakdown_html +
                '</div></div>'
            )

            st.markdown(detail_html, unsafe_allow_html=True)
        else:
            st.info("Data floor price ticker ini belum tersedia (kemungkinan riwayat harga kurang dari 21 hari).")

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

    def _penalty_badge(val):
        # v10.4.0 BARU — beda dari _badge biasa: ini PENGURANG skor, bukan
        # penambah, jadi tampilkan tanda minus + warna bahaya, dan HANYA
        # muncul kalau ada penalti (tak perlu tampilkan "EXTENSION 0%" di
        # tiap kartu, cuma bikin ramai tanpa informasi baru).
        if val <= 0:
            return ""
        return ('<span style="opacity:1;border:1px solid ' + C_DANGER +
               ';color:' + C_DANGER + ';border-radius:3px;padding:1px 6px;' +
               'font-size:var(--text-2xs);font-family:Share Tech Mono,monospace;' +
               'margin-right:4px" title="Extended move — harga sudah jauh dari swing low awal">'
               '\u26a0 EXT -' + str(val) + '%</span>')

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
                _badge("STRUCT", r["structure_pct"], C_WARNING) +
                _penalty_badge(r.get("extension_penalty", 0) or 0)
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
                _bars_since_segment(r.get('bars_since_formed')) + ' ' + pk_tag +
                '</div>'
                '<div style="margin-top:0.5rem">' + badges + '</div>'
                '</div>'
            )
            st.markdown(card_html, unsafe_allow_html=True)

st.markdown("<br><br>", unsafe_allow_html=True)
st.caption("Retest-only path: breakout tanpa pullback akan selalu bernilai conviction "
          "rendah dalam skema ini -- trade-off yang disengaja demi menyaring false breakout.")


# ═══════════════════════════════════════════════════════════════════════
# GOLDEN SETUP 4H (BETA) — Fase 4-3, v10.9.0
#
# SENGAJA section TERPISAH dari scan daily di atas — TIDAK menyentuh
# st.session_state["zone_results"]/["zone_ctx"], TIDAK menyentuh
# ZoneScanner/logs/scan_history.db sama sekali. Scope: 40 ticker
# IDX_WATCHLIST saja (BUKAN full universe) — fetch_4h() belum py caching/
# batching, full-universe blm pernah diuji skalanya (lihat docstring
# agents/golden_setup_scanner.py). Hasil scan session-only, TIDAK
# tersimpan ke DB (skema zone_scans blm py kolom utk field baru).
#
# Basis: VIDYA/trend Heikin Ashi (use_ha_trend=True, terbukti smooth thd
# harga real candlestick, lihat changelog v10.6.0), golden_setup_bonus
# (vidya_pct 15->20 saat zone_ordinal_since_flip==1, dikalibrasi 2 basis
# data konvergen — real n=656 & HA n=516, distribusi HAMPIR identik).
# ═══════════════════════════════════════════════════════════════════════
st.markdown("<br>", unsafe_allow_html=True)
sec_head("GOLDEN SETUP 4H (BETA)")
st.caption("Scan terpisah, khusus 40 ticker watchlist likuid — VIDYA baru belok hijau "
          "(basis Heikin Ashi) + zona retest pertama sejak flip. Belum tersimpan ke "
          "riwayat DB, hasil per-sesi browser saja.")

g_run_btn = st.button("SCAN GOLDEN SETUP 4H", type="secondary")

if g_run_btn:
    with st.spinner("Scanning 40 ticker watchlist (4H, basis Heikin Ashi)... ~1-2 menit"):
        g_scanner = GoldenSetupScanner4H()
        g_results, g_ctx = g_scanner.scan()
        st.session_state["golden4h_results"] = g_results
        st.session_state["golden4h_ctx"] = g_ctx

g_results = st.session_state.get("golden4h_results", [])
g_ctx = st.session_state.get("golden4h_ctx", {})

if not g_results and not g_ctx:
    render_empty_state("★", "BELUM ADA HASIL SCAN GOLDEN SETUP",
                       "Klik SCAN GOLDEN SETUP 4H utk memulai.", "")
else:
    gc1, gc2, gc3, gc4 = st.columns(4)
    gc1.metric("UNIVERSE", g_ctx.get("total_universe", 0))
    gc2.metric("DIANALISIS", g_ctx.get("analyzed", 0))
    gc3.metric("WATCHING", g_ctx.get("watching_count", 0))
    gc4.metric("★ GOLDEN SETUP", g_ctx.get("golden_count", 0))
    if g_ctx.get("skipped_short_history") or g_ctx.get("crashed"):
        st.caption(f"Skip data pendek: {g_ctx.get('skipped_short_history',0)} | "
                  f"Crash: {g_ctx.get('crashed',0)}")

    if not g_results:
        render_empty_state("◎", "TIDAK ADA ZONA WATCHING SAAT INI",
                           "Coba scan lagi nanti — kondisi pasar berubah tiap 4 jam.", "")
    else:
        # v10.9.0 FIX: helper badge di sini SENGAJA self-contained (definisi
        # sendiri, TIDAK reuse _badge/_penalty_badge dari section daily di
        # atas) -- fungsi2 itu cuma terdefinisi kalau `filtered` (hasil scan
        # daily) tidak kosong, krn didefinisikan di dalam cabang else-nya.
        # Kalau user buka halaman ini SEBELUM pernah scan daily / filter
        # conviction daily kosongkan hasil, _badge/_penalty_badge TIDAK
        # exist -- panggil dari section terpisah ini bakal NameError.
        # Section Golden Setup 4H harus berdiri sendiri, tidak boleh
        # bergantung nasib pada state section lain.
        def _golden_badge():
            return ('<span style="opacity:1;border:1px solid ' + C_WARNING +
                   ';color:' + C_WARNING + ';border-radius:3px;padding:1px 8px;'
                   'font-size:var(--text-2xs);font-family:Share Tech Mono,monospace;'
                   'margin-right:4px;font-weight:900">★ GOLDEN SETUP</span>')

        def _g_badge(label, val, active_color):
            col = active_color if val > 0 else LABEL_COLOR
            opacity = "1" if val > 0 else "0.35"
            return ('<span style="opacity:' + opacity + ';border:1px solid ' + col +
                   ';color:' + col + ';border-radius:3px;padding:1px 6px;' +
                   'font-size:var(--text-2xs);font-family:Share Tech Mono,monospace;' +
                   'margin-right:4px">' + label + ' ' + str(val) + '%</span>')

        def _g_penalty_badge(val):
            if val <= 0:
                return ""
            return ('<span style="opacity:1;border:1px solid ' + C_DANGER +
                   ';color:' + C_DANGER + ';border-radius:3px;padding:1px 6px;' +
                   'font-size:var(--text-2xs);font-family:Share Tech Mono,monospace;' +
                   'margin-right:4px" title="Extended move — harga sudah jauh dari swing low awal">'
                   '\u26a0 EXT -' + str(val) + '%</span>')

        g_cols = st.columns(2)
        for g_idx, gr in enumerate(g_results):
            g_col = g_cols[g_idx % 2]
            with g_col:
                g_cc = C_WARNING if gr["is_golden_setup"] else (
                    NEON_GREEN if gr["conviction_pct"] >= 75 else
                    (C_WARNING if gr["conviction_pct"] >= 40 else LABEL_COLOR)
                )
                g_zona_str = ("Rp{:,.0f} - Rp{:,.0f}".format(gr["zone_bottom"], gr["zone_top"])
                             if gr["zone_top"] else "-")
                g_badges = (
                    (_golden_badge() if gr["is_golden_setup"] else "") +
                    _g_badge("BASE", gr["base_pct"], NEON_GREEN) +
                    _g_badge("RETEST", gr["retest_pct"], NEON_GREEN) +
                    _g_badge("VIDYA", gr["vidya_pct"], C_INFO) +
                    _g_badge("VOL", gr["volume_pct"], C_INFO) +
                    _g_badge("STRUCT", gr["structure_pct"], C_WARNING) +
                    _g_penalty_badge(gr.get("extension_penalty", 0) or 0)
                )
                g_flip_ago = gr.get("bars_since_vidya_flip")
                g_flip_line = (f" | {g_flip_ago} bar sejak flip VIDYA"
                              if g_flip_ago is not None else "")
                g_card_html = (
                    '<div style="background:var(--bg-card);border:1px solid ' + g_cc + '55;'
                    'border-left:4px solid ' + g_cc + ';border-radius:var(--r-md);'
                    'padding:1rem 1.2rem;margin-bottom:0.8rem">'
                    '<div style="display:flex;justify-content:space-between;align-items:center">'
                    '<span style="font-family:Orbitron,monospace;font-size:var(--text-lg);'
                    'font-weight:800;color:#E2E8F0">' + gr['ticker'] + '</span>'
                    '<span style="font-family:Orbitron,monospace;font-size:var(--text-xl);'
                    'font-weight:900;color:' + g_cc + '">' + str(gr['conviction_pct']) + '%</span>'
                    '</div>'
                    '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);'
                    'color:var(--text-muted);margin:0.4rem 0">'
                    'Close Rp' + '{:,.0f}'.format(gr['close']) + ' | Zona ' + g_zona_str +
                    ' | Retest ' + str(gr['retest_hold_days']) + '/2 bar' + g_flip_line +
                    '</div>'
                    '<div style="margin-top:0.5rem">' + g_badges + '</div>'
                    '</div>'
                )
                st.markdown(g_card_html, unsafe_allow_html=True)

    st.caption("Golden Setup = zona retest PERTAMA sejak VIDYA belok hijau (basis Heikin "
              "Ashi) — proxy pola 'flip -> koreksi -> reversal' favorit. Bukan jaminan "
              "profit, tetap validasi manual sebelum entry.")


# ═══════════════════════════════════════════════════════════════════════
# BOS / CHoCH / EQL BIRU BARU TERBENTUK (BETA) — Fase 4-5, v10.9.3
#
# KOREKSI v10.9.2 dari v10.9.1: v10.9.1 salah paham syaratnya AND (ketiga
# event WAJIB muncul bareng) — user klarifikasi yang benar OR, CUKUP SALAH
# SATU dari {BOS, CHoCH, EQL} yang baru terbentuk. v10.9.1 juga masih ada
# section "CEK 1 TICKER" (single-ticker checker) di bawahnya — atas
# permintaan user, section itu DIHAPUS TOTAL, ini satu-satunya section
# BOS/CHoCH/EQL yang tersisa di halaman ini.
#
# v10.9.3 — dua penambahan atas permintaan user:
#   1. Hasil scan TERAKHIR sekarang di-load otomatis begitu page dibuka
#      (pola sama persis dgn _load_latest_from_db() ZONA AKTIF di atas) —
#      TIDAK perlu klik SCAN dulu tiap kunjungan. Butuh minimal 1x scan
#      pernah dijalankan (sama spt ZONA AKTIF) — kalau belum pernah sama
#      sekali, tetap tampil "BELUM ADA HASIL SCAN".
#   2. Filter (jendela freshness 1-5 hari, jenis event BOS/CHoCH/EQL) +
#      sort arah (terbaru/terlama dulu) di atas grid kartu — filter jalan
#      di data yang SUDAH di-scan (tidak re-scan ke universe), murni
#      Python-side di rerun Streamlit.
#
# Scan full universe (pola fetch_batch sama spt ZoneScanner, TERBUKTI aman
# utk skala penuh — BUKAN fetch_4h() spt Golden Setup 4H yg sengaja
# dibatasi 40 ticker). BOS/CHoCH: scope manapun (internal ATAU swing)
# dihitung. Logic deteksi ada di agents/structure_scanner.py
# (StructureFreshScanner) + core/structure_signals.py — SENGAJA independen:
# TIDAK menyentuh session_state zone_results/zone_ctx/golden4h_*, TIDAK
# menyentuh ZoneScanner/GoldenSetupScanner4H sama sekali. Persist ke tabel
# BARU structure_scans (agents/scan_logger.py) — TERPISAH dari zone_scans,
# nol resiko ke skema/tabel produksi lain.
# ═══════════════════════════════════════════════════════════════════════
st.markdown("<br>", unsafe_allow_html=True)
sec_head("BOS / CHoCH / EQL BIRU BARU TERBENTUK (BETA)")
st.caption("Scan full universe — cari saham yang SALAH SATU dari Internal/Swing BOS, "
          "CHoCH bullish, atau Equal Low (EQL) biru baru terbentuk dalam 5 hari bursa "
          "terakhir. Kartu menampilkan event mana saja yang match (bisa 1, 2, atau "
          "ketiganya sekaligus).")


def _load_latest_structure_from_db():
    """v10.9.3: page dibuka -> tampilkan hasil scan TERAKHIR dari
    structure_scans (bukan re-scan otomatis -- scan penuh makan ~4-6
    menit, memaksa itu tiap buka halaman bukan UX yang baik). Tombol SCAN
    tetap tersedia utk data terbaru. Pola sama persis dgn
    _load_latest_from_db() (ZONA AKTIF) di atas. Fail-safe: return
    (None, None) kalau DB/tabel belum ada (instalasi baru/belum pernah
    scan) atau kosong."""
    try:
        import sqlite3
        import json as _json
        conn = sqlite3.connect("logs/scan_history.db")
        latest_date = conn.execute(
            "SELECT MAX(scan_date) FROM structure_scans"
        ).fetchone()[0]
        if not latest_date:
            conn.close()
            return None, None

        rows = conn.execute(
            "SELECT raw_json FROM structure_scans WHERE scan_date = ?", (latest_date,)
        ).fetchall()
        results = [_json.loads(r[0]) for r in rows]

        ctx_row = conn.execute(
            "SELECT v FROM meta WHERE k='structure_scan_ctx'"
        ).fetchone()
        conn.close()

        results.sort(key=lambda r: r["freshness"])
        ctx = _json.loads(ctx_row[0]) if ctx_row else {
            "scan_date": latest_date, "match_count": len(results),
        }
        return results, ctx
    except Exception:
        return None, None


t_run_btn = st.button("SCAN STRUKTUR BARU (FULL UNIVERSE)", type="secondary")

if t_run_btn:
    with st.spinner("Scanning full universe (~4-6 menit, unduh 2 tahun data harian)..."):
        t_scanner = StructureFreshScanner()
        t_results, t_ctx = t_scanner.scan()
        st.session_state["structure_fresh_results"] = t_results
        st.session_state["structure_fresh_ctx"] = t_ctx

# v10.9.3: kalau belum pernah klik SCAN sesi ini, muat hasil scan terakhir
# dari DB dulu (bukan biarkan kosong "belum ada hasil scan").
if "structure_fresh_results" not in st.session_state:
    _db_t_results, _db_t_ctx = _load_latest_structure_from_db()
    if _db_t_results is not None:
        st.session_state["structure_fresh_results"] = _db_t_results
        st.session_state["structure_fresh_ctx"] = _db_t_ctx

t_results = st.session_state.get("structure_fresh_results", [])
t_ctx = st.session_state.get("structure_fresh_ctx", {})

if not t_results and not t_ctx:
    render_empty_state("⚡", "BELUM ADA HASIL SCAN",
                       "Klik SCAN STRUKTUR BARU (FULL UNIVERSE) utk memulai.", "")
else:
    tc1, tc2, tc3, tc4 = st.columns(4)
    tc1.metric("UNIVERSE", t_ctx.get("total_universe", 0))
    tc2.metric("DIANALISIS", t_ctx.get("analyzed", 0))
    tc3.metric("MATCH", t_ctx.get("match_count", 0))
    if t_ctx.get("skipped_short_history") or t_ctx.get("crashed"):
        st.caption(f"Skip data pendek: {t_ctx.get('skipped_short_history',0)} | "
                  f"Crash: {t_ctx.get('crashed',0)}")
    tc4.caption(f"Update: {t_ctx.get('scan_date', '-')}")

    if not t_results:
        render_empty_state("◎", "TIDAK ADA TICKER DENGAN EVENT BARU TERBENTUK",
                           "Coba scan lagi nanti — kondisi struktur berubah tiap hari bursa.", "")
    else:
        # --- Filter + sort (v10.9.3) — murni Python-side, tidak re-scan ---
        fc1, fc2, fc3 = st.columns([2, 2, 1])
        with fc1:
            t_day_range = st.slider(
                "Terbentuk berapa hari lalu", 1, 5, (1, 5), key="t_day_range",
                help="1 = hari ini, 5 = paling lama dalam window scan (5 hari bursa).",
            )
        with fc2:
            t_kind_filter = st.multiselect(
                "Jenis event", ["BOS", "CHoCH", "EQL"],
                default=["BOS", "CHoCH", "EQL"], key="t_kind_filter",
            )
        with fc3:
            t_sort_dir = st.selectbox(
                "Urutkan", ["Terbaru dulu", "Terlama dulu"], key="t_sort_dir",
            )

        _kind_display_to_internal = {"BOS": "BOS", "CHoCH": "CHOCH", "EQL": "EQL"}
        _selected_kinds = {_kind_display_to_internal[k] for k in t_kind_filter}
        _day_lo, _day_hi = t_day_range[0] - 1, t_day_range[1] - 1  # 1-5 (tampilan) -> 0-4 (freshness asli)

        t_filtered = [
            r for r in t_results
            if _day_lo <= r["freshness"] <= _day_hi
            and set(r.get("match_kinds", [])) & _selected_kinds
        ]
        t_filtered.sort(key=lambda r: r["freshness"], reverse=(t_sort_dir == "Terlama dulu"))

        if not t_kind_filter:
            st.info("Pilih minimal 1 jenis event di filter di atas.")
        elif not t_filtered:
            render_empty_state("◎", "TIDAK ADA HASIL SESUAI FILTER",
                               "Coba longgarkan rentang hari atau tambah jenis event.", "")
        else:
            st.caption(f"Menampilkan {len(t_filtered)} dari {len(t_results)} match.")

            # Self-contained (prinsip sama spt catatan v10.9.0 di section Golden
            # Setup 4H): helper badge di sini definisi sendiri, TIDAK reuse
            # _badge/_g_badge dari section lain — section ini harus tetap bisa
            # render biarpun section2 lain di atas belum pernah di-scan/kosong.
            def _t_freshness_color(days):
                if days <= 1:
                    return NEON_GREEN
                if days <= 3:
                    return C_INFO
                return C_WARNING

            def _t_event_badge(label, date_str, scope, days_ago, color):
                if date_str is None:
                    return ""  # event ini tidak match — jangan tampilkan badge-nya
                scope_tag = f" ({scope})" if scope else ""
                return ('<span style="opacity:1;border:1px solid ' + color + ';color:' + color +
                       ';border-radius:3px;padding:2px 8px;font-size:var(--text-2xs);'
                       'font-family:Share Tech Mono,monospace;margin-right:5px;margin-bottom:4px;'
                       'display:inline-block">' + label + scope_tag + ' · ' + date_str +
                       ' · ' + str(days_ago) + 'h lalu</span>')

            _bias_label_t = {1: "BULLISH", -1: "BEARISH", None: "-"}

            t_cols = st.columns(2)
            for t_idx, t_r in enumerate(t_filtered):
                t_col = t_cols[t_idx % 2]
                with t_col:
                    fc = _t_freshness_color(t_r["freshness"])
                    fresh_label = "HARI INI" if t_r["freshness"] == 0 else f"{t_r['freshness']}h lalu"
                    badges_t = (
                        _t_event_badge("BOS", t_r["bos_date"], t_r["bos_scope"],
                                      t_r["bos_days_ago"], NEON_GREEN) +
                        _t_event_badge("CHoCH", t_r["choch_date"], t_r["choch_scope"],
                                      t_r["choch_days_ago"], C_WARNING) +
                        _t_event_badge("EQL", t_r["eql_date"], "",
                                      t_r["eql_days_ago"], C_INFO)
                    )
                    t_card_html = (
                        '<div style="background:var(--bg-card);border:1px solid ' + fc + '55;'
                        'border-left:4px solid ' + fc + ';border-radius:var(--r-md);'
                        'padding:1rem 1.2rem;margin-bottom:0.8rem">'
                        '<div style="display:flex;justify-content:space-between;align-items:center">'
                        '<span style="font-family:Orbitron,monospace;font-size:var(--text-lg);'
                        'font-weight:800;color:#E2E8F0">' + t_r['ticker'] + '</span>'
                        '<span style="font-family:Orbitron,monospace;font-size:var(--text-md);'
                        'font-weight:900;color:' + fc + '">' + fresh_label + '</span>'
                        '</div>'
                        '<div style="font-family:Share Tech Mono,monospace;font-size:var(--text-sm);'
                        'color:var(--text-muted);margin:0.4rem 0">'
                        'Close Rp' + '{:,.0f}'.format(t_r['close']) +
                        ' | Bias Internal: ' + _bias_label_t[t_r['internal_bias']] +
                        ' | Bias Swing: ' + _bias_label_t[t_r['swing_bias']] +
                        '</div>'
                        '<div style="margin-top:0.5rem">' + badges_t + '</div>'
                        '</div>'
                    )
                    st.markdown(t_card_html, unsafe_allow_html=True)

st.markdown("<br><br>", unsafe_allow_html=True)

