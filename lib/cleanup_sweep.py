#!/usr/bin/env python3
"""Daily cleanup sweep for the MR pipeline (G-Eskayo/marvin#9), same shape
as cron_health.py -- silent failure is the recurring real problem in this
codebase, so every run writes what it did to OUTPUT_PATH. Scheduled daily on
both machines by config/launchd/com.marvin.cleanup-sweep.plist.

Two independent sweeps:

- **Stale claims**: a `claimed:*` issue whose `updatedAt` hasn't moved in
  over STALE_THRESHOLD_HOURS (a machine crashed, slept, or stalled) gets
  released via ticket_claim.release() -- the existing primitive, not new
  release machinery.
- **Resolved worktrees**: every worktree under sandbox_orchestration's
  WORKTREES_ROOT, for every project (the repo is read from the worktree's own
  clone, not assumed), is decided by decide_worktree(): removed once its PR is
  merged or closed, or when it is an empty attempt (no PR, no commits, no
  changes) older than EMPTY_MIN_AGE_HOURS whose issue is not claimed; kept
  while its PR is open or its ticket is running; and reported for a person to
  look at when it holds uncommitted work or commits with no PR. Found
  2026-10-06: nothing removed a resolved ticket's worktree (run_ticket never
  did, and this sweep was never scheduled and only knew G-Eskayo/marvin), so
  39 GiB of them filled the mac-mini to 94%.

- **Builder simulators** (ADR 0065: disposable once their ticket is done): a
  simulator named for a ticket ("Seal-118") is deleted once that number is
  closed in every project, and a leftover screenshot-capture simulator
  ("marvin-<hash>") once it is shut down. Xcode's own devices are never
  touched; anything the sweep can't tie to a ticket is listed for a person.
  Found 2026-10-14: Seal-118 ran for four days after its PR merged.

- **Leftover edits** (#629): a worktree with uncommitted edits or unpushed commits used to be kept as "needs a
  look" forever; nobody looked, and on 2026-10-24 all 43 pipeline worktrees (11.8 GiB) were in that state, with
  9.5 GiB more of helper worktrees under `<repo>/.claude/worktrees` that the sweep didn't know about. Gil's rule:
  back up, then remove. Once idle BACKUP_MIN_AGE_HOURS, with no claim, no open PR and no process inside, every edit
  is committed and pushed to `backup/<branch>-<date>` on origin; only when the remote ref matches is the folder
  removed. A folder with no git record is listed, never deleted.

Removal is lossless by construction: plain `git worktree remove` (never
--force, so git refuses if anything uncommitted or untracked is there) and the
branch is kept, so every commit stays reachable. Ignored build output
(.build, node_modules) is what the removal actually frees.
"""
from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ticket_claim  # noqa: E402
from sandbox_orchestration import WORKTREES_ROOT  # noqa: E402

