#!/usr/bin/env python3
"""Per-project execution profiles: how the ticket pipeline builds, tests and verifies a project that is
not marvin (CONTEXT.md "Per-project execution profiles"). A profile is a JSON file in
config/projects/ that says where the project's clone is, which machines can run it, what environment its
toolchain needs, how a ticket is verified (tiers: command, parser, required/optional) and what the headless
model may run. marvin itself keeps its built-in path and has no profile.

    project_profile.py list                 profiles and whether dispatch is on
    project_profile.py selftest <repo> [ref]  dry run in a throwaway worktree: no model call, no GitHub writes
    project_profile.py gate-info <repo>     what the dashboard's merge gate needs (JSON)
    project_profile.py verify <repo> <dir>  run the required checks in a worktree; exit 0 clean, 1 failed, 3 tool missing
"""
from __future__ import annotations
import copy
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence_capture import TestTimedOut  # noqa: E402

PROFILES_DIR = Path.home() / ".agents" / "config" / "projects"
PIPELINE_CLONES = Path.home() / ".agents-pipeline-clones"  # dedicated clones: not a working copy, not in iCloud
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


_VITEST_RE = re.compile(r"Tests\s+(?:(\d+) failed\s*\|\s*)?(?:(\d+) skipped\s*\|\s*)?(?:(\d+) passed)?(?:\s*\|\s*(\d+) skipped)?\s*\((\d+)\)")


def parse_vitest(output: str) -> dict | None:
    """vitest's summary line: 'Tests  2 failed | 17 passed | 1 skipped (20)'."""
    m = None
    for m in _VITEST_RE.finditer(output):
        pass
    if m is None:
        return None
    failed, skipped_a, passed, skipped_b, total = m.groups()
    failed, passed, total = int(failed or 0), int(passed or 0), int(total)
    skipped = int(skipped_a or skipped_b or 0)
    return {"total": total, "failed": failed, "skipped": skipped, "passed": passed}


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
    if parser == "vitest":
        return parse_vitest(output)
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
    profile.setdefault("clone_mode", "catalog")  # "catalog" = the live working copy; "pipeline" = a dedicated clone
    profile.setdefault("generated", [])  # files a tool rebuilds; see generated_paths.py
    for g in profile["generated"]:
        if not isinstance(g, dict) or not g.get("path") or not isinstance(g.get("regenerate", []), list):
            raise ValueError(f"{source}: each generated entry needs a path, and regenerate (if any) must be a command list")
    profile.setdefault("setup", [])
    for st in profile["setup"]:
        if "command" not in st or "id" not in st:
            raise ValueError(f"{source}: setup step needs an id and a command")
        st.setdefault("label", st["id"])
        st.setdefault("cwd", ".")
        st.setdefault("requires", [])
        st.setdefault("timeout_s", 1800)
    profile.setdefault("merge_from_dashboard", False)  # approving/denying its PRs in MR Review is opt-in too
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


def _token_env() -> dict:
    """GH_TOKEN from the pipeline's shared token file, so a clone/fetch authenticates as the pipeline does."""
    try:
        import project_catalog
        return project_catalog.run_env()
    except Exception:  # noqa: BLE001
        return dict(os.environ)


def pipeline_clone_path(profile: dict) -> Path:
    return PIPELINE_CLONES / profile["repo"].split("/")[-1]


def resolve_clone(profile: dict, catalog: dict | None = None, ensure: bool = False) -> Path | None:
    """The clone the pipeline works from on THIS machine.
    clone_mode "catalog" (default): the project's live working copy (catalog's newest local path, then the
    profile's hints). clone_mode "pipeline": a dedicated clone under ~/.agents-pipeline-clones, never a
    person's working copy and never inside iCloud (a clone of an iCloud-synced folder took minutes and can
    stall; the same repo cloned from GitHub takes under a second). With ensure=True a missing pipeline clone
    is created; without it, None."""
    if profile.get("clone_mode") == "pipeline":
        path = pipeline_clone_path(profile)
        if (path / ".git").exists():
            return path
        if not ensure:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(["gh", "repo", "clone", profile["repo"], str(path), "--", "-q"], capture_output=True, text=True,
                              timeout=600, env=_token_env())
        return path if proc.returncode == 0 and (path / ".git").exists() else None
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


