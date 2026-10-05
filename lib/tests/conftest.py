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
