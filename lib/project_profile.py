#!/usr/bin/env python3
"""Per-project execution profiles: how the ticket pipeline builds, tests and verifies a project that is
not marvin (CONTEXT.md "Per-project execution profiles"). A profile is a JSON file in
config/projects/ that says where the project's clone is, which machines can run it, what environment its
toolchain needs, how a ticket is verified (tiers: command, parser, required/optional) and what the headless
model may run. marvin itself keeps its built-in path and has no profile.

    project_profile.py list                 profiles and whether dispatch is on
    project_profile.py selftest <repo>      dry run in a throwaway worktree: no model call, no GitHub writes
"""
from __future__ import annotations
import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PROFILES_DIR = Path.home() / ".agents" / "config" / "projects"
_NO_TESTS_MARKERS = ("no tests ran", "no test files found")


class EnvMissing(RuntimeError):
    """A required tool is not installed on THIS machine. The machine is not suitable for the ticket;
    the ticket did nothing wrong, so it must not be counted as a failure."""

    def __init__(self, tier: str, missing: list[str]):
        super().__init__(f"required verification '{tier}' needs {', '.join(missing)}, which this machine does not have")
        self.tier, self.missing = tier, missing


class MeasureError(RuntimeError):
    """A tier crashed without producing a result. An error, never a zero."""


# ── parsers ─────────────────────────────────────────────────────────────────

_XCTEST_RE = re.compile(r"Executed (\d+) tests?, with (?:(\d+) tests? skipped and )?(\d+) failures?")
_SWIFT_TESTING_RE = re.compile(r"Test run with (\d+) tests?[^\n]*?\b(passed|failed)\b(?:[^\n]*?with (\d+) issues?)?")


def parse_swift_test(output: str) -> dict | None:
    """`swift test` prints an XCTest summary (the last 'Executed N tests' line is the whole run) and, after
    it, a Swift Testing summary. Both are added. None = it never got far enough to run tests."""
    total = failed = skipped = 0
    found = False
    xc = _XCTEST_RE.findall(output)
    if xc:
        t, sk, f = xc[-1]
        total, skipped, failed = int(t), int(sk or 0), int(f)
        found = True
    for t, verdict, issues in _SWIFT_TESTING_RE.findall(output):
        total += int(t)
        if verdict == "failed":
            failed += int(issues) if issues else 1
        found = True
    if not found:
        return None
    return {"total": total, "failed": failed, "skipped": skipped, "passed": max(0, total - failed - skipped)}


def parse_xcodebuild(output: str) -> dict | None:
    if "** BUILD SUCCEEDED **" in output:
        return {"build_ok": 1}
    if "** BUILD FAILED **" in output:
        return {"build_ok": 0}
    return None


def parse_exit_code(output: str, returncode: int | None = None) -> dict | None:
    return {"build_ok": 1 if returncode == 0 else 0}


def parse_output(parser: str, output: str, returncode: int) -> dict | None:
    if parser == "swift-test":
        return parse_swift_test(output)
    if parser == "xcodebuild":
        return parse_xcodebuild(output)
    if parser == "exit-code":
        return parse_exit_code(output, returncode)
    raise ValueError(f"unknown parser: {parser}")


# ── profiles ────────────────────────────────────────────────────────────────

def _validate(profile: dict, source: str) -> dict:
    for key in ("repo", "verify"):
        if key not in profile:
            raise ValueError(f"{source}: missing '{key}'")
    for t in profile["verify"]:
        for key in ("id", "command"):
            if key not in t:
                raise ValueError(f"{source}: verify tier {t.get('id', '?')} is missing '{key}'")
        t.setdefault("label", t["id"])
        t.setdefault("cwd", ".")
        t.setdefault("requires", [])
        t.setdefault("parser", "exit-code")
        t.setdefault("required", False)
        t.setdefault("timeout_s", 1200)
    profile.setdefault("base_branch", "main")
    profile.setdefault("dispatch", "off")  # a profile does nothing until a person turns it on
    profile.setdefault("machines", [])
    profile.setdefault("clone_hints", [])
    profile.setdefault("env", {})
    profile.setdefault("executor", {})
    profile.setdefault("evidence", {})
    return profile


