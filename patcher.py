"""
Simple Trading V6 — Patcher & Version Manager
==============================================
Versioning scheme:  MAJOR.MINOR.PATCH
  MAJOR = 6  (generasi — tidak berubah)
  MINOR = 1, 2, 3 ...  (fitur baru signifikan)
  PATCH = 1–9  (bug fix / tweak kecil)
         ↑ setelah 9: minor+1, patch kembali ke 1
         Jadi: 6.1.9 → 6.2.1  (bukan 6.2.0)

═══ WORKFLOW DEPLOY YANG BENAR ═══
  Setiap kali akan distribute RAR baru, jalankan:

    python patcher.py deploy "Deskripsi perubahan"

  Ini otomatis: backup versi aktif → bump versi → snapshot

═══ COMMANDS LENGKAP ═══
  python patcher.py deploy "note"     # REKOMENDASI: full deploy sequence
  python patcher.py deploy-minor "n" # Bump minor (fitur besar)
  python patcher.py current           # Tampilkan versi sekarang
  python patcher.py bump "note"       # Manual bump patch saja
  python patcher.py bump-minor "n"   # Manual bump minor saja
  python patcher.py backup            # Backup versi aktif ke logs/backups/
  python patcher.py list-restore      # Lihat semua restore points
  python patcher.py list              # List semua snapshots JSON
  python patcher.py snapshot "label" # Buat snapshot manual
  python patcher.py restore "label"  # Restore version.json ke snapshot

═══ FIRST TIME SETUP ═══
  python restore_setup.py             # Seed backups dari RAR yang sudah ada
"""

import sys, json, shutil
from datetime import date
from pathlib import Path

ROOT        = Path(__file__).parent
VER_FILE    = ROOT / "version.json"
SNAP_DIR    = ROOT / "logs" / "snapshots"
BACKUP_DIR  = ROOT / "logs" / "backups"
SNAP_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

MAJOR = 6        # Tidak berubah
MAX_PATCH = 9    # Setelah 9, minor naik dan patch kembali ke 1


# ─────────────────────────────────────────────────────────────────────────────
# Version helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_version() -> dict:
    try:
        return json.loads(VER_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"version": f"{MAJOR}.1.1", "codename": "UNKNOWN", "date": str(date.today()), "changelog": []}


def save_version(data: dict):
    VER_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def parse_version(ver_str: str) -> tuple:
    """'6.1.3' → (6, 1, 3)"""
    parts = ver_str.strip().lstrip("Vv").split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 1
        patch = int(parts[2]) if len(parts) > 2 else 0
        return (major, minor, patch)
    except Exception:
        return (MAJOR, 1, 1)


def fmt_version(major: int, minor: int, patch: int) -> str:
    return f"{major}.{minor}.{patch}"


def next_patch(ver_str: str) -> str:
    """
    6.1.1 → 6.1.2
    6.1.9 → 6.2.1   (patch wraps at MAX_PATCH, minor increments)
    """
    major, minor, patch = parse_version(ver_str)
    if patch >= MAX_PATCH:
        return fmt_version(major, minor + 1, 1)
    return fmt_version(major, minor, patch + 1)


def next_minor(ver_str: str) -> str:
    """6.1.x → 6.2.1"""
    major, minor, _ = parse_version(ver_str)
    return fmt_version(major, minor + 1, 1)


# ─────────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────────

def cmd_current():
    v = load_version()
    ver = v.get("version", "?")
    cd  = v.get("codename", "")
    dt  = v.get("date", "")
    print(f"\n  Current: V{ver}  [{cd}]  {dt}")
    changelog = v.get("changelog", [])
    if changelog:
        print(f"\n  Changelog (last {min(5,len(changelog))}):")
        for line in changelog[-5:]:
            print(f"    · {line}")
    print()


def cmd_bump(mode: str = "patch", note: str = ""):
    """Auto-bump version dan update version.json."""
    v       = load_version()
    old_ver = v.get("version", f"{MAJOR}.1.0")

    if mode == "minor":
        new_ver = next_minor(old_ver)
    else:
        new_ver = next_patch(old_ver)

    # Build changelog entry
    today = str(date.today())
    entry = f"{new_ver} — {today}"
    if note:
        entry += f": {note}"

    # Update version.json
    v["version"]  = new_ver
    v["date"]     = today
    changelog = v.get("changelog", [])
    changelog.append(entry)
    v["changelog"] = changelog[-50:]   # Keep last 50 entries
    save_version(v)

    print(f"  V{old_ver} → V{new_ver}  [{today}]")
    return new_ver


