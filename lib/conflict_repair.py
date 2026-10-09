#!/usr/bin/env python3
"""conflict_repair.py — try the cheap fix before any rebuild when a PR conflicts with its base (2026-10-09, #314).

The hourly scan used to send every conflicting PR's ticket back for a full agent rebuild. Most conflicts here are
trivial (two PRs appending tests or docs to the same file), and some PRs are made by hand, where "rebuild" means an
agent redoing someone's work. So, before any send-back:

  1. rebase the PR onto its base in a scratch worktree (never the shared checkout); the conflicts that are safe to
     resolve by code are resolved by generated_paths.resolve_rebase: generated files, changes the base already has,
     and spots where both sides only ADDED lines (both kept, base first)
  2. run the project's tests (what the merge gate runs) and push with --force-with-lease
  3. anything else -- a real conflict, failing tests -- is not touched; the caller decides (flag a hand-made PR for a
     person, send a pipeline PR back for a rebuild, naming the files)

At most MAX_PER_SCAN repairs per scan (each runs a test suite); a PR whose current commit already failed a repair is
not retried. Outcomes: {"outcome": "repaired", "detail"} | {"outcome": "rebuild", "files", "reason"} | {"outcome": "later"}.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generated_paths as gp  # noqa: E402

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


def repair(repo: str, head: str, clone: str, base: str, run_tests=default_tests) -> dict:
    """Rebase `head` onto `base` resolving only safe conflicts, test, push. Never touches the shared checkout."""
    files = conflicted_files(clone, base, head)
    wt = tempfile.mkdtemp(prefix="conflict-repair-")
    try:
        _git(clone, "fetch", "-q", "origin", base, head)
        old = _git(clone, "rev-parse", f"origin/{head}").stdout.strip()
        _git(clone, "worktree", "add", "-q", "--detach", wt, f"origin/{head}")
        reb = _git(wt, "rebase", f"origin/{base}", check=False)  # the machine's own git identity, as the merge gate's rebase uses
        resolved: dict = {}
        if reb.returncode != 0:
            os.environ.setdefault("GIT_EDITOR", "true")
            resolved = gp.resolve_rebase(wt, gp.rules_for(repo))
            if not resolved.get("ok"):
                return {"outcome": "rebuild", "files": resolved.get("files") or files, "reason": resolved.get("reason", "")}
        changed = [l for l in _git(wt, "diff", "--name-only", f"origin/{base}", "HEAD").stdout.splitlines() if l]
        ok, out = run_tests(repo, wt, changed)
        if not ok:
            return {"outcome": "rebuild", "files": files, "reason": f"tests fail after resolving the conflict:\n{out[-800:]}"}
        push = _git(wt, "push", "-q", f"--force-with-lease={head}:{old}", "origin", f"HEAD:{head}", check=False)
        if push.returncode != 0:
            return {"outcome": "later", "reason": f"push refused (the branch moved?): {push.stderr[-300:]}"}
        kinds = [f"both sides only added lines in {', '.join(resolved.get('both_inserted') or [])}" if resolved.get("both_inserted") else "",
                 f"{', '.join(resolved.get('already_on_base') or [])} already had this change on {base}" if resolved.get("already_on_base") else ""]
        detail = "; ".join(k for k in kinds if k) or "it rebased cleanly"
        return {"outcome": "repaired", "detail": f"{detail}. Tests pass on the rebased branch."}
    except (subprocess.SubprocessError, OSError) as e:
        return {"outcome": "rebuild", "files": files, "reason": f"repair could not run: {e}"}
    finally:
        _git(clone, "worktree", "remove", "--force", wt, check=False)


# ── per-scan budget and memory ──────────────────────────────────────────────

def _load(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def _save(data: dict, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1))
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
        return {"outcome": "rebuild", "files": [], "reason": "no clone of this project here to repair it in"}
    state = _load(state_path)
    key = f"{repo}#{pr.get('number')}"
    if sha and state.get(key, {}).get("failed_sha") == sha:
        prev = state[key]
        return {"outcome": "rebuild", "files": prev.get("files", []), "reason": prev.get("reason", "")}
    if budget.left <= 0:
        return {"outcome": "later"}
    budget.left -= 1
    res = do_repair(repo, head, clone, base)
    if res["outcome"] == "rebuild" and sha:
        state[key] = {"failed_sha": sha, "files": res.get("files", []), "reason": res.get("reason", "")[:500]}
        _save(state, state_path)
    return res
