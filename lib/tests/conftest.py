"""Suite-wide isolation for state files that production code writes under ~/.claude.

Any test that reaches run_ticket.run()/ticket_pipeline.main() would otherwise append
to the REAL pipeline-failures.jsonl and could trip the live circuit breaker (the same
pollution pattern hit repeatedly on 2026-10-01 with ticket stage files). Redirect by
default so a new call to a side-effecting module can never touch real state.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import readable_guard  # noqa: E402

# Tests that read the portfolio repo are left out where that repo can't be read from this process
# (and, always, inside the merge gate, MARVIN_MERGE_GATE=1: a PR must not be judged on another repo's data).
# On the mac-mini a launchd job opening files in iCloud-managed ~/Documents blocks forever, which hung
# the merge gate and the pipeline at collection, 2026-10-06). Checked once, in a child process.
_portfolio_blocked = None
_not_collected: list[str] = []


def pytest_ignore_collect(collection_path, config):
    global _portfolio_blocked
    if collection_path.suffix != ".py" or not collection_path.name.startswith("test_"):
        return None
    if _portfolio_blocked is None:
        _portfolio_blocked = readable_guard.exclude_portfolio_tests()
    if not _portfolio_blocked:
        return None
    try:
        source = collection_path.read_text(encoding="utf-8")
    except OSError:
        return None
    if readable_guard.reads_portfolio_repo(source):
        _not_collected.append(collection_path.name)
        return True
    return None


_GH_BLOCK_DIR: Path | None = None


def _gh_block_dir(tmp_path_factory) -> Path:
    """A `gh` that never reaches GitHub, first on every test's PATH. The merge gate's main-health check re-runs
    this suite each time main moves; tests that reached the real gh spent ~1,300 GitHub calls an hour on the
    mini (2026-10-08, found via the gh gate's log). It fails like an offline gh and records which test asked."""
    global _GH_BLOCK_DIR
    if _GH_BLOCK_DIR is None:
        d = tmp_path_factory.mktemp("no-github")
        fake = d / "gh"
        fake.write_text('#!/bin/sh\nprintf "%s|%s %s\\n" "$PYTEST_CURRENT_TEST" "$1" "$2" >> "$(dirname "$0")/calls.log"\n'
                        'echo "gh is blocked in tests (lib/tests/conftest.py): inject a fake" >&2\nexit 1\n')
        fake.chmod(0o755)
        _GH_BLOCK_DIR = d
    return _GH_BLOCK_DIR


@pytest.fixture(autouse=True)
def _no_real_github(tmp_path_factory, monkeypatch):
    import os
    d = _gh_block_dir(tmp_path_factory)
    monkeypatch.setenv("PATH", f"{d}:{os.environ.get('PATH', '')}")
    monkeypatch.delenv("GH_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def _no_real_disk_housekeeping(request, monkeypatch):
    # cleanup_sweep.run_daily_sweep runs the real disk ledger and trim (dry_run=False) on whatever machine runs
    # the tests; a test must never trim the real machine's caches. (disk_ledger/disk_trim's own tests test them.)
    if request.module.__name__.rsplit(".", 1)[-1] in ("test_disk_ledger", "test_disk_trim"):
        return
    import disk_ledger
    import disk_trim
    monkeypatch.setattr(disk_ledger, "run_daily_ledger", lambda *a, **k: None)
    monkeypatch.setattr(disk_trim, "trim_with_logging", lambda *a, **k: {})


def pytest_terminal_summary(terminalreporter):
    if _GH_BLOCK_DIR is not None and (_GH_BLOCK_DIR / "calls.log").exists():
        calls = [l.split("|")[0].split(" ")[0] for l in (_GH_BLOCK_DIR / "calls.log").read_text().splitlines()]
        tests = sorted(set(calls))
        terminalreporter.write_line(f"{len(calls)} blocked gh call(s) from {len(tests)} test(s); give them a fake gh: "
                                    + ", ".join(t.split("::")[-1] for t in tests[:8]), yellow=True)
    if _not_collected:
        terminalreporter.write_line(
            f"portfolio repo is on this machine but not readable from this process: {len(_not_collected)} test "
            f"file(s) not collected ({', '.join(sorted(_not_collected))})", yellow=True)


@pytest.fixture(autouse=True)
def _isolate_failure_breaker_log(tmp_path_factory, monkeypatch):
    import failure_breaker
    monkeypatch.setattr(failure_breaker, "LOG_PATH", tmp_path_factory.mktemp("breaker") / "pipeline-failures.jsonl")


@pytest.fixture(autouse=True)
def _isolate_board_registry(tmp_path_factory, monkeypatch):
    # _claim() registers a dashboard board; tests must never write the real, synced registry.
    import board_registry
    monkeypatch.setattr(board_registry, "REGISTRY_PATH", tmp_path_factory.mktemp("boards") / "registry.json")
    import ticket_pipeline
    monkeypatch.setattr(ticket_pipeline, "_discover_boards", lambda: [])  # no real gh calls from tests
    monkeypatch.setattr(ticket_pipeline, "_refresh_catalog", lambda: None)
    monkeypatch.setattr(ticket_pipeline, "_local_busy", lambda: False)  # the real machine may be mid-ticket
    monkeypatch.setattr(ticket_pipeline, "_run_ticket_agents", lambda step, summary: None)  # no real gh calls


@pytest.fixture(autouse=True)
def _isolate_job_events(tmp_path_factory, monkeypatch):
    # Instrumented jobs write a run log; tests must never write the real ~/.claude/logs/jobs.
    import job_events
    monkeypatch.setattr(job_events, "JOBS_DIR", tmp_path_factory.mktemp("jobs"))


@pytest.fixture(autouse=True)
def _isolate_launch_log(tmp_path_factory, monkeypatch):
    # Every launched run is recorded for Metrics and Health; tests must never write the real launch log.
    import marvin_launcher
    monkeypatch.setattr(marvin_launcher, "LAUNCH_LOG", tmp_path_factory.mktemp("launches") / "launches.jsonl")


@pytest.fixture(autouse=True)
def _isolate_fit_check(monkeypatch):
    # Raising a PR posts a north-star fit check (gh); tests opt in by passing fit_check explicitly.
    import mr_raiser
    monkeypatch.setattr(mr_raiser, "_default_fit_check", lambda *a: None)


@pytest.fixture(autouse=True)
def _isolate_project_profiles(tmp_path_factory, monkeypatch):
    # A real config/projects/*.json with dispatch "on" must never change what a test dispatches.
    import project_profile
    monkeypatch.setattr(project_profile, "PROFILES_DIR", tmp_path_factory.mktemp("profiles"))


@pytest.fixture(autouse=True)
def _isolate_ticket_stages_everywhere(tmp_path_factory, monkeypatch):
    # Tests use realistic ticket references (#9, #17...); recorded for real they pollute the account's actual
    # ticket-stages folder and show up as fake history on the dashboard (found 2026-10-05).
    import ticket_stages
    monkeypatch.setattr(ticket_stages, "STAGES_DIR", tmp_path_factory.mktemp("stages"))


@pytest.fixture(autouse=True)
def _isolate_ticket_evidence(monkeypatch):
    # The pre-dispatch "does work already exist" guard shells out to gh/git; tests opt in explicitly.
    import ticket_pipeline
    monkeypatch.setattr(ticket_pipeline, "_evidence_facts", lambda repo: None)
    monkeypatch.setattr(ticket_pipeline, "_requeue_all", lambda repos: [])
    monkeypatch.setattr(ticket_pipeline, "_background_checks", lambda: None)  # no background test runs from tests  # no real gh calls from the scan


def pytest_configure(config):
    config.addinivalue_line("markers", "real_preflight: run sandbox_orchestration's real worktree preflight (git), not the stub")
