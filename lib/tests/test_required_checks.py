"""marvin#826 step 1: one required-checks list per project, read by GitHub CI and by the merge gate. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_required_checks.py -v

The list lives in the project's own repo (.github/required-checks.json), because GitHub CI can only read the repo it
runs in; the private instance profile cannot be read there. CI runs each check through .github/run-check.sh, the
merge gate runs the same script, and lib/project_profile.py folds the list into a project's verify steps. These tests
try to make the three disagree: a check with no CI job, a CI job that runs something else, a list that names a check
twice, a runner that swallows a failure.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import required_checks as rc  # noqa: E402
import project_profile as pp  # noqa: E402

RUNNER = ROOT / ".github" / "run-check.sh"
needs_jq = pytest.mark.skipif(not shutil.which("jq"), reason="jq is not installed")


# ── the list itself ─────────────────────────────────────────────────────────

def test_marvin_has_a_list_and_every_check_is_well_formed():
    checks = rc.load(ROOT)
    assert {c["id"] for c in checks} >= {"python", "dashboard", "secret-scan"}
    for c in checks:
        assert c["name"] and c["where"] in ("both", "ci")
        if c["where"] == "both":
            assert c["command"] and all(isinstance(a, str) for a in c["command"])


@pytest.mark.parametrize("bad,why", [
    ({"checks": [{"id": "a", "name": "A", "command": ["true"]}, {"id": "a", "name": "B", "command": ["true"]}]}, "twice"),
    ({"checks": [{"id": "a", "name": "A", "command": ["true"]}, {"id": "b", "name": "A", "command": ["true"]}]}, "twice"),
    ({"checks": [{"id": "a", "name": "A"}]}, "command"),
    ({"checks": [{"id": "a", "name": "A", "command": "make test"}]}, "command"),
    ({"checks": [{"id": "A B", "name": "A", "command": ["true"]}]}, "id"),
    ({"checks": [{"id": "a", "command": ["true"]}]}, "name"),
    ({"checks": [{"id": "a", "name": "A", "command": ["true"], "where": "laptop"}]}, "where"),
    ({"checks": []}, "no checks"),
    ({"checks": "python"}, "no checks"),
    ([], "no checks"),
])
def test_a_malformed_list_is_refused_with_a_reason(tmp_path, bad, why):
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "required-checks.json").write_text(json.dumps(bad))
    with pytest.raises(ValueError, match=why):
        rc.load(tmp_path)


def test_no_list_reads_as_none_and_broken_json_is_an_error(tmp_path):
    assert rc.load(tmp_path) is None
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "required-checks.json").write_text("{nope")
    with pytest.raises(ValueError, match="JSON"):
        rc.load(tmp_path)


def test_the_branch_protection_names_are_every_check_in_order():
    assert rc.names(ROOT) == [c["name"] for c in rc.load(ROOT)]


# ── GitHub CI runs exactly the list ─────────────────────────────────────────

def _jobs(repo: Path) -> dict:
    return yaml.safe_load((repo / ".github" / "workflows" / "ci.yml").read_text())["jobs"]


def test_every_required_check_is_a_ci_job_with_the_same_name():
    job_names = {j.get("name") for j in _jobs(ROOT).values()}
    missing = [c["name"] for c in rc.load(ROOT) if c["name"] not in job_names]
    assert not missing, f"required checks with no CI job (branch protection would wait forever): {missing}"


def test_each_ci_job_for_a_shared_check_runs_it_through_the_runner_not_its_own_copy():
    by_name = {j.get("name"): j for j in _jobs(ROOT).values()}
    for c in rc.load(ROOT):
        if c["where"] != "both":
            continue
        runs = " ".join(s.get("run", "") for s in by_name[c["name"]]["steps"])
        assert f".github/run-check.sh {c['id']}" in runs, f"CI job '{c['name']}' does not run the list's command"


def test_the_drift_check_catches_a_job_renamed_on_one_side(tmp_path):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "required-checks.json").write_text(json.dumps(
        {"checks": [{"id": "unit", "name": "Unit tests", "command": ["true"]}]}))
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(
        "jobs:\n  unit:\n    name: Unit test\n    steps:\n      - run: .github/run-check.sh unit\n")
    assert rc.ci_drift(tmp_path) == ["Unit tests: no CI job has this name"]
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(
        "jobs:\n  unit:\n    name: Unit tests\n    steps:\n      - run: npm test\n")
    assert rc.ci_drift(tmp_path) == ["Unit tests: the CI job does not run .github/run-check.sh unit"]


def test_marvin_has_no_drift():
    assert rc.ci_drift(ROOT) == []


# ── the shared runner ───────────────────────────────────────────────────────

def _repo(tmp_path: Path, checks: list[dict]) -> Path:
    (tmp_path / ".github").mkdir(exist_ok=True)
    shutil.copy(RUNNER, tmp_path / ".github" / "run-check.sh")
    (tmp_path / ".github" / "required-checks.json").write_text(json.dumps({"checks": checks}))
    return tmp_path


def _run(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", ".github/run-check.sh", *args], cwd=repo, capture_output=True, text=True,
                          env={**os.environ, **(env or {})}, timeout=60)


@needs_jq
def test_the_runner_runs_the_command_in_its_cwd_and_passes_the_exit_code_through(tmp_path):
    (tmp_path / "sub").mkdir()
    repo = _repo(tmp_path, [
        {"id": "ok", "name": "OK", "cwd": "sub", "command": ["bash", "-c", "pwd; echo 'two words'"]},
        {"id": "bad", "name": "Bad", "command": ["bash", "-c", "echo failing; exit 3"]},
    ])
    ok = _run(repo, "ok")
    assert ok.returncode == 0 and ok.stdout.splitlines()[-2:] == [str((tmp_path / "sub").resolve()), "two words"]
    bad = _run(repo, "bad")
    assert bad.returncode == 3 and "failing" in bad.stdout


@needs_jq
def test_the_runner_keeps_arguments_with_spaces_and_quotes_whole(tmp_path):
    repo = _repo(tmp_path, [{"id": "q", "name": "Q", "command": ["printf", "[%s]", "a b", "it's", "$HOME", "`x`"]}])
    assert _run(repo, "q").stdout.endswith("[a b][it's][$HOME][`x`]")


@needs_jq
@pytest.mark.parametrize("args,needle", [(["nope"], "no check 'nope'"), ([], "usage")])
def test_the_runner_refuses_an_unknown_or_missing_id(tmp_path, args, needle):
    repo = _repo(tmp_path, [{"id": "ok", "name": "OK", "command": ["true"]}])
    r = _run(repo, *args)
    assert r.returncode == 2 and needle in r.stderr


@needs_jq
def test_the_runner_will_not_run_a_ci_only_check_locally_by_accident(tmp_path):
    repo = _repo(tmp_path, [{"id": "scan", "name": "Scan", "where": "ci"}])
    r = _run(repo, "scan")
    assert r.returncode == 2 and "runs in CI only" in r.stderr


# ── the merge gate and pipeline read the same list (lib/project_profile.py) ─

PROFILE = {"repo": "o/p", "verify": [
    {"id": "unit", "label": "old unit", "command": ["swift", "test"], "required": True},
    {"id": "lint", "label": "Lint (optional)", "command": ["swiftlint"], "required": False},
]}


def test_the_profile_takes_its_required_checks_from_the_repo_list(tmp_path):
    _repo(tmp_path, [
        {"id": "unit", "name": "Unit tests", "cwd": "Pkg", "command": ["swift", "test"], "parser": "swift-test",
         "requires": ["swift"], "timeout_s": 900},
        {"id": "scan", "name": "Secret scan", "where": "ci"},
    ])
    p = pp.with_required_checks(pp._validate(json.loads(json.dumps(PROFILE)), "t"), tmp_path)
    by_id = {t["id"]: t for t in p["verify"]}
    assert set(by_id) == {"unit", "lint"}  # the CI-only scan is not run by the gate
    unit = by_id["unit"]
    assert unit["command"] == ["bash", ".github/run-check.sh", "unit"] and unit["cwd"] == "."
    assert (unit["label"], unit["parser"], unit["requires"], unit["timeout_s"], unit["required"]) == \
           ("Unit tests", "swift-test", ["swift"], 900, True)
    assert by_id["lint"]["required"] is False  # optional steps the list doesn't name are kept


def test_a_profile_required_step_the_list_dropped_stops_being_required(tmp_path):
    _repo(tmp_path, [{"id": "other", "name": "Other", "command": ["true"]}])
    p = pp.with_required_checks(pp._validate(json.loads(json.dumps(PROFILE)), "t"), tmp_path)
    assert [t["id"] for t in p["verify"] if t["required"]] == ["other"]


def test_a_repo_without_a_list_keeps_its_profile_unchanged(tmp_path):
    p = pp._validate(json.loads(json.dumps(PROFILE)), "t")
    assert pp.with_required_checks(p, tmp_path) == p


def test_verify_dir_runs_the_list_through_the_runner(tmp_path):
    _repo(tmp_path, [{"id": "unit", "name": "Unit tests", "command": ["true"], "parser": "exit-code"}])
    seen = []

    def runner(cmd, cwd, env, timeout):
        seen.append((cmd, Path(cwd)))
        return 0, "ok"
    r = pp.verify_dir(pp._validate({"repo": "o/p", "verify": []}, "t"), tmp_path, runner=runner, have=lambda c, e: True)
    assert r["ok"] and seen == [(["bash", ".github/run-check.sh", "unit"], tmp_path)]


def test_a_check_the_pr_does_not_affect_passes_the_gate_whatever_its_parser(tmp_path):
    # run-check.sh prints this and exits 0 when no path the check covers changed (step 3); every parser must read it
    # as "nothing to run", not as a crash with no result.
    _repo(tmp_path, [{"id": "unit", "name": "Unit", "command": ["swift", "test"], "parser": "swift-test"},
                     {"id": "app", "name": "App", "command": ["xcodebuild"], "parser": "xcodebuild"}])
    out = "run-check: unit: not affected by this change (nothing it covers changed since origin/main): no tests ran\n"
    r = pp.verify_dir(pp._validate({"repo": "o/p", "verify": []}, "t"), tmp_path,
                      runner=lambda cmd, cwd, env, timeout: (0, out), have=lambda c, e: True)
    assert r["ok"] and r["kind"] == "passed", r


def test_ci_runs_the_python_suite_in_parallel_as_the_gate_does():
    # Serial on GitHub's 3-core macOS runner the full suite passed its 40-minute limit at 86% (2026-10-30).
    job = _jobs(ROOT)["python-tests"]
    assert "-n auto" in job["env"]["PYTEST_ADDOPTS"] and job["timeout-minutes"] >= 60
