"""The morning brief (marvin#306): one short start-of-day brief, built from what MARVIN already knows, no model run."""
import json
from datetime import datetime, timezone

import pytest

import brief_items as bi
import morning_brief as mb

NOW = datetime(2026, 10, 9, 9, 45, tzinfo=timezone.utc)


@pytest.fixture
def mock_mb_helpers(monkeypatch):
    """Mock all helper functions used by item builders."""
    monkeypatch.setattr(mb, "_open_prs", lambda: [
        {"number": 308, "title": "MARVIN launcher", "repo": "marvin", "waiting_on_marvin": False, "question": False},
    ])
    monkeypatch.setattr(mb, "_red_checks", lambda: [
        {"label": "Missed purpose", "detail": "#277 Allow read-only tools: missed"},
    ])
    monkeypatch.setattr(mb, "_human_tickets", lambda: [
        {"number": 14, "title": "Enroll in the Apple developer program", "repo": "marvin"},
    ])
    monkeypatch.setattr(mb, "_deadlines", lambda now: [
        {"project": "clarity-captions", "date": "2026-10-25", "hard": True},
    ])
    monkeypatch.setattr(mb, "_top_tickets", lambda: [
        {"repo": "clarity-captions", "number": 31, "title": "Live captions view", "priority": "p0"},
    ])
    monkeypatch.setattr(mb, "_auto_merge_report", lambda: None)
    monkeypatch.setattr(mb, "_regressions", lambda now: [])
    monkeypatch.setattr(mb, "_digest_idea", lambda now: "Wire the outcome check into the brief.")
    monkeypatch.setattr(mb, "_research_idea", lambda now: "A paper on cheaper planning with smaller models.")


def _sources(**over):
    """Mock sources that return items. Use real builders by default."""
    base = {
        "your_projects": lambda: mb._your_projects_items(NOW),
        "your_day": lambda: mb._your_day_items(NOW),
        "research": lambda: mb._research_items(NOW),
        "world_security": lambda: mb._world_security_items(NOW),
    }
    return {**base, **over}


def test_the_brief_leads_with_what_needs_a_decision(mock_mb_helpers):
    # With tier-first sorting, the red check (tier 0) + PR + human task (tier 1) + top ticket (tier 2)
    # + deadline (tier 2) all fit within the 5-item cap without blanking anything.
    text = mb.render(mb.gather(NOW, _sources()), NOW)
    assert text.index("Needs you") < text.index("Today")
    # Tier 0 (red check) is highest priority
    assert "Missed purpose" in text
    # Tier 1 items (PR, human task)
    assert "PR #308 MARVIN launcher" in text
    assert "#14 Enroll in the Apple developer program" in text
    # Tier 2 deadline still fits
    assert "clarity-captions: 16 days" in text


def test_numbers_always_come_with_titles(mock_mb_helpers):
    text = mb.render(mb.gather(NOW, _sources()), NOW)
    assert "#31 Live captions view" in text


def test_deadlines_count_down_and_hard_ones_say_so(mock_mb_helpers):
    # With tier-first sorting, deadlines (tier 2) still fit within the 5-item cap
    # alongside tier 0 (red checks) and tier 1 items (PR, human task).
    text = mb.render(mb.gather(NOW, _sources()), NOW)
    assert "clarity-captions: 16 days (2026-10-25, hard deadline)" in text


def test_a_failing_source_is_named_not_hidden(mock_mb_helpers):
    text = mb.render(mb.gather(NOW, _sources(your_projects=lambda: (_ for _ in ()).throw(OSError("rate limited")))), NOW)
    assert "couldn't read your projects items" in text


def test_a_failing_reader_within_a_builder_is_named_not_hidden(mock_mb_helpers, monkeypatch):
    """Reader-level failures (like _open_prs rate limit) should be named in Gaps, not silent."""
    # Make _open_prs fail but _red_checks succeed
    monkeypatch.setattr(mb, "_open_prs", lambda: (_ for _ in ()).throw(OSError("rate limited")))
    monkeypatch.setattr(mb, "_red_checks", lambda: [{"label": "Test", "detail": "Check"}])
    # Silence other builders to avoid noise
    monkeypatch.setattr(mb, "_regressions", lambda now: [])
    monkeypatch.setattr(mb, "_human_tickets", lambda: [])
    monkeypatch.setattr(mb, "_top_tickets", lambda: [])
    monkeypatch.setattr(mb, "_auto_merge_report", lambda: None)
    monkeypatch.setattr(mb, "_digest_idea", lambda now: None)

    text = mb.render(mb.gather(NOW, _sources()), NOW)
    # The red check should still appear
    assert "Test: Check" in text
    # The failure should be named in Gaps
    assert "Gaps" in text
    assert "couldn't read open PRs" in text


