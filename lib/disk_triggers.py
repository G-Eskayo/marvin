#!/usr/bin/env python3
"""Disk cleanup triggered by use, not once a day (marvin#765).

The daily sweep (cleanup_sweep.py) and its first aid already know what is safe to delete. They ran on a schedule, but
the space filled between runs: on 2026-10-29 the Mac mini had 12 GB free after a restart, with macOS's aerial wallpaper
writing 2.1 GB in under 4 hours, helpers' `curl` writing 8.6 GB in 9 minutes, and merged PRs' worktrees left in
~/Developer/<repo>-<n> where the sweep never looked. This module hangs the existing rules on the events that use the
space, so nothing here polls:

  preflight      before heavy work starts (helper-tab, so every lane line too; the merge gate has its own since #690):
                 below FLOOR_BYTES, reclaim() once, then go, or refuse in plain words. Same floor as #690.
  after-merge    the merge server fires it once per merge: every Mac removes worktrees whose PR merged (any clone's
                 `git worktree list`, so ~/Developer/<repo>-<n> and .claude/worktrees alike) and their Xcode
                 DerivedData. Kept: uncommitted or untracked work, a process inside, commits the merged PR lacks.
  aerial-watch   a launchd WatchPaths job on the aerial videos folder: keep the newest the moment it grows. Behind
                 config/disk_triggers.json `aerial_watch_trim`, off until the owner picks item 1's option on the PR.

Every trigger appends one line to LOG_PATH (what ran, what it freed, free space after), which the Health card
disk:activity reads on each Mac. Cost: one statvfs per pre-flight; after a merge, one `git worktree list` per clone,
one `gh pr list` per repo with worktrees, and one lsof.

    disk_triggers.py preflight --what "helper Seal Speak: #60"   # exit 0 = go, 1 = refused (message on stderr)
    disk_triggers.py after-merge                                  # this Mac and every other registered Mac
    disk_triggers.py aerial-watch                                 # the WatchPaths job (no-op while the flag is off)
    disk_triggers.py reclaim                                      # what the pre-flight runs below the floor
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cleanup_sweep as cs  # noqa: E402
import gh_env  # noqa: E402

MARVIN_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = MARVIN_ROOT / "config" / "disk_triggers.json"
LOG_PATH = Path.home() / ".claude" / "logs" / "disk-triggers.jsonl"
LOG_MAX_BYTES = 2 * 2**20
# The merge gate's floor (#690, dashboard/webhook-server/merge.js MIN_GATE_FREE_BYTES): one number for "too full to
# start", so a helper never starts work the gate would then refuse to merge.
FLOOR_BYTES = 5 * 2**30
STEP_MERGED_WORKTREES = "disk-clean-merged-worktrees"
MERGED_PR_LIMIT = 200
DERIVED_DATA_GRACE_S = 600   # a DerivedData folder written in the last 10 minutes may belong to a build still running
DU_TIMEOUT_S = 60

GB = lambda n: f"{n / 2**30:.1f} GB"  # noqa: E731
MIB = lambda n: f"{n // 2**20} MiB"  # noqa: E731


# ── the trigger log ─────────────────────────────────────────────────────────────────────────────────────────────

def free_bytes(path: Path | None = None) -> int | None:
    try:
        s = os.statvfs(path or Path.home())
        return s.f_bavail * s.f_frsize
    except OSError:
        return None


def record(trigger: str, freed: int, detail: str, now: datetime | None = None, **extra) -> None:
    """One line per trigger run. Never raises: a log that can't be written must not stop the cleanup it reports."""
    entry = {"ts": (now or datetime.now(timezone.utc)).isoformat(), "trigger": trigger, "freed_bytes": int(freed or 0),
             "free_after": free_bytes(), "detail": str(detail)[:300], **extra}
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_MAX_BYTES:   # keep the newest half, bounded forever
            lines = LOG_PATH.read_text(errors="replace").splitlines()
            LOG_PATH.write_text("\n".join(lines[len(lines) // 2:]) + "\n")
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def summarize(lines: list[str], since: datetime) -> dict:
    """{"freed_bytes", "by_trigger": {trigger: bytes}, "refused": [what]} for log lines at or after `since`."""
    out = {"freed_bytes": 0, "by_trigger": {}, "refused": []}
    for line in lines:
        try:
            e = json.loads(line)
            ts = datetime.fromisoformat(e["ts"])
        except (ValueError, KeyError, TypeError):
            continue
        if ts < since:
            continue
        freed = int(e.get("freed_bytes") or 0)
        if freed > 0:
            out["freed_bytes"] += freed
            out["by_trigger"][e["trigger"]] = out["by_trigger"].get(e["trigger"], 0) + freed
        if e.get("trigger") == "preflight" and e.get("ok") is False:
            out["refused"].append(str(e.get("what", "?")))
    return out


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


# ── pre-flight ──────────────────────────────────────────────────────────────────────────────────────────────────

def reclaim() -> dict:
    """Everything already ruled disposable, in one pass: the sweep's first aid (old aerial videos, disk_trim's
    allowlisted caches), merged PRs' worktrees on this Mac, old unused pytest temp folders (#866), and the download
    cache back under its cap. No rule of its own. Each part is independent: one breaking is reported and the others still run."""
    import download_cache
    parts = [("rebuildable", cs.clear_rebuildable),
             ("merged worktrees", lambda: clean_merged_worktrees()),
             ("pytest temp", lambda: cs.trim_pytest_temps()),
             ("download cache", lambda: download_cache.enforce_cap())]
    freed, notes = 0, []
    for label, fn in parts:
        try:
            r = fn() or {}
            n = r.get("freed_bytes", 0)
            n = n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else 0
            freed += n
            notes.append(f"{label} {MIB(n)}")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{label} failed: {type(exc).__name__}")
    return {"changed": freed > 0, "freed_bytes": freed, "detail": f"freed {MIB(freed)} ({', '.join(notes)})"}


def preflight(what: str, floor: int = FLOOR_BYTES, free: Callable[[], int | None] | None = None,
              reclaim: Callable[[], dict] | None = None) -> dict:
    """Before heavy work starts. Above the floor: go, touching nothing. Below it: reclaim once (no retry loop), then
    go if that was enough, else refuse with a message a person can act on. Free space that can't be read never blocks
    (as #690). Returns {"ok", "free_before", "free_after", "reclaimed", "message"}."""
    free = free or free_bytes
    reclaim = reclaim or globals()["reclaim"]
    before = free()
    if before is None or before >= floor:
        return {"ok": True, "free_before": before, "free_after": before, "reclaimed": None, "message": ""}
    try:
        r = reclaim() or {}
        detail, freed = str(r.get("detail") or "nothing to clear"), int(r.get("freed_bytes") or 0)
    except Exception as exc:  # noqa: BLE001 -- a broken reclaim is a refusal with the reason, never a crash
        detail, freed = f"cleanup failed: {type(exc).__name__}: {str(exc)[:120]}", 0
    after = free()
    ok = after is None or after >= floor
    message = "" if ok else (
        f"Not starting {what}: the disk has {GB(after)} free and work needs {GB(floor)}. "
        f"Cleanup already ran ({detail}). Free up space on this Mac (Health shows what is using it), then start it again.")
    record("preflight", freed, detail, what=what, ok=ok, free_before=before)
    return {"ok": ok, "free_before": before, "free_after": after, "reclaimed": detail, "message": message}


# ── after a merge ───────────────────────────────────────────────────────────────────────────────────────────────

def discover_clones() -> list[Path]:
    """Every main clone on this Mac: ~/.agents, each ~/Developer/<repo> whose `.git` is a folder (a worktree's is a
    file), and the clones behind the pipeline's and helpers' worktree roots. Found on disk, so a new repo needs no
    code change."""
    home = cs.HOME
    found: list[Path] = []
    cands = [home / ".agents"]
    dev = home / "Developer"
    if dev.is_dir():
        cands += sorted(dev.iterdir())
    for c in cands:
        if (c / ".git").is_dir() and c not in found:
            found.append(c)
    for root in cs.worktree_roots():
        for entry in sorted(root.iterdir()):
            r = cs._git(entry, "rev-parse", "--path-format=absolute", "--git-common-dir") if entry.is_dir() else None
            clone = Path(r.stdout.strip()).parent if r and r.returncode == 0 else None
            if clone and clone not in found:
                found.append(clone)
    return found


def _list_worktrees(clone: Path) -> list[dict]:
    """Linked worktrees of one clone (the main checkout is never listed), from git itself."""
    out = cs._git(clone, "worktree", "list", "--porcelain")
    if out.returncode != 0:
        return []
    items, cur = [], {}
    for line in out.stdout.splitlines() + [""]:
        if not line:
            if cur:
                items.append(cur)
            cur = {}
            continue
        key, _, val = line.partition(" ")
        cur[key] = val or True
    return [{"path": Path(w["worktree"]), "head": w.get("HEAD"), "branch": str(w["branch"]).removeprefix("refs/heads/"),
             "prunable": "prunable" in w}
            for w in items[1:] if isinstance(w.get("branch"), str)]


def _repo_of(clone: Path) -> str | None:
    m = cs.GITHUB_REPO_RE.search(cs._git(clone, "remote", "get-url", "origin").stdout.strip())
    return m.group(1) if m else None


def _default_merged(repo: str) -> dict[str, list[str]]:
    """{branch: [head SHAs of its merged PRs]} for the repo's recent merged PRs. Raises on any gh failure, so an
    outage never reads as "nothing merged" (or worse, as permission). Runs with gh_env's GH_TOKEN: over ssh or from
    launchd the keychain is locked and plain gh answers 401 (#866)."""
    r = gh_env.run(["gh", "pr", "list", "--repo", repo, "--state", "merged", "--limit", str(MERGED_PR_LIMIT),
                    "--json", "headRefName,headRefOid"])
    out: dict[str, list[str]] = {}
    for pr in json.loads(r.stdout or "[]"):
        out.setdefault(pr["headRefName"], []).append(pr["headRefOid"])
    return out


def _size_bytes(path: Path) -> int:
    import disk_ledger
    kb = disk_ledger.du_kb(path, timeout=DU_TIMEOUT_S)
    return kb * 1024 if isinstance(kb, int) else 0


def _derived_data_for(worktree: Path, dd_root: Path) -> list[Path]:
    """Xcode DerivedData folders whose workspace lives inside `worktree` (their info.plist says where)."""
    if not dd_root.is_dir():
        return []
    wt = str(worktree.resolve())
    hits = []
    for d in dd_root.iterdir():
        try:
            with open(d / "info.plist", "rb") as f:
                ws = str(plistlib.load(f).get("WorkspacePath") or "")
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
        if ws and (ws == wt or ws.startswith(wt + "/") or str(Path(ws).resolve()).startswith(wt + "/")):
            hits.append(d)
    return hits


def decide_merged(wt: dict, merged_heads: list[str], clone: Path, cwds: set[str]) -> tuple[str, str]:
    """("remove" | "keep", reason) for a worktree whose branch has a merged PR."""
    path = Path(wt["path"])
    if cs._in_use(path, cwds):
        return "keep", "a process is working inside it"
    status = cs._git(path, "status", "--porcelain")
    if status.returncode != 0:
        return "keep", "git could not read it"
    if status.stdout.strip():
        return "keep", "has uncommitted or untracked work"
    head = wt.get("head")
    if head in merged_heads:
        return "remove", "its PR merged"
    for oid in merged_heads:   # HEAD behind the merged head is fine; commits after it are not in the PR
        if cs._git(clone, "merge-base", "--is-ancestor", str(head), oid).returncode == 0:
            return "remove", "its PR merged"
    return "keep", "has commits not in the merged PR"


def clean_merged_worktrees(clones: list[Path] | None = None, merged: Callable[[str], dict] | None = None,
                           cwds: set[str] | None = None, derived_data: Path | None = None) -> dict:
    """Remove the worktrees of merged PRs on this Mac, plus their Xcode build products. Lossless like the sweep:
    plain `git worktree remove` (git refuses anything uncommitted or untracked) and the branch stays, so every commit
    stays reachable. Returns {"removed", "kept", "freed_bytes", "github_errors": {repo: reason}}."""
    clones = discover_clones() if clones is None else clones
    merged = merged or _default_merged
    cwds = cs._cwds_in_use() if cwds is None else cwds
    dd_root = derived_data or (cs.HOME / "Library" / "Developer" / "Xcode" / "DerivedData")
    removed, kept, freed = [], [], 0
    by_repo: dict[str, dict | Exception] = {}
    for clone in clones:
        wts = _list_worktrees(clone)
        if any(w["prunable"] for w in wts):
            cs._git(clone, "worktree", "prune")   # folder already gone: only git's record is left
        wts = [w for w in wts if not w["prunable"]]
        repo = _repo_of(clone) if wts else None
        if not repo:
            continue
        if repo not in by_repo:
            try:
                by_repo[repo] = merged(repo)
            except Exception as exc:  # noqa: BLE001 -- GitHub failing must never read as "merged"
                by_repo[repo] = exc
        known = by_repo[repo]
        for wt in wts:
            if isinstance(known, Exception):
                kept.append({"path": str(wt["path"]), "reason": f"could not check GitHub: {str(known)[:300]}"})
                continue
            heads = known.get(wt["branch"])
            if not heads:
                continue   # its PR hasn't merged: not this trigger's business
            action, reason = decide_merged(wt, heads, clone, cwds)
            if action != "remove":
                kept.append({"path": str(wt["path"]), "reason": reason})
                continue
            size = _size_bytes(wt["path"])
            dds = _derived_data_for(wt["path"], dd_root)
            if cs._git(clone, "worktree", "remove", str(wt["path"])).returncode != 0:
                kept.append({"path": str(wt["path"]), "reason": "git refused to remove it"})
                continue
            freed += size
            for d in dds:
                if time.time() - d.stat().st_mtime < DERIVED_DATA_GRACE_S or cs._in_use(d, cwds):
                    continue
                n = _size_bytes(d)
                shutil.rmtree(d, ignore_errors=True)
                freed += n
            removed.append({"path": str(wt["path"]), "branch": wt["branch"], "reason": reason,
                            "derived_data": [d.name for d in dds]})
    errors = {repo: str(v)[:300] for repo, v in by_repo.items() if isinstance(v, Exception)}
    return {"removed": removed, "kept": kept, "freed_bytes": freed, "github_errors": errors}


def merged_worktrees_step() -> dict:
    """The first-aid step (purpose_metrics FIRST_AID), so the merge server reaches every Mac over the same ssh path."""
    r = clean_merged_worktrees()
    n, freed = len(r["removed"]), r["freed_bytes"]
    detail = f"removed {n} worktree(s) of merged PRs, freed {MIB(freed)}"
    errors = r.get("github_errors") or {}
    blind = [k for k in r["kept"] if k["reason"].startswith("could not check GitHub")]
    looked = [k for k in r["kept"] if not k["reason"].startswith("could not check GitHub")]
    if blind:   # one reason per repo, said once, not the same 401 repeated for each of 31 worktrees (#866)
        detail += f"; kept {len(blind)} unchecked, could not check GitHub (" + "; ".join(
            f"{repo}: {why}" for repo, why in errors.items()) + ")"
    if looked:
        detail += f"; kept {len(looked)} (" + "; ".join(f"{Path(k['path']).name}: {k['reason']}" for k in looked[:5]) + ")"
    if n or r["kept"]:
        record("after-merge", freed, detail, removed=[x["path"] for x in r["removed"]])
    return {"changed": n > 0, "freed_bytes": freed, "detail": detail}


def after_merge(everywhere: Callable[[str], list[dict]] | None = None) -> list[dict]:
    if everywhere is None:
        import purpose_metrics
        everywhere = purpose_metrics.first_aid_everywhere
    return everywhere(STEP_MERGED_WORKTREES)


# ── aerial videos (item 1: the owner's choice; this is the WatchPaths option, off until chosen) ─────────────────

def aerial_watch(config: dict | None = None) -> dict:
    cfg = load_config() if config is None else config
    if cfg.get("aerial_watch_trim") is not True:
        return {"ran": False, "freed_bytes": 0, "detail": "off (config/disk_triggers.json aerial_watch_trim)"}
    freed = cs.trim_aerial_videos()
    if freed:
        record("aerial-watch", freed, f"removed old aerial videos, kept the newest ({MIB(freed)})")
    return {"ran": True, "freed_bytes": freed, "detail": f"freed {MIB(freed)}"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="disk_triggers.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preflight")
    p.add_argument("--what", required=True, help="what is about to start, named in a refusal")
    sub.add_parser("after-merge")
    sub.add_parser("aerial-watch")
    sub.add_parser("reclaim")
    a = ap.parse_args(argv)
    if a.cmd == "preflight":
        r = preflight(a.what)
        if not r["ok"]:
            print(r["message"], file=sys.stderr)
        return 0 if r["ok"] else 1
    if a.cmd == "after-merge":
        print(json.dumps(after_merge()))
    elif a.cmd == "aerial-watch":
        print(json.dumps(aerial_watch()))
    elif a.cmd == "reclaim":
        print(json.dumps(reclaim()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
