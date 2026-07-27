"""
diagnose_defense_multi.py — Uji hit-rate test_whale_defense() di beberapa
ticker berkarakter beda, utk isolasi: apakah 0.2% hit-rate BUMI representatif
kriteria umum, atau khas BUMI (kemungkinan terdistorsi ARB/ARA).

Jalankan dari folder repo: python diagnose_defense_multi.py
Read-only, tidak mengubah data apa pun.
"""
import sys
sys.path.insert(0, ".")
from core.data_feed import DataFeed
from agents.whale_scanner import estimate_floor_price

TICKERS = {
    "BUMI.JK": "gocap/ARB-ARA prone (pembanding — sudah diuji sblmnya)",
    "BBCA.JK": "blue-chip stabil, likuid tinggi",
    "ANTM.JK": "mid-cap komoditas, volatilitas sedang",
    "GOTO.JK": "float besar, volatile",
}

feed = DataFeed(timeframe="1d", period="2y")

print(f"{'Ticker':<10} {'Karakter':<38} {'Hari cek':>9} {'Defended':>9} {'Hit-rate':>9} {'Lolos gate floor':>17}")
print("-" * 100)

for ticker, desc in TICKERS.items():
    df = feed.fetch(ticker)
    if df is None or len(df) < 30:
        print(f"{ticker:<10} {'(data tidak cukup)':<38}")
        continue
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df = df.copy()
        df.columns = df.columns.get_level_values(0)

    close, vol, low, high = df["Close"], df["Volume"], df["Low"], df["High"]
    fp = estimate_floor_price(close, vol, low)
    floor_price = fp.get("floor_price", 0.0)

    vol_ma_series = vol.rolling(20).mean()
    n_checked = 0
    n_defended = 0
    n_pass_floor_gate = 0
    for i in range(20, len(df)):
        v = float(vol.iloc[i]); c = float(close.iloc[i])
        lo = float(low.iloc[i]); hi = float(high.iloc[i])
        prev_c = float(close.iloc[i - 1])
        vol_ma = float(vol_ma_series.iloc[i])
        if vol_ma <= 0:
            continue
        n_checked += 1
        is_heavy = v > vol_ma * 2.0
        dropped = c < prev_c
        recovered = ((c - lo) / (hi - lo) > 0.5) if (hi - lo) > 0 else False
        if is_heavy and dropped and recovered:
            n_defended += 1
            if floor_price > 0:
                pct_from_floor = (c / floor_price - 1) * 100
                if pct_from_floor <= 15.0:
                    n_pass_floor_gate += 1

    hit_rate = (n_defended / n_checked * 100) if n_checked else 0
    print(f"{ticker:<10} {desc:<38} {n_checked:>9} {n_defended:>9} {hit_rate:>8.2f}% {n_pass_floor_gate:>17}")

print("\nSELESAI — salin SEMUA output di atas.")
print("Perhatikan: 'Lolos gate floor' = defended DAN dekat floor (<=15%)")
print("— itu yg benar2 dianggap bermakna oleh sistem, bukan sekadar 'defended'.")
