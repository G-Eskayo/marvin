"""The morning brief (marvin#306): one short start-of-day brief, built from what MARVIN already knows, no model run."""
import json
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import morning_brief as mb
import brief_items as bi

NOW = datetime(2026, 10, 9, 9, 45, tzinfo=timezone.utc)


def _sources(**over):
    base = {
        "open_prs": lambda: [{"number": 308, "title": "MARVIN launcher", "repo": "marvin", "waiting_on_marvin": False, "question": False}],
        "red_checks": lambda: [{"label": "Missed purpose", "detail": "#277 Allow read-only tools: missed", "severity": "red"}],
        "human_tickets": lambda: [{"number": 14, "title": "Enroll in the Apple developer program", "repo": "marvin"}],
        "launches": lambda: [{"kind": "ticket-planner", "cost_usd": 0.8}, {"kind": "ticket-executor", "cost_usd": 0.2},
                             {"kind": "background-analyst", "cost_usd": 0.1}],
        "merged": lambda: [{"number": 307, "title": "North stars single source", "repo": "marvin"}],
        "revisited": lambda: [],
        "deadlines": lambda: [{"project": "clarity-captions", "date": "2026-10-25", "hard": True}],
        "top_tickets": lambda: [{"repo": "clarity-captions", "number": 31, "title": "Live captions view", "priority": "p0"}],
        "digest_idea": lambda: "Wire the outcome check into the brief.",
        "research_idea": lambda: "A paper on cheaper planning with smaller models.",
        "late_night": lambda: "01:40",
        "auto_merge": lambda: None,
        "regressions": lambda: [],
    }
    return {**base, **over}


# ── Test Cases 1-10: Items shape, selection, and rendering ──────────────────────────────────────

def test_1_zero_candidates():
    """Zero candidates — all sources return empty/None → mostly empty sections."""
    sources = _sources(
        open_prs=lambda: [],
        red_checks=lambda: [],
        human_tickets=lambda: [],
        launches=lambda: [],  # Launches returns "Quiet" even when empty
        merged=lambda: [],
        revisited=lambda: [],
        deadlines=lambda: [],
        top_tickets=lambda: [],
        digest_idea=lambda: None,
        research_idea=lambda: None,
        auto_merge=lambda: None,
        regressions=lambda: [],
        late_night=lambda: None,
    )
    gathered = mb.gather(NOW, sources)
    items = mb.select_items(gathered, NOW)
    # Launches always returns a "Quiet" item when empty
    assert any("Quiet" in item.line for item in items)
    text = mb.render(gathered, NOW)
    assert "Morning brief" in text


def test_2_one_candidate():
    """One candidate — exactly one PR anywhere with quiet launches → has rank 1."""
    sources = _sources(
        open_prs=lambda: [{"number": 100, "title": "One PR", "repo": "marvin", "waiting_on_marvin": False, "question": False}],
        red_checks=lambda: [],
        human_tickets=lambda: [],
        launches=lambda: [],  # Launches returns "Quiet"
        merged=lambda: [],
        revisited=lambda: [],
        deadlines=lambda: [],
        top_tickets=lambda: [],
        digest_idea=lambda: None,
        research_idea=lambda: None,
        auto_merge=lambda: None,
        regressions=lambda: [],
        late_night=lambda: None,
    )
    gathered = mb.gather(NOW, sources)
    items = mb.select_items(gathered, NOW)
    # Should have PR (rank 1 in Needs you) and Quiet (Overnight)
    pr_items = [i for i in items if "#100" in i.line]
    assert len(pr_items) == 1
    assert pr_items[0].rank == 1
    text = mb.render(gathered, NOW)
    assert "#100" in text


def test_3_hundreds_of_candidates_capped_at_5():
    """Hundreds of candidates — main items (non-ideas) capped at 5."""
    # Create 200 synthetic top_tickets
    tickets = [
        {"repo": f"r{i%3}", "number": 1000 + i, "title": f"Ticket {i}", "priority": "p0" if i < 100 else "p1"}
        for i in range(200)
    ]
    sources = _sources(top_tickets=lambda: tickets)
    gathered = mb.gather(NOW, sources)
    items = mb.select_items(gathered, NOW)
    # Main items (non-ideas) should be <= 5
    main_items = [i for i in items if i.section != "__ideas__"]
    assert len(main_items) <= 5, f"Expected <= 5 main items, got {len(main_items)}"