def load_profile(repo: str, directory: Path | None = None) -> dict | None:
    directory = directory or PROFILES_DIR
    if not directory.is_dir():
        return None
    for f in sorted(directory.glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{f.name}: not valid JSON ({e})") from e
        if isinstance(data, dict) and data.get("repo") == repo:
            return _validate(data, f.name)
    return None


def all_profiles(directory: Path | None = None) -> list[dict]:
    directory = directory or PROFILES_DIR
    out = []
    if directory.is_dir():
        for f in sorted(directory.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                if isinstance(data, dict) and "repo" in data:
                    out.append(_validate(data, f.name))
            except (json.JSONDecodeError, ValueError):
                continue  # one broken profile must not hide the others; `list` reports it
    return out


def dispatchable_repos(directory: Path | None = None) -> list[str]:
    return [p["repo"] for p in all_profiles(directory) if p["dispatch"] == "on"]


def resolve_clone(profile: dict, catalog: dict | None = None) -> Path | None:
    """The project's real clone on THIS machine: the catalog's newest local path first (the live working
    copy), then the profile's own hints."""
    candidates = []
    for p in (catalog or {}).get("projects", []):
        if p.get("repo") == profile["repo"]:
            candidates += p.get("localPaths", [])
    candidates += profile.get("clone_hints", [])
    for c in candidates:
        path = Path(c).expanduser()
        if (path / ".git").exists():
            return path
    return None


# ── environment ─────────────────────────────────────────────────────────────

def build_env(profile: dict, base_env: dict | None = None) -> dict:
    """The environment verification runs in. DEVELOPER_DIR points at an installed Xcode for this one
    process tree, so `swift test` finds XCTest without anyone running `sudo xcode-select` (which would
    change the whole machine)."""
    env = dict(base_env if base_env is not None else os.environ)
    spec = (profile.get("env") or {}).get("DEVELOPER_DIR")
    if isinstance(spec, dict):
        for cand in spec.get("first_existing", []):
            if Path(cand).expanduser().is_dir():
                env["DEVELOPER_DIR"] = str(Path(cand).expanduser())
                break
    parts = env.get("PATH", "").split(":")
    for extra in ("/opt/homebrew/bin", "/usr/local/bin"):
        if extra not in parts:
            parts.insert(0, extra)
    env["PATH"] = ":".join(p for p in parts if p)
    return env


def have(capability: str, env: dict, which=shutil.which) -> bool:
    if capability == "xcode":
        dev = env.get("DEVELOPER_DIR")
        return bool(dev) and (Path(dev) / "usr" / "bin" / "xcodebuild").exists()
    if capability in ("swift", "xcodegen"):
        return which(capability, path=env.get("PATH")) is not None
    return which(capability, path=env.get("PATH")) is not None


def missing_here(profile: dict) -> list[str]:
    """Tools the profile's REQUIRED checks need that THIS machine lacks (empty = it can run them)."""
    env = build_env(profile)
    out: list[str] = []
    for t in profile.get("verify", []):
        if t.get("required") and t.get("enabled") is not False:
            out += [c for c in t.get("requires", []) if not have(c, env) and c not in out]
    return out


# ── measuring ───────────────────────────────────────────────────────────────

def _default_runner(cmd, cwd, env, timeout):
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


class Measurer:
    """Callable with the shape `execute_ticket` expects of `measure`: worktree -> metrics. Also keeps what
    it saw (`report`) so the PR can say exactly what was and was not verified."""

    def __init__(self, profile: dict, runner=_default_runner, have=None, env: dict | None = None):
        self.profile = _validate(copy.deepcopy(profile), "profile")  # same defaults as a loaded profile
        self.runner = runner
        self.env = env if env is not None else build_env(self.profile)
        self.have = have or (lambda cap, e: globals()["have"](cap, e))
        self.report: dict = {"tiers": [], "notes": []}

    def __call__(self, worktree: Path) -> dict:
        metrics: dict = {}
        passed = failed = 0
        self.report = {"tiers": [], "notes": []}
        for t in self.profile["verify"]:
            row = {"id": t["id"], "label": t["label"], "ran": False}
            self.report["tiers"].append(row)
            if t.get("enabled") is False:
                self.report["notes"].append(f"{t['label']}: not verified (disabled in the project's profile)")
                continue
            missing = [c for c in t["requires"] if not self.have(c, self.env)]
            if missing:
                if t["required"]:
                    raise EnvMissing(t["id"], missing)
                self.report["notes"].append(f"{t['label']}: not verified (needs {', '.join(missing)}, not available on this machine)")
                continue
            rc, out = self.runner(t["command"], Path(worktree) / t["cwd"], self.env, t["timeout_s"])
            parsed = parse_output(t["parser"], out, rc)
            if parsed is None:
                if any(m in out.lower() for m in _NO_TESTS_MARKERS):
                    parsed = {"total": 0, "failed": 0, "skipped": 0, "passed": 0}
                else:
                    raise MeasureError(f"{t['label']} produced no result (crashed or never ran): ...{out[-300:].strip()}")
            row.update(ran=True, **parsed)
            if "build_ok" in parsed:
                metrics[f"{t['id']}_build_ok"] = {"value": parsed["build_ok"], "higher_is_better": True}
            else:
                metrics[f"{t['id']}_passed"] = {"value": parsed["passed"], "higher_is_better": True}
                metrics[f"{t['id']}_failed"] = {"value": parsed["failed"], "higher_is_better": False}
                passed += parsed["passed"]
                failed += parsed["failed"]
        metrics["tests_passed"] = {"value": passed, "higher_is_better": True}
        metrics["tests_failed"] = {"value": failed, "higher_is_better": False}
        return metrics

    def evidence(self) -> tuple[dict | None, dict]:
        """(test_results, dev_evidence) in the shapes mr_raiser formats into the PR body."""
        tests = [t for t in self.report["tiers"] if t.get("ran") and "total" in t]
        test_results = None
        if tests:
            test_results = {"suite": " + ".join(t["label"] for t in tests), "passed": sum(t["passed"] for t in tests),
                            "failed": sum(t["failed"] for t in tests), "total": sum(t["total"] for t in tests)}
        reason = ((self.profile.get("evidence") or {}).get("dev") or {}).get("na", "no dev-environment capture configured for this project")
        return test_results, {"na": True, "reason": reason}

    def pr_note(self) -> str:
        return "\n".join(self.report["notes"])


# ── selftest ────────────────────────────────────────────────────────────────

def _cleanup_worktree(clone: Path, worktree: Path, branch: str) -> None:
    subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=clone, capture_output=True)
    subprocess.run(["git", "branch", "-D", branch], cwd=clone, capture_output=True)


def selftest(profile: dict, runner=_default_runner, have=None, catalog: dict | None = None) -> dict:
    """Everything a real ticket does EXCEPT the model call and any GitHub write: find the clone, make a real
    worktree from the base branch, run the required checks for real (the baseline), and build the PR body the
    pipeline would raise. Always removes the worktree and branch it made."""
    import mr_raiser
    import sandbox_orchestration as so
    import metrics_registry as mr

    profile = _validate(copy.deepcopy(profile), "profile")
    clone = resolve_clone(profile, catalog if catalog is not None else _catalog())
    if clone is None:
        return {"ok": False, "error": f"no local clone of {profile['repo']} on this machine"}
    ticket_ref = f"{profile['repo']}#999999"
    branch = f"pipeline/{ticket_ref.lower()}"
    measurer = Measurer(profile, runner=runner, have=have)
    # Fail fast on a machine that cannot run the required checks: no worktree, no git, nothing to clean up.
    lacking = []
    for t in profile["verify"]:
        if t["required"] and t.get("enabled") is not False:
            lacking += [c for c in t["requires"] if not measurer.have(c, measurer.env) and c not in lacking]
    if lacking:
        return {"ok": False, "clone": str(clone), "error": f"this machine lacks {', '.join(lacking)}, which the required checks need"}
    worktree = None
    try:
        worktree = so._create_worktree(clone, ticket_ref, profile["base_branch"])
        baseline = measurer(worktree)
        comparison = mr.compare("selftest", baseline, baseline)
        test_results, dev = measurer.evidence()
        if test_results is not None:
            test_results["notes"] = measurer.pr_note()
        body = (f"Closes {ticket_ref}\n\n## Metrics Comparison\n\n{mr_raiser._format_comparison(comparison)}\n\n"
                f"## Test Results\n\n{mr_raiser._format_test_results(test_results)}\n\n"
                f"## Dev Environment Evidence\n\n{mr_raiser._format_dev_evidence(dev)}")
        return {"ok": True, "clone": str(clone), "worktree": str(worktree), "metrics": {k: v["value"] for k, v in baseline.items()},
                "tiers": measurer.report["tiers"], "notes": measurer.report["notes"], "pr_body": body}
    except (EnvMissing, MeasureError, Exception) as e:  # noqa: BLE001 -- the report says what broke
        return {"ok": False, "error": str(e), "clone": str(clone)}
    finally:
        if worktree is not None:
            _cleanup_worktree(clone, worktree, branch)


def _catalog() -> dict:
    try:
        import project_catalog
        return project_catalog.read_catalog(project_catalog.catalog_path()) or {"projects": []}
    except Exception:  # noqa: BLE001
        return {"projects": []}


# ── the headless model's leash ──────────────────────────────────────────────

def executor_tools(profile: dict, clone: Path | None = None) -> tuple[str, str]:
    """(allowed, disallowed) tool strings for the execution call. Editing is allowed (in the worktree);
    the project's real clone is denied so an absolute path can never land a change in it (the lesson of
    marvin #41's executor writing into the real checkout)."""
    ex = profile.get("executor") or {}
    allowed = ["Read", "Edit", "Write", "Bash(git status*)", *ex.get("allowed_tools", [])]
    denied = []
    if clone is not None:
        denied = [f"Write({clone}/**)", f"Edit({clone}/**)"]
    return ",".join(allowed), ",".join(denied)


def executor_notes(profile: dict) -> str:
    return (profile.get("executor") or {}).get("notes", "")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        for p in all_profiles():
            print(f"{p['repo']:<36} dispatch={p['dispatch']:<4} machines={','.join(p['machines']) or '-':<24} tiers={','.join(t['id'] for t in p['verify'])}")
        return 0
    if cmd == "selftest" and len(sys.argv) > 2:
        profile = load_profile(sys.argv[2])
        if profile is None:
            print(f"no profile for {sys.argv[2]}", file=sys.stderr)
            return 1
        print(f"profile ok. missing on this machine: {missing_here(profile) or 'nothing'}")
        r = selftest(profile)
        if not r["ok"]:
            print("SELFTEST FAILED:", r["error"])
            return 1
        print(f"clone      {r['clone']}\nmetrics    {r['metrics']}")
        for n in r["notes"]:
            print("note      ", n)
        print("\n--- the PR body the pipeline would raise ---\n" + r["pr_body"])
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
