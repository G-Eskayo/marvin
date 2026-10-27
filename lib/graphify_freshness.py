#!/usr/bin/env python3
"""Keeps the graphify code graph current, and says when it isn't (marvin#691).

Three ways the graph went stale (found 2026-10-26, docs/research/knowledge-graphs-2026-10-26.md):
1. graphify's own hook rebuilds on post-commit only, but code_sync lands most commits with `git merge`, which fires
   post-merge. The graph sat 84 commits behind HEAD.
2. A rebuild that finds no topology change leaves graph.json untouched, so its `built_at_commit` lags even when the
   graph is right. `built_at_commit` alone can't say "current"; the stamp written here can.
3. graphify backs up a dated snapshot daily and nothing prunes them (22 dirs, 242 MB).

`refresh` is the one writer: every hook (post-commit, post-merge, post-rewrite) and the Health tab's "Rebuild graph
now" button call it. It runs `graphify update`, records the result in graphify-out/.marvin_freshness.json, and prunes
snapshots to the newest KEEP_SNAPSHOTS. `check` is the Health check `graphify:fresh`; it reads only the tail of
graph.json and one `git diff --name-only`, so it costs O(changed files), not O(graph).

    graphify_freshness.py refresh <repo> [--graphify PATH]
    graphify_freshness.py install-hooks <repo>
    graphify_freshness.py check <repo>
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

OUT = "graphify-out"
STAMP = ".marvin_freshness.json"
LOCK = ".marvin_freshness.lock"
KEEP_SNAPSHOTS = 7
RED_AFTER_HOURS = 24
UPDATE_TIMEOUT_S = 900
TAIL_BYTES = 4096

CHECK_ID, CHECK_LABEL = "graphify:fresh", "Code graph is current"
HOOKS = ("post-commit", "post-merge", "post-rewrite")
MARKER_START = "# marvin-graphify-freshness-start"
MARKER_END = "# marvin-graphify-freshness-end"
GRAPHIFY_START, GRAPHIFY_END = "# graphify-hook-start", "# graphify-hook-end"
LOG = Path.home() / ".cache" / "graphify-rebuild.log"

_SHA = re.compile(r'"built_at_commit"\s*:\s*"([0-9a-f]{7,40})"')
_SNAPSHOT = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _git_env() -> dict:
    # A hook exports GIT_DIR/GIT_INDEX_FILE for its own repo; they must not leak into git calls aimed elsewhere
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env=_git_env())


def default_graphify() -> str:
    # absolute: launchd (code_sync) runs with a PATH that omits ~/.local/bin
    return os.environ.get("GRAPHIFY_BIN") or shutil.which("graphify") or str(Path.home() / ".local" / "bin" / "graphify")


# ── reading ──────────────────────────────────────────────────────────────

def read_built_commit(graph_json: Path) -> str | None:
    """`built_at_commit` is the last key graphify writes; read the tail, never parse a 15 MB graph for one string."""
    try:
        with open(graph_json, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - TAIL_BYTES))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    m = _SHA.search(tail)
    return m.group(1) if m else None


def read_stamp(out_dir: Path) -> dict | None:
    try:
        return json.loads((Path(out_dir) / STAMP).read_text())
    except (OSError, ValueError):
        return None


def _write_stamp(out_dir: Path, stamp: dict) -> None:
    tmp = Path(out_dir) / (STAMP + ".tmp")
    tmp.write_text(json.dumps(stamp, indent=2))
    os.replace(tmp, Path(out_dir) / STAMP)


def _tracked(out_dir: Path) -> tuple[set[str], set[str]]:
    """Paths graphify extracted, and their extensions (so a brand-new .py counts but a .heic never does)."""
    try:
        paths = set(json.loads((Path(out_dir) / "manifest.json").read_text()))
    except (OSError, ValueError):
        paths = set()
    return paths, {Path(p).suffix for p in paths if Path(p).suffix}


def tracked_changes(repo: Path, since_sha: str) -> list[str] | None:
    """Graph-tracked files that differ between `since_sha` and HEAD. Trees are diffed, not history walked, so a build
    commit off to the side of HEAD (after a rebase) still works. None when the commit isn't in this repo."""
    repo = Path(repo)
    if _git(repo, "cat-file", "-e", f"{since_sha}^{{commit}}").returncode != 0:
        return None
    r = _git(repo, "diff", "--name-only", since_sha, "HEAD")
    if r.returncode != 0:
        return None
    paths, exts = _tracked(repo / OUT)
    return [p for p in r.stdout.splitlines()
            if p and not p.startswith(OUT + "/") and (p in paths or Path(p).suffix in exts)]


