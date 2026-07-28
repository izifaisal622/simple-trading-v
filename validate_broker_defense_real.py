"""
validate_broker_defense_real.py — Uji get_broker_position/get_broker_bottom_buys/
get_broker_defense_streak/get_top_brokers_to_watch terhadap data broker_daily
PRODUKSI NYATA (bukan sintetis lagi). Read-only, tidak mengubah data apa pun.

Jalankan dari folder repo: python validate_broker_defense_real.py
"""
import sys, sqlite3
sys.path.insert(0, ".")
from core.data_feed import DataFeed
from agents.broker_defense import (
    get_broker_position, get_broker_bottom_buys,
    get_broker_defense_streak, get_top_brokers_to_watch,
)

# Ambil semua ticker unik yg ada di broker_daily
conn = sqlite3.connect("logs/broker_history.db")
tickers = [r[0] for r in conn.execute(
    "SELECT DISTINCT ticker FROM broker_daily ORDER BY ticker"
).fetchall()]
conn.close()
print(f"Ticker di broker_daily: {len(tickers)} — {tickers}\n")

feed = DataFeed(timeframe="1d", period="2y")

print("=" * 78)
print("1) get_broker_position — posisi kumulatif tiap broker per ticker")
print("=" * 78)
conn = sqlite3.connect("logs/broker_history.db")
for t in tickers[:5]:  # 5 ticker pertama saja biar tak kepanjangan
    codes = [r[0] for r in conn.execute(
        "SELECT DISTINCT broker_code FROM broker_daily WHERE ticker=?", (t,)
    ).fetchall()]
    print(f"\n{t} — {len(codes)} broker aktif:")
    for code in codes:
        pos = get_broker_position(t, code)
        tag = "AKUMULATOR" if pos["cumulative_net_lot"] > 0 else "DISTRIBUTOR" if pos["cumulative_net_lot"] < 0 else "NETRAL"
        print(f"  {code}: net_lot={pos['cumulative_net_lot']:>10} | buy={pos['cumulative_buy_lot']:>10} "
              f"sell={pos['cumulative_sell_lot']:>10} | {tag}")
conn.close()

print("\n" + "=" * 78)
print("2) get_top_brokers_to_watch — ranking top-3 per ticker (butuh data harga)")
print("=" * 78)
for t in tickers[:5]:
    df = feed.fetch(f"{t}.JK")
    if df is None or len(df) < 21:
        print(f"\n{t}: data harga tidak cukup ({0 if df is None else len(df)} bar), skip.")
        continue
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df = df.copy()
        df.columns = df.columns.get_level_values(0)

    top = get_top_brokers_to_watch(t, df, top_n=3)
    print(f"\n{t}:")
    if not top:
        print("  (tidak ada broker akumulator — semua net-seller atau tak ada data)")
    for r in top:
        print(f"  {r['broker_code']}: skor={r['score']} | posisi={r['position']['cumulative_net_lot']} lot | "
              f"defends={r['n_defends']} | bottom_buys={r['n_bottom_buys']} | watch_worthy={r['watch_worthy']}")

print("\n" + "=" * 78)
print("SELESAI — salin SEMUA output di atas.")
print("=" * 78)
