"""The test harness's own promises (pipeline review 2026-10-21, F3 and F10), checked rather than assumed.

- A hung test fails in about two minutes, by name (pytest-timeout, pytest.ini). If the plugin is missing on a machine
  this file fails, naming the fix, instead of the gate silently losing its per-test limit.
- No test touches the real ~/.claude: HOME is a temp mirror (conftest.py), subprocesses inherit it, and a write that
  still aims at the real folder is refused and fails the test that tried (lib/real_home_guard.py).
- No test runs du on the real home (lib/tests/conftest.py): that du is what hung the gate.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import real_home_guard as rhg  # noqa: E402

REAL = rhg.real_home()


def _drop_my_violations(request):
    rhg.ACTIVE.violations[:] = [v for v in rhg.ACTIVE.violations if v[0] != request.node.nodeid]


# ---- per-test timeout ----

def test_the_per_test_timeout_plugin_is_installed_and_set(request):
    assert request.config.pluginmanager.hasplugin("timeout"), (
        "pytest-timeout is not installed in this venv, so a hung test would hold the merge gate with no name: "
        "run ~/.agents/venv/bin/python -m pip install pytest-timeout pytest-xdist (setup.sh does this)")
    assert float(request.config.getini("timeout")) == 120


def test_a_hung_test_fails_by_name_within_its_limit(tmp_path):
    """A real pytest run of a test that blocks: it must fail, quickly, with its name and the timeout reason."""
    hung = tmp_path / "test_hangs.py"
    hung.write_text("import time\n\ndef test_blocks_forever():\n    time.sleep(600)\n\ndef test_after_it_still_runs():\n    pass\n")
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--timeout", "2", str(hung)],
                       cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert p.returncode == 1
    assert "FAILED test_hangs.py::test_blocks_forever" in p.stdout
    assert "Timeout" in p.stdout
    assert "1 passed" in p.stdout, "the run must carry on past the hung test"


# ---- temp HOME ----

def test_home_is_a_temp_mirror_not_the_real_home():
    home = Path.home()
    assert home != REAL and os.path.realpath(home) != os.path.realpath(REAL)
    assert (home / ".claude").is_dir() and not (home / ".claude").is_symlink()
    # Earlier tests in the same process may have written temp logs; what matters is that they are not the real ones.
    logs = home / ".claude" / "logs"
    assert not logs.is_symlink() and (not logs.exists() or rhg.outside_real_home(logs))
    for entry in (home / ".claude").rglob("*"):
        if entry.is_symlink():
            assert str(entry.relative_to(home / ".claude")) in rhg.read_through(REAL)
    if (REAL / ".agents").exists():
        assert (home / ".agents").resolve() == (REAL / ".agents").resolve(), "the mirror must still reach ~/.agents"


def test_subprocesses_inherit_the_temp_home():
    out = subprocess.run(["/bin/sh", "-c", 'printf %s "$HOME"'], capture_output=True, text=True, timeout=10).stdout
    assert out == str(Path.home()) and out != str(REAL)
    node = subprocess.run(["node", "-e", "process.stdout.write(require('os').homedir())"], capture_output=True,
                          text=True, timeout=30) if _has("node") else None
    if node is not None and node.returncode == 0:
        assert node.stdout == str(Path.home())


def _has(cmd):
    from shutil import which
    return which(cmd) is not None


def test_make_test_home_mirrors_everything_but_claude(tmp_path):
    real = tmp_path / "real"
    (real / ".claude" / "logs").mkdir(parents=True)
    (real / ".claude" / "logs" / "errors.jsonl").write_text("real\n")
    (real / ".claude.json").write_text("{}")
    (real / ".agents").mkdir()
    (real / "Documents").mkdir()
    (real / ".gitconfig").write_text("[user]\n")
    home = rhg.make_test_home(real, parent=str(tmp_path))
    assert sorted(p.name for p in home.iterdir()) == [".agents", ".claude", ".gitconfig", "Documents"]
    assert (home / ".agents").is_symlink() and not (home / ".claude").is_symlink()
    assert list((home / ".claude").iterdir()) == []
    (home / ".claude" / "x").write_text("temp")
    assert not (real / ".claude" / "x").exists()


def test_read_only_inputs_are_linked_in_and_still_cannot_be_written(tmp_path):
    real = tmp_path / "real"
    slug = str(real).replace("/", "-")
    mem = real / ".claude" / "projects" / slug / "memory"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("# Memory Index\n")
    (real / ".claude" / "settings.json").write_text("{}")
    (real / ".claude" / "projects" / slug / "transcript.jsonl").write_text("private\n")
    home = rhg.make_test_home(real, parent=str(tmp_path))
    assert (home / ".claude" / "projects" / slug / "memory" / "MEMORY.md").read_text() == "# Memory Index\n"
    assert (home / ".claude" / "settings.json").read_text() == "{}"
    assert not (home / ".claude" / "projects" / slug / "transcript.jsonl").exists(), "only the memory, not transcripts"
    g = rhg.WriteGuard(rhg.protected_roots(real), resolve_under=(str(home / ".claude"),))
    for target in (home / ".claude" / "settings.json", home / ".claude" / "projects" / slug / "memory" / "new.md",
                   home / ".claude" / "projects" / slug / "memory" / "deep" / "er.md"):
        with pytest.raises(PermissionError):
            g("open", (str(target), "w", 0))
    g.violations.clear()
    g("open", (str(home / ".claude" / "logs" / "errors.jsonl"), "a", 0))  # a temp-only path: allowed
    g("open", (str(home / ".claude" / "settings.json"), "r", 0))         # reading a linked input: allowed
    assert g.violations == []


# ---- the write guard ----

@pytest.mark.parametrize("write", [
    lambda p: open(p, "a"),
    lambda p: p.write_text("x"),
    lambda p: p.parent.mkdir(parents=True, exist_ok=True) or p.touch(),
    lambda p: os.open(str(p), os.O_WRONLY | os.O_CREAT),
    lambda p: os.remove(p),
    lambda p: os.rename(p, p.with_suffix(".bak")),
    lambda p: __import__("shutil").rmtree(p.parent),
    lambda p: __import__("sqlite3").connect(str(p)),
], ids=["open-a", "write_text", "mkdir", "os.open", "remove", "rename", "rmtree", "sqlite"])
def test_writes_to_the_real_claude_folder_are_refused(request, write):
    target = REAL / ".claude" / "logs" / "harness-guard-probe.jsonl"
    before = target.exists()
    try:
        with pytest.raises(PermissionError, match="real ~/.claude"):
            write(target)
    finally:
        _drop_my_violations(request)
    assert target.exists() == before


def test_writes_to_the_real_claude_json_are_refused(request):
    try:
        with pytest.raises(PermissionError):
            (REAL / ".claude.json").write_text("{}")
    finally:
        _drop_my_violations(request)


def test_a_swallowed_refusal_is_still_recorded_against_the_test(request):
    target = REAL / ".claude" / "logs" / "errors.jsonl"
    try:
        try:
            with open(target, "a") as f:  # code under test often wraps log writes in a bare except
                f.write("fake\n")
        except Exception:  # noqa: BLE001
            pass
        mine = [v for v in rhg.ACTIVE.violations if v[0] == request.node.nodeid]
        assert mine and mine[0][2] == str(target)
    finally:
        _drop_my_violations(request)


def test_reads_and_temp_writes_are_allowed(tmp_path):
    (tmp_path / "ok.txt").write_text("fine")
    (Path.home() / ".claude" / "logs").mkdir(parents=True, exist_ok=True)
    (Path.home() / ".claude" / "logs" / "errors.jsonl").write_text("temp\n")
    # Reading the real folder is not what this guards.
    if (REAL / ".claude").is_dir():
        os.listdir(REAL / ".claude")


@pytest.mark.parametrize("event,args,hit", [
    ("open", ("/r/.claude/logs/x", "r", 0), False),
    ("open", ("/r/.claude/logs/x", "rb", 0), False),
    ("open", ("/r/.claude/logs/x", "w", 0), True),
    ("open", ("/r/.claude/logs/x", None, os.O_RDONLY), False),
    ("open", ("/r/.claude/logs/x", None, os.O_APPEND | os.O_WRONLY), True),
    ("open", ("/r/.claude/logs/x", None, os.O_CREAT), True),
    ("open", (3, "w", 0), False),
    ("open", ("/r/.claudette/x", "w", 0), False),
    ("open", ("/r/.claude", "w", 0), True),
    ("open", ("/r/.agents/../.claude/x", "w", 0), True),
    ("os.rename", ("/tmp/a", "/r/.claude/b", None, None), True),
    ("shutil.copyfile", ("/r/.claude/a", "/tmp/b"), False),
    ("shutil.copyfile", ("/tmp/a", "/r/.claude/b"), True),
    ("os.listdir", ("/r/.claude",), False),
    ("subprocess.Popen", ("rm", ["rm", "-rf", "/r/.claude"], None, None), False),
])
def test_guard_classifies_events(event, args, hit):
    g = rhg.WriteGuard(("/r/.claude", "/r/.claude.json"))
    if hit:
        with pytest.raises(PermissionError):
            g(event, args)
    else:
        g(event, args)
    assert bool(g.violations) == hit


def test_a_disarmed_guard_lets_writes_through():
    g = rhg.WriteGuard(("/r/.claude",))
    g.armed = False
    g("open", ("/r/.claude/x", "w", 0))
    assert g.violations == []


# ---- du on the real home ----

def test_du_on_the_real_home_is_refused_at_once():
    import disk_ledger
    with pytest.raises(AssertionError, match="du on the real home"):
        disk_ledger._default_du_kb(REAL / "Documents")
    with pytest.raises(AssertionError, match="du on the real home"):
        disk_ledger._default_du_kb(Path.home() / "Library" / "Caches")  # through the mirror's symlink


def test_du_on_a_temp_folder_still_runs(tmp_path):
    import disk_ledger
    (tmp_path / "f").write_bytes(b"x" * 4096)
    assert disk_ledger._default_du_kb(tmp_path) >= 4
