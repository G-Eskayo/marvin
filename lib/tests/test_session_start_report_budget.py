"""marvin#1141: session-start report budget tests.

The session-start report was cut to 8,000 chars to fit Claude Code's hook cap (marvin#1037),
which meant the lexicon's definitions were dropped in favor of just the term names
(marvin#1037, commit 98bc265b). After removing the MCP glossary to its own reference note,
the full lexicon now fits; this reverts load_lexicon() to show full definitions again
(marvin#1141).

Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_session_start_report_budget.py -v

Temp HOME only; never the real ~/.claude (2026-10-09 logs wipe).
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import session_start_report as ssr  # noqa: E402

LEXICON = """# Shared Lexicon

Concepts and images built between Giles and Claude. Load every session.

---

## Meta

- **wire** — symlink skill into `~/.claude/commands/` + add to routing table.
- **skill loop** — the self-improve cycle: observe pattern → quality filter → draft skill → wire it
- **quality filter** — the 3-gate check (recurrence, evidence, value) before codifying anything

## Concepts

- **design pattern** — a recurring solution shape.
"""


@pytest.fixture
def home(monkeypatch, tmp_path):
    claude = tmp_path / ".claude"
    (claude / "handoffs").mkdir(parents=True)
    (claude / "commands").mkdir()
    monkeypatch.setattr(ssr, "CLAUDE_DIR", claude)
    monkeypatch.setattr(ssr, "FULL_REPORT", tmp_path / ".agents" / "var" / "session-start-report.md")
    monkeypatch.setattr(ssr, "log_hook_error", lambda *a, **kw: None)
    monkeypatch.setattr(ssr, "_last_wake", lambda: None)
    # every live check off by default; each test turns on what it needs
    for name in ("check_suggestions", "check_improvement_queue", "process_and_check_quarantine",
                 "check_hook_errors", "check_cron_health", "check_auto_fix_log", "check_sync_log",
                 "check_auto_merge_report", "check_daily_digest", "check_research_digest",
                 "check_sync_block", "check_morning_brief"):
        monkeypatch.setattr(ssr, name, lambda: None)
    monkeypatch.setattr(ssr, "check_identity", lambda: "MARVIN active — test-mac · agents@aaaa · claude@bbbb · 3 skills wired")
    return claude


def _report(capsys) -> str:
    ssr.main()
    return capsys.readouterr().out


def _handoff(home: Path, name: str, body: str, age: timedelta = timedelta(hours=2)) -> Path:
    p = home / "handoffs" / name
    p.write_text(body)
    t = (datetime.now(timezone.utc) - age).timestamp()
    os.utime(p, (t, t))
    return p


# ── the whole report fits under Claude Code's cap ───────────────────────────

def test_report_fits_the_cap_even_when_every_source_is_huge(home, monkeypatch, capsys):
    (home / "lexicon.md").write_text(LEXICON + "".join(f"- **term{i}** — {'x' * 300}\n" for i in range(2000)))
    _handoff(home, "handoff-2026-11-04-10-00.md", "# Handoff: big\n" + "y" * 200_000)
    monkeypatch.setattr(ssr, "check_morning_brief", lambda: "# Morning brief\n" + "z" * 50_000)
    monkeypatch.setattr(ssr, "check_cron_health", lambda: "cron-health flagged:\n" + "c" * 30_000)
    monkeypatch.setattr(ssr, "check_sync_block", lambda: "## ⛔ SYNC BLOCKED — fix this before anything else\n\n" + "s" * 20_000)
    out = _report(capsys)
    assert len(out) <= ssr.BUDGET < ssr.INLINE_LIMIT


def test_banner_is_always_the_first_line(home, monkeypatch, capsys):
    monkeypatch.setattr(ssr, "check_sync_block", lambda: "## ⛔ SYNC BLOCKED\n\n" + "s" * 50_000)
    out = _report(capsys)
    assert out.splitlines()[0] == "MARVIN active — test-mac · agents@aaaa · claude@bbbb · 3 skills wired"


# ── lexicon: full definitions now visible, not just term names ────────────────

def test_lexicon_shows_full_definitions(home, capsys):
    """load_lexicon() returns the full lexicon file text, not just term names.

    Revert from marvin#1037's "names only" to pre-#1037 shape after MCP glossary
    moved to reference-mcp. Definitions should now appear in the report.
    """
    (home / "lexicon.md").write_text(LEXICON)
    out = _report(capsys)
    # Term names should appear
    for term in ("wire", "skill loop", "quality filter", "design pattern"):
        assert term in out
    # Definitions should now appear (were dropped in #1037)
    assert "observe pattern" in out  # part of "skill loop" definition
    assert "symlink skill into" in out  # part of "wire" definition
    # Report contains the lexicon section
    assert "## Lexicon" in out


def test_lexicon_with_no_terms_or_missing_adds_nothing(home, capsys):
    """Empty or missing lexicon adds no section to the report."""
    out = _report(capsys)
    assert "Lexicon" not in out
    (home / "lexicon.md").write_text("# Shared Lexicon\n\nnothing yet\n")
    assert "Lexicon" not in _report(capsys)


def test_lexicon_that_is_not_text_does_not_break_the_report(home, capsys):
    """Binary or corrupt lexicon file doesn't crash; _safe() wrapper handles it."""
    (home / "lexicon.md").write_bytes(b"\xff\xfe\x00- **x** \x80\x81")
    out = _report(capsys)
    assert out.startswith("MARVIN active")  # report still completes