def ignore_in_clone(clone: Path, patterns: list[str]) -> None:
    """Add names to the clone's own exclude file (shared by all its worktrees). A dependency folder that is a
    symlink escapes a "node_modules/" ignore rule (git sees a file, not a directory), so the bare name is
    excluded here and `git add -A` can never commit it."""
    exclude = clone / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    have = exclude.read_text().splitlines() if exclude.exists() else []
    add = [p for p in patterns if p not in have]
    if add:
        exclude.write_text("\n".join(have + add) + "\n")


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
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        stdout, stderr = proc.communicate()
        output = (stdout or "") + (stderr or "")
        raise TestTimedOut(cmd, timeout, output)
    return proc.returncode, (stdout or "") + (stderr or "")


def _failure_lines(output: str, limit: int = 60) -> list[str]:
    """The lines that say what failed, kept from the FULL output (a long mostly-green run would otherwise
    push them out of any tail we keep)."""
    return [l.strip() for l in output.splitlines() if re.search(r"\bfailed\b|error:|FAIL", l)][:limit]


class Measurer:
    """Callable with the shape `execute_ticket` expects of `measure`: worktree -> metrics. Also keeps what
    it saw (`report`) so the PR can say exactly what was and was not verified."""

    def __init__(self, profile: dict, runner=_default_runner, have=None, env: dict | None = None):
        self.profile = _validate(copy.deepcopy(profile), "profile")  # same defaults as a loaded profile
        self.runner = runner
        self.env = env if env is not None else build_env(self.profile)
        self.have = have or (lambda cap, e: globals()["have"](cap, e))
        self.report: dict = {"tiers": [], "notes": []}
        self.last_output = ""

    def __call__(self, worktree: Path) -> dict:
        metrics: dict = {}
        passed = failed = 0
        self.report = {"tiers": [], "notes": []}
        self._setup(Path(worktree))
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
            try:
                rc, out = self.runner(t["command"], Path(worktree) / t["cwd"], self.env, t["timeout_s"])
            except TestTimedOut as exc:
                raise TestTimedOut(exc.command, exc.timeout_s, exc.partial_output) from exc
            parsed = parse_output(t["parser"], out, rc)
            if parsed is None:
                if any(m in out.lower() for m in _NO_TESTS_MARKERS):
                    parsed = {"total": 0, "failed": 0, "skipped": 0, "passed": 0}
                else:
                    self.last_output = out
                    if "missing script" in out.lower():  # npm: the project has no such script at all
                        raise MeasureError(f"{t['label']} cannot run: this project has no test command yet "
                                           f"(npm says: {out.strip().splitlines()[0][:120] if out.strip() else 'missing script'}). "
                                           f"Add the script, or land the change that adds it, before this can be verified.")
                    raise MeasureError(f"{t['label']} produced no result (crashed or never ran): ...{out[-300:].strip()}")
            row.update(ran=True, output_tail=out[-3000:], failure_lines=_failure_lines(out), **parsed)
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

    def _setup(self, worktree: Path) -> None:
        """Dependency steps a fresh worktree needs before its checks can run (e.g. installing packages).
        A step whose `creates` path already exists is skipped, so the second measurement is free."""
        for st in self.profile.get("setup", []):
            if st.get("creates") and (worktree / st["creates"]).exists():
                continue
            missing = [c for c in st["requires"] if not self.have(c, self.env)]
            if missing:
                raise EnvMissing(st["id"], missing)
            try:
                rc, out = self.runner(st["command"], worktree / st["cwd"], self.env, st["timeout_s"])
            except TestTimedOut as exc:
                raise TestTimedOut(exc.command, exc.timeout_s, exc.partial_output) from exc
            if rc != 0:
                raise MeasureError(f"setup step '{st['label']}' failed: ...{out[-400:].strip()}")

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


# ── what the merge gate asks of a profile ───────────────────────────────────

def gate_info(profile: dict, catalog: dict | None = None, have=None) -> dict:
    """Everything the dashboard's merge gate needs to know to rebase and retest one of this project's PRs."""
    profile = _validate(copy.deepcopy(profile), "profile")
    clone = resolve_clone(profile, catalog if catalog is not None else _catalog(), ensure=True)
    env = build_env(profile)
    check = have or (lambda cap, e: globals()["have"](cap, e))
    missing: list[str] = []
    for t in profile["verify"]:
        if t["required"] and t.get("enabled") is not False:
            missing += [c for c in t["requires"] if not check(c, env) and c not in missing]
    return {"repo": profile["repo"], "clone": str(clone) if clone else None, "base_branch": profile["base_branch"],
            "merge_from_dashboard": profile["merge_from_dashboard"], "missing_here": missing,
            "generated": profile["generated"]}


