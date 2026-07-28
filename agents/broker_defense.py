"""
agents/broker_defense.py — Tahap 1: kalkulasi murni per-broker (posisi,
bottom-buy, defense streak). Dipakai sbg fondasi utk tahap 2 (ranking top-3
broker per saham) dan tahap 3 (integrasi UI).

DESAIN PENTING (hasil diskusi + pembuktian data nyata):
  - DEFENSE mewarisi PERSIS logika test_whale_defense() di whale_scanner.py
    (heavy vol >2x avg20 + price_dropped + recovered ke atas 50% rentang
    hi-lo) — bukan definisi paralel baru. "Yang defend" = broker spesifik
    net-buy PADA hari yg memenuhi kondisi itu.
  - Kriteria RENTANG (bukan "N hari BERTURUT-TURUT"), krn terbukti via
    diagnose_defense_multi.py: hit-rate defend level-saham cuma ~0.2-0.4%
    hari (BUMI/BBCA/ANTM/GOTO semua serupa) — mensyaratkan 3 hari berurutan
    scr statistik nyaris mustahil terpicu. Default: >=1 defend dlm 60 hari
    terakhir dianggap "watch-worthy" (bisa di-tune stlh data broker_daily
    nyata terkumpul cukup byk — saat ini tabel MASIH KOSONG per 2026-07-26).
  - Posisi kumulatif TIDAK pakai window waktu tetap — data broker_daily
    saat ini sporadis (cuma terisi saat token Stockbit fresh), jadi
    "SEMUA hari yg tercatat" lebih realistis drpd window 30/60/90 hari yg
    mgkn justru mayoritas kosong.
"""

import logging
from agents.broker_history import get_db

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 60  # utk defend/bottom-buy — rekam jejak historis, butuh rentang panjang krn langka
DEFAULT_MIN_DEFENDS = 1
DEFAULT_POSITION_WINDOW_DAYS = 14  # utk posisi kumulatif — aktivitas TERKINI, sengaja beda horizon dr defend


def get_broker_position(ticker: str, broker_code: str,
                         window_days: int = DEFAULT_POSITION_WINDOW_DAYS) -> dict:
    """Posisi kumulatif broker tsb pada ticker — total net_lot dlm window_days
    TERAKHIR (kalender, dihitung dr hari ini) — bukan lagi 'semua riwayat'
    (diubah v10.3.4, sesuai keputusan: posisi cerminan AKTIVITAS TERKINI,
    beda horizon dr defend/bottom-buy yg tetap 60 hari krn itu soal REKAM
    JEJAK historis, bukan kebaruan). window_days=None -> perilaku lama (semua
    riwayat), dipertahankan utk kompatibilitas mundur bila diperlukan."""
    t = ticker.replace(".JK", "")
    conn = get_db()
    try:
        if window_days is None:
            rows = conn.execute("""
                SELECT date, buy_lot, sell_lot, net_lot FROM broker_daily
                WHERE ticker=? AND broker_code=? ORDER BY date
            """, (t, broker_code)).fetchall()
        else:
            from datetime import datetime, timedelta
            cutoff = (datetime.now() - timedelta(days=window_days)).strftime("%Y-%m-%d")
            rows = conn.execute("""
                SELECT date, buy_lot, sell_lot, net_lot FROM broker_daily
                WHERE ticker=? AND broker_code=? AND date>=? ORDER BY date
            """, (t, broker_code, cutoff)).fetchall()
    finally:
        conn.close()

    if not rows:
        return {"ticker": t, "broker_code": broker_code, "n_days": 0,
                "cumulative_net_lot": 0, "cumulative_buy_lot": 0,
                "cumulative_sell_lot": 0, "first_date": None, "last_date": None,
                "window_days": window_days}

    cum_net  = sum(r["net_lot"]  for r in rows)
    cum_buy  = sum(r["buy_lot"]  for r in rows)
    cum_sell = sum(r["sell_lot"] for r in rows)
    return {
        "ticker": t, "broker_code": broker_code, "n_days": len(rows),
        "cumulative_net_lot": cum_net, "cumulative_buy_lot": cum_buy,
        "cumulative_sell_lot": cum_sell,
        "first_date": rows[0]["date"], "last_date": rows[-1]["date"],
        "window_days": window_days,
    }


