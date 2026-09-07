"""
agents/early_watch_scanner.py — Scanner "Early Watch" (EXPERIMENTAL), 4h.

LABEL WAJIB DI UI: "EXPERIMENTAL" — bukan tingkat kepercayaan yang sama
dengan agents/momentum_scanner.py (Momentum BETA, 3/3 validated study
case). Baca CATATAN VALIDASI di bawah SEBELUM percaya output file ini.

LATAR BELAKANG (sesi 2026-09-07): user menantang premis
agents/momentum_scanner.py sendiri — "kalau VIDYA (band luar) sudah
beralih dari merah ke hijau, itu sudah TELAT". Usul: titik "mulai
pantau" yang benar adalah saat closing price cross ke ATAS garis
centerline VIDYA (vidya_val, TANPA offset ATR) SEMENTARA band luar
(is_trend_up) MASIH merah/belum confirmed — lebih dini drpd sinyal
Momentum yang sudah shipped. Disempurnakan lagi oleh user: centerline
ini suka "flicker" (berkedip hijau-merah berkali-kali) selama fase
choppy sebelum flip resmi, jadi perlu dipasangkan dengan konfirmasi
struktur BOS/CHoCH terdekat supaya bukan noise murni.

DEFINISI MEKANIS (final, hasil investigasi 3 diagnostic script
read-only — diagnose_early_momentum.py, diagnose_early_watch_concept.py,
diagnose_early_watch_episodes.py — TIDAK ADA di file ini yang
reimplementasi rumus VIDYA/struktur sendiri, SEMUA fungsi di-import dari
core/ob_engine.py & core/structure_signals.py yang sudah ada):

  1. Centerline-flip-up: bar di mana Close melewati vidya_val dari bawah
     ke atas (`_vidya_calc(df["Close"], VIDYA_LENGTH, VIDYA_MOMENTUM)`,
     TANPA offset ATR — beda dari upper_band/lower_band yang dipakai
     is_trend_up).
  2. "Early candidate": centerline-flip-up di atas yang terjadi SAAT
     is_trend_up (dari run_engine(), band luar) MASIH False — kalau band
     luar sudah True, itu domain scanner Momentum yang sudah ada, bukan
     Early Watch.
  3. Episode: early candidate yang berdekatan (gap <= EPISODE_GAP bar)
     digabung jadi SATU episode (pakai bar pertama & terakhir) — supaya
     flicker berulang dalam fase choppy yang sama tidak menghasilkan
     alert duplikat. Terbukti PENTING secara empiris: tanpa clustering
     ini rasio SINI/BUMI cuma bergeser tipis (~5-6 poin persen), jadi
     BUKAN sumber utama noise, tapi tetap dipakai supaya scanner produksi
     tidak spam alert per-flicker.
  4. Match VALID hanya kalau episode itu punya minimal 1 event BOS ATAU
     CHoCH (compute_bullish_structure, scope apa pun, union) dengan
     bar_index dalam rentang [episode_start - RECENT_WINDOW,
     episode_end + RECENT_WINDOW]. Episode TANPA confirmation ini
     DIBUANG (dianggap noise) — TIDAK dikembalikan oleh fungsi manapun
     di file ini.

CATATAN VALIDASI — WAJIB DIBACA, INI BEDA DARI MOMENTUM SCANNER:

  Momentum scanner (agents/momentum_scanner.py) divalidasi 3/3 terhadap
  study case chart real (BUMI/SINI/UANG) SEBELUM di-ship. Early Watch
  BELUM melewati validasi setara. Yang SUDAH diuji (diagnose_early_watch_
  episodes.py, full histori BUMI & SINI per 2026-09-07):

    - BUMI: 25 episode sepanjang ~2.5 tahun histori, 9 match (BOS/CHoCH
      confirmed) = 36%.
    - SINI: 21 episode, 6 match = 29%.

  Artinya: dari SEMUA episode yang lolos filter definisi di atas, cuma
  ~30% yang BENAR match (populasi 100% di sini SUDAH melalui filter
  no-confirmation-dibuang -- 64-71% early candidate MENTAH malah tidak
  pernah sampai jadi match sama sekali). Yang BELUM diuji sama sekali:
  apakah 30% yang match ini BENAR mendahului trend-up sungguhan (band
  luar akhirnya flip True) lebih sering drpd yang tidak match — alias
  BELUM ada bukti predictive value, cuma bukti "definisi ini mekanis
  konsisten & tidak generate alert tak terbatas". Keputusan user
  (2026-09-07): ship as-is dengan label EXPERIMENTAL, validasi lanjut
  dari observasi pemakaian live, BUKAN dari diagnostic lebih lanjut.
  Kalau nanti user laporkan alert yang sering meleset, definisi di file
  ini yang harus direvisi duluan — bukan tanda cara pakainya salah.

  KONSEKUENSI UNTUK UI: tampilkan expected-value SERENDAH ini secara
  eksplisit ke user tiap kali section ini dirender (jangan biarkan card
  terlihat se-"pasti" card Momentum yang sudah 3/3 validated).

ASUMSI YANG DIWARISI dari momentum_scanner.py (TIDAK diverifikasi ulang
di sini): run_engine(df) dipanggil TANPA kwargs -> use_ha_trend=False
default -> trend_close == df["Close"] raw (lihat core/ob_engine.py
VidyaSmcEngine.run()). Kalau default itu berubah di masa depan,
vidya_val yang dihitung manual di file ini (_vidya_calc(df["Close"], ...))
akan DIVERGEN dari yang dipakai run_engine() secara internal untuk
is_trend_up -- cek ulang asumsi ini kalau core/ob_engine.py berubah.

FILE INI ADITIF — TIDAK mengubah core/ob_engine.py, core/structure_signals.py,
atau agents/momentum_scanner.py sama sekali. Cuma meng-import fungsi yang
sudah ada.

JALANKAN SELF-TEST:
    python agents/early_watch_scanner.py
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
RECENT_WINDOW = 5         # bar 4h -- SAMA dgn momentum_scanner.py, apple-to-apple
EPISODE_GAP = 5           # gap maks (bar) antar early-candidate buat digabung 1 episode
VIDYA_LENGTH = 10         # HARUS sama dgn default VidyaSmcEngine, lihat ASUMSI di atas
VIDYA_MOMENTUM = 20


@dataclass
class EarlyWatchEvent:
    ticker: str
    episode_start_date: object
    episode_end_date: object
    episode_start_bar: int
    episode_end_bar: int
    flicker_count: int         # jumlah raw centerline-flip yg tergabung di episode ini
    confirmations: list        # StructureEvent (BOS/CHoCH), semua yg match, bukan cuma 1
    bars_between: int          # jarak confirmation TERDEKAT ke ujung episode (freshness)

    @property
    def kinds_label(self) -> str:
        return "+".join(f"{c.kind}({c.scope})" for c in self.confirmations)

    @property
    def latest_confirmation(self):
        return max(self.confirmations, key=lambda c: c.bar_index)


def _cluster_into_episodes(flip_bars: list, gap: int) -> list:
    """Gabungkan bar index yg berdekatan (gap <= threshold) jadi satu
    episode (start_bar, end_bar, [raw_bars]). Identik dgn logika yg sudah
    diuji di diagnose_early_watch_episodes.py (clustering test PASS)."""
    if not flip_bars:
        return []
    flip_bars = sorted(flip_bars)
    episodes = []
    cur = [flip_bars[0]]
    for b in flip_bars[1:]:
        if b - cur[-1] <= gap:
            cur.append(b)
        else:
            episodes.append(cur)
            cur = [b]
    episodes.append(cur)
    return [(ep[0], ep[-1], ep) for ep in episodes]


def find_all_early_watch_episodes(
    df: pd.DataFrame,
    ticker: str = "",
    recent_window: int = RECENT_WINDOW,
    episode_gap: int = EPISODE_GAP,
) -> list[EarlyWatchEvent]:
    """Semua episode Early Watch VALID (sudah lolos filter confirmation)
    sepanjang histori df, urut waktu naik. Episode tanpa BOS/CHoCH dekat
    TIDAK masuk return value (dibuang sbg noise, sesuai definisi)."""
    if df is None or len(df) < MIN_BARS_REQUIRED:
        return []
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)

    close = df["Close"]
    vidya_val = _vidya_calc(close, VIDYA_LENGTH, VIDYA_MOMENTUM)
    above_centerline = close > vidya_val

    engine_states = run_engine(df)
    is_trend_up_by_bar = {s.bar_index: s.is_trend_up for s in engine_states}
    date_by_bar = {s.bar_index: s.date for s in engine_states}

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

    early_candidates = [i for i in centerline_flips if is_trend_up_by_bar.get(i) is False]
    if not early_candidates:
        return []

    episodes_raw = _cluster_into_episodes(early_candidates, episode_gap)

    sig = compute_bullish_structure(df, ticker=ticker)
    structure_events = [e for e in sig.events if e.kind in ("BOS", "CHOCH")] if sig else []
    if not structure_events:
        return []

    out: list[EarlyWatchEvent] = []
    for start_bar, end_bar, raw in episodes_raw:
        confirmations = [
            e for e in structure_events
            if (start_bar - recent_window) <= e.bar_index <= (end_bar + recent_window)
        ]
        if not confirmations:
            continue
        confirmations.sort(key=lambda e: e.bar_index)
        bars_between = min(abs(e.bar_index - end_bar) for e in confirmations)
        out.append(EarlyWatchEvent(
            ticker=ticker,
            episode_start_date=date_by_bar.get(start_bar),
            episode_end_date=date_by_bar.get(end_bar),
            episode_start_bar=start_bar,
            episode_end_bar=end_bar,
            flicker_count=len(raw),
            confirmations=confirmations,
            bars_between=bars_between,
        ))

    out.sort(key=lambda e: e.episode_end_bar)
    return out


def find_latest_early_watch(
    df: pd.DataFrame,
    ticker: str = "",
    recent_window: int = RECENT_WINDOW,
    episode_gap: int = EPISODE_GAP,
) -> Optional[EarlyWatchEvent]:
    """Untuk scan produksi: True HANYA kalau ada episode match DAN band
    luar (is_trend_up) MASIH False di bar terakhir (kalau sudah True,
    ticker itu sudah pindah domain ke scanner Momentum, bukan Early Watch
    lagi) DAN episode itu fresh (episode_end_bar dalam recent_window bar
    dari bar terakhir). Return None kalau tidak ada yang fresh."""
    if df is None or len(df) < MIN_BARS_REQUIRED:
        return None

    engine_states = run_engine(df)
    if engine_states[-1].is_trend_up:
        return None  # band luar sudah confirmed -- domain Momentum, bukan Early Watch

    episodes = find_all_early_watch_episodes(df, ticker=ticker, recent_window=recent_window,
                                              episode_gap=episode_gap)
    if not episodes:
        return None

    n = len(df)
    cutoff = n - recent_window
    fresh = [e for e in episodes if e.episode_end_bar >= cutoff]
    if not fresh:
        return None
    return max(fresh, key=lambda e: e.latest_confirmation.bar_index)


class EarlyWatchScanner4H:
    """Scan universe (default: get_catalyst_universe(full_universe=True),
    SAMA dgn MomentumScanner4H/StructureFreshScanner) cari ticker dengan
    Early Watch episode FRESH (centerline flip + BOS/CHoCH dekat, band
    luar MASIH merah), timeframe 4h.

    EXPERIMENTAL -- lihat CATATAN VALIDASI di docstring modul ini. Pola
    orkestrasi (class, .scan() -> (results, ctx)) SENGAJA identik dgn
    MomentumScanner4H (chunking, delay, fetch tanpa cache) supaya reuse
    layout render yang sama di UI, TIDAK ada logika baru di fase fetch."""

    CHUNK_SIZE = 15
    CHUNK_DELAY = 3.0
    MAX_WORKERS = 8

    def __init__(self, recent_window: int = RECENT_WINDOW, episode_gap: int = EPISODE_GAP):
        self.recent_window = recent_window
        self.episode_gap = episode_gap

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
        logger.info(f"[EarlyWatch4H] Mulai hitung episode ({n_compute} ticker)...")

        results = []
        crashed = 0
        for idx, (ticker, df) in enumerate(data.items(), start=1):
            base_ticker = ticker.replace(".JK", "")
            try:
                ev = find_latest_early_watch(df, ticker=base_ticker,
                                              recent_window=self.recent_window,
                                              episode_gap=self.episode_gap)
            except Exception as exc:
                logger.debug(f"[EarlyWatch4H] {ticker}: engine crash — {exc}")
                crashed += 1
                continue
            if ev is not None:
                results.append(ev)
            if idx % PROGRESS_EVERY == 0 or idx == n_compute:
                logger.info(f"[EarlyWatch4H] Hitung: {idx}/{n_compute} ticker diproses "
                            f"({len(results)} episode sejauh ini, {time.time() - t_compute0:.1f}s)")

        compute_elapsed = time.time() - t_compute0
        logger.info(f"[EarlyWatch4H] Hitung selesai: {n_compute} ticker dalam "
                    f"{compute_elapsed:.1f}s ({crashed} crash)")

        results.sort(key=lambda e: e.bars_between)
        ctx = {
            "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "total_universe": len(tickers),
            "fetched_ok": len(data),
            "fetch_failed": fetch_failed,
            "crashed": crashed,
            "match_count": len(results),
        }
        logger.info(f"[EarlyWatch4H] Done: {len(results)} episode | "
                    f"{fetch_failed} fetch gagal | {crashed} crash")
        return results, ctx


if __name__ == "__main__":
    # ── Self-test dgn data SINTETIS -- buktikan logika clustering+pairing
    # mekanis benar, BUKAN bukti apa pun soal BUMI/SINI (itu tugas
    # diagnose_early_watch_episodes.py di mesin dgn akses data live). ──
    import numpy as np

    def _make_synthetic_uptrend_df(n=320, flip_at=280, eql_before_structure=True):
        # SAMA PERSIS dgn generator self-test agents/momentum_scanner.py (seed,
        # bentuk kurva) -- dipinjam sengaja krn TERBUKTI menghasilkan centerline
        # cross (bar 282) SATU bar SEBELUM band-luar confirm (vidya_flipped_up
        # bar 283) yg dipasangkan dgn CHoCH(internal) bar 286 (jarak 4, dalam
        # RECENT_WINDOW=5) -- persis skenario "early" yg mau dibuktikan di sini,
        # bukan skenario acak yg belum tentu menghasilkan match apa pun.
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

    df_syn = _make_synthetic_uptrend_df()
    all_ep = find_all_early_watch_episodes(df_syn, ticker="SYN-TEST")
    print(f"[self-test] total episode Early Watch (sudah filter confirmation) "
          f"sepanjang histori sintetis: {len(all_ep)}")
    for e in all_ep:
        print(f"  episode {e.episode_start_date.date()}..{e.episode_end_date.date()} "
              f"(#flick={e.flicker_count}) | {e.kinds_label} | jarak={e.bars_between} bar")

    assert len(all_ep) >= 1, ("SELF-TEST GAGAL: skenario sintetis ini SUDAH terbukti (lihat "
        "komentar di _make_synthetic_uptrend_df) menghasilkan 1 centerline-cross early "
        "berjarak 4 bar dari CHoCH(internal) -- 0 match berarti ada bug di clustering/pairing.")
    print("[self-test] PASS -- logika episode+pairing ketemu minimal 1 match pada skenario "
          "'early cross 1 bar sebelum band confirm' yang sudah diverifikasi manual.")

    latest = find_latest_early_watch(df_syn, ticker="SYN-TEST")
    print(f"[self-test] latest (production filter): "
          f"{'ADA -- ' + str(latest.episode_end_date.date()) if latest else 'None'}")

    # Sanity: clustering helper standalone
    clustered = _cluster_into_episodes([10, 12, 14, 50, 90, 92], gap=5)
    assert clustered == [(10, 14, [10, 12, 14]), (50, 50, [50]), (90, 92, [90, 92])], \
        "SELF-TEST GAGAL: clustering helper berubah perilaku."
    print("[self-test] PASS -- clustering helper konsisten dgn diagnose_early_watch_episodes.py.")
