"""A PR to marvin must not be judged on another repo's data: tests that read the portfolio repo stay out of the merge gate."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import readable_guard as rg  # noqa: E402


def test_the_merge_gate_excludes_portfolio_reading_tests_even_when_the_repo_is_readable():
    assert rg.exclude_portfolio_tests(environ={"MARVIN_MERGE_GATE": "1"}, blocked=False) is True


def test_outside_the_gate_they_run_unless_the_repo_cannot_be_read():
    assert rg.exclude_portfolio_tests(environ={}, blocked=False) is False
    assert rg.exclude_portfolio_tests(environ={}, blocked=True) is True


def test_a_machine_without_the_portfolio_repo_leaves_those_tests_out(monkeypatch, tmp_path):
    # mac-mini-2012 has no portfolio checkout; 20 tests that read it failed there instead of being left out (ADR 0069).
    import readable_guard as rg
    monkeypatch.setattr(rg, "PORTFOLIO_PROBE", tmp_path / "missing" / "templates.json")
    assert rg.exclude_portfolio_tests(environ={}) is True
