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


def pytest_terminal_summary(terminalreporter):
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
