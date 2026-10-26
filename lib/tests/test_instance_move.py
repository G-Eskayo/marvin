"""ADR 0071 step 2: the owner's state lives in the private instance, and nothing writes it back into the engine. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_instance_move.py -v

Moving files out is not enough: if any writer still targets the old engine path, auto-sync republishes the data the
next day. So every reader and writer is pointed at the instance, the old paths are gitignored as a backstop, and
code_sync syncs the nested instance repo along with the engine. Real temp repos, a temp HOME.
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "skills" / "self-improve" / "scripts"))
sys.path.insert(0, str(ROOT / "brain-map"))

import instance  # noqa: E402

MOVED = ["bench/metrics", "docs/plans", "docs/screenshots", "docs/evidence", "config/projects", "retrospective-log.md"]
# Ignored too, so a stale writer on any machine can't republish them. docs/screenshots and docs/evidence are not:
# ticket PRs still commit their evidence images there until engine PRs switch to a demo instance.
IGNORED = ["bench/metrics/ticket-1.mac-mini.json", "docs/plans/x-2026-10-25.md", "config/projects/x.json",
           "retrospective-log.md"]


@pytest.mark.parametrize("p", MOVED)
def test_the_engine_no_longer_tracks_the_owners_state(p):
    tracked = subprocess.run(["git", "ls-files", "--", p], cwd=ROOT, capture_output=True, text=True).stdout
    assert tracked == "", f"{p} is still in the public engine"


@pytest.mark.parametrize("p", IGNORED)
def test_a_stale_writer_cannot_put_it_back(p):
    assert subprocess.run(["git", "check-ignore", "-q", p], cwd=ROOT).returncode == 0, f"{p} would be committed again"


@pytest.fixture
def inst_env(tmp_path, monkeypatch):
    d = tmp_path / "inst"
    monkeypatch.setenv("MARVIN_INSTANCE_DIR", str(d))
    instance.reset()
    return d


@pytest.mark.parametrize("module,attr,rel", [
    ("metrics_registry", "METRICS_DIR", ("bench", "metrics")),
    ("project_profile", "PROFILES_DIR", ("config", "projects")),
    ("background_review", "RETRO_LOG", ("retrospective-log.md",)),
    ("generate", "PROJECT_PROFILES_DIR", ("config", "projects")),
])
def test_every_reader_and_writer_points_at_the_instance(inst_env, module, attr, rel):
    m = importlib.reload(importlib.import_module(module))
    assert getattr(m, attr) == inst_env.joinpath(*rel)


def test_the_brain_map_facts_read_run_results_from_the_instance():
    src = (ROOT / "brain-map" / "scripts" / "facts.py").read_text()
    assert 'REPO / "bench" / "metrics"' not in src
    assert 'instance.path("bench", "metrics")' in src


def test_the_retrospective_integrity_check_defaults_to_the_instance_repo(inst_env):
    import verify_retrospective_integrity as v
    assert v.default_repo() == inst_env


def test_the_deliverable_guard_sends_plans_to_the_instance_not_the_public_engine():
    import deliverable_location_guard as g
    assert "~/.agents/instance/docs/plans/" in g.REASON
    assert "~/.agents/docs/plans/" not in g.REASON


# ── code_sync carries the nested instance repo ───────────────────────────────

def _git(cwd: Path, *a: str) -> str:
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _repo_with_origin(tmp_path: Path, name: str, clone_at: Path) -> Path:
    remote = tmp_path / f"{name}.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    _git(tmp_path, "clone", "-q", str(remote), str(clone_at))
    _git(clone_at, "checkout", "-q", "-b", "main")
    (clone_at / "README.md").write_text(f"{name}\n")
    _git(clone_at, "add", "-A")
    _git(clone_at, "commit", "-qm", "init")
    _git(clone_at, "push", "-q", "origin", "main")
    return remote


@pytest.fixture
def engine_and_instance(tmp_path, monkeypatch):
    from test_code_sync_push import _quiet
    _quiet(monkeypatch, tmp_path / "sync-log.md")
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}.items():
        monkeypatch.setenv(k, v)
    engine = tmp_path / "engine"
    eng_remote = _repo_with_origin(tmp_path, "engine", engine)
    (engine / ".gitignore").write_text("/instance/\n")
    _git(engine, "add", "-A")
    _git(engine, "commit", "-qm", "ignore instance")
    _git(engine, "push", "-q", "origin", "main")
    inst_remote = _repo_with_origin(tmp_path, "instance", engine / "instance")
    return engine, eng_remote, inst_remote


def _remote_head(remote: Path) -> str:
    return _git(remote.parent, "--git-dir", str(remote), "rev-parse", "main")


def test_pushing_the_engine_also_pushes_its_instance(engine_and_instance, monkeypatch):
    import code_sync as cs
    engine, eng_remote, inst_remote = engine_and_instance
    (engine / "instance" / "plan.md").write_text("private plan\n")
    before_engine = _remote_head(eng_remote)
    monkeypatch.setattr(sys, "argv", ["code_sync.py", "push", str(engine)])

    cs.main()

    assert _remote_head(inst_remote) == _git(engine / "instance", "rev-parse", "HEAD")
    assert "plan.md" in _git(engine / "instance", "show", "--stat", "HEAD")
    assert _remote_head(eng_remote) == before_engine, "the instance's change must not touch the public engine"


def test_pulling_the_engine_also_pulls_its_instance(engine_and_instance, tmp_path, monkeypatch):
    import code_sync as cs
    engine, _, inst_remote = engine_and_instance
    other = tmp_path / "other-mac"
    _git(tmp_path, "clone", "-q", str(inst_remote), str(other))
    (other / "from-laptop.md").write_text("x\n")
    _git(other, "add", "-A")
    _git(other, "commit", "-qm", "laptop")
    _git(other, "push", "-q", "origin", "main")
    monkeypatch.setattr(sys, "argv", ["code_sync.py", "pull", str(engine)])

    cs.main()

    assert (engine / "instance" / "from-laptop.md").exists()


def test_an_engine_without_an_instance_syncs_exactly_as_before(tmp_path, monkeypatch):
    """A fresh install before `setup.sh --new`, or the Kali node, which never gets the instance (ADR 0069)."""
    import code_sync as cs
    calls = []
    monkeypatch.setattr(cs, "push", lambda repo, *a, **k: calls.append(repo))
    (tmp_path / "engine").mkdir()
    monkeypatch.setattr(sys, "argv", ["code_sync.py", "push", str(tmp_path / "engine")])
    cs.main()
    assert calls == [tmp_path / "engine"]


def test_a_plain_instance_folder_that_is_not_a_repo_is_left_alone(tmp_path, monkeypatch):
    import code_sync as cs
    calls = []
    monkeypatch.setattr(cs, "push", lambda repo, *a, **k: calls.append(repo))
    (tmp_path / "engine" / "instance").mkdir(parents=True)
    monkeypatch.setattr(sys, "argv", ["code_sync.py", "push", str(tmp_path / "engine")])
    cs.main()
    assert calls == [tmp_path / "engine"]


def test_the_instance_is_synced_even_when_the_engine_step_raises(tmp_path, monkeypatch):
    """A broken engine sync must not strand the owner's private state unsynced."""
    import code_sync as cs
    calls = []

    def push(repo, *a, **k):
        calls.append(repo)
        if repo.name == "engine":
            raise RuntimeError("engine push blew up")
    monkeypatch.setattr(cs, "push", push)
    (tmp_path / "engine" / "instance" / ".git").mkdir(parents=True)
    monkeypatch.setattr(sys, "argv", ["code_sync.py", "push", str(tmp_path / "engine")])
    with pytest.raises(RuntimeError):
        cs.main()
    assert calls == [tmp_path / "engine", tmp_path / "engine" / "instance"]
