"""North-star fit checks on PRs (marvin#276): deterministic facts against the ticket's stated fit; a Judge only on flags."""
import json
import subprocess
from pathlib import Path

import fit_check as fc

BODY = """## What to build
Thing.

## North-star fit
Reuses the launcher; one small module; no new tokens at run time.

## Acceptance criteria
- [ ] it works
"""


def test_the_fit_section_is_read_from_the_ticket():
    assert fc.fit_section(BODY).startswith("Reuses the launcher")
    assert fc.fit_section("## What to build\nx") is None


def test_test_files_are_recognised_across_the_projects_languages():
    for path in ("lib/tests/test_x.py", "dashboard/test/a.test.js", "Packages/Core/Tests/CoreTests/AppTests.swift"):
        assert fc.is_test(path), path
    assert not fc.is_test("lib/fit_check.py")


def _facts(**kw):
    base = {"new_files": [], "new_source_files": [], "lines_added": 40, "lines_removed": 10,
            "source_files_changed": 1, "test_files_changed": 1}
    return {**base, **kw}


def test_a_small_tested_change_with_a_stated_fit_passes_every_check():
    checks = fc.run_checks(_facts(), "Reuses X.", cost_usd=0.4)
    assert all(c["ok"] for c in checks)


def test_each_fact_flags_what_contradicts_a_lean_fit():
    flagged = {c["name"] for c in fc.run_checks(
        _facts(new_source_files=["a.py", "b.py", "c.py"], lines_added=900, test_files_changed=0), None, cost_usd=9.0)
        if not c["ok"]}
    assert flagged == {"North-star fit stated", "Reuse before adding", "Simplest sufficient", "Tested", "Token cost"}


def test_the_report_marks_each_check():
    text = fc.render(fc.run_checks(_facts(test_files_changed=0), "x", 0.1))
    assert "| ✅ | North-star fit stated" in text and "| ⚠️ | Tested" in text


def test_ticket_cost_sums_this_tickets_launches(tmp_path):
    log = tmp_path / "launches.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in [
        {"ticket": "G-Eskayo/marvin#5", "cost_usd": 0.5}, {"ticket": "G-Eskayo/marvin#5", "cost_usd": 0.25},
        {"ticket": "G-Eskayo/marvin#6", "cost_usd": 9}]) + "\nnot json\n")
    assert fc.ticket_cost("G-Eskayo/marvin#5", log) == 0.75


def test_diff_facts_come_from_git(tmp_path):
    git = lambda *a: subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                    check=True, capture_output=True, text=True)
    git("init", "-q", "-b", "main")
    (tmp_path / "a.py").write_text("x = 1\n")
    git("add", "."); git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD").stdout.strip()
    (tmp_path / "a.py").write_text("x = 2\ny = 3\n")
    (tmp_path / "b.py").write_text("z = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_b.py").write_text("def test(): pass\n")
    git("add", "."); git("commit", "-qm", "work")
    facts = fc.diff_facts(tmp_path, base)
    assert facts["new_source_files"] == ["b.py"]
    assert facts["test_files_changed"] == 1 and facts["source_files_changed"] == 2
    assert (facts["lines_added"], facts["lines_removed"]) == (4, 1)


def test_the_judge_runs_only_when_something_is_flagged():
    launched = []
    judge = lambda prompt: launched.append(prompt) or "VERDICT: fits"
    assert fc.judge_if_flagged(fc.run_checks(_facts(), "x", 0.1), "x", _facts(), judge=judge) is None
    assert launched == []
    verdict = fc.judge_if_flagged(fc.run_checks(_facts(test_files_changed=0), "x", 0.1), "x", _facts(), judge=judge)
    assert verdict == "VERDICT: fits" and "Tested" in launched[0]


# ── every fix gets an outcome check (2026-10-26): a warning in the fit check, not a block ─────────────────────

from datetime import datetime, timedelta, timezone  # noqa: E402

LATER = (datetime.now(timezone.utc) + timedelta(days=10)).date().isoformat()
FIX_WITH_CHECK = BODY + f"\n## Recurrence check\n- **Probe:** ticket-planned-3x-in-24h\n- **Check on:** {LATER}\n"


def _outcome_row(body, labels=("bug",), title="Fix the thing"):
    rows = [c for c in fc.run_checks(_facts(), "x", 0.1, outcome=fc.outcome_check(body, title, list(labels)))
            if c["name"] == "Outcome check"]
    return rows[0] if rows else None


def test_a_fix_without_an_outcome_check_is_flagged_as_a_warning():
    row = _outcome_row(BODY)
    assert row and not row["ok"] and "no outcome check" in row["detail"]
    assert "warning" in row["detail"]


def test_a_fix_with_a_valid_outcome_check_passes():
    row = _outcome_row(FIX_WITH_CHECK)
    assert row and row["ok"]


def test_a_conventional_fix_title_counts_as_a_fix_without_the_label():
    assert not _outcome_row(BODY, labels=(), title="fix(gh): stop the storm")["ok"]
    assert _outcome_row(BODY, labels=("enhancement",), title="Add a chart") is None   # not a fix: no row


def test_a_malformed_outcome_check_is_flagged_even_on_a_feature():
    row = _outcome_row(BODY + "\n## Purpose metric\n- **Measure:** nope\n", labels=("enhancement",), title="Add")
    assert row and not row["ok"] and "malformed" in row["detail"]


def test_a_valid_check_without_a_label_the_daily_check_reads_is_flagged():
    row = _outcome_row(BODY + f"\n## Purpose metric\n- **Measure:** github-calls-per-day\n- **Baseline:** 9000\n"
                       f"- **Target:** -30%\n- **Check on:** {LATER}\n", labels=("enhancement",), title="Fewer calls")
    assert row and not row["ok"] and "purpose-metric" in row["detail"]


def test_the_report_reads_the_tickets_labels_without_an_extra_github_call(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(fc, "diff_facts", lambda wt, base="origin/main": _facts())
    monkeypatch.setattr(fc, "ticket_cost", lambda ref: 0.1)
    text = fc.report("G-Eskayo/marvin#5", tmp_path, BODY, judge=lambda p: seen.append(p) or "VERDICT: fits",
                     title="Fix it", labels=["bug"])
    assert "| ⚠️ | Outcome check" in text and seen and "Outcome check" in seen[0]


def test_the_ticket_read_survives_a_bad_gh_answer(monkeypatch):
    answers = iter([
        subprocess.CompletedProcess([], 0, json.dumps({"body": "b", "title": "Fix", "labels": [{"name": "bug"}, "x", None]}), ""),
        subprocess.CompletedProcess([], 0, "not json", ""),
        subprocess.CompletedProcess([], 0, "[1, 2]", ""),
        subprocess.CompletedProcess([], 1, "", "offline"),
    ])
    monkeypatch.setattr(fc.subprocess, "run", lambda *a, **k: next(answers))
    assert fc._ticket("G-Eskayo/marvin#5") == {"body": "b", "title": "Fix", "labels": ["bug"]}
    for _ in range(3):
        assert fc._ticket("G-Eskayo/marvin#5") == {"body": "", "title": "", "labels": []}