def cmd_list():
    snaps = sorted(SNAP_DIR.glob("*.json"))
    if not snaps:
        print("  No snapshots found.")
        return
    print(f"\n  {len(snaps)} snapshots:\n")
    for s in snaps[-20:]:
        try:
            d = json.loads(s.read_text(encoding="utf-8"))
            print(f"    V{d.get('version','?'):12s}  {d.get('date',''):12s}  {s.name}")
        except Exception:
            print(f"    {s.name}")
    print()


def cmd_snapshot(label: str = ""):
    v = load_version()
    ver = v.get("version", "?")
    if not label:
        label = f"V{ver}"
    snap_path = SNAP_DIR / f"{label.replace('.','_').replace(' ','_')}.json"
    snap_path.write_text(json.dumps(v, indent=2), encoding="utf-8")
    print(f"  Snapshot saved: {snap_path.name}")


def cmd_restore(label: str):
    snap_path = SNAP_DIR / f"{label.replace('.','_').replace(' ','_')}.json"
    if not snap_path.exists():
        # Try partial match
        matches = list(SNAP_DIR.glob(f"*{label}*"))
        if len(matches) == 1:
            snap_path = matches[0]
        elif len(matches) > 1:
            print(f"  Ambiguous label. Matches: {[m.name for m in matches]}")
            return
        else:
            print(f"  Snapshot not found: {label}")
            return
    data = json.loads(snap_path.read_text(encoding="utf-8"))
    save_version(data)
    print(f"  Restored to V{data.get('version','?')} from {snap_path.name}")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def save_rar_backup(rar_src_path: str = None) -> str | None:
    """
    Copy RAR ke logs/backups/STV_V{version}.rar untuk restore point.
    Dipanggil setelah RAR baru di-generate.
    Returns path backup atau None jika gagal.
    """
    v    = load_version()
    ver  = v.get("version", "?")
    name = f"STV_V{ver}.rar"
    dst  = BACKUP_DIR / name

    # Jika src tidak diberikan, cari RAR terbaru di outputs/
    if rar_src_path is None:
        candidates = [
            ROOT.parent / "outputs" / f"STV_V{ver}.rar",
            ROOT.parent / "outputs" / "Simple_Trading_V6.rar",
        ]
        for c in candidates:
            if c.exists():
                rar_src_path = str(c)
                break

    if not rar_src_path or not Path(rar_src_path).exists():
        return None

    try:
        import shutil
        shutil.copy2(rar_src_path, dst)
        # Prune — keep only 10 most recent backups
        backups = sorted(BACKUP_DIR.glob("STV_V*.rar"),
                        key=lambda f: f.stat().st_mtime, reverse=True)
        for old in backups[10:]:
            old.unlink(missing_ok=True)
        return str(dst)
    except Exception as e:
        print(f"  [Backup] Failed: {e}")
        return None


def auto_backup_current(label: str = "", max_keep: int = 10) -> str | None:
    """
    Pack versi AKTIF sekarang ke logs/backups/STV_V{version}_{date}.rar
    sebelum update. Dipanggil otomatis dari gate.py startup dan saat deploy.

    Returns: path RAR yang dibuat, atau None jika gagal/sudah ada.
    NEW V6.3.2
    """
    try:
        import subprocess
        v   = load_version()
        ver = v.get("version", "?").replace(".", "_")
        dt  = str(date.today()).replace("-", "")
        name = f"STV_V{ver}_{dt}.rar"
        dst  = BACKUP_DIR / name

        # Jangan backup ulang jika sudah ada hari ini
        if dst.exists():
            return str(dst)

        # File-file inti yang perlu di-backup
        core_files = [
            "gate.py", "orchestrator.py", "trade_logger.py",
            "outcome_tracker_ui.py", "patcher.py",
            "assets_ui.py", "version.json",
        ]
        dirs_to_backup = ["agents", "core", "config", "pages"]

        # Build file list yang ada
        files_exist = [str(ROOT / f) for f in core_files if (ROOT / f).exists()]
        dirs_exist  = [str(ROOT / d) for d in dirs_to_backup if (ROOT / d).exists()]

        if not files_exist and not dirs_exist:
            return None

        # Coba rar command — fallback ke zip jika rar tidak ada di PATH (WinError 2)
        rar_ok = False
        try:
            cmd = ["rar", "a", "-ep1", str(dst)] + files_exist + dirs_exist
            result = subprocess.run(cmd, capture_output=True, timeout=60)
            rar_ok = result.returncode in (0, 1)  # 1 = warning (ok)
        except (FileNotFoundError, OSError):
            rar_ok = False

        if not rar_ok:
            # Fallback ke zip
            import zipfile
            zip_dst = BACKUP_DIR / name.replace(".rar", ".zip")
            with zipfile.ZipFile(str(zip_dst), "w", zipfile.ZIP_DEFLATED) as zf:
                for fp in files_exist:
                    zf.write(fp, Path(fp).name)
                for dp in dirs_exist:
                    for f in Path(dp).rglob("*"):
                        if f.is_file() and not any(
                            p in str(f) for p in ["__pycache__", ".pyc"]
                        ):
                            zf.write(str(f), str(f.relative_to(ROOT)))
            dst = zip_dst

        if not dst.exists():
            return None

        # Prune — keep only max_keep backups
        all_bak = sorted(
            list(BACKUP_DIR.glob("STV_V*.rar")) + list(BACKUP_DIR.glob("STV_V*.zip")),
            key=lambda f: f.stat().st_mtime, reverse=True
        )
        for old in all_bak[max_keep:]:
            old.unlink(missing_ok=True)

        return str(dst)

    except Exception as e:
        print(f"  [AutoBackup] Warning: {e}")
        return None