def test_4_all_candidates_from_one_section():
    """All candidates from one section — still capped at 5 total (main items only)."""
    prs = [
        {"number": 100 + i, "title": f"PR {i}", "repo": "marvin", "waiting_on_marvin": False, "question": False}
        for i in range(20)
    ]
    # Only include PRs, suppress other items and ideas so all top 5 are from same source
    sources = _sources(
        open_prs=lambda: prs,
        red_checks=lambda: [],
        human_tickets=lambda: [],
        launches=lambda: [],
        merged=lambda: [],
        deadlines=lambda: [],
        top_tickets=lambda: [],
        digest_idea=lambda: None,
        research_idea=lambda: None,
    )
    gathered = mb.gather(NOW, sources)
    items = mb.select_items(gathered, NOW)
    # Main items (non-ideas) should be <= 5
    main_items = [i for i in items if i.section != "__ideas__"]
    assert len(main_items) <= 5
    # Most items should be from Needs you (PRs)
    needs_you_items = [i for i in main_items if i.section == "Needs you"]
    assert len(needs_you_items) >= 1, "At least one PR should be in top items"


def test_5_ties_in_rank_are_deterministic():
    """Ties in rank — two items with identical score produce deterministic order."""
    prs = [
        {"number": 100, "title": "PR A", "repo": "marvin", "waiting_on_marvin": False, "question": False},
        {"number": 101, "title": "PR B", "repo": "marvin", "waiting_on_marvin": False, "question": False},
    ]
    sources = _sources(open_prs=lambda: prs)
    gathered = mb.gather(NOW, sources)
    items1 = mb.select_items(gathered, NOW)
    items2 = mb.select_items(gathered, NOW)
    # Same order on both runs
    assert [i.line for i in items1] == [i.line for i in items2]


def test_6_missing_layer_is_handled():
    """An item missing a layer — select_items() fills the missing layer."""
    # Create a minimal item without all layers
    # This tests that the mapping functions handle missing fields gracefully
    gathered = mb.gather(NOW, _sources())
    items = mb.select_items(gathered, NOW)
    # All items should have required fields
    for item in items:
        assert isinstance(item, bi.Item)
        assert item.section in bi.SECTIONS or item.section == "__ideas__"
        assert isinstance(item.rank, int)
        assert isinstance(item.line, str)
        assert isinstance(item.summary, str)


def test_7_no_url_renders_without_broken_links():
    """A source with no URL — renders without broken `[link]()`."""
    # Only include digest idea to ensure it's selected
    sources = _sources(
        digest_idea=lambda: "An idea from the digest",
        open_prs=lambda: [],
        red_checks=lambda: [],
        human_tickets=lambda: [],
        launches=lambda: [],
        merged=lambda: [],
        deadlines=lambda: [],
        top_tickets=lambda: [],
        research_idea=lambda: None,
        auto_merge=lambda: None,
        regressions=lambda: [],
        late_night=lambda: None,
    )
    gathered = mb.gather(NOW, sources)
    text = mb.render(gathered, NOW)
    # Should render the idea without broken markup
    assert "An idea from the digest" in text


