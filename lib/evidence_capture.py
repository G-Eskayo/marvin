#!/usr/bin/env python3
"""Evidence capture for the MR pipeline (G-Eskayo/marvin#72, ADR 0024).

Captures real test-suite results (`capture_test_results`,
G-Eskayo/marvin#76) and, for UI-touching tickets, dev-environment
screenshot evidence (`ticket_touches_ui`/`capture_dev_evidence`,
G-Eskayo/marvin#77).

Kept as its own module rather than folded into
`sandbox_orchestration.execute_ticket`, whose own tune-and-compare-loop
interface and tests stay untouched by this addition: `mr_raiser.raise_mr`
calls into this module directly with the worktree path `execute_ticket`
already returned, rather than `execute_ticket` absorbing capture logic it
has no reason to know about.

`parse_test_output` is split out from `capture_test_results`, and
`ticket_touches_ui` from `capture_dev_evidence`, as pure logic
independently testable without a real subprocess run.
"""
from __future__ import annotations
import os
import re
import resource
import signal
import subprocess
from pathlib import Path
from typing import Callable


def parse_test_output(suite: str, output: str) -> dict:
    """Extract pass/fail/total from a test runner's real stdout+stderr.
    Recognizes pytest's summary line ("11 passed in 2.72s",
    "3 failed, 8 passed in 2.72s") and vitest's ("Tests  33 passed (33)",
    "Tests  30 passed | 3 failed (33)"). Returns
    {"suite", "passed", "failed", "total"} with all three None if no
    recognized summary line is found."""
    # vitest's summary line is distinctively prefixed with "Tests" (as
    # opposed to the "Test Files" line above it, which has its own,
    # different pass/fail counts) -- match that whole line first so its
    # counts aren't shadowed by "Test Files"'s.
    vitest_line = re.search(
        r"^\s*Tests\s+(\d+)\s+passed(?:\s*\|\s*(\d+)\s+failed)?\s*\((\d+)\)", output, re.MULTILINE
    )
    if vitest_line:
        passed = int(vitest_line.group(1))
        failed = int(vitest_line.group(2) or 0)
        total = int(vitest_line.group(3))
        return {"suite": suite, "passed": passed, "failed": failed, "total": total}

    # pytest's real summary is the LAST line of the form "... N passed ... in
    # 12.3s". Text earlier in the output (a failing test's assertion diff, a
    # printed fixture) can contain "N passed"/"N failed" too, so searching the
    # whole output for the first match misread a failing 544-test run as 7
    # passed / 4 failed (found 2026-10-01). Restrict to that line when present;
    # fall back to the whole output only if no such line exists.
    summary_lines = [
        line for line in output.splitlines()
        if re.search(r"\bin \d+(?:\.\d+)?s\b", line) and re.search(r"\d+\s+(?:passed|failed)", line)
    ]
    scope = summary_lines[-1] if summary_lines else output
    passed_match = re.search(r"(\d+)\s+passed", scope)
    failed_match = re.search(r"(\d+)\s+failed", scope)
    if not passed_match and not failed_match:
        return {"suite": suite, "passed": None, "failed": None, "total": None}

    passed = int(passed_match.group(1)) if passed_match else 0
    failed = int(failed_match.group(1)) if failed_match else 0
    return {"suite": suite, "passed": passed, "failed": failed, "total": passed + failed}


# macOS gives launchd children (the ticket-pipeline webhook server) and some
# interactive shells a 256-file soft limit, which a full pytest run exhausts
# ("OSError: Too many open files"). That turned ~10 unrelated tests into
# failures and made every ticket's baseline read 0 passed / 11 failed, so no
# ticket could register as "improved". Raise the *child's* floor here, the one
# choke point every measure()/evidence run goes through.
MIN_NOFILE_SOFT_LIMIT = 4096


def _raise_nofile_limit() -> None:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    target = MIN_NOFILE_SOFT_LIMIT if hard == resource.RLIM_INFINITY else min(MIN_NOFILE_SOFT_LIMIT, hard)
    if soft < target:
        resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))


class TestTimedOut(RuntimeError):
    """Test command exceeded timeout_s and was killed. Machine did not fail;
    the test suite ran out of time. Do not count as a failure of the ticket."""

    def __init__(self, command: list[str], timeout_s: int, partial_output: str):
        self.command = command
        self.timeout_s = timeout_s
        self.partial_output = partial_output
        last_line = [l.strip() for l in partial_output.splitlines() if l.strip()][-1:][0] if partial_output.strip() else ""
        cmd_hint = last_line or " ".join(command)
        super().__init__(f"timed out after {timeout_s}s running {cmd_hint}")


