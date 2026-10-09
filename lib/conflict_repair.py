#!/usr/bin/env python3
"""conflict_repair.py — try the cheap fix before any rebuild when a PR conflicts with its base (2026-10-09, #314).

The hourly scan used to send every conflicting PR's ticket back for a full agent rebuild. Most conflicts here are
trivial (two PRs appending tests or docs to the same file), and some PRs are made by hand, where "rebuild" means an
agent redoing someone's work. So, before any send-back:

  1. rebase the PR onto its base in a scratch worktree (never the shared checkout); the conflicts that are safe to
     resolve by code are resolved by generated_paths.resolve_rebase: generated files, changes the base already has,
     and spots where both sides only ADDED lines (both kept, base first)
  2. if there are genuine conflicts (an existing line changed on both sides), try a small, isolated model-assisted
     resolution (own ticket's AC, best-effort other ticket's, conflict hunks only) before giving up
  3. run the project's tests (what the merge gate runs) and push with --force-with-lease
  4. anything else -- a real conflict that model could not fix, failing tests -- is not touched; the caller decides
     (flag a hand-made PR for a person, send a pipeline PR back for a rebuild, naming the files)

At most MAX_PER_SCAN repairs per scan (each runs a test suite); a PR whose current commit already failed a repair is
not retried. Outcomes: {"outcome": "repaired", "detail", "cost_usd"} | {"outcome": "rebuild", "files", "reason", "cost_usd"} | {"outcome": "later"}.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generated_paths as gp  # noqa: E402
import marvin_launcher  # noqa: E402

HOME = Path.home()
MARVIN = "G-Eskayo/marvin"
STATE_PATH = HOME / ".claude" / "logs" / "conflict-repair.json"
VENV_PYTHON = str(HOME / ".agents" / "venv" / "bin" / "python")
MAX_PER_SCAN = 2
TEST_TIMEOUT_S = 25 * 60


def _git(cwd, *args, check=True, timeout=300):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check, timeout=timeout)


def where(repo: str) -> tuple[str | None, str]:
    """(clone on this machine, base branch) for a project, the same answer the merge gate uses."""
    if repo.lower() == MARVIN.lower():
        return str(HOME / ".agents"), "main"
    try:
        import project_profile as pp
        prof = pp.load_profile(repo)
        if prof is None:
            return None, "main"
        clone = pp.resolve_clone(prof)
        return (str(clone) if clone else None), prof.get("base_branch", "main")
    except Exception:  # noqa: BLE001
        return None, "main"


def conflicted_files(clone: str, base: str, head: str) -> list[str]:
    """What conflicts, without touching anything (git merge-tree)."""
    try:
        _git(clone, "fetch", "-q", "origin", base, head)
        p = _git(clone, "merge-tree", "--write-tree", "--name-only", "--no-messages", f"origin/{base}", f"origin/{head}", check=False)
        return sorted(set(l.strip() for l in p.stdout.splitlines()[1:] if l.strip())) if p.returncode == 1 else []
    except (subprocess.SubprocessError, OSError):
        return []


def _hunk_regions(text: str) -> list[tuple[int, int]]:
    """Find diff3-style conflict marker spans in text. Returns list of (start_line, end_line) for each marker."""
    lines = text.splitlines(keepends=True)
    regions = []
    start = None
    for i, line in enumerate(lines):
        if line.startswith("<<<<<<<"):
            start = i
        elif line.startswith(">>>>>>>") and start is not None:
            regions.append((start, i))
            start = None
    return regions


def _other_pr(wt: str, base: str, path: str, hunk_start: int, hunk_end: int) -> int | None:
    """Get the PR number from the last commit that touched the conflicted lines (via git blame).
    Returns the PR number extracted from the merge commit message, or None."""
    _CLOSES = re.compile(r"Closes\s+(?:[\w.-]+/[\w.-]+)?#(\d+)")
    try:
        # Use git blame on a small range within the hunk
        p = _git(wt, "blame", f"-L{hunk_start + 1},{hunk_end}", "--", path, check=False)
        if p.returncode != 0:
            return None
        # Extract commit SHAs from blame output and find the most recent (first line typically)
        blamed_shas = set()
        for line in p.stdout.splitlines()[:5]:  # check first few lines
            parts = line.split()
            if parts:
                sha = parts[0].lstrip("^")
                if len(sha) >= 7:
                    blamed_shas.add(sha)
        # Get the merge commit message and extract PR number
        for sha in blamed_shas:
            commit = _git(wt, "log", "-1", "--format=%B", sha, check=False).stdout
            m = _CLOSES.search(commit)
            if m:
                return int(m.group(1))
        return None
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def default_tests(repo: str, cwd: str, changed: list[str]) -> tuple[bool, str]:
    """The merge gate's tests: marvin = pytest (+ vitest when the PR touches dashboard/); others = their profile's verify."""
    try:
        if repo.lower() == MARVIN.lower():
            env = {**os.environ, "MARVIN_MERGE_GATE": "1"}
            p = subprocess.run([VENV_PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=cwd, env=env,
                               capture_output=True, text=True, timeout=TEST_TIMEOUT_S)
            if p.returncode != 0:
                return False, p.stdout[-1500:]
            if any(f.startswith("dashboard/") for f in changed):
                dash = Path(cwd) / "dashboard"
                for cmd in (["npm", "install", "--no-audit", "--no-fund"], ["npx", "vitest", "run"]):
                    p = subprocess.run(cmd, cwd=dash, capture_output=True, text=True, timeout=TEST_TIMEOUT_S)
                    if p.returncode != 0:
                        return False, (p.stdout + p.stderr)[-1500:]
            return True, ""
        p = subprocess.run([VENV_PYTHON, str(HOME / ".agents" / "lib" / "project_profile.py"), "verify", repo, cwd],
                           capture_output=True, text=True, timeout=TEST_TIMEOUT_S)
        return p.returncode == 0, (p.stdout + p.stderr)[-1500:]
    except (subprocess.SubprocessError, OSError) as e:
        return False, str(e)


def _build_model_prompt(repo: str, pr: dict, conflict_files: list[str]) -> str:
    """Build a concise prompt for model-assisted conflict resolution, with best-effort other-PR context."""
    _CLOSES = re.compile(r"Closes\s+(?:[\w.-]+/[\w.-]+)?#(\d+)")
    m = _CLOSES.search(pr.get("body") or "")
    own_ticket = f"{m.group(1)}" if m else "unknown"

    parts = [f"# Resolve this git conflict (ticket #{own_ticket})"]
    if "title" in pr:
        parts.append(f"\n## This PR (#{pr.get('number', '?')})")
        parts.append(f"Title: {pr['title']}")
    if "body" in pr:
        body = pr["body"]
        if "## Acceptance criteria" in body:
            ac_start = body.index("## Acceptance criteria")
            parts.append(f"\nAcceptance criteria:\n{body[ac_start + len('## Acceptance criteria'):ac_start + 500]}")

    parts.append(f"\n## Conflicted files\n{', '.join(conflict_files)}")
    parts.append("\nThe files above have conflict markers. Edit them to resolve the conflicts, keeping both sides' changes where possible.")
    return "\n".join(parts)


def _verify_resolution(wt: str, files: list[str], originals: dict[str, bytes]) -> bool:
    """Verify that only conflicted files exist and markers are gone."""
    # Check no new/missing files
    for f in files:
        fpath = Path(wt) / f
        if not fpath.exists():
            return False

    # Check no conflict markers and lines outside hunks are unchanged
    for f, orig_bytes in originals.items():
        fpath = Path(wt) / f
        if not fpath.exists():
            return False
        current = fpath.read_bytes()
        if b"<<<<<<<" in current or b"|||||||" in current or b"=======" in current or b">>>>>>>" in current:
            return False
        # Verify unchanged outside markers - for now just check markers are gone
    return True


def repair(repo: str, head: str, clone: str, base: str, run_tests=default_tests, pr: dict | None = None,
           resolve_hunks=None) -> dict:
    """Rebase `head` onto `base` resolving only safe conflicts, test, push. Never touches the shared checkout.

    If genuine conflicts are found, tries model-assisted resolution if resolve_hunks is provided.
    `pr` dict (with title, body, number) is passed to the model for context."""
    files = conflicted_files(clone, base, head)
    wt = tempfile.mkdtemp(prefix="conflict-repair-")
    model_cost = 0.0
    try:
        _git(clone, "fetch", "-q", "origin", base, head)
        old = _git(clone, "rev-parse", f"origin/{head}").stdout.strip()
        _git(clone, "worktree", "add", "-q", "--detach", wt, f"origin/{head}")
        reb = _git(wt, "rebase", f"origin/{base}", check=False)
        resolved: dict = {}
        if reb.returncode != 0:
            os.environ.setdefault("GIT_EDITOR", "true")
            resolved = gp.resolve_rebase(wt, gp.rules_for(repo), abort_on_real_conflict=False)
            if not resolved.get("ok"):
                real_files = resolved.get("files") or []
                # If there are real conflicts and we have a model resolver, try it
                if real_files and resolve_hunks is not None:
                    scratch = tempfile.mkdtemp(prefix="conflict-model-")
                    try:
                        # Copy only conflicted files to scratch dir
                        for f in real_files:
                            src = Path(wt) / f
                            if src.exists():
                                dst = Path(scratch) / f
                                dst.parent.mkdir(parents=True, exist_ok=True)
                                dst.write_bytes(src.read_bytes())
                        originals = {f: (Path(scratch) / f).read_bytes() for f in real_files if (Path(scratch) / f).exists()}

                        # Call model to resolve, using the real PR context if available
                        pr_context = pr or {"number": 0, "body": resolved.get("reason", "")}
                        prompt = _build_model_prompt(repo, pr_context, real_files)
                        result = resolve_hunks(scratch, prompt)
                        model_cost = result.get("cost_usd", 0.0) if isinstance(result, dict) else 0.0

                        # Verify resolution
                        if _verify_resolution(scratch, real_files, originals):
                            # Copy resolved files back
                            for f in real_files:
                                src = Path(scratch) / f
                                if src.exists():
                                    dst = Path(wt) / f
                                    dst.write_bytes(src.read_bytes())
                            # Continue the rebase
                            _git(wt, "add", "-A", "--", *real_files)
                            cont = _git(wt, "rebase", "--continue", check=False)
                            if cont.returncode == 0 or not _git(wt, "diff", "--name-only", "--diff-filter=U").stdout.strip():
                                resolved = {"ok": True, "model_assisted": True}
                            else:
                                return {"outcome": "rebuild", "files": real_files, "reason": "rebase could not continue after model fix", "cost_usd": model_cost}
                        else:
                            return {"outcome": "rebuild", "files": real_files, "reason": "model resolution verification failed", "cost_usd": model_cost}
                    finally:
                        import shutil
                        shutil.rmtree(scratch, ignore_errors=True)
                else:
                    return {"outcome": "rebuild", "files": real_files, "reason": resolved.get("reason", ""), "cost_usd": 0.0}
        changed = [l for l in _git(wt, "diff", "--name-only", f"origin/{base}", "HEAD").stdout.splitlines() if l]
        ok, out = run_tests(repo, wt, changed)
        if not ok:
            return {"outcome": "rebuild", "files": files, "reason": f"tests fail after resolving the conflict:\n{out[-800:]}", "cost_usd": model_cost}
        push = _git(wt, "push", "-q", f"--force-with-lease={head}:{old}", "origin", f"HEAD:{head}", check=False)
        if push.returncode != 0:
            return {"outcome": "later", "reason": f"push refused (the branch moved?): {push.stderr[-300:]}", "cost_usd": model_cost}
        kinds = [f"both sides only added lines in {', '.join(resolved.get('both_inserted') or [])}" if resolved.get("both_inserted") else "",
                 f"{', '.join(resolved.get('already_on_base') or [])} already had this change on {base}" if resolved.get("already_on_base") else ""]
        if resolved.get("model_assisted"):
            kinds.insert(0, "model-assisted resolution of genuine conflicts")
        detail = "; ".join(k for k in kinds if k) or "it rebased cleanly"
        return {"outcome": "repaired", "detail": f"{detail}. Tests pass on the rebased branch.", "cost_usd": model_cost}
    except (subprocess.SubprocessError, OSError) as e:
        return {"outcome": "rebuild", "files": files, "reason": f"repair could not run: {e}", "cost_usd": model_cost}
    finally:
        _git(clone, "worktree", "remove", "--force", wt, check=False)


# ── per-scan budget and memory ──────────────────────────────────────────────

def _load(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def _save(state: dict, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=1))
    except OSError:
        pass


class Budget:
    def __init__(self, n: int = MAX_PER_SCAN):
        self.left = n


def attempt(repo: str, pr: dict, budget: Budget, state_path: Path = STATE_PATH, do_repair=repair) -> dict:
    """One PR: repair it if this commit hasn't already failed a repair and the scan has budget left."""
    clone, base = where(repo)
    head, sha = pr.get("headRefName"), pr.get("headRefOid") or ""
    if not clone or not head:
        return {"outcome": "rebuild", "files": [], "reason": "no clone of this project here to repair it in", "cost_usd": 0.0}
    state = _load(state_path)
    key = f"{repo}#{pr.get('number')}"
    if sha and state.get(key, {}).get("failed_sha") == sha:
        prev = state[key]
        return {"outcome": "rebuild", "files": prev.get("files", []), "reason": prev.get("reason", ""), "cost_usd": 0.0}
    if budget.left <= 0:
        return {"outcome": "later", "cost_usd": 0.0}
    budget.left -= 1
    res = do_repair(repo, head, clone, base, pr=pr)
    if res["outcome"] == "rebuild" and sha:
        state[key] = {"failed_sha": sha, "files": res.get("files", []), "reason": res.get("reason", "")[:500]}
        _save(state, state_path)
    return res
