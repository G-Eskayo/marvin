#!/usr/bin/env python3
"""MARVIN's daily auto-fixer: small, behaviour-preserving fixes from the improvement queue, sent as ONE gated PR a day.

Gil, 2026-07-08: "own your own optimization and bug fixes... low risk small daily patches". Gil, 2026-10-26: gate it,
and allow simplification (KISS) items. Until then it edited the shared ~/.agents checkout in place and auto-sync
committed the edits straight to main with no PR, no tests and no merge gate (against ADR 0063 and the rule that work
happens in a worktree). Now, each run (com.marvin.auto-fix, daily 11:00 on the Mac Mini):

1. Refreshes earlier marks: an item "in PR #n" becomes "done, PR #n merged" once n merges, or "tried" if it was closed.
2. Stops if today's branch (auto-fix/<date>) already has a PR, if GitHub can't be read (fail closed), or if another
   run holds the lock. So two runs in a day open at most one PR.
3. Reads ~/.claude/improvement-queue.md (oldest first, duplicates folded) and keeps pending NAMING, VERBOSITY and KISS
   items on .py files inside the repo that aren't core infrastructure (_core_files: live hooks and launchd jobs). At
   most MAX_ITEMS items over MAX_FILES files a run; the rest wait for later days, unmarked.
4. Waits while the 5-minute load is over LOAD_LIMIT (12), then makes a fresh worktree from origin/main on
   auto-fix/<date> with the ticket pipeline's own helper (sandbox_orchestration._create_worktree: same root, so
   cleanup_sweep removes it after merge; a leftover worktree is preserved under refs/rescue/ first).
5. Skips, with a note in the queue: a file deleted since it was queued, a file no tests cover, a KISS function that no
   longer exists or is longer than KISS_MAX_FUNCTION_LINES (80).
6. Runs the tests that cover those files (pytest -n 2) BEFORE fixing. A red baseline stops the run: nothing is
   attempted or marked, since it isn't the items' fault.
7. Launches the fixer (Background analyst, Read+Edit only, cwd = the worktree, writes to ~/.agents/** denied as for
   the pipeline's executor). Afterwards: anything it wrote into the shared checkout is restored; any file it changed
   that isn't one of the queued files is reverted ("only within one file"); a queued file that no longer compiles, or
   whose diff is over the cap (DIFF_CAP per item: VERBOSITY 6, NAMING 30, KISS 60 changed lines), is reverted.
8. Runs the same tests AFTER. Red: no PR, the failure goes in the log, the items are marked "tried". Green: one
   commit, pushed, one PR (gh via ~/.agents/bin/gh, --body-file) listing each item's queue entry and the test results.
   It goes through the normal merge gate when Gil approves; it is never merged by this job.

Queue marks are a suffix on the item's bullet (every copy of it), so the existing format still parses:
    - **[NAMING]** ... (`lib/x.py`) — auto-fix: in PR #712 (2026-10-26)
    - **[NAMING]** ... (`lib/x.py`) — auto-fix: done, PR #712 merged
    - **[KISS]** ... (`lib/y.py`) — auto-fix: skipped 2026-10-26, function is 95 lines, over the 80-line cap
    - **[VERBOSITY]** ... (`lib/z.py`) — auto-fix: tried 2026-10-26, tests failed
Delete the suffix to put an item back in the queue.

Every run appends to ~/.claude/auto-fix-log.md ("N candidate(s) found, M fixed", the line output_contracts reads).

Run standalone: ~/.agents/venv/bin/python auto_fix.py
"""
from __future__ import annotations

import ast
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

AGENTS_DIR = Path.home() / ".agents"                      # the shared checkout: read, never edited
REPO_LIB = Path(__file__).resolve().parents[3] / "lib"     # this checkout's own lib
CLAUDE_DIR = Path.home() / ".claude"
LOG_PATH = CLAUDE_DIR / "auto-fix-log.md"
QUEUE_PATH = CLAUDE_DIR / "improvement-queue.md"
VENV_PYTHON = AGENTS_DIR / "venv" / "bin" / "python"
GH = AGENTS_DIR / "bin" / "gh"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"

