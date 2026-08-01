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
        # v10.4.0 FIX: entry_zone_label bawaan whale_scanner.py mengandung
        # bahasa verdict trading ("Skip"/"Acceptable") yg dirancang utk
        # filosofi AKUMULASI-DI-FLOOR (mean-reversion) — BERTENTANGAN dgn
        # filosofi inti page 1 (breakout-retest, yg SENGAJA menunggu harga
        # naik dulu sebelum retest, jadi harga WAJAR jauh dari floor absolut).
        # User menunjukkan kasus nyata (RGAS: conviction 100% VIDYA+SMC tapi
        # "Skip" dari floor whale) — dua sinyal saling bertentangan di kartu
        # yg sama. Diganti label NETRAL (jarak fakta, tanpa rekomendasi
        # trading) — verdict trading di halaman ini murni dari conviction_pct
        # milik page 1 sendiri, bukan dicampur logika page 2.
        zone_label_neutral = {
            "AT_FLOOR": "Dekat floor", "NEAR_FLOOR": "Dekat floor",
            "MID_RANGE": "Jarak sedang dari floor", "FAR_FROM_FLOOR": "Jauh dari floor",
        }
        table_rows = ""
        for r, fm in floor_rows:
            label = zone_label_neutral.get(fm["entry_zone"], "-")
            table_rows += (
                '<tr style="border-bottom:1px solid rgba(255,255,255,0.06)">'
                f'<td style="padding:0.5rem 0.8rem;font-family:Orbitron,monospace;'
                f'font-weight:700">{r["ticker"]}</td>'
                f'<td style="padding:0.5rem 0.8rem;text-align:right;'
                f'font-family:Share Tech Mono,monospace">Rp{r["close"]:,.0f}</td>'
                f'<td style="padding:0.5rem 0.8rem;text-align:right;'
                f'font-family:Share Tech Mono,monospace">Rp{fm["floor_price"]:,.0f}</td>'
                f'<td style="padding:0.5rem 0.8rem;text-align:right;'
                f'font-family:Share Tech Mono,monospace">Rp{fm["vwap_60d"]:,.0f}</td>'
                f'<td style="padding:0.5rem 0.8rem;text-align:right;'
                f'font-family:Share Tech Mono,monospace">{fm["pct_above_floor"]:+.1f}%</td>'
                f'<td style="padding:0.5rem 0.8rem;color:var(--text-muted)">{label}</td>'
                f'<td style="padding:0.5rem 0.8rem;text-align:right;'
                f'font-family:Share Tech Mono,monospace">{r["conviction_pct"]}%</td>'
                f'<td style="padding:0.5rem 0.8rem;text-align:right;'
                f'font-family:Share Tech Mono,monospace">{fm["ff_vol"]:.1f}\u00d7</td>'
                f'<td style="padding:0.5rem 0.8rem">{fm["sector"]}</td>'
                '</tr>'
            )
        table_html = (
            '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;'
            'font-size:var(--text-sm)">'
            '<thead><tr style="background:rgba(255,255,255,0.03);text-align:left">'
            '<th style="padding:0.5rem 0.8rem">Ticker</th>'
            '<th style="padding:0.5rem 0.8rem;text-align:right">Price</th>'
            '<th style="padding:0.5rem 0.8rem;text-align:right">Floor</th>'
            '<th style="padding:0.5rem 0.8rem;text-align:right">VWAP60</th>'
            '<th style="padding:0.5rem 0.8rem;text-align:right">%\u2191Floor</th>'
            '<th style="padding:0.5rem 0.8rem">Zone</th>'
            '<th style="padding:0.5rem 0.8rem;text-align:right">Conv</th>'
            '<th style="padding:0.5rem 0.8rem;text-align:right">FF-Vol\u00d7</th>'
            '<th style="padding:0.5rem 0.8rem">Sector</th>'
            '</tr></thead><tbody>' + table_rows + '</tbody></table></div>'
        )
        st.markdown(table_html, unsafe_allow_html=True)

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
            label = zone_label_neutral.get(_sel_fm["entry_zone"], "-")
            ext_pen = _sel_r.get("extension_penalty", 0) or 0
            ext_atr = _sel_r.get("extension_atr", 0) or 0
            ext_line = (
                f'<br><span style="color:{C_WARNING}">\u26a0 Extended move: '
                f'-{ext_pen} poin (harga {ext_atr:.1f}x ATR dari swing low awal)</span>'
                if ext_pen > 0 else ""
            )
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
                f'Zona retest: {zona_str} | Retest {_sel_r["retest_hold_days"]}/2 hari{ext_line}<br>'
                f'Floor: Rp{_sel_fm["floor_price"]:,.0f} | VWAP60: Rp{_sel_fm["vwap_60d"]:,.0f} | '
                f'{label} ({_sel_fm["pct_above_floor"]:+.1f}%)<br>'
                f'Sector: {_sel_fm["sector"]} | FF-Vol: {_sel_fm["ff_vol"]:.1f}\u00d7'
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
                ' | ' + str(r['bars_since_formed'] or 0) + ' hari sejak terbentuk ' + pk_tag +
                '</div>'
                '<div style="margin-top:0.5rem">' + badges + '</div>'
                '</div>'
            )
            st.markdown(card_html, unsafe_allow_html=True)

st.markdown("<br><br>", unsafe_allow_html=True)
st.caption("Retest-only path: breakout tanpa pullback akan selalu bernilai conviction "
          "rendah dalam skema ini -- trade-off yang disengaja demi menyaring false breakout.")