def get_broker_bottom_buys(ticker: str, broker_code: str, price_df,
                            weak_close_threshold: float = 0.3) -> list:
    """Hari2 broker tsb net-buy (net_lot>0) DAN closing hari itu DEKAT LOW
    harian (weak close) — beda dgn 'defense' (yg butuh RECOVER ke atas).
    Ini pola "beli saat harga lemah", bukan "menahan harga".

    price_df: DataFrame harga dgn index tanggal (Timestamp/str 'YYYY-MM-DD')
    dan kolom Close/High/Low — dari DataFeed.fetch() yg sama dipakai scanner.
    weak_close_threshold: (close-low)/(high-low) <= ini dianggap "dekat low"
    (default 0.3 — simetris dgn 'recovered' test_whale_defense yg pakai >0.5
    utk arah sebaliknya)."""
    t = ticker.replace(".JK", "")
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT date, net_lot, buy_lot FROM broker_daily
            WHERE ticker=? AND broker_code=? AND net_lot>0 ORDER BY date
        """, (t, broker_code)).fetchall()
    finally:
        conn.close()

    if not rows or price_df is None or len(price_df) == 0:
        return []

    price_by_date = {str(idx.date()) if hasattr(idx, "date") else str(idx): row
                      for idx, row in price_df.iterrows()}

    bottom_buys = []
    for r in rows:
        prow = price_by_date.get(r["date"])
        if prow is None:
            continue
        hi, lo, c = float(prow["High"]), float(prow["Low"]), float(prow["Close"])
        if (hi - lo) <= 0:
            continue
        close_pos = (c - lo) / (hi - lo)
        if close_pos <= weak_close_threshold:
            bottom_buys.append({
                "date": r["date"], "net_lot": r["net_lot"],
                "close": c, "close_pos_in_range": round(close_pos, 3),
            })
    return bottom_buys


def get_broker_defense_streak(ticker: str, broker_code: str, price_df,
                               window_days: int = DEFAULT_WINDOW_DAYS,
                               min_defends: int = DEFAULT_MIN_DEFENDS) -> dict:
    """Deteksi 'defend' per-broker dlm window_days terakhir: hari2 di mana
    (a) kondisi test_whale_defense TERPENUHI (heavy vol >2x avg20 + price
    turun + recover >50% rentang hi-lo) DAN (b) broker tsb net-buy hari itu.
    Kriteria RENTANG (min_defends dlm window_days), BUKAN berturut-turut
    ketat — lihat docstring modul utk alasan (hit-rate defend ~0.2-0.4%/hari,
    3 hari berurutan scr statistik nyaris mustahil).

    price_df: DataFrame harga dgn index tanggal, kolom Close/High/Low/Volume,
    urut kronologis (dipakai jg utk hitung vol_ma20 & prev_close)."""
    t = ticker.replace(".JK", "")
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT date, net_lot FROM broker_daily
            WHERE ticker=? AND broker_code=? AND net_lot>0 ORDER BY date
        """, (t, broker_code)).fetchall()
    finally:
        conn.close()

    empty = {"ticker": t, "broker_code": broker_code, "defend_days": [],
             "n_defends": 0, "watch_worthy": False, "window_days": window_days}
    if not rows or price_df is None or len(price_df) < 21:
        return empty

    broker_buy_dates = {r["date"]: r["net_lot"] for r in rows}
    vol_ma = price_df["Volume"].rolling(20).mean()

    # Batas window: window_days TERAKHIR dari harga yg tersedia (bukan dari
    # broker_buy_dates — krn kita perlu tahu vol_ma20 & prev_close jg utk
    # hari2 broker itu, dan window dihitung dari kalender harga, konsisten
    # dgn cara test_whale_defense menghitung window 20 harinya sendiri).
    start_idx = max(20, len(price_df) - window_days)

    defend_days = []
    for i in range(start_idx, len(price_df)):
        date_str = str(price_df.index[i].date()) if hasattr(price_df.index[i], "date") else str(price_df.index[i])
        if date_str not in broker_buy_dates:
            continue
        v      = float(price_df["Volume"].iloc[i])
        c      = float(price_df["Close"].iloc[i])
        lo     = float(price_df["Low"].iloc[i])
        hi     = float(price_df["High"].iloc[i])
        prev_c = float(price_df["Close"].iloc[i - 1])
        vma    = float(vol_ma.iloc[i])
        if vma <= 0 or (hi - lo) <= 0:
            continue

        is_heavy_vol  = v > vma * 2.0
        price_dropped = c < prev_c
        recovered     = (c - lo) / (hi - lo) > 0.5
        if is_heavy_vol and price_dropped and recovered:
            defend_days.append({
                "date": date_str, "net_lot": broker_buy_dates[date_str],
                "vol_vs_avg": round(v / vma, 2),
            })

    return {
        "ticker": t, "broker_code": broker_code, "defend_days": defend_days,
        "n_defends": len(defend_days), "window_days": window_days,
        "watch_worthy": len(defend_days) >= min_defends,
    }