def capture_test_results(worktree_path: Path, test_command: list[str], timeout_s: int = 1200) -> dict:
    """Run the ticket's real test command inside worktree_path and parse
    its output. `test_command` is caller-supplied (e.g.
    ["pytest", "-q"] or ["npx", "vitest", "run"]) since different
    subsystems use different runners -- this module has no way to know
    which one a given ticket needs.

    Raises TestTimedOut if the command exceeds timeout_s."""
    proc = subprocess.Popen(
        test_command, cwd=worktree_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True, preexec_fn=_raise_nofile_limit,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        stdout, stderr = proc.communicate()
        output = (stdout or "") + (stderr or "")
        raise TestTimedOut(test_command, timeout_s, output)

    output = (stdout or "") + (stderr or "")
    parsed = parse_test_output(" ".join(test_command), output)
    parsed["output_tail"] = output[-600:]
    return parsed


# UI-associated path prefixes for dev-evidence gating (ADR 0024). A direct
# check on the diff, not a general classifier -- the one narrow built-in
# exception to "every evidence section always required" in v1.
UI_PATH_PREFIXES = ("dashboard/src/", "dashboard/electron/")


def _is_ui_path(changed_file: str) -> bool:
    return any(changed_file.startswith(prefix) for prefix in UI_PATH_PREFIXES)


def ticket_touches_ui(worktree_path: Path, base_branch: str = "main") -> bool:
    """True if this ticket's diff (against base_branch) includes any file
    under a UI-associated path."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_branch}...HEAD"],
        cwd=worktree_path, capture_output=True, text=True,
    )
    return any(_is_ui_path(f) for f in result.stdout.splitlines())


def _default_capture_screenshot(worktree_path: Path) -> str:
    """Real default: builds the dashboard and drives it headlessly via
    dashboard/scripts/capture_screenshot.mjs (playwright-core +
    Playwright's _electron launcher -- same pattern as the `run` skill's
    Electron driver examples), saving the screenshot into the worktree
    itself so it rides along in mr_raiser._commit_and_push's existing
    `git add -A` rather than needing a separate upload mechanism. Returns
    the screenshot's path relative to worktree_path, suitable for a
    PR-body markdown image reference."""
    dashboard_dir = worktree_path / "dashboard"
    relative_output = Path("docs") / "evidence" / f"{worktree_path.name}.png"
    output_path = worktree_path / relative_output

    subprocess.run(["npm", "install"], cwd=dashboard_dir, check=True, capture_output=True)
    subprocess.run(["npm", "run", "build"], cwd=dashboard_dir, check=True, capture_output=True)
    subprocess.run(
        ["node", "scripts/capture_screenshot.mjs", str(output_path)],
        cwd=dashboard_dir, check=True, capture_output=True,
    )
    return str(relative_output)


# ── UI changes carry images (marvin #374) ────────────────────────────────────
# The same rules as dashboard/webhook-server/ui_evidence.js (which refuses Approve on a UI change with no image), so
# "the pipeline captured screenshots" and "the gate lets it merge" agree on what counts as a UI change. A project adds
# its own paths with evidence.ui_paths in its profile.
DEFAULT_UI_PATTERNS = (
    "dashboard/src/*", "dashboard/src/components/**", "dashboard/src/assets/**", "**/*.xcassets/**", "**/*.xcstrings", "**/*.storyboard", "**/*.xib",
    "**/*View.swift", "**/Views/**/*.swift", "**/*.jsx", "**/*.tsx", "**/*.css", "**/*.html",
)


def glob_to_regex(glob: str) -> re.Pattern:
    """'**/' matches zero or more folders, '**' anything, '*' anything but a slash; everything else is literal."""
    out, i = "", 0
    while i < len(glob):
        c = glob[i]
        if glob.startswith("**/", i):
            out += "(?:.*/)?"; i += 3; continue
        if glob.startswith("**", i):
            out += ".*"; i += 2; continue
        out += "[^/]*" if c == "*" else re.escape(c)
        i += 1
    return re.compile(f"^{out}$")


def ui_files(files, extra_patterns=()) -> list[str]:
    own = [p for p in (extra_patterns or []) if isinstance(p, str) and p]
    patterns = [glob_to_regex(p) for p in (*DEFAULT_UI_PATTERNS, *own)]
    return [f for f in (files or []) if isinstance(f, str) and f and any(r.match(f) for r in patterns)]


def changed_files(worktree_path: Path, base_branch: str = "main") -> list[str]:
    result = subprocess.run(["git", "diff", "--name-only", f"{base_branch}...HEAD"], cwd=worktree_path,
                            capture_output=True, text=True)
    return result.stdout.splitlines()


def _run_checked(run, cmd, cwd=None):
    try:
        return run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        detail = "\n".join(str(x) for x in (e.stderr, e.output) if x)
        lines = [l.strip() for l in detail.splitlines() if "error" in l.lower()] or [l.strip() for l in detail.splitlines() if l.strip()]
        raise RuntimeError(f"{cmd[0]} failed: {' / '.join(lines[-2:])[:300]}") from e


def capture_ios_simulator(worktree_path: Path, cfg: dict, run=subprocess.run, sleep=None) -> list[dict]:
    """Builds an iOS app for the simulator (signing off), launches each configured scene (launch arguments, e.g. a
    debug-only demo mode) in light and dark, and screenshots it into the worktree, so the images ride along in the
    pipeline's commit. Proven by hand on the Mac Mini on 2026-10-09. Returns [{path (relative), caption}]. Raises
    ValueError for an incomplete config and RuntimeError (with the tool's own error line) when a step fails.
    simctl cannot tap or rotate, so scenes are reached through launch arguments only."""
    import tempfile
    import time
    sleep = sleep or time.sleep
    required = ("project_dir", "project", "scheme", "simulator", "bundle_id")
    if not isinstance(cfg, dict) or any(not cfg.get(k) for k in required) or not cfg.get("scenes"):
        raise ValueError(f"evidence.dev.ios_simulator needs {', '.join(required)} and at least one scene")
    project_dir = Path(worktree_path) / cfg["project_dir"]
    for cmd in cfg.get("prepare", []):
        _run_checked(run, list(cmd), cwd=project_dir)
    configuration = cfg.get("configuration", "Debug")
    derived = Path(tempfile.mkdtemp(prefix="ios-evidence-"))
    _run_checked(run, ["xcodebuild", "-project", cfg["project"], "-scheme", cfg["scheme"],
                       "-destination", f"platform=iOS Simulator,name={cfg['simulator']}", "-configuration", configuration,
                       "CODE_SIGNING_ALLOWED=NO", "-derivedDataPath", str(derived), "build"], cwd=project_dir)
    apps = sorted((derived / "Build" / "Products" / f"{configuration}-iphonesimulator").glob("*.app"))
    if not apps:
        raise RuntimeError("xcodebuild failed: no .app was built for the simulator")
    try:
        run(["xcrun", "simctl", "boot", cfg["simulator"]], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        # Already running is fine. simctl says so on a different line from its "error" line, so read all of it.
        if "current state: booted" not in f"{e.stderr or ''}\n{e.output or ''}".lower():
            _run_checked(run, ["xcrun", "simctl", "boot", cfg["simulator"]])
    _run_checked(run, ["xcrun", "simctl", "install", "booted", str(apps[0])])
    out_dir = Path("docs") / "evidence" / Path(worktree_path).name
    (Path(worktree_path) / out_dir).mkdir(parents=True, exist_ok=True)
    shots = []
    for appearance in cfg.get("appearances", ["light", "dark"]):
        _run_checked(run, ["xcrun", "simctl", "ui", "booted", "appearance", appearance])
        for scene in cfg["scenes"]:
            try:
                run(["xcrun", "simctl", "terminate", "booted", cfg["bundle_id"]], capture_output=True)
            except Exception:  # noqa: BLE001 -- not running is fine
                pass
            _run_checked(run, ["xcrun", "simctl", "launch", "booted", cfg["bundle_id"], *scene.get("args", [])])
            sleep(cfg.get("wait_s", 4))
            rel = out_dir / f"{scene['name']}-{appearance}.png"
            _run_checked(run, ["xcrun", "simctl", "io", "booted", "screenshot", str(Path(worktree_path) / rel)])
            shots.append({"path": str(rel), "caption": f"{scene['name']}, {appearance}"})
    return shots


def capture_dev_evidence(
    worktree_path: Path,
    touches_ui: bool,
    capture_screenshot: Callable[[Path], str] | None = None,
) -> dict:
    """For a UI-touching ticket, drive the app headlessly and capture a
    screenshot; for a non-UI ticket, return the explicit N/A case rather
    than a fabricated or omitted one (ADR 0024). Always returns a dict --
    never None -- so mr_raiser's formatting has exactly one shape to
    handle, with `na` distinguishing "legitimately not applicable" from
    a populated result."""
    if not touches_ui:
        return {"na": True, "reason": "no UI"}

    capture_screenshot = capture_screenshot or _default_capture_screenshot
    try:
        screenshot_path = capture_screenshot(worktree_path)
    except (subprocess.SubprocessError, OSError, RuntimeError) as e:
        # A broken screenshot driver must not fail the ticket: on 2026-10-07 it failed every UI ticket, tripped the
        # circuit breaker and stalled the pipeline. The PR says the screenshot is missing and why, so review sees it.
        detail = (getattr(e, "stderr", None) or getattr(e, "output", None) or str(e))
        detail = detail.decode() if isinstance(detail, bytes) else str(detail)
        last = [l.strip() for l in detail.splitlines() if l.strip() and not l.strip().startswith("at ")]
        return {"na": False, "error": "capture failed: " + (" / ".join(last[-2:]) if last else type(e).__name__)[:300]}
    return {
        "na": False,
        "screenshot_path": screenshot_path,
        "description": "Live screenshot captured from the running app.",
    }
