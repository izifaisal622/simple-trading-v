"""
Simple Trading V9 — Strategy Config
Loads from config/settings.json with fallback defaults.
Auto-patch from director is applied on top at runtime.
"""
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "settings.json"
LOGS_DIR    = Path(__file__).parent.parent / "logs"
PATCH_FILE  = LOGS_DIR / "auto_patch.json"


@dataclass
class StrategyConfig:
    # ── EMA XBO ───────────────────────────────────────────────────────────────
    ema_fast:          int   = 13
    ema_slow:          int   = 89
    ema_trend:         int   = 200
    box_max_bars:      int   = 20
    box_min_bars:      int   = 3
    box_range_pct:     float = 8.0      # V3: overridden by ATR dynamic
    vol_mult:          float = 2.0
    min_score:         int   = 3
    tp1_rr:            float = 1.5
    tp2_rr:            float = 2.5
    tp3_rr:            float = 4.0

    # ── Whale Scanner ─────────────────────────────────────────────────────────
    whale_vol_multiplier: float = 2.0
    whale_min_value_bn:   float = 0.5
    whale_top_n:          int   = 30

    # ── Telegram (optional) ───────────────────────────────────────────────────
    telegram_token:    str   = ""
    telegram_chat_id:  str   = ""

    # ── Universe ──────────────────────────────────────────────────────────────
    universe_size:     str   = "full"   # full | watchlist

    @classmethod
    def load(cls) -> "StrategyConfig":
        """Load from settings.json, apply auto-patch on top."""
        cfg = cls()

        # Load user settings
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                for k, v in data.items():
                    if hasattr(cfg, k):
                        setattr(cfg, k, v)
            except Exception as e:
                print(f"[Config] Warning: cannot load settings.json: {e}")

        # Apply director auto-patch silently
        if PATCH_FILE.exists():
            try:
                patch = json.loads(PATCH_FILE.read_text(encoding="utf-8"))
                if not patch.get("_applied", False):
                    applied = []
                    for k, v in patch.items():
                        if k.startswith("_"): continue
                        if hasattr(cfg, k):
                            setattr(cfg, k, v)
                            applied.append(k)
                    if applied:
                        print(f"[Config] Auto-patch applied: {applied}")
                        patch["_applied"] = True
                        PATCH_FILE.write_text(json.dumps(patch, indent=2), encoding="utf-8")
            except Exception:
                pass

        return cfg

    def save(self):
        """Save current config to settings.json."""
        CONFIG_FILE.parent.mkdir(exist_ok=True)
        d = asdict(self)
        # Don't save patch-applied fields (those come from auto_patch.json)
        CONFIG_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def to_dict(self) -> dict:
        return asdict(self)