def _parse_backup_filename(stem: str) -> tuple[str, str]:
    """
    Parse versi dan tanggal dari nama file backup.
    Handle dua format:
      Baru: STV_V6_3_2_20260605  → ("6.3.2", "2026-06-05")
      Lama: STV_V6.2.7           → ("6.2.7", "")
      Lama: STV_V6.3.1           → ("6.3.1", "")
    Returns: (ver_str, date_str)
    """
    raw = stem.replace("STV_V", "").replace("STV_v", "")

    # Format baru: angka dipisah underscore + tanggal di akhir
    # Contoh: 6_3_2_20260605
    if "_" in raw:
        parts = raw.split("_")
        ver_str = ""
        date_str = ""
        try:
            # Cari 3 angka versi di awal
            num_parts = []
            tail_parts = []
            for i, p in enumerate(parts):
                if p.isdigit() and len(num_parts) < 3:
                    num_parts.append(p)
                else:
                    tail_parts = parts[i:]
                    break
            if len(num_parts) >= 3:
                ver_str = f"{num_parts[0]}.{num_parts[1]}.{num_parts[2]}"
            # Cari tanggal (8 digit) di sisa
            for tp in tail_parts:
                if tp.isdigit() and len(tp) == 8:
                    d = tp
                    date_str = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                    break
        except Exception:
            pass
        return ver_str, date_str

    # Format lama: 6.2.7 atau 6.3.1 (titik sebagai separator)
    if "." in raw:
        # raw = "6.2.7" atau "6.3.1"
        dots = raw.split(".")
        if len(dots) >= 3 and all(d.isdigit() for d in dots[:3]):
            return f"{dots[0]}.{dots[1]}.{dots[2]}", ""
        # Mungkin ada suffix: "6.3.1_backup" — coba strip
        try:
            clean = dots[0] + "." + dots[1] + "." + dots[2].split("_")[0]
            return clean, ""
        except Exception:
            pass

    return raw, ""


def get_backup_list(max_items: int = 5) -> list[dict]:
    """
    Return sorted list of backup metadata dicts:
      {name, path, version, date_str, size_mb}
    Newest first, excludes versi aktif dari list (karena bukan "sebelumnya").
    Used by gate.py for restore points display.
    V6.3.2 — fixed: handle format lama (STV_V6.2.7) dan baru (STV_V6_3_2_yyyymmdd)
    """
    cur_ver = ""
    try:
        v = load_version()
        cur_ver = v.get("version", "")
    except Exception:
        pass

    all_bak = sorted(
        list(BACKUP_DIR.glob("STV_V*.rar")) + list(BACKUP_DIR.glob("STV_V*.zip")),
        key=lambda f: f.stat().st_mtime, reverse=True
    )

    result = []
    seen_versions = set()  # Deduplikasi: jika ada dua file versi sama, ambil yang terbaru

    for bf in all_bak:
        ver_str, date_str = _parse_backup_filename(bf.stem)

        # Skip duplikat versi (keep newest)
        dedup_key = ver_str or bf.stem
        if dedup_key in seen_versions:
            continue
        seen_versions.add(dedup_key)

        result.append({
            "name":      bf.name,
            "path":      str(bf),
            "version":   f"V{ver_str}" if ver_str else bf.stem,
            "ver_raw":   ver_str,
            "date_str":  date_str,
            "size_mb":   round(bf.stat().st_size / 1024 / 1024, 2),
            "is_active": (ver_str == cur_ver),
        })

        if len(result) >= max_items:
            break

    return result


