"""
Simple Trading V9 — Alert Agent V2 (Institutional)
====================================================
UPGRADE V2:
  • Removed unused List, Optional imports
  • score display updated 7→8 (matches V6.5 cap)
  • STRONG_BREAKOUT signal added to breakout category
  • VP entry zone displayed in Telegram breakout alert
  • All _g() calls preserved (dict/object compat)
  • Typed where unambiguous
"""

import logging
import requests
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def _g(r: Any, field: str, default: Any = "") -> Any:
    if isinstance(r, dict):
        return r.get(field, default)
    return getattr(r, field, default)


class AlertAgent:

    def __init__(self, config: Any) -> None:
        self.cfg = config

    # ── Console report ────────────────────────────────────────────────────────

    def print_report(
        self,
        results: list,
        recommendations: list | None = None,
        regime: dict | None = None,
    ) -> None:
        recommendations = recommendations or []
        regime          = regime or {}
        rec_map = {r.get("ticker"): r.get("recommendation", "") for r in recommendations}

        strong_bos = [r for r in results if _g(r, "signal") == "STRONG_BREAKOUT"]
        breakouts  = [r for r in results if _g(r, "signal") == "BREAKOUT"]
        watchlists = [r for r in results if _g(r, "signal") == "WATCHLIST"]
        correcting = [r for r in results if _g(r, "signal") in ("CORRECTING", "DEEP_CORRECT")]

        cycle  = regime.get("cycle", "")
        ihsg   = regime.get("ihsg", 0)
        mom_4w = regime.get("mom_4w", 0)

        print(f"\n{'='*60}")
        print(f"  EMA XBO Scan Results — {datetime.now().strftime('%d %b %Y %H:%M')}")
        print(f"  Total setups: {len(results)}")
        if cycle:
            mom_str = f"{mom_4w:+.1f}%" if isinstance(mom_4w, (int, float)) else "—"
            print(f"  Regime: {cycle} | IHSG {ihsg:,.0f} | 4W {mom_str}")
        print(f"{'='*60}")

        if cycle in ("BEAR_TREND", "BEAR_CONSOLIDATION"):
            print(f"\n  ⚠️  {cycle} — Reduce size or sit out. Only A-grade setups.")

        def _print_setup(r: Any, score_cap: int = 8) -> None:
            ticker    = str(_g(r, "ticker", "?")).replace(".JK", "")
            score     = _g(r, "score", 0)
            close     = _g(r, "close", 0)
            sl_price  = _g(r, "sl_price", 0)
            risk_pct  = _g(r, "risk_pct", 0)
            tp1_price = _g(r, "tp1_price", 0)
            rr_ratio  = _g(r, "rr_ratio", 0)
            box_range = _g(r, "box_range_pct", 0)
            bars      = _g(r, "bars_in_range", 0)
            vol_ratio = _g(r, "vol_ratio", 0)
            cross     = _g(r, "cross_state", "")
            dual_ok   = _g(r, "dual_confirmed", False)
            vp_zone   = _g(r, "vp_entry_zone", "")

            dual_tag  = " ✓DUAL" if dual_ok else ""
            vp_tag    = f" [{vp_zone}]" if vp_zone and vp_zone != "UNKNOWN" else ""
            print(f"  {ticker:<12} Score {score}/{score_cap}  |  "
                  f"Entry Rp{close:,.0f}  |  SL Rp{sl_price:,.0f} ({risk_pct}%)  |  "
                  f"TP1 Rp{tp1_price:,.0f}  |  R:R {rr_ratio}:1{dual_tag}{vp_tag}")
            try:
                print(f"             Box {float(box_range):.1f}% | {bars} bars | "
                      f"Vol {float(vol_ratio):.1f}× | {cross}")
            except (TypeError, ValueError):
                print(f"             Box {box_range}% | {bars} bars | Vol {vol_ratio}× | {cross}")

            ms_label = _g(r, "ms_structure", "")
            if ms_label and ms_label not in ("UNKNOWN", ""):
                print(f"             📐 Structure: {ms_label}")

            rec = rec_map.get(ticker + ".JK", rec_map.get(ticker, ""))
            if rec:
                print(f"             💬 {rec[:120]}")
            print()

        if strong_bos:
            print(f"\n🔥 STRONG BREAKOUT ({len(strong_bos)})")
            print("-" * 50)
            for r in strong_bos:
                _print_setup(r)

        if breakouts:
            print(f"\n🟢 BREAKOUT SIGNALS ({len(breakouts)})")
            print("-" * 50)
            for r in breakouts:
                _print_setup(r)

        if watchlists:
            print(f"\n🟡 WATCHLIST ({len(watchlists)})")
            print("-" * 50)
            for r in watchlists:
                ticker    = str(_g(r, "ticker", "?")).replace(".JK", "")
                score     = _g(r, "score", 0)
                close     = _g(r, "close", 0)
                box_range = _g(r, "box_range_pct", 0)
                bars      = _g(r, "bars_in_range", 0)
                vol_ratio = _g(r, "vol_ratio", 0)
                vp_zone   = _g(r, "vp_entry_zone", "")
                vp_tag    = f" [{vp_zone}]" if vp_zone and vp_zone != "UNKNOWN" else ""
                try:
                    print(f"  {ticker:<12} Score {score}/8  |  "
                          f"Entry Rp{close:,.0f}  |  Box {float(box_range):.1f}% | "
                          f"{bars} bars | Vol {float(vol_ratio):.1f}×{vp_tag}")
                except (TypeError, ValueError):
                    print(f"  {ticker:<12} Score {score}/8  |  Entry Rp{close:,.0f}")

        if correcting:
            print(f"\n🟠 CORRECTING / WATCH ({len(correcting)})")
            print("-" * 50)
            top = sorted(correcting, key=lambda x: -(_g(x, "score", 0) or 0))[:10]
            for r in top:
                ticker = str(_g(r, "ticker", "?")).replace(".JK", "")
                signal = _g(r, "signal", "")
                score  = _g(r, "score", 0)
                close  = _g(r, "close", 0)
                cross  = _g(r, "cross_state", "")
                try:
                    print(f"  {ticker:<12} {signal:<14} Score {score}/8  |  "
                          f"Rp{close:,.0f}  |  {cross}")
                except (TypeError, ValueError):
                    print(f"  {ticker:<12} {signal:<14} Score {score}/8")

        if not results:
            msg = "  No qualifying setups today."
            if cycle == "BEAR_TREND":
                msg += " Bear market aktif — tunggu konfirmasi reversal."
            elif cycle == "BEAR_CONSOLIDATION":
                msg += " Market masih konsolidasi — be selective."
            print(f"\n{msg}")

        print(f"\n{'='*60}\n")

    # ── Telegram ──────────────────────────────────────────────────────────────

    def _send_telegram(self, message: str) -> bool:
        token   = self.cfg.telegram_token
        chat_id = self.cfg.telegram_chat_id
        if not token or not chat_id:
            logger.debug("[Alert] Telegram not configured — skipping")
            return False
        try:
            url  = f"https://api.telegram.org/bot{token}/sendMessage"
            resp = requests.post(url, json={
                "chat_id": chat_id, "text": message, "parse_mode": "HTML",
            }, timeout=10)
            if resp.status_code == 200:
                logger.info("[Alert] Telegram sent ✓")
                return True
            logger.warning(f"[Alert] Telegram {resp.status_code}: {resp.text[:100]}")
            return False
        except Exception as exc:
            logger.warning(f"[Alert] Telegram failed: {exc}")
            return False

    def send_breakout_alert(self, result: Any, recommendation: str = "") -> bool:
        ticker    = str(_g(result, "ticker", "?")).replace(".JK", "")
        signal    = _g(result, "signal", "BREAKOUT")
        score     = _g(result, "score", 0)
        close     = _g(result, "close", 0)
        sl_price  = _g(result, "sl_price", 0)
        risk_pct  = _g(result, "risk_pct", 0)
        tp1_price = _g(result, "tp1_price", 0)
        tp2_price = _g(result, "tp2_price", 0)
        box_range = _g(result, "box_range_pct", 0)
        bars      = _g(result, "bars_in_range", 0)
        vol_ratio = _g(result, "vol_ratio", 0)
        dual_ok   = _g(result, "dual_confirmed", False)
        vp_zone   = _g(result, "vp_entry_zone", "")

        dual_tag = " ✓ Dual TF confirmed" if dual_ok else ""
        fire_tag = "🔥 " if signal == "STRONG_BREAKOUT" else ""
        try:
            vol_str = f"{float(vol_ratio):.1f}×"
            box_str = f"{float(box_range):.1f}%"
        except (TypeError, ValueError):
            vol_str = str(vol_ratio)
            box_str = str(box_range)

        vp_line = f"\n📊 VP Zone: {vp_zone}" if vp_zone and vp_zone != "UNKNOWN" else ""

        msg = (
            f"🚨 <b>{fire_tag}BREAKOUT ALERT</b>\n\n"
            f"📊 <b>{ticker}</b> — Score {score}/8{dual_tag}\n"
            f"💰 Entry: Rp{close:,.0f}\n"
            f"🛡 SL: Rp{sl_price:,.0f} ({risk_pct}%)\n"
            f"🎯 TP1: Rp{tp1_price:,.0f} | TP2: Rp{tp2_price:,.0f}\n"
            f"📦 Box: {box_str} | {bars} bars\n"
            f"📈 Vol: {vol_str} MA20{vp_line}\n"
        )
        if recommendation:
            msg += f"\n💬 {recommendation[:200]}"
        msg += f"\n\n⏰ {datetime.now().strftime('%d %b %Y %H:%M')} WIB"
        return self._send_telegram(msg)

    def send_daily_report(
        self, results: list, ai_report: str = "", regime: dict | None = None
    ) -> bool:
        regime    = regime or {}
        cycle     = regime.get("cycle", "")
        ihsg      = regime.get("ihsg", 0)
        mom_4w    = regime.get("mom_4w", 0)
        strong_bo = [r for r in results if _g(r, "signal") == "STRONG_BREAKOUT"]
        breakouts = [r for r in results if _g(r, "signal") == "BREAKOUT"]
        watchlists= [r for r in results if _g(r, "signal") == "WATCHLIST"]

        regime_line = ""
        if cycle:
            mom_str = f"{mom_4w:+.1f}%" if isinstance(mom_4w, (int, float)) else "—"
            regime_line = f"\n📈 {cycle} | IHSG {ihsg:,.0f} | 4W {mom_str}"

        msg = (
            f"📋 <b>Daily Scan — {datetime.now().strftime('%d %b %Y')}</b>{regime_line}\n\n"
            f"🔥 Strong Breakout: {len(strong_bo)}\n"
            f"🟢 Breakouts: {len(breakouts)}\n"
            f"🟡 Watchlist: {len(watchlists)}\n"
            f"📊 Total setups: {len(results)}\n"
        )

        top_picks = (strong_bo + breakouts)[:3]
        if top_picks:
            msg += "\n<b>Top Picks:</b>\n"
            for r in top_picks:
                ticker = str(_g(r, "ticker", "?")).replace(".JK", "")
                score  = _g(r, "score", 0)
                close  = _g(r, "close", 0)
                sig    = _g(r, "signal", "")
                fire   = "🔥" if sig == "STRONG_BREAKOUT" else "🟢"
                msg += f"• {fire} {ticker} Score {score}/8 Rp{close:,.0f}\n"
        elif cycle == "BEAR_TREND":
            msg += "\n⚠️ Bear market — no breakouts today. Stay safe.\n"

        if ai_report:
            msg += f"\n💬 <b>AI Summary:</b>\n{ai_report[:300]}"
        msg += f"\n\n⏰ {datetime.now().strftime('%H:%M')} WIB"
        return self._send_telegram(msg)

    def send_whale_alert(self, whale_results: list) -> bool:
        if not whale_results:
            return False
        block  = [w for w in whale_results if "BLOCK" in w.get("signal", "")]
        buyers = [w for w in whale_results if w.get("chg_pct", 0) > 0.5]
        msg = (
            f"🐋 <b>Whale Alert — {datetime.now().strftime('%d %b %Y %H:%M')}</b>\n\n"
            f"📊 Total alerts: {len(whale_results)}\n"
            f"🔴 Block trades: {len(block)}\n"
            f"▲ Buy pressure: {len(buyers)}\n\n"
            f"<b>Top Activity:</b>\n"
        )
        for w in whale_results[:5]:
            ticker = w.get("ticker", "?").replace(".JK", "")
            try:
                vol_str = f"{float(w.get('vol_ratio', 0)):.1f}×"
                val_str = f"Rp{float(w.get('value_bn', 0)):.1f}Bn"
                chg_str = f"{float(w.get('chg_pct', 0)):+.1f}%"
            except (TypeError, ValueError):
                vol_str = str(w.get("vol_ratio", "?"))
                val_str = str(w.get("value_bn", "?"))
                chg_str = str(w.get("chg_pct", "?"))
            msg += f"• {ticker} {w.get('signal','')} | {vol_str} | {val_str} | {chg_str}\n"
        return self._send_telegram(msg)
