"""
Simple Trading V2 — News Edge Agent v2
========================================
Three-pillar scoring model:
  Pillar 1: Source credibility (0–40 pts)
  Pillar 2: Content quality   (0–40 pts)
  Pillar 3: Manipulation risk (0–30 penalty)

Final score = P1 + P2 - P3  (range 0–80)
Verdict: VERIFIED ≥65 | STRONG ≥50 | SIGNAL ≥35 | WATCH ≥20 | NOISE <20
         MANIPULATION_WARNING when P3 ≥ 15 (overrides any verdict)

Every edge card shows the exact reasons for its score — full transparency.
"""

import logging
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# PILLAR 1: Source credibility tiers
# ─────────────────────────────────────────────────────────────────────────────
SOURCE_TIERS = {
    # Tier 1 — Official / regulatory (40 pts)
    "idx.co.id": 40, "ojk.go.id": 40, "bapepam": 40,
    "idx": 40, "bursa efek indonesia": 40,

    # Tier 2 — Major verified financial media (30 pts)
    "kontan": 30, "kontan.co.id": 30,
    "bisnis.com": 30, "bisnis indonesia": 30,
    "cnbcindonesia": 30, "cnbcindonesia.com": 30,
    "bloomberg": 30, "reuters": 30,
    "investor.id": 30, "investordaily": 30,
    "thejakartapost": 30, "jakarta post": 30,
    "beritasatu": 28,

    # Tier 3 — General media with financial desk (20 pts)
    "detik": 20, "detikfinance": 20,
    "kompas": 20, "kompas.com": 20,
    "tribun": 18, "tribunnews": 18,
    "okezone": 18, "liputan6": 18,
    "tempo": 22, "tempo.co": 22,
    "medcom": 18,

    # Tier 4 — Unknown / low-credibility (10 pts)
    # Anything not matched → defaults to 10
}

def _source_score(publisher: str) -> tuple[int, str]:
    """Returns (score, reason) for a publisher name."""
    if not publisher:
        return 10, "sumber tidak diketahui"
    pub_lower = publisher.lower()
    for key, score in SOURCE_TIERS.items():
        if key in pub_lower:
            tier = "Tier 1 resmi" if score >= 40 else "Tier 2 media besar" if score >= 28 else "Tier 3 media umum"
            return score, f"{tier}: {publisher}"
    return 10, f"Tier 4 tidak dikenal: {publisher}"


# ─────────────────────────────────────────────────────────────────────────────
# PILLAR 2: Content quality signals
# ─────────────────────────────────────────────────────────────────────────────
# Format: (keyword_list, point_delta, reason_text, signal_type)
# signal_type: "verify" adds, "hedge" subtracts

CONTENT_SIGNALS: list[tuple[list[str], int, str]] = [
    # --- Verification signals (positive) ---
    (["keterbukaan informasi", "no. ket", "nomor ket", "idxket", "idx no."],
     +15, "ada nomor keterbukaan IDX resmi"),
    (["laporan keuangan", "laporan tahunan", "annual report", "financial report"],
     +12, "mengacu laporan keuangan resmi"),
    (["direktur utama", "cfo", "ceo", "presiden direktur", "komisaris utama",
      "manajemen menyatakan", "menurut direktur"],
     +10, "ada atribusi nama pejabat"),
    (["rp ", "rp.", "triliun", "miliar", "billion", "trillion", "%"],
     +10, "ada angka spesifik"),
    (["cum date", "ex date", "record date", "effective date", "tanggal efektif",
      "tanggal pencatatan"],
     +10, "ada tanggal aksi korporasi spesifik"),
    (["resmi mengumumkan", "memastikan", "mengkonfirmasi", "officially announced",
      "confirmed", "press release", "siaran pers"],
     +8, "kalimat konfirmasi resmi"),
    (["announces", "announced", "says in a statement", "said on"],
     +8, "konfirmasi dalam bahasa Inggris"),
    (["added effective", "added to", "removed from index", "rebalancing effective",
      "inclusion effective"],
     +10, "konfirmasi perubahan indeks resmi"),

    # --- Hedge / uncertainty signals (negative) ---
    (["kabarnya", "dikabarkan", "konon", "menurut kabar", "beredar kabar"],
     -15, "bahasa gosip: 'kabarnya/dikabarkan'"),
    (["diduga", "disebut-sebut", "diisukan", "isu beredar"],
     -12, "bahasa isu tidak terverifikasi"),
    (["sumber internal", "sumber terpercaya", "narasumber anonim",
      "pihak yang mengetahui", "insider"],
     -10, "sumber anonim tidak bisa diverifikasi"),
    (["berencana", "sedang mempertimbangkan", "kemungkinan akan", "plans to",
      "is considering", "may consider", "reportedly planning"],
     -10, "masih rencana, belum terkonfirmasi"),
    (["rumor", "reportedly", "alleged", "allegedly", "said to be"],
     -12, "bahasa rumor/unverified"),
]

