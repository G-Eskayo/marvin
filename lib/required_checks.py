"""A project's required checks: one list, read by GitHub CI, the merge gate and branch protection (marvin#826).

Before this, GitHub CI ran the dashboard tests and the merge gate ran those plus the Python suite, so a PR could be
green on the website and red in MR Review, and a website merge skipped the Python tests entirely (#767, #770). Now
each project repo carries its list in .github/required-checks.json:

    {"checks": [{"id": "python", "name": "Python tests", "cwd": ".", "command": ["python", "-m", "pytest", "-q"],
                 "parser": "pytest", "requires": ["python"], "timeout_s": 1800, "where": "both"}, ...]}

  id        what CI and the gate call it: `.github/run-check.sh <id>` runs it
  name      the GitHub check name: the CI job's `name:`, and what branch protection requires
  where     "both" (default): CI and the merge gate run it; "ci": only CI can (a tool the Macs run elsewhere, e.g.
            the secret scan, which every clone also runs as its pre-push hook)
  command   argv, run in cwd by the runner. `python` means the interpreter on PATH (CI's setup-python, the gate's venv)

The list lives in the repo, not the instance profile, because CI can read only the repo it runs in. The profile still
owns everything machine-specific (setup steps, which Macs, env); lib/project_profile.py folds the list in as the
project's required verify steps (with_required_checks), so the gate and the pipeline run what CI runs.

    required_checks.py names [repo]    the GitHub check names, one per line (what branch protection requires)
    required_checks.py drift [repo]    say where ci.yml and the list disagree; exit 1 if they do
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

LIST = Path(".github") / "required-checks.json"
RUNNER = ".github/run-check.sh"
_ID = re.compile(r"[a-z0-9][a-z0-9-]*")


def load(repo: Path) -> list[dict] | None:
    """The repo's checks with defaults filled in; None when it has no list. ValueError says what is wrong."""
    f = Path(repo) / LIST
    if not f.is_file():
        return None
    try:
        data = json.loads(f.read_text())
    except ValueError as e:
        raise ValueError(f"{LIST}: not valid JSON ({e})") from e
    checks = data.get("checks") if isinstance(data, dict) else None
    if not isinstance(checks, list) or not checks:
        raise ValueError(f"{LIST}: no checks (it needs a non-empty \"checks\" list)")
    out, ids, names = [], set(), set()
    for c in checks:
        if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not _ID.fullmatch(c["id"]):
            raise ValueError(f"{LIST}: each check needs an id of lowercase letters, digits and dashes")
        cid = c["id"]
        if not isinstance(c.get("name"), str) or not c["name"].strip():
            raise ValueError(f"{LIST}: check {cid} needs a name (its GitHub check name)")
        where = c.get("where", "both")
        if where not in ("both", "ci"):
            raise ValueError(f"{LIST}: check {cid}: where must be \"both\" or \"ci\", not {where!r}")
        cmd = c.get("command")
        if where == "both" and (not isinstance(cmd, list) or not cmd or not all(isinstance(a, str) for a in cmd)):
            raise ValueError(f"{LIST}: check {cid} needs a command (a list of strings)")
        if cid in ids or c["name"] in names:
            raise ValueError(f"{LIST}: check {cid} ({c['name']}) is listed twice")
        ids.add(cid)
        names.add(c["name"])
        out.append({"cwd": ".", "requires": [], "parser": "exit-code", "timeout_s": 1200, **c, "where": where})
    return out


def names(repo: Path) -> list[str]:
    return [c["name"] for c in load(repo) or []]


def ci_drift(repo: Path) -> list[str]:
    """Where .github/workflows/ci.yml and the list disagree. Empty = CI runs exactly the list."""
    import yaml
    checks = load(repo) or []
    try:
        jobs = (yaml.safe_load((Path(repo) / ".github" / "workflows" / "ci.yml").read_text()) or {}).get("jobs") or {}
    except OSError:
        return ["ci.yml: missing"] if checks else []
    by_name = {j.get("name"): j for j in jobs.values() if isinstance(j, dict)}
    out = []
    for c in checks:
        job = by_name.get(c["name"])
        if job is None:
            out.append(f"{c['name']}: no CI job has this name")
        elif c["where"] == "both" and f"{RUNNER} {c['id']}" not in " ".join(str(s.get("run", "")) for s in job.get("steps") or []):
            out.append(f"{c['name']}: the CI job does not run {RUNNER} {c['id']}")
    return out


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    repo = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1]
    try:
        if cmd == "names":
            print("\n".join(names(repo)))
            return 0
        if cmd == "drift":
            problems = ci_drift(repo)
            print("\n".join(problems) or "no drift: CI runs exactly the required checks")
            return 1 if problems else 0
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
