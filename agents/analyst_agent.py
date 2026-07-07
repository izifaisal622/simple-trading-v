"""
Simple Trading V9 — Analyst Agent V4 (Institutional Grade)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Rules-based analysis. Zero API cost. Zero external dependency.

Architecture:
  • _g()            → typed field accessor (Union default, no Pylance errors)
  • SignalContext   → dataclass capturing all fields used in analysis
  • MarketAnalystAgent.recommend()      → per-ticker decision output
  • MarketAnalystAgent.recommend_batch() → batch BREAKOUT filter
  • MarketAnalystAgent.analyze_whale()  → WhaleSummary (dict + formatted string)

Decision philosophy (institutional):
  • Every recommendation is regime-adjusted — no blind bullish bias in bear markets.
  • Conviction = f(score, volume_quality, box_quality, RS vs IHSG, regime).
  • Risk sizing is explicit — not implied.
  • All signal tiers covered: STRONG_BREAKOUT, BREAKOUT, WATCHLIST, REVERSAL,
    DISTRIBUTION, HOLD, NEUTRAL.
  • Whale scoring uses a 5-dimension weighted matrix (not keyword matching).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Union


# ─────────────────────────────────────────────────────────────────────────────
# TYPED FIELD ACCESSOR
# Fixes all Pylance reportArgumentType errors by accepting Union default.
# ─────────────────────────────────────────────────────────────────────────────

def _g(record: Any, key: str, default: Union[str, int, float, None] = None) -> Any:
    """
    Safe accessor for dict or object records.
    Returns `default` (typed Union) instead of bare str — eliminates Pylance errors.
    """
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _f(record: Any, key: str, default: float = 0.0) -> float:
    """Typed float accessor — always returns float."""
    try:
        return float(_g(record, key, default) or default)
    except (TypeError, ValueError):
        return default


def _i(record: Any, key: str, default: int = 0) -> int:
    """Typed int accessor — always returns int."""
    try:
        return int(_g(record, key, default) or default)
    except (TypeError, ValueError):
        return default


def _s(record: Any, key: str, default: str = "") -> str:
    """Typed string accessor — always returns str."""
    v = _g(record, key, default)
    return str(v) if v is not None else default


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL CONTEXT — single structured intake for all analysis
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SignalContext:
    """
    Normalised view of a SetupResult (dict or object).
    All downstream logic reads from here — no scattered _g() calls.
    """
    ticker:        str
    score:         float
    signal:        str
    regime_tag:    str
    rs_vs_ihsg_4w: float
    atr14:         float
    vol_ratio:     float
    box_range_pct: float
    bars_in_range: int
    holding_days:  int
    close:         float
    sl_price:      float
    tp1_price:     float
    tp2_price:     float
    box_high:      float
    box_low:       float
    pengeringan:   bool
    is_reversal:   bool

    @classmethod
    def from_result(cls, r: Any) -> "SignalContext":
        ticker_raw = _s(r, "ticker", "?")
        return cls(
            ticker        = ticker_raw.replace(".JK", ""),
            score         = _f(r, "score"),
            signal        = _s(r, "signal").upper(),
            regime_tag    = _s(r, "regime_tag", "FULL"),
            rs_vs_ihsg_4w = _f(r, "rs_vs_ihsg_4w"),
            atr14         = _f(r, "atr14"),
            vol_ratio     = _f(r, "vol_ratio"),
            box_range_pct = _f(r, "box_range_pct"),
            bars_in_range = _i(r, "bars_in_range"),
            holding_days  = _i(r, "holding_days_est"),
            close         = _f(r, "close"),
            sl_price      = _f(r, "sl_price"),
            tp1_price     = _f(r, "tp1_price"),
            tp2_price     = _f(r, "tp2_price"),
            box_high      = _f(r, "box_high"),
            box_low       = _f(r, "box_low"),
            pengeringan   = bool(_g(r, "pengeringan_detected", False)),
            is_reversal   = bool(_g(r, "is_reversal_signal", False)),
        )

    @property
    def rr_ratio(self) -> float:
        """Risk/Reward to TP1."""
        risk   = self.close - self.sl_price
        reward = self.tp1_price - self.close
        if risk <= 0:
            return 0.0
        return round(reward / risk, 2)

    @property
    def sl_pct(self) -> float:
        if self.close <= 0:
            return 0.0
        return round((self.close - self.sl_price) / self.close * 100, 2)


# ─────────────────────────────────────────────────────────────────────────────
# CONVICTION ENGINE
# Replaces flat score label with multi-factor conviction rating.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ConvictionResult:
    label:      str    # TIER_1 / TIER_2 / TIER_3 / SPECULATIVE / AVOID
    score_adj:  float  # regime-adjusted composite score
    size_pct:   int    # recommended position size as % of normal
    reasoning:  list[str] = field(default_factory=list)


def _compute_sizing_tier(ctx: SignalContext) -> ConvictionResult:
    """
    Institutional conviction engine.

    Inputs:
      base score (0–8), volume quality, box quality, RS vs IHSG, regime.

    Output:
      ConvictionResult with tiered label + explicit sizing guidance.

    Sizing philosophy:
      TIER_1  → 100% normal size  (highest conviction, trend aligned)
      TIER_2  → 75%               (solid setup, minor hesitation)
      TIER_3  → 50%               (valid but one weak dimension)
      SPECULATIVE → 25%           (bear/weak regime, use sparingly)
      AVOID   → 0%                (do not trade)
    """
    reasons: list[str] = []
    adj = ctx.score * 0.8  # v9.9.1: skor kini /10 — kalibrasi ke skala analyst lama (/8), TIER tak berubah

    # ── Volume adjustment ────────────────────────────────────────────────────
    if ctx.vol_ratio >= 3.0:
        adj += 1.0
        reasons.append(f"Volume {ctx.vol_ratio:.1f}× (institusional konfirmasi)")
    elif ctx.vol_ratio >= 2.0:
        adj += 0.5
        reasons.append(f"Volume {ctx.vol_ratio:.1f}× (solid)")
    elif ctx.vol_ratio < 1.2:
        adj -= 0.5
        reasons.append(f"Volume {ctx.vol_ratio:.1f}× (lemah — retail only)")

    # ── Box / accumulation quality ───────────────────────────────────────────
    if ctx.bars_in_range >= 8 and ctx.box_range_pct <= 5.0:
        adj += 1.0
        reasons.append(f"Box ketat {ctx.box_range_pct:.1f}% / {ctx.bars_in_range} bar (pengeringan matang)")
    elif ctx.bars_in_range >= 5:
        adj += 0.5
        reasons.append(f"Konsolidasi {ctx.bars_in_range} bar (cukup)")
    elif ctx.bars_in_range < 3:
        adj -= 0.5
        reasons.append(f"Konsolidasi hanya {ctx.bars_in_range} bar (prematur)")

    # ── Pengeringan bonus ────────────────────────────────────────────────────
    if ctx.pengeringan:
        adj += 0.5
        reasons.append("Pengeringan barang terdeteksi (+0.5)")

    # ── RS vs IHSG adjustment ────────────────────────────────────────────────
    if ctx.rs_vs_ihsg_4w > 5.0:
        adj += 0.5
        reasons.append(f"RS +{ctx.rs_vs_ihsg_4w:.1f}% vs IHSG (outperform kuat)")
    elif ctx.rs_vs_ihsg_4w < -5.0:
        adj -= 1.0
        reasons.append(f"RS {ctx.rs_vs_ihsg_4w:.1f}% vs IHSG (laggard — hindari)")
    elif ctx.rs_vs_ihsg_4w < -2.0:
        adj -= 0.5
        reasons.append(f"RS {ctx.rs_vs_ihsg_4w:.1f}% vs IHSG (underperform)")

    # ── R/R quality ──────────────────────────────────────────────────────────
    rr = ctx.rr_ratio
    if rr >= 3.0:
        adj += 0.5
        reasons.append(f"R/R {rr:.1f}× (sangat baik)")
    elif rr < 1.5:
        adj -= 0.5
        reasons.append(f"R/R {rr:.1f}× (tidak layak secara matematis)")

    # ── Regime penalty ───────────────────────────────────────────────────────
    regime_penalty = {
        "WATCHLIST_ONLY": -3.0,
        "SPECULATIVE":    -1.5,
        "CAUTION":        -0.5,
        "FULL":            0.0,
        "BULL_STRONG":     0.5,
    }
    penalty = regime_penalty.get(ctx.regime_tag, 0.0)
    if penalty != 0.0:
        adj += penalty
        reasons.append(f"Regime {ctx.regime_tag} (adj {penalty:+.1f})")

    # ── Final tier mapping ───────────────────────────────────────────────────
    if ctx.regime_tag == "WATCHLIST_ONLY":
        if adj >= 6.0:
            return ConvictionResult("SPECULATIVE", adj, 25, reasons)
        return ConvictionResult("AVOID", adj, 0, reasons)

    if adj >= 8.0:
        return ConvictionResult("TIER_1", adj, 100, reasons)
    elif adj >= 6.0:
        return ConvictionResult("TIER_2", adj, 75, reasons)
    elif adj >= 4.5:
        return ConvictionResult("TIER_3", adj, 50, reasons)
    elif adj >= 3.0:
        return ConvictionResult("SPECULATIVE", adj, 25, reasons)
    else:
        return ConvictionResult("AVOID", adj, 0, reasons)


# ─────────────────────────────────────────────────────────────────────────────
# WHALE SUMMARY — structured output + formatted string
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WhaleSummary:
    """
    Structured whale activity summary.
    Access `.formatted` for display string.
    Access dict fields for downstream use (alerts, logging, Streamlit widgets).
    """
    date:            str
    cycle:           str
    ihsg:            float
    total_alerts:    int
    buy_count:       int
    sell_count:      int
    net_bias:        str          # ACCUMULATION / DISTRIBUTION / NEUTRAL
    net_bias_value:  float        # buy_val - sell_val in Bn IDR
    smart_tickers:   list[str]
    smart_avg_conv:  float
    at_floor_tickers: list[str]
    pengeringan_tickers: list[str]
    regime_note:     str
    scoring_matrix:  dict         # 5-dimension scores
    formatted:       str = field(default="", repr=False)

    def to_dict(self) -> dict:
        return {
            "date":               self.date,
            "cycle":              self.cycle,
            "ihsg":               self.ihsg,
            "total_alerts":       self.total_alerts,
            "buy_count":          self.buy_count,
            "sell_count":         self.sell_count,
            "net_bias":           self.net_bias,
            "net_bias_value_bn":  self.net_bias_value,
            "smart_tickers":      self.smart_tickers,
            "smart_avg_conviction": self.smart_avg_conv,
            "at_floor_tickers":   self.at_floor_tickers,
            "pengeringan_tickers": self.pengeringan_tickers,
            "regime_note":        self.regime_note,
            "scoring_matrix":     self.scoring_matrix,
            "formatted":          self.formatted,
        }


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL HANDLERS — one function per signal tier
# ─────────────────────────────────────────────────────────────────────────────

def _handle_strong_breakout(ctx: SignalContext, conv: ConvictionResult) -> list[str]:
    lines = [
        f"**{ctx.ticker}** ─ 🔥 STRONG BREAKOUT | {conv.label} ({ctx.score:.0f}/10 → adj {conv.score_adj:.1f})",
        f"Entry Rp{ctx.close:,.0f} | SL Rp{ctx.sl_price:,.0f} ({ctx.sl_pct:.1f}%) | "
        f"TP1 Rp{ctx.tp1_price:,.0f} | TP2 Rp{ctx.tp2_price:,.0f} | R/R {ctx.rr_ratio:.1f}×",
        f"Position size: {conv.size_pct}% normal. Entry sekarang valid — momentum sudah terkonfirmasi.",
    ]
    return lines


def _handle_breakout(ctx: SignalContext, conv: ConvictionResult) -> list[str]:
    lines = [
        f"**{ctx.ticker}** ─ BREAKOUT | {conv.label} ({ctx.score:.0f}/10 → adj {conv.score_adj:.1f})",
        f"Entry Rp{ctx.close:,.0f} | SL Rp{ctx.sl_price:,.0f} ({ctx.sl_pct:.1f}%) | "
        f"TP1 Rp{ctx.tp1_price:,.0f} | R/R {ctx.rr_ratio:.1f}×",
        f"Position size: {conv.size_pct}% normal. Entry hari ini atau besok open.",
    ]
    return lines


def _handle_watchlist(ctx: SignalContext, conv: ConvictionResult) -> list[str]:
    trigger = f"Rp{ctx.box_high:,.0f}" if ctx.box_high else "resistance terdekat"
    lines = [
        f"**{ctx.ticker}** ─ WATCHLIST | {conv.label} ({ctx.score:.0f}/10)",
        f"Belum breakout. Pasang alert di {trigger}. "
        f"Potensi entry Rp{ctx.box_high:,.0f} | TP1 Rp{ctx.tp1_price:,.0f} | R/R est {ctx.rr_ratio:.1f}×",
        "Monitor volume — butuh ≥2× average saat breakout.",
    ]
    return lines


def _handle_reversal(ctx: SignalContext, conv: ConvictionResult) -> list[str]:
    lines = [
        f"**{ctx.ticker}** ─ REVERSAL SETUP | {conv.label} ({ctx.score:.0f}/10)",
        f"Entry area Rp{ctx.close:,.0f} | SL ketat Rp{ctx.sl_price:,.0f} ({ctx.sl_pct:.1f}%) | "
        f"TP1 Rp{ctx.tp1_price:,.0f} | R/R {ctx.rr_ratio:.1f}×",
        f"Position size: {conv.size_pct}% normal (reversal = higher failure rate, size down).",
        "Konfirmasi wajib: volume bullish candle ≥1.5× dan close di atas MA20.",
    ]
    return lines


def _handle_distribution(ctx: SignalContext, conv: ConvictionResult) -> list[str]:
    lines = [
        f"**{ctx.ticker}** ─ ⚠️ DISTRIBUTION SIGNAL | JANGAN BELI.",
        f"Harga Rp{ctx.close:,.0f}. Pola distribusi aktif — smart money kemungkinan keluar.",
        "Jika sudah hold: pertimbangkan partial exit atau trailing stop ketat.",
    ]
    return lines


def _handle_hold(ctx: SignalContext, conv: ConvictionResult) -> list[str]:
    lines = [
        f"**{ctx.ticker}** ─ HOLD / MONITOR | Score {ctx.score:.0f}/10 (belum actionable)",
        "Setup belum matang. Tidak ada trigger valid hari ini.",
        f"Review kembali jika volume meningkat atau harga mendekati Rp{ctx.box_high:,.0f}.",
    ]
    return lines


_SIGNAL_HANDLERS = {
    "STRONG_BREAKOUT": _handle_strong_breakout,
    "BREAKOUT":        _handle_breakout,
    "WATCHLIST":       _handle_watchlist,
    "REVERSAL":        _handle_reversal,
    "DISTRIBUTION":    _handle_distribution,
    "HOLD":            _handle_hold,
}


# ─────────────────────────────────────────────────────────────────────────────
# WHALE SCORING MATRIX — 5-dimension weighted evaluation
# ─────────────────────────────────────────────────────────────────────────────

def _whale_scoring_matrix(whale_results: list, regime: dict) -> dict:
    """
    5-dimension scoring matrix for whale session quality.

    Dimensions (each 0–20, total 0–100):
      1. Smart Money Density   — ratio of SMART/LIKELY_SMART to total
      2. Buy-Side Momentum     — buy value vs sell value ratio
      3. Floor Price Proximity — % of buy-side entries at/near floor
      4. Accumulation Quality  — pengeringan + absorption detection
      5. Regime Alignment      — how well activity aligns with market cycle

    Returns dict of dimension scores + total.
    """
    if not whale_results:
        return {k: 0 for k in [
            "smart_density", "buy_momentum", "floor_proximity",
            "accumulation_quality", "regime_alignment", "total"
        ]}

    total       = len(whale_results)
    smart       = [w for w in whale_results if w.get("whale_quality") in ("SMART", "LIKELY_SMART")]
    buy_side    = [w for w in whale_results if w.get("is_long_signal")]
    sell_side   = [w for w in whale_results if not w.get("is_long_signal")]
    at_floor    = [w for w in buy_side if w.get("entry_zone") in ("AT_FLOOR", "NEAR_FLOOR")]
    pengeringan = [w for w in whale_results if w.get("pengeringan_detected")]
    buy_val     = sum(w.get("value_bn", 0) or 0 for w in buy_side)
    sell_val    = sum(w.get("value_bn", 0) or 0 for w in sell_side)
    cycle       = regime.get("cycle", "SIDEWAYS")

    # 1. Smart Money Density (0–20)
    smart_ratio   = len(smart) / total if total else 0
    smart_score   = min(20, round(smart_ratio * 20))

    # 2. Buy-Side Momentum (0–20)
    total_val = buy_val + sell_val
    buy_ratio = buy_val / total_val if total_val > 0 else 0.5
    buy_score = min(20, round(buy_ratio * 20))

    # 3. Floor Proximity (0–20)
    floor_ratio = len(at_floor) / len(buy_side) if buy_side else 0
    floor_score = min(20, round(floor_ratio * 20))

    # 4. Accumulation Quality (0–20)
    peng_ratio  = len(pengeringan) / total if total else 0
    # Avg conviction of smart whales
    avg_conv    = (
        sum(w.get("conviction", 0) or 0 for w in smart) / len(smart)
        if smart else 0
    )
    accum_score = min(20, round(peng_ratio * 10 + (avg_conv / 10) * 10))

    # 5. Regime Alignment (0–20)
    regime_align_map = {
        "BULL_TREND":   {"buy": 20, "neutral": 10, "sell": 2},
        "BULL_WEAK":    {"buy": 16, "neutral": 10, "sell": 4},
        "SIDEWAYS":     {"buy": 12, "neutral": 10, "sell": 8},
        "BEAR_WEAK":    {"buy": 8,  "neutral": 6,  "sell": 12},
        "BEAR_TREND":   {"buy": 4,  "neutral": 4,  "sell": 16},
    }
    align_scores = regime_align_map.get(cycle, {"buy": 10, "neutral": 10, "sell": 10})
    if buy_val > sell_val * 1.3:
        regime_score = align_scores["buy"]
    elif sell_val > buy_val * 1.3:
        regime_score = align_scores["sell"]
    else:
        regime_score = align_scores["neutral"]

    total_score = smart_score + buy_score + floor_score + accum_score + regime_score

    return {
        "smart_density":       smart_score,
        "buy_momentum":        buy_score,
        "floor_proximity":     floor_score,
        "accumulation_quality": accum_score,
        "regime_alignment":    regime_score,
        "total":               total_score,
    }


def _whale_session_grade(total_score: int) -> str:
    """Maps total matrix score to session grade."""
    if total_score >= 80:
        return "A — Kondisi ideal, semua dimensi aligned."
    elif total_score >= 60:
        return "B — Setup kuat, minor hesitation."
    elif total_score >= 40:
        return "C — Aktivitas ada tapi mixed signal."
    elif total_score >= 20:
        return "D — Lemah / bear dominan."
    else:
        return "F — Jangan trade hari ini."


# ─────────────────────────────────────────────────────────────────────────────
# MAIN AGENT CLASS
# ─────────────────────────────────────────────────────────────────────────────

class MarketAnalystAgent:
    """
    Institutional-grade rules-based analyst.

    No API key needed. No external dependency.
    All decisions are deterministic, traceable, and regime-adjusted.
    """

    def __init__(self, config: Any = None) -> None:
        self.cfg = config

    # ── Per-ticker recommendation ─────────────────────────────────────────────

    def recommend(self, result: Any) -> str:
        """
        Generate an actionable, regime-adjusted recommendation.

        Returns formatted string for direct display.
        Uses ConvictionEngine for multi-factor score adjustment.
        Dispatches to signal-specific handler for context-appropriate output.
        """
        ctx  = SignalContext.from_result(result)
        conv = _compute_sizing_tier(ctx)

        handler = _SIGNAL_HANDLERS.get(ctx.signal, _handle_hold)
        lines   = handler(ctx, conv)

        # ── Universal appended context ────────────────────────────────────────
        if conv.reasoning:
            lines.append(f"Faktor: {' | '.join(conv.reasoning)}")

        if ctx.holding_days > 0 and ctx.atr14 > 0:
            lines.append(f"Est. hold {ctx.holding_days} hari. ATR14 Rp{ctx.atr14:,.0f}.")

        if conv.label == "AVOID":
            lines.append("❌ SKIP — tidak memenuhi minimum conviction threshold.")

        return "  \n".join(lines)

    # ── Batch recommendation (BREAKOUT + STRONG_BREAKOUT filter) ─────────────

    def recommend_batch(self, results: list) -> list[dict]:
        """
        Filter actionable signals and return recommendation list.

        Only BREAKOUT and STRONG_BREAKOUT are included.
        AVOID-tier signals are excluded even if BREAKOUT signal.
        """
        out = []
        actionable = {"BREAKOUT", "STRONG_BREAKOUT"}
        for r in results:
            signal = _s(r, "signal", "").upper()
            if signal not in actionable:
                continue
            ticker = _s(r, "ticker", "?")
            try:
                ctx  = SignalContext.from_result(r)
                conv = _compute_sizing_tier(ctx)
                if conv.label == "AVOID":
                    continue
                out.append({
                    "ticker":         ticker,
                    "signal":         signal,
                    "conviction":     conv.label,
                    "size_pct":       conv.size_pct,
                    "score_adj":      round(conv.score_adj, 1),
                    "recommendation": self.recommend(r),
                })
            except Exception as exc:
                out.append({
                    "ticker":         ticker,
                    "signal":         signal,
                    "conviction":     "ERROR",
                    "size_pct":       0,
                    "score_adj":      0.0,
                    "recommendation": f"[Error generating recommendation: {exc}]",
                })
        # Sort: STRONG_BREAKOUT first, then by adj score descending
        out.sort(key=lambda x: (x["signal"] != "STRONG_BREAKOUT", -x["score_adj"]))
        return out

    # ── Whale analysis ────────────────────────────────────────────────────────

    def analyze_whale(self, whale_results: list, regime: dict) -> WhaleSummary:
        """
        Institutional whale activity analysis.

        Returns WhaleSummary dataclass with:
          • All structured fields (for downstream use / Streamlit widgets)
          • .formatted  → display string
          • .to_dict()  → dict for logging/JSON export

        Decision quality:
          • 5-dimension scoring matrix (not keyword matching)
          • Regime-adjusted interpretation
          • Explicit session grade (A–F)
          • Actionable regime-specific guidance
        """
        date_str = datetime.now().strftime("%d %b %Y")
        cycle    = regime.get("cycle", "SIDEWAYS")
        ihsg     = float(regime.get("ihsg", 0) or 0)

        # ── Empty guard ───────────────────────────────────────────────────────
        if not whale_results:
            empty = WhaleSummary(
                date=date_str, cycle=cycle, ihsg=ihsg,
                total_alerts=0, buy_count=0, sell_count=0,
                net_bias="NEUTRAL", net_bias_value=0.0,
                smart_tickers=[], smart_avg_conv=0.0,
                at_floor_tickers=[], pengeringan_tickers=[],
                regime_note="Tidak ada data whale hari ini.",
                scoring_matrix=_whale_scoring_matrix([], regime),
                formatted="Tidak ada aktivitas whale hari ini.",
            )
            return empty

        # ── Classify ──────────────────────────────────────────────────────────
        smart       = [w for w in whale_results if w.get("whale_quality") in ("SMART", "LIKELY_SMART")]
        buy_side    = [w for w in whale_results if w.get("is_long_signal")]
        sell_side   = [w for w in whale_results if not w.get("is_long_signal")]
        at_floor    = [w for w in buy_side if w.get("entry_zone") in ("AT_FLOOR", "NEAR_FLOOR")]
        pengeringan = [w for w in whale_results if w.get("pengeringan_detected")]

        buy_val  = sum(w.get("value_bn", 0) or 0 for w in buy_side)
        sell_val = sum(w.get("value_bn", 0) or 0 for w in sell_side)

        # ── Net bias ──────────────────────────────────────────────────────────
        if buy_val > sell_val * 1.5:
            net_bias = "ACCUMULATION"
        elif sell_val > buy_val * 1.5:
            net_bias = "DISTRIBUTION"
        else:
            net_bias = "NEUTRAL"

        # ── Smart whale details ───────────────────────────────────────────────
        smart_sorted  = sorted(smart, key=lambda x: -(x.get("conviction", 0) or 0))
        smart_tickers = [w["ticker"].replace(".JK", "") for w in smart_sorted[:5]]
        smart_avg_conv = (
            sum(w.get("conviction", 0) or 0 for w in smart) / len(smart)
            if smart else 0.0
        )

        at_floor_tickers = [w["ticker"].replace(".JK", "") for w in at_floor[:5]]
        peng_tickers     = [w["ticker"].replace(".JK", "") for w in pengeringan[:5]]

        # ── Scoring matrix ────────────────────────────────────────────────────
        matrix = _whale_scoring_matrix(whale_results, regime)
        grade  = _whale_session_grade(matrix["total"])

        # ── Regime-specific guidance ──────────────────────────────────────────
        regime_guidance = {
            "BULL_TREND":  "Bull trend aktif — prioritaskan setup at-floor dengan volume kuat. Full size valid.",
            "BULL_WEAK":   "Bull melemah — selektif. Fokus TIER_1 saja. Kurangi 25% size dari normal.",
            "SIDEWAYS":    "Sideways — hanya floor price setup. Skip setup di tengah range.",
            "BEAR_WEAK":   "Bear awal — max 25% normal size. Build watchlist untuk reversal nanti.",
            "BEAR_TREND":  "BEAR TREND aktif — JANGAN beli kecuali reversal terkonfirmasi. "
                           "Fokus build recovery watchlist.",
        }
        regime_note = regime_guidance.get(cycle, "Kondisi pasar tidak teridentifikasi — hati-hati.")

        # ── Format output ─────────────────────────────────────────────────────
        parts = []
        parts.append(
            f"**Whale Activity — {date_str}** | {cycle} | IHSG {ihsg:,.0f}"
        )
        parts.append(
            f"{len(whale_results)} alerts: {len(buy_side)} beli (Rp{buy_val:.1f}B) "
            f"vs {len(sell_side)} jual (Rp{sell_val:.1f}B) — **{net_bias}**"
        )
        parts.append(
            f"Session Score: {matrix['total']}/100 — {grade}"
        )
        parts.append(
            f"  Smart:{matrix['smart_density']} | "
            f"Buy:{matrix['buy_momentum']} | "
            f"Floor:{matrix['floor_proximity']} | "
            f"Accum:{matrix['accumulation_quality']} | "
            f"Regime:{matrix['regime_alignment']}"
        )

        if smart_tickers:
            parts.append(
                f"Smart whale aktif: {', '.join(smart_tickers)} "
                f"(avg conviction {smart_avg_conv:.1f}/10)"
            )

        if at_floor_tickers:
            parts.append(
                f"Setup terbaik — at/near floor: {', '.join(at_floor_tickers)} "
                f"(R/R terfavorit, prioritaskan)"
            )

        if peng_tickers:
            parts.append(
                f"Pengeringan terdeteksi: {', '.join(peng_tickers)} "
                f"— barang berpindah ke smart money"
            )

        parts.append(f"Regime note: {regime_note}")

        formatted = "  \n".join(parts)

        return WhaleSummary(
            date             = date_str,
            cycle            = cycle,
            ihsg             = ihsg,
            total_alerts     = len(whale_results),
            buy_count        = len(buy_side),
            sell_count       = len(sell_side),
            net_bias         = net_bias,
            net_bias_value   = round(buy_val - sell_val, 2),
            smart_tickers    = smart_tickers,
            smart_avg_conv   = round(smart_avg_conv, 1),
            at_floor_tickers = at_floor_tickers,
            pengeringan_tickers = peng_tickers,
            regime_note      = regime_note,
            scoring_matrix   = matrix,
            formatted        = formatted,
        )
