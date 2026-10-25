"""Tests for project playbooks (config/playbooks/, project_profile.load_playbook and executor_notes; marvin #613).
Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_playbooks.py -v
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
REPO = LIB.parent
sys.path.insert(0, str(LIB))

import project_profile as pp  # noqa: E402

REAL_PLAYBOOKS = REPO / "config" / "playbooks"
import instance  # noqa: E402
REAL_PROFILES = instance.path("config", "projects")  # the owner's real profiles live in the private instance (ADR 0071)
needs_instance = pytest.mark.skipif(not REAL_PROFILES.is_dir(), reason="needs the owner's instance; runs on the owner's machines")


@pytest.fixture(autouse=True)
def temp_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    pp._PLAYBOOK_CACHE.clear()
    return home


def _base(**kw):
    return {"repo": "G-Eskayo/app", "verify": [], **kw}


# ── loading and validating ──────────────────────────────────────────────────

def test_the_shipped_ios_playbook_loads_with_every_section():
    pb = pp.load_playbook("ios-app")
    ids = [s["id"] for s in pb["stages"]]
    assert ids[:3] == ["ticket", "design", "build"] and "ship" in ids and "after-ship" in ids
    for s in pb["stages"]:
        assert s["proof"] and s["machine"], s["id"]
    assert pb["owner_gates"] and pb["machines"] and pb["known_traps"] and pb["ship_checklist"]
    assert "macos" in pb["variants"]


def test_the_md_and_json_name_the_same_stages():
    md = (REAL_PLAYBOOKS / "ios-app.md").read_text()
    for s in pp.load_playbook("ios-app")["stages"]:
        assert s["label"] in md, f"stage {s['id']} ({s['label']}) is missing from ios-app.md"


def test_an_unknown_playbook_is_a_clear_error_naming_it_and_the_known_ones():
    with pytest.raises(ValueError) as e:
        pp._validate(_base(playbook="android-app"), "x.json")
    msg = str(e.value)
    assert "x.json" in msg and "android-app" in msg and "ios-app" in msg


@pytest.mark.parametrize("name", ["../projects/marvin", "ios-app/../../x", "", "IOS APP", 7, None, ["ios-app"]])
def test_a_playbook_name_that_is_not_a_plain_slug_is_refused_never_read_as_a_path(name):
    with pytest.raises(ValueError):
        pp._validate(_base(playbook=name), "x.json")


def test_an_unknown_variant_is_a_clear_error():
    with pytest.raises(ValueError) as e:
        pp._validate(_base(playbook="ios-app", playbook_variant="watchos"), "x.json")
    assert "watchos" in str(e.value) and "macos" in str(e.value)


def test_a_variant_without_a_playbook_is_an_error():
    with pytest.raises(ValueError):
        pp._validate(_base(playbook_variant="macos"), "x.json")


def test_malformed_playbook_json_is_a_clear_error_not_a_crash(tmp_path, monkeypatch):
    d = tmp_path / "pb"
    d.mkdir()
    (d / "broken.json").write_text('{"name": "broken", "stages": [')
    monkeypatch.setattr(pp, "PLAYBOOKS_DIR", d)
    with pytest.raises(ValueError) as e:
        pp.load_playbook("broken")
    assert "broken.json" in str(e.value) and "JSON" in str(e.value)


@pytest.mark.parametrize("body", [
    [],                                                        # not an object
    {"name": "p"},                                             # no stages
    {"name": "p", "stages": []},                               # empty stages
    {"name": "p", "stages": [{"id": "a", "label": "A"}]},      # a stage without proof
    {"name": "p", "stages": [{"id": "a", "label": "A", "proof": ["x"], "machine": "m"},
                             {"id": "a", "label": "B", "proof": ["y"], "machine": "m"}]},  # duplicate id
    {"name": "other", "stages": [{"id": "a", "label": "A", "proof": ["x"], "machine": "m"}]},  # name mismatch
    {"name": "p", "stages": [{"id": "a", "label": "A", "proof": ["x"], "machine": "m"}],
     "variants": {"v": {"drop_stages": ["nope"]}}},              # a variant dropping a stage that doesn't exist
])
def test_a_structurally_wrong_playbook_is_refused(tmp_path, monkeypatch, body):
    d = tmp_path / "pb"
    d.mkdir()
    (d / "p.json").write_text(json.dumps(body))
    monkeypatch.setattr(pp, "PLAYBOOKS_DIR", d)
    with pytest.raises(ValueError):
        pp.load_playbook("p")


def test_a_profile_pointing_at_a_broken_playbook_does_not_hide_other_profiles(tmp_path, monkeypatch):
    d = tmp_path / "projects"
    d.mkdir()
    (d / "a.json").write_text(json.dumps(_base(repo="G-Eskayo/a", playbook="nope")))
    (d / "b.json").write_text(json.dumps(_base(repo="G-Eskayo/b", playbook="ios-app")))
    assert [p["repo"] for p in pp.all_profiles(directory=d)] == ["G-Eskayo/b"]
    with pytest.raises(ValueError):
        pp.load_profile("G-Eskayo/a", directory=d)


# ── the macos variant ───────────────────────────────────────────────────────

def test_the_macos_variant_drops_testflight_and_the_device_check():
    full = [s["id"] for s in pp.load_playbook("ios-app")["stages"]]
    mac = pp.load_playbook("ios-app", "macos")
    ids = [s["id"] for s in mac["stages"]]
    assert "ship" in full and "device-check" in full
    assert "ship" not in ids and "after-ship" not in ids and "device-check" not in ids
    assert mac["ship_checklist"] == []
    blob = json.dumps(mac["stages"])
    assert "TestFlight" not in blob and "simctl" not in blob
    assert ids[:3] == ["ticket", "design", "build"] and "merge" in ids  # order kept


def test_resolving_a_variant_never_mutates_the_cached_base_playbook():
    pp.load_playbook("ios-app", "macos")
    assert "ship" in [s["id"] for s in pp.load_playbook("ios-app")["stages"]]


# ── executor notes generated from the playbook ──────────────────────────────

def test_executor_notes_keep_the_projects_own_notes_first_and_add_proof_and_owner_gates():
    prof = pp._validate(_base(playbook="ios-app", executor={"notes": "This is the app. Read CLAUDE.md."}), "x")
    notes = pp.executor_notes(prof)
    assert notes.startswith("This is the app. Read CLAUDE.md.")
    tail = notes.split(pp.PLAYBOOK_MARKER, 1)[1]
    assert "swift test" in tail and "Owner gates" in tail and "bundle id" in tail
    assert "Ship" not in tail  # the owner's stages are not the executor's job


def test_executor_notes_are_idempotent_even_when_a_generated_section_was_pasted_into_the_profile():
    prof = pp._validate(_base(playbook="ios-app", executor={"notes": "Own notes."}), "x")
    once = pp.executor_notes(prof)
    pasted = pp._validate(_base(playbook="ios-app", executor={"notes": once}), "x")
    assert pp.executor_notes(pasted) == once
    assert once.count(pp.PLAYBOOK_MARKER) == 1


def test_executor_notes_without_a_playbook_are_exactly_the_profiles_notes():
    assert pp.executor_notes(_base(executor={"notes": "Just these."})) == "Just these."
    assert pp.executor_notes(_base()) == ""


def test_executor_notes_with_only_a_playbook_are_just_the_generated_section():
    notes = pp.executor_notes(pp._validate(_base(playbook="ios-app"), "x"))
    assert notes.startswith(pp.PLAYBOOK_MARKER)


def test_look_proof_note_matches_whether_the_profile_captures_the_simulator():
    with_cap = pp._validate(_base(playbook="ios-app", evidence={"dev": {"ios_simulator": {"scheme": "S"}}}), "x")
    without = pp._validate(_base(playbook="ios-app"), "x")
    assert "screenshots the profile's scenes itself" in pp.executor_notes(with_cap)
    assert "takes no screenshots" in pp.executor_notes(without)


def test_macos_variant_notes_never_mention_testflight_or_the_ios_simulator_capture():
    prof = pp._validate(_base(playbook="ios-app", playbook_variant="macos"), "x")
    notes = pp.executor_notes(prof)
    assert "TestFlight" not in notes and "iOS Simulator" not in notes and "macOS app" in notes


# ── selftest flags a profile that can never run ─────────────────────────────

def test_selftest_flags_dispatch_on_with_no_machines_before_touching_any_clone(tmp_path):
    prof = _base(dispatch="on", machines=[], clone_hints=[str(tmp_path / "gone")])
    r = pp.selftest(prof, runner=lambda *a: (_ for _ in ()).throw(AssertionError("must not run")),
                    have=lambda c, e: True, catalog={"projects": []})
    assert r["ok"] is False and r["kind"] == "profile" and "machines" in r["error"]


def test_profile_problems_is_quiet_for_dispatch_off_or_listed_machines():
    assert pp.profile_problems(_base(dispatch="off", machines=[])) == []
    assert pp.profile_problems(_base(dispatch="on", machines=["mac-mini-1"])) == []
    assert pp.profile_problems(_base(dispatch="on", machines=[]))


@needs_instance
def test_the_home_repo_is_never_called_unrunnable_because_the_pipeline_runs_it_on_every_machine(tmp_path):
    # ticket_pipeline dispatches G-Eskayo/marvin whatever its profile lists; listing a machine would narrow it
    assert pp.profile_problems(_base(repo=pp.HOME_REPO, dispatch="on", machines=[])) == []
    assert pp.HOME_REPO not in pp.unrunnable_repos(directory=REAL_PROFILES)
    # callers add HOME_REPO themselves ([REPO, *runnable_repos()]): it must not appear here too, or it is scanned twice
    assert pp.HOME_REPO not in pp.runnable_repos(directory=REAL_PROFILES)


def test_only_the_exact_home_repo_is_exempt_not_a_lookalike():
    for repo in ("G-Eskayo/marvin-mobile", "g-eskayo/marvin-x", "Other/marvin"):
        assert pp.profile_problems(_base(repo=repo, dispatch="on", machines=[]))


def test_selftest_reports_an_unknown_playbook_as_a_profile_error_not_a_crash(tmp_path):
    r = pp.selftest(_base(playbook="nope", clone_hints=[str(tmp_path)]), have=lambda c, e: True, catalog={"projects": []})
    assert r["ok"] is False and r["kind"] == "profile" and "nope" in r["error"]


# ── the real profiles in this repo ──────────────────────────────────────────

APP_PROFILES = ["G-Eskayo/clarity-captions", "G-Eskayo/marvin-mobile", "G-Eskayo/nourished", "G-Eskayo/killer-sudoku"]


@needs_instance
def test_every_real_profile_still_validates_so_none_is_silently_dropped():
    profiles = pp.all_profiles(directory=REAL_PROFILES)
    assert len(profiles) == len(list(REAL_PROFILES.glob("*.json")))


@needs_instance
@pytest.mark.parametrize("repo", APP_PROFILES)
def test_no_app_profile_can_never_run(repo):
    p = pp.load_profile(repo, directory=REAL_PROFILES)
    assert pp.profile_problems(p) == [] and repo not in pp.unrunnable_repos(directory=REAL_PROFILES)


@needs_instance
@pytest.mark.parametrize("repo,variant", [
    ("G-Eskayo/clarity-captions", None), ("G-Eskayo/marvin-mobile", None),
    ("G-Eskayo/nourished", None), ("G-Eskayo/killer-sudoku", "macos")])
def test_the_four_app_profiles_name_the_ios_playbook(repo, variant):
    p = pp.load_profile(repo, directory=REAL_PROFILES)
    assert p["playbook"] == "ios-app" and p.get("playbook_variant") == variant


@needs_instance
def test_clarity_captions_notes_no_longer_say_the_app_cannot_be_built():
    p = pp.load_profile("G-Eskayo/clarity-captions", directory=REAL_PROFILES)
    assert "cannot build" not in pp.executor_notes(p)
    assert any(t["id"] == "spike-app" and t["required"] for t in p["verify"])


@needs_instance
def test_nourished_stays_off_and_has_a_real_verify_step():
    p = pp.load_profile("G-Eskayo/nourished", directory=REAL_PROFILES)
    assert p["dispatch"] == "off" and p["verify"] and any(t["required"] for t in p["verify"])