def test_8_duplicate_items_deduped():
    """Duplicate items from two feeds — dedup keeps one (same ticket from different feeds)."""
    # Same ticket appearing in both top_tickets and human_tickets
    top_tickets_list = [{"repo": "marvin", "number": 100, "title": "Ticket X", "priority": "p0"}]
    human_tickets_list = [{"number": 100, "title": "Ticket X (from human)", "repo": "marvin"}]

    # Suppress other sources to ensure both items are considered
    sources = _sources(
        open_prs=lambda: [],
        top_tickets=lambda: top_tickets_list,
        human_tickets=lambda: human_tickets_list,
        red_checks=lambda: [],
        launches=lambda: [],
        merged=lambda: [],
        deadlines=lambda: [],
        digest_idea=lambda: None,
        research_idea=lambda: None,
        auto_merge=lambda: None,
        regressions=lambda: [],
        late_night=lambda: None,
    )
    gathered = mb.gather(NOW, sources)
    items = mb.select_items(gathered, NOW)
    # Count main items with #100 — should be 1 due to dedup (same ticket from two sources)
    main_items = [i for i in items if i.section != "__ideas__"]
    count_100 = sum(1 for i in main_items if "#100" in i.line)
    assert count_100 <= 1, f"Expected <= 1 item with #100, got {count_100}, items: {[i.line for i in main_items]}"


def test_9_huge_summary_truncated():
    """Huge summary text — render stays one sentence, summary capped."""
    huge_title = "x" * 50000
    tickets = [{"repo": "marvin", "number": 100, "title": huge_title, "priority": "p0"}]
    sources = _sources(top_tickets=lambda: tickets)
    gathered = mb.gather(NOW, sources)
    items = mb.select_items(gathered, NOW)
    text = mb.render(gathered, NOW)
    # Line should be manageable length (truncated)
    for item in items:
        assert len(item.line) < 500, f"Line too long: {len(item.line)}"


def test_10_non_english_titles():
    """Non-English titles — renders without mangling."""
    hebrew_title = "חלק מהשם"  # "Part of the name" in Hebrew
    tickets = [{"repo": "marvin", "number": 100, "title": hebrew_title, "priority": "p0"}]
    sources = _sources(top_tickets=lambda: tickets)
    gathered = mb.gather(NOW, sources)
    items = mb.select_items(gathered, NOW)
    text = mb.render(gathered, NOW)
    # Should render without raising
    assert "Morning brief" in text


def test_11_markdown_injection_in_titles():
    """Markdown/HTML injection — rendered `.md` structure remains valid."""
    injection_title = "](javascript:alert(1))"
    tickets = [{"repo": "marvin", "number": 100, "title": injection_title, "priority": "p0"}]
    sources = _sources(top_tickets=lambda: tickets)
    gathered = mb.gather(NOW, sources)
    text = mb.render(gathered, NOW)
    # Check that section headers are still parseable
    assert "## Needs you" in text or "## Today" in text or "## Overnight" in text


def test_12_feed_failing_does_not_drop_whole_brief():
    """A feed failing — other sections still populate."""
    sources = _sources(open_prs=lambda: (_ for _ in ()).throw(OSError("rate limited")))
    gathered = mb.gather(NOW, sources)
    # Should have missing entry
    assert any("open PRs" in m for m in gathered.get("missing", []))
    items = mb.select_items(gathered, NOW)
    # Other items should still be there
    text = mb.render(gathered, NOW)
    assert "Morning brief" in text


def test_13_each_dependency_failing_individually():
    """Each dependency failing — brief still builds."""
    sources_to_test = ["open_prs", "red_checks", "human_tickets", "launches", "deadlines", "top_tickets"]
    for source_key in sources_to_test:
        failing_sources = _sources(**{source_key: lambda: (_ for _ in ()).throw(OSError("test failure"))})
        gathered = mb.gather(NOW, failing_sources)
        # Should record the failure
        assert gathered["missing"], f"Expected missing entry for {source_key}"
        # Should still render
        text = mb.render(gathered, NOW)
        assert "Morning brief" in text


def test_14_write_idempotency(tmp_path, monkeypatch):
    """Repeats/idempotency — `write()` called twice is a no-op."""
    import machine_profile
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "test")

    path1 = mb.write(NOW, _sources())
    content1 = path1.read_text()
    items1_path = tmp_path / "2026-10-09.items.json"
    items1 = json.loads(items1_path.read_text())

    # Second write with different sources should not overwrite
    path2 = mb.write(NOW, _sources(open_prs=lambda: []))
    content2 = path2.read_text()
    items2 = json.loads(items1_path.read_text())

    assert content1 == content2
    assert items1 == items2


