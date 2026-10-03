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