SCOPE = ("NAMING", "VERBOSITY", "KISS")
MAX_ITEMS = 10
MAX_FILES = 5
# Changed lines (added + removed, git numstat) a file may carry, summed over its items. A rename touches the
# definition and its uses; a comment trim one or two lines; a KISS simplification of a function up to 80 lines long
# should come out smaller, so 60 changed lines is room for a real simplification but not a rewrite.
DIFF_CAP = {"VERBOSITY": 6, "NAMING": 30, "KISS": 60}
KISS_MAX_FUNCTION_LINES = 80
LOAD_LIMIT = 12.0            # CPU rule: wait while the 5-minute load is over 12
LOAD_POLL_S = 60
LOAD_MAX_WAIT_S = 3600
TEST_TIMEOUT_S = 1800
FIXER_TIMEOUT_S = 600

sys.path.insert(0, str(REPO_LIB))
import marvin_hooks  # noqa: E402
import sandbox_orchestration as so  # noqa: E402
from build_type_measure import _scope_root  # noqa: E402
from evidence_capture import capture_test_results, TestTimedOut  # noqa: E402
import job_events  # noqa: E402  (run log shown in the dashboard's Health tab)
import instance  # noqa: E402

REPO = instance.engine_repo()  # where the PR goes: this install's own engine repo

HOOK_SETTINGS_PATHS = (marvin_hooks.USER_SETTINGS, marvin_hooks.LOCAL_SETTINGS)


def _core_files() -> set[Path]:
    """Every script this system currently depends on to run itself — derived live from what's actually wired up
    (hooks and every launchd job's ProgramArguments), not hardcoded, so new ones are excluded automatically."""
    core: set[Path] = set()
    # Hooks: user-level settings.json since #291, so reading settings.local.json alone protected none of them.
    for script in marvin_hooks.wired_scripts(HOOK_SETTINGS_PATHS):
        if script["path"].endswith(".py") and str(AGENTS_DIR) in script["path"]:
            core.add(Path(script["path"]).resolve())
    try:
        # Every launchd job, whatever its label prefix: only scripts under ~/.agents are kept, so no owner name is needed.
        for plist in LAUNCH_AGENTS_DIR.glob("*.plist"):
            for match in re.findall(r"<string>([^<]+\.py)</string>", plist.read_text(errors="replace")):
                if str(AGENTS_DIR) in match:
                    core.add(Path(match).resolve())
    except Exception:
        pass
    return core


# ── seams (tests replace these) ───────────────────────────────────────────────────────────────────────────────────

def _gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([str(GH), *args], capture_output=True, text=True, timeout=120)


def _default_launch_fixer(prompt: str, cwd: Path) -> None:
    import marvin_launcher
    result = marvin_launcher.launch("background-analyst", prompt, cwd=cwd, tools="Read,Edit", allowed_tools="Read,Edit",
                                    disallowed_tools=so._EXEC_DISALLOWED_TOOLS, permission_mode="dontAsk",
                                    timeout=FIXER_TIMEOUT_S)
    if result is not None and getattr(result, "exit_code", 0) != 0:
        raise RuntimeError(f"fixer exited {result.exit_code}: {(result.stderr or result.text or '')[:200]}")


_launch_fixer = _default_launch_fixer


def _load_5min() -> float:
    try:
        return os.getloadavg()[1]
    except (OSError, AttributeError):
        return 0.0


_sleep = time.sleep


# ── the queue ─────────────────────────────────────────────────────────────────────────────────────────────────────

MARK_SEP = " — auto-fix: "
LINE_RE = re.compile(r"^- (\*\*\[([A-Z]+)\]\*\* (.+?) \(`([^`\n]+)`\))(?: — auto-fix: (.*))?$")


def parse_queue(text: str) -> list[dict]:
    """Distinct queue items, first-seen (oldest) first: {entry, kind, message, path, mark}. Malformed lines are
    ignored. O(lines)."""
    items: dict[str, dict] = {}
    for line in text.splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        entry, kind, message, path, mark = m.groups()
        item = items.get(entry)
        if item is None:
            items[entry] = {"entry": entry, "kind": kind, "message": message, "path": path.strip(), "mark": mark}
        elif mark and not item["mark"]:
            item["mark"] = mark
    return list(items.values())


def _read_queue() -> str:
    try:
        return QUEUE_PATH.read_text(errors="replace")
    except OSError:
        return ""


