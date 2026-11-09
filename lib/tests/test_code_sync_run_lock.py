"""code_sync holds one lock per clone, so two runs never merge the same clone at once (#1188).

2026-11-09, MacBook: four headless helpers started within a second, and each one's SessionStart hook ran
`code_sync.py pull` on the same clones. The runs raced: "cannot lock ref 'HEAD': is at X but expected Y" and
"cannot lock ref 'MERGE_AUTOSTASH': reference already exists", logged as "CONFLICT merging origin/main" nine runs in a
row, and a stash was left behind that made every later pull refuse. Real temp repos, like test_code_sync_pull.py:
the bug is in real git state, so a mocked subprocess would not show it.

Run: ~/.agents/venv/bin/python -m pytest lib/tests/test_code_sync_run_lock.py -v
"""
from __future__ import annotations
import fcntl
import os
import subprocess
import sys
import textwrap
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import code_sync as cs  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def _origin_and_clones(tmp_path: Path) -> tuple[Path, Path, Path]:
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "--bare", "-b", "main")
    clones = []
    for name in ("clone_a", "clone_b"):
        c = tmp_path / name
        if not clones:
            c.mkdir()
            _git(c, "init", "-b", "main")
            _git(c, "remote", "add", "origin", str(origin))
        else:
            subprocess.run(["git", "clone", str(origin), str(c)], check=True, capture_output=True)
        _git(c, "config", "user.email", "t@example.com")
        _git(c, "config", "user.name", name)
        if not clones:
            (c / "notes.md").write_text("seed\n")
            _git(c, "add", "-A")
            _git(c, "commit", "-m", "seed")
            _git(c, "push", "origin", "main")
            _git(c, "branch", "--set-upstream-to=origin/main")
        clones.append(c)
    return origin, clones[0], clones[1]


def _remote_moves_ahead(clone_b: Path, n: int = 3) -> str:
    for i in range(n):
        (clone_b / f"b{i}.md").write_text(f"from b {i}\n")
        _git(clone_b, "add", "-A")
        _git(clone_b, "commit", "-m", f"b {i}")
    _git(clone_b, "push", "origin", "main")
    return _git(clone_b, "rev-parse", "HEAD").strip()


def _quiet(monkeypatch, tmp_path):
    log = tmp_path / "sync-log.md"
    monkeypatch.setattr(cs, "LOG_PATH", log)
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)
    monkeypatch.setattr(cs, "machine_label", lambda: "test-machine")
    monkeypatch.setattr(cs.error_log, "record", lambda *a, **kw: None)
    monkeypatch.setattr(cs, "_track_episode", lambda *a, **kw: None)
    return log


