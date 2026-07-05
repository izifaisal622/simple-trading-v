"""
tools/ship.py — commit + push + GitHub Release dalam satu perintah, dari mesin lokal.

Pakai:
    python tools/ship.py
    python tools/ship.py -m "pesan commit custom"

Yang dilakukan:
1. Baca versi terkini dari version.json (root repo)
2. git add -A, commit dengan pesan "<versi> — <baris changelog pertama>" (atau -m)
3. git push
4. Buat GitHub Release via `gh` CLI kalau terpasang; kalau tidak, buka
   halaman release di browser dengan tag terisi.

Kredensial: memakai login git/gh yang SUDAH ada di mesin ini.
Tidak ada token di script, tidak ada token di chat.
"""

import json
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/izifaisal622/simple-trading-v"


def run(cmd: list, check: bool = True) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=ROOT, check=check)


def main() -> None:
    vfile = ROOT / "version.json"
    if not vfile.exists():
        sys.exit("version.json tidak ditemukan — jalankan dari dalam repo.")

    data = json.loads(vfile.read_text(encoding="utf-8"))
    version = str(data.get("version", "")).strip()
    if not version:
        sys.exit("Field 'version' kosong di version.json.")

    # Pesan commit: -m custom, atau baris changelog teratas
    if len(sys.argv) >= 3 and sys.argv[1] == "-m":
        msg = sys.argv[2]
    else:
        cl = data.get("changelog", [])
        first = cl[0] if cl else ""
        if isinstance(first, dict):
            first = "; ".join(first.get("changes", [])[:1])
        msg = str(first)[:120] or f"release {version}"

    # Guard: jangan commit kalau tidak ada perubahan
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                            capture_output=True, text=True)
    if not status.stdout.strip():
        sys.exit("Tidak ada perubahan untuk di-commit.")

    run(["git", "add", "-A"])
    run(["git", "commit", "-m", f"{version} — {msg}"])
    run(["git", "push"])

    # Release: gh CLI kalau ada, fallback ke browser
    tag = f"v{version}"
    has_gh = subprocess.run(["gh", "--version"], capture_output=True).returncode == 0 \
        if _which("gh") else False
    if has_gh:
        run(["gh", "release", "create", tag, "--title", tag, "--notes", msg],
            check=False)
    else:
        url = f"{REPO_URL}/releases/new?tag={tag}&title={tag}"
        print(f"gh CLI tidak terpasang — buka browser: {url}")
        webbrowser.open(url)

    print(f"\nSelesai: {tag} — {msg}")


def _which(name: str) -> bool:
    from shutil import which
    return which(name) is not None


if __name__ == "__main__":
    main()
