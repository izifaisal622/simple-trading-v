"""
Simple Trading V9 — Orchestrator
Runs all agents in the correct order.
Zero API cost. All analysis is local.

Usage:
  python orchestrator.py                   # full daily run
  python orchestrator.py --mode ema        # EMA scan only
  python orchestrator.py --mode whale      # Whale scan only
  python orchestrator.py --mode director   # Director review only
  python orchestrator.py --mode weekly     # Full weekly deep review
  streamlit run gate.py                    # Dashboard
"""

import sys
import os
import json
import logging
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("orchestrator")

LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)


def run_ema_scan(cfg, regime):
    """v10.0.7 — REPLACE TOTAL: sistem lama (scanner_agent+DailyEMAEngine,
    skor tangga breakout) diganti sistem baru (zone_scanner+conviction_engine,
    retest-zone conviction 20-100%). Mandiri — TIDAK pakai analyst_agent/
    alert_agent (keduanya tetap dipakai whale scan, jangan disentuh)."""
    print("\n" + "═"*60)
    print("  MODULE 01 — VIDYA+SMC RETEST-ZONE SCANNER")
    print("═"*60)

    from agents.zone_scanner import ZoneScanner

    scanner = ZoneScanner()
    results, ctx = scanner.scan()  # log_zone_results dipanggil internal di .scan()

    print(f"\n  Regime: {ctx['regime']} | Universe: {ctx['total_universe']} "
          f"| Dianalisis: {ctx['analyzed']} | Watching: {ctx['watching_count']}")
    if ctx["skipped_short_history"] or ctx["crashed"]:
        print(f"  ⚠ Skip data pendek: {ctx['skipped_short_history']} | Crash: {ctx['crashed']}")

    if results:
        print(f"\n{'TICKER':<8} {'CONV%':>6} {'STATUS':<10} {'ZONA':<20} {'RETEST':>7} {'BREAKDOWN'}")
        print("-" * 80)
        for r in results[:30]:
            zona = f"{r['zone_bottom']:.0f}-{r['zone_top']:.0f}" if r['zone_top'] else "-"
            breakdown = (f"base{r['base_pct']}+retest{r['retest_pct']}"
                        f"+vidya{r['vidya_pct']}+vol{r['volume_pct']}+struct{r['structure_pct']}")
            print(f"{r['ticker']:<8} {r['conviction_pct']:>5}% {r['status']:<10} "
                  f"{zona:<20} {r['retest_hold_days']:>6}d  {breakdown}")
    else:
        print("\n  Tidak ada zona WATCHING hari ini.")

    print(f"\n[Zone] Done: {len(results)} watching setups")
    return results



def run_whale_scan(cfg, regime):
    print("\n" + "═"*60)
    print("  MODULE 02 — FOLLOW THE WHALE")
    print("═"*60)

    from agents.whale_scanner import WhaleScanner
    from agents.analyst_agent import MarketAnalystAgent
    from agents.alert_agent   import AlertAgent

    # Pass None so adapt_to_market() can set optimal vol for current regime
    # User can override via dashboard OVERRIDE VOL field
    scanner = WhaleScanner(vol_multiplier=None, min_value_bn=None)
    analyst = MarketAnalystAgent(cfg)
    alerter = AlertAgent(cfg)

    # v9.8.1: orchestrator ikut full universe (konsisten dgn default page 2) —
    # jalur CLI ini tidak lewat dropdown UI, jadi harus eksplisit
    results, ctx = scanner.scan(top_n=cfg.whale_top_n, full_universe=True)

    # Save to results file
    results_file = LOGS_DIR / "daily_results.json"
    existing = {}
    if results_file.exists():
        try: existing = json.loads(results_file.read_text(encoding="utf-8"))
        except: pass

    existing.update({
        "date":          datetime.now().isoformat(),
        "whale_date":    datetime.now().strftime("%Y-%m-%d"),  # v9.8.8: kunci tanggal per-sistem
        "whale_results": results,
        "whale_total":   len(results),
        "whale_context": ctx,
    })
    if "regime" not in existing:
        existing["regime"] = regime
    results_file.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")

    # ── Daily broker history save (Phase 3 — runs if token available) ──────
    try:
        from agents.broker_history import save_broker_data
        from agents.ownership_agent import OwnershipAgent as _OA
        _oa    = _OA()
        _token = _oa.get_stockbit_token()
        if _token and results:
            _saved = 0
            for _w in sorted(results, key=lambda x: -x.get("conviction",0))[:15]:
                _t  = _w.get("ticker","")
                _sb = _oa.get_broker_summary_stockbit(_t)
                if _sb.get("available"):
                    _bl = _sb.get("top_buyers",[]) + _sb.get("top_sellers",[])
                    save_broker_data(_t, _bl)
                    _saved += 1
            if _saved:
                print(f"[Broker] Saved broker history: {_saved} tickers")
    except Exception:
        pass

    # Rules-based whale summary
    summary = analyst.analyze_whale(results, regime)
    print(f"\n[Whale] {summary.formatted}")

    # Telegram
    if cfg.telegram_token:
        alerter.send_whale_alert(results)

    smart = [w for w in results if w.get("whale_quality") in ("SMART","LIKELY_SMART")]
    print(f"\n[Whale] Done: {len(results)} alerts | {len(smart)} smart whale setups")
    return results