def mark_items(marks: dict[str, str]) -> None:
    """Set the auto-fix suffix on every copy of each entry in `marks`. Written atomically; O(lines)."""
    if not marks or not QUEUE_PATH.exists():
        return
    out = []
    for line in QUEUE_PATH.read_text(errors="replace").splitlines(keepends=True):
        m = LINE_RE.match(line.rstrip("\n"))
        if m and m.group(1) in marks:
            line = f"- {m.group(1)}{MARK_SEP}{marks[m.group(1)]}" + ("\n" if line.endswith("\n") else "")
        out.append(line)
    fd, tmp = tempfile.mkstemp(dir=QUEUE_PATH.parent, prefix=".improvement-queue.")
    with os.fdopen(fd, "w") as f:
        f.write("".join(out))
    os.replace(tmp, QUEUE_PATH)


def refresh_pr_marks(today: str | None = None) -> None:
    """Items "in PR #n": done once n merged, tried once it was closed unmerged; left alone while open or unreadable."""
    today = today or _today()
    marks, states = {}, {}
    for item in parse_queue(_read_queue()):
        m = re.match(r"in PR #(\d+)", item["mark"] or "")
        if not m:
            continue
        n = m.group(1)
        if n not in states:
            r = _gh(["pr", "view", n, "--repo", REPO, "--json", "number,state"])
            try:
                states[n] = json.loads(r.stdout).get("state") if r.returncode == 0 else None
            except (json.JSONDecodeError, AttributeError):
                states[n] = None
        if states[n] == "MERGED":
            marks[item["entry"]] = f"done, PR #{n} merged"
        elif states[n] == "CLOSED":
            marks[item["entry"]] = f"tried {today}, PR #{n} closed unmerged"
    mark_items(marks)


def _in_scope(item: dict, core: set[Path]) -> bool:
    """Shape checks that need no worktree: pending, a kind in scope, a .py path inside the repo, not core."""
    if item["mark"] or item["kind"] not in SCOPE:
        return False
    rel = Path(item["path"])
    if rel.is_absolute() or ".." in rel.parts or rel.suffix != ".py":
        return False
    return (AGENTS_DIR / rel).resolve() not in core