def _content_score(title: str) -> tuple[int, list[str]]:
    """Returns (score, reasons[]) for headline content quality."""
    tl = title.lower()
    score = 0
    reasons = []
    for keywords, delta, reason in CONTENT_SIGNALS:
        if any(kw in tl for kw in keywords):
            score += delta
            tag = "+" if delta > 0 else ""
            reasons.append(f"{tag}{delta}: {reason}")
    return max(-40, min(40, score)), reasons


# ─────────────────────────────────────────────────────────────────────────────
# PILLAR 3: Manipulation / goreng saham risk signals
# ─────────────────────────────────────────────────────────────────────────────
PUMP_SIGNALS: list[tuple[list[str], int, str]] = [
    # --- Classic pump language ---
    (["target harga", "target price", "potensi naik", "berpotensi naik",
      "akan naik", "siap naik", "saham ini akan", "mau naik"],
     +15, "pump language: 'target harga/potensi naik'"),
    (["rekomendasi beli", "buy recommendation", "strong buy", "hot pick",
      "next big", "multi-bagger", "saham pilihan"],
     +12, "rekomendasi beli tanpa konteks"),
    (["siap breakout", "breakout sebentar lagi", "momentum beli",
      "entry sekarang", "saham gorengan"],
     +12, "hype language / goreng signal"),
    # --- Extraordinary claims from unverified sources ---
    (["+100%", "+200%", "+300%", "+400%", "+500%", "berlipat ganda",
      "naik berlipat", "gain besar"],
     +10, "klaim return extraordiner"),
    # --- Anonymous / suspicious sourcing ---
    (["sumber dekat perusahaan", "orang dalam", "bocoran", "rahasia",
      "exclusive info", "inside info"],
     +8, "klaim info internal bocoran"),
    # --- Paid content patterns ---
    (["advertorial", "konten berbayar", "sponsored", "iklan"],
     +10, "konten berbayar / advertorial"),
]

def _manipulation_risk(title: str, source_score: int, n_sources: int) -> tuple[int, list[str]]:
    """Returns (risk_score, reasons[]) for manipulation detection."""
    tl = title.lower()
    risk = 0
    reasons = []

    # Linguistic pump signals
    for keywords, penalty, reason in PUMP_SIGNALS:
        if any(kw in tl for kw in keywords):
            risk += penalty
            reasons.append(f"+{penalty}: {reason}")

    # Structural risk factors
    if source_score <= 10 and n_sources == 1:
        risk += 10
        reasons.append("+10: satu sumber tidak dikenal saja, tidak ada corroborasi")
    elif n_sources == 1:
        risk += 5
        reasons.append("+5: hanya satu sumber, belum dikonfirmasi outlet lain")

    if source_score <= 10:
        risk += 5
        reasons.append("+5: sumber Tier 4 (portal tidak dikenal)")

    return min(30, risk), reasons


# ─────────────────────────────────────────────────────────────────────────────
# Verdict mapping
# ─────────────────────────────────────────────────────────────────────────────
def _verdict(total: int, manip: int) -> tuple[str, str, str]:
    """Returns (verdict_id, verdict_label, verdict_color)."""
    if manip >= 15:
        return "MANIPULATION_WARNING", "⚠ MANIPULASI?", "#ef4444"
    if total >= 65:
        return "VERIFIED_SIGNAL", "✓ VERIFIED", "#00ff66"
    if total >= 50:
        return "STRONG_SIGNAL", "↑ STRONG", "#39ff14"
    if total >= 35:
        return "SIGNAL", "◉ SIGNAL", "#60a5fa"
    if total >= 20:
        return "WATCH", "◎ WATCH", "#f0b429"
    return "NOISE", "× NOISE", "#6b7280"


