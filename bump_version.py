#!/usr/bin/env python3
"""
bump_version.py — STV Version Manager
======================================
Usage:
  python bump_version.py "Deskripsi fix/feat ini"
  python bump_version.py "FIX: nama bug" --type fix
  python bump_version.py --show
  python bump_version.py "..." --dry-run

Versioning rules:
  Format: MAJOR.MINOR.PATCH — semua digit MAKSIMAL single digit (0-9)
  Patch rollover : 8.7.8 → 8.7.9 → 8.8.0 (bukan 8.7.10)
  Minor rollover : 8.9.9 → 9.0.0

Workflow (auto):
  1. Increment versi dengan rollover rule
  2. Prepend changelog entry ke version.json
  3. git add version.json
  4. git commit dengan message = changelog entry
  5. git push origin main
  6. git tag vX.Y.Z + git push origin vX.Y.Z
"""

import json
import subprocess
import sys
import argparse
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path

VERSION_FILE = Path(__file__).parent / "version.json"
GITHUB_REPO  = "izifaisal622/simple-trading-v"


def load():
    with open(VERSION_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save(data):
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def increment(version: str) -> str:
    """
    Increment patch dengan single-digit rollover.
    8.7.8 → 8.7.9
    8.7.9 → 8.8.0  (patch maxed, rollover minor)
    8.9.9 → 9.0.0  (minor maxed, rollover major)
    """
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(f"Format versi tidak dikenali: {version} (expected X.Y.Z)")
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

    patch += 1
    if patch > 9:
        patch = 0
        minor += 1
    if minor > 9:
        minor = 0
        major += 1

    return f"{major}.{minor}.{patch}"


def run(cmd: list, check=True) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"[ERROR] {' '.join(cmd)}")
        print(result.stderr.strip())
        sys.exit(1)
    return result


def show(data):
    print(f"Version  : {data['version']}")
    print(f"Codename : {data['codename']}")
    print(f"Date     : {data['date']}")
    print(f"\nChangelog terbaru (5 entry):")
    for entry in data["changelog"][:5]:
        print(f"  • {entry[:100]}{'...' if len(entry) > 100 else ''}")


def create_github_release(token: str, tag: str, name: str, body: str):
    """
    Buat GitHub Release via API.
    Tidak crash jika token kosong — cukup print warning.
    """
    if not token:
        print("[WARN] --token tidak diberikan — GitHub Release tidak dibuat (tag sudah push).")
        return
    import json as _json
    url     = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
    payload = _json.dumps({
        "tag_name":         tag,
        "name":             name,
        "body":             body,
        "draft":            False,
        "prerelease":       False,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data    = payload,
        method  = "POST",
        headers = {
            "Authorization": f"token {token}",
            "Content-Type":  "application/json",
            "Accept":        "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = _json.loads(resp.read())
            print(f"✓ GitHub Release: {data.get('html_url','created')}")
    except urllib.error.HTTPError as e:
        print(f"[WARN] GitHub Release gagal: {e.code} {e.reason}")


def main():
    parser = argparse.ArgumentParser(description="STV Version Bumper")
    parser.add_argument("message", nargs="?", help="Changelog message untuk versi baru")
    parser.add_argument(
        "--type", choices=["fix", "feat", "chore", "hotfix", "rewrite"],
        default=None, help="Prefix type (opsional)"
    )
    parser.add_argument("--show",    action="store_true", help="Tampilkan versi saat ini")
    parser.add_argument("--dry-run", action="store_true", help="Preview tanpa eksekusi")
    parser.add_argument("--token",   default="",          help="GitHub token untuk buat Release (opsional, bisa juga set env GH_TOKEN)")
    args = parser.parse_args()

    import os
    data = load()
    gh_token = args.token or os.environ.get("GH_TOKEN", "")

    if args.show:
        show(data)
        return

    if not args.message:
        print("ERROR: Harus ada message. Contoh:")
        print('  python bump_version.py "FIX: log_trade() entry_date mismatch"')
        print('  python bump_version.py --show')
        sys.exit(1)

    old_version = data["version"]
    new_version = increment(old_version)
    today       = date.today().strftime("%Y-%m-%d")

    # Build prefix jika --type diberikan
    msg = args.message.strip()
    if args.type:
        prefix_map = {
            "fix":     "FIX",
            "feat":    "FEAT",
            "chore":   "CHORE",
            "hotfix":  "HOTFIX",
            "rewrite": "REWRITE",
        }
        prefix = prefix_map[args.type]
        if not msg.upper().startswith(prefix):
            msg = f"{prefix}: {msg}"

    commit_msg = f"{new_version} — {msg}"

    print(f"\n{'─'*60}")
    print(f"  {old_version}  →  {new_version}")
    print(f"  {commit_msg[:70]}{'...' if len(commit_msg) > 70 else ''}")
    print(f"{'─'*60}")

    if args.dry_run:
        print("\n[DRY RUN] Tidak ada perubahan.")
        print(f"\nAkan dieksekusi:")
        print(f"  version.json: {old_version} → {new_version}")
        print(f"  git commit -m \"{commit_msg}\"")
        print(f"  git push origin main")
        print(f"  git tag v{new_version} && git push origin v{new_version}")
        return

    # 1. Update version.json
    data["version"]   = new_version
    data["date"]      = today
    data["changelog"] = [commit_msg] + data["changelog"]
    save(data)
    print("✓ version.json updated")

    # 2. git add version.json
    run(["git", "add", str(VERSION_FILE)])
    print("✓ git add version.json")

    # 3. git commit
    run(["git", "commit", "--allow-empty", "-m", commit_msg])
    print(f"✓ git commit")

    # 4. git push
    run(["git", "push", "origin", "main"])
    print(f"✓ git push origin main")

    # 5. git tag + push tag
    tag = f"v{new_version}"
    run(["git", "tag", tag])
    run(["git", "push", "origin", tag])
    print(f"✓ git tag {tag} pushed")

    # 6. GitHub Release
    create_github_release(
        token = gh_token,
        tag   = tag,
        name  = f"v{new_version} — {msg[:60]}",
        body  = commit_msg,
    )

    print(f"\n🚀 {new_version} released.")


if __name__ == "__main__":
    main()