def list_backups() -> list:
    """Return list of available backup RARs, newest first."""
    return sorted(
        BACKUP_DIR.glob("STV_V*.rar"),
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )


def deploy(note: str = "", bump_mode: str = "patch") -> str:
    """
    Full deploy sequence — jalankan ini sebelum distribusi versi baru:
      1. Backup versi AKTIF sekarang ke logs/backups/
      2. Bump version (patch atau minor)
      3. Buat snapshot version.json
      4. Print summary

    Usage:
      python patcher.py deploy "Deskripsi perubahan"
      python patcher.py deploy-minor "Fitur besar"

    Returns: new version string
    NEW V6.3.3
    """
    print("\n🚀 DEPLOY SEQUENCE")
    print("─" * 40)

    # Step 1: Backup versi sekarang SEBELUM bump
    print("\n1. Backup versi aktif...")
    bak_path = auto_backup_current()
    if bak_path:
        print(f"   ✓ Backed up: {Path(bak_path).name}")
    else:
        print("   · Backup skip (sudah ada atau gagal)")

    # Step 2: Bump versi
    print("\n2. Bump version...")
    new_ver = cmd_bump(bump_mode, note)
    print(f"   ✓ Version: V{new_ver}")

    # Step 3: Snapshot
    print("\n3. Snapshot version.json...")
    cmd_snapshot(f"V{new_ver}")
    print(f"   ✓ Snapshot saved")

    # Step 4: Summary
    print("\n4. Restore points tersedia:")
    baks = get_backup_list(5)
    for b in baks:
        active = " ← AKTIF" if b.get("is_active") else ""
        print(f"   {b['version']:<12} {b['date_str'] or '—':<12} {b['size_mb']:.1f}MB{active}")

    print(f"\n✅ V{new_ver} siap deploy. Build RAR lalu distribute.")
    print("─" * 40)
    return new_ver


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        cmd_current()
        return

    cmd = args[0].lower()

    if cmd == "current":
        cmd_current()

    elif cmd in ("bump", "bump-patch"):
        note = args[1] if len(args) > 1 else ""
        cmd_bump("patch", note)

    elif cmd == "bump-minor":
        note = args[1] if len(args) > 1 else ""
        cmd_bump("minor", note)

    elif cmd == "list":
        cmd_list()

    elif cmd == "backup":
        # Auto-backup versi aktif (baru di V6.3.2)
        dst = auto_backup_current()
        if dst:
            print(f"  Backup saved: {dst}")
        else:
            # Fallback: coba save_rar_backup dengan src manual
            src = args[1] if len(args) > 1 else None
            dst2 = save_rar_backup(src)
            if dst2:
                print(f"  Backup saved: {dst2}")
            else:
                print("  Backup failed. Ensure 'rar' is installed or project files accessible.")

    elif cmd == "list-restore":
        baks = get_backup_list(10)
        if baks:
            print(f"\n  {len(baks)} restore point(s):\n")
            for b in baks:
                print(f"    {b['version']:12s}  {b['date_str']:12s}  {b['size_mb']:.1f}MB  {b['name']}")
        else:
            print("  No restore points found.")
        print()

    elif cmd in ("list-backups", "list-restore"):
        baks = get_backup_list(10)
        if baks:
            print(f"\n  {len(baks)} restore point(s):\n")
            for b in baks:
                active = " ← AKTIF" if b.get("is_active") else ""
                print(f"    {b['version']:<12} {b['date_str'] or '—':<12} {b['size_mb']:.1f}MB  {b['name']}{active}")
        else:
            print("  No restore points yet. Run: python patcher.py backup")
        print()

    elif cmd == "deploy":
        note = args[1] if len(args) > 1 else ""
        deploy(note, "patch")

    elif cmd == "deploy-minor":
        note = args[1] if len(args) > 1 else ""
        deploy(note, "minor")

    elif cmd == "snapshot":
        label = args[1] if len(args) > 1 else ""
        cmd_snapshot(label)

    elif cmd == "restore":
        if len(args) < 2:
            print("  Usage: python patcher.py restore <label>")
        else:
            cmd_restore(args[1])

    else:
        print(f"  Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
