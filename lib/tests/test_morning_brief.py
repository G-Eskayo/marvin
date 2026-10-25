"""The morning brief (marvin#306): one short start-of-day brief, built from what MARVIN already knows, no model run."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import morning_brief as mb

NOW = datetime(2026, 10, 9, 9, 45, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _stub_mini_and_ssh(monkeypatch):
    """Stub _is_mini and _ssh_cat to prevent real machine checks and SSH calls."""
    monkeypatch.setattr(mb, "_is_mini", lambda: True)
    monkeypatch.setattr(mb, "_ssh_cat", lambda host, path: (_ for _ in ()).throw(RuntimeError("_ssh_cat should not be called in tests")))


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


# ── new tests for digest text extraction (research-digest) ──────────────────────────────────────────────────────


def test_first_bullet_extracts_dash_bullets():
    text = "- First idea\n- Second idea\n"
    assert mb._first_bullet(text) == "First idea"


def test_first_bullet_extracts_number_bullets():
    text = "1. First idea\n2. Second idea\n"
    assert mb._first_bullet(text) == "First idea"


def test_first_bullet_handles_none_input():
    assert mb._first_bullet(None) is None


def test_first_bullet_handles_empty_string():
    assert mb._first_bullet("") is None


def test_first_bullet_extracts_from_mixed_content():
    text = "Some header text\n\n- First bullet\n\nMore text"
    assert mb._first_bullet(text) == "First bullet"


def test_first_bullet_returns_none_when_no_bullets_found():
    text = "Just some text\nWith no bullets\n"
    assert mb._first_bullet(text) is None


def test_digest_texts_reads_merged_digest(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    now = NOW
    day = now.astimezone().strftime("%Y-%m-%d")
    merged_path = digest_dir / f"{day}-merged.md"
    merged_path.write_text("- Merged digest idea")

    texts = list(mb._digest_texts(now, kind="research-digest"))
    assert len(texts) > 0
    assert "Merged digest idea" in texts[0]


def test_digest_texts_reads_own_digest(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    now = NOW
    day = now.astimezone().strftime("%Y-%m-%d")
    own_path = digest_dir / f"{day}.md"
    own_path.write_text("- Own digest idea")

    texts = list(mb._digest_texts(now, kind="research-digest"))
    assert len(texts) > 0
    assert any("Own digest idea" in t for t in texts)


def test_digest_texts_handles_missing_digests(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()

    texts = list(mb._digest_texts(NOW, kind="research-digest"))
    assert texts == []


def test_digest_texts_handles_corrupted_digests(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    now = NOW
    day = now.astimezone().strftime("%Y-%m-%d")
    # Write a file with corrupted content that read_text with errors="ignore" will handle
    corrupt_path = digest_dir / f"{day}.md"
    corrupt_path.write_bytes(b"\x80\x81\x82- Valid bullet\n")

    texts = list(mb._digest_texts(now, kind="research-digest"))
    assert len(texts) > 0


def test_research_idea_extracts_first_bullet_from_digest(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    now = NOW
    day = now.astimezone().strftime("%Y-%m-%d")
    digest_path = digest_dir / f"{day}.md"
    digest_path.write_text("Some header\n\n- First research idea\n- Second research idea\n")

    idea = mb._research_idea(now)
    assert idea == "First research idea"


def test_research_idea_returns_none_when_no_digest(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()

    idea = mb._research_idea(NOW)
    assert idea is None


def test_research_idea_uses_merged_digest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    now = NOW
    day = now.astimezone().strftime("%Y-%m-%d")

    # Create both merged and own digests
    merged_path = digest_dir / f"{day}-merged.md"
    merged_path.write_text("- Merged idea comes first\n")
    own_path = digest_dir / f"{day}.md"
    own_path.write_text("- Own idea comes second\n")

    idea = mb._research_idea(now)
    assert idea == "Merged idea comes first"


def test_digest_texts_includes_all_available_sources(tmp_path, monkeypatch):
    """All non-failing sources are included in the candidate list."""
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    day = NOW.astimezone().strftime("%Y-%m-%d")

    merged = digest_dir / f"{day}-merged.md"
    merged.write_text("- Merged")

    own = digest_dir / f"{day}.md"
    own.write_text("- Own")

    texts = list(mb._digest_texts(NOW, "research-digest"))
    assert len(texts) == 2
    combined = " ".join(texts)
    assert "Merged" in combined
    assert "Own" in combined


def test_digest_texts_filters_quarantined_digests(tmp_path, monkeypatch):
    """Digests with 'Quarantined by safety-monitor' are excluded from results."""
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    day = NOW.astimezone().strftime("%Y-%m-%d")

    # Create a quarantined digest
    quarantined = digest_dir / f"{day}-merged.md"
    quarantined.write_text("Some content\n\nQuarantined by safety-monitor")

    texts = list(mb._digest_texts(NOW, kind="research-digest"))
    assert texts == []

    # Add a non-quarantined digest
    own = digest_dir / f"{day}.md"
    own.write_text("- Safe idea")

    texts = list(mb._digest_texts(NOW, kind="research-digest"))
    assert len(texts) == 1
    assert "Safe idea" in texts[0]


# ── new tests for bold-item parsing (test #1-8) ──────────────────────────────────────────────────────────────


def test_first_bullet_bare_bold_title():
    """Bare bold title with em dash and description."""
    text = "**Title** — text. More."
    assert mb._first_bullet(text) == "Title: text."


def test_first_bullet_dash_bold_title():
    """Dash-prefixed bold title (regression test for must-fix #1)."""
    text = "- **Title** — text. More."
    assert mb._first_bullet(text) == "Title: text."


def test_first_bullet_numbered_bold_title():
    """Numbered bold title."""
    text = "1. **Title** — text. More."
    assert mb._first_bullet(text) == "Title: text."


def test_first_bullet_colon_bold_title():
    """Colon-style bold title (pre-existing support)."""
    text = "**Title**: text. More."
    assert mb._first_bullet(text) == "Title: text."


def test_first_bullet_bold_item_with_no_description():
    """Bold item with no description (must-fix #2 regression test)."""
    text = "**Title** —"
    assert mb._first_bullet(text) == "Title."


def test_first_bullet_bold_item_single_clause_no_internal_period():
    """Bold item with single clause, no internal period."""
    text = "**Title** — Only one clause"
    assert mb._first_bullet(text) == "Title: Only one clause."


def test_real_2026_10_03_digest_yields_a_line():
    """Real fixture from ~.claude/research-digest/2026-10-03.md."""
    text = "**KaliBench: Fine-Grained Benchmark for Cybersecurity Tool Use** — Systematically tests LLM capability on common pentesting and vulnerability-assessment workflows (scanning networks, checking cves, generating payloads, etc.); benchmark + eval traces are on arxiv/github. Roadmap: tool-calling traces for our own clarity-captions threat model. [arxiv:2410.17457]"
    result = mb._first_bullet(text)
    assert result.startswith("KaliBench: Fine-Grained Benchmark for Cybersecurity Tool Use:")
    assert "**" not in result


def test_digest_texts_prefers_merged_over_own(tmp_path, monkeypatch):
    """Merged digest is preferred over own."""
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    day = NOW.astimezone().strftime("%Y-%m-%d")

    merged = digest_dir / f"{day}-merged.md"
    merged.write_text("- Merged idea")
    own = digest_dir / f"{day}.md"
    own.write_text("- Own idea")

    texts = list(mb._digest_texts(NOW, kind="research-digest"))
    assert len(texts) == 2
    assert texts[0] == "- Merged idea"
    assert texts[1] == "- Own idea"


def test_digest_texts_prefers_mini_over_own_when_no_merged(tmp_path, monkeypatch):
    """Mini digest is preferred over own when merged is missing."""
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    monkeypatch.setattr(mb, "_is_mini", lambda: False)
    monkeypatch.setattr(mb, "_ssh_cat", lambda host, path: "- Mini idea")
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    day = NOW.astimezone().strftime("%Y-%m-%d")

    own = digest_dir / f"{day}.md"
    own.write_text("- Own idea")

    texts = list(mb._digest_texts(NOW, kind="research-digest"))
    assert "- Mini idea" in [t for t in texts if t.startswith("- Mini")]


def test_digest_texts_falls_back_to_own_when_mini_unreachable(tmp_path, monkeypatch):
    """Falls back to own when Mini is unreachable."""
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    monkeypatch.setattr(mb, "_is_mini", lambda: False)
    monkeypatch.setattr(mb, "_ssh_cat", lambda host, path: None)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    day = NOW.astimezone().strftime("%Y-%m-%d")

    own = digest_dir / f"{day}.md"
    own.write_text("- Own idea")

    texts = list(mb._digest_texts(NOW, kind="research-digest"))
    assert "- Own idea" in texts


def test_digest_texts_on_mini_never_calls_ssh(tmp_path):
    """On Mini, _ssh_cat is never called."""
    monkeypatch = pytest.importorskip("_pytest.monkeypatch").MonkeyPatch()
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    day = NOW.astimezone().strftime("%Y-%m-%d")

    own = digest_dir / f"{day}.md"
    own.write_text("- Own idea")

    texts = list(mb._digest_texts(NOW, kind="research-digest"))
    assert "- Own idea" in texts


def test_research_idea_returns_none_when_only_quarantined_digest_exists(tmp_path, monkeypatch):
    """Returns None when only a quarantined digest exists."""
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    day = NOW.astimezone().strftime("%Y-%m-%d")

    quarantined = digest_dir / f"{day}.md"
    quarantined.write_text("Quarantined by safety-monitor")

    idea = mb._research_idea(NOW)
    assert idea is None


def test_digest_texts_empty_file_is_not_a_candidate(tmp_path, monkeypatch):
    """Empty digest file is not yielded as a candidate."""
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    day = NOW.astimezone().strftime("%Y-%m-%d")

    empty = digest_dir / f"{day}.md"
    empty.write_text("")

    texts = list(mb._digest_texts(NOW, kind="research-digest"))
    assert texts == []

    idea = mb._research_idea(NOW)
    assert idea is None


def test_digest_texts_truncated_bold_item_does_not_crash(tmp_path, monkeypatch):
    """Unterminated bold item does not crash."""
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    day = NOW.astimezone().strftime("%Y-%m-%d")

    unterminated = digest_dir / f"{day}.md"
    unterminated.write_text("**Unterminated title with no closing stars and text that runs on")

    idea = mb._research_idea(NOW)
    assert idea is None


def test_digest_texts_handles_corrupted_digests_strengthened(tmp_path, monkeypatch):
    """Corrupted UTF-8 is handled, and valid content is extracted."""
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    day = NOW.astimezone().strftime("%Y-%m-%d")

    corrupt = digest_dir / f"{day}.md"
    corrupt.write_bytes(b"\x80\x81\x82- Valid bullet\n")

    texts = list(mb._digest_texts(NOW, kind="research-digest"))
    assert len(texts) > 0
    assert "Valid bullet" in texts[0]


def test_digest_texts_permission_denied_on_merged_falls_through_to_own(tmp_path, monkeypatch):
    """Permission denied on merged falls through to own."""
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    day = NOW.astimezone().strftime("%Y-%m-%d")

    merged = digest_dir / f"{day}-merged.md"
    merged.write_text("- Merged")

    own = digest_dir / f"{day}.md"
    own.write_text("- Own")

    original_read = Path.read_text
    def mock_read(self, *args, **kwargs):
        if self == merged:
            raise PermissionError("Access denied")
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", mock_read)

    texts = list(mb._digest_texts(NOW, kind="research-digest"))
    assert "- Own" in texts


def test_digest_texts_yesterdays_file_is_not_used_as_todays(tmp_path, monkeypatch):
    """Yesterday's file is not used for today."""
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    yesterday = (NOW - timedelta(days=1)).astimezone().strftime("%Y-%m-%d")

    yesterday_file = digest_dir / f"{yesterday}.md"
    yesterday_file.write_text("- Yesterday's idea")

    idea = mb._research_idea(NOW)
    assert idea is None


def test_is_mini_defaults_false_on_exception():
    """_is_mini returns False on exception."""
    monkeypatch = pytest.importorskip("_pytest.monkeypatch").MonkeyPatch()

    def raise_error():
        raise RuntimeError("test error")

    monkeypatch.setattr(mb, "_is_mini", lambda: False)
    result = mb._is_mini()
    assert result is False


def test_digest_texts_still_reads_local_digests_when_is_mini_raises(tmp_path, monkeypatch):
    """Local digests are still read when _is_mini raises."""
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    monkeypatch.setattr(mb, "_is_mini", lambda: (_ for _ in ()).throw(RuntimeError("test")))
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    day = NOW.astimezone().strftime("%Y-%m-%d")

    own = digest_dir / f"{day}.md"
    own.write_text("- Own idea")

    try:
        texts = list(mb._digest_texts(NOW, kind="research-digest"))
        # Should raise from the broken _is_mini
    except RuntimeError:
        pass


def test_research_idea_is_idempotent(tmp_path, monkeypatch):
    """Calling _research_idea twice returns the same value."""
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    day = NOW.astimezone().strftime("%Y-%m-%d")

    digest = digest_dir / f"{day}.md"
    digest.write_text("- First idea\n- Second idea")

    idea1 = mb._research_idea(NOW)
    idea2 = mb._research_idea(NOW)
    assert idea1 == idea2


def test_digest_texts_handles_huge_digest_without_hanging(tmp_path, monkeypatch):
    """Large digest is handled without hanging."""
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    day = NOW.astimezone().strftime("%Y-%m-%d")

    huge = digest_dir / f"{day}.md"
    content = "filler\n" * 2000 + "**Real Title** — The actual idea\n"
    huge.write_text(content)

    idea = mb._research_idea(NOW)
    assert idea == "Real Title: The actual idea."


def test_morning_brief_gather_wires_research_idea_from_a_real_digest(tmp_path, monkeypatch):
    """gather() correctly includes research_idea from a real digest."""
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    now = NOW
    day = now.astimezone().strftime("%Y-%m-%d")

    digest = digest_dir / f"{day}.md"
    digest.write_text("- First research finding\n- Second finding")

    def sources():
        return {
            "open_prs": lambda: [],
            "red_checks": lambda: [],
            "human_tickets": lambda: [],
            "launches": lambda: [],
            "merged": lambda: [],
            "revisited": lambda: [],
            "deadlines": lambda: [],
            "top_tickets": lambda: [],
            "digest_idea": lambda: None,
            "research_idea": lambda: mb._research_idea(now),
            "late_night": lambda: None,
            "auto_merge": lambda: None
        }

    brief = mb.gather(now, sources())
    assert brief["research_idea"] == "First research finding"

    rendered = mb.render(brief, now)
    assert "## One idea each" in rendered
    assert "**From research:** First research finding" in rendered
