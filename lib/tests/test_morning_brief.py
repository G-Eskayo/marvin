"""The morning brief (marvin#306): one short start-of-day brief, built from what MARVIN already knows, no model run."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

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


def test_build_gates_on_should_run(tmp_path, monkeypatch):
    """Test 3: build() skips when should_run() returns False (standby, not yet time)."""
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)
    path = tmp_path / "2026-10-09.md"

    # Mock should_run to return False (we're standby and it's not fallback time yet).
    monkeypatch.setattr("morning_brief.brief_fallback.should_run", lambda *a, **k: False)

    # Mock gather to raise if called (it shouldn't be).
    def raise_on_gather(*a, **k):
        raise AssertionError("gather should not be called when should_run returns False")
    monkeypatch.setattr(mb, "gather", raise_on_gather)

    result = mb.build(NOW, _sources())
    # Should return the path without building.
    assert result == path
    # File should not be created.
    assert not path.exists()


def test_build_writes_sidecar_before_brief(tmp_path, monkeypatch):
    """Test 4: build() writes the .built-by sidecar before the brief body."""
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)
    monkeypatch.setattr("morning_brief.machine_profile.registry_id", lambda: "macbook-pro")
    monkeypatch.setattr("morning_brief.brief_fallback.should_run", lambda *a, **k: True)
    path = mb.build(NOW, _sources())

    # Sidecar should exist and contain this machine's ID.
    sidecar = tmp_path / "2026-10-09.md.built-by"
    assert sidecar.exists()
    assert sidecar.read_text() == "macbook-pro"

    # Brief should exist and be valid.
    assert path.exists()
    assert "# Morning brief" in path.read_text()


def test_build_skips_when_already_produced(tmp_path, monkeypatch):
    """Test 5: build() skips (returns path) when output is already produced by another machine."""
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)
    monkeypatch.setattr("morning_brief.machine_profile.registry_id", lambda: "macbook-pro")
    monkeypatch.setattr("morning_brief.brief_fallback.should_run", lambda *a, **k: True)

    # Simulate brief already produced by mac-mini.
    path = tmp_path / "2026-10-09.md"
    path.write_text("# Existing brief from mac-mini")
    sidecar = tmp_path / "2026-10-09.md.built-by"
    sidecar.write_text("mac-mini")

    # Try to build: should skip.
    result = mb.build(NOW, _sources())
    assert result == path
    # The existing brief should not change.
    assert "Existing brief from mac-mini" in path.read_text()


def test_builder_of_returns_machine_id_from_sidecar(tmp_path):
    """Test 17: builder_of() returns the machine ID from the .built-by sidecar."""
    path = tmp_path / "brief.md"
    path.write_text("# Brief")
    sidecar = tmp_path / "brief.md.built-by"
    sidecar.write_text("mac-mini")

    assert brief_fallback.builder_of(path) == "mac-mini"


def test_builder_of_returns_none_for_missing_sidecar(tmp_path):
    """builder_of() returns None if sidecar doesn't exist."""
    path = tmp_path / "brief.md"
    path.write_text("# Brief")
    assert brief_fallback.builder_of(path) is None


def test_build_brief_leg_skip_when_already_produced(tmp_path, monkeypatch):
    """Test 4 (brief leg): build() skips writing if brief already produced by another machine.
    Tests the recheck before writing (the second gate before path.write_text).
    """
    briefs_dir = tmp_path / "briefs"
    briefs_dir.mkdir(parents=True)
    brief_path = briefs_dir / "2026-10-09.md"

    # Pre-create the brief file as if produced by another machine.
    brief_path.write_text("# Brief from primary")
    sidecar = briefs_dir / "2026-10-09.md.built-by"
    sidecar.write_text("mac-mini")

    # Mock machine_profile to recognize the file as produced by another machine.
    monkeypatch.setattr("brief_fallback.machine_profile.registry_id", lambda: "macbook-pro")
    monkeypatch.setattr("brief_fallback.machine_profile.remote_macs", lambda: {})

    # Mock should_run and produced.
    monkeypatch.setattr("brief_fallback.should_run", lambda *a, **k: True)
    monkeypatch.setattr("brief_fallback.produced", lambda path: path == brief_path)

    # Patch BRIEFS to use tmp_path.
    monkeypatch.setattr(mb, "BRIEFS", briefs_dir)

    # Mock gather and render.
    monkeypatch.setattr(mb, "gather", lambda *a, **k: {})
    monkeypatch.setattr(mb, "render", lambda *a, **k: "# New brief content")

    original_content = brief_path.read_text()
    result = mb.build(NOW, _sources())

    # File should not have been modified.
    assert brief_path.read_text() == original_content
    assert result == brief_path
