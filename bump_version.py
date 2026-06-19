#!/usr/bin/env python3
"""
bump_version.py — STV Version Manager
======================================
Usage:
  python bump_version.py "Deskripsi singkat fix/feat ini"
  python bump_version.py "FIX: nama bug" --type fix
  python bump_version.py "FEAT: nama fitur" --type feat
  python bump_version.py --show

Workflow:
  1. Baca version.json
  2. Increment patch (8.X.Y → 8.X.Y+1)
  3. Prepend changelog entry
  4. git add version.json
  5. Print perintah commit + tag yang siap di-copy

Tidak auto-commit — user tetap control penuh atas commit message.
"""

import json
import subprocess
import sys
import argparse
from datetime import date
from pathlib import Path

VERSION_FILE = Path(__file__).parent / "version.json"


def load():
    with open(VERSION_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save(data):
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def increment_patch(version: str) -> str:
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(f"Format versi tidak dikenali: {version} (expected X.Y.Z)")
    major, minor, patch = parts
    return f"{major}.{minor}.{int(patch) + 1}"


def git_stage():
    result = subprocess.run(
        ["git", "add", str(VERSION_FILE)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[WARN] git add gagal: {result.stderr.strip()}")


def show(data):
    print(f"Version  : {data['version']}")
    print(f"Codename : {data['codename']}")
    print(f"Date     : {data['date']}")
    print(f"\nChangelog terbaru (5 entry):")
    for entry in data["changelog"][:5]:
        print(f"  • {entry[:100]}{'...' if len(entry)>100 else ''}")


def main():
    parser = argparse.ArgumentParser(description="STV Version Bumper")
    parser.add_argument("message", nargs="?", help="Changelog message untuk versi baru")
    parser.add_argument("--type", choices=["fix","feat","chore","hotfix","rewrite"],
                        default=None, help="Prefix type (opsional, bisa langsung tulis di message)")
    parser.add_argument("--show", action="store_true", help="Tampilkan versi saat ini tanpa bump")
    parser.add_argument("--dry-run", action="store_true", help="Preview tanpa write/git")
    args = parser.parse_args()

    data = load()

    if args.show:
        show(data)
        return

    if not args.message:
        print("ERROR: Harus ada message. Contoh:")
        print('  python bump_version.py "FIX: log_trade() entry_date parameter mismatch"')
        print('  python bump_version.py --show')
        sys.exit(1)

    old_version = data["version"]
    new_version = increment_patch(old_version)
    today       = date.today().strftime("%Y-%m-%d")

    # Build prefix jika --type diberikan dan message belum punya prefix
    msg = args.message.strip()
    if args.type and not msg.upper().startswith(args.type.upper()):
        prefix_map = {
            "fix":     "FIX",
            "feat":    "FEAT",
            "chore":   "CHORE",
            "hotfix":  "HOTFIX",
            "rewrite": "REWRITE",
        }
        msg = f"{prefix_map[args.type]}: {msg}"

    changelog_entry = f"{new_version} — {msg}"

    print(f"\n{'─'*55}")
    print(f"  {old_version}  →  {new_version}")
    print(f"  {changelog_entry[:70]}{'...' if len(changelog_entry)>70 else ''}")
    print(f"{'─'*55}")

    if args.dry_run:
        print("\n[DRY RUN] Tidak ada perubahan.")
        print(f"\nCommit yang akan dibuat:")
        print(f'  git commit -m "{changelog_entry}"')
        print(f"  git tag v{new_version}")
        return

    # Update data
    data["version"]   = new_version
    data["date"]      = today
    data["changelog"] = [changelog_entry] + data["changelog"]
    save(data)

    # Stage version.json
    git_stage()

    print(f"\n✓ version.json updated dan di-stage.")
    print(f"\nLangkah selanjutnya — copy-paste perintah ini:")
    print(f"\n  git commit -m \"{changelog_entry}\"")
    print(f"  git push origin main")
    print(f"  git tag v{new_version} && git push origin v{new_version}")
    print()


if __name__ == "__main__":
    main()