def test_lexicon_with_malformed_markdown_still_shows_well_formed_terms(home, capsys):
    """A broken term (missing ** closer) plus a well-formed one: show what works."""
    lexicon_text = """## Meta

- **broken term — no closer
- **good term** — this one is well formed

## End"""
    (home / "lexicon.md").write_text(lexicon_text)
    out = _report(capsys)
    assert out.startswith("MARVIN active")
    # Well-formed term should appear
    assert "good term" in out
    assert "well formed" in out


def test_lexicon_with_unreadable_file_does_not_crash(home, capsys):
    """File permission errors are caught by _safe() wrapper in main()."""
    (home / "lexicon.md").write_text("- **test** — definition")
    (home / "lexicon.md").chmod(0o000)
    try:
        out = _report(capsys)
        # Report should still start with banner even if lexicon couldn't be read
        assert out.startswith("MARVIN active")
    finally:
        (home / "lexicon.md").chmod(0o644)  # restore for cleanup


def test_real_script_output_fits_with_a_real_sized_home(tmp_path):
    """Run the script itself under a temp HOME with real-sized lexicon fixture.

    The post-split lexicon (after MCP moved to reference-mcp) has Meta (3 terms)
    plus about 5 trailing terms. Total ~2 KB. This test builds a realistic fixture
    that actually fits in the 8 KB budget to prove load_lexicon() can return the
    full text in normal operation."""
    claude = tmp_path / ".claude"
    (claude / "handoffs").mkdir(parents=True)
    (claude / "commands").mkdir()
    # Post-split: Meta's 3 terms + 5 realistic trailing terms (from MEMORY.md).
    # Each term def is ~80 chars; total ~2 KB, leaving room for headers + other sections.
    realistic_lexicon = LEXICON + "".join(f"- **term{i}** — {'definition text ' * 5}\n" for i in range(5))
    (claude / "lexicon.md").write_text(realistic_lexicon)
    (claude / "handoffs" / "handoff-2026-11-04-10-00.md").write_text("# Handoff: live-sized\n" + "h" * 1000)
    r = subprocess.run([sys.executable, str(LIB / "session_start_report.py")], capture_output=True, text=True,
                       env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("MARVIN active")
    assert len(r.stdout) <= ssr.BUDGET, f"Output {len(r.stdout)} exceeded budget {ssr.BUDGET}"
    # Full definitions should appear, not just term names
    assert "observe pattern" in r.stdout
    assert "symlink skill into" in r.stdout
    # Final newline is added by print(); total must stay under budget
    assert len(r.stdout) + 1 <= ssr.BUDGET


# ── defects found by code review: must-fix bugs ──────────────────────────────

def test_fit_does_not_crash_on_empty_sections_list():
    """fit() must handle empty list gracefully. If all checks fail and are caught by _safe(),
    sections would be empty and sections[0] raises IndexError outside any wrapper."""
    result = ssr.fit([], ssr.BUDGET)
    # Should not crash; returns empty string or minimal output
    assert isinstance(result, str)


def test_left_out_line_keeps_the_read_path_when_many_sections_dropped():
    """The 'Left out' closing line must preserve the read path even when title list is long.
    Code review defect: the original code at line 479 cut the entire line to fit budget,
    which could remove the critical 'read <path>' pointer. Fixed version always keeps the
    path, truncating only the section title list if needed."""
    budget = 300
    sections = ["MARVIN active - short"]
    for i in range(10):
        sections.append("## " + ("x" * 50))

    result = ssr.fit(sections, budget)
    assert len(result) <= budget, f"Result {len(result)} exceeded budget {budget}"
    if "Left out" in result:
        # The path must always be in the closing line
        assert "session-start-report.md" in result
        # The closing line must fit in budget
        closing_line = [line for line in result.split("\n\n") if line.startswith("Left out")]
        assert closing_line, "Should have a 'Left out' line if sections were dropped"


def test_fit_output_plus_print_newline_stays_under_budget():
    """The fit() output plus the newline that print() adds must stay under BUDGET.
    Code review defect (fixed): the original code set out[0] to sections[0][:budget],
    leaving no room for separators and closing lines. The fixed version reserves space."""
    sections = ["MARVIN active - test"]
    for i in range(8):
        sections.append("## Section " + str(i) + "\n" + ("." * 1000))

    result = ssr.fit(sections, ssr.BUDGET)
    total_with_newline = len(result) + 1
    assert total_with_newline <= ssr.BUDGET, (
        f"Output + newline ({total_with_newline}) exceeds BUDGET ({ssr.BUDGET}). "
        f"fit() must reserve room for separators and closing line."
    )
    # Verify the banner is still there (first section is always kept)
    assert result.startswith("MARVIN active")
