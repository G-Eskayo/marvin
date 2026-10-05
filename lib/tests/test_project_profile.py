"""Tests for project_profile.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_project_profile.py -v
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import project_profile as pp  # noqa: E402

# Real output captured from `swift test` in Packages/CaptionCore on mac-mini, 2026-10-05.
XCTEST_OK = """Test Suite 'ThemeTests' passed at 2026-10-05 12:01:49.579.
\t Executed 3 tests, with 0 failures (0 unexpected) in 0.000 (0.000) seconds
Test Suite 'CaptionCorePackageTests.xctest' passed at 2026-10-05 12:01:49.579.
\t Executed 61 tests, with 1 test skipped and 0 failures (0 unexpected) in 0.023 (0.026) seconds
Test Suite 'All tests' passed at 2026-10-05 12:01:49.579.
\t Executed 61 tests, with 1 test skipped and 0 failures (0 unexpected) in 0.023 (0.028) seconds
◇ Test run started.
→ Testing Library Version: 1902
✔ Test run with 0 tests in 0 suites passed after 0.001 seconds.
"""
XCTEST_FAIL = """Test Suite 'All tests' failed at 2026-10-05 12:01:49.579.
\t Executed 12 tests, with 2 failures (0 unexpected) in 0.5 (0.5) seconds
"""
NO_XCTEST = "error: no such module 'XCTest'\nerror: fatalError\n"
SWIFT_TESTING_OK = "✔ Test run with 7 tests in 2 suites passed after 0.004 seconds.\n"
SWIFT_TESTING_FAIL = "✘ Test run with 5 tests in 1 suite failed after 0.1 seconds with 2 issues.\n"


# ── parsers ─────────────────────────────────────────────────────────────────

def test_swift_test_reads_the_final_xctest_summary_with_skips_not_counted_as_passed():
    r = pp.parse_swift_test(XCTEST_OK)
    assert (r["total"], r["failed"], r["skipped"], r["passed"]) == (61, 0, 1, 60)


def test_swift_test_reports_failures():
    r = pp.parse_swift_test(XCTEST_FAIL)
    assert (r["total"], r["failed"], r["passed"]) == (12, 2, 10)


def test_swift_test_adds_swift_testing_runs_to_the_xctest_totals():
    r = pp.parse_swift_test(XCTEST_OK + SWIFT_TESTING_OK)
    assert r["total"] == 68 and r["failed"] == 0
    assert pp.parse_swift_test(SWIFT_TESTING_FAIL)["failed"] == 2


def test_a_build_that_never_reached_the_tests_is_unparseable_not_zero():
    assert pp.parse_swift_test(NO_XCTEST) is None
    assert pp.parse_swift_test("") is None


def test_xcodebuild_parser_reads_succeeded_and_failed():
    assert pp.parse_xcodebuild("...\n** BUILD SUCCEEDED **\n") == {"build_ok": 1}
    assert pp.parse_xcodebuild("error: x\n** BUILD FAILED **\n") == {"build_ok": 0}
    assert pp.parse_xcodebuild("nothing useful") is None


# ── profile loading ─────────────────────────────────────────────────────────

def write_profile(tmp_path, **over):
    base = {"repo": "G-Eskayo/proj", "base_branch": "main", "dispatch": "off", "machines": ["mac-mini-1"],
            "verify": [{"id": "core", "label": "Core tests", "command": ["swift", "test"], "cwd": "Pkg", "requires": ["swift"],
                        "parser": "swift-test", "required": True}], "evidence": {"dev": {"na": "no simulator capture"}}}
    base.update(over)
    (tmp_path / "proj.json").write_text(json.dumps(base))
    return tmp_path


def test_loads_a_profile_by_repo_and_returns_none_for_a_repo_without_one(tmp_path):
    d = write_profile(tmp_path)
    assert pp.load_profile("G-Eskayo/proj", directory=d)["base_branch"] == "main"
    assert pp.load_profile("G-Eskayo/marvin", directory=d) is None


def test_a_profile_starts_with_dispatch_off_unless_it_says_otherwise(tmp_path):
    d = write_profile(tmp_path)
    assert pp.load_profile("G-Eskayo/proj", directory=d)["dispatch"] == "off"
    assert pp.dispatchable_repos(directory=d) == []
    d2 = write_profile(tmp_path, dispatch="on")
    assert pp.dispatchable_repos(directory=d2) == ["G-Eskayo/proj"]


def test_a_malformed_profile_is_reported_not_silently_used(tmp_path):
    (tmp_path / "bad.json").write_text(json.dumps({"repo": "G-Eskayo/bad", "verify": [{"id": "x"}]}))
    try:
        pp.load_profile("G-Eskayo/bad", directory=tmp_path)
    except ValueError as e:
        assert "command" in str(e)
    else:
        raise AssertionError("should refuse a tier with no command")


# ── capabilities / environment ──────────────────────────────────────────────

def test_env_uses_the_first_xcode_that_exists_without_touching_the_system_selection(tmp_path):
    xc = tmp_path / "Xcode.app" / "Contents" / "Developer"
    (xc / "usr" / "bin").mkdir(parents=True)
    profile = {"env": {"DEVELOPER_DIR": {"first_existing": ["/nope/Xcode.app", str(xc)]}}}
    assert pp.build_env(profile, base_env={"PATH": "/usr/bin"})["DEVELOPER_DIR"] == str(xc)
    assert pp.build_env({"env": {"DEVELOPER_DIR": {"first_existing": ["/nope"]}}}, base_env={"PATH": "/usr/bin"}).get("DEVELOPER_DIR") is None


def test_capabilities_are_checked_against_the_environment_the_commands_will_run_in(tmp_path):
    xc = tmp_path / "Developer"
    (xc / "usr" / "bin").mkdir(parents=True)
    (xc / "usr" / "bin" / "xcodebuild").write_text("")
    env = {"DEVELOPER_DIR": str(xc), "PATH": "/usr/bin"}
    assert pp.have("xcode", env, which=lambda n, path=None: None) is True
    assert pp.have("xcode", {"PATH": "/usr/bin"}, which=lambda n, path=None: None) is False
    assert pp.have("swift", env, which=lambda n, path=None: "/usr/bin/swift") is True
    assert pp.have("xcodegen", env, which=lambda n, path=None: None) is False


# ── clone resolution ────────────────────────────────────────────────────────

def test_finds_the_real_clone_through_the_catalog_then_the_hints(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    (a / ".git").mkdir(parents=True)
    (b / ".git").mkdir(parents=True)
    cat = {"projects": [{"id": "proj", "repo": "G-Eskayo/proj", "localPaths": [str(tmp_path / "gone"), str(a)]}]}
    assert pp.resolve_clone({"repo": "G-Eskayo/proj"}, catalog=cat) == a
    assert pp.resolve_clone({"repo": "G-Eskayo/proj", "clone_hints": [str(b)]}, catalog={"projects": []}) == b
    assert pp.resolve_clone({"repo": "G-Eskayo/proj"}, catalog={"projects": []}) is None


# ── measuring ───────────────────────────────────────────────────────────────

def runner_returning(outputs):
    calls = []

    def run(cmd, cwd, env, timeout):
        calls.append({"cmd": cmd, "cwd": str(cwd), "env_dev": env.get("DEVELOPER_DIR")})
        return outputs.pop(0)

    run.calls = calls
    return run


PROFILE = {"repo": "G-Eskayo/proj", "verify": [
    {"id": "core", "label": "Core tests", "command": ["swift", "test"], "cwd": "Pkg", "requires": ["swift"], "parser": "swift-test", "required": True},
    {"id": "app", "label": "App build", "command": ["xcodebuild"], "cwd": "App", "requires": ["xcodegen"], "parser": "xcodebuild", "required": False},
]}


def test_measure_runs_each_available_tier_in_its_cwd_and_shapes_metrics_for_the_comparison(tmp_path):
    (tmp_path / "Pkg").mkdir()
    runner = runner_returning([(0, XCTEST_OK)])
    m = pp.Measurer(PROFILE, runner=runner, have=lambda cap, env: cap == "swift")
    metrics = m(tmp_path)
    assert metrics["core_passed"] == {"value": 60, "higher_is_better": True}
    assert metrics["core_failed"] == {"value": 0, "higher_is_better": False}
    assert metrics["tests_passed"]["value"] == 60 and metrics["tests_failed"]["value"] == 0
    assert runner.calls[0]["cwd"] == str(tmp_path / "Pkg")


def test_an_optional_tier_without_its_tools_is_skipped_and_the_report_says_so(tmp_path):
    (tmp_path / "Pkg").mkdir()
    m = pp.Measurer(PROFILE, runner=runner_returning([(0, XCTEST_OK)]), have=lambda cap, env: cap == "swift")
    m(tmp_path)
    notes = " ".join(m.report["notes"])
    assert "App build" in notes and "not verified" in notes and "xcodegen" in notes
    assert [t["id"] for t in m.report["tiers"] if t["ran"]] == ["core"]


def test_a_required_tier_without_its_tools_is_an_environment_problem_not_a_result(tmp_path):
    m = pp.Measurer(PROFILE, runner=runner_returning([]), have=lambda cap, env: False)
    try:
        m(tmp_path)
    except pp.EnvMissing as e:
        assert "swift" in str(e) and e.tier == "core"
    else:
        raise AssertionError("must not report zero tests for a missing toolchain")


def test_a_tier_that_crashed_without_a_summary_is_an_error_not_zero(tmp_path):
    (tmp_path / "Pkg").mkdir()
    m = pp.Measurer(PROFILE, runner=runner_returning([(1, NO_XCTEST)]), have=lambda cap, env: cap == "swift")
    try:
        m(tmp_path)
    except pp.MeasureError as e:
        assert "Core tests" in str(e) and "XCTest" in str(e)
    else:
        raise AssertionError("a crash must not read as zero tests")


def test_a_disabled_tier_never_runs_and_is_listed(tmp_path):
    prof = {**PROFILE, "verify": [{**PROFILE["verify"][0]}, {**PROFILE["verify"][1], "enabled": False}]}
    (tmp_path / "Pkg").mkdir()
    m = pp.Measurer(prof, runner=runner_returning([(0, XCTEST_OK)]), have=lambda cap, env: True)
    m(tmp_path)
    assert "disabled" in " ".join(m.report["notes"])


def test_evidence_summarises_the_tiers_for_the_pr_and_is_honest_about_what_was_not_run(tmp_path):
    (tmp_path / "Pkg").mkdir()
    m = pp.Measurer({**PROFILE, "evidence": {"dev": {"na": "no simulator capture on pipeline machines"}}},
                    runner=runner_returning([(0, XCTEST_OK)]), have=lambda cap, env: cap == "swift")
    m(tmp_path)
    tr, dev = m.evidence()
    assert tr["suite"] == "Core tests" and tr["passed"] == 60 and tr["failed"] == 0 and tr["total"] == 61
    assert dev == {"na": True, "reason": "no simulator capture on pipeline machines"}
    assert "not verified" in m.pr_note()


# ── what the headless model may run ─────────────────────────────────────────

def test_the_executor_may_build_and_test_but_not_write_into_the_real_clone(tmp_path):
    profile = {"executor": {"allowed_tools": ["Bash(swift build*)", "Bash(swift test*)"], "notes": "Use SwiftPM."}}
    allowed, denied = pp.executor_tools(profile, clone=Path("/Users/me/Developer/proj"))
    assert "Bash(swift test*)" in allowed and "Edit" in allowed and "Write" in allowed
    assert "Write(/Users/me/Developer/proj/**)" in denied and "Edit(/Users/me/Developer/proj/**)" in denied


# ── selftest: the whole path except the model and GitHub ────────────────────

def test_selftest_measures_a_real_worktree_shows_the_pr_body_and_always_cleans_up(tmp_path, monkeypatch):
    import sandbox_orchestration as so
    removed = []
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / "Pkg").mkdir()
    monkeypatch.setattr(so, "_create_worktree", lambda clone, ref, base="main": wt)
    monkeypatch.setattr(pp, "_cleanup_worktree", lambda clone, worktree, branch: removed.append((str(worktree), branch)))
    profile = {**PROFILE, "base_branch": "main", "dispatch": "off", "machines": [], "clone_hints": [str(tmp_path)]}
    (tmp_path / ".git").mkdir()
    report = pp.selftest(profile, runner=runner_returning([(0, XCTEST_OK)]), have=lambda cap, env: cap == "swift", catalog={"projects": []})
    assert report["ok"] is True
    assert "Core tests" in report["pr_body"] and "## Test Results" in report["pr_body"] and "not verified" in report["pr_body"]
    assert removed and removed[0][0] == str(wt)


def test_selftest_cleans_up_even_when_the_measurement_blows_up(tmp_path, monkeypatch):
    import sandbox_orchestration as so
    removed = []
    wt = tmp_path / "wt"
    wt.mkdir()
    monkeypatch.setattr(so, "_create_worktree", lambda clone, ref, base="main": wt)
    monkeypatch.setattr(pp, "_cleanup_worktree", lambda clone, worktree, branch: removed.append(1))
    (tmp_path / ".git").mkdir()
    profile = {**PROFILE, "clone_hints": [str(tmp_path)]}
    report = pp.selftest(profile, runner=runner_returning([(1, NO_XCTEST)]), have=lambda cap, env: True, catalog={"projects": []})
    assert report["ok"] is False and "XCTest" in report["error"]
    assert removed == [1]


def test_selftest_says_so_when_this_machine_cannot_run_the_required_checks(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    profile = {**PROFILE, "clone_hints": [str(tmp_path)]}
    report = pp.selftest(profile, runner=runner_returning([]), have=lambda cap, env: False, catalog={"projects": []})
    assert report["ok"] is False and "swift" in report["error"]


# ── the merge gate's view of a profile ──────────────────────────────────────

def test_a_profile_does_not_allow_merging_from_the_dashboard_unless_it_says_so():
    p = pp._validate({"repo": "G-Eskayo/x", "verify": [{"id": "t", "command": ["true"]}]}, "x")
    assert p["merge_from_dashboard"] is False
    q = pp._validate({"repo": "G-Eskayo/x", "merge_from_dashboard": True, "verify": [{"id": "t", "command": ["true"]}]}, "x")
    assert q["merge_from_dashboard"] is True


def test_gate_info_gives_the_gate_the_clone_the_base_branch_and_what_this_machine_lacks(tmp_path):
    (tmp_path / ".git").mkdir()
    profile = {**PROFILE, "base_branch": "trunk", "merge_from_dashboard": True, "clone_hints": [str(tmp_path)]}
    info = pp.gate_info(profile, catalog={"projects": []}, have=lambda cap, env: cap != "swift")
    assert info == {"repo": "G-Eskayo/proj", "clone": str(tmp_path), "base_branch": "trunk", "merge_from_dashboard": True, "missing_here": ["swift"], "generated": []}


def test_verify_passes_when_every_required_check_is_clean(tmp_path):
    (tmp_path / "Pkg").mkdir()
    r = pp.verify_dir(PROFILE, tmp_path, runner=runner_returning([(0, XCTEST_OK)]), have=lambda cap, env: cap == "swift")
    assert r["ok"] is True and r["kind"] == "passed"
    assert "60 passed" in r["summary"]


def test_verify_fails_with_the_failing_output_when_a_test_fails(tmp_path):
    (tmp_path / "Pkg").mkdir()
    out = "Test Case '-[CoreTests.AlignTests testBad]' failed (0.1 seconds).\n" + XCTEST_FAIL
    r = pp.verify_dir(PROFILE, tmp_path, runner=runner_returning([(1, out)]), have=lambda cap, env: cap == "swift")
    assert r["ok"] is False and r["kind"] == "failed"
    assert "2 failed" in r["summary"] and "testBad" in r["output_tail"]


def test_verify_reports_a_missing_toolchain_as_env_missing_not_as_a_failure(tmp_path):
    r = pp.verify_dir(PROFILE, tmp_path, runner=runner_returning([]), have=lambda cap, env: False)
    assert r["ok"] is False and r["kind"] == "env_missing" and "swift" in r["summary"]


def test_verify_reports_a_crash_without_a_summary_as_an_error(tmp_path):
    (tmp_path / "Pkg").mkdir()
    r = pp.verify_dir(PROFILE, tmp_path, runner=runner_returning([(1, NO_XCTEST)]), have=lambda cap, env: cap == "swift")
    assert r["ok"] is False and r["kind"] == "error" and "XCTest" in r["output_tail"]


def test_verify_feedback_leads_with_the_failing_lines_even_when_a_long_run_buries_them(tmp_path):
    (tmp_path / "Pkg").mkdir()
    noise = "".join(f"Test Case '-[S.T test{i}]' passed (0.0 seconds).\n" for i in range(400))
    out = "Test Case '-[S.T testBroken]' failed (0.1 seconds).\n" + noise + XCTEST_FAIL
    r = pp.verify_dir(PROFILE, tmp_path, runner=runner_returning([(1, out)]), have=lambda cap, env: cap == "swift")
    assert r["kind"] == "failed"
    assert r["output_tail"].startswith("Test Case '-[S.T testBroken]' failed")  # not lost off the end
    assert len(r["output_tail"]) <= 4000


# ── a dedicated pipeline clone (not anyone's working copy, not in iCloud) ───

def test_pipeline_mode_uses_a_clone_of_its_own_and_ignores_the_catalogs_working_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "PIPELINE_CLONES", tmp_path / "clones")
    human = tmp_path / "Documents" / "proj"
    (human / ".git").mkdir(parents=True)
    profile = {"repo": "G-Eskayo/proj", "clone_mode": "pipeline"}
    cat = {"projects": [{"repo": "G-Eskayo/proj", "localPaths": [str(human)]}]}
    assert pp.resolve_clone(profile, cat) is None  # not created yet, and NOT the human's copy
    (tmp_path / "clones" / "proj" / ".git").mkdir(parents=True)
    assert pp.resolve_clone(profile, cat) == tmp_path / "clones" / "proj"


def test_ensure_creates_the_pipeline_clone_once_with_the_shared_token(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "PIPELINE_CLONES", tmp_path / "clones")
    calls = []

    def fake_clone(cmd, **kw):
        calls.append((cmd, kw.get("env", {}).get("GH_TOKEN")))
        (tmp_path / "clones" / "proj" / ".git").mkdir(parents=True)

        class R:
            returncode = 0
            stdout = stderr = ""
        return R()

    monkeypatch.setattr(pp.subprocess, "run", fake_clone)
    monkeypatch.setattr(pp, "_token_env", lambda: {"GH_TOKEN": "tok"})
    profile = {"repo": "G-Eskayo/proj", "clone_mode": "pipeline"}
    path = pp.resolve_clone(profile, {"projects": []}, ensure=True)
    assert path == tmp_path / "clones" / "proj"
    assert calls[0][0][:3] == ["gh", "repo", "clone"] and calls[0][0][3] == "G-Eskayo/proj" and calls[0][1] == "tok"
    pp.resolve_clone(profile, {"projects": []}, ensure=True)
    assert len(calls) == 1  # already there: not cloned again


def test_a_failed_clone_is_reported_as_no_clone_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "PIPELINE_CLONES", tmp_path / "clones")

    def boom(cmd, **kw):
        class R:
            returncode = 1
            stdout = ""
            stderr = "authentication failed"
        return R()

    monkeypatch.setattr(pp.subprocess, "run", boom)
    assert pp.resolve_clone({"repo": "G-Eskayo/proj", "clone_mode": "pipeline"}, {"projects": []}, ensure=True) is None


def test_the_pipeline_clone_never_hides_files_the_project_ignores_by_directory(tmp_path):
    # a dependency folder reached through a symlink escapes a "node_modules/" ignore rule, so make sure
    # the clone's own exclude file ignores the bare name too
    clone = tmp_path / "c"
    (clone / ".git" / "info").mkdir(parents=True)
    pp.ignore_in_clone(clone, ["node_modules"])
    pp.ignore_in_clone(clone, ["node_modules"])
    text = (clone / ".git" / "info" / "exclude").read_text()
    assert text.count("node_modules") == 1


# ── setup steps (dependencies in a fresh worktree) ──────────────────────────

SETUP = {"id": "deps", "label": "Install dependencies", "command": ["npm", "ci"], "creates": "node_modules", "requires": ["node"]}


def test_setup_runs_when_its_result_is_missing_and_is_skipped_when_present(tmp_path):
    prof = {**PROFILE, "setup": [SETUP]}
    (tmp_path / "Pkg").mkdir()
    have = lambda c, e: c != "xcodegen"  # the optional app-build tier stays out of this
    m = pp.Measurer(prof, runner=runner_returning([(0, "installed"), (0, XCTEST_OK)]), have=have)
    m(tmp_path)
    assert m.runner.calls[0]["cmd"] == ["npm", "ci"]
    (tmp_path / "node_modules").mkdir()
    m2 = pp.Measurer(prof, runner=runner_returning([(0, XCTEST_OK)]), have=have)
    m2(tmp_path)
    assert [c["cmd"] for c in m2.runner.calls] == [["swift", "test"]]  # node_modules already there: no reinstall


def test_a_failing_setup_is_an_error_naming_the_step_not_a_zero_test_result(tmp_path):
    prof = {**PROFILE, "setup": [SETUP]}
    m = pp.Measurer(prof, runner=runner_returning([(1, "npm ERR! network")]), have=lambda c, e: True)
    try:
        m(tmp_path)
    except pp.MeasureError as e:
        assert "Install dependencies" in str(e) and "npm ERR" in str(e)
    else:
        raise AssertionError("a broken install must not read as zero tests")


def test_setup_needing_a_tool_the_machine_lacks_is_an_environment_problem(tmp_path):
    prof = {**PROFILE, "setup": [SETUP]}
    m = pp.Measurer(prof, runner=runner_returning([]), have=lambda c, e: c != "node")
    try:
        m(tmp_path)
    except pp.EnvMissing as e:
        assert "node" in str(e)
    else:
        raise AssertionError("must be reported as the machine lacking node")


VITEST_OK = """ RUN  v2.1.9 /x

 ✓ test/bills.test.js (20 tests) 208ms

 Test Files  1 passed (1)
      Tests  20 passed (20)