def _is_main_worktree(repo: Path) -> bool:
    gd, cd = _git(repo, "rev-parse", "--git-dir"), _git(repo, "rev-parse", "--git-common-dir")
    if gd.returncode or cd.returncode:
        return False
    return (repo / gd.stdout.strip()).resolve() == (repo / cd.stdout.strip()).resolve()


def _hooks_dir(repo: Path) -> Path:
    p = Path(_git(repo, "rev-parse", "--git-path", "hooks").stdout.strip())
    return p if p.is_absolute() else Path(repo) / p


def missing_hooks(repo: Path) -> list[str]:
    d = _hooks_dir(Path(repo))
    out = []
    for name in HOOKS:
        try:
            ok = MARKER_START in (d / name).read_text() and os.access(d / name, os.X_OK)
        except OSError:
            ok = False
        if not ok:
            out.append(name)
    return out


# ── severity ─────────────────────────────────────────────────────────────

def _files(n: int) -> str:
    return f"{n} file{'' if n == 1 else 's'} changed"


def evaluate(*, head: str | None, basis_sha: str | None, basis_at: datetime | None, changed: list[str] | None,
             last_error: str | None, missing_hooks: list[str], graph_exists: bool, now: datetime
             ) -> tuple[str, str, int | None]:
    """Pure: (severity, detail, value). value = graph-tracked files changed since the graph was last known current."""
    if not graph_exists:
        return "yellow", "graph not built on this machine yet (graphify update .)", None
    if missing_hooks:
        return "red", f"git hooks that keep it current are missing: {', '.join(missing_hooks)} (graphify_freshness.py install-hooks)", None
    if last_error:
        return "red", f"last rebuild failed: {last_error.strip()[-300:]}", None
    if changed is None:
        return "red", f"built from {str(basis_sha)[:7]}, a commit this repo doesn't have; rebuild it", None
    if not changed:
        return "green", f"current at {str(head)[:7]}", 0
    age_h = (now - basis_at).total_seconds() / 3600 if basis_at else float("inf")
    when = f"{age_h:.1f} h ago" if age_h < 48 else f"{age_h / 24:.1f} days ago"
    sev = "red" if age_h > RED_AFTER_HOURS else "yellow"
    sample = ", ".join(changed[:3]) + (", …" if len(changed) > 3 else "")
    return sev, f"{_files(len(changed))} since build {str(basis_sha)[:7]} ({when}): {sample}", len(changed)


def _parse(ts) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def check(repo: Path, now: datetime | None = None, hooks_ok: bool | None = None) -> dict:
    repo, now = Path(repo), now or _now()
    out = repo / OUT
    stamp = read_stamp(out) or {}
    graph = out / "graph.json"
    head = _git(repo, "rev-parse", "HEAD").stdout.strip() or None
    basis_sha, basis_at = stamp.get("last_ok_head"), _parse(stamp.get("last_ok_at"))
    if not basis_sha:
        basis_sha = read_built_commit(graph)
        if basis_sha:
            t = _git(repo, "show", "-s", "--format=%cI", basis_sha)
            basis_at = _parse(t.stdout.strip()) if t.returncode == 0 else None
    changed = tracked_changes(repo, basis_sha) if basis_sha else None
    sev, detail, value = evaluate(head=head, basis_sha=basis_sha, basis_at=basis_at, changed=changed,
                                  last_error=stamp.get("last_error"),
                                  missing_hooks=[] if hooks_ok else missing_hooks(repo),
                                  graph_exists=graph.exists(), now=now)
    return {"id": CHECK_ID, "label": CHECK_LABEL, "severity": sev, "detail": detail,
            "checked_at": now.isoformat(), "value": value}


# ── writing ──────────────────────────────────────────────────────────────

def prune_snapshots(out_dir: Path, keep: int = KEEP_SNAPSHOTS) -> list[str]:
    """Delete all but the newest `keep` dated (YYYY-MM-DD) backup dirs graphify made inside out_dir. Disposable tier:
    each is a copy of an older graph. Symlinks are unlinked, never followed; nothing else is touched."""
    out_dir = Path(out_dir)
    dated = sorted((p for p in out_dir.iterdir() if _SNAPSHOT.match(p.name) and (p.is_dir() or p.is_symlink())),
                   key=lambda p: p.name)
    removed = []
    for p in dated[:-keep] if keep > 0 else dated:
        if p.is_symlink():
            p.unlink()
        else:
            shutil.rmtree(p)
        removed.append(p.name)
    return removed