def _failure_digest(tiers: list[dict], limit: int = 4000) -> str:
    """The failing lines first, then the tail of the output."""
    chunks = []
    for t in tiers:
        lines = t.get("failure_lines", [])
        chunks.append("\n".join(lines[:40]) + ("\n...\n" if lines else "") + t.get("output_tail", "")[-1500:])
    return "\n".join(chunks)[:limit]


def _classify_measurement(tiers: list[dict]) -> dict:
    """Classify a measurement result from tiers into kind and summary.
    Returns {"kind": "passed"|"failed", "summary": str, "bad": [tiers...]}.
    This logic is shared between verify_dir and selftest."""
    bad = []
    for t in tiers:
        if not t.get("ran"):
            continue
        if t.get("build_ok") == 0:
            bad.append(t)
        elif t.get("failed"):
            bad.append(t)
    ran = [t for t in tiers if t.get("ran")]
    if bad:
        summary = "; ".join(f"{t['label']}: " + ("build failed" if "build_ok" in t else f"{t['failed']} failed of {t['total']}") for t in bad)
        return {"kind": "failed", "summary": summary, "bad": bad}
    summary = "; ".join(f"{t['label']}: " + ("build ok" if "build_ok" in t else f"{t['passed']} passed") for t in ran)
    return {"kind": "passed", "summary": summary, "bad": []}


def verify_dir(profile: dict, directory: Path, runner=_default_runner, have=None) -> dict:
    """Run the profile's checks in `directory` (the gate's scratch worktree) and say whether it is clean.
    kind: passed | failed | env_missing (this machine lacks a tool: not the PR's fault) | error (a check
    crashed without a result)."""
    m = Measurer(profile, runner=runner, have=have)
    try:
        metrics = m(Path(directory))
    except EnvMissing as e:
        return {"ok": False, "kind": "env_missing", "summary": str(e), "tiers": [], "output_tail": ""}
    except TestTimedOut as e:
        mins = max(1, round(e.timeout_s / 60))
        return {"ok": False, "kind": "error", "summary": f"Check did not finish within {mins} min and was killed", "tiers": m.report["tiers"], "output_tail": e.partial_output[-3000:]}
    except MeasureError as e:
        return {"ok": False, "kind": "error", "summary": str(e).split(": ...")[0], "tiers": m.report["tiers"], "output_tail": m.last_output[-3000:] or str(e)}
    classification = _classify_measurement(m.report["tiers"])
    ran = [t for t in m.report["tiers"] if t.get("ran")]
    if classification["kind"] == "failed":
        return {"ok": False, "kind": "failed", "summary": classification["summary"], "tiers": ran, "output_tail": _failure_digest(classification["bad"])}
    return {"ok": True, "kind": "passed", "summary": classification["summary"], "tiers": ran, "output_tail": ""}


# ── selftest ────────────────────────────────────────────────────────────────

def _cleanup_worktree(clone: Path, worktree: Path, branch: str) -> None:
    subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=clone, capture_output=True)
    subprocess.run(["git", "branch", "-D", branch], cwd=clone, capture_output=True)


