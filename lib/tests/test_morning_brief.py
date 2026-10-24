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


def test_build_cli_skips_when_should_run_returns_false(tmp_path, monkeypatch, capsys):
    """Test 6: build_cli() returns None and skips when brief_fallback.should_run() returns False."""
    import brief_fallback

    monkeypatch.setattr(mb, "BRIEFS", tmp_path)
    today = datetime(2026, 10, 24, 9, 45, tzinfo=timezone.utc)

    # Mock should_run to return False
    mock_decision = brief_fallback.Decision(
        should_build=False, reason="brief produced on mac-mini-1, still fresh"
    )
    monkeypatch.setattr(mb.brief_fallback, "should_run", lambda **kw: mock_decision)

    # Call build_cli()
    result = mb.build_cli(now=today)

    # Verify it returned None (skipped)
    assert result is None
    # Verify nothing was written
    assert not (tmp_path / "2026-10-24.md").exists()
    # Verify the skip message was printed
    captured = capsys.readouterr()
    assert "[skip]" in captured.out


def test_build_cli_builds_and_records(tmp_path, monkeypatch, capsys):
    """Test 7: build_cli() builds the brief, records it, and returns the path."""
    import brief_fallback

    monkeypatch.setattr(mb, "BRIEFS", tmp_path)
    today = datetime(2026, 10, 24, 9, 45, tzinfo=timezone.utc)

    # Mock should_run to return True
    mock_decision = brief_fallback.Decision(should_build=True, reason="must build")
    monkeypatch.setattr(mb.brief_fallback, "should_run", lambda **kw: mock_decision)

    # Mock machine_profile
    monkeypatch.setattr(mb.machine_profile, "registry_id", lambda: "mac-mini-1")

    # Call build_cli()
    result = mb.build_cli(now=today)

    # Verify the brief was written
    assert result is not None
    assert result.name == "2026-10-24.md"
    assert result.exists()

    # Verify the sidecar was created
    sidecar = result.with_name(result.stem + ".built-by.json")
    assert sidecar.exists()
    assert json.loads(sidecar.read_text())["built_on"] == "mac-mini-1"

    # Verify the path was printed
    captured = capsys.readouterr()
    assert str(result) in captured.out
