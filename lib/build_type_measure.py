#!/usr/bin/env python3
"""Build-type ticket measure() for sandbox_orchestration.execute_ticket
(G-Eskayo/marvin#90).

A build-type ticket (a new feature/tab/flag with no prior baseline to
tune -- see CONTEXT.md's "Build-type ticket" glossary entry) has no real
metric to improve, unlike a tunable-subsystem ticket. `measure()` here
feeds metrics_registry.compare()'s existing interface a mechanical
pass/fail-style signal instead: raw tests_passed/tests_failed counts, so
"improved" means "more tests pass and nothing newly fails" -- not a
fabricated tunable metric, and not a passing fraction either (a fraction
can't tell "added new passing tests to an already-100%-passing suite"
from "nothing changed," both read as 1.0 -> 1.0; a real dispatch,
G-Eskayo/marvin#21, hit exactly this).

Reuses evidence_capture.capture_test_results/parse_test_output (G-Eskayo/
marvin#76) for the actual subprocess-run-and-parse work rather than
re-deriving it -- this module only adds the test-command selection and
the metrics_registry shaping on top.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence_capture import capture_test_results, TestTimedOut  # noqa: E402

VENV_PYTHON = str(Path.home() / ".agents" / "venv" / "bin" / "python")


def _touched_files(worktree_path: Path, base_branch: str = "main") -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_branch}...HEAD"],
        cwd=worktree_path, capture_output=True, text=True,
    )
    return result.stdout.splitlines()


def _touches_dashboard(touched: list[str]) -> bool:
    return any(f.startswith("dashboard/") for f in touched)


def _scope_root(touched_file: str) -> str:
    """One touched file -> the pytest path arg it implies. `skills/` gets
    two path components (skills/paper-dive, not all of skills/ -- that'd
    still pull in every other skill's tests) since it's a shared
    namespace for otherwise-unrelated areas; everything else gets one
    (lib, bench, brain-map, ...)."""
    parts = touched_file.split("/")
    if parts[0] == "skills" and len(parts) > 1:
        return "/".join(parts[:2])
    return parts[0]


def parallel_args(env: dict | None = None, have_xdist: bool | None = None, workers=None) -> list[str]:
    """pytest-xdist workers for a build's test step, sized to free memory like the merge gate's (#940), or [] where
    xdist is missing. Run serially, `pytest -q lib` outgrew the 1200 s evidence limit (it took 10-11 min on 10-22 and
    timed out on every marvin build from 10-31 to 11-02, #995); CI and the gate already run the suite in parallel."""
    import os
    env = os.environ if env is None else env
    if have_xdist is None:
        import importlib.util
        have_xdist = importlib.util.find_spec("xdist") is not None
    if not have_xdist:
        return []
    n = env.get("MARVIN_TEST_WORKERS", "")
    if not (n.isdigit() and int(n) > 0):
        try:
            import test_slot
            n = str((workers or test_slot.workers)())
        except Exception:  # noqa: BLE001 - an unreadable count still runs in parallel, never serially by accident
            n = "auto"
    return ["-n", n]


def test_command_for(worktree_path: Path, base_branch: str = "main", parallel: list[str] | None = None) -> list[str]:
    """Which test command matches what this ticket's diff actually
    touches, scoped rather than always running the entire repo's tests --
    a real live-fire dispatch (G-Eskayo/marvin#21) found this the hard
    way: an unrelated, pre-existing test-collection failure elsewhere in
    the repo made the whole-repo baseline read 0.0, and "fixing" that
    unrelated collection error registered as a false-positive
    "improvement" for a ticket that was never actually implemented.
    A single list (not a (command, cwd) pair) so this composes directly
    with capture_test_results's cwd=worktree_path-always signature --
    the dashboard case cd's internally via a wrapped shell command."""
    touched = _touched_files(worktree_path, base_branch)
    par = parallel_args() if parallel is None else parallel
    if _touches_dashboard(touched):
        return ["bash", "-c", "cd dashboard && npx vitest run"]

    roots = sorted({_scope_root(f) for f in touched if f})
    existing_roots = [r for r in roots if (worktree_path / r).is_dir()]
    if not existing_roots:
        # Nothing changed, or nothing maps to a real code directory (e.g.
        # docs/adr/*.md-only) -- no scoped target to run, fall back to
        # the whole suite rather than silently running nothing.
        return [VENV_PYTHON, "-m", "pytest", "-q", *par]
    return [VENV_PYTHON, "-m", "pytest", "-q", *par, *existing_roots]


def _ensure_dashboard_deps(worktree_path: Path) -> None:
    """A fresh worktree has no node_modules, so vitest would fail wholesale on
    missing deps rather than on anything the ticket did -- the same gap that
    made PR #119's merge gate report a 'massive error' (webhook-server/
    merge.js). Install once; the second measure() in a ticket's run finds
    node_modules already present and skips this."""
    dashboard = worktree_path / "dashboard"
    if (dashboard / "node_modules").is_dir():
        return
    import node_modules_seed  # #687: seeded from the cache, so the install writes almost nothing
    node_modules_seed.npm_install(dashboard, ["npm", "install", "--no-audit", "--no-fund"],
                                  capture_output=True, text=True, timeout=600)


def _measure_commands(worktree_path: Path) -> list[list[str]]:
    """The commands measure() runs. Deliberately NOT derived from the ticket's
    diff: the baseline is taken before the executor edits anything (empty diff)
    and the current reading after, so any diff-dependent choice made the two
    readings run different tests. Found 2026-10-01: baseline = whole suite
    (540 passed), current after a change under skills/research = `pytest -q
    skills/research` (0 tests, 'regressed' in 1s); a dashboard ticket compared
    pytest to vitest. Same fixed set both times, whatever the diff."""
    commands = [[VENV_PYTHON, "-m", "pytest", "-q"]]
    if (worktree_path / "dashboard" / "package.json").is_file():
        commands.append(["bash", "-c", "cd dashboard && npx vitest run"])
    return commands


class MeasureError(RuntimeError):
    """A suite crashed without producing a test summary. Raised instead of
    reporting 0 so a broken environment can't masquerade as a result."""


# A runner's own statement that it found nothing to run -- a legitimate 0
# (e.g. a brand-new subsystem), unlike a traceback or "command not found".
_NO_TESTS_MARKERS = ("no tests ran", "no test files found")


def _suite_label(command: list[str]) -> str:
    return "vitest" if any("vitest" in part for part in command) else "pytest"


def measure(worktree_path: Path) -> dict:
    """metrics_registry.compare()-shaped measure() for build-type
    tickets. Returns two separate counts -- tests_passed (higher is
    better) and tests_failed (lower is better) -- rather than one
    passing fraction. A real live-fire dispatch (G-Eskayo/marvin#21)
    found the fraction was blind to a common, legitimate case: a ticket
    that adds new passing tests to an already-100%-passing suite (34/34
    -> 37/37) is still 1.0 -> 1.0, registering as "unchanged" even though
    real, correct work landed. Two counts let metrics_registry.compare()'s
    existing per-metric direction logic see the added passing tests as a
    real improvement, while still catching an actual regression (failed
    count going up) as not passing -- something one fraction can't do.

    Counts are summed across the whole pytest suite and, when the repo has a
    dashboard, the whole vitest suite -- the same fixed set on every call (see
    `_measure_commands`), so a baseline and a later reading are comparable.
    Each suite's own counts are also recorded (`pytest_passed`, `vitest_failed`,
    ...) so a suite that contributes nothing is visible in the data -- found
    2026-10-01 when #41's baseline read 544 against a clean 684.

    Raises MeasureError if a suite produced no summary and did not say it found
    nothing to run: a crash is an error, not a zero. Raises TestTimedOut if a
    suite exceeded its timeout."""
    import cleanup_sweep

    commands = _measure_commands(worktree_path)
    if len(commands) > 1:
        _ensure_dashboard_deps(worktree_path)
    metrics: dict = {}
    passed = failed = 0
    for command in commands:
        label = _suite_label(command)
        if label == "pytest":
            with cleanup_sweep.disposable_basetemp() as basetemp_args:
                parsed = capture_test_results(worktree_path, command + basetemp_args)
        else:
            parsed = capture_test_results(worktree_path, command)
        if parsed.get("passed") is None and parsed.get("failed") is None:
            tail = parsed.get("output_tail") or ""
            if not any(marker in tail.lower() for marker in _NO_TESTS_MARKERS):
                raise MeasureError(
                    f"{label} produced no test summary (crashed or never ran): "
                    f"...{tail[-300:].strip()}"
                )
        suite_passed = parsed.get("passed") or 0
        suite_failed = parsed.get("failed") or 0
        metrics[f"{label}_passed"] = {"value": suite_passed, "higher_is_better": True}
        metrics[f"{label}_failed"] = {"value": suite_failed, "higher_is_better": False}
        passed += suite_passed
        failed += suite_failed
    metrics["tests_passed"] = {"value": passed, "higher_is_better": True}
    metrics["tests_failed"] = {"value": failed, "higher_is_better": False}
    return metrics


# ── the affected tests, the same set before and after (marvin#1152) ─────────

# What the caller's environment may carry that would change which tests run: the gate's MARVIN_BASE, a selection
# file left over from an outer run. Both sides of a comparison are run without them, so only our selection counts.
_SELECTION_ENV = ("MARVIN_BASE", "MARVIN_SELECTED_TESTS")


def _git_out(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True, timeout=60).stdout


def _changed_since(worktree: Path, base_sha: str) -> list[str]:
    """Every path the change touches against the base commit: committed, staged, unstaged, deleted, and new files not
    yet added (the executor never commits). Raises CalledProcessError when git can't say."""
    tracked = _git_out(worktree, "diff", "--name-only", base_sha).split()
    new = _git_out(worktree, "ls-files", "--others", "--exclude-standard").split()
    return sorted(set(tracked) | set(new))


def _suite_reading(label: str, parsed: dict) -> tuple[int, int]:
    """(passed, failed) from one run, with measure()'s rule: a crash is an error, a runner's 'no tests ran' is 0."""
    if parsed.get("passed") is None and parsed.get("failed") is None:
        tail = parsed.get("output_tail") or ""
        if not any(marker in tail.lower() for marker in _NO_TESTS_MARKERS):
            raise MeasureError(f"{label} produced no test summary (crashed or never ran): ...{tail[-300:].strip()}")
    return parsed.get("passed") or 0, parsed.get("failed") or 0


def _metrics(suites: dict[str, tuple[int, int]]) -> dict:
    out: dict = {}
    for label, (p, f) in suites.items():
        out[f"{label}_passed"] = {"value": p, "higher_is_better": True}
        out[f"{label}_failed"] = {"value": f, "higher_is_better": False}
    out["tests_passed"] = {"value": sum(p for p, _ in suites.values()), "higher_is_better": True}
    out["tests_failed"] = {"value": sum(f for _, f in suites.values()), "higher_is_better": False}
    return out


class PairedMeasure:
    """The measure for a marvin ticket: the Python tests its change can affect (lib/affected_tests.select, the
    selection the merge gate and CI run), never the whole ~5,700-test suite that timed out the verify step on almost
    every ticket (103 times on the Mini).

    The selection depends on the change, which doesn't exist when execute_ticket takes its baseline. So the first call
    (the untouched worktree) only pins the base commit and runs vitest there. Each later call computes ONE selection
    from the change, runs it on the change and, in a throwaway detached worktree, on the base commit, and
    `paired_baseline()` names that base reading: before and after always ran the identical command on the identical
    list. A test the change adds is in the list but absent at the base (a real improvement); a test it deletes is
    left out on both sides. Whenever the selection can't be trusted (a change to how tests run, a change git can't
    read), both sides run everything; a base that can't be pinned at all falls back to measure() on both sides.
    A base reading is cached per selection, so a later iteration with the same reach doesn't rerun it."""

    def __init__(self):
        self.base_sha: str | None = None
        self.full = False                       # no pinned base: measure() (everything) on both sides
        self._started = False
        self._vitest_base: tuple[int, int] | None = None
        self._base_cache: dict = {}
        self._paired: dict | None = None
        self._last: dict | None = None          # {"selection", "passed", "failed"} of the last reading after the change

    # ── execute_ticket's interface ─────────────────────────────────────────
    def __call__(self, worktree_path: Path) -> dict:
        wt = Path(worktree_path)
        if not self._started:
            self._started = True
            try:
                self.base_sha = _git_out(wt, "rev-parse", "HEAD").strip() or None
            except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
                self.base_sha = None
            if self.base_sha is None:
                print("[measure] cannot pin the base commit; measuring every test before and after", file=sys.stderr)
                self.full = True
                self._paired = measure(wt)
                return self._paired
            suites = {}
            if self._has_dashboard(wt):
                self._vitest_base = self._vitest(wt)
                suites["vitest"] = self._vitest_base
            return _metrics(suites) if suites else {}
        if self.full:
            return measure(wt)
        selection = self._selection(wt)
        after = {"pytest": self._pytest(wt, selection)}
        if self._vitest_base is not None:
            after["vitest"] = self._vitest(wt)
        key = None if selection is None else tuple(selection)
        if key not in self._base_cache:
            self._base_cache[key] = self._pytest_at_base(wt, selection)
        base = {"pytest": self._base_cache[key]}
        if self._vitest_base is not None:
            base["vitest"] = self._vitest_base
        self._paired = _metrics(base)
        p, f = after["pytest"]
        self._last = {"selection": selection, "passed": p + after.get("vitest", (0, 0))[0],
                      "failed": f + after.get("vitest", (0, 0))[1], "vitest": "vitest" in after}
        return _metrics(after)

    def paired_baseline(self) -> dict | None:
        """The base reading on the same tests as the last call's (execute_ticket compares against this)."""
        return self._paired

    def test_results(self) -> dict | None:
        """The last reading after the change, in mr_raiser's test-results shape, so the PR doesn't run them again."""
        if self._last is None:
            return None
        sel = self._last["selection"]
        suite = "pytest (every test)" if sel is None else f"pytest ({len(sel)} test files the change can affect)"
        if self._last["vitest"]:
            suite += " + vitest"
        return {"suite": suite, "passed": self._last["passed"], "failed": self._last["failed"],
                "total": self._last["passed"] + self._last["failed"]}

    # ── pieces ─────────────────────────────────────────────────────────────
    @staticmethod
    def _has_dashboard(wt: Path) -> bool:
        return (wt / "dashboard" / "package.json").is_file()

    def _vitest(self, wt: Path) -> tuple[int, int]:
        _ensure_dashboard_deps(wt)
        return _suite_reading("vitest", capture_test_results(wt, ["bash", "-c", "cd dashboard && npx vitest run"]))

    def _selection(self, wt: Path) -> list[str] | None:
        """The test files to run on both sides, or None for all. Computed from the change alone."""
        import affected_tests
        try:
            changed = _changed_since(wt, self.base_sha)
        except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
            print(f"[measure] cannot tell what changed since {self.base_sha[:12]}; every test, both sides", file=sys.stderr)
            return None
        picked = affected_tests.select(wt, changed, untracked=True)
        if picked is None:
            return None
        return [p for p in picked if (wt / p).is_file()]   # a deleted test runs on neither side

    @staticmethod
    def _env(selection_file: str | None) -> dict:
        import os
        env = {k: v for k, v in os.environ.items() if k not in _SELECTION_ENV}
        if selection_file:
            env["MARVIN_SELECTED_TESTS"] = selection_file
        return env

    def _pytest(self, wt: Path, selection: list[str] | None) -> tuple[int, int]:
        import cleanup_sweep
        import os
        import tempfile
        path = None
        if selection is not None:
            fd, path = tempfile.mkstemp(prefix="marvin-paired-selection-", suffix=".txt")
            with os.fdopen(fd, "w") as f:
                f.write("\n".join(selection) + "\n")
        try:
            command = [VENV_PYTHON, "-m", "pytest", "-q", *parallel_args()]
            with cleanup_sweep.disposable_basetemp() as basetemp_args:
                parsed = capture_test_results(wt, command + basetemp_args, env=self._env(path))
            return _suite_reading("pytest", parsed)
        finally:
            if path:
                Path(path).unlink(missing_ok=True)

    def _pytest_at_base(self, wt: Path, selection: list[str] | None) -> tuple[int, int]:
        """The same selection on the pinned base commit, in a detached worktree removed afterwards."""
        import shutil
        import tempfile
        holder = Path(tempfile.mkdtemp(prefix="marvin-paired-base-"))
        base_wt = holder / "base"
        proc = subprocess.run(["git", "worktree", "add", "-q", "--detach", str(base_wt), self.base_sha],
                              cwd=wt, capture_output=True, text=True)
        try:
            if proc.returncode != 0:
                raise MeasureError(f"cannot check out the base commit {self.base_sha[:12]} to measure it: "
                                   f"{(proc.stderr or '').strip()[-300:]}")
            try:   # the same node_modules the ticket's worktree was seeded with, so a test that needs it sees it too
                import node_modules_seed
                node_modules_seed.seed_tree(base_wt)
            except Exception:  # noqa: BLE001 - a seed miss leaves the tree as a fresh worktree, as for the ticket
                pass
            return self._pytest(base_wt, selection)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(base_wt)], cwd=wt, capture_output=True)
            shutil.rmtree(holder, ignore_errors=True)