def _hold_lock(clone: Path):
    """Hold the clone's code_sync lock the way another run would (an open fd with an exclusive flock)."""
    gitdir = Path(_git(clone, "rev-parse", "--absolute-git-dir").strip())
    fd = os.open(gitdir / cs.RUN_LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def test_a_pull_waits_out_a_held_lock_then_skips_without_touching_the_clone(tmp_path, monkeypatch):
    log = _quiet(monkeypatch, tmp_path)
    monkeypatch.setattr(cs, "RUN_LOCK_WAIT_S", 0.3)
    _, a, b = _origin_and_clones(tmp_path)
    _remote_moves_ahead(b)
    before = _git(a, "rev-parse", "HEAD").strip()
    fd = _hold_lock(a)
    try:
        cs.pull(a)
    finally:
        os.close(fd)
    assert _git(a, "rev-parse", "HEAD").strip() == before, "a run without the lock must not merge"
    # The skip must not write sync-log.md: it lives in the Claude dir, the very clone the holder may be merging.
    assert not log.exists() or "CONFLICT" not in log.read_text()
    assert not log.exists() or log.read_text().strip() == ""
    assert cs._RUN["neutral"] is True and not cs._RUN["failed"]


def test_the_lock_is_released_after_a_run(tmp_path, monkeypatch):
    _quiet(monkeypatch, tmp_path)
    monkeypatch.setattr(cs, "RUN_LOCK_WAIT_S", 0.3)
    _, a, b = _origin_and_clones(tmp_path)
    head = _remote_moves_ahead(b)
    cs.pull(a)
    fd = _hold_lock(a)   # would raise BlockingIOError if the first run still held it
    os.close(fd)
    assert _git(a, "rev-parse", "HEAD").strip() == head


def test_the_lock_is_released_when_the_run_crashes(tmp_path, monkeypatch):
    _quiet(monkeypatch, tmp_path)
    _, a, _b = _origin_and_clones(tmp_path)

    def boom():
        raise RuntimeError("mid-run crash")
    try:
        cs._tracked(a, "pull", None, boom)
    except RuntimeError:
        pass
    os.close(_hold_lock(a))


def test_a_lock_file_left_by_a_dead_run_does_not_block(tmp_path, monkeypatch):
    """flock belongs to the open fd, so a killed run leaves a file but no lock."""
    _quiet(monkeypatch, tmp_path)
    monkeypatch.setattr(cs, "RUN_LOCK_WAIT_S", 0.3)
    _, a, b = _origin_and_clones(tmp_path)
    head = _remote_moves_ahead(b)
    holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import fcntl, os, time
        fd = os.open({str(Path(_git(a, 'rev-parse', '--absolute-git-dir').strip()) / cs.RUN_LOCK_NAME)!r},
                     os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        print("held", flush=True)
        time.sleep(60)
    """)], stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "held"
    holder.kill()
    holder.wait()
    cs.pull(a)
    assert _git(a, "rev-parse", "HEAD").strip() == head


_DRIVER = textwrap.dedent("""
    import sys
    sys.path.insert(0, sys.argv[1])
    import code_sync as cs
    from pathlib import Path
    cs.LOG_PATH = Path(sys.argv[3])
    cs.notify = lambda *a, **kw: None
    cs.machine_label = lambda: "racer"
    cs.error_log.record = lambda *a, **kw: None
    cs._track_episode = lambda *a, **kw: None
    sys.stdin.readline()          # start line: every racer is released at once
    getattr(cs, sys.argv[4])(Path(sys.argv[2]))
""")


def test_four_runs_started_together_on_one_clone_never_race(tmp_path):
    """The 2026-11-09 burst: several runs at once on one clone, the remote ahead and a local edit to carry over."""
    _, a, b = _origin_and_clones(tmp_path)
    head = _remote_moves_ahead(b, 5)
    (a / "notes.md").write_text("seed\nlocal edit\n")       # dirty tree: the engine path stashes / autostashes
    driver = tmp_path / "driver.py"
    driver.write_text(_DRIVER)
    log = tmp_path / "race-log.md"
    env = {**os.environ, "HOME": str(tmp_path / "home")}  # never the real ~/.claude
    (tmp_path / "home").mkdir()
    racers = [subprocess.Popen([sys.executable, str(driver), str(LIB), str(a), str(log), action],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
              for action in ("pull", "pull", "pull", "pull")]
    for r in racers:
        r.stdin.write("go\n")
        r.stdin.flush()
    outs = [r.communicate(timeout=120) for r in racers]
    assert all(r.returncode == 0 for r in racers), outs
    text = log.read_text() if log.exists() else ""
    assert "CONFLICT" not in text and "cannot lock ref" not in text, text
    assert _git(a, "rev-parse", "HEAD").strip() == head
    assert _git(a, "stash", "list").strip() == "", "no stash may be left behind"
    assert subprocess.run(["git", "rev-parse", "-q", "--verify", "MERGE_AUTOSTASH"], cwd=a).returncode != 0
    assert (a / "notes.md").read_text() == "seed\nlocal edit\n", "the local edit survives"


def test_a_git_lock_failure_is_not_labelled_a_conflict(tmp_path, monkeypatch):
    """If a lock error still happens (a git process outside code_sync), say so: CONFLICT sent 11-09's fix the wrong way."""
    log = _quiet(monkeypatch, tmp_path)
    _, a, _b = _origin_and_clones(tmp_path)
    out = ("Updating 86ae8b2d..abdcd847\nfatal: update_ref failed for ref 'MERGE_AUTOSTASH': "
           "cannot lock ref 'MERGE_AUTOSTASH': reference already exists\n")
    monkeypatch.setattr(cs, "_merge_remote", lambda repo: (False, out))
    (a / "notes.md").write_text("seed\ndirty\n")
    cs.pull(a)
    text = log.read_text()
    assert "CONFLICT" not in text
    assert "git lock" in text.lower()
    assert cs._RUN["failed"], "a lock failure is still a failed run"