"""
VITEST_MIXED = " Test Files  1 failed | 2 passed (3)\n      Tests  2 failed | 17 passed | 1 skipped (20)\n"


def test_vitest_summary_is_read_from_its_real_output():
    assert pp.parse_vitest(VITEST_OK) == {"total": 20, "failed": 0, "skipped": 0, "passed": 20}
    r = pp.parse_vitest(VITEST_MIXED)
    assert (r["total"], r["failed"], r["passed"], r["skipped"]) == (20, 2, 17, 1)
    assert pp.parse_vitest("Error: Electron failed to install correctly") is None
    assert pp.parse_output("vitest", VITEST_OK, 0)["passed"] == 20


def test_a_profile_can_forbid_the_model_from_reading_or_writing_sensitive_paths(tmp_path):
    profile = {"executor": {"allowed_tools": [], "denied_tools": ["Read(~/Library/Application Support/FinanceOS/**)", "Bash(cat ~/Library/Application Support/FinanceOS*)"]}}
    allowed, denied = pp.executor_tools(profile, clone=Path("/c"))
    assert "Read(~/Library/Application Support/FinanceOS/**)" in denied
    assert "Write(/c/**)" in denied  # the real-clone wall is still there
    assert "FinanceOS" not in allowed


def test_selftest_can_be_pointed_at_a_branch_other_than_the_base(tmp_path, monkeypatch):
    import sandbox_orchestration as so
    seen = {}
    wt = tmp_path / "wt"
    (wt / "Pkg").mkdir(parents=True)
    monkeypatch.setattr(so, "_create_worktree", lambda clone, ref, base="main": seen.setdefault("base", base) and wt)
    monkeypatch.setattr(pp, "_cleanup_worktree", lambda *a: None)
    (tmp_path / ".git").mkdir()
    profile = {**PROFILE, "clone_hints": [str(tmp_path)]}
    pp.selftest(profile, runner=runner_returning([(0, XCTEST_OK)]), have=lambda c, e: c == "swift", catalog={"projects": []}, ref="feature/x")
    assert seen["base"] == "feature/x"


# ── generated-file rules (see generated_paths.py) ───────────────────────────

def _minimal(**extra):
    return {"repo": "o/r", "verify": [{"id": "t", "label": "t", "command": ["true"], "parser": "exit-code", "required": True}], **extra}


def test_generated_defaults_to_none():
    assert pp._validate(_minimal(), "p")["generated"] == []


def test_generated_rules_are_validated():
    import pytest
    ok = pp._validate(_minimal(generated=[{"path": "graphify-out"}, {"path": "package-lock.json", "unless": "package.json", "regenerate": ["npm", "i"]}]), "p")
    assert len(ok["generated"]) == 2
    with pytest.raises(ValueError, match="generated"):
        pp._validate(_minimal(generated=[{"unless": "x"}]), "p")
    with pytest.raises(ValueError, match="generated"):
        pp._validate(_minimal(generated=[{"path": "a", "regenerate": "npm i"}]), "p")  # a command is a list, not a shell string
