"""marvin#1037: the session-start report must reach the model whole.

Claude Code caps hook stdout at 10,000 characters. Over that, it saves the output to a file and puts only the
file path plus the first 2,000 characters in context, and it never tells Claude to read the file (hooks
reference, "Over the limit"). The report was 12.8-15.4 KB, so every session since the lexicon was added saw the
banner, the checklist and a sliver of the lexicon; the rest of the lexicon and the whole handoff never arrived.
Bench Run 31's transcripts show exactly that preview. Run via:
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

## MCP (Model Context Protocol)

- **MCP** — open protocol for connecting AI applications to external systems.
- **tool (MCP)** — model-controlled executable function.
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


def test_a_cut_section_says_so_and_where_the_rest_is(home, monkeypatch, capsys):
    monkeypatch.setattr(ssr, "check_morning_brief", lambda: "# Morning brief\n" + "line\n" * 20_000)
    out = _report(capsys)
    assert "## Morning brief" in out
    assert "cut to fit" in out
    assert str(ssr.FULL_REPORT) in out


def test_the_full_report_is_saved_whole_for_whatever_was_cut(home, monkeypatch, capsys):
    brief = "# Morning brief\n" + "".join(f"brief line {i}\n" for i in range(5000))
    monkeypatch.setattr(ssr, "check_morning_brief", lambda: brief)
    _report(capsys)
    saved = ssr.FULL_REPORT.read_text()
    assert "brief line 4999" in saved


def test_sync_block_is_never_pushed_out_by_bulk_below_it(home, monkeypatch, capsys):
    monkeypatch.setattr(ssr, "check_sync_block", lambda: "## ⛔ SYNC BLOCKED — fix this before anything else\n\nfix me")
    monkeypatch.setattr(ssr, "check_morning_brief", lambda: "# Morning brief\n" + "z" * 50_000)
    out = _report(capsys)
    assert "SYNC BLOCKED" in out and "fix me" in out
    assert out.index("SYNC BLOCKED") < out.index("Morning brief")


def test_checklist_notes_survive_a_huge_morning_brief(home, monkeypatch, capsys):
    monkeypatch.setattr(ssr, "check_improvement_queue", lambda: "207 item(s) queued in improvement-queue.md")
    monkeypatch.setattr(ssr, "check_morning_brief", lambda: "# Morning brief\n" + "z\n" * 50_000)
    out = _report(capsys)
    assert "207 item(s) queued" in out


# ── lexicon: every term named, definitions on demand ────────────────────────

def test_lexicon_lists_every_term_and_where_the_definitions_are(home, capsys):
    (home / "lexicon.md").write_text(LEXICON)
    out = _report(capsys)
    for term in ("wire", "skill loop", "quality filter", "MCP", "tool (MCP)"):
        assert term in out
    assert "lexicon.md" in out
    assert "observe pattern" not in out  # definitions are read on demand, not pasted every session


def test_lexicon_with_no_terms_or_missing_adds_nothing(home, capsys):
    out = _report(capsys)
    assert "Lexicon" not in out
    (home / "lexicon.md").write_text("# Shared Lexicon\n\nnothing yet\n")
    assert "Lexicon" not in _report(capsys)


def test_lexicon_that_is_not_text_does_not_break_the_report(home, capsys):
    (home / "lexicon.md").write_bytes(b"\xff\xfe\x00- **x** \x80\x81")
    out = _report(capsys)
    assert out.startswith("MARVIN active")


# ── handoff: a pointer, not the body ────────────────────────────────────────

def test_handoff_is_a_pointer_with_its_title_and_age(home, capsys):
    _handoff(home, "handoff-2026-11-03-17-30.md",
             "# Handoff 2026-11-03 17:30: WezTerm x dashboard\n\n## State\nsecret detail " + "d" * 5000,
             age=timedelta(days=1, hours=1))
    out = _report(capsys)
    assert "handoff-2026-11-03-17-30.md" in out
    assert "WezTerm x dashboard" in out
    assert "1d old" in out
    assert "secret detail" not in out


def test_handoff_older_than_a_week_is_not_shown(home, capsys):
    _handoff(home, "handoff-old.md", "# Handoff: old\n", age=timedelta(days=8))
    assert "handoff-old" not in _report(capsys)


def test_handoff_without_a_heading_still_points_at_the_file(home, capsys):
    _handoff(home, "handoff-x.md", "")
    assert "handoff-x.md" in _report(capsys)


# ── same state, same bytes ──────────────────────────────────────────────────

def test_same_state_gives_byte_identical_reports(home, capsys):
    (home / "lexicon.md").write_text(LEXICON)
    _handoff(home, "handoff-a.md", "# Handoff: a\n")
    assert _report(capsys) == _report(capsys)


def test_unwritable_full_report_path_still_prints_the_report(home, monkeypatch, capsys, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    monkeypatch.setattr(ssr, "FULL_REPORT", blocker / "x" / "report.md")
    monkeypatch.setattr(ssr, "check_morning_brief", lambda: "# Morning brief\n" + "z" * 50_000)
    out = _report(capsys)
    assert out.startswith("MARVIN active") and len(out) <= ssr.BUDGET


# ── the real script, as the hook runs it ────────────────────────────────────

def test_real_script_output_fits_with_a_real_sized_home(tmp_path):
    """Run the script itself under a temp HOME holding a lexicon and handoff the size of the live ones."""
    claude = tmp_path / ".claude"
    (claude / "handoffs").mkdir(parents=True)
    (claude / "commands").mkdir()
    (claude / "lexicon.md").write_text(LEXICON + "".join(f"- **t{i}** — {'d' * 150}\n" for i in range(60)))
    (claude / "handoffs" / "handoff-2026-11-04-10-00.md").write_text("# Handoff: live-sized\n" + "h" * 4000)
    r = subprocess.run([sys.executable, str(LIB / "session_start_report.py")], capture_output=True, text=True,
                       env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("MARVIN active")
    assert len(r.stdout) <= ssr.BUDGET
    assert "t59" in r.stdout and "live-sized" in r.stdout
