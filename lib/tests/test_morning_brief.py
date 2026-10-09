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
