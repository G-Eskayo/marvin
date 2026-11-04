#!/usr/bin/env python3
"""A project's gitignored models, fetched once per machine and linked into each worktree (#1114).

A pipeline worktree or merge-gate checkout is a fresh clone, so a model the app needs at build time but that git
never holds (Seal Speak's Parakeet Ultra and Sortformer, hundreds of MB each) is missing there, and the build fails
before any test runs. A project profile's setup step calls this instead:

    model_cache.py link --project P --name N --key FILE [--key FILE ...] --into PATH [--into PATH ...] -- FETCH...

- The cache is <root>/<project>/<name>/<key>/<name>, where <key> hashes the --key files (the fetch script and its
  sha256 manifest, the same files GitHub CI keys its cache on), so a branch that changes the model gets its own copy.
- FETCH is the project's own fetch command, run in the worktree with MODEL_CACHE_DEST (the folder to create) and
  MODEL_CACHE_WORK (an empty scratch folder). It runs under a per-model lock, into a staging folder, and its result
  is moved in only when it exits 0 and produced files. The file list with sizes is written last: it is what makes a
  copy "cached", and every later run checks it with a stat walk (cheap, no hashing), fetching again when files are
  missing, extra or resized. The project's fetch script does the sha256 checks.
- Each --into path becomes a link to the cache. Links are removed before a fetch, so a fetch that writes at the
  in-tree path can never write into a cached copy. A real folder already at a path is kept. Links are excluded in
  the clone's info/exclude so `git add -A` can't commit them.
- A failed fetch (no network, a bad download) exits 1 with the model's name, the fetch's last lines and how to
  fetch it by hand. Nothing half-done is left behind.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_ROOT = Path.home() / ".agents-pipeline-cache" / "models"
MANIFEST = "files.json"


class FetchFailed(RuntimeError):
    pass


def cache_key(key_files: list[Path]) -> str:
    h = hashlib.sha256()
    for f in key_files:
        try:
            data = Path(f).read_bytes()
        except OSError as e:
            raise FetchFailed(f"can't read cache key file {f}: {e.strerror or e}") from e
        h.update(Path(f).name.encode() + b"\0" + hashlib.sha256(data).digest())
    return h.hexdigest()[:16]


def _listing(folder: Path) -> dict[str, int]:
    out = {}
    for base, _dirs, files in os.walk(folder):
        for f in files:
            if f == ".DS_Store":
                continue
            p = Path(base) / f
            out[str(p.relative_to(folder))] = p.stat().st_size
    return out


def _valid(key_dir: Path, name: str) -> bool:
    content = key_dir / name
    try:
        want = json.loads((key_dir / MANIFEST).read_text())
    except (OSError, ValueError):
        return False
    return isinstance(want, dict) and bool(want) and content.is_dir() and _listing(content) == want


def _rm(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _exclude(worktree: Path, targets: list[Path]) -> None:
    r = subprocess.run(["git", "rev-parse", "--git-common-dir", "--show-toplevel"], cwd=worktree, capture_output=True,
                       text=True)
    if r.returncode != 0:
        return
    common, top = r.stdout.split("\n")[:2]
    exclude = (worktree / common).resolve() / "info" / "exclude"
    try:
        have = exclude.read_text().splitlines() if exclude.exists() else []
        add = ["/" + str(t.relative_to(Path(top).resolve())) for t in targets]
        add = [a for a in add if a not in have]
        if add:
            exclude.parent.mkdir(parents=True, exist_ok=True)
            exclude.write_text("\n".join(have + add) + "\n")
    except (OSError, ValueError):
        pass   # the ignore rule is a belt-and-braces; a link that can't be excluded still works


def _fetch(name: str, key_dir: Path, fetch: list[str], cwd: Path) -> None:
    staging = key_dir.parent / f"{key_dir.name}.partial-{os.getpid()}"
    _rm(staging)
    work = staging / ".work"
    work.mkdir(parents=True)
    dest = staging / name
    env = {**os.environ, "MODEL_CACHE_DEST": str(dest), "MODEL_CACHE_WORK": str(work)}
    try:
        r = subprocess.run(fetch, cwd=cwd, env=env, capture_output=True, text=True)
        tail = "\n".join(((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-8:])
        if r.returncode != 0:
            raise FetchFailed(f"couldn't fetch the {name} model (the fetch exited {r.returncode}):\n{tail}")
        files = _listing(dest) if dest.is_dir() else {}
        if not files:
            raise FetchFailed(f"the {name} model's fetch exited 0 but produced no files at $MODEL_CACHE_DEST:\n{tail}")
        shutil.rmtree(work)
        (staging / MANIFEST).write_text(json.dumps(files, sort_keys=True))
        _rm(key_dir)
        staging.rename(key_dir)
    except FetchFailed as e:
        raise FetchFailed(f"{e}\nThis checkout can't build without it. Check the network, or fetch it by hand once "
                          f"with: cd {cwd} && MODEL_CACHE_DEST=<folder> {' '.join(fetch)}") from None
    finally:
        _rm(staging)


def ensure(name: str, key_files: list[Path], targets: list[Path], fetch: list[str], *, cwd: Path,
           root: Path = DEFAULT_ROOT, project: str = "default") -> list[str]:
    """Make every target a link to a checked cached copy of `name`, fetching it first if needed. Returns notes."""
    cwd = Path(cwd).resolve()
    targets = [Path(t) if Path(t).is_absolute() else cwd / t for t in targets]
    for t in targets:
        if not os.path.normpath(t).startswith(str(cwd) + os.sep):
            raise FetchFailed(f"{t} is outside the worktree {cwd}")
    targets = [Path(os.path.normpath(t)) for t in targets]
    key = cache_key([Path(k) if Path(k).is_absolute() else cwd / k for k in key_files])
    notes = []
    need = []
    for t in targets:
        if t.is_dir() and not t.is_symlink():
            notes.append(f"{t.relative_to(cwd)}: kept the copy already there")
        else:
            need.append(t)
    if not need:
        return notes
    model_dir = Path(root) / project / name
    model_dir.mkdir(parents=True, exist_ok=True)
    key_dir = model_dir / key
    with open(model_dir / ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for stale in model_dir.glob("*.partial-*"):   # only the lock holder fetches: anything here is a dead run's
            _rm(stale)
        if _valid(key_dir, name):
            notes.append(f"{name}: cached ({key})")
        else:
            for t in need:   # so a fetch that writes at the in-tree path can't write into a cached copy
                if t.is_symlink():
                    t.unlink()
            _fetch(name, key_dir, fetch, cwd)
            notes.append(f"{name}: fetched into the cache ({key})")
    for t in need:
        t.parent.mkdir(parents=True, exist_ok=True)
        if t.is_symlink():
            t.unlink()
        t.symlink_to(key_dir / name)
    _exclude(cwd, need)
    return notes


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="model_cache", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ln = sub.add_parser("link", help="link a cached model into this worktree, fetching it once if needed")
    ln.add_argument("--project", required=True)
    ln.add_argument("--name", required=True)
    ln.add_argument("--key", action="append", required=True, help="a file the model's version depends on")
    ln.add_argument("--into", action="append", required=True, help="a path in this worktree to link it at")
    ln.add_argument("--root", default=str(DEFAULT_ROOT))
    ln.add_argument("fetch", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)
    fetch = a.fetch[1:] if a.fetch[:1] == ["--"] else a.fetch
    if not fetch:
        ap.error("link needs the fetch command after --")
    for part in (a.project, a.name):
        if not part or "/" in part or part.startswith("."):
            ap.error(f"bad name {part!r}")
    try:
        notes = ensure(a.name, [Path(k) for k in a.key], [Path(t) for t in a.into], fetch, cwd=Path.cwd(),
                       root=Path(a.root), project=a.project)
    except FetchFailed as e:
        print(f"model_cache: {e}", file=sys.stderr)
        return 1
    for n in notes:
        print(f"model_cache: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