# ─────────────────────────────────────────────────────────────────────────────
# Edge Catalog (14 categories)
# ─────────────────────────────────────────────────────────────────────────────
EDGE_CATALOG = {
    "MSCI_ADD": {
        "keywords_id": ["msci", "indeks msci", "rebalancing msci", "masuk msci"],
        "keywords_en": ["msci", "msci inclusion", "msci rebalancing", "index addition"],
        "strength": "CRITICAL", "direction": "LONG",
        "desc": "Passive fund forced buying — MSCI rebalancing", "emoji": "★",
    },
    "LQ45_IDX30_ADD": {
        "keywords_id": ["lq45", "idx30", "masuk indeks", "konstituen indeks"],
        "keywords_en": ["lq45", "idx30", "index inclusion", "index rebalancing"],
        "strength": "HIGH", "direction": "LONG",
        "desc": "LQ45/IDX30 rebalancing forced flow", "emoji": "◆",
    },
    "BUYBACK": {
        "keywords_id": ["buyback", "buy back", "pembelian kembali saham"],
        "keywords_en": ["buyback", "share repurchase", "buy back"],
        "strength": "HIGH", "direction": "LONG",
        "desc": "Management buyback — strong confidence signal", "emoji": "↺",
    },
    "DIVIDEND": {
        "keywords_id": ["dividen", "cum dividen", "cum date", "pembagian dividen"],
        "keywords_en": ["dividend", "cum date", "ex dividend"],
        "strength": "MEDIUM", "direction": "LONG",
        "desc": "Dividend play — buy before cum date", "emoji": "₿",
    },
    "ACQUISITION_TARGET": {
        "keywords_id": ["diakuisisi", "akuisisi", "merger", "go private",
                        "tender offer", "privatisasi", "pengambilalihan"],
        "keywords_en": ["acquisition", "merger", "take over", "take private", "tender offer"],
        "strength": "CRITICAL", "direction": "LONG",
        "desc": "M&A / acquisition target — re-rating event", "emoji": "⬆",
    },
    "MAJOR_CONTRACT": {
        "keywords_id": ["kontrak baru", "menang tender", "proyek baru",
                        "memenangkan proyek", "perjanjian kerja sama"],
        "keywords_en": ["major contract", "new contract", "project win"],
        "strength": "MEDIUM", "direction": "LONG",
        "desc": "Major contract / project win — revenue catalyst", "emoji": "📋",
    },
    "EARNINGS_BEAT": {
        "keywords_id": ["laba naik", "profit naik", "laba bersih naik",
                        "laba bersih tumbuh", "pendapatan tumbuh", "rekor laba",
                        "laba melonjak", "kinerja meningkat"],
        "keywords_en": ["earnings beat", "profit surge", "net income grew",
                        "profit rose", "revenue growth"],
        "strength": "MEDIUM", "direction": "LONG",
        "desc": "Earnings beat / profit growth — fundamental rerating", "emoji": "📈",
    },
    "INSIDER_BUY": {
        "keywords_id": ["direksi beli saham", "komisaris beli", "direktur beli",
                        "pemegang saham tambah", "menambah kepemilikan"],
        "keywords_en": ["director buys", "insider buy", "major shareholder adds"],
        "strength": "HIGH", "direction": "LONG",
        "desc": "Insider / major holder buying — smart money signal", "emoji": "👤",
    },
    "GOVERNMENT_PROJECT": {
        "keywords_id": ["proyek strategis nasional", "psn", "proyek pemerintah",
                        "kontrak pemerintah", "pertamina", "pln", "hutama karya"],
        "keywords_en": ["government project", "state contract", "infrastructure project"],
        "strength": "MEDIUM", "direction": "LONG",
        "desc": "Government / SOE project — APBN spending catalyst", "emoji": "🏛",
    },
    "COMMODITY_POSITIVE": {
        "keywords_id": ["harga batu bara naik", "harga nikel naik", "harga cpo naik",
                        "harga minyak naik", "komoditas menguat", "batu bara menguat",
                        "nikel menguat", "coal rally", "nickel rally"],
        "keywords_en": ["coal price rises", "nickel price up", "cpo price surge",
                        "commodity rally", "coal rally"],
        "strength": "MEDIUM", "direction": "LONG",
        "desc": "Commodity price tailwind — sector beneficiary", "emoji": "⛏",
    },
    "RIGHTS_ISSUE": {
        "keywords_id": ["hmetd", "rights issue", "pmhmetd", "penambahan modal",
                        "private placement"],
        "keywords_en": ["rights issue", "share issuance", "private placement"],
        "strength": "MEDIUM", "direction": "CAUTION",
        "desc": "Rights issue / dilution — caution, check discount", "emoji": "⚠",
    },
    "INSIDER_SELL": {
        "keywords_id": ["direksi jual saham", "komisaris jual", "melepas kepemilikan"],
        "keywords_en": ["director sells", "insider sell", "major shareholder reduces"],
        "strength": "MEDIUM", "direction": "CAUTION",
        "desc": "Insider / major holder selling — watch for drift", "emoji": "⬇",
    },
    "EARNINGS_MISS": {
        "keywords_id": ["laba turun", "rugi bersih", "penurunan laba",
                        "kinerja melemah", "margin tertekan"],
        "keywords_en": ["earnings miss", "net loss", "profit decline"],
        "strength": "MEDIUM", "direction": "AVOID",
        "desc": "Earnings miss / profit decline — avoid or wait", "emoji": "📉",
    },
    "SUSPEND_RESUME": {
        "keywords_id": ["suspend", "penghentian perdagangan", "dibuka kembali",
                        "resume perdagangan"],
        "keywords_en": ["trading suspended", "trading halted", "resume trading"],
        "strength": "HIGH", "direction": "VOLATILE",
        "desc": "Post-suspend volatility — high risk / high reward", "emoji": "⏸",
    },
}