def test_writing_and_reading_mark_consumption(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)
    path = mb.write(NOW, _sources())
    assert path.name == "2026-10-09.md" and path.read_text().startswith("# Morning brief")
    assert mb.read_dates() == []
    shown = mb.show_today(NOW)
    assert "Needs you" in shown
    assert [d.date().isoformat() for d in mb.read_dates()] == ["2026-10-09"]
    assert [d.date().isoformat() for d in mb.brief_dates()] == ["2026-10-09"]


def test_the_session_report_shows_todays_brief_first_and_that_marks_it_read(tmp_path, monkeypatch, capsys):
    import session_start_report as ssr
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)
    today = datetime.now(timezone.utc)
    (tmp_path / f"{today.astimezone():%Y-%m-%d}.md").write_text("# Morning brief, today\n\n## Needs you\n\n- Review PR #1 X\n")
    for name in dir(ssr):
        if name.startswith("check_") and name not in ("check_identity", "check_morning_brief"):
            monkeypatch.setattr(ssr, name, lambda *a, **k: None)
    monkeypatch.setattr(ssr, "check_identity", lambda: "MARVIN active — test")
    monkeypatch.setattr(ssr, "load_lexicon", lambda: None)
    monkeypatch.setattr(ssr, "check_handoff", lambda: None)
    monkeypatch.setattr(ssr, "process_and_check_quarantine", lambda: None)
    ssr.main()
    out = capsys.readouterr().out
    assert out.index("MARVIN active") < out.index("## Morning brief") < out.index("Session-start checklist")
    assert mb.read_dates()


def test_the_auto_merge_shadow_report_heads_needs_you_when_ready():
    from datetime import datetime, timezone
    now = datetime(2026, 10, 12, 8, tzinfo=timezone.utc)
    items = [bi.make_item("your_projects", 1, "Auto-merge shadow report ready: would have merged 4 of 6 PRs, 0 you'd have denied. Say 'switch on auto-merge' to turn it on.")]
    text = mb.render({"items": items}, now)
    needs = text.split("## Needs you")[1].split("##")[0]
    assert needs.strip().startswith("- Auto-merge shadow report ready")
    assert "Auto-merge" not in mb.render({"items": []}, now)


def test_a_pr_whose_decisions_are_in_waits_on_marvin_not_on_gil(mock_mb_helpers, monkeypatch):
    """marvin#607: #577's decisions were in, yet the wrap-up still listed it as waiting on Gil."""
    prs_data = [{"number": 577, "title": "Vitals design v3", "repo": "marvin", "waiting_on_marvin": True, "question": True},
                {"number": 590, "title": "Real PR titles", "repo": "marvin", "waiting_on_marvin": False}]

    # Override _open_prs to return PRs with waiting_on_marvin status
    monkeypatch.setattr(mb, "_open_prs", lambda: prs_data)

    text = mb.render(mb.gather(NOW, _sources()), NOW)
    needs = text.split("## Needs you", 1)[1].split("##", 1)[0]
    assert "PR #590 Real PR titles" in needs and "#577" not in needs
    marvin = text.split("## Waiting on MARVIN", 1)[1].split("##", 1)[0]
    assert "PR #577 Vitals design v3" in marvin and "asked a question" in marvin