OUTPUT_PATH = Path.home() / ".claude" / "logs" / "mr-pipeline-sweep.md"
LOCK_PATH = Path.home() / ".claude" / "logs" / "cleanup-sweep.lock"
STALE_THRESHOLD_HOURS = 24
EMPTY_MIN_AGE_HOURS = 24
BACKUP_MIN_AGE_HOURS = 48  # leftover edits untouched this long are backed up and removed (#629)
BACKUP_MAX_FILE_BYTES = 50 * 2**20    # bigger leftovers (a model, a recording) are not committed: they'd grow the
BACKUP_MAX_TOTAL_BYTES = 200 * 2**20  # clone's .git and fail GitHub's 100 MB limit; kept for a person instead
MARVIN_ROOT = Path(__file__).resolve().parent.parent
PUSH_GUARD = MARVIN_ROOT / "bin" / "pre-push-guard"
PUSH_GUARD_SHARED = MARVIN_ROOT / "config" / "push-guard" / "patterns.txt"
HOME = Path.home()  # one seam: tests point it (and WORKTREES_ROOT) at a temp dir (conftest)
AERIAL_SUBPATH = Path("Library") / "Application Support" / "com.apple.wallpaper" / "aerials" / "videos"
ISSUE_NUMBER_RE = re.compile(r"#(\d+)$|^ticket/(\d+)(?:-|$)")  # pipeline/…#N, or ticket/<n>-<slug> (#226)
GITHUB_REPO_RE = re.compile(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$")


def _default_list_claimed_open_issues() -> list[dict]:
    result = subprocess.run(
        ["gh", "issue", "list", "--repo", ticket_claim.REPO, "--state", "open",
         "--json", "number,labels,updatedAt"],
        capture_output=True, text=True, check=True,
    )
    issues = json.loads(result.stdout)
    return [
        issue for issue in issues
        if any(label["name"].startswith("claimed:") for label in issue.get("labels", []))
    ]


def _git(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True)


def worktree_roots() -> list[Path]:
    """Where worktrees live: the pipeline's root plus every repo's helper worktrees (`.claude/worktrees` under
    ~/Developer/* and ~/.agents), found on disk so a new repo is covered with no code change (#629)."""
    home = HOME
    roots = [WORKTREES_ROOT, home / ".agents" / ".claude" / "worktrees"]
    dev = home / "Developer"
    if dev.is_dir():
        roots += sorted(d / ".claude" / "worktrees" for d in dev.iterdir() if d.is_dir())
    return [r for r in roots if r.is_dir()]


def _cwds_in_use() -> set[str]:
    """Working directories of every running process (one lsof call), so a worktree a session is inside is left
    alone. lsof missing or failing returns an empty set; the 48 h idle rule still guards live work."""
    try:
        out = subprocess.run(["/usr/sbin/lsof", "-n", "-d", "cwd", "-Fn"], capture_output=True, text=True,
                             timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line[1:] for line in out.splitlines() if line.startswith("n/")}


def _in_use(path: Path, cwds: set[str]) -> bool:
    p = str(Path(path).resolve())
    return any(c == p or c.startswith(p + "/") for c in cwds)


def _default_list_worktrees() -> list[dict]:
    """One dict per git worktree under worktree_roots(): path, branch, the clone
    it belongs to, that clone's GitHub repo (None if not on GitHub), commits
    ahead of origin/main, whether anything is uncommitted, age in hours, and
    whether a process is inside it. A folder git doesn't recognize comes back
    with "broken": True."""
    out = []
    cwds = _cwds_in_use()
    for root in worktree_roots():
        out += _list_root(root, cwds)
    return out


def _list_root(root: Path, cwds: set[str]) -> list[dict]:
    out = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        branch = _git(entry, "branch", "--show-current")
        common = _git(entry, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if common.returncode != 0:
            if (entry / ".git").exists():
                out.append({"path": entry, "broken": True})
            continue
        if branch.returncode != 0 or not branch.stdout.strip():
            continue
        clone = Path(common.stdout.strip()).parent
        url = _git(clone, "remote", "get-url", "origin").stdout.strip()
        match = GITHUB_REPO_RE.search(url)
        ahead = _git(entry, "rev-list", "--count", "origin/main..HEAD").stdout.strip()
        out.append({
            "path": entry,
            "branch": branch.stdout.strip(),
            "clone": clone,
            "repo": match.group(1) if match else None,
            "ahead": int(ahead) if ahead.isdigit() else None,
            "dirty": bool(_git(entry, "status", "--porcelain").stdout.strip()),
            "age_hours": (time.time() - entry.stat().st_mtime) / 3600,
            "in_use": _in_use(entry, cwds),
        })
    return out


def _default_pr_state(repo: str, branch: str) -> str | None:
    """MERGED / CLOSED / OPEN for the newest PR from this branch, None if there is none.
    Raises on a gh failure so an outage never reads as "no PR"."""
    result = subprocess.run(
        ["gh", "pr", "list", "--repo", repo, "--head", branch, "--state", "all",
         "--json", "state", "--jq", ".[0].state"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip() or None


def _default_is_claimed(repo: str, number: int) -> bool:
    result = subprocess.run(
        ["gh", "issue", "view", str(number), "--repo", repo, "--json", "labels,state"],
        capture_output=True, text=True, check=True,
    )
    issue = json.loads(result.stdout)
    return issue.get("state") == "OPEN" and any(l["name"].startswith("claimed:") for l in issue.get("labels", []))


def _default_remove_worktree(wt: dict) -> bool:
    """Lossless removal; False when git refuses (something uncommitted or untracked is there)."""
    return _git(Path(wt["clone"]), "worktree", "remove", str(wt["path"])).returncode == 0


def _push_guard_allows(path: Path, head: str, ref: str) -> bool:
    """ADR 0071 guard on exactly what the backup push would publish, run directly so a repo without the hook
    (clarity-captions) is still checked, always with MARVIN's shared patterns. Missing guard = refuse."""
    if not PUSH_GUARD.exists():
        return False
    env = {**os.environ, "PUSH_GUARD_SHARED": str(PUSH_GUARD_SHARED)}
    r = subprocess.run([str(PUSH_GUARD), "origin"], cwd=path, capture_output=True, text=True, env=env,
                       input=f"HEAD {head} refs/heads/{ref} {'0' * 40}\n")
    return r.returncode == 0


def backup_worktree(wt: dict, today: str | None = None,
                    guard: Callable[[Path, str, str], bool] | None = None) -> str | None:
    """Commit every leftover edit (ignored build output stays out) and push the worktree's HEAD to
    `backup/<branch>-<today>` on origin. Returns the ref only when origin's copy matches HEAD; None on any failure,
    so the caller keeps the folder. The push guard runs first (it is the check that matters here); git hooks
    are then skipped (--no-verify), since the guard already ran and the commit hooks are for shipping, not saving."""
    path = Path(wt["path"])
    today = today or datetime.now(timezone.utc).strftime("%Y%m%d")
    ref = f"backup/{wt['branch']}-{today}"
    if _git(path, "add", "-A").returncode != 0:
        return None
    staged = _git(path, "diff", "--cached", "--name-only", "-z").stdout.split("\0")
    sizes = [(path / f).stat().st_size for f in staged if f and (path / f).is_file()]
    if sizes and (max(sizes) > BACKUP_MAX_FILE_BYTES or sum(sizes) > BACKUP_MAX_TOTAL_BYTES):
        _git(path, "reset", "-q")  # leave the edits exactly as they were
        return None
    if _git(path, "diff", "--cached", "--quiet").returncode != 0:
        msg = f"WIP backup by the cleanup sweep (#629): leftover edits from {path.name}"
        commit = _git(path, "-c", "user.name=MARVIN cleanup sweep", "-c", "user.email=marvin@localhost",
                      "commit", "-q", "--no-verify", "-m", msg)
        if commit.returncode != 0:
            return None
    head = _git(path, "rev-parse", "HEAD").stdout.strip()
    if not (guard or _push_guard_allows)(path, head, ref):
        return None  # personal data, a secret or a transcript: the commit stays local, nothing is published
    if _git(path, "push", "-q", "--no-verify", "origin", f"HEAD:refs/heads/{ref}").returncode != 0:
        return None
    remote = _git(path, "ls-remote", "origin", f"refs/heads/{ref}").stdout.split()
    return ref if head and remote and remote[0] == head else None


def trim_aerial_videos(folder: Path | None = None) -> int:
    """macOS's aerial screen saver downloads a new 250-620 MB video almost daily and never deletes old ones (12 GiB
    on the Mini, 2026-10-24). Keep only the newest (the one showing); return bytes freed. Disposable (ADR 0065):
    Apple re-downloads any it needs."""
    folder = folder or HOME / AERIAL_SUBPATH
    if not folder.is_dir():
        return 0
    videos = sorted(folder.glob("*.mov"), key=lambda p: p.stat().st_mtime, reverse=True)
    freed = 0
    for old in videos[1:]:
        freed += old.stat().st_size
        old.unlink()
    return freed


def drop_build_output(worktree: Path, rel_paths: list[str]) -> list[str]:
    """Remove regenerable build output (SwiftPM .build, node_modules) from a pipeline worktree once a ticket run
    ends; returns what was removed. Only directories inside the worktree that git ignores are removed, and an
    untracked symlink (node_modules linked to a shared cache) is unlinked, never followed, so work is never lost."""
    worktree = Path(worktree)
    root = worktree.resolve()
    removed = []
    for rel in rel_paths:
        if Path(rel).is_absolute() or ".." in Path(rel).parts:
            continue
        p = worktree / rel
        if not (p.is_symlink() or p.is_dir()) or not p.parent.resolve().is_relative_to(root):
            continue
        if p.is_symlink():
            # a "node_modules/" ignore rule matches directories only, so git sees the link as untracked, not ignored
            if _git(worktree, "ls-files", "--", rel).stdout.strip():
                continue
            p.unlink()
        elif _git(worktree, "check-ignore", "-q", rel).returncode != 0:
            continue
        else:
            shutil.rmtree(p)
        removed.append(rel)
    return removed


def _extract_issue_number(branch: str) -> int | None:
    match = ISSUE_NUMBER_RE.search(branch)
    return int(match.group(1) or match.group(2)) if match else None


def find_stale_claims(
    threshold_hours: float = STALE_THRESHOLD_HOURS,
    list_claimed_open_issues: Callable[[], list[dict]] | None = None,
    now: datetime | None = None,
) -> list[dict]:
    list_claimed_open_issues = list_claimed_open_issues or _default_list_claimed_open_issues
    now = now or datetime.now(timezone.utc)

    stale = []
    for issue in list_claimed_open_issues():
        updated_at = datetime.fromisoformat(issue["updatedAt"].replace("Z", "+00:00"))
        age_hours = (now - updated_at).total_seconds() / 3600
        if age_hours <= threshold_hours:
            continue
        for label in issue["labels"]:
            if label["name"].startswith("claimed:"):
                stale.append({
                    "issue_number": issue["number"],
                    "machine_id": label["name"].removeprefix("claimed:"),
                    "age_hours": age_hours,
                })
    return stale


def sweep_stale_claims(
    threshold_hours: float = STALE_THRESHOLD_HOURS,
    list_claimed_open_issues: Callable[[], list[dict]] | None = None,
    release: Callable[[int, str], None] | None = None,
    now: datetime | None = None,
) -> list[dict]:
    release = release or ticket_claim.release
    stale = find_stale_claims(threshold_hours, list_claimed_open_issues, now)
    for entry in stale:
        release(entry["issue_number"], entry["machine_id"])
    return stale


def decide_worktree(wt: dict, pr_state: str | None, claimed: bool) -> tuple[str, str]:
    """("remove" | "backup" | "keep" | "review", reason). "backup" = push its
    leftover work to a backup branch, then remove (#629). "review" = kept for
    now and listed in the log (recent leftover work, or an open PR's)."""
    if wt.get("repo") is None:
        return "keep", "not a GitHub clone the sweep knows how to check"
    if wt.get("in_use"):
        return "keep", "a process is working inside it"
    if claimed:
        return "keep", "its ticket is claimed (running)"
    if wt.get("dirty"):
        if pr_state == "OPEN" or wt.get("age_hours", 0) < BACKUP_MIN_AGE_HOURS:
            return "review", "has uncommitted work"
        return "backup", "has uncommitted work"
    if pr_state in ("MERGED", "CLOSED"):
        return "remove", f"PR {pr_state.lower()}"
    if pr_state == "OPEN":
        return "keep", "PR open"
    if wt.get("ahead"):
        if wt.get("age_hours", 0) < BACKUP_MIN_AGE_HOURS:
            return "review", f"{wt['ahead']} commit(s) with no PR"
        return "backup", f"{wt['ahead']} commit(s) with no PR"
    if wt.get("age_hours", 0) < EMPTY_MIN_AGE_HOURS:
        return "keep", "new, may be a ticket starting"
    return "remove", "empty attempt (no PR, no commits, no changes)"


def sweep_worktrees(
    list_worktrees: Callable[[], list[dict]] | None = None,
    pr_state: Callable[[str, str], str | None] | None = None,
    is_claimed: Callable[[str, int], bool] | None = None,
    remove_worktree: Callable[[dict], bool] | None = None,
    backup: Callable[[dict], str | None] | None = None,
) -> dict:
    list_worktrees = list_worktrees or _default_list_worktrees
    pr_state = pr_state or _default_pr_state
    is_claimed = is_claimed or _default_is_claimed
    remove_worktree = remove_worktree or _default_remove_worktree
    backup = backup or backup_worktree

    removed, review = [], []
    for wt in list_worktrees():
        if wt.get("broken"):
            review.append({**wt, "reason": "folder has no git record (its worktree metadata is gone); not deleted"})
            continue
        repo, number = wt.get("repo"), _extract_issue_number(wt["branch"])
        try:
            state = pr_state(repo, wt["branch"]) if repo else None
            claimed = bool(repo and number is not None and is_claimed(repo, number))
        except Exception as exc:  # a GitHub failure must never read as "no PR"
            review.append({**wt, "reason": f"could not check GitHub: {str(exc)[:120]}"})
            continue
        action, reason = decide_worktree(wt, state, claimed)
        if action == "backup":
            ref = backup(wt)
            if not ref:
                review.append({**wt, "reason": f"{reason}; backup failed, kept"})
            elif remove_worktree(wt):
                removed.append({**wt, "reason": f"{reason}, backed up to {ref}"})
            else:
                review.append({**wt, "reason": f"{reason}, backed up to {ref}, but git refused to remove it"})
        elif action == "remove":
            if remove_worktree(wt):
                removed.append({**wt, "reason": reason})
            else:
                review.append({**wt, "reason": f"{reason}, but git refused to remove it"})
        elif action == "review":
            review.append({**wt, "reason": reason})
    return {"removed": removed, "review": review}


SIM_TICKET_RE = re.compile(r"[-_ #](\d+)$")  # "Seal-118", "clarity_140", "build #7"
CAPTURE_SIM_RE = re.compile(r"^marvin-[0-9a-f]{8}$")  # simulator_capture._device_name


def _simctl_json(*args: str) -> dict:
    if shutil.which("xcrun") is None:
        return {}   # no Xcode (e.g. mac-mini-2012 on Linux): no simulators, nothing to sweep
    out = subprocess.run(["xcrun", "simctl", "list", *args, "--json"], capture_output=True, text=True, timeout=60)
    return json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else {}


def _default_list_simulators() -> list[dict]:
    devices = _simctl_json("devices").get("devices", {})
    return [{"name": d["name"], "udid": d["udid"], "state": d.get("state", "")} for ds in devices.values() for d in ds]


def _default_stock_names() -> set[str]:
    return {t["name"] for t in _simctl_json("devicetypes").get("devicetypes", [])}


def _default_delete_simulator(sim: dict) -> bool:
    subprocess.run(["xcrun", "simctl", "shutdown", sim["udid"]], capture_output=True, timeout=60)
    return subprocess.run(["xcrun", "simctl", "delete", sim["udid"]], capture_output=True, timeout=120).returncode == 0


def _default_issue_state(repo: str, number: int) -> str | None:
    """OPEN / CLOSED, None when the repo has no such issue. Raises on any other gh failure."""
    result = subprocess.run(["gh", "issue", "view", str(number), "--repo", repo, "--json", "state", "-q", ".state"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        if "Could not resolve" in result.stderr or "not found" in result.stderr.lower():
            return None
        raise RuntimeError(result.stderr.strip()[:200])
    return result.stdout.strip() or None


def _ticket_open_anywhere(number: int, repos: list[str] | None = None,
                          issue_state: Callable[[str, int], str | None] | None = None) -> bool:
    """A simulator name carries a number, not a repo, so the ticket counts as done only when no project has it
    open, and at least one project has it closed. A number no project knows is treated as open (leave it)."""
    if repos is None:
        import project_profile as pp
        repos = [p["repo"] for p in pp.all_profiles()]
    issue_state = issue_state or _default_issue_state
    states = [issue_state(repo, number) for repo in repos]
    return "OPEN" in states or not any(states)


def decide_simulator(sim: dict, stock: set[str], ticket_open: Callable[[int], bool]) -> tuple[str, str]:
    """("remove" | "keep" | "review", reason)."""
    name = sim["name"]
    if name in stock:
        return "keep", "one of Xcode's own devices"
    if CAPTURE_SIM_RE.match(name):
        if sim.get("state") == "Booted":
            return "keep", "a screenshot capture may be using it"
        return "remove", "leftover screenshot-capture simulator"
    match = SIM_TICKET_RE.search(name)
    if not match:
        return "review", "can't tie it to a ticket"
    number = int(match.group(1))
    if ticket_open(number):
        return "keep", f"ticket #{number} is still open"
    return "remove", f"ticket #{number} is closed in every project"


def sweep_simulators(
    list_simulators: Callable[[], list[dict]] | None = None,
    stock_names: Callable[[], set[str]] | None = None,
    ticket_open: Callable[[int], bool] | None = None,
    delete_simulator: Callable[[dict], bool] | None = None,
) -> dict:
    if list_simulators is None and shutil.which("xcrun") is None:
        return {"removed": [], "review": []}   # no Xcode on this machine (mac-mini-2012): no simulators exist
    sims = (list_simulators or _default_list_simulators)()
    stock = (stock_names or _default_stock_names)()
    if not stock:  # without it, "iPhone 17" looks like ticket #17: delete nothing
        return {"removed": [], "review": [{"name": "(all simulators)", "udid": "", "reason": "couldn't read Xcode's device list, so none were checked"}]}
    lookup = ticket_open or _ticket_open_anywhere
    known: dict[int, bool] = {}
    ticket_open = lambda n: known[n] if n in known else known.setdefault(n, lookup(n))  # noqa: E731
    delete_simulator = delete_simulator or _default_delete_simulator

    removed, review = [], []
    for sim in sims:
        try:
            action, reason = decide_simulator(sim, stock, ticket_open)
        except Exception as exc:  # a GitHub failure must never read as "ticket closed"
            review.append({**sim, "reason": f"could not check GitHub: {str(exc)[:120]}"})
            continue
        if action == "remove":
            if delete_simulator(sim):
                removed.append({**sim, "reason": reason})
            else:
                review.append({**sim, "reason": f"{reason}, but simctl refused to delete it"})
        elif action == "review":
            review.append({**sim, "reason": reason})
    return {"removed": removed, "review": review}


def _default_compress_transcripts() -> dict | None:
    """Transcripts are kept forever (ADR 0065: irreplaceable), so the cold ones are compressed losslessly."""
    try:
        import cold_compress
        return cold_compress.compress_transcripts()
    except Exception as exc:  # noqa: BLE001 -- never stops the sweep
        return {"compressed": [], "failed": [], "saved_kb": 0, "skipped": f"failed: {str(exc)[:120]}"}


def _write_log(stale: list[dict], worktrees: dict, simulators: dict | None = None,
               compressed: dict | None = None, aerials_freed: int = 0) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    lines = [
        f"- Released stale claim: issue #{e['issue_number']} held by `{e['machine_id']}`, "
        f"{e['age_hours']:.1f}h since last update"
        for e in stale
    ]
    lines += [f"- Removed worktree ({w['reason']}): `{w['path']}`" for w in worktrees["removed"]]
    lines += [f"- Needs a look, kept ({w['reason']}): `{w['path']}`" for w in worktrees["review"]]
    sims = simulators or {"removed": [], "review": []}
    lines += [f"- Removed simulator ({s['reason']}): `{s['name']}`" for s in sims["removed"]]
    lines += [f"- Simulator needs a look, kept ({s['reason']}): `{s['name']}`" for s in sims["review"]]
    if compressed and compressed.get("skipped"):
        lines.append(f"- Transcript compression skipped: {compressed['skipped']}")
    elif compressed and compressed["compressed"]:
        lines.append(f"- Compressed {len(compressed['compressed'])} cold transcript(s), "
                     f"{compressed['saved_kb'] // 1024} MiB saved (same files, same paths)")
    lines += [f"- Transcript not compressed ({f['reason']}): `{f['path']}`" for f in (compressed or {}).get("failed", [])]
    if aerials_freed:
        lines.append(f"- Removed old aerial screen-saver videos: {aerials_freed // 2**20} MiB (kept the newest)")
    body = "\n".join(lines) + "\n" if lines else "Nothing to clean up: no stale claims, no resolved worktrees.\n"
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = OUTPUT_PATH.read_text() if OUTPUT_PATH.exists() else "# MR pipeline cleanup sweep\n\n"
    OUTPUT_PATH.write_text(existing + f"\n## {timestamp}\n\n{body}")


OUTCOME_CHECK_MACHINE = "mac-mini-1"  # one Mac measures and comments, so the two never race (the primary host)


def _default_outcome_check() -> None:
    """Purpose metrics whose check date has passed get measured and recorded on their ticket (marvin#304), and the
    top pending suggestions go through ticket promotion (marvin#305)."""
    try:
        import machine_profile
        if machine_profile.registry_id() != OUTCOME_CHECK_MACHINE:
            return
        import purpose_metrics
        purpose_metrics.run()
    except Exception as exc:  # noqa: BLE001 -- never let it stop the sweep; retried tomorrow
        print(f"[cleanup-sweep] outcome check failed: {exc}", file=sys.stderr)
    try:
        # Ticket promotion: the consumer the analysts' suggestions never had (marvin#305), top few per day.
        import output_contracts
        output_contracts.run_promotion()
    except Exception as exc:  # noqa: BLE001
        print(f"[cleanup-sweep] ticket promotion failed: {exc}", file=sys.stderr)


def run_daily_sweep(
    list_claimed_open_issues: Callable[[], list[dict]] | None = None,
    list_worktrees: Callable[[], list[dict]] | None = None,
    pr_state: Callable[[str, str], str | None] | None = None,
    is_claimed: Callable[[str, int], bool] | None = None,
    release: Callable[[int, str], None] | None = None,
    remove_worktree: Callable[[dict], bool] | None = None,
    threshold_hours: float = STALE_THRESHOLD_HOURS,
    now: datetime | None = None,
) -> dict:
    """Cron entry point. Runs sweeps (claims, worktrees, disk ledger, disk trim),
    logs what was removed/released/kept for review (same visibility standard as
    cron_health.py), returns a summary."""
    stale = sweep_stale_claims(threshold_hours, list_claimed_open_issues, release, now)
    worktrees = sweep_worktrees(list_worktrees, pr_state, is_claimed, remove_worktree)
    try:
        simulators = sweep_simulators()
    except Exception as exc:  # noqa: BLE001 -- e.g. no Xcode on this machine; never stops the sweep
        simulators = {"removed": [], "review": [{"name": "(all simulators)", "reason": f"sweep failed: {str(exc)[:120]}"}]}

    # Disk ledger and trim (log separately via their own functions)
    try:
        import disk_ledger as dl  # noqa: E402
        dl.run_daily_ledger()
    except Exception:
        pass

    try:
        import disk_trim as dt  # noqa: E402
        dt.trim_with_logging(dry_run=False)
    except Exception:
        pass

    _default_outcome_check()

    compressed = _default_compress_transcripts()

    try:
        aerials_freed = trim_aerial_videos()
    except OSError:
        aerials_freed = 0

    _write_log(stale, worktrees, simulators, compressed, aerials_freed)
    return {"stale_claims_released": len(stale), "worktrees_removed": len(worktrees["removed"]),
            "worktrees_for_review": len(worktrees["review"]), "simulators_removed": len(simulators["removed"])}


def clear_rebuildable() -> dict:
    """First aid for a nearly full disk (2026-10-28: macOS's aerial wallpaper refilled the Mac mini between daily
    sweeps, 3-8 GB a day, and two Approves were refused). Runs only the trims this sweep already makes on disposable,
    rebuildable files, through the same functions: old aerial videos (trim_aerial_videos, keep the newest) and
    disk_trim's allowlisted caches (deny-first, and only below its own free-space floor). No rule of its own, and none
    of the other sweeps (claims, worktrees, simulators). Single flight with the daily sweep (same lock): while that
    runs, this returns at once and touches nothing. Called through purpose_metrics.FIRST_AID "disk-clear-rebuildable"
    by the merge gate's disk check and the health check's low-disk result. Logged to OUTPUT_PATH when it freed
    anything. Returns {"changed", "freed_bytes", "detail"}."""
    import fcntl
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return {"changed": False, "freed_bytes": 0, "detail": "the cleanup sweep is already running on this Mac"}
        notes = []
        try:
            aerials = trim_aerial_videos()
        except OSError as exc:
            aerials, _ = 0, notes.append(f"aerial videos failed: {type(exc).__name__}")
        caches = 0
        try:
            import disk_trim
            r = disk_trim.trim_with_logging(dry_run=False)
            kb = r.get("total_kb_freed", 0) if isinstance(r, dict) else 0
            caches = kb * 1024 if isinstance(kb, int) and not isinstance(kb, bool) and kb > 0 else 0
        except Exception as exc:  # noqa: BLE001 -- a broken cache trim must not stop the video trim's result
            notes.append(f"caches failed: {type(exc).__name__}")
    freed = aerials + caches
    mib = lambda n: f"{n // 2**20} MiB"  # noqa: E731
    detail = f"freed {mib(freed)} (aerial videos {mib(aerials)}, caches {mib(caches)})" + (f"; {'; '.join(notes)}" if notes else "")
    if freed:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing = OUTPUT_PATH.read_text() if OUTPUT_PATH.exists() else "# MR pipeline cleanup sweep\n\n"
        OUTPUT_PATH.write_text(existing + f"\n## {datetime.now(timezone.utc).isoformat()}\n\n- First aid (disk nearly full): {detail}\n")
    return {"changed": freed > 0, "freed_bytes": freed, "detail": detail}


def main() -> dict:
    """launchd entry point, single flight (#586, the #457 main-health pattern): a sweep still running (say, stuck in a
    size walk) makes the next one return {"busy": True} at once instead of queueing. The flock dies with its process,
    so it can never go stale."""
    import fcntl
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("[cleanup-sweep] another sweep is still running; skipped", file=sys.stderr)
            return {"busy": True}
        return run_daily_sweep()


if __name__ == "__main__":
    print(json.dumps(main()))
