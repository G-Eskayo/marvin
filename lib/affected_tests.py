#!/usr/bin/env python3
"""affected_tests.py — the Python tests a change can affect, so a PR doesn't run all of them (marvin#826 step 3).

Every PR used to run every test, so one unrelated failure anywhere blocked every PR in the repo, and a one-line docs
PR ran ~7,000 tests. CI's and the gate's "Python tests" check runs this instead of pytest directly:

  - no $MARVIN_BASE (main after a merge, main-health): the whole suite
  - $MARVIN_BASE set (a PR): the test files the change can affect, from the paths changed since the branch left
    that base (git diff base...HEAD):
      the rules, always (lib/rule_checks.RULE_FILES that are rules: test_instance*.py judge every file in the repo,
      so any change can break them; #767 and #770 did)
      every changed test file
      every test whose imports reach a changed module, however deep (`import x`, `from x import y`,
      importlib.import_module("x"); a module is known by its file name, so two files of the same name both count)
      every test whose import chain reaches code that names a changed non-Python file (config/x.json, merge.js;
      a file name several tracked files share, like index.html, counts only beside its folder's name)
      every test under a changed conftest.py's folder (its fixtures reach them all)
    and the whole suite when what changed is how all tests run (the root conftest.py, pytest.ini,
    requirements-ci.txt, this file, .github/). A base the clone can't resolve also runs the whole suite: never skip
    on a guess.

The selection reaches pytest through $MARVIN_SELECTED_TESTS (a file of paths), which the repo's conftest.py honours
at collection, so unselected files are never even imported. Cost: one parse of every tracked .py file (~450, under a
second) and a breadth-first walk of the import graph: O(files + imports).

    affected_tests.py                 run the Python tests for $MARVIN_BASE (all of them without it)
    affected_tests.py list <base>     print the selection, one file per line ("ALL" for the whole suite)
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict, deque
from pathlib import Path

RULES = ["lib/tests/test_instance.py", "lib/tests/test_instance_move.py"]
RUNS_EVERYTHING = re.compile(r"^conftest\.py$|^pytest\.ini$|^requirements-ci\.txt$|^lib/affected_tests\.py$|^\.github/")
_TEST = re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$")
_TOO_COMMON = {"__init__.py"}  # a name every package has says nothing about who reads it


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True, timeout=60).stdout


def all_tests(repo: Path) -> list[str]:
    return sorted(p for p in _git(Path(repo), "ls-files", "*.py").split() if _TEST.search(p))


def changed_paths(repo: Path, base: str) -> list[str]:
    return sorted(set(_git(Path(repo), "diff", "--name-only", f"{base}...HEAD").split()))


def _module_name(path: str) -> str:
    p = Path(path)
    return p.parent.name if p.stem == "__init__" else p.stem


def _imports(source: str) -> set[str]:
    """Every name a file could be importing a module by: each dotted part, and the names `from` brings in."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                out.update(a.name.split("."))
        elif isinstance(n, ast.ImportFrom):
            out.update((n.module or "").split("."))
            out.update(a.name for a in n.names)
        elif (isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", None)) == "import_module"
              and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
            out.update(n.args[0].value.split("."))
    out.discard("")
    return out


def select(repo: Path, changed: list[str]) -> list[str] | None:
    """The test files `changed` can affect, or None for the whole suite."""
    repo = Path(repo)
    if any(RUNS_EVERYTHING.search(p) for p in changed):
        return None
    sources: dict[str, str] = {}
    for p in _git(repo, "ls-files", "*.py").split():
        try:
            sources[p] = (repo / p).read_text(errors="replace")
        except OSError:
            continue
    by_module: dict[str, set[str]] = defaultdict(set)  # module name -> files that import it
    for p, src in sources.items():
        for name in _imports(src):
            by_module[name].add(p)
    # Where the walk starts: the changed Python files (deleted ones too: their importers must fail), and code that
    # names a changed file of any other kind.
    start: set[str] = {p for p in changed if p.endswith(".py")}
    names = defaultdict(int)
    for p in _git(repo, "ls-files").split():
        names[Path(p).name] += 1
    for p in changed:
        name, parent = Path(p).name, Path(p).parent.name
        if p.endswith(".py") or name in _TOO_COMMON:
            continue
        # A name several files share (index.html, .gitignore, package.json) only counts beside its folder's name.
        shared = names[name] > 1 and parent
        start |= {f for f, src in sources.items() if name in src and (not shared or parent in src)}
    seen, todo = set(start), deque(start)
    while todo:  # every file whose imports reach a changed one
        for importer in by_module.get(_module_name(todo.popleft()), ()):
            if importer not in seen:
                seen.add(importer)
                todo.append(importer)
    tests = set(all_tests(repo))
    picked = {p for p in seen if p in tests} | {p for p in RULES if p in tests}
    for p in changed:
        if Path(p).name == "conftest.py":
            picked |= {t for t in tests if t.startswith(str(Path(p).parent) + "/")}
    return sorted(picked)


def plan(repo: Path, base: str | None) -> tuple[list[str], dict]:
    """The pytest command and environment for the Python check."""
    argv = [sys.executable, "-m", "pytest", "-q"]
    env = {k: v for k, v in os.environ.items() if k != "MARVIN_SELECTED_TESTS"}
    if not base:
        print("affected tests: no base given, running the whole suite", flush=True)
        return argv, env
    try:
        changed = changed_paths(repo, base)
    except subprocess.CalledProcessError:
        print(f"affected tests: cannot tell what changed since {base}; running the whole suite", file=sys.stderr, flush=True)
        return argv, env
    picked = select(repo, changed)
    if picked is None:
        print(f"affected tests: {len(changed)} changed path(s) include how tests run; running the whole suite", flush=True)
        return argv, env
    fd, path = tempfile.mkstemp(prefix="marvin-selected-", suffix=".txt")
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(picked) + "\n")
    print(f"affected tests: {len(picked)} of {len(all_tests(repo))} test files for {len(changed)} changed path(s) "
          f"since {base}", flush=True)
    return argv, {**env, "MARVIN_SELECTED_TESTS": path}


def main(argv: list[str]) -> int:
    repo = Path(__file__).resolve().parents[1]
    if argv[:1] == ["list"] and len(argv) == 2:
        picked = select(repo, changed_paths(repo, argv[1]))
        print("ALL" if picked is None else "\n".join(picked))
        return 0
    if argv:
        print(__doc__)
        return 2
    cmd, env = plan(repo, os.environ.get("MARVIN_BASE") or None)
    try:
        code = subprocess.run(cmd, cwd=repo, env=env).returncode
        # 5 = nothing collected: every selected file was left out on this machine (conftest's portfolio guard)
        return 0 if code == 5 and env.get("MARVIN_SELECTED_TESTS") else code
    finally:
        if env.get("MARVIN_SELECTED_TESTS"):
            Path(env["MARVIN_SELECTED_TESTS"]).unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