def refresh(repo: Path, graphify: str | None = None, now: datetime | None = None) -> dict:
    """Run `graphify update`, stamp the result, prune snapshots. Serialized by a lock so two hooks firing together
    (amend + rewrite, merge + button) run one after the other instead of writing graph.json at once."""
    repo = Path(repo).resolve()
    out = repo / OUT
    if not out.is_dir() or not _is_main_worktree(repo):
        return {"skipped": True, "ok": None}
    with open(out / LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        head = _git(repo, "rev-parse", "HEAD").stdout.strip()
        stamp = read_stamp(out) or {}
        when = (now or _now()).isoformat()
        try:
            r = subprocess.run([graphify or default_graphify(), "update", str(repo)], cwd=repo, capture_output=True,
                               text=True, timeout=UPDATE_TIMEOUT_S, env={**_git_env(), "PYTHONHASHSEED": "0"})
            ok, error = r.returncode == 0, None if r.returncode == 0 else (r.stdout + r.stderr).strip()[-500:] or f"exit {r.returncode}"
        except (OSError, subprocess.SubprocessError) as exc:
            ok, error = False, f"{type(exc).__name__}: {exc}"
        stamp.update(last_attempt_at=when, last_attempt_head=head, last_error=error)
        if ok:
            stamp.update(last_ok_head=head, last_ok_at=when)
        _write_stamp(out, stamp)
        removed = prune_snapshots(out)
    return {"skipped": False, "ok": ok, "error": error, "head": head, "pruned": removed}


def _block(graphify: str | None, detach: bool) -> str:
    cmd = f'"{sys.executable}" "{Path(__file__).resolve()}" refresh "$_gfr"'
    if graphify:
        cmd += f' --graphify "{graphify}"'
    run = f'nohup {cmd} >>"{LOG}" 2>&1 </dev/null &' if detach else f"{cmd};"
    return (f"{MARKER_START}\n"
            "# Keeps graphify-out current however commits land: commit, merge (code_sync), rebase (marvin#691).\n"
            "# Detached, so git never waits on it. Installed by lib/graphify_freshness.py install-hooks.\n"
            'if [ "${GRAPHIFY_SKIP_HOOK:-0}" != "1" ] && [ "${1:-}" != "amend" ]; then\n'
            '    _gfr=$(git rev-parse --show-toplevel 2>/dev/null)\n'
            f'    [ -n "$_gfr" ] && [ -d "$_gfr/{OUT}" ] && {{ mkdir -p "{LOG.parent}"; {run} }}\n'
            "fi\n"
            f"{MARKER_END}\n")


def _strip(text: str, start: str, end: str) -> tuple[str, bool]:
    i = text.find(start)
    j = text.find(end, i) if i >= 0 else -1
    if i < 0 or j < 0:
        return text, False
    return text[:i] + text[j + len(end):].lstrip("\n"), True


def install_hooks(repo: Path, graphify: str | None = None, detach: bool = True) -> list[str]:
    """Idempotent. Puts our block in each of HOOKS, replacing graphify's own post-commit rebuild (one writer) and any
    older copy of ours, and keeps every other line already there (brain-map, version bump, ...)."""
    d = _hooks_dir(Path(repo))
    d.mkdir(parents=True, exist_ok=True)
    block = _block(graphify, detach)
    changed = []
    for name in HOOKS:
        p = d / name
        old = p.read_text() if p.exists() else "#!/bin/sh\n"
        text, _ = _strip(old, MARKER_START, MARKER_END)
        text, had_graphify = _strip(text, GRAPHIFY_START, GRAPHIFY_END)
        if not text.startswith("#!"):
            text = "#!/bin/sh\n" + text
        text = text.rstrip("\n") + "\n\n" + block
        if text != old:
            p.write_text(text)
            changed.append(name)
        p.chmod(p.stat().st_mode | 0o111)
    return changed


def _cli(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in ("refresh", "install-hooks", "check"):
        print(__doc__.strip().splitlines()[-3:], file=sys.stderr)
        return 2
    action, repo = argv[0], Path(argv[1]).expanduser()
    graphify = argv[argv.index("--graphify") + 1] if "--graphify" in argv else None
    if action == "refresh":
        r = refresh(repo, graphify=graphify)
        print(f"[graphify-freshness] {datetime.now().isoformat(timespec='seconds')} {json.dumps(r)}")
        return 0 if r.get("ok") is not False else 1
    if action == "install-hooks":
        print("updated: " + (", ".join(install_hooks(repo, graphify=graphify)) or "nothing (already installed)"))
        return 0
    print(json.dumps(check(repo), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