def run_learning(cfg):
    # Wire paper journal data to learning agent if available
    try:
        from agents.journal_agent import compute_performance
        perf = compute_performance()
        if perf.get("total", 0) >= 5:
            print(f"[Learning] Paper journal: {perf['total']} trades | "
                  f"WR {perf['win_rate']}% | EV {perf['expectancy']:+.2f}R")
    except Exception:
        pass

def run_learning_inner(cfg):
    print("\n" + "═"*60)
    print("  LEARNING AGENT — Trade History Analysis")
    print("═"*60)
    from agents.learning_agent import run_learning_cycle
    summary = run_learning_cycle(auto_apply=True)
    print(f"[Learning] {summary}")


def run_director(cfg, full=False):
    print("\n" + "═"*60)
    print(f"  DIRECTOR — {'Weekly Deep Review' if full else 'Daily Check'}")
    print("═"*60)
    from agents.director_agent import run_director as _run
    result = _run(cfg, full=full)
    print(f"\n[Director] {result}")


def run_msci(cfg, regime):
    print("\n" + "═"*60)
    print("  MODULE 03 — MSCI / INDEX REBALANCING SCANNER")
    print("═"*60)
    try:
        from agents.msci_agent import run_msci_scan, get_active_events
        from datetime import date
        active = get_active_events()
        if active:
            for ev in active:
                print(f"  ◈ {ev['index']} | Phase: {ev['phase']} | "
                      f"T-{ev['t_minus']} hari | Effective: {ev['effective_date']}")
        result = run_msci_scan(cfg)
        print(f"\n[MSCI] {result}")
    except Exception as e:
        print(f"[MSCI] Error: {e}")
        import traceback; traceback.print_exc()



def _launch_dashboard():
    """Open Streamlit dashboard in browser — exactly ONE tab."""
    import subprocess, webbrowser, time, threading, sys, os

    gate = Path(__file__).parent / "gate.py"
    url  = "http://localhost:8501"
    print(f"\n[Dashboard] Launching Streamlit → {url}")
    print("[Dashboard] Press Ctrl+C to stop\n")

    # Start Streamlit in background (non-blocking)
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(gate),
         "--server.headless", "true",
         "--server.port", "8501",
         "--browser.gatherUsageStats", "false",
         "--server.runOnSave", "false"],
        cwd=str(gate.parent),
    )

    # Wait for Streamlit to be ready, then open browser
    import urllib.request
    for attempt in range(20):
        time.sleep(1)
        try:
            urllib.request.urlopen(url, timeout=1)
            break  # server is up
        except Exception:
            pass

    # Open browser — try multiple methods for Windows compatibility
    opened = False
    try:
        if sys.platform == "win32":
            os.startfile(url)
            opened = True
        else:
            webbrowser.open_new_tab(url)
            opened = True
    except Exception as e:
        print(f"[Dashboard] Could not auto-open browser: {e}")
        print(f"[Dashboard] Open manually: {url}")

    if opened:
        print(f"[Dashboard] Browser opened → {url}")

    # Keep process alive
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        print("\n[Dashboard] Stopped.")




