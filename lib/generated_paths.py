"""Files a tool regenerates (graphify-out/, package-lock.json) change in almost every PR, so unrelated PRs
conflict on them. Rather than untrack them, a project profile declares them:

    "generated": [{"path": "graphify-out"},
                  {"path": "package-lock.json", "unless": "package.json",
                   "regenerate": ["npm", "install", "--package-lock-only", "--ignore-scripts"]}]

* path        a file, or a directory (everything under it)
* unless      the rule does NOT apply when this file is in the same change -- a PR that really changes
              package.json must keep its lockfile change
* regenerate  how to rebuild it; used when a rebase conflicts on it (otherwise main's copy is taken)

Two uses, one implementation: `unstage_generated` keeps them out of a pipeline PR's commit, and
`resolve_rebase` lets the merge gate finish a rebase whose ONLY conflicts are in generated files.
A conflict in real code is never papered over.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def is_generated(path: str, rules: list[dict]) -> bool:
    return any(path == r["path"] or path.startswith(r["path"].rstrip("/") + "/") for r in rules)


def generated_among(changed: list[str], rules: list[dict]) -> list[str]:
    """The changed paths that are generated noise, honouring `unless` (a rule is off when its guard file changed too)."""
    changed_set = set(changed)
    live = [r for r in rules if not (r.get("unless") and r["unless"] in changed_set)]
    return [p for p in changed if is_generated(p, live)]


def _git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check, env={**os.environ, "GIT_EDITOR": "true"})


def unstage_generated(worktree, rules: list[dict]) -> list[str]:
    """Take generated paths out of the staged change (they stay modified on disk, uncommitted). Returns them."""
    if not rules:
        return []
    staged = _git(worktree, "diff", "--cached", "--name-only").stdout.split("\n")
    drop = generated_among([p for p in staged if p], rules)
    if drop:
        _git(worktree, "reset", "-q", "--", *drop)
    return drop


def _in_rebase(worktree) -> bool:
    for d in ("rebase-merge", "rebase-apply"):
        git_path = _git(worktree, "rev-parse", "--git-path", d).stdout.strip()
        if (Path(worktree) / git_path).exists():  # git-path may be relative to the worktree or absolute
            return True
    return False


def _already_on_base(worktree, path: str) -> bool:
    """Is the PR's own change to `path` already present in main's copy? True when the commit being replayed
    (REBASE_HEAD), applied IN REVERSE to main's version of the file (context lines ignored: main may have
    edited the neighbouring lines), goes through cleanly -- i.e. every line
    it added is there and every line it removed is gone. That is what happens when parallel PRs each add the
    same thing (finance-os #8, #9, #10 each added the same vitest setup to package.json)."""
    commit = _git(worktree, "rev-parse", "REBASE_HEAD", check=False)
    ours = _git(worktree, "show", f":2:{path}", check=False)  # stage 2 = the branch being rebased onto
    if commit.returncode != 0 or ours.returncode != 0:
        return False
    patch = _git(worktree, "diff", f"{commit.stdout.strip()}^", commit.stdout.strip(), "--", path, check=False).stdout
    if not patch.strip():
        return False
    # Content check first, since the apply below ignores context lines: every line the PR added must be in
    # main's copy (counting repeats), so a loose position match can never "confirm" a change that isn't there.
    from collections import Counter
    added = Counter(l[1:].strip() for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++") and l[1:].strip())
    have = Counter(l.strip() for l in ours.stdout.splitlines())
    if any(have[line] < n for line, n in added.items()):
        return False
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(ours.stdout)
        done = subprocess.run(["git", "apply", "-R", "--check", "-C0", "--ignore-whitespace"], cwd=tmp, input=patch,
                              capture_output=True, text=True)
    return done.returncode == 0


def resolve_rebase(worktree, rules: list[dict], max_steps: int = 100) -> dict:
    """Finish a rebase that stopped on conflicts, if every conflicted file is generated. During a rebase
    `--ours` is the branch being rebased ONTO (main), so a generated file takes main's copy, is rebuilt with
    its `regenerate` command if it has one, and the rebase continues. A non-generated file whose conflict is
    only that main ALREADY has this PR's change is resolved the same way (main's copy). Anything else aborts.
    """
    already: list[str] = []
    for _ in range(max_steps):
        unmerged = [p for p in _git(worktree, "diff", "--name-only", "--diff-filter=U").stdout.split("\n") if p]
        if not unmerged:
            if not _in_rebase(worktree):
                return {"ok": True, "already_on_base": already}
            cont = _git(worktree, "rebase", "--continue", check=False)
            if cont.returncode != 0 and not _git(worktree, "diff", "--name-only", "--diff-filter=U").stdout.strip():
                # everything this commit did is already on main, so nothing is left to commit: drop it
                if "nothing to commit" in (cont.stdout + cont.stderr).lower() or "no changes" in (cont.stdout + cont.stderr).lower():
                    _git(worktree, "rebase", "--skip", check=False)
                    continue
                _git(worktree, "rebase", "--abort", check=False)
                return {"ok": False, "reason": f"rebase could not continue: {(cont.stderr or cont.stdout)[-300:]}"}
            continue
        redundant = [p for p in unmerged if not is_generated(p, rules) and _already_on_base(worktree, p)]
        real = [p for p in unmerged if not is_generated(p, rules) and p not in redundant]
        if real:
            _git(worktree, "rebase", "--abort", check=False)
            return {"ok": False, "reason": "conflicts in files that are neither generated nor already on main: " + ", ".join(real)}
        already += redundant
        for path in unmerged:
            if _git(worktree, "checkout", "--ours", "--", path, check=False).returncode != 0:
                _git(worktree, "rm", "-q", "-f", "--", path, check=False)
        for rule in rules:
            if rule.get("regenerate") and any(is_generated(p, [rule]) for p in unmerged):
                done = subprocess.run(rule["regenerate"], cwd=worktree, capture_output=True, text=True)
                if done.returncode != 0:
                    _git(worktree, "rebase", "--abort", check=False)
                    return {"ok": False, "reason": f"regenerating {rule['path']} failed: {(done.stderr or done.stdout)[-300:]}"}
        to_add = [r["path"] for r in rules if os.path.exists(Path(worktree) / r["path"])] + [p for p in redundant if os.path.exists(Path(worktree) / p)]
        _git(worktree, "add", "-A", "--", *(to_add or ["."]))
        for gone in (p for p in redundant if not os.path.exists(Path(worktree) / p)):
            _git(worktree, "rm", "-q", "--cached", "--", gone, check=False)
    _git(worktree, "rebase", "--abort", check=False)
    return {"ok": False, "reason": "gave up resolving generated-file conflicts after too many steps"}


# marvin has no project profile; these are the files its own tools rewrite (health monitor, metrics, the graph), which
# conflicted on every post-merge rebase (#225) and in code_sync.
MARVIN = "G-Eskayo/marvin"
MARVIN_GENERATED = [{"path": "bench/metrics"}, {"path": "graphify-out"}]


def rules_for(repo: str) -> list[dict]:
    import project_profile as pp
    profile = pp.load_profile(repo)
    if profile is not None:
        return profile.get("generated", [])
    return MARVIN_GENERATED if repo.lower() == MARVIN.lower() else []


def main() -> None:  # python generated_paths.py resolve-rebase <owner/repo> <worktree>   (exit 0 = resolved)
    import json
    if len(sys.argv) != 4 or sys.argv[1] != "resolve-rebase":
        sys.exit("usage: generated_paths.py resolve-rebase <owner/repo> <worktree>")
    res = resolve_rebase(sys.argv[3], rules_for(sys.argv[2]))
    print(json.dumps(res))
    sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
