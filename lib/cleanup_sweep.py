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

Removal is lossless by construction: plain `git worktree remove` (never
--force, so git refuses if anything uncommitted or untracked is there) and the
branch is kept, so every commit stays reachable. Ignored build output
(.build, node_modules) is what the removal actually frees.
"""
from __future__ import annotations
import json
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
STALE_THRESHOLD_HOURS = 24
EMPTY_MIN_AGE_HOURS = 24
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


def _default_list_worktrees() -> list[dict]:
    """One dict per git worktree under WORKTREES_ROOT: path, branch, the clone
    it belongs to, that clone's GitHub repo (None if not on GitHub), commits
    ahead of origin/main, whether anything is uncommitted, and age in hours."""
    if not WORKTREES_ROOT.exists():
        return []
    out = []
    for entry in sorted(WORKTREES_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        branch = _git(entry, "branch", "--show-current")
        common = _git(entry, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if branch.returncode != 0 or not branch.stdout.strip() or common.returncode != 0:
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
    """("remove" | "keep" | "review", reason). "review" = kept, and listed in the
    log for a person, because it holds work nothing else has."""
    if wt.get("repo") is None:
        return "keep", "not a GitHub clone the sweep knows how to check"
    if wt.get("dirty"):
        return "review", "has uncommitted work"
    if claimed:
        return "keep", "its ticket is claimed (running)"
    if pr_state in ("MERGED", "CLOSED"):
        return "remove", f"PR {pr_state.lower()}"
    if pr_state == "OPEN":
        return "keep", "PR open"
    if wt.get("ahead"):
        return "review", f"{wt['ahead']} commit(s) with no PR"
    if wt.get("age_hours", 0) < EMPTY_MIN_AGE_HOURS:
        return "keep", "new, may be a ticket starting"
    return "remove", "empty attempt (no PR, no commits, no changes)"


def sweep_worktrees(
    list_worktrees: Callable[[], list[dict]] | None = None,
    pr_state: Callable[[str, str], str | None] | None = None,
    is_claimed: Callable[[str, int], bool] | None = None,
    remove_worktree: Callable[[dict], bool] | None = None,
) -> dict:
    list_worktrees = list_worktrees or _default_list_worktrees
    pr_state = pr_state or _default_pr_state
    is_claimed = is_claimed or _default_is_claimed
    remove_worktree = remove_worktree or _default_remove_worktree

    removed, review = [], []
    for wt in list_worktrees():
        repo, number = wt.get("repo"), _extract_issue_number(wt["branch"])
        try:
            state = pr_state(repo, wt["branch"]) if repo else None
            claimed = bool(repo and number is not None and is_claimed(repo, number))
        except Exception as exc:  # a GitHub failure must never read as "no PR"
            review.append({**wt, "reason": f"could not check GitHub: {str(exc)[:120]}"})
            continue
        action, reason = decide_worktree(wt, state, claimed)
        if action == "remove":
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
               compressed: dict | None = None) -> None:
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

    _write_log(stale, worktrees, simulators, compressed)
    return {"stale_claims_released": len(stale), "worktrees_removed": len(worktrees["removed"]),
            "worktrees_for_review": len(worktrees["review"]), "simulators_removed": len(simulators["removed"])}


if __name__ == "__main__":
    summary = run_daily_sweep()
    print(json.dumps(summary))