def _print_stats():
    """Print performance stats from trade_log.db."""
    try:
        from trade_logger import get_stats, get_open_trades, get_closed_trades
        stats  = get_stats()
        open_t = get_open_trades()
        closed = get_closed_trades(limit=10)

        print(f"\n{'═'*60}")
        print("  PERFORMANCE STATS")
        print(f"{'═'*60}")
        print(f"  Open trades   : {len(open_t)}")
        print(f"  Closed trades : {stats.get('total_closed', 0)} / 30")
        if stats.get("win_rate") is not None:
            print(f"  Win rate      : {stats['win_rate']:.1f}%")
            print(f"  Expectancy    : {stats['expectancy']:+.3f}R")
            print(f"  Avg R         : {stats['avg_r']:+.2f}R")
        else:
            print("  Win rate      : UNKNOWN (need 30 closed trades)")
        print()
        if closed:
            print("  Last 10 closed trades:")
            for t in closed[:10]:
                pnl = f"{t.get('pnl_r',0):+.2f}R" if t.get('pnl_r') is not None else "—"
                print(f"    {t['ticker']:<6} {t.get('outcome','?'):<10} {pnl}")
        print(f"{'═'*60}\n")
    except Exception as e:
        print(f"[Stats] Error: {e}")


def _run_single_ticker(cfg, regime, ticker: str, no_llm: bool = False):
    """Run full analysis on a single ticker — both EMA and Whale context."""
    # Zone conviction analysis (v10.1 REPLACE TOTAL — TechnicalEngine class
    # tak pernah ada di technical_engine.py, import ini sudah rusak sejak
    # sebelum migrasi, silently ditelan except di bawah. Diganti sekalian.)
    try:
        from core.data_feed import DataFeed
        from core.conviction_engine import run_conviction

        feed_d = DataFeed(timeframe="1d", period="2y")
        df_day = feed_d.fetch(ticker)

        if df_day is not None and len(df_day) >= 260:
            states = run_conviction(df_day, internal_size=5, swing_size=50)
            r = states[-1]
            print(f"  ZONE     | Status: {r.status:<12} | Conviction: {r.conviction_pct}% | "
                  f"Retest: {r.retest_hold_days}/2")
            if r.zone_top:
                print(f"           | Zona: {r.zone_bottom:,.0f}-{r.zone_top:,.0f} | "
                      f"Base:{r.base_pct} Retest:{r.retest_pct} VIDYA:{r.vidya_pct} "
                      f"Vol:{r.volume_pct} Struct:{r.structure_pct}")
        else:
            print(f"  [ZONE] Data harian tidak cukup utk {ticker} (butuh >=260 bar)")
    except Exception as e:
        print(f"  [ZONE] Error: {e}")

    # Whale analysis
    try:
        from agents.whale_scanner import WhaleScanner
        ws  = WhaleScanner(vol_multiplier=1.0, min_value_bn=0.0)   # low threshold for single
        res = ws._scan_ticker(ticker, regime.get("cycle","UNKNOWN"))
        if res:
            print(f"  Whale    | Signal: {res.get('signal','?'):<12} | "
                  f"Conv: {res.get('conviction',0)}/10 | "
                  f"Zone: {res.get('entry_zone','?')}")
            print(f"           | Floor: {res.get('floor_price',0):,.0f} | "
                  f"VP POC: {res.get('vp_poc',0):,.0f} | "
                  f"Peng: {res.get('pengeringan_detected','?')}")
            if res.get("vp_desc"):
                print(f"           | VP: {res['vp_desc']}")
            if res.get("pengeringan_desc"):
                print(f"           | {res['pengeringan_desc']}")
        else:
            print(f"  Whale    | {ticker} tidak memenuhi threshold scan")
    except Exception as e:
        print(f"  [Whale] Error: {e}")

    # LLM analysis if requested
    if not no_llm:
        try:
            from agents.single_stock_agent import analyze_single_stock
            result = analyze_single_stock(ticker, cfg, regime)
            if result:
                print(f"\n  [AI] {result[:300]}...")
        except Exception as e:
            print(f"  [LLM] Skipped: {e}")


