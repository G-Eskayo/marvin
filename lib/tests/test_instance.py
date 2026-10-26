"""ADR 0071 step 1: lib/instance.py, the one place engine code asks "whose MARVIN is this?". Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_instance.py -v

The engine is public and shared; each person's MARVIN is a private instance. Engine code must not hard-code the
owner, so a friend's clone files tickets against their own fork, not G-Eskayo/marvin. Real temp git repos, never the
real ~/.agents/instance.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import instance  # noqa: E402


def _engine(tmp_path: Path, origin: str | None) -> Path:
    e = tmp_path / f"engine{len(list(tmp_path.glob('engine*')))}"
    e.mkdir()
    subprocess.run(["git", "init", "-q", str(e)], check=True)
    if origin:
        subprocess.run(["git", "-C", str(e), "remote", "add", "origin", origin], check=True)
    return e


@pytest.fixture
def at(tmp_path, monkeypatch):
    """Point instance.py at a temp engine checkout and a temp instance dir; returns a setter for both."""
    def _at(origin: str | None = None, config: dict | str | None = None) -> Path:
        e = _engine(tmp_path, origin)
        d = tmp_path / "inst"
        d.mkdir(exist_ok=True)
        if config is not None:
            (d / "instance.json").write_text(config if isinstance(config, str) else json.dumps(config))
        monkeypatch.setattr(instance, "ENGINE_DIR", e)
        monkeypatch.setenv("MARVIN_INSTANCE_DIR", str(d))
        instance.reset()
        return d
    yield _at
    instance.reset()


@pytest.mark.parametrize("url", [
    "https://github.com/pat-example/marvin.git",
    "https://github.com/pat-example/marvin",
    "git@github.com:pat-example/marvin.git",
    "ssh://git@github.com/pat-example/marvin.git",
    "https://x-access-token:abc@github.com/pat-example/marvin.git",
])
def test_the_engine_repo_is_derived_from_the_clones_own_origin(at, url):
    at(origin=url)
    assert instance.engine_repo() == "pat-example/marvin"
    assert instance.owner() == "pat-example"


def test_a_friends_fork_is_never_mistaken_for_the_upstream(at):
    at(origin="https://github.com/pat-example/marvin.git")
    assert instance.engine_repo() != instance.UPSTREAM
    assert instance.UPSTREAM == "G-Eskayo/marvin"


def test_no_origin_falls_back_to_the_config_then_the_upstream(at):
    at(origin=None, config={"engine_repo": "pat-example/marvin"})
    assert instance.engine_repo() == "pat-example/marvin"
    at(origin=None, config={})
    assert instance.engine_repo() == instance.UPSTREAM


def test_the_real_origin_beats_a_stale_engine_repo_in_the_config(at):
    """Derived beats stored: a config copied from someone else's instance must not redirect tickets."""
    at(origin="https://github.com/pat-example/marvin.git", config={"engine_repo": "G-Eskayo/marvin"})
    assert instance.engine_repo() == "pat-example/marvin"


def test_a_feature_is_on_only_for_a_real_true(at):
    """A hand-edited "false" or "yes" string, or 1, must not switch a feature on."""
    at(origin=None, config={"features": {"a": "false", "b": "yes", "c": 1, "d": True}})
    assert [instance.feature_enabled(k) for k in "abcd"] == [False, False, False, True]


def test_a_non_github_origin_is_not_parsed_into_a_fake_repo(at):
    at(origin="/Users/someone/marvin-mirror.git", config={})
    assert instance.engine_repo() == instance.UPSTREAM


def test_the_config_owner_wins_over_the_origin(at):
    """An org-owned fork: the repo owner isn't the person; the config says who the person is."""
    at(origin="https://github.com/some-org/marvin.git", config={"owner": "pat-example"})
    assert instance.owner() == "pat-example"
    assert instance.engine_repo() == "some-org/marvin"


def test_tickets_go_to_the_engine_repo_unless_configured(at):
    at(origin="https://github.com/pat-example/marvin.git")
    assert instance.tickets_repo() == "pat-example/marvin"
    at(origin="https://github.com/pat-example/marvin.git", config={"tickets_repo": "pat-example/marvin-instance"})
    assert instance.tickets_repo() == "pat-example/marvin-instance"


def test_features_are_off_until_the_instance_turns_them_on(at):
    at(origin=None, config={})
    assert instance.feature_enabled("portfolio") is False
    at(origin=None, config={"features": {"portfolio": True, "resume_tailor": False}})
    assert instance.feature_enabled("portfolio") is True
    assert instance.feature_enabled("resume_tailor") is False
    assert instance.feature_enabled("unknown_thing") is False


@pytest.mark.parametrize("bad", ["{not json", "[]", '"a string"', '{"features": "yes"}', '{"owner": 7}'])
def test_a_corrupt_or_wrong_shaped_config_reads_as_a_blank_instance(at, bad):
    at(origin="https://github.com/pat-example/marvin.git", config=bad)
    assert instance.owner() == "pat-example"
    assert instance.feature_enabled("portfolio") is False


def test_a_missing_instance_dir_is_a_blank_instance_not_a_crash(at, tmp_path, monkeypatch):
    at(origin=None)
    monkeypatch.setenv("MARVIN_INSTANCE_DIR", str(tmp_path / "does-not-exist"))
    instance.reset()
    assert instance.engine_repo() == instance.UPSTREAM
    assert instance.feature_enabled("portfolio") is False
    assert instance.instance_dir() == tmp_path / "does-not-exist"


