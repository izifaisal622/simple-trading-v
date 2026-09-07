"""
agents/momentum_scanner.py — Scanner "Momentum": gabungan VIDYA-flip
(core/ob_engine.py) + struktur bullish BOS/CHoCH (core/structure_signals.py),
timeframe 4h. DRAFT hasil sesi diskusi 2026-09-05 dengan user — BELUM
divalidasi terhadap data live (lihat CATATAN PENTING di bawah).

KENAPA FILE TERPISAH: sama prinsipnya dengan agents/structure_scanner.py dan
agents/golden_setup_scanner.py — ADITIF, tidak mengubah core/ob_engine.py,
core/structure_signals.py, atau pipeline produksi manapun. File ini HANYA
mengorkestrasi dua engine yang SUDAH ada & tervalidasi terpisah:
  - core/ob_engine.run_engine()            -> is_trend_up, vidya_flipped_up
  - core/structure_signals.compute_bullish_structure() -> BOS/CHoCH/EQL

DEFINISI MATCH (disepakati eksplisit dengan user, sesi 2026-09-05, dari 3
study case: BUMI 17-Jul-2026, SINI 18-Aug-2026, UANG 31-Aug-2026):
  - Layer A (VIDYA flip, WAJIB): event vidya_flipped_up (state
    is_trend_up berubah False/None -> True).
  - Layer B (struktur, WAJIB, union): minimal satu event BOS ATAU CHoCH
    (scope internal ATAU swing — union, BOS/CHoCH scr mekanis adalah event
    yang SAMA, cuma beda label tergantung bias sebelumnya — lihat docstring
    core/structure_signals.py) dengan bar_index dalam jarak <= RECENT_WINDOW
    bar dari bar_index event flip tsb. Window SIMETRIS (bukan strict
    "struktur harus sesudah flip") karena urutan di 3 study case tidak
    konsisten: SINI CHoCH persis di candle breakout yang sama dgn flip;
    UANG CHoCH muncul sesudah cluster EQL+star. Kalau asumsi ini salah,
    lihat parameter `symmetric_window` di find_all_momentum_events().
  - Layer C (EQL, OPSIONAL — TIDAK menggugurkan match): kalau ada event EQL
    dengan bar_index < bar_index structure event di atas, ditandai
    high_conviction=True. Ini murni tag informasi tambahan di card, sesuai
    keputusan user structure event EQL bersifat opsional bukan wajib.

RECENT_WINDOW = 5 bar (4h) — disepakati eksplisit dengan user.

CATATAN PENTING — WAJIB dibaca sebelum lanjut ke Fase 2 (UI wiring):

  (1) UNIVERSE — DIPUTUSKAN user 2026-09-05: pakai get_catalyst_universe(
      full_universe=True), SAMA PERSIS yang dipakai StructureFreshScanner
      di Page 1 (agents/structure_scanner.py, dipanggil tanpa argumen dari
      pages/1_VIDYA_SMC_Zone.py -> default full_universe=True). Ini universe
      DINAMIS (stage-0 liquidity screen + movers, di-cache harian) — jumlah
      561 yang disebut user adalah snapshot HARI scan itu, bukan angka
      tetap. MomentumScanner4H di bawah pakai fungsi yang sama.

  (2) RISIKO BELUM TERUJI — fetch_4h() (dipakai MomentumScanner4H) TIDAK
      punya caching (beda dari DataFeed.fetch_batch() yang dipakai
      StructureFreshScanner utk daily scan — itu SUDAH ada incremental
      cache pipeline). Setiap scan Momentum akan selalu re-download 60m
      raw x 729 hari utk SEMUA ticker di universe, dari nol, setiap kali.
      agents/golden_setup_scanner.py SENGAJA dibatasi ke 40 ticker justru
      karena risiko ini (lihat docstring-nya) — scan 561 ticker via
      fetch_4h() BELUM PERNAH dicoba siapa pun di proyek ini. Mitigasi yang
      dipakai di sini: chunk=15 + delay 3 detik antar chunk, ANGKA INI
      DIPINJAM dari pola yang sudah terbukti aman di
      core/data_feed.py fetch_batch._batch_download() (yg jg diturunkan
      dari 40->15 setelah kena rate-limit) — TAPI itu divalidasi utk
      endpoint DAILY, belum utk 60m intraday, dan environment yang menulis
      file ini TIDAK BISA mengetes sendiri (tidak ada akses network).
      REKOMENDASI: jangan langsung scan 561 di percobaan pertama — panggil
      MomentumScanner4H().scan(tickers=get_catalyst_universe(full_universe=True)[:50])
      dulu, cek log ada rate-limit error atau tidak, baru naikkan bertahap.

  (3) BELUM DIVALIDASI TERHADAP DATA LIVE — environment yang menulis file
      ini tidak punya akses network ke Yahoo Finance (dicoba, gagal
      403/ConnectionError). find_all_momentum_events() SUDAH lolos
      self-test dengan data sintetis (lihat blok __main__ di bawah, atau
      jalankan `python agents/momentum_scanner.py`) yang membuktikan
      LOGIKA PENGGABUNGAN-nya benar (window, union BOS/CHoCH, EQL
      high_conviction) — tapi BELUM ada bukti bahwa BUMI/SINI/UANG di
      tanggal yang disebut user benar-benar ke-detect. WAJIB jalankan
      validate_momentum_cases.py (di root repo) di mesin dengan akses data
      live SEBELUM percaya scanner ini benar, dan sebelum lanjut Fase 2.
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
from core.ob_engine import run_engine
from core.structure_signals import compute_bullish_structure

logger = logging.getLogger(__name__)

MIN_BARS_REQUIRED = 260  # buffer ATR(200) + swing(50) — sama kontrak dgn scanner lain
RECENT_WINDOW = 5        # bar 4h — disepakati eksplisit dengan user, sesi 2026-09-05
EQL_LOOKBACK_WINDOW = 20  # bar 4h (~10 hari bursa) — BELUM disepakati eksplisit dgn
# user, angka ASUMSI saya berdasarkan narasi study case UANG ("EQL+star duluan,
# baru CHoCH"). v1 SEBELUMNYA cek "EQL kapan saja di SELURUH histori sebelum
# structure event" -- bug: menghasilkan high_conviction=True nyaris 100% dari
# waktu (terbukti di validate_momentum_cases.py run pertama: 38/38 match True)
# karena data 3 tahun hampir selalu punya EQL di suatu titik sebelumnya. Fix:
# batasi ke EQL_LOOKBACK_WINDOW bar SEBELUM structure event -- kalau angka 20
# ini ternyata tidak sesuai maksud user, sesuaikan di sini.


@dataclass
class MomentumMatch:
    ticker: str
    flip_date: object
    flip_bar_index: int
    confirmations: list       # SEMUA StructureEvent (BOS/CHoCH, scope apapun) dlm window —
    # BUKAN cuma 1 yang "terdekat". v1 sebelumnya cuma nyimpen 1 dan MEMBUANG sisanya
    # kalau ada >1 event valid dlm window yang sama (bug ketemu dari kasus nyata UANG
    # 2026-09: BOS(internal)@09-02 DAN CHoCH(swing)@09-03 sama-sama valid dlm window
    # dari 1 flip yang sama, tapi versi lama cuma nunjukkin CHoCH-nya, BOS-nya hilang).
    # Fix ini niru pola yang SUDAH ada di agents/structure_scanner.py: "kalau lebih
    # dari satu jenis event match, SEMUA ditampilkan, bukan cuma 1."
    bars_between: int          # jarak flip ke confirmation TERDEKAT (utk sort freshness)
    high_conviction: bool = False   # True kalau ada EQL dlm EQL_LOOKBACK_WINDOW sblm confirmation terbaru
    eql_date: Optional[object] = None
    delta_volume_pct: Optional[float] = None

    @property
    def kinds_label(self) -> str:
        """String ringkas semua confirmation, mis. 'BOS(internal)+CHOCH(swing)' —
        buat ditampilkan di card tanpa caller perlu loop manual."""
        return "+".join(f"{c.kind}({c.scope})" for c in self.confirmations)

    @property
    def latest_confirmation(self):
        """Confirmation dgn bar_index PALING BESAR (paling baru) — dipakai kalau
        caller cuma butuh satu titik acuan, mis. utk anchor tanggal di UI."""
        return max(self.confirmations, key=lambda c: c.bar_index)


def find_all_momentum_events(
    df: pd.DataFrame,
    ticker: str = "",
    recent_window: int = RECENT_WINDOW,
    symmetric_window: bool = True,
) -> list[MomentumMatch]:
    """
    Jalankan KEDUA engine atas satu df, dan untuk tiap event VIDYA-flip-up
    kumpulkan SEMUA event struktur BOS/CHoCH (scope internal MAUPUN swing)
    yang bar_index-nya dalam jarak <= recent_window dari bar flip tsb — bukan
    cuma yang terdekat (lihat catatan di MomentumMatch.confirmations soal
    kenapa berubah dari versi awal). Kembalikan SEMUA kejadian match
    sepanjang histori df (urut waktu naik) — BUKAN cuma yang terbaru. Dipakai
    baik untuk scan produksi (caller filter ke bar terbaru sendiri, lihat
    find_latest_momentum_match) maupun untuk validasi terhadap tanggal
    historis spesifik.

    df wajib kolom Open/High/Low/Close/Volume, index tanggal urut naik —
    kontrak sama dengan core/ob_engine.run_engine() dan
    core/structure_signals.compute_bullish_structure().

    symmetric_window=True (default): structure event boleh SEBELUM atau
    SESUDAH bar flip, asal |jarak| <= recent_window. Set False untuk
    varian strict "structure harus muncul PADA ATAU SESUDAH bar flip" kalau
    ternyata itu yang dimaksud user setelah validasi data live.

    CATATAN: flip yang berdekatan (mis. dua flip 4 bar terpisah, kasus nyata
    BUMI 2026-07-21 & 2026-07-23) BISA menghasilkan confirmation yang
    tumpang-tindih antar match — ini SENGAJA tidak di-dedup, karena kedua
    flip itu masing-masing memang punya confirmation valid sendiri
    (dibuktikan dari data live, lihat diagnose_momentum_window.py run
    2026-09). Kalau nanti ternyata bikin card produksi terlalu berisik
    (duplikat/mirip), pertimbangkan clustering flip yang berdekatan jadi 1
    match sebelum lanjut Fase 2 — TIDAK dilakukan di sini supaya scope fix
    ini tetap sempit (cuma perbaiki data yang hilang, bukan re-desain
    granularity match).
    """
    if df is None or len(df) < MIN_BARS_REQUIRED:
        return []
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)

    engine_states = run_engine(df)
    flip_states = [s for s in engine_states if s.vidya_flipped_up]
    if not flip_states:
        return []

    sig = compute_bullish_structure(df, ticker=ticker)
    if sig is None:
        return []

    structure_events = [e for e in sig.events if e.kind in ("BOS", "CHOCH")]
    eql_events = [e for e in sig.events if e.kind == "EQL"]
    if not structure_events:
        return []

    delta_by_bar = {s.bar_index: s.delta_volume_pct for s in engine_states}

    matches: list[MomentumMatch] = []

    for flip in flip_states:
        confirmations = []
        for ev in structure_events:
            dist = ev.bar_index - flip.bar_index
            if symmetric_window:
                if abs(dist) <= recent_window:
                    confirmations.append(ev)
            else:
                if 0 <= dist <= recent_window:
                    confirmations.append(ev)
        if not confirmations:
            continue
        confirmations.sort(key=lambda e: e.bar_index)
        anchor_bar = max(e.bar_index for e in confirmations)  # confirmation TERBARU —
        # dipakai sbg titik acuan EQL-lookback & delta-volume, konsisten dgn "state
        # akhir setelah semua confirmation di window ini selesai terbentuk".
        bars_between = min(abs(e.bar_index - flip.bar_index) for e in confirmations)

        eql_cutoff = anchor_bar - EQL_LOOKBACK_WINDOW
        eql_before = [e for e in eql_events if eql_cutoff <= e.bar_index < anchor_bar]
        eql_ev = max(eql_before, key=lambda e: e.bar_index) if eql_before else None

        matches.append(MomentumMatch(
            ticker=ticker,
            flip_date=flip.date, flip_bar_index=flip.bar_index,
            confirmations=confirmations,
            bars_between=bars_between,
            high_conviction=eql_ev is not None,
            eql_date=eql_ev.date if eql_ev else None,
            delta_volume_pct=round(delta_by_bar.get(anchor_bar, 0.0), 2),
        ))

    matches.sort(key=lambda m: m.flip_bar_index)
    return matches


def find_latest_momentum_match(
    df: pd.DataFrame,
    ticker: str = "",
    recent_window: int = RECENT_WINDOW,
) -> Optional[MomentumMatch]:
    """
    Untuk scan produksi: True HANYA kalau ada match dan (a) trend masih up
    di bar TERAKHIR (belum flip balik turun sejak match itu), dan (b) bar
    flip match tsb berada dalam recent_window bar dari bar terakhir (fresh,
    bukan setup lama). Return None kalau tidak ada match fresh.
    """
    if df is None or len(df) < MIN_BARS_REQUIRED:
        return None
    matches = find_all_momentum_events(df, ticker=ticker, recent_window=recent_window)
    if not matches:
        return None

    engine_states = run_engine(df)
    if not engine_states[-1].is_trend_up:
        return None  # sudah flip balik turun -- momentum tidak aktif lagi

    n = len(df)
    cutoff = n - recent_window
    fresh = [m for m in matches if m.flip_bar_index >= cutoff]
    if not fresh:
        return None
    return max(fresh, key=lambda m: m.latest_confirmation.bar_index)


class MomentumScanner4H:
    """Scan universe (default: get_catalyst_universe(full_universe=True) —
    SAMA dengan default StructureFreshScanner di Page 1) cari ticker dengan
    Momentum match FRESH (VIDYA flip + BOS/CHoCH dalam recent_window bar,
    trend masih up), timeframe 4h.

    BELUM PERNAH DIUJI DI SKALA INI — baca CATATAN PENTING (2) di docstring
    modul ini SEBELUM menjalankan scan(tickers=None) (full universe). Coba
    scope kecil dulu (mis. 50 ticker) lewat parameter `tickers`.

    Pola orkestrasi (class, .scan() -> (results, ctx)) sengaja dibuat
    konsisten dengan StructureFreshScanner/GoldenSetupScanner4H yang sudah
    ada, supaya gampang di-render pakai layout card yang sama di Page 1/2."""

    CHUNK_SIZE = 15    # dipinjam dari core/data_feed.py fetch_batch._batch_download
    CHUNK_DELAY = 3.0  # detik — sama alasan, BELUM divalidasi utk endpoint 60m/4h
    MAX_WORKERS = 8    # sama dgn default max_workers DataFeed.fetch_batch

    def __init__(self, recent_window: int = RECENT_WINDOW):
        self.recent_window = recent_window

    def _fetch_all(self, tickers: list) -> dict:
        """Download fetch_4h() utk semua ticker, di-chunk dgn delay antar
        chunk (mitigasi rate-limit — lihat CATATAN PENTING (2)). Dalam satu
        chunk, fetch jalan konkuren (ThreadPoolExecutor) — fetch_4h()
        sendiri TIDAK diubah sama sekali, cuma dipanggil banyak kali."""
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
                        logger.debug(f"[Momentum4H] fetch {t}: {exc}")
            logger.info(f"[Momentum4H] chunk {ci + 1}/{len(chunks)} done "
                        f"({len(results)} ticker fetched so far)")
            if ci < len(chunks) - 1:
                time.sleep(self.CHUNK_DELAY)
        return results

    def scan(self, tickers: Optional[list] = None) -> tuple:
        tickers = tickers if tickers is not None else get_catalyst_universe(full_universe=True)
        logger.info(f"[Momentum4H] Universe: {len(tickers)} ticker — fetch_4h() chunked "
                    f"({self.CHUNK_SIZE}/chunk, delay {self.CHUNK_DELAY}s)...")

        data = self._fetch_all(tickers)
        fetch_failed = len(tickers) - len(data)
        logger.info(f"[Momentum4H] Fetch selesai: {len(data)}/{len(tickers)} berhasil "
                    f"({fetch_failed} gagal/skip)")

        # ── Fase hitung (CPU-bound: run_engine + compute_bullish_structure per
        # ticker) — TIDAK ADA logging sebelumnya di fase ini sama sekali, jadi
        # kalau lambat/macet, log terakhir yang kelihatan cuma "Fetch selesai"
        # di atas, dan tidak ada cara membedakan "masih jalan" vs "hang" vs
        # "crash tak tercatat". Ketemu masalah ini pas trial 560 ticker
        # (2026-09-07) — output berhenti persis di baris "Fetch selesai" tanpa
        # kejelasan. Fix: heartbeat progress tiap PROGRESS_EVERY ticker +
        # timing eksplisit, murni observability, TIDAK mengubah logika match.
        PROGRESS_EVERY = 50
        n_compute = len(data)
        t_compute0 = time.time()
        logger.info(f"[Momentum4H] Mulai hitung match ({n_compute} ticker, "
                    f"engine per-ticker, tidak ada progress log sebelum fix ini)...")

        results = []
        crashed = 0
        for idx, (ticker, df) in enumerate(data.items(), start=1):
            base_ticker = ticker.replace(".JK", "")
            try:
                m = find_latest_momentum_match(df, ticker=base_ticker, recent_window=self.recent_window)
            except Exception as exc:
                logger.debug(f"[Momentum4H] {ticker}: engine crash — {exc}")
                crashed += 1
                continue
            if m is not None:
                results.append(m)
            if idx % PROGRESS_EVERY == 0 or idx == n_compute:
                logger.info(f"[Momentum4H] Hitung match: {idx}/{n_compute} ticker diproses "
                            f"({len(results)} match sejauh ini, {time.time() - t_compute0:.1f}s)")

        compute_elapsed = time.time() - t_compute0
        logger.info(f"[Momentum4H] Hitung match selesai: {n_compute} ticker dalam "
                    f"{compute_elapsed:.1f}s ({crashed} crash)")

        results.sort(key=lambda m: m.bars_between)
        ctx = {
            "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "total_universe": len(tickers),
            "fetched_ok": len(data),
            "fetch_failed": fetch_failed,
            "crashed": crashed,
            "match_count": len(results),
            "high_conviction_count": sum(1 for m in results if m.high_conviction),
        }
        logger.info(f"[Momentum4H] Done: {len(results)} match "
                    f"({ctx['high_conviction_count']} high conviction) | "
                    f"{fetch_failed} fetch gagal | {crashed} crash")
        return results, ctx


if __name__ == "__main__":
    # ── Self-test dengan data SINTETIS (bukan data pasar nyata) ──
    # Tujuannya HANYA membuktikan logika pairing/window/EQL benar secara
    # mekanis. TIDAK membuktikan apa pun soal BUMI/SINI/UANG -- itu tugas
    # validate_momentum_cases.py di mesin dengan akses data live.
    import numpy as np

    def _make_synthetic_uptrend_df(n=320, flip_at=280, structure_at=283,
                                     eql_before_structure=True):
        rng = np.random.default_rng(42)
        dates = pd.date_range("2024-01-01", periods=n, freq="4h")
        # Downtrend landai sampai flip_at, lalu uptrend tajam sesudahnya --
        # supaya VIDYA (EMA-like) & swing/internal pivot punya bahan yg jelas.
        base = np.concatenate([
            np.linspace(200, 100, flip_at) + rng.normal(0, 0.5, flip_at),
            np.linspace(100, 220, n - flip_at) + rng.normal(0, 0.5, n - flip_at),
        ])
        # Selipkan pola equal-low sebelum structure event kalau diminta
        if eql_before_structure:
            eq_idx = structure_at - 8
            base[eq_idx] = base[eq_idx - 5] * 1.0  # samakan dua low berdekatan
        close = pd.Series(base, index=dates)
        high = close + rng.uniform(0.5, 2.0, n)
        low = close - rng.uniform(0.5, 2.0, n)
        open_ = close.shift(1).fillna(close.iloc[0])
        vol = pd.Series(rng.uniform(1e6, 5e6, n), index=dates)
        return pd.DataFrame({"Open": open_, "High": high, "Low": low,
                              "Close": close, "Volume": vol}, index=dates)

    df_syn = _make_synthetic_uptrend_df()
    all_events = find_all_momentum_events(df_syn, ticker="SYN-TEST")
    print(f"[self-test] total match sepanjang histori sintetis: {len(all_events)}")
    for m in all_events:
        conf_str = ", ".join(f"{c.kind}({c.scope})@{c.date.date()}" for c in m.confirmations)
        print(f"  flip={m.flip_date.date()} bar={m.flip_bar_index} | {conf_str} | "
              f"jarak={m.bars_between} bar | high_conviction={m.high_conviction}")

    assert len(all_events) >= 1, "SELF-TEST GAGAL: uptrend sintetis jelas tapi 0 match -- ada bug di pairing/window."
    print("[self-test] PASS -- logika pairing/window ketemu minimal 1 match pada uptrend sintetis yang jelas.")