def main():
    parser = argparse.ArgumentParser(description="Simple Trading V9 Orchestrator")
    parser.add_argument("--clear-cache", action="store_true", help="Hapus disk cache data sebelum scan")
    parser.add_argument("--mode",
                        choices=["ema","whale","flow","director","learning","weekly","all","stats","study"],
                        default="all", help="Which module to run")
    parser.add_argument("--ticker",    help="Single ticker deep-dive analysis (e.g. BBCA)")
    parser.add_argument("--no-llm",    action="store_true",
                        help="Skip LLM calls (faster scan, no API cost)")
    parser.add_argument("--dashboard", action="store_true",
                        help="Launch Streamlit dashboard after scan")
    parser.add_argument("--ui",        action="store_true",
                        help="Launch dashboard only, skip scan")
    args = parser.parse_args()

    # Dashboard-only mode
    if args.ui:
        _launch_dashboard()
        return

    from config.strategy_config import StrategyConfig
    from core.data_feed         import get_ihsg_regime

    if args.clear_cache:
        import shutil
        cache_dir = Path(__file__).parent / "logs" / "data_cache"
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            print("[Cache] Data cache cleared ✓")

    print(f"\n{'═'*60}")
    print(f"  SIMPLE TRADING V9 — {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"{'═'*60}\n")

    cfg = StrategyConfig.load()
    print(f"[Config] Loaded | EMA {cfg.ema_fast}/{cfg.ema_slow} | "
          f"Vol {cfg.vol_mult}× | Min score {cfg.min_score}")

    print("[Regime] Fetching IHSG regime...")
    regime = get_ihsg_regime()
    print(f"[Regime] {regime.get('cycle')} | IHSG {regime.get('ihsg'):,.0f} | "
          f"4W {regime.get('mom_4w',0):+.1f}% | Breadth {regime.get('breadth',0)}/6")

    mode    = args.mode
    no_llm  = getattr(args, "no_llm", False)

    # ── Single ticker deep-dive ──────────────────────────────────────────────
    if args.ticker:
        ticker = args.ticker.upper().replace(".JK","")
        print(f"\n{'═'*60}")
        print(f"  SINGLE TICKER: {ticker}")
        print(f"{'═'*60}\n")
        _run_single_ticker(cfg, regime, ticker, no_llm=no_llm)
        return

    # ── Stats mode ────────────────────────────────────────────────────────────
    if mode == "stats":
        _print_stats()
        return

    # ── Web self-study mode ───────────────────────────────────────────────────
    if mode == "study":
        run_director(cfg, full=True)
        return


    # ── Flow scan mode ────────────────────────────────────────────────────────
    if mode == "flow":
        try:
            from agents.flow_scanner import FlowScanner
            from core.data_feed import get_dynamic_universe
            from pathlib import Path as _Path
            import json as _json
            from datetime import datetime as _dt

            print("\n[Flow] Starting War Room scan...")
            scanner  = FlowScanner()
            # v9.8.8: doktrin satu universe — flow ikut stage-0 477 (fungsi yang
            # sama dgn whale/EMA; sudah ber-suffix .JK, jangan tambah lagi)
            from core.data_feed import get_catalyst_universe as _gcu
            universe = _gcu(full_universe=True)
            results  = scanner.scan(tickers=universe, max_workers=8)

            logs_dir = _Path(__file__).parent / "logs"
            logs_dir.mkdir(exist_ok=True)
            results_file = logs_dir / "daily_results.json"
            existing = {}
            if results_file.exists():
                try:
                    existing = _json.loads(results_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            existing["flow_results"] = results
            existing["flow_total"]   = len(results)
            existing["flow_date"]    = _dt.now().strftime("%Y-%m-%d")
            results_file.write_text(_json.dumps(existing, indent=2, default=str), encoding="utf-8")

            whale_signals = [r for r in results if r.get("signal") == "WHALE_ACCUMULATION"]
            inst_signals  = [r for r in results if r.get("signal") in ("INSTITUTIONAL_BUY", "ABSORPTION_HINT")]
            print(f"[Flow] Done: {len(results)} tickers | {len(whale_signals)} WHALE | {len(inst_signals)} INSTITUTIONAL")
        except Exception as exc:
            print(f"[Flow] ERROR: {exc}")
            import traceback; traceback.print_exc()
        return

    if mode in ("all", "ema"):
        run_ema_scan(cfg, regime)

    if mode in ("all", "whale"):
        run_whale_scan(cfg, regime)

    if mode in ("all", "whale", "ema"):
        run_msci(cfg, regime)

    if mode in ("all", "learning"):
        run_learning(cfg)

    if mode in ("all", "director"):
        try:
            run_director(cfg, full=False)
        except Exception as _de:
            # v9.9.0: Director advisory, bukan kritis — crash-nya tidak boleh
            # menggagalkan pipeline scan + dashboard (pelajaran crash STUDY_FILE)
            print(f"[Director] CRASH (pipeline lanjut): {_de}")


    if mode == "weekly":
        run_ema_scan(cfg, regime)
        run_whale_scan(cfg, regime)
        run_msci(cfg, regime)
        run_learning(cfg)
        run_director(cfg, full=True)

    print(f"\n{'═'*60}")
    print(f"  DONE — {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'═'*60}\n")

    # Auto-launch dashboard if requested
    if args.dashboard or args.ui:
        _launch_dashboard()


if __name__ == "__main__":
    main()