def test_instance_path_joins_under_the_instance_dir(at):
    d = at(origin=None)
    assert instance.path("plans", "x.md") == d / "plans" / "x.md"


def test_the_default_instance_dir_is_home_agents_instance_even_from_a_worktree(monkeypatch, tmp_path):
    """The pipeline runs engine code from worktrees; they must all find the one real instance."""
    monkeypatch.delenv("MARVIN_INSTANCE_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(instance, "ENGINE_DIR", tmp_path / "some-worktree")
    assert instance.instance_dir() == tmp_path / ".agents" / "instance"


def test_the_config_file_is_read_once_per_process(at, monkeypatch):
    """O(1) after the first call: engine code calls these in loops."""
    d = at(origin="https://github.com/pat-example/marvin.git", config={"owner": "pat-example"})
    instance.owner()
    (d / "instance.json").write_text(json.dumps({"owner": "changed"}))
    assert instance.owner() == "pat-example"
    instance.reset()
    assert instance.owner() == "changed"


def test_the_engine_never_tracks_the_instance_dir():
    """The instance is a separate private repo nested at ~/.agents/instance/; the engine must ignore all of it."""
    r = subprocess.run(["git", "check-ignore", "-q", "instance/plans/secret.md"], cwd=ROOT)
    assert r.returncode == 0
    tracked = subprocess.run(["git", "ls-files", "instance"], cwd=ROOT, capture_output=True, text=True).stdout
    assert tracked == ""


# ── the ratchet: no new hard-coded owner, account or machine in engine code ───────────────────────────────────────

IDENTITY = re.compile(r"""["'`][^"'`\n]*(G-Eskayo|gileskayo|gils-mac-mini|marvin-laptop|\bGiles?\b|\bGil\b)[^"'`\n]*["'`]""")
COMMENT = re.compile(r"""^\s*(#|//|\*|/\*)""")
CODE = ["*.py", "*.js", "*.jsx", "*.ts", "*.mjs", "*.sh"]
NOT_ENGINE_CODE = re.compile(r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]*\.py$|\.test\.(js|jsx|ts|mjs)$|^bench/metrics/|^docs/")

# Files that hard-coded an identity when this test landed (2026-10-25). ADR 0071 step 3 empties this list.
# Never add to it: read the owner and repos from lib/instance.py (or electron/main/instance.js) instead.
GRANDFATHERED = set((ROOT / "lib" / "tests" / "instance_grandfathered.txt").read_text().split())


def _offenders() -> set[str]:
    files = subprocess.run(["git", "ls-files", "--", *CODE], cwd=ROOT, capture_output=True, text=True).stdout.split()
    out = set()
    for f in files:
        if NOT_ENGINE_CODE.search(f) or f in {"lib/instance.py", "dashboard/electron/main/instance.js"}:
            continue
        try:
            lines = (ROOT / f).read_text(errors="replace").splitlines()
        except OSError:
            continue
        if any(IDENTITY.search(l) and not COMMENT.match(l) for l in lines):
            out.add(f)
    return out


def test_no_new_engine_file_hard_codes_an_owner_account_or_machine():
    new = sorted(_offenders() - GRANDFATHERED)
    assert new == [], f"use lib/instance.py (owner(), engine_repo(), tickets_repo()) instead of hard-coding: {new}"


def test_the_grandfathered_list_only_shrinks():
    """A file that was cleaned up must come off the list, or a later regression in it would pass unnoticed."""
    fixed = sorted(GRANDFATHERED - _offenders())
    assert fixed == [], f"no longer hard-codes an identity; remove from instance_grandfathered.txt: {fixed}"


def test_the_ratchet_catches_a_quoted_owner_but_not_a_comment(tmp_path):
    assert IDENTITY.search('OWNER = "G-Eskayo"')
    assert IDENTITY.search("const r = `G-Eskayo/${name}`")
    assert IDENTITY.search("label = 'asks Gil first'")
    assert not IDENTITY.search("OWNER = instance.owner()")
    assert COMMENT.match("    # see G-Eskayo/marvin#21")
    assert COMMENT.match("  // G-Eskayo/marvin")
    assert not IDENTITY.search('msg = "Gilbert and Gilda"')


# ── configuration check: is_configured() and require_configured() ────────────────────────────────────────────

def test_is_configured_true_when_origin_is_a_real_github_url(at):
    at(origin="https://github.com/pat-example/marvin.git")
    assert instance.is_configured() is True


def test_is_configured_true_when_engine_repo_is_in_config(at):
    at(origin=None, config={"engine_repo": "pat-example/marvin"})
    assert instance.is_configured() is True


def test_is_configured_true_when_owner_is_in_config(at):
    at(origin=None, config={"owner": "pat-example"})
    assert instance.is_configured() is True


def test_is_configured_true_when_tickets_repo_is_in_config(at):
    at(origin=None, config={"tickets_repo": "pat-example/tickets"})
    assert instance.is_configured() is True


def test_is_configured_false_when_nothing_is_set(at):
    at(origin=None, config={})
    assert instance.is_configured() is False


def test_is_configured_false_when_instance_is_missing(at, tmp_path, monkeypatch):
    at(origin=None)
    monkeypatch.setenv("MARVIN_INSTANCE_DIR", str(tmp_path / "does-not-exist"))
    instance.reset()
    assert instance.is_configured() is False


def test_require_configured_raises_when_not_configured(at):
    at(origin=None, config={})
    with pytest.raises(instance.NotConfiguredError):
        instance.require_configured()


def test_require_configured_does_not_raise_when_configured(at):
    at(origin="https://github.com/pat-example/marvin.git")
    instance.require_configured()  # should not raise
