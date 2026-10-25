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


def test_first_paragraph_with_heading_extracts_section_content(tmp_path):
    f = tmp_path / "digest.md"
    f.write_text("# Title\n\n## Section\n\nFirst para text here.\n\nSecond para.\n\n## Next")
    result = mb._first_paragraph(f, "Section")
    assert result == "First para text here."


def test_first_paragraph_with_heading_returns_none_when_heading_missing(tmp_path):
    f = tmp_path / "digest.md"
    f.write_text("# Title\n\nSome text.")
    assert mb._first_paragraph(f, "Missing") is None


def test_first_paragraph_without_heading_extracts_bold_text(tmp_path):
    f = tmp_path / "digest.md"
    f.write_text("## Section\n\n**Title**: descriptive text.\n\nNext para.")
    result = mb._first_paragraph(f, None)
    assert result == "Title: descriptive text."


def test_first_paragraph_without_heading_handles_em_dash_separator(tmp_path):
    f = tmp_path / "digest.md"
    f.write_text("**Topic** — explanation text.\n\nNext.")
    result = mb._first_paragraph(f, None)
    assert result == "Topic: explanation text."


def test_first_paragraph_without_heading_handles_bullet_prefix(tmp_path):
    f = tmp_path / "digest.md"
    f.write_text("- **Title**: descriptive text.\n\nNext.")
    result = mb._first_paragraph(f, None)
    assert result == "Title: descriptive text."


def test_first_paragraph_without_heading_handles_numbered_prefix(tmp_path):
    f = tmp_path / "digest.md"
    f.write_text("1. **Title**: descriptive text.\n\nNext.")
    result = mb._first_paragraph(f, None)
    assert result == "Title: descriptive text."


def test_first_paragraph_without_heading_handles_asterisk_prefix(tmp_path):
    f = tmp_path / "digest.md"
    f.write_text("* **Title**: descriptive text.\n\nNext.")
    result = mb._first_paragraph(f, None)
    assert result == "Title: descriptive text."


def test_first_paragraph_without_heading_ignores_whitespace_around_bold(tmp_path):
    f = tmp_path / "digest.md"
    f.write_text("   - **Title**  :  descriptive text.\n\nNext.")
    result = mb._first_paragraph(f, None)
    assert result == "Title: descriptive text."


def test_first_paragraph_without_heading_stops_at_first_sentence(tmp_path):
    f = tmp_path / "digest.md"
    f.write_text("**Title**: first sentence. Second sentence.\n\nNext.")
    result = mb._first_paragraph(f, None)
    assert result == "Title: first sentence."


def test_first_paragraph_without_heading_handles_corrupt_file(tmp_path):
    f = tmp_path / "digest.md"
    f.write_bytes(b"\xff\xfe**Title**: text.")
    result = mb._first_paragraph(f, None)
    assert result is None or isinstance(result, str)


def test_first_paragraph_without_heading_returns_none_when_no_bold_text(tmp_path):
    f = tmp_path / "digest.md"
    f.write_text("Regular text\nNo bold here.")
    assert mb._first_paragraph(f, None) is None


def test_first_paragraph_without_heading_returns_none_for_missing_file(tmp_path):
    f = tmp_path / "nonexistent.md"
    assert mb._first_paragraph(f, None) is None


def test_research_idea_tries_merged_then_default_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    (tmp_path / "research-digest").mkdir()

    merged_file = tmp_path / "research-digest" / "2026-10-09-merged.md"
    merged_file.write_text("**Merged Paper**: merged insight.\n")

    default_file = tmp_path / "research-digest" / "2026-10-09.md"
    default_file.write_text("**Default Paper**: default insight.\n")

    now = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
    result = mb._research_idea(now)
    assert "merged insight" in result


def test_research_idea_falls_back_to_default_when_merged_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    (tmp_path / "research-digest").mkdir()

    default_file = tmp_path / "research-digest" / "2026-10-09.md"
    default_file.write_text("**Default Paper**: default insight.\n")

    now = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
    result = mb._research_idea(now)
    assert result == "Default Paper: default insight."


def test_research_idea_returns_none_when_neither_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    (tmp_path / "research-digest").mkdir()

    now = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
    assert mb._research_idea(now) is None


