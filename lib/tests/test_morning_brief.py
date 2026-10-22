"""The morning brief (marvin#306): one short start-of-day brief, built from what MARVIN already knows, no model run."""
import json
from datetime import datetime, timezone
from pathlib import Path
import pytest

import morning_brief as mb

NOW = datetime(2026, 10, 9, 9, 45, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_real_subprocess(monkeypatch):
    """Prevent accidental real subprocess calls (network, real file access) in tests."""
    import subprocess
    original_run = subprocess.run

    def patched_run(*args, **kwargs):
        # Allow specific test mocks; raise on real calls
        raise RuntimeError(f"Real subprocess.run called in test: {args}")

    monkeypatch.setattr(subprocess, "run", patched_run)


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


def test_first_paragraph_text_extracts_from_text_directly():
    text = "**Research idea**: Some important finding. More details.\n\nNext section."
    result = mb._first_paragraph_text(text, None)
    assert result == "Research idea: Some important finding."


def test_first_paragraph_text_extracts_under_heading_without_prefix():
    text = "## Compounding Move\n\nThis is the idea. More text.\n\n## Next section"
    result = mb._first_paragraph_text(text, "Compounding Move")
    assert result == "This is the idea. More text."


def test_first_paragraph_text_tolerates_dash_prefix():
    text = "- ## Compounding Move\n\nThis is the idea.\n\n## Next section"
    result = mb._first_paragraph_text(text, "Compounding Move")
    assert result == "This is the idea."


def test_first_paragraph_text_tolerates_asterisk_prefix():
    text = "* ## Compounding Move\n\nThis is the idea.\n\n## Next section"
    result = mb._first_paragraph_text(text, "Compounding Move")
    assert result == "This is the idea."


def test_first_paragraph_text_tolerates_numbered_list_prefix():
    text = "1) ## Compounding Move\n\nThis is the idea.\n\n## Next section"
    result = mb._first_paragraph_text(text, "Compounding Move")
    assert result == "This is the idea."


def test_first_paragraph_text_tolerates_various_numbered_prefixes():
    """Test that various numeric list formats are tolerated."""
    for prefix in ["1) ", "2. ", "42) ", "99. "]:
        text = f"{prefix}## Compounding Move\n\nThis is the idea.\n\n## Next section"
        result = mb._first_paragraph_text(text, "Compounding Move")
        assert result == "This is the idea.", f"Failed for prefix: {prefix}"


def test_read_text_returns_file_content_when_exists(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("Content here")
    assert mb._read_text(f) == "Content here"


def test_read_text_returns_none_when_missing(tmp_path):
    f = tmp_path / "missing.md"
    assert mb._read_text(f) is None


def test_read_text_returns_none_on_decode_error(tmp_path):
    f = tmp_path / "bad.txt"
    f.write_bytes(b'\xff\xfe')
    result = mb._read_text(f)
    assert result is None


def test_research_idea_returns_none_when_quarantined(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    (digest_dir / "2026-10-09.md").write_text("**Quarantined research**: idea\n\nQuarantined by safety-monitor")
    now = datetime(2026, 10, 9, 9, tzinfo=timezone.utc)
    result = mb._research_idea(now)
    assert result is None


def test_research_idea_returns_paragraph_when_not_quarantined(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    (digest_dir / "2026-10-09.md").write_text("**Good research**: Some useful finding. More details.\n\nMore text.")
    now = datetime(2026, 10, 9, 9, tzinfo=timezone.utc)
    result = mb._research_idea(now)
    assert result == "Good research: Some useful finding."


def test_research_text_prefers_merged_digest(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    (digest_dir / "2026-10-09.md").write_text("**Regular**: idea")
    (digest_dir / "2026-10-09-merged.md").write_text("**Merged**: idea")
    result = mb._research_text("2026-10-09")
    assert result == "**Merged**: idea"


def test_research_text_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    (tmp_path / "research-digest").mkdir()
    result = mb._research_text("2026-10-09")
    assert result is None


def test_research_text_order_prefers_merged_over_own(tmp_path, monkeypatch):
    """On local machine, merged is preferred over own."""
    import machine_profile
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "macbook-pro")
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    (digest_dir / "2026-10-09.md").write_text("**Own**: idea")
    (digest_dir / "2026-10-09-merged.md").write_text("**Merged**: idea")
    result = mb._research_text("2026-10-09")
    assert result == "**Merged**: idea"


def test_research_text_fallback_to_own_when_no_merged(tmp_path, monkeypatch):
    """On local machine, own is used when merged is missing."""
    import machine_profile
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "macbook-pro")
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    (digest_dir / "2026-10-09.md").write_text("**Own**: idea")
    result = mb._research_text("2026-10-09")
    assert result == "**Own**: idea"


def test_research_text_tries_mini_via_ssh_before_own(tmp_path, monkeypatch):
    """On non-Mini, ssh to Mini is tried before falling back to own."""
    import machine_profile
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "macbook-pro")
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    (digest_dir / "2026-10-09.md").write_text("**Own**: idea")
    # Mock ssh to return Mini's merged
    monkeypatch.setattr(mb, "_ssh_cat_mini", lambda path: "**Mini merged**: idea" if "merged" in path else None)
    result = mb._research_text("2026-10-09")
    assert result == "**Mini merged**: idea"


def test_research_text_falls_back_to_own_if_mini_ssh_fails(tmp_path, monkeypatch):
    """If Mini ssh fails, own (local) is used."""
    import machine_profile
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "macbook-pro")
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    (digest_dir / "2026-10-09.md").write_text("**Own**: idea")
    # Mock ssh to always fail
    monkeypatch.setattr(mb, "_ssh_cat_mini", lambda path: None)
    result = mb._research_text("2026-10-09")
    assert result == "**Own**: idea"


def test_research_text_on_mini_skips_ssh(tmp_path, monkeypatch):
    """On Mini, ssh is skipped and own is used as fallback."""
    import machine_profile
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "mac-mini")
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    (digest_dir / "2026-10-09.md").write_text("**Own**: idea")
    # Mock ssh to detect if it's called (it shouldn't be)
    calls = []
    monkeypatch.setattr(mb, "_ssh_cat_mini", lambda path: (calls.append(path), None)[1])
    result = mb._research_text("2026-10-09")
    assert result == "**Own**: idea"
    assert len(calls) == 0  # ssh was not called