def selftest(profile: dict, runner=_default_runner, have=None, catalog: dict | None = None, ref: str | None = None) -> dict:
    """Everything a real ticket does EXCEPT the model call and any GitHub write: find the clone, make a real
    worktree from the base branch, run the required checks for real (the baseline), and build the PR body the
    pipeline would raise. Always removes the worktree and branch it made."""
    import mr_raiser
    import sandbox_orchestration as so
    import metrics_registry as mr

    profile = _validate(copy.deepcopy(profile), "profile")
    clone = resolve_clone(profile, catalog if catalog is not None else _catalog(), ensure=True)
    if clone is None:
        return {"ok": False, "kind": "no_clone", "error": f"no local clone of {profile['repo']} on this machine"}
    ticket_ref = f"{profile['repo']}#999999"
    branch = f"pipeline/{ticket_ref.lower()}"
    measurer = Measurer(profile, runner=runner, have=have)
    # Fail fast on a machine that cannot run the required checks: no worktree, no git, nothing to clean up.
    lacking = []
    for t in profile["verify"]:
        if t["required"] and t.get("enabled") is not False:
            lacking += [c for c in t["requires"] if not measurer.have(c, measurer.env) and c not in lacking]
    if lacking:
        return {"ok": False, "kind": "env_missing", "error": f"this machine lacks {', '.join(lacking)}, which the required checks need", "clone": str(clone)}
    worktree = None
    try:
        worktree = so._create_worktree(clone, ticket_ref, ref or profile["base_branch"])
        baseline = measurer(worktree)
        # Check if the measured tiers actually passed
        classification = _classify_measurement(measurer.report["tiers"])
        if classification["kind"] == "failed":
            return {"ok": False, "kind": "failed", "error": classification["summary"], "clone": str(clone)}
        comparison = mr.compare("selftest", baseline, baseline)
        test_results, dev = measurer.evidence()
        if test_results is not None:
            test_results["notes"] = measurer.pr_note()
        body = (f"Closes {ticket_ref}\n\n## Metrics Comparison\n\n{mr_raiser._format_comparison(comparison)}\n\n"
                f"## Test Results\n\n{mr_raiser._format_test_results(test_results)}\n\n"
                f"## Dev Environment Evidence\n\n{mr_raiser._format_dev_evidence(dev)}")
        return {"ok": True, "kind": "passed", "clone": str(clone), "worktree": str(worktree), "metrics": {k: v["value"] for k, v in baseline.items()},
                "tiers": measurer.report["tiers"], "notes": measurer.report["notes"], "pr_body": body}
    except EnvMissing as e:
        return {"ok": False, "kind": "env_missing", "error": str(e), "clone": str(clone)}
    except (MeasureError, Exception) as e:  # noqa: BLE001
        return {"ok": False, "kind": "error", "error": str(e), "clone": str(clone)}
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

# Read-only inspection every headless agent (planner and executor, every project) may run (Gil, 2026-10-08,
# marvin#277). Before this, 59% of all failed tool calls were agents refused by their own allowlist: the repo
# CLAUDE.md tells them to `graphify query` first, and they naturally reach for `gh pr view` / `git log`.
# Claude Code checks each part of a compound command, so `git log && git push` is still refused.
# Never add a subcommand that writes, pushes, deletes or edits GitHub state (tested).
READ_ONLY_INSPECTION_TOOLS = (
    "Bash(graphify query*)", "Bash(graphify path*)", "Bash(graphify explain*)",
    "Bash(gh issue view*)", "Bash(gh issue list*)", "Bash(gh pr view*)", "Bash(gh pr list*)",
    "Bash(gh pr diff*)", "Bash(gh pr checks*)", "Bash(gh repo view*)", "Bash(gh run view*)", "Bash(gh run list*)",
    "Bash(git status*)", "Bash(git log*)", "Bash(git diff*)", "Bash(git show*)", "Bash(git blame*)",
    "Bash(git ls-files*)", "Bash(git rev-parse*)", "Bash(git grep*)",
)

def executor_tools(profile: dict, clone: Path | None = None) -> tuple[str, str]:
    """(allowed, disallowed) tool strings for the execution call. Editing is allowed (in the worktree);
    the project's real clone is denied so an absolute path can never land a change in it (the lesson of
    marvin #41's executor writing into the real checkout)."""
    ex = profile.get("executor") or {}
    allowed = ["Read", "Edit", "Write", *READ_ONLY_INSPECTION_TOOLS, *ex.get("allowed_tools", [])]
    denied = list(ex.get("denied_tools", []))
    if clone is not None:
        denied += [f"Write({clone}/**)", f"Edit({clone}/**)"]
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
        r = selftest(profile, ref=sys.argv[3] if len(sys.argv) > 3 else None)
        if not r["ok"]:
            print("SELFTEST FAILED:", r["error"])
            return 1
        print(f"clone      {r['clone']}\nmetrics    {r['metrics']}")
        for n in r["notes"]:
            print("note      ", n)
        print("\n--- the PR body the pipeline would raise ---\n" + r["pr_body"])
        return 0
    if cmd == "gate-info" and len(sys.argv) > 2:
        profile = load_profile(sys.argv[2])
        print(json.dumps(gate_info(profile) if profile else {"profile": False}))
        return 0
    if cmd == "verify" and len(sys.argv) > 3:
        profile = load_profile(sys.argv[2])
        if profile is None:
            print(f"no profile for {sys.argv[2]}", file=sys.stderr)
            return 2
        r = verify_dir(profile, Path(sys.argv[3]))
        if r["ok"]:
            print(json.dumps(r))
            return 0
        print(f"{r['summary']}\n\n{r['output_tail']}", file=sys.stderr)
        return 3 if r["kind"] == "env_missing" else 1
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