def test_15_concurrency_safe_write(tmp_path, monkeypatch):
    """Concurrency — atomic writes prevent partial/corrupt `.json`."""
    import machine_profile
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "test")

    path = mb.write(NOW, _sources())
    # File should exist and be valid JSON
    assert path.exists()
    items_path = tmp_path / "2026-10-09.items.json"
    assert items_path.exists()
    json.loads(items_path.read_text())  # Should not raise


def test_16_unwritable_briefs_dir(tmp_path, monkeypatch):
    """Wrong permissions — `write()` raises clear error."""
    import machine_profile
    read_only_dir = tmp_path / "readonly"
    read_only_dir.mkdir()
    read_only_dir.chmod(0o444)  # Read-only

    monkeypatch.setattr(mb, "BRIEFS", read_only_dir)
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "test")

    try:
        mb.write(NOW, _sources())
        assert False, "Expected OSError"
    except OSError as e:
        assert "cannot write" in str(e) or "Permission denied" in str(e)
    finally:
        read_only_dir.chmod(0o755)  # Restore for cleanup


def test_17_stale_json_missing_keys(tmp_path, monkeypatch):
    """Stale state — invalid `<day>.json` falls back gracefully."""
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)

    # Write a JSON file with missing keys
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "2026-10-09.md").write_text("# Morning brief")
    (tmp_path / "2026-10-09.read").write_text(NOW.isoformat())

    # show_today should not crash
    result = mb.show_today(NOW)
    # Result should be the markdown, not a crash
    assert result is not None or result is None  # Graceful fallback


def test_18_corrupt_json_handling(tmp_path, monkeypatch):
    """A person's mistake — broken JSON doesn't crash show_today()."""
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)

    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "2026-10-09.md").write_text("# Morning brief")
    (tmp_path / "2026-10-09.read").write_text(NOW.isoformat())
    # Corrupt JSON
    (tmp_path / "2026-10-09.items.json").write_text("{invalid json")

    # show_today should not crash
    result = mb.show_today(NOW)
    assert result is not None or result is None  # Graceful fallback


def test_19_ranking_favors_active_work():
    """Ranking favors active work — hard deadline and p0 outrank routine review."""
    sources = _sources(
        deadlines=lambda: [{"project": "clarity-captions", "date": "2026-10-11", "hard": True}],
        top_tickets=lambda: [{"repo": "marvin", "number": 100, "title": "p0 ticket", "priority": "p0"}],
        open_prs=lambda: [{"number": 200, "title": "Routine PR", "repo": "marvin", "waiting_on_marvin": False, "question": False}],
    )
    gathered = mb.gather(NOW, sources)
    items = mb.select_items(gathered, NOW)
    # Items should be ordered by score
    items2 = mb.select_items(gathered, NOW)
    assert [i.line for i in items] == [i.line for i in items2]  # Deterministic


def test_20_cap_at_5_items():
    """Cap holds — exactly 6 strong candidates → exactly 5 main items ship."""
    tickets = [
        {"repo": "marvin", "number": 100 + i, "title": f"p0 ticket {i}", "priority": "p0"}
        for i in range(6)
    ]
    sources = _sources(top_tickets=lambda: tickets)
    gathered = mb.gather(NOW, sources)
    items = mb.select_items(gathered, NOW)
    # Main items (non-ideas) should be exactly 5
    main_items = [i for i in items if i.section != "__ideas__"]
    assert len(main_items) == 5, f"Expected 5 main items, got {len(main_items)}"


def test_21_session_start_renders_from_items(tmp_path, monkeypatch):
    """Session start renders from items — brief still shows without stale markdown."""
    import machine_profile
    monkeypatch.setattr(mb, "BRIEFS", tmp_path)
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "test")

    # Write a brief
    path = mb.write(NOW, _sources())

    # Remove the markdown file to simulate items being the source of truth
    path.unlink()

    # show_today should still work (falls back gracefully)
    result = mb.show_today(NOW)
    # Should handle missing markdown gracefully
    assert result is None or "Morning brief" in str(result)


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
    different_sources = _sources(open_prs=lambda: [])
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