def test_1_real_2026_10_03_md_excerpt_simple_bullet(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    (tmp_path / "research-digest").mkdir()
    today = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
    f = tmp_path / "research-digest" / "2026-10-03.md"
    f.write_text("- **Title**: blurb. [link]\n\nOther content.")
    result = mb._research_idea(today)
    assert result == "Title: blurb."


def test_2_real_2026_10_03_merged_md_excerpt_parenthetical_annotation(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    (tmp_path / "research-digest").mkdir()
    today = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
    f = tmp_path / "research-digest" / "2026-10-03-merged.md"
    f.write_text("**KaliBench: Benchmark for Evaluating LLM-based Code Generators** (confirmed on both). Its fine-grained scoring framework.\n\nMore content.")
    result = mb._research_idea(today)
    assert result == "KaliBench: Benchmark for Evaluating LLM-based Code Generators: Its fine-grained scoring framework."


def test_3_real_2026_10_07_merged_md_excerpt_italicized_parenthetical_and_colon(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    (tmp_path / "research-digest").mkdir()
    today = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
    f = tmp_path / "research-digest" / "2026-10-07-merged.md"
    f.write_text("**EmbeddingGemma 2: An open-source embedding model** *(confirmed on both)*: A possible replacement for expensive closed alternatives.\n\nMore.")
    result = mb._research_idea(today)
    assert result == "EmbeddingGemma 2: An open-source embedding model: A possible replacement for expensive closed alternatives."


def test_4_real_2026_07_03_md_excerpt_em_dash_separator_no_bullet(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    (tmp_path / "research-digest").mkdir()
    today = datetime(2026, 7, 3, 12, tzinfo=timezone.utc)
    f = tmp_path / "research-digest" / "2026-07-03.md"
    f.write_text("**Title** — blurb.\n\nNext para.")
    result = mb._research_idea(today)
    assert result == "Title: blurb."


def test_5_real_merged_preferred_over_default_when_both_present(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    (tmp_path / "research-digest").mkdir()
    today = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
    merged = tmp_path / "research-digest" / "2026-10-03-merged.md"
    default = tmp_path / "research-digest" / "2026-10-03.md"
    merged.write_text("**Merged Paper**: merged insight.\n")
    default.write_text("**Default Paper**: default insight.\n")
    result = mb._research_idea(today)
    assert "merged insight" in result


def test_6_real_quarantine_placeholder_content_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    (tmp_path / "research-digest").mkdir()
    today = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
    f = tmp_path / "research-digest" / "2026-10-16.md"
    quarantine_text = ("[QUARANTINE PLACEHOLDER: research_colony]\n"
                       "This is a placeholder for content being held back for review.\n")
    f.write_text(quarantine_text)
    result = mb._research_idea(today)
    assert result is None


def test_7_yesterday_content_not_used_for_today(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    (tmp_path / "research-digest").mkdir()
    today = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
    yesterday_file = tmp_path / "research-digest" / "2026-10-03.md"
    yesterday_file.write_text("**Yesterday's Paper**: insight.\n")
    result = mb._research_idea(today)
    assert result is None


def test_8_empty_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    (tmp_path / "research-digest").mkdir()
    today = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
    f = tmp_path / "research-digest" / "2026-10-09.md"
    f.write_text("")
    result = mb._research_idea(today)
    assert result is None


def test_9_truncated_bold_no_closing_marker_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    (tmp_path / "research-digest").mkdir()
    today = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
    f = tmp_path / "research-digest" / "2026-10-09.md"
    f.write_text("**Title: no closing marker here")
    result = mb._research_idea(today)
    assert result is None


def test_10_corrupt_file_extracts_readable_content(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    (tmp_path / "research-digest").mkdir()
    today = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
    f = tmp_path / "research-digest" / "2026-10-09.md"
    f.write_bytes(b"\xff\xfe**Title**: text.")
    result = mb._first_paragraph(f, None)
    assert result == "Title: text."


def test_11_research_idea_idempotent_repeated_reads(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    (tmp_path / "research-digest").mkdir()
    today = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
    f = tmp_path / "research-digest" / "2026-10-03.md"
    f.write_text("- **Title**: blurb. [link]\n\nOther content.")
    result1 = mb._research_idea(today)
    result2 = mb._research_idea(today)
    assert result1 == result2


def test_12_title_with_nothing_usable_after_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    (tmp_path / "research-digest").mkdir()
    today = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
    f = tmp_path / "research-digest" / "2026-10-09.md"
    f.write_text("**Title**: .")
    result = mb._research_idea(today)
    assert result is None