def test_open_prs_marks_waiting_from_one_graphql_read(monkeypatch):
    import owner_decisions as od
    from datetime import timedelta
    at = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    dec = {"databaseId": 1, "url": "u", "createdAt": at, "author": {"login": "G-Eskayo"},
           "body": od.HEADING + '\n\n```marvin-decisions\n{"answers": {"n": {"text": "why?"}}}\n```'}
    data = {"prs": [{"repo": "G-Eskayo/marvin", "number": 577, "title": "V", "url": "", "last_commit_at": None,
                     "comments": [dec]},
                    {"repo": "G-Eskayo/marvin", "number": 590, "title": "T", "url": "", "last_commit_at": None,
                     "comments": []}], "followups": [], "complete": True}
    monkeypatch.setattr(od, "fetch", lambda repos, run=None: data)
    got = {p["number"]: p for p in mb._open_prs()}
    assert got[577]["waiting_on_marvin"] and got[577]["question"] and not got[590]["waiting_on_marvin"]


def test_write_is_idempotent_against_an_existing_file(tmp_path, monkeypatch):
    """write() called twice for the same day must not overwrite a pre-existing file."""
    import machine_profile
    now = datetime(2026, 10, 22, 9, 45, tzinfo=timezone.utc)
    briefs_dir = tmp_path / "briefs"
    monkeypatch.setattr("morning_brief.BRIEFS", briefs_dir)
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "mac-mini")

    # First write
    brief_path = mb.write(now, _sources())
    original_content = brief_path.read_text()

    # Second write with different sources — should not overwrite
    different_sources = _sources(your_projects=lambda: [])
    result_path = mb.write(now, different_sources)

    # Content should be unchanged
    assert brief_path.read_text() == original_content
    assert result_path == brief_path


def test_write_records_who_built_it(tmp_path, monkeypatch):
    """After write(), a .built-by sidecar exists with machine label and reason."""
    import machine_profile
    now = datetime(2026, 10, 22, 9, 45, tzinfo=timezone.utc)
    briefs_dir = tmp_path / "briefs"
    monkeypatch.setattr("morning_brief.BRIEFS", briefs_dir)
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "mac-mini-1")

    # Write with a reason
    brief_path = mb.write(now, _sources(), builder_reason="fallback: covering for the laptop")

    # Check sidecar
    sidecar_path = briefs_dir / f"2026-10-22.built-by"
    assert sidecar_path.exists()
    assert sidecar_path.read_text() == "mac-mini-1: fallback: covering for the laptop\n"


def test_builder_of_reads_the_sidecar(tmp_path, monkeypatch):
    """builder_of() reads the .built-by sidecar."""
    briefs_dir = tmp_path / "briefs"
    briefs_dir.mkdir()
    monkeypatch.setattr("morning_brief.BRIEFS", briefs_dir)

    # Create a sidecar
    sidecar_path = briefs_dir / "2026-10-22.built-by"
    sidecar_path.write_text("macbook-pro-1: primary\n")

    # Read it back
    result = mb.builder_of("2026-10-22")
    assert result == "macbook-pro-1: primary"

    # Non-existent day
    assert mb.builder_of("2026-10-20") is None


def test_build_checks_fallback_gate(tmp_path, monkeypatch):
    """build() checks the fallback gate before building."""
    import brief_fallback
    import machine_profile

    briefs_dir = tmp_path / "briefs"
    monkeypatch.setattr("morning_brief.BRIEFS", briefs_dir)
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "mac-mini-1")

    # Mock should_run to return False
    def mock_should_run(*args, **kwargs):
        return brief_fallback.Decision(False, "standby: primary already produced")
    monkeypatch.setattr("brief_fallback.should_run", mock_should_run)

    # Call build
    result = mb.build(NOW, _sources())

    # Brief should not have been created
    assert not (briefs_dir / "2026-10-09.md").exists()

def test_build_called_with_explicit_parameters(tmp_path, monkeypatch):
    """build() calls should_run() with usual_hour=9, usual_minute=15."""
    import brief_fallback
    import machine_profile

    briefs_dir = tmp_path / "briefs"
    monkeypatch.setattr("morning_brief.BRIEFS", briefs_dir)
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "mac-mini-1")

    # Track calls to should_run
    calls = []

    def mock_should_run(*args, **kwargs):
        calls.append(kwargs)
        return brief_fallback.Decision(False, "test: skipping")
    monkeypatch.setattr("brief_fallback.should_run", mock_should_run)

    # Call build
    mb.build(NOW, _sources())

    # Verify should_run was called with the right parameters
    assert len(calls) == 1
    assert calls[0].get("usual_hour") == 9
    assert calls[0].get("usual_minute") == 15