# ═══ TAHAP 2 — Ranking top-N broker per saham ═══════════════════════════════
# Bobot skor (bisa disesuaikan — angka awal, belum divalidasi thd data nyata
# krn broker_daily masih dlm proses pengumpulan per 2026-07-27):
WEIGHT_POSITION   = 40  # posisi kumulatif (rank persentil antar broker aktif di ticker ini)
WEIGHT_DEFENSE    = 40  # jumlah hari defend (di-cap DEFENSE_CAP biar 1 broker tak mendominasi)
WEIGHT_BOTTOM_BUY = 20  # jumlah hari beli-di-bottom (di-cap BOTTOM_BUY_CAP)
DEFENSE_CAP     = 3
BOTTOM_BUY_CAP  = 5


def get_top_brokers_to_watch(ticker: str, price_df, top_n: int = 3,
                              window_days: int = DEFAULT_WINDOW_DAYS,
                              min_defends: int = DEFAULT_MIN_DEFENDS) -> list:
    """Gabungkan get_broker_position + get_broker_bottom_buys +
    get_broker_defense_streak jadi SATU skor per broker, urutkan, ambil top_n.
    Hanya broker dgn cumulative_net_lot > 0 (akumulator, bukan distributor)
    yg dipertimbangkan — sesuai filosofi 'follow the whale' (ikuti yg beli,
    bukan yg jual).

    Skor = position_percentile*WEIGHT_POSITION
         + min(n_defends,DEFENSE_CAP)/DEFENSE_CAP*WEIGHT_DEFENSE
         + min(n_bottom_buys,BOTTOM_BUY_CAP)/BOTTOM_BUY_CAP*WEIGHT_BOTTOM_BUY
    (rentang skor 0-100). Bobot BELUM divalidasi thd data nyata (broker_daily
    msh dikumpulkan) — mudah disesuaikan lewat konstanta modul di atas
    setelah data cukup utk evaluasi empiris."""
    t = ticker.replace(".JK", "")
    conn = get_db()
    try:
        codes = [r["broker_code"] for r in conn.execute(
            "SELECT DISTINCT broker_code FROM broker_daily WHERE ticker=?", (t,)
        ).fetchall()]
    finally:
        conn.close()

    if not codes:
        return []

    profiles = []
    for code in codes:
        pos = get_broker_position(t, code)
        if pos["cumulative_net_lot"] <= 0:
            continue  # skip distributor — cuma follow akumulator
        bottom = get_broker_bottom_buys(t, code, price_df)
        defense = get_broker_defense_streak(t, code, price_df, window_days, min_defends)
        profiles.append({
            "broker_code": code, "position": pos,
            "n_bottom_buys": len(bottom), "bottom_buys": bottom,
            "n_defends": defense["n_defends"], "defend_days": defense["defend_days"],
            "watch_worthy": defense["watch_worthy"],
        })

    if not profiles:
        return []

    max_lot = max(p["position"]["cumulative_net_lot"] for p in profiles)
    for p in profiles:
        position_pct = (p["position"]["cumulative_net_lot"] / max_lot) if max_lot > 0 else 0
        defend_pct   = min(p["n_defends"], DEFENSE_CAP) / DEFENSE_CAP
        bottom_pct   = min(p["n_bottom_buys"], BOTTOM_BUY_CAP) / BOTTOM_BUY_CAP
        p["score"] = round(
            position_pct * WEIGHT_POSITION +
            defend_pct   * WEIGHT_DEFENSE +
            bottom_pct   * WEIGHT_BOTTOM_BUY, 1
        )

    profiles.sort(key=lambda p: -p["score"])
    return profiles[:top_n]


