"""
Simple Trading V6 — Broker History Agent V2 (Institutional)
=============================================================
UPGRADE V2:
  • Removed unused json import
  • Removed unused Optional import
  • Removed unused 'dominant' variable in get_accumulation_trend
  • All bare-except → logged handlers
  • Type hints cleaned throughout
  • No logic changes — data/DB schema preserved
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

logger   = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent.parent
DB_PATH  = BASE_DIR / "logs" / "broker_history.db"


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS broker_daily (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker      TEXT    NOT NULL,
        date        TEXT    NOT NULL,
        broker_code TEXT    NOT NULL,
        broker_name TEXT,
        broker_type TEXT,
        buy_lot     INTEGER DEFAULT 0,
        sell_lot    INTEGER DEFAULT 0,
        net_lot     INTEGER DEFAULT 0,
        buy_val_bn  REAL    DEFAULT 0,
        sell_val_bn REAL    DEFAULT 0,
        created_at  TEXT    DEFAULT (datetime('now','localtime')),
        UNIQUE(ticker, date, broker_code)
    );
    CREATE INDEX IF NOT EXISTS idx_ticker_date ON broker_daily(ticker, date);
    CREATE INDEX IF NOT EXISTS idx_date        ON broker_daily(date);

    CREATE TABLE IF NOT EXISTS broker_snapshots (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker     TEXT NOT NULL,
        date       TEXT NOT NULL,
        summary    TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(ticker, date)
    );
    """)
    conn.commit()
    return conn


