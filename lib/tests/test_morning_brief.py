"""The morning brief (marvin#306): one short start-of-day brief, built from what MARVIN already knows, no model run."""
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import morning_brief as mb
import brief_fallback

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


def test_the_brief_leads_with_what_needs_a_decision():
    text = mb.render(mb.gather(NOW, _sources()), NOW)
    assert text.index("Needs you") < text.index("Overnight") < text.index("Today")
    assert "PR #308 MARVIN launcher" in text and "#277 Allow read-only tools" in text
    assert "#14 Enroll in the Apple developer program" in text


def test_numbers_always_come_with_titles():
    text = mb.render(mb.gather(NOW, _sources()), NOW)
    assert "#31 Live captions view" in text and "#307 North stars single source" in text


def test_overnight_counts_runs_by_kind_and_cost():
    text = mb.render(mb.gather(NOW, _sources()), NOW)
    assert "3 model runs" in text and "$1.10" in text


def test_deadlines_count_down_and_hard_ones_say_so():
    text = mb.render(mb.gather(NOW, _sources()), NOW)
    assert "clarity-captions: 16 days (2026-10-25, hard deadline)" in text


def test_a_late_night_gets_a_factual_nudge_never_a_guilt_trip():
    text = mb.render(mb.gather(NOW, _sources()), NOW)
    assert "01:40" in text and "should" not in text.lower()
    quiet = mb.render(mb.gather(NOW, _sources(late_night=lambda: None)), NOW)
    assert "Balance" not in quiet


def test_a_failing_source_is_named_not_hidden():
    text = mb.render(mb.gather(NOW, _sources(open_prs=lambda: (_ for _ in ()).throw(OSError("rate limited")))), NOW)
    assert "couldn't read open PRs" in text and "Overnight" in text


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
    text = mb.render({"auto_merge": "Auto-merge shadow report ready: would have merged 4 of 6 PRs, 0 you'd have denied. Say 'switch on auto-merge' to turn it on."}, now)
    needs = text.split("## Needs you")[1].split("##")[0]
    assert needs.strip().startswith("- Auto-merge shadow report ready")
    assert "Auto-merge" not in mb.render({}, now)


def test_a_pr_whose_decisions_are_in_waits_on_marvin_not_on_gil():
    """marvin#607: #577's decisions were in, yet the wrap-up still listed it as waiting on Gil."""
    prs = lambda: [{"number": 577, "title": "Vitals design v3", "waiting_on_marvin": True, "question": True},
                   {"number": 590, "title": "Real PR titles", "waiting_on_marvin": False}]
    text = mb.render(mb.gather(NOW, _sources(open_prs=prs)), NOW)
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
    monkeypatch.setattr(od, "fetch", lambda repos, run=None: None)
    brief = mb.gather(NOW, {"open_prs": mb._open_prs})
    assert brief["open_prs"] is None and "open PRs" in brief["missing"][0]


def test_build_idempotency_with_fallback_gate(tmp_path, monkeypatch, utc_tz):
    """build() is idempotent: calling it twice on the same day produces the same result (test 16)."""
    briefs_dir = tmp_path / "briefs"
    briefs_dir.mkdir()
    monkeypatch.setattr(mb, "BRIEFS", briefs_dir)

    # Mock brief_fallback.should_run and brief_fallback.produced
    def mock_should_run(*args, **kwargs):
        return brief_fallback.Decision(True, "primary")
    monkeypatch.setattr(brief_fallback, "should_run", mock_should_run)

    # Mock produced() to check locally only (no remote check)
    local_produced_call_count = [0]
    original_produced = brief_fallback.produced
    def mock_produced(local_path, remote_path=None, host=None, run=None):
        local_produced_call_count[0] += 1
        if local_path.exists():
            try:
                content = local_path.read_text()
                if content and content.strip():
                    return True
            except Exception:
                pass
        return False
    monkeypatch.setattr(brief_fallback, "produced", mock_produced)

    # Mock sources
    def mock_sources(**over):
        return {
            "open_prs": lambda: [],
            "red_checks": lambda: [],
            "human_tickets": lambda: [],
            "launches": lambda: [],
            "merged": lambda: [],
            "deadlines": lambda: [],
            "top_tickets": lambda: [],
            **over
        }

    # First build
    result1 = mb.build(NOW, builder_reason="test-builder-1", sources=mock_sources())
    assert result1 is not None
    content1 = result1.read_text()

    # Second build should return early and not overwrite
    result2 = mb.build(NOW, builder_reason="test-builder-2", sources=mock_sources())
    assert result2 is not None
    content2 = result2.read_text()

    # Content should be identical (no overwrite happened)
    assert content1 == content2
    # Verify produced() was called at least once
    assert local_produced_call_count[0] > 0


def test_builder_of_reads_sidecar(tmp_path, monkeypatch):
    """builder_of() reads the .builder sidecar file (round-trip test)."""
    briefs_dir = tmp_path / "briefs"
    briefs_dir.mkdir()
    monkeypatch.setattr(mb, "BRIEFS", briefs_dir)

    day = "2026-10-24"
    builder_label = "macbook-pro-1"

    # Write a sidecar
    sidecar = briefs_dir / f"{day}.builder"
    sidecar.write_text(builder_label)

    # Read it back
    result = mb.builder_of(day)
    assert result == builder_label


def test_builder_of_returns_none_for_missing(tmp_path, monkeypatch):
    """builder_of() returns None when sidecar doesn't exist."""
    briefs_dir = tmp_path / "briefs"
    briefs_dir.mkdir()
    monkeypatch.setattr(mb, "BRIEFS", briefs_dir)

    result = mb.builder_of("2026-10-24")
    assert result is None


def test_builder_of_default_day_uses_injected_now_not_wall_clock(tmp_path, monkeypatch, utc_tz):
    """builder_of(now=...) with no day arg uses the injected datetime, not wall clock."""
    briefs_dir = tmp_path / "briefs"
    briefs_dir.mkdir()
    monkeypatch.setattr(mb, "BRIEFS", briefs_dir)

    # Use a fixed time: 2026-10-24 09:45 UTC
    injected_now = datetime(2026, 10, 24, 9, 45, tzinfo=timezone.utc)

    # Write a sidecar for that specific day
    day_str = mb._day(injected_now)
    assert day_str == "2026-10-24"
    (briefs_dir / f"{day_str}.builder").write_text("test-builder")

    # Call with the injected time, no explicit day
    result = mb.builder_of(now=injected_now)
    assert result == "test-builder"


def test_builder_of_default_matches_build_local_date(tmp_path, monkeypatch, utc_tz):
    """builder_of() with no day uses the same day as build() would use for the same now."""
    briefs_dir = tmp_path / "briefs"
    briefs_dir.mkdir()
    monkeypatch.setattr(mb, "BRIEFS", briefs_dir)

    # Use a fixed time
    fixed_now = datetime(2026, 10, 24, 15, 30, tzinfo=timezone.utc)

    # The day should match what _day() returns
    expected_day = mb._day(fixed_now)
    (briefs_dir / f"{expected_day}.builder").write_text("matching-builder")

    # builder_of with the same injected time should find it
    result = mb.builder_of(now=fixed_now)
    assert result == "matching-builder"
