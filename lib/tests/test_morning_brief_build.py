"""Integration tests for morning_brief.py's build() function with brief_fallback. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_morning_brief_build.py -v
"""
from datetime import datetime, timezone
from pathlib import Path

import morning_brief as mb


NOW = datetime(2026, 10, 9, 9, 45, tzinfo=timezone.utc)


def _sources(**over):
    base = {
        "open_prs": lambda: [{"number": 308, "title": "MARVIN launcher", "ticket": "#302"}],
        "red_checks": lambda: [{"label": "Missed purpose", "detail": "#277 Allow read-only tools: missed"}],
        "human_tickets": lambda: [{"number": 14, "title": "Enroll in the Apple developer program"}],
        "launches": lambda: [{"kind": "ticket-planner", "cost_usd": 0.8}, {"kind": "ticket-executor", "cost_usd": 0.2},
                             {"kind": "background-analyst", "cost_usd": 0.1}],
        "merged": lambda: [{"number": 307, "title": "North stars single source"}],
        "deadlines": lambda: [{"project": "clarity-captions", "date": "2026-10-25", "hard": True}],
        "top_tickets": lambda: [{"repo": "clarity-captions", "number": 31, "title": "Live captions view", "priority": "p0"}],
        "digest_idea": lambda: "Wire the outcome check into the brief.",
        "research_idea": lambda: "A paper on cheaper planning with smaller models.",
        "late_night": lambda: "01:40",
    }
    return {**base, **over}


def test_build_gates_on_should_run_decision(tmp_path, monkeypatch):
    """build() gates on brief_fallback.should_run: standby before deadline skips."""
    import machine_profile
    import scanner_role
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)

    # Standby time: primary hasn't reached deadline yet
    standby_time = datetime(2026, 10, 9, 9, 0).astimezone()  # 9:00, deadline is 9:15

    # Pretend we're standby (not primary)
    monkeypatch.setattr(scanner_role, "is_primary", lambda x: False)
    monkeypatch.setattr(machine_profile, "registry_id", lambda: "macbook-pro")

    # Call build — it should return None due to should_run returning False
    result = mb.build(standby_time, _sources())

    # Verify no brief was written
    assert result is None


def test_build_produced_check_prevents_rewrite(tmp_path, monkeypatch):
    """build() rechecks produced() before write to prevent race condition overwrites."""
    import machine_profile
    import scanner_role
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)

    # Setup: primary after deadline should build
    primary_after_deadline = datetime(2026, 10, 9, 10, 0).astimezone()  # 10:00, after 9:15

    # Pretend we're the primary
    monkeypatch.setattr(scanner_role, "is_primary", lambda x: True)
    monkeypatch.setattr(machine_profile, "registry_id", lambda: "mac-mini")

    # Pre-create the brief file (race condition: another machine just built it)
    brief_path = tmp_path / f"{mb._day(primary_after_deadline)}.md"
    original_content = "# Morning brief from primary\n\nOriginal content"
    brief_path.write_text(original_content)

    # Call build
    result = mb.build(primary_after_deadline, _sources())

    # Verify the original content was preserved (not overwritten)
    content = brief_path.read_text()
    assert content == original_content
    assert "Morning brief from primary" in content


def test_build_records_builder_machine(tmp_path, monkeypatch):
    """build() writes the .built-by sidecar file with the builder machine ID."""
    import machine_profile
    import scanner_role
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)
    monkeypatch.setattr(machine_profile, "registry_id", lambda: "mac-mini")

    # Pretend we're the primary so should_run returns True
    monkeypatch.setattr(scanner_role, "is_primary", lambda x: True)

    # Build after deadline so should_run doesn't time-gate it
    after_deadline = datetime(2026, 10, 9, 10, 0).astimezone()

    result = mb.build(after_deadline, _sources())

    # Verify the brief was written
    assert result is not None
    assert result.exists()

    # Verify the builder file was written
    bp = mb.builder_path(after_deadline)
    assert bp.exists()
    assert bp.read_text().strip() == "mac-mini"


def test_builder_of_reads_builder_file(tmp_path, monkeypatch):
    """builder_of() reads which machine built the brief from the .built-by file."""
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)

    # Create a builder file
    bp = mb.builder_path(NOW)
    bp.write_text("macbook-pro")

    builder = mb.builder_of(NOW)
    assert builder == "macbook-pro"


def test_builder_of_returns_none_if_not_recorded(tmp_path, monkeypatch):
    """builder_of() returns None if the .built-by file doesn't exist."""
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)

    builder = mb.builder_of(NOW)
    assert builder is None