# Build flat keyword → edge map
_KW_MAP: dict[str, str] = {}
for _eid, _cfg in EDGE_CATALOG.items():
    for _kw in _cfg["keywords_id"] + _cfg["keywords_en"]:
        _KW_MAP[_kw.lower()] = _eid


# ─────────────────────────────────────────────────────────────────────────────
# Google News RSS sources
# ─────────────────────────────────────────────────────────────────────────────
GOOGLE_NEWS_QUERIES = [
    ("saham IDX MSCI rebalancing indeks",           "id"),
    ("dividen buyback akuisisi saham Indonesia",    "id"),
    ("kontrak proyek batu bara nikel saham IDX",    "id"),
    ("keterbukaan informasi IDX emiten",            "id"),
    ("laba kinerja keuangan emiten IDX",            "id"),
    ("MSCI Indonesia index rebalancing 2026",       "en"),
    ("IDX Indonesia stock corporate action",        "en"),
]
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl={lang}&gl=ID&ceid=ID:{lang}"


# ─────────────────────────────────────────────────────────────────────────────
# Main Agent
# ─────────────────────────────────────────────────────────────────────────────
class NewsEdgeAgent:
    def __init__(self, max_age_hours: int = 72):
        self.max_age_hours = max_age_hours
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; TradingBot/1.0)",
            "Accept": "application/rss+xml,application/xml,text/xml,*/*",
        })

    def _fetch_google_rss(self, query: str, lang: str = "id") -> list[dict]:
        url = GOOGLE_NEWS_RSS.format(q=requests.utils.quote(query), lang=lang)
        try:
            resp = self.session.get(url, timeout=12)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            items = []
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                link  = item.findtext("link") or ""
                pub   = item.findtext("pubDate") or ""
                src_el = item.find("source")
                src   = src_el.text if src_el is not None else ""
                if title:
                    items.append({"title": title, "link": link,
                                  "publisher": src, "pubDate": pub, "source": "google_rss"})
            return items
        except Exception as e:
            logger.debug(f"[News] Google RSS failed '{query[:30]}': {e}")
            return []

    def _fetch_yfinance_news(self, ticker: str) -> list[dict]:
        try:
            import yfinance as yf
            t = ticker if ticker.endswith(".JK") else ticker + ".JK"
            news = yf.Ticker(t).news or []
            return [{
                "title":     n.get("title", ""),
                "link":      n.get("link", ""),
                "publisher": n.get("publisher", ""),
                "pubDate":   datetime.fromtimestamp(
                    n.get("providerPublishTime", 0), tz=timezone.utc
                ).strftime("%a, %d %b %Y %H:%M:%S +0000"),
                "source": "yfinance", "tickers": [t],
            } for n in news]
        except Exception as e:
            logger.debug(f"[News] yfinance news failed {ticker}: {e}")
            return []

    def _parse_age_hours(self, pub_date_str: str) -> float:
        if not pub_date_str:
            return 999
        try:
            dt  = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %z")
            now = datetime.now(tz=timezone.utc)
            return (now - dt).total_seconds() / 3600
        except Exception:
            return 999

    def _classify_edge(self, title: str) -> list[str]:
        tl = title.lower()
        return list({_KW_MAP[kw] for kw in _KW_MAP if kw in tl})

    def _extract_tickers(self, title: str, known: list[str]) -> list[str]:
        candidates = set(re.findall(r'\b([A-Z]{3,5})\b', title))
        known_set  = {t.replace(".JK","").upper() for t in known}
        return [t for t in candidates if t in known_set]

    def _score_news_item(self, item: dict, n_sources: int) -> dict:
        """Full three-pillar scoring. Returns enriched item dict."""
        title     = item.get("title", "")
        publisher = item.get("publisher", "")

        # Pillar 1
        p1, p1_reason = _source_score(publisher)

        # Pillar 2
        p2, p2_reasons = _content_score(title)

        # Pillar 3
        p3, p3_reasons = _manipulation_risk(title, p1, n_sources)

        total = max(0, p1 + p2 - p3)

        verdict_id, verdict_label, verdict_color = _verdict(total, p3)

        score_detail = {
            "source_score":  p1,
            "content_score": p2,
            "manip_risk":    p3,
            "total_score":   total,
            "verdict_id":    verdict_id,
            "verdict_label": verdict_label,
            "verdict_color": verdict_color,
            "score_reasons": {
                "source":  p1_reason,
                "content": p2_reasons,
                "manip":   p3_reasons,
            },
        }
        return {**item, **score_detail}

    def scan(self, known_tickers: list[str] | None = None,
             msci_candidates: list[str] | None = None) -> list[dict]:
        from core.data_feed import get_catalyst_universe, get_msci_candidates as _gmc
        known_tickers   = known_tickers   or get_catalyst_universe()
        msci_candidates = msci_candidates or _gmc()

        t0 = time.time()
        raw_news: list[dict] = []

        # 1) Google News RSS
        print("[News] Fetching Google News RSS...")
        with ThreadPoolExecutor(max_workers=4) as exe:
            futs = {exe.submit(self._fetch_google_rss, q, lang): (q, lang)
                    for q, lang in GOOGLE_NEWS_QUERIES}
            for f in as_completed(futs):
                raw_news.extend(f.result())
        print(f"[News] Google RSS: {len(raw_news)} items")

        # 2) Per-ticker yfinance for MSCI candidates
        print(f"[News] yfinance news for {min(50, len(msci_candidates))} catalyst tickers...")
        yf_count = 0
        with ThreadPoolExecutor(max_workers=10) as exe:
            futs = {exe.submit(self._fetch_yfinance_news, t): t
                    for t in msci_candidates[:50]}
            for f in as_completed(futs):
                items = f.result()
                raw_news.extend(items)
                yf_count += len(items)
        print(f"[News] yfinance: {yf_count} items")

        # 3) Count corroboration per story (simple: count how many items share ≥2 words)
        seen_titles: set[str] = set()
        deduped: list[dict] = []
        for item in raw_news:
            title = item.get("title","").strip()
            if not title or title in seen_titles:
                continue
            age_h = self._parse_age_hours(item.get("pubDate",""))
            if age_h > self.max_age_hours:
                continue
            seen_titles.add(title)
            deduped.append({**item, "age_hours": round(age_h, 1)})

        # Count corroboration: how many other headlines share ≥3 keywords
        def _word_set(t: str) -> set:
            stop = {"yang","dan","di","ke","dari","ini","itu","untuk","dengan","akan","adalah"}
            return {w for w in re.findall(r'[a-z]{4,}', t.lower()) if w not in stop}

        word_sets = [_word_set(item["title"]) for item in deduped]
        corroborations = []
        for i, ws in enumerate(word_sets):
            count = sum(1 for j, other in enumerate(word_sets) if i != j and len(ws & other) >= 3)
            corroborations.append(count)

        # 4) Score + classify all items
        edges: list[dict] = []
        for i, item in enumerate(deduped):
            edge_ids = self._classify_edge(item["title"])
            if not edge_ids:
                continue

            n_sources = corroborations[i] + 1
            scored    = self._score_news_item(item, n_sources)
            scored["corroboration"] = n_sources

            # Skip NOISE unless it's a manipulation warning (always show those)
            if scored["verdict_id"] == "NOISE" and scored["manip_risk"] < 15:
                continue

            mentioned = self._extract_tickers(item["title"], known_tickers)
            mentioned += [t.replace(".JK","") for t in item.get("tickers", [])]
            mentioned  = list(dict.fromkeys(t.upper() for t in mentioned))

            for edge_id in edge_ids:
                cfg = EDGE_CATALOG[edge_id]
                edges.append({
                    **scored,
                    "edge_id":   edge_id,
                    "strength":  cfg["strength"],
                    "direction": cfg["direction"],
                    "desc":      cfg["desc"],
                    "emoji":     cfg["emoji"],
                    "tickers":   mentioned,
                })

        # Sort: manipulation warnings first, then by total_score desc
        def _sort_key(e):
            manip_flag = 0 if e["verdict_id"] == "MANIPULATION_WARNING" else 1
            return (manip_flag, -e["total_score"], e["age_hours"])

        edges.sort(key=_sort_key)

        elapsed = round(time.time() - t0, 1)
        print(f"[News] Done: {len(edges)} scored edges from {len(deduped)} unique headlines in {elapsed}s")
        return edges

    def summary(self, edges: list[dict]) -> str:
        if not edges:
            return "Tidak ada edge berita hari ini."
        lines = [f"\n=== NEWS EDGE SCAN v2 — {datetime.now().strftime('%d %b %Y %H:%M')} ===\n"]
        by_verdict = {}
        for e in edges:
            by_verdict.setdefault(e["verdict_id"], []).append(e)
        for vid in ["MANIPULATION_WARNING","VERIFIED_SIGNAL","STRONG_SIGNAL","SIGNAL","WATCH"]:
            items = by_verdict.get(vid, [])
            if not items: continue
            lines.append(f"\n{e['verdict_label'] if items else ''} {vid} ({len(items)})")
            lines.append("-" * 55)
            for e in items[:5]:
                tickers_str = " ".join(e["tickers"][:4]) if e["tickers"] else "(market-wide)"
                lines.append(
                    f"  Score {e['total_score']}/80 | {tickers_str}\n"
                    f"  \"{e['title'][:85]}\"\n"
                    f"  Src:{e['source_score']} Cont:{e['content_score']} Manip:-{e['manip_risk']}"
                )
        lines.append(f"\nTotal: {len(edges)} edges.")
        return "\n".join(lines)


def run_news_scan(save_results: bool = True) -> list[dict]:
    import json
    from pathlib import Path
    from core.data_feed import get_catalyst_universe, get_msci_candidates
    agent = NewsEdgeAgent(max_age_hours=72)
    edges = agent.scan(known_tickers=get_catalyst_universe(),
                       msci_candidates=get_msci_candidates())
    print(agent.summary(edges))
    if save_results:
        out_file = Path(__file__).parent.parent / "logs" / "news_edges.json"
        out_file.write_text(
            json.dumps({"date": datetime.now().isoformat(),
                        "total": len(edges), "edges": edges},
                       indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        print(f"[News] Saved → {out_file}")
    return edges

if __name__ == "__main__":
    run_news_scan()
