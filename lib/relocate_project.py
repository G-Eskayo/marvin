#!/usr/bin/env python3
"""
relocate_project.py — move a project out of iCloud ~/Documents without losing anything (#262; the #192 procedure).

Both Macs share ONE iCloud ~/Documents, and background jobs block on it, so projects belong in ~/Developer on each Mac.

  1. copy the whole folder (unpushed commits, uncommitted changes, untracked files, stashes) to <dest_root>/<name>,
     except rebuildable output git itself ignores (.build, node_modules, DerivedData…): rebuilt on the next build
  2. verify the copy reads the same: commit, `git status`, stash count and `git fsck` for a repo; file list and sizes
     for a plain folder
  3. only then rename the old copy to a hidden `.<name>-old-icloud-<date>` beside it. Nothing is ever deleted.
  4. (--to-host) copy the verified folder to the other Mac over ssh and verify it there the same way

Refuses (and moves nothing) when the destination exists or a verification differs.
    relocate_project.py PATH [--dest ~/Developer] [--to-host gils-mac-mini] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path


class RelocateRefused(Exception):
    pass


def _git(path: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=300).stdout


def state(path: Path) -> dict:
    """What must be identical after the copy."""
    path = Path(path)
    if (path / ".git").exists():
        fsck = subprocess.run(["git", "-C", str(path), "fsck", "--no-progress"], capture_output=True, text=True, timeout=600)
        return {"git": True, "head": _git(path, "rev-parse", "HEAD").strip(),
                "status": _git(path, "status", "--porcelain", "--untracked-files=all").rstrip("\n"),
                "stashes": len([l for l in _git(path, "stash", "list").splitlines() if l.strip()]),
                "fsck_ok": fsck.returncode == 0}
    files = sorted((str(p.relative_to(path)), p.stat().st_size) for p in path.rglob("*") if p.is_file())
    return {"git": False, "files": len(files), "bytes": sum(s for _, s in files), "list_hash": hashlib.sha256(json.dumps(files).encode()).hexdigest()}


# Rebuildable output, skipped ONLY when git itself ignores the folder (a tracked folder of the same name is copied).
# killer-sudoku: 11,243 of its 11,781 files were .build, and reading them out of iCloud one by one took hours.
BUILD_DIRS = {".build", "DerivedData", "node_modules", ".gradle", "build", "dist", ".next", "__pycache__", ".venv", "venv"}


def skippable(src: Path) -> list[str]:
    """Relative paths of git-ignored build-output folders (not descended into)."""
    if not (src / ".git").exists():
        return []
    found = []
    for root, dirs, _ in os.walk(src):
        if ".git" in dirs:
            dirs.remove(".git")
        for d in list(dirs):
            if d in BUILD_DIRS:
                rel = os.path.relpath(os.path.join(root, d), src)
                if subprocess.run(["git", "-C", str(src), "check-ignore", "-q", rel + "/"]).returncode == 0:
                    found.append(rel)
                    dirs.remove(d)
    return sorted(found)


def _copy(src: Path, dest: Path, skip: list[str] = ()) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    excludes = [f"--exclude=/{rel}/" for rel in skip]
    p = subprocess.run(["rsync", "-a", *excludes, f"{src}/", f"{dest}/"], capture_output=True, text=True)
    if p.returncode != 0:
        raise RelocateRefused(f"copy failed: {p.stderr.strip()[:300]}")


def relocate(src: Path, dest_root: Path, stamp: str | None = None, dry_run: bool = False) -> dict:
    src, dest_root = Path(src).expanduser(), Path(dest_root).expanduser()
    if not src.is_dir():
        raise RelocateRefused(f"{src} is not a folder")
    dest = dest_root / src.name
    if dest.exists():
        raise RelocateRefused(f"{dest} already exists: compare the two copies by hand first")
    before = state(src)
    if before.get("git") and not before["fsck_ok"]:
        raise RelocateRefused(f"{src} fails git fsck before the move: fix that first")
    skip = skippable(src)
    if dry_run:
        return {"ok": True, "dry_run": True, "src": str(src), "dest": str(dest), "state": before, "skipped": skip}
    _copy(src, dest, skip)
    after = state(dest)
    if after != before:
        raise RelocateRefused(f"the copy at {dest} doesn't match {src}; original left in place. before={before} after={after}")
    hidden = src.parent / f".{src.name}-old-icloud-{stamp or date.today().isoformat()}"
    src.rename(hidden)
    return {"ok": True, "src": str(src), "dest": str(dest), "old_copy": str(hidden), "state": after, "skipped": skip}


def send_to_host(dest: Path, host: str) -> dict:
    """Copy a verified folder to the same path on the other Mac and verify it there."""
    rel = Path(dest).relative_to(Path.home())
    probe = subprocess.run(["ssh", host, f"test -e ~/{rel} && echo EXISTS || echo free"], capture_output=True, text=True, timeout=60)
    if "EXISTS" in probe.stdout:
        raise RelocateRefused(f"{host}:~/{rel} already exists")
    p = subprocess.run(["rsync", "-a", "--partial", "-e", "ssh -o ServerAliveInterval=15", f"{dest}/", f"{host}:{rel}/"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RelocateRefused(f"copy to {host} failed: {p.stderr.strip()[:300]}")
    code = f"import sys,json; sys.path.insert(0, '{Path(__file__).parent}'); import relocate_project as r; print(json.dumps(r.state(r.Path.home()/'{rel}')))"
    remote = subprocess.run(["ssh", host, f"~/.agents/venv/bin/python -c \"{code}\""], capture_output=True, text=True, timeout=900)
    there, here = json.loads(remote.stdout.strip().splitlines()[-1]), state(dest)
    if there != here:
        raise RelocateRefused(f"{host} copy differs: {there} vs {here}")
    return {"ok": True, "host": host, "state": there}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", type=Path)
    ap.add_argument("--dest", type=Path, default=Path.home() / "Developer")
    ap.add_argument("--to-host")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    try:
        out = relocate(a.path, a.dest, dry_run=a.dry_run)
        if a.to_host and not a.dry_run:
            out["other_mac"] = send_to_host(Path(out["dest"]), a.to_host)
    except RelocateRefused as e:
        print(json.dumps({"ok": False, "refused": str(e)}))
        sys.exit(2)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