def _function_lines(path: Path, name: str) -> int | None:
    """Length of the function or method called `name` (the longest, if several), None if there is none."""
    tree = ast.parse(path.read_text())
    lengths = [n.end_lineno - n.lineno + 1 for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    return max(lengths) if lengths else None


def _has_tests(root: Path) -> bool:
    return next(root.rglob("test_*.py"), None) is not None


def select(items: list[dict], worktree: Path, today: str) -> tuple[list[dict], dict[str, str]]:
    """(items to fix, skip marks). Stops at MAX_ITEMS; an item on a file past MAX_FILES waits, unmarked."""
    chosen, skipped, files, tested = [], {}, set(), {}
    for item in items:
        if len(chosen) >= MAX_ITEMS:
            break
        wt_file = worktree / item["path"]
        if not wt_file.is_file():
            skipped[item["entry"]] = f"skipped {today}, file no longer exists"
            continue
        root = _scope_root(item["path"])
        if root not in tested:
            tested[root] = _has_tests(worktree / root)
        if not tested[root]:
            skipped[item["entry"]] = f"skipped {today}, no tests cover {root}"
            continue
        if item["kind"] == "KISS":
            name = re.search(r"Function '([^']+)'", item["message"])
            try:
                n = _function_lines(wt_file, name.group(1)) if name else None
            except (SyntaxError, ValueError):
                skipped[item["entry"]] = f"skipped {today}, file does not parse"
                continue
            if n is None:
                skipped[item["entry"]] = f"skipped {today}, function no longer exists"
                continue
            if n > KISS_MAX_FUNCTION_LINES:
                skipped[item["entry"]] = f"skipped {today}, function is {n} lines, over the {KISS_MAX_FUNCTION_LINES}-line cap"
                continue
        if item["path"] not in files and len(files) >= MAX_FILES:
            continue
        files.add(item["path"])
        chosen.append(item)
    return chosen, skipped


# ── prompt ────────────────────────────────────────────────────────────────────────────────────────────────────────

FIX_PROMPT_TEMPLATE = """You are MARVIN's autonomous low-risk fixer, running unattended with Read and Edit only. You work in a git worktree at {worktree}; edit only the files named below, inside that folder. Your change becomes a pull request that a person reviews, and the tests run before and after.

Fix ONLY these findings, each within its own file:
{findings_list}

How to fix each kind:
- NAMING: rename the generic variable or parameter to a descriptive name and update every reference to it in that function. Do not rename anything public that other files use.
- VERBOSITY: tighten the comment's wording; keep its meaning.
- KISS: simplify that one function without changing what it does (same inputs give the same outputs and the same side effects, same signature). Keep the change inside that file and small: at most {kiss_cap} changed lines. If it can't be simplified that way, leave it.

Touch nothing else: no other refactoring, renames, logic changes or reformatting, and never a test file. If a finding looks wrong, already fixed, or you aren't confident the fix is safe and correct, skip it."""


def build_prompt(chosen: list[dict], worktree: Path) -> str:
    lines = [f"- [{c['kind']}] {c['message']} (file: {worktree / c['path']})" for c in chosen]
    return FIX_PROMPT_TEMPLATE.format(worktree=worktree, findings_list="\n".join(lines), kiss_cap=DIFF_CAP["KISS"])


# ── git, tests ────────────────────────────────────────────────────────────────────────────────────────────────────

def _git(cwd: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def _changed_paths(worktree: Path) -> list[str]:
    out = _git(worktree, "status", "--porcelain", "--untracked-files=all").stdout
    return [line[3:].strip().strip('"') for line in out.splitlines() if line.strip()]


def _revert(worktree: Path, rel: str) -> None:
    if _git(worktree, "ls-files", "--error-unmatch", "--", rel).returncode == 0:
        _git(worktree, "checkout", "--", rel)
    else:
        (worktree / rel).unlink(missing_ok=True)


def _diff_lines(worktree: Path, rel: str) -> int:
    out = _git(worktree, "diff", "--numstat", "--", rel).stdout.split()
    return sum(int(x) for x in out[:2] if x.isdigit())


def test_command(roots: list[str]) -> list[str]:
    return [str(VENV_PYTHON), "-m", "pytest", "-q", "-n", "2", *roots]


def _run_suite(worktree: Path, cmd: list[str]) -> dict:
    """The parsed result plus ok: green only with no failures or errors and at least one test passed."""
    try:
        r = capture_test_results(worktree, cmd, timeout_s=TEST_TIMEOUT_S)
    except TestTimedOut as e:
        return {"suite": "pytest", "passed": None, "failed": None, "total": None, "ok": False,
                "output_tail": f"timed out after {e.timeout_s}s\n{e.partial_output[-500:]}"}
    tail = r.get("output_tail", "")
    summary = [l for l in tail.splitlines() if re.search(r"\bin \d+(?:\.\d+)?s\b", l)][-1:]
    errors = bool(summary and re.search(r"\d+ errors?\b", summary[0]))
    r["ok"] = bool(r.get("passed")) and not r.get("failed") and not errors
    return r


def _wait_for_load() -> bool:
    waited = 0
    while _load_5min() > LOAD_LIMIT:
        if waited >= LOAD_MAX_WAIT_S:
            return False
        _sleep(LOAD_POLL_S)
        waited += LOAD_POLL_S
    return True


def _discard_worktree(worktree: Path, branch: str) -> None:
    _git(AGENTS_DIR, "worktree", "remove", "--force", str(worktree))
    _git(AGENTS_DIR, "branch", "-D", branch)


# ── log ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def log_run(today: str, headline: str, details: list[str] | None = None) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = f"{today}T{datetime.now(timezone.utc):%H:%M:%S}+00:00"
    with LOG_PATH.open("a") as f:
        f.write("\n".join([f"\n## {stamp}", headline, *(details or [])]) + "\n")


def _lock_path() -> Path:
    return so.WORKTREES_ROOT / ".auto-fix.lock"


# ── PR ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _todays_pr(branch: str) -> tuple[bool, int | None]:
    """(readable, PR number on today's branch in any state)."""
    r = _gh(["pr", "list", "--repo", REPO, "--head", branch, "--state", "all", "--json", "number,state"])
    if r.returncode != 0:
        return False, None
    try:
        prs = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return False, None
    return True, (prs[0].get("number") if prs else None)


def pr_body(today: str, fixed: list[dict], left_out: dict[str, str], cmd: list[str], before: dict, after: dict) -> str:
    from mr_raiser import _format_test_results
    lines = [f"Daily auto-fix batch for {today} (`com.marvin.auto-fix`, `skills/improve/scripts/auto_fix.py`).",
             "",
             "Behaviour-preserving fixes taken from `~/.claude/improvement-queue.md`, made in a worktree on "
             f"`auto-fix/{today}` from origin/main; the shared `~/.agents` checkout was not touched. The tests that cover "
             "these files ran before and after the fix and passed both times.",
             "",
             "Not auto-merged: it goes through the normal merge gate when the owner approves.",
             "", "## Items fixed", "", *[f"- {i['entry']}" for i in fixed]]
    if left_out:
        lines += ["", "## Left out", "", *[f"- {entry} — {note}" for entry, note in left_out.items()]]
    lines += ["", "## Test Results", "", f"Command: `{' '.join(['pytest'] + cmd[cmd.index('-q'):])}`",
              "", "### Before", "", _format_test_results(before), "", "### After", "", _format_test_results(after),
              "", "## Size caps", "",
              f"Changed lines per item: VERBOSITY {DIFF_CAP['VERBOSITY']}, NAMING {DIFF_CAP['NAMING']}, "
              f"KISS {DIFF_CAP['KISS']}; KISS functions longer than {KISS_MAX_FUNCTION_LINES} lines are not attempted. "
              "Only the queued files may change."]
    return "\n".join(lines) + "\n"


def _commit_push_and_open(worktree: Path, branch: str, today: str, fixed: list[dict], body: str) -> tuple[int | None, str]:
    from mr_raiser import AUTHOR, CO_AUTHOR
    title = f"Auto-fix batch {today}: {len(fixed)} small fix(es) from the improvement queue"
    _git(worktree, "add", "--", *sorted({i["path"] for i in fixed}), check=True)  # only the queued files: never test caches
    commit = _git(worktree, "commit", f"--author={AUTHOR}", "-m", title, "-m",
                  "\n".join(f"- {i['entry']}" for i in fixed), "-m", CO_AUTHOR)
    if commit.returncode != 0:
        return None, f"commit failed: {(commit.stderr or commit.stdout).strip()[-300:]}"
    push = _git(worktree, "push", "-u", "origin", branch)
    if push.returncode != 0:
        return None, f"push failed: {(push.stderr or push.stdout).strip()[-300:]}"
    with tempfile.NamedTemporaryFile("w", suffix=".md", prefix="auto-fix-pr-", delete=False) as f:
        f.write(body)
        body_file = f.name
    try:
        r = _gh(["pr", "create", "--repo", REPO, "--base", "main", "--head", branch, "--title", title,
                 "--body-file", body_file])
    finally:
        os.unlink(body_file)
    m = re.search(r"/pull/(\d+)", r.stdout or "")
    if r.returncode != 0 or not m:
        _git(worktree, "push", "origin", "--delete", branch)  # no PR: don't leave an orphan branch for tomorrow to trip on
        return None, f"gh pr create failed: {(r.stderr or r.stdout).strip()[-300:]}"
    return int(m.group(1)), (r.stdout or "").strip()


# ── the run ───────────────────────────────────────────────────────────────────────────────────────────────────────

def run(today: str | None = None) -> None:
    today = today or _today()
    so.WORKTREES_ROOT.mkdir(parents=True, exist_ok=True)
    with open(_lock_path(), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log_run(today, "Skipped — another auto-fix run holds the lock")
            return
        _run_locked(today)


def _run_locked(today: str) -> None:
    branch = f"auto-fix/{today}"
    refresh_pr_marks(today)
    readable, pr = _todays_pr(branch)
    if not readable:
        log_run(today, "Skipped — could not read GitHub to check for today's PR (fails closed)")
        return
    if pr:
        log_run(today, f"Skipped — today's batch already has PR #{pr}")
        return

    core = _core_files()
    pending = [i for i in parse_queue(_read_queue()) if _in_scope(i, core)]
    if not pending:
        log_run(today, "Skipped — no queued items in scope")
        return
    if not _wait_for_load():
        log_run(today, f"Skipped — 5-minute load stayed over {LOAD_LIMIT:g} for {LOAD_MAX_WAIT_S // 60} min")
        return

    try:
        worktree = so._create_worktree(AGENTS_DIR, "auto-fix", branch=branch)
    except Exception as e:  # noqa: BLE001
        log_run(today, f"Skipped — could not create the worktree: {e}")
        return

    try:
        _fix_in(worktree, branch, today, pending)
    except Exception as e:  # noqa: BLE001  (the shared checkout is never at risk; the worktree goes)
        log_run(today, f"Failed — {type(e).__name__}: {e}")
        _discard_worktree(worktree, branch)
        raise


def _fix_in(worktree: Path, branch: str, today: str, pending: list[dict]) -> None:
    chosen, skipped = select(pending, worktree, today)
    mark_items(skipped)
    if not chosen:
        log_run(today, f"{len(pending)} candidate(s) found, 0 fixed — none could be attempted",
                [f"- {e} — {n}" for e, n in skipped.items()])
        _discard_worktree(worktree, branch)
        return

    roots = sorted({_scope_root(i["path"]) for i in chosen})
    cmd = test_command(roots)
    before = _run_suite(worktree, cmd)
    if not before["ok"]:
        log_run(today, f"Skipped — baseline tests are red before any fix ({' '.join(roots)}); nothing attempted",
                ["```", before.get("output_tail", "")[-500:], "```"])
        _discard_worktree(worktree, branch)
        return

    files = sorted({i["path"] for i in chosen})
    shared_before = {f: (AGENTS_DIR / f).read_bytes() for f in files if (AGENTS_DIR / f).is_file()}
    try:
        _launch_fixer(build_prompt(chosen, worktree), worktree)
    except Exception as e:  # noqa: BLE001
        _restore_shared(today, shared_before)
        log_run(today, f"Skipped — the fixer run failed: {type(e).__name__}: {str(e)[:200]}")
        _discard_worktree(worktree, branch)
        return
    _restore_shared(today, shared_before)

    marks, reverted = {}, []
    for rel in _changed_paths(worktree):
        if rel not in files:
            _revert(worktree, rel)
            reverted.append(f"- reverted `{rel}`: not a queued file")
    kept = []
    for rel in files:
        mine = [i for i in chosen if i["path"] == rel]
        if rel not in _changed_paths(worktree):
            marks.update({i["entry"]: f"tried {today}, no change made" for i in mine})
            continue
        if subprocess.run([str(VENV_PYTHON), "-m", "py_compile", str(worktree / rel)], capture_output=True).returncode:
            _revert(worktree, rel)
            marks.update({i["entry"]: f"tried {today}, fix did not compile" for i in mine})
            reverted.append(f"- reverted `{rel}`: no longer compiled")
            continue
        cap, n = sum(DIFF_CAP[i["kind"]] for i in mine), _diff_lines(worktree, rel)
        if n > cap:
            _revert(worktree, rel)
            marks.update({i["entry"]: f"skipped {today}, diff was {n} lines, over the {cap}-line cap" for i in mine})
            reverted.append(f"- reverted `{rel}`: {n} changed lines, over the {cap}-line cap")
            continue
        kept += mine

    if not kept:
        mark_items(marks)
        log_run(today, f"{len(chosen)} candidate(s) found, 0 fixed — nothing kept", reverted)
        _discard_worktree(worktree, branch)
        return

    after = _run_suite(worktree, cmd)
    if not after["ok"]:
        marks.update({i["entry"]: f"tried {today}, tests failed" for i in kept})
        mark_items(marks)
        log_run(today, f"{len(chosen)} candidate(s) found, 0 fixed — tests failed after the fix, no PR opened",
                [*reverted, *[f"- tried: {i['entry']}" for i in kept], "```", after.get("output_tail", "")[-500:], "```"])
        _discard_worktree(worktree, branch)
        return

    left_out = {**skipped, **{e: n for e, n in marks.items()}}
    number, detail = _commit_push_and_open(worktree, branch, today, kept, pr_body(today, kept, left_out, cmd, before, after))
    if number is None:
        mark_items(marks)
        log_run(today, f"{len(chosen)} candidate(s) found, 0 fixed — {detail}", reverted)
        _discard_worktree(worktree, branch)
        return
    marks.update({i["entry"]: f"in PR #{number} ({today})" for i in kept})
    mark_items(marks)
    log_run(today, f"{len(chosen)} candidate(s) found, {len(kept)} fixed — PR #{number} opened for review",
            [detail, *reverted, *[f"- fixed: {i['entry']}" for i in kept]])
    _discard_worktree(worktree, branch)  # the branch is on origin; cleanup_sweep need not find it


def _restore_shared(today: str, before: dict[str, bytes]) -> None:
    """The fixer is denied writes to ~/.agents, but check rather than assume: put back anything it changed there."""
    changed = [f for f, data in before.items() if (AGENTS_DIR / f).read_bytes() != data]
    for f in changed:
        (AGENTS_DIR / f).write_bytes(before[f])
    if changed:
        log_run(today, f"Alarm — the fixer wrote into the shared checkout; restored {len(changed)} file(s)",
                [f"- `{f}`" for f in changed])


@job_events.reported("auto-fix", "Auto-fix (one gated PR a day)")
def main() -> None:
    run()


if __name__ == "__main__":
    main()