def save_broker_data(ticker: str, broker_list: list, date: str | None = None) -> None:
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    t = ticker.replace(".JK", "")

    from agents.ownership_agent import BROKER_PROFILES_DEFAULT
    conn = get_db()
    try:
        for b in broker_list:
            code = b.get("code", "?")
            info = BROKER_PROFILES_DEFAULT.get(code, {})
            conn.execute("""
            INSERT OR REPLACE INTO broker_daily
            (ticker,date,broker_code,broker_name,broker_type,
             buy_lot,sell_lot,net_lot,buy_val_bn,sell_val_bn)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                t, date, code,
                info.get("name", code),
                info.get("type", "UNKNOWN"),
                b.get("buy_lot", 0),
                b.get("sell_lot", 0),
                b.get("buy_lot", 0) - b.get("sell_lot", 0),
                b.get("buy_val", 0),
                b.get("sell_val", 0),
            ))
        conn.commit()
        logger.info(f"[BrokerHistory] Saved {len(broker_list)} brokers for {t} on {date}")
    except Exception as exc:
        logger.error(f"[BrokerHistory] save_broker_data {t}: {exc}")
    finally:
        conn.close()


def get_accumulation_trend(ticker: str, days: int = 30) -> dict:
    t    = ticker.replace(".JK", "")
    conn = get_db()
    try:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        rows  = conn.execute("""
            SELECT date, broker_code, broker_type, buy_lot, sell_lot, net_lot, buy_val_bn
            FROM broker_daily
            WHERE ticker=? AND date>=?
            ORDER BY date ASC
        """, (t, since)).fetchall()

        if not rows:
            return {"available": False, "days": days, "ticker": t}

        smart_buy_total   = 0
        smart_sell_total  = 0
        retail_buy_total  = 0
        retail_sell_total = 0
        daily_net: dict   = {}
        smart_brokers: dict = {}

        for row in rows:
            d     = row["date"]
            btype = row["broker_type"]
            net   = row["net_lot"]
            buy   = row["buy_lot"]
            sell  = row["sell_lot"]
            code  = row["broker_code"]

            if btype in ("OWNER_PROXY", "FOREIGN_INST", "LOCAL_INST", "MARKET_MAKER"):
                smart_buy_total  += buy
                smart_sell_total += sell
                if code not in smart_brokers:
                    smart_brokers[code] = {
                        "buy": 0, "sell": 0, "net": 0,
                        "name": row["broker_name"], "type": btype,
                    }
                smart_brokers[code]["buy"]  += buy
                smart_brokers[code]["sell"] += sell
                smart_brokers[code]["net"]  += net
            elif btype == "RETAIL":
                retail_buy_total  += buy
                retail_sell_total += sell

            if d not in daily_net:
                daily_net[d] = {"smart_net": 0, "retail_net": 0, "total_buy": 0}
            if btype in ("OWNER_PROXY", "FOREIGN_INST", "LOCAL_INST", "MARKET_MAKER"):
                daily_net[d]["smart_net"] += net
            elif btype == "RETAIL":
                daily_net[d]["retail_net"] += net
            daily_net[d]["total_buy"] += buy

        days_data      = list(daily_net.values())
        smart_buy_days = sum(1 for d in days_data if d["smart_net"] > 0)
        smart_pct      = smart_buy_days / len(days_data) * 100 if days_data else 0
        net_smart      = smart_buy_total - smart_sell_total
        top_smart      = sorted(smart_brokers.items(), key=lambda x: -x[1]["net"])

        if smart_pct >= 70 and net_smart > 0:
            acc_signal = "STRONG_ACCUMULATION"
        elif smart_pct >= 50 and net_smart > 0:
            acc_signal = "ACCUMULATION"
        elif smart_pct >= 40:
            acc_signal = "NEUTRAL"
        elif net_smart < 0:
            acc_signal = "DISTRIBUTION"
        else:
            acc_signal = "UNKNOWN"

        return {
            "available":         True,
            "ticker":            t,
            "days":              len(days_data),
            "days_requested":    days,
            "smart_buy_days":    smart_buy_days,
            "smart_buy_pct":     round(smart_pct, 1),
            "smart_net_lot":     net_smart,
            "smart_buy_total":   smart_buy_total,
            "retail_sell_total": retail_sell_total,
            "acc_signal":        acc_signal,
            "top_smart_brokers": [
                {"code": k, "name": v["name"], "type": v["type"],
                 "net": v["net"], "buy": v["buy"], "sell": v["sell"]}
                for k, v in top_smart[:5]
            ],
            "daily_net": daily_net,
        }

    except Exception as exc:
        logger.error(f"[BrokerHistory] get_accumulation_trend {t}: {exc}")
        return {"available": False, "ticker": t, "error": str(exc)}
    finally:
        conn.close()


def get_multi_period_summary(ticker: str) -> dict:
    t      = ticker.replace(".JK", "")
    result = {"ticker": t, "periods": {}}
    for label, days in [("1W", 7), ("1M", 30), ("3M", 90), ("6M", 180)]:
        result["periods"][label] = get_accumulation_trend(t, days)
    return result


def parse_broker_csv(filepath: str, ticker: str, date: str | None = None) -> int:
    import csv
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    t = ticker.replace(".JK", "")
    broker_list = []
    try:
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = (row.get("broker_code") or row.get("Broker") or
                        row.get("broker") or row.get("Code", "")).strip().upper()
                buy_lot  = int(str(row.get("buy_lot")  or row.get("Buy Lot")  or row.get("buy",  "0")).replace(",", "") or 0)
                sell_lot = int(str(row.get("sell_lot") or row.get("Sell Lot") or row.get("sell", "0")).replace(",", "") or 0)
                buy_val  = float(str(row.get("buy_val")  or row.get("Buy Val")  or row.get("buy_value",  "0")).replace(",", "") or 0) / 1e9
                sell_val = float(str(row.get("sell_val") or row.get("Sell Val") or row.get("sell_value", "0")).replace(",", "") or 0) / 1e9
                if code:
                    broker_list.append({
                        "code": code, "buy_lot": buy_lot, "sell_lot": sell_lot,
                        "buy_val": buy_val, "sell_val": sell_val,
                    })
        if broker_list:
            save_broker_data(t, broker_list, date)
    except Exception as exc:
        logger.error(f"[BrokerHistory] parse_broker_csv: {exc}")
    return len(broker_list)


def hengky_lot_math(
    ticker: str,
    shares_out: float,
    free_float_pct: float,
    known_holders: list | None = None,
) -> dict:
    """Hengky supply concentration math from MBSS video."""
    total_float_lot = shares_out * free_float_pct / 100 / 500
    known_holders   = known_holders or []
    total_locked    = sum(h.get("lot", 0) for h in known_holders)
    free_lot        = max(0, total_float_lot - total_locked)
    control_pct     = (total_locked / total_float_lot * 100) if total_float_lot > 0 else 0

    if control_pct >= 80:   label = "SANGAT TERPUSAT — mudah dinaikkan"
    elif control_pct >= 60: label = "TERPUSAT — owner dominan"
    elif control_pct >= 40: label = "MODERATE — ada kontrol"
    else:                   label = "BEBAS — supply banyak"

    steps: list = []
    running = total_float_lot
    steps.append(f"Total float: {total_float_lot:,.0f} lot ({free_float_pct}% × {shares_out/1e6:.0f}M saham)")
    for h in known_holders:
        running -= h["lot"]
        steps.append(f"  − {h['name']}: {h['lot']:,.0f} lot → sisa {running:,.0f} lot")

    return {
        "ticker":           ticker.replace(".JK", ""),
        "shares_out":       shares_out,
        "free_float_pct":   free_float_pct,
        "total_float_lot":  round(total_float_lot),
        "total_locked_lot": round(total_locked),
        "free_lot":         round(free_lot),
        "control_pct":      round(control_pct, 1),
        "supply_label":     label,
        "steps":            steps,
        "known_holders":    known_holders,
    }
