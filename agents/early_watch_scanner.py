"""
agents/early_watch_scanner.py — Scanner "Early Watch" (EXPERIMENTAL), 4h.

LABEL WAJIB DI UI: "EXPERIMENTAL" — bukan tingkat kepercayaan yang sama
dengan agents/momentum_scanner.py (Momentum BETA, 3/3 validated study
case).

RIWAYAT DEFINISI — v2 ini MENGGANTI TOTAL definisi v1 (dikirim sbg
v10.9.7, BELUM PERNAH dijalankan live oleh user sebelum diganti):

  v1 (10.9.7): WAJIB ada BOS/CHoCH dlm ±5 bar dari episode centerline-flip
  supaya lolos jadi match -- filter algoritmik ketat, terbukti dari
  backtest (diagnose_early_watch_episodes.py) cuma meloloskan ~30-36%
  early candidate, sisanya dibuang sbg "noise" walau belum ada bukti
  buangan itu memang tidak berguna.

  v2 (INI, 10.9.8, sesi 2026-09-07 lanjutan): user SENGAJA menyederhanakan
  setelah melihat hasil v1 -- "saya butuhnya cuma 2 syarat: VIDYA merah +
  Momentum hijau. Choppy atau tidak biar saya analisa manual. COCH/BOS/EQL
  cuma tag tambahan." Filter algoritmik jadi CUMA 2 syarat WAJIB (band
  luar merah + centerline pernah cross ke atas dlm N bar terakhir),
  keputusan "sinyal ini valid/noise" dipindah SEPENUHNYA ke manusia
  (user lihat chart sendiri apakah choppy/range atau bersih). BOS/CHoCH/
  EQL TETAP dihitung & ditampilkan (kalau ada di dekat titik cross) tapi
  HANYA sbg tag informasi -- kehadiran/ketidakhadirannya TIDAK menggugurkan
  atau meloloskan match apa pun.

DEFINISI MEKANIS v2 (TIDAK ADA di file ini yang reimplementasi rumus
VIDYA/struktur sendiri -- SEMUA fungsi di-import dari core/ob_engine.py &
core/structure_signals.py yang sudah ada):

  1. WAJIB — Band luar (is_trend_up dari run_engine()) MASIH False di bar
     TERAKHIR ("VIDYA merah" sekarang). Kalau sudah True, ticker itu
     domain scanner Momentum, bukan Early Watch.
  2. WAJIB — Ada centerline-flip-up (Close cross ke atas vidya_val, HITUNG
     TANPA offset ATR -- beda dari upper/lower band yg dipakai is_trend_up)
     dalam RECENT_WINDOW bar terakhir DAN band luar MASIH False persis di
     bar cross itu (kalau band sudah True saat cross terjadi, itu bukan
     "early", itu Momentum). Diambil yang PALING BARU kalau ada >1 cross
     yg lolos syarat window ini (choppy/flicker ganda) -- caller cuma
     dikasih 1 state per ticker per scan.
  3. OPSIONAL, TAG SAJA — BOS/CHoCH (compute_bullish_structure, scope apa
     pun, union) dgn bar_index dlm ±RECENT_WINDOW dari bar cross di atas.
     Ditampilkan kalau ADA, TAPI TIDAK WAJIB ADA. EQL dlm EQL_LOOKBACK_
     WINDOW bar sebelum bar cross -- SAMA, tag saja.

KONSEKUENSI PERUBAHAN INI: dibanding v1, v2 akan menghasilkan LEBIH BANYAK
ticker per scan (syarat lolos jauh lebih longgar -- cuma 2 kondisi wajib,
bukan 4). Ini SESUAI KEINGINAN user (ekspektasi expected-value per alert
LEBIH RENDAH drpd v1, tapi RECALL lebih tinggi -- user yg saring manual
dari chart, bukan algoritma). WAJIB tetap label EXPERIMENTAL di UI dan
JANGAN klaim rasio match apa pun dari sini krn v2 belum pernah dihitung
distribusinya (v1 punya angka 30-36% dari backtest, itu angka MILIK v1,
BUKAN v2 -- jangan disamakan).

ASUMSI YANG DIWARISI dari momentum_scanner.py (TIDAK diverifikasi ulang):
run_engine(df) dipanggil TANPA kwargs -> use_ha_trend=False default ->
trend_close == df["Close"] raw (lihat core/ob_engine.py VidyaSmcEngine.run()).
Kalau default itu berubah di masa depan, vidya_val yg dihitung manual di
file ini (_vidya_calc(df["Close"], ...)) akan DIVERGEN dari yg dipakai
run_engine() secara internal utk is_trend_up -- cek ulang kalau
core/ob_engine.py berubah.

FILE INI ADITIF — TIDAK mengubah core/ob_engine.py, core/structure_signals.py,
atau agents/momentum_scanner.py sama sekali.

JALANKAN SELF-TEST:
    python -m agents.early_watch_scanner
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from core.data_feed import fetch_4h, get_catalyst_universe
from core.ob_engine import run_engine, _vidya_calc
from core.structure_signals import compute_bullish_structure

logger = logging.getLogger(__name__)

MIN_BARS_REQUIRED = 260   # sama kontrak dgn momentum_scanner.py (buffer ATR200/swing50)
RECENT_WINDOW = 5         # bar 4h -- diwarisi dari v1/momentum_scanner.py utk konsistensi;
# user TIDAK menyebut angka N spesifik saat minta simplifikasi ini ("cross dalam N bar
# terakhir") -- 5 dipakai sbg default supaya apple-to-apple dgn scanner lain, GANTI
# di sini kalau ternyata user mau window lain setelah lihat hasil live.
EQL_LOOKBACK_WINDOW = 20  # bar 4h -- sama asumsi dgn momentum_scanner.py, tag opsional saja
VIDYA_LENGTH = 10         # HARUS sama dgn default VidyaSmcEngine, lihat ASUMSI di atas
VIDYA_MOMENTUM = 20


@dataclass
class EarlyWatchState:
    ticker: str
    cross_date: object          # tanggal centerline cross yg memicu state ini
    cross_bar: int
    bars_since_cross: int       # 0 = cross persis di bar terakhir, >0 = beberapa bar lalu
    close: float
    vidya_val: float
    confirmations: list         # StructureEvent BOS/CHoCH dekat cross_bar -- TAG SAJA,
    # BISA KOSONG (list kosong = tidak ada, BUKAN berarti state ini invalid/dibuang).
    eql_date: Optional[object] = None   # tag EQL opsional -- BISA None, BUKAN syarat.

    @property
    def kinds_label(self) -> str:
        """String tag BOS/CHoCH, mis. 'CHOCH(internal)+BOS(swing)' -- '-' kalau kosong
        (kosong itu NORMAL di v2, bukan tanda error)."""
        if not self.confirmations:
            return "-"
        return "+".join(f"{c.kind}({c.scope})" for c in self.confirmations)

    @property
    def has_confirmation(self) -> bool:
        return bool(self.confirmations)


def find_early_watch_state(
    df: pd.DataFrame,
    ticker: str = "",
    recent_window: int = RECENT_WINDOW,
) -> Optional[EarlyWatchState]:
    """Untuk scan produksi: cek APAKAH ticker ini SEDANG dalam kondisi
    'VIDYA merah + Momentum hijau' SEKARANG. Return None kalau tidak.
    Return SATU EarlyWatchState (cross paling baru dlm window) kalau ya --
    BOS/CHoCH/EQL diisi kalau kebetulan ada di dekatnya, TIDAK disyaratkan."""
    if df is None or len(df) < MIN_BARS_REQUIRED:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)

    engine_states = run_engine(df)
    if engine_states[-1].is_trend_up:
        return None  # band luar sudah confirmed HIJAU -- domain Momentum, bukan Early Watch

    close = df["Close"]
    vidya_val_series = _vidya_calc(close, VIDYA_LENGTH, VIDYA_MOMENTUM)
    above_centerline = close > vidya_val_series
    is_trend_up_by_bar = {s.bar_index: s.is_trend_up for s in engine_states}
    date_by_bar = {s.bar_index: s.date for s in engine_states}

    n = len(df)
    cutoff = n - recent_window
    centerline_flips = []
    prev_above = None
    for i in range(len(df)):
        ab = above_centerline.iloc[i]
        if ab != ab:  # NaN (warmup)
            continue
        ab = bool(ab)
        if prev_above is not None and ab and not prev_above:
            centerline_flips.append(i)
        prev_above = ab

    # WAJIB #2: cross dlm window, DAN band luar masih False PERSIS di bar cross itu
    # (kalau band sudah True saat itu, itu bukan "early" -- itu Momentum).
    fresh_early = [i for i in centerline_flips
                   if i >= cutoff and is_trend_up_by_bar.get(i) is False]
    if not fresh_early:
        return None
    cross_bar = max(fresh_early)  # kalau ada >1 flicker di window, ambil yg PALING BARU

    # ── Tag opsional (BOS/CHoCH/EQL) -- TIDAK mempengaruhi valid/tidaknya state ──
    confirmations = []
    eql_date = None
    sig = compute_bullish_structure(df, ticker=ticker)
    if sig is not None:
        structure_events = [e for e in sig.events if e.kind in ("BOS", "CHOCH")]
        confirmations = [e for e in structure_events
                          if abs(e.bar_index - cross_bar) <= recent_window]
        confirmations.sort(key=lambda e: e.bar_index)

        eql_events = [e for e in sig.events if e.kind == "EQL"]
        eql_cutoff = cross_bar - EQL_LOOKBACK_WINDOW
        eql_before = [e for e in eql_events if eql_cutoff <= e.bar_index < cross_bar]
        if eql_before:
            eql_date = max(eql_before, key=lambda e: e.bar_index).date

    return EarlyWatchState(
        ticker=ticker,
        cross_date=date_by_bar.get(cross_bar),
        cross_bar=cross_bar,
        bars_since_cross=(n - 1) - cross_bar,
        close=float(close.iloc[cross_bar]),
        vidya_val=float(vidya_val_series.iloc[cross_bar]),
        confirmations=confirmations,
        eql_date=eql_date,
    )


class EarlyWatchScanner4H:
    """Scan universe (default: get_catalyst_universe(full_universe=True),
    SAMA dgn MomentumScanner4H/StructureFreshScanner) cari ticker yang
    SEDANG dalam kondisi 'VIDYA merah + Momentum hijau' (2 syarat wajib
    saja, v2), timeframe 4h.

    EXPERIMENTAL -- lihat docstring modul ini utk riwayat definisi v1->v2.
    Pola orkestrasi (class, .scan() -> (results, ctx)) SENGAJA identik
    dgn MomentumScanner4H (chunking, delay, fetch tanpa cache)."""

    CHUNK_SIZE = 15
    CHUNK_DELAY = 3.0
    MAX_WORKERS = 8

    def __init__(self, recent_window: int = RECENT_WINDOW):
        self.recent_window = recent_window

    def _fetch_all(self, tickers: list) -> dict:
        results = {}
        chunks = [tickers[i:i + self.CHUNK_SIZE] for i in range(0, len(tickers), self.CHUNK_SIZE)]
        for ci, chunk in enumerate(chunks):
            with ThreadPoolExecutor(max_workers=min(self.MAX_WORKERS, len(chunk))) as exe:
                fut_map = {exe.submit(fetch_4h, t): t for t in chunk}
                for fut in as_completed(fut_map):
                    t = fut_map[fut]
                    try:
                        df = fut.result()
                        if df is not None:
                            results[t] = df
                    except Exception as exc:
                        logger.debug(f"[EarlyWatch4H] fetch {t}: {exc}")
            logger.info(f"[EarlyWatch4H] chunk {ci + 1}/{len(chunks)} done "
                        f"({len(results)} ticker fetched so far)")
            if ci < len(chunks) - 1:
                time.sleep(self.CHUNK_DELAY)
        return results

    def scan(self, tickers: Optional[list] = None) -> tuple:
        tickers = tickers if tickers is not None else get_catalyst_universe(full_universe=True)
        logger.info(f"[EarlyWatch4H] Universe: {len(tickers)} ticker — fetch_4h() chunked "
                    f"({self.CHUNK_SIZE}/chunk, delay {self.CHUNK_DELAY}s)...")

        data = self._fetch_all(tickers)
        fetch_failed = len(tickers) - len(data)
        logger.info(f"[EarlyWatch4H] Fetch selesai: {len(data)}/{len(tickers)} berhasil "
                    f"({fetch_failed} gagal/skip)")

        PROGRESS_EVERY = 50
        n_compute = len(data)
        t_compute0 = time.time()
        logger.info(f"[EarlyWatch4H] Mulai hitung state ({n_compute} ticker)...")

        results = []
        crashed = 0
        for idx, (ticker, df) in enumerate(data.items(), start=1):
            base_ticker = ticker.replace(".JK", "")
            try:
                st_ = find_early_watch_state(df, ticker=base_ticker, recent_window=self.recent_window)
            except Exception as exc:
                logger.debug(f"[EarlyWatch4H] {ticker}: engine crash — {exc}")
                crashed += 1
                continue
            if st_ is not None:
                results.append(st_)
            if idx % PROGRESS_EVERY == 0 or idx == n_compute:
                logger.info(f"[EarlyWatch4H] Hitung: {idx}/{n_compute} ticker diproses "
                            f"({len(results)} state sejauh ini, {time.time() - t_compute0:.1f}s)")

        compute_elapsed = time.time() - t_compute0
        logger.info(f"[EarlyWatch4H] Hitung selesai: {n_compute} ticker dalam "
                    f"{compute_elapsed:.1f}s ({crashed} crash)")

        results.sort(key=lambda e: e.bars_since_cross)
        ctx = {
            "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "total_universe": len(tickers),
            "fetched_ok": len(data),
            "fetch_failed": fetch_failed,
            "crashed": crashed,
            "match_count": len(results),
            "with_confirmation_count": sum(1 for r in results if r.has_confirmation),
        }
        logger.info(f"[EarlyWatch4H] Done: {len(results)} state "
                    f"({ctx['with_confirmation_count']} ada tag BOS/CHoCH) | "
                    f"{fetch_failed} fetch gagal | {crashed} crash")
        return results, ctx


if __name__ == "__main__":
    # ── Self-test dgn data SINTETIS -- buktikan logika 2-syarat + tag
    # opsional mekanis benar, BUKAN bukti apa pun soal ticker real. ──
    import numpy as np

    def _make_synthetic_uptrend_df(n=320, flip_at=280, eql_before_structure=True):
        # SAMA generator dgn momentum_scanner.py -- TERBUKTI menghasilkan centerline
        # cross bar 282, SATU bar SEBELUM band-luar confirm (vidya_flipped_up bar 283),
        # dgn CHoCH(internal) bar 286 (jarak 4) di dekatnya -- skenario yg pas utk
        # buktikan state 'masih merah + baru cross' KETEMU, dan tag CHoCH ikut terisi.
        rng = np.random.default_rng(42)
        dates = pd.date_range("2024-01-01", periods=n, freq="4h")
        base = np.concatenate([
            np.linspace(200, 100, flip_at) + rng.normal(0, 0.5, flip_at),
            np.linspace(100, 220, n - flip_at) + rng.normal(0, 0.5, n - flip_at),
        ])
        if eql_before_structure:
            eq_idx = flip_at + 3 - 8
            base[eq_idx] = base[eq_idx - 5] * 1.0
        close = pd.Series(base, index=dates)
        high = close + rng.uniform(0.5, 2.0, n)
        low = close - rng.uniform(0.5, 2.0, n)
        open_ = close.shift(1).fillna(close.iloc[0])
        vol = pd.Series(rng.uniform(1e6, 5e6, n), index=dates)
        return pd.DataFrame({"Open": open_, "High": high, "Low": low,
                              "Close": close, "Volume": vol}, index=dates)

    # ── Skenario A: potong persis di bar 282 (cross baru terjadi, band msh merah,
    # ini bar TERAKHIR di df) -- harus KETEMU state, DAN dpt tag CHoCH kalau sudah
    # kebentuk di titik itu (structure di skenario penuh baru muncul bar 286, jadi
    # DI SINI belum kebentuk -- justru itu yg mau dibuktikan: tag BOLEH kosong). ──
    df_full = _make_synthetic_uptrend_df()
    df_cut_at_cross = df_full.iloc[:283].copy()  # bar 0..282, bar terakhir = 282
    st_a = find_early_watch_state(df_cut_at_cross, ticker="SYN-A")
    print(f"[self-test A] potong tepat di bar cross (282): "
          f"{'KETEMU, cross=' + str(st_a.cross_date.date()) + ' tag=' + st_a.kinds_label if st_a else 'None'}")
    assert st_a is not None, "SELF-TEST A GAGAL: cross di bar terakhir + band msh merah harus ketemu."
    assert st_a.bars_since_cross == 0
    print("[self-test A] PASS -- state ketemu tepat saat band masih merah, tag boleh kosong ('-').")

    # ── Skenario B: potong 3 bar setelah cross (285), CHoCH sudah kebentuk (286
    # belum, tapi structure detection bisa retroaktif kasih tanggal 283-286 range --
    # cek langsung apa adanya, bukan asumsi) -- band msh merah smp bar 282 (blm
    # jadi True krn vidya_flipped_up baru di 283 -- tunggu, df_full punya band True
    # dari 283 dst, jadi potongan >=283 justru harus None). Uji negatif ini penting:
    # begitu band confirmed True, Early Watch WAJIB berhenti melapor ticker itu. ──
    df_cut_after_confirm = df_full.iloc[:284].copy()  # bar terakhir = 283 (band sudah True)
    st_b = find_early_watch_state(df_cut_after_confirm, ticker="SYN-B")
    print(f"[self-test B] potong SETELAH band confirm (bar 283): "
          f"{'KETEMU (SALAH!)' if st_b else 'None (benar)'}")
    assert st_b is None, "SELF-TEST B GAGAL: band sudah True tapi masih dilaporkan Early Watch."
    print("[self-test B] PASS -- begitu band confirmed hijau, Early Watch berhenti (domain Momentum).")

    print("[self-test] SEMUA PASS.")
