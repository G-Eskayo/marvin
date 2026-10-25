"""The morning brief (marvin#306): one short start-of-day brief, built from what MARVIN already knows, no model run."""
import json
from datetime import datetime, timezone

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
    import machine_profile
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "mac-mini")
    path = mb.write(NOW, _sources())
    assert path.name == "2026-10-09.md" and path.read_text().startswith("# Morning brief")
    assert (tmp_path / "2026-10-09.built-by").read_text().strip() == "primary@mac-mini"
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


def test_builder_of_returns_builder_label_from_built_by_file(tmp_path, monkeypatch):
    """Test 18: builder_of() reads and returns the .built-by file content."""
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)
    (tmp_path / "2026-10-09.built-by").write_text("primary@mac-mini\n")
    assert mb.builder_of("2026-10-09") == "primary@mac-mini"
    assert mb.builder_of("2026-10-10") is None


def test_builder_of_different_day_still_none(tmp_path, monkeypatch):
    """Test 17b: builder_of() for a different day returns None if no .built-by file exists."""
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)
    (tmp_path / "2026-10-09.built-by").write_text("primary@mac-mini\n")
    # Different day, no file
    assert mb.builder_of("2026-10-10") is None
    assert mb.builder_of("2026-10-11") is None


def test_build_threads_role_primary_to_builder_reason(tmp_path, monkeypatch):
    """Test 1: build() threads Decision.role=primary to builder_reason=primary."""
    import brief_fallback
    from unittest import mock
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)

    # Mock should_run to return a Decision with role="primary"
    def mock_should_run(path, usual_hour, usual_minute, now=None):
        return brief_fallback.Decision(True, "running on primary (mac-mini)", role="primary")

    monkeypatch.setattr(brief_fallback, "should_run", mock_should_run)
    mb.build(NOW, _sources())

    # Verify the brief was written with builder_reason=primary
    assert (tmp_path / "2026-10-09.built-by").exists()
    assert "primary@" in (tmp_path / "2026-10-09.built-by").read_text()


def test_build_threads_role_fallback_to_builder_reason(tmp_path, monkeypatch):
    """Test 2: build() threads Decision.role=fallback to builder_reason=fallback."""
    import brief_fallback
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)

    # Mock should_run to return a Decision with role="fallback"
    def mock_should_run(path, usual_hour, usual_minute, now=None):
        return brief_fallback.Decision(True, "primary did not produce output", role="fallback")

    monkeypatch.setattr(brief_fallback, "should_run", mock_should_run)
    mb.build(NOW, _sources())

    # Verify the brief was written with builder_reason=fallback
    assert (tmp_path / "2026-10-09.built-by").exists()
    assert "fallback@" in (tmp_path / "2026-10-09.built-by").read_text()


def test_build_calls_write_with_fallback_reason_when_should_run(tmp_path, monkeypatch):
    """Test 19: build() calls write with builder_reason='fallback' when fallback should run."""
    import machine_profile
    import brief_fallback
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "macbook-pro")

    # Mock should_run to return True (fallback should run)
    def mock_should_run(path, usual_hour, usual_minute, now=None):
        return brief_fallback.Decision(True, "primary did not produce output")

    monkeypatch.setattr(brief_fallback, "should_run", mock_should_run)
    mb.build(NOW, _sources())

    # Check that the brief was written with fallback builder
    built_by = tmp_path / "2026-10-09.built-by"
    assert built_by.exists()
    assert "fallback@macbook-pro" in built_by.read_text()


def test_build_skips_when_should_run_false(tmp_path, monkeypatch, capsys):
    """Test 19b: build() skips write when should_run returns False."""
    import brief_fallback
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)

    # Mock should_run to return False (fallback should skip)
    def mock_should_run(path, usual_hour, usual_minute, now=None):
        return brief_fallback.Decision(False, "primary produced output (local)")

    monkeypatch.setattr(brief_fallback, "should_run", mock_should_run)
    mb.build(NOW, _sources())

    # Check that no brief was written
    assert not (tmp_path / "2026-10-09.md").exists()
    captured = capsys.readouterr()
    assert "Skipped brief build" in captured.out


def test_write_repairs_a_stale_failure_placeholder_brief(tmp_path, monkeypatch):
    """Test 5: write() overwrites a brief that contains the failure placeholder."""
    import machine_profile
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "mac-mini")

    # Pre-write a stale brief with the failure placeholder
    path = tmp_path / "2026-10-09.md"
    path.write_text("(claude call failed: timeout)\n# Morning brief")

    # write() should recognize it as invalid and overwrite it
    result = mb.write(NOW, _sources())
    assert result == path
    content = path.read_text()
    assert "(claude call failed:" not in content
    assert "# Morning brief" in content


def test_write_repairs_an_empty_brief_file(tmp_path, monkeypatch):
    """Test 6: write() overwrites an empty brief file."""
    import machine_profile
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "mac-mini")

    # Pre-write an empty brief
    path = tmp_path / "2026-10-09.md"
    path.write_text("")

    # write() should recognize it as invalid and overwrite it
    result = mb.write(NOW, _sources())
    assert result == path
    content = path.read_text()
    assert len(content) > 0
    assert "# Morning brief" in content


def test_write_does_not_rewrite_a_valid_existing_brief(tmp_path, monkeypatch):
    """Test 7: write() does not overwrite a valid existing brief (idempotent)."""
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)

    # Pre-write a valid brief with a sentinel value
    path = tmp_path / "2026-10-09.md"
    original_content = "# Morning brief, Thursday 2026-10-09\n\nSentinel: original content\n"
    path.write_text(original_content)

    # write() should recognize it as valid and return without rewriting
    result = mb.write(NOW, _sources())
    assert result == path
    content = path.read_text()
    assert content == original_content  # Should be unchanged


def test_write_does_not_clobber_a_file_that_appears_mid_gather(tmp_path, monkeypatch):
    """Test 8: write() does not overwrite a file that appears while gather() is running."""
    import machine_profile
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "mac-mini")

    # Mock gather to write a competing valid brief as a side effect
    original_gather = mb.gather
    competing_content = "# Morning brief, Thursday 2026-10-09\n\nCompeting brief from another machine\n"

    def mock_gather(now, sources=None):
        path = tmp_path / "2026-10-09.md"
        path.write_text(competing_content)
        return original_gather(now, sources)

    monkeypatch.setattr(mb, "gather", mock_gather)

    # write() should detect the competing file via the re-check and not overwrite it
    result = mb.write(NOW, _sources())
    assert result.read_text() == competing_content  # Should keep the competing content