def get_broker_leaderboard(ticker: str, price_df, top_n: int = 10,
                            window_days: int = DEFAULT_WINDOW_DAYS,
                            min_defends: int = DEFAULT_MIN_DEFENDS) -> list:
    """v10.3.3: leaderboard SEMUA broker aktif (akumulator DAN distributor),
    diurutkan |posisi| terbesar — beda dgn get_top_brokers_to_watch (yg CUMA
    tampilkan akumulator, dipakai utk badge WATCH). Ini utk gambaran lengkap
    siapa beli siapa jual di ticker itu, tanpa menyaring.

    Skor/defend/bottom-buy CUMA dihitung utk AKUMULATOR (net_lot>0) — sinyal2
    itu spesifik pola akumulasi (defend/beli-di-bottom), tak relevan scr
    definisi utk distributor. Distributor tampil dgn score=None."""
    t = ticker.replace(".JK", "")
    conn = get_db()
    try:
        codes = [r["broker_code"] for r in conn.execute(
            "SELECT DISTINCT broker_code FROM broker_daily WHERE ticker=?", (t,)
        ).fetchall()]
    finally:
        conn.close()

    if not codes:
        return []

    profiles = []
    for code in codes:
        pos = get_broker_position(t, code)
        net = pos["cumulative_net_lot"]
        if net == 0:
            continue
        is_accum = net > 0
        entry = {
            "broker_code": code, "position": pos,
            "role": "AKUMULATOR" if is_accum else "DISTRIBUTOR",
        }
        if is_accum:
            bottom = get_broker_bottom_buys(t, code, price_df)
            defense = get_broker_defense_streak(t, code, price_df, window_days, min_defends)
            entry["n_bottom_buys"] = len(bottom)
            entry["n_defends"] = defense["n_defends"]
            entry["watch_worthy"] = defense["watch_worthy"]
        else:
            entry["n_bottom_buys"] = None
            entry["n_defends"] = None
            entry["watch_worthy"] = False
        profiles.append(entry)

    if not profiles:
        return []

    # Basis skor (max_lot) HANYA dari akumulator — biar skala 0-100 tetap
    # konsisten dgn get_top_brokers_to_watch, tak tercampur skala distributor
    # yg net_lot-nya negatif.
    accum_lots = [p["position"]["cumulative_net_lot"] for p in profiles if p["role"] == "AKUMULATOR"]
    max_lot = max(accum_lots) if accum_lots else 1
    for p in profiles:
        if p["role"] == "AKUMULATOR":
            position_pct = (p["position"]["cumulative_net_lot"] / max_lot) if max_lot > 0 else 0
            defend_pct   = min(p["n_defends"], DEFENSE_CAP) / DEFENSE_CAP
            bottom_pct   = min(p["n_bottom_buys"], BOTTOM_BUY_CAP) / BOTTOM_BUY_CAP
            p["score"] = round(
                position_pct * WEIGHT_POSITION +
                defend_pct   * WEIGHT_DEFENSE +
                bottom_pct   * WEIGHT_BOTTOM_BUY, 1
            )
        else:
            p["score"] = None

    profiles.sort(key=lambda p: -abs(p["position"]["cumulative_net_lot"]))
    return profiles[:top_n]