def test_research_idea_handles_ssh_failures_gracefully(tmp_path, monkeypatch):
    """_research_idea returns None when all sources fail."""
    import machine_profile
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    monkeypatch.setattr(machine_profile, "machine_label", lambda: "macbook-pro")
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    monkeypatch.setattr(mb, "_ssh_cat_mini", lambda path: None)
    now = datetime(2026, 10, 9, 9, tzinfo=timezone.utc)
    result = mb._research_idea(now)
    assert result is None


def test_ssh_cat_mini_returns_none_on_connection_failure(monkeypatch):
    """_ssh_cat_mini gracefully returns None when ssh fails."""
    monkeypatch.setattr("subprocess.run", lambda *a, **k: type('obj', (), {'returncode': 1, 'stdout': ''})())
    result = mb._ssh_cat_mini("~/.claude/test.md")
    assert result is None


def test_first_paragraph_text_prevents_garbage_merge_across_blank_lines():
    """The [^\n*]+ pattern prevents matching title across blank lines into unrelated bullets."""
    text = """**Label One**: Some text here

- ** Label Two**: More text
"""
    result = mb._first_paragraph_text(text, None)
    # Should match "Label One", not incorrectly merge across the blank line
    assert result == "Label One: Some text here."
    # Should not include "Label Two"
    assert "Label Two" not in result


def test_is_quarantined_detects_exact_quarantine_marker():
    """_is_quarantined detects the exact 'Quarantined by safety-monitor' marker."""
    text = "**Research idea**: Something\n\nQuarantined by safety-monitor"
    assert mb._is_quarantined(text) is True


def test_is_quarantined_detects_paraphrased_forms():
    """_is_quarantined catches LLM-paraphrased wording (case-insensitive)."""
    text = "**Research idea**: Something\n\nThis idea was quarantined by the safety-monitor process"
    assert mb._is_quarantined(text) is True

    text_lower = "**Research idea**: Something\n\nThe Safety-Monitor Quarantined this content"
    assert mb._is_quarantined(text_lower) is True


def test_is_quarantined_requires_both_keywords():
    """_is_quarantined requires both 'quarantined' and 'safety-monitor' to avoid false positives."""
    assert mb._is_quarantined("This idea is quarantined") is False
    assert mb._is_quarantined("This is from the safety-monitor") is False
    assert mb._is_quarantined("Quarantined by safety-monitor") is True


def test_research_idea_detects_quarantine_with_paraphrased_wording(tmp_path, monkeypatch):
    """_research_idea returns None when digest is quarantined, even if paraphrased."""
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    (digest_dir / "2026-10-09.md").write_text(
        "**Flagged research**: Some finding\n\nThe Safety-Monitor held this quarantined for safety reasons"
    )
    now = datetime(2026, 10, 9, 9, tzinfo=timezone.utc)
    result = mb._research_idea(now)
    assert result is None


def test_research_text_falls_back_to_own_if_machine_profile_raises(tmp_path, monkeypatch):
    """_research_text falls back to own (local) if machine_profile.machine_label() raises."""
    monkeypatch.setattr(mb, "CLAUDE", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    (digest_dir / "2026-10-09.md").write_text("**Own**: idea")
    # Mock machine_profile to raise an exception
    monkeypatch.setattr("machine_profile.machine_label", lambda: (_ for _ in ()).throw(RuntimeError("test error")))
    result = mb._research_text("2026-10-09")
    # Should fall back to own (local) file
    assert result == "**Own**: idea"
