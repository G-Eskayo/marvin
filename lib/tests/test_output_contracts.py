"""Output contracts (marvin#305, ADR 0059): every producer's output gets a consumer in time, or Health says so."""
from datetime import datetime, timezone

import output_contracts as oc

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)

SUGGESTIONS = """# Suggestions

## Use the classifier everywhere
**Priority**: 9
**Status**: pending
**Why**: x
**Added**: 2026-09-01

## Fix the sync log
**Priority**: 8
**Status**: resolved 2026-09-20
**Added**: 2026-08-13

## Newer idea
**Priority**: 5
**Status**: pending
**Added**: 2026-10-05
"""


def test_suggestions_pending_and_consumed_dates_are_read():
    pending, consumed = oc.suggestions_state(SUGGESTIONS)
    assert [d.date().isoformat() for d in pending] == ["2026-09-01", "2026-10-05"]
    assert [d.date().isoformat() for d in consumed] == ["2026-09-20"]


def _contract(pending, consumed, within=14, measured=True):
    return oc.Contract("architecture-review", "suggestions.md", "ticket promotion", within,
                       state=(lambda: (pending, consumed)) if measured else None)


def d(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def test_overdue_output_is_yellow_with_the_oldest_age():
    f = oc.evaluate(_contract([d("2026-09-01"), d("2026-10-05")], [d("2026-10-01")]), NOW)
    assert f["severity"] == "yellow" and "1 item" in f["detail"] and "37 days" in f["detail"]


def test_a_producer_nobody_consumed_for_30_days_is_a_removal_candidate():
    f = oc.evaluate(_contract([d("2026-09-01")], [d("2026-08-20")]), NOW)
    assert f["severity"] == "red" and "removal candidate" in f["detail"]
    never = oc.evaluate(_contract([d("2026-09-01")], []), NOW)
    assert never["severity"] == "red" and "never" in never["detail"]


def test_a_consumed_up_to_date_producer_is_green():
    assert oc.evaluate(_contract([d("2026-10-05")], [d("2026-10-06")]), NOW)["severity"] == "green"


def test_an_unmeasured_contract_says_who_will_consume_it():
    c = oc.Contract("daily-digest", "digest/*.md", "the morning brief (#306)", 1, state=None)
    f = oc.evaluate(c, NOW)
    assert f["severity"] == "yellow" and "not measured" in f["detail"] and "morning brief" in f["detail"]


def test_every_producer_has_a_contract():
    names = {c.producer for c in oc.CONTRACTS}
    assert {"architecture-review", "improvement-sweep", "safety-monitor", "daily-digest", "research-digest",
            "morning-brief"} <= names


def test_promotion_takes_the_top_pending_suggestions_up_to_the_cap_and_records_the_decision():
    decisions = iter([{"promoted": True, "ticket_ref": "https://github.com/G-Eskayo/marvin/issues/400", "reasoning": "r"},
                      {"promoted": False, "ticket_ref": None, "reasoning": "one-off"}])
    seen = []
    text = oc.promote_pending(SUGGESTIONS, NOW, limit=2, promote=lambda finding: seen.append(finding) or next(decisions))
    assert len(seen) == 2 and seen[0].startswith("## Use the classifier everywhere")
    assert "**Status**: promoted 2026-10-08 https://github.com/G-Eskayo/marvin/issues/400" in text
    assert "**Status**: declined 2026-10-08 (one-off)" in text
    assert "**Status**: resolved 2026-09-20" in text  # untouched


def test_a_promotion_that_made_no_ticket_stays_pending_and_a_finished_one_is_resolved():
    decisions = iter([{"promoted": True, "ticket_ref": None, "reasoning": "r"},
                      {"promoted": True, "ticket_ref": "NOTHING_LEFT", "reasoning": "r"}])
    text = oc.promote_pending(SUGGESTIONS, NOW, limit=2, promote=lambda finding: next(decisions))
    assert text.count("**Status**: pending") == 1
    assert "**Status**: resolved 2026-10-08 (ticket promotion: its own updates say nothing remains)" in text


def test_a_digest_is_consumed_by_that_days_brief_and_a_brief_by_being_read(tmp_path, monkeypatch):
    import morning_brief
    monkeypatch.setattr(oc, "CLAUDE", tmp_path)
    monkeypatch.setattr(morning_brief, "BRIEFS", tmp_path / "briefs")
    (tmp_path / "daily-digest").mkdir()
    for day in ("2026-10-06", "2026-10-07", "2026-10-07-merged"):
        (tmp_path / "daily-digest" / f"{day}.md").write_text("x")
    (tmp_path / "briefs").mkdir()
    (tmp_path / "briefs" / "2026-10-07.md").write_text("brief")
    pending, consumed = oc._digest("daily-digest")()
    assert [d.date().isoformat() for d in pending] == ["2026-10-06"]
    assert [d.date().isoformat() for d in consumed] == ["2026-10-07"]
    assert [d.date().isoformat() for d in oc._brief()[0]] == ["2026-10-07"]
    (tmp_path / "briefs" / "2026-10-07.read").write_text("now")
    assert oc._brief()[0] == []


# ── after the move to the inbox (ADR 0083): the same contracts, read from the pile ─────────────────────────────

import inbox  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture
def piles(tmp_path, monkeypatch):
    """A temp ~/.claude with the legacy files beside an inbox root; nothing imported yet."""
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "suggestions.md").write_text(SUGGESTIONS)
    monkeypatch.setattr(inbox, "default_root", lambda: claude / "inbox")
    monkeypatch.setattr(oc, "SUGGESTIONS", claude / "suggestions.md")
    monkeypatch.setattr(oc, "QUEUE", claude / "improvement-queue.md")
    monkeypatch.setattr(oc, "AUTO_FIX_LOG", claude / "auto-fix-log.md")
    return claude


def test_before_the_import_the_contracts_read_the_old_file(piles):
    assert [d.date().isoformat() for d in oc._suggestions()[0]] == ["2026-09-01", "2026-10-05"]
    assert not inbox.pile_exists("suggestions")  # reading never makes the pile


def test_after_the_import_the_contracts_read_the_inbox(piles):
    inbox.import_legacy("suggestions")
    (piles / "suggestions.md").write_text("")  # proves the old file is no longer read
    pending, consumed = oc._suggestions()
    assert sorted(d.date().isoformat() for d in pending) == ["2026-09-01", "2026-10-05"]
    assert [d.date().isoformat() for d in consumed] == ["2026-09-20"]


def test_the_queue_contract_counts_open_items_not_sections(piles):
    (piles / "improvement-queue.md").write_text(
        "## 2026-07-01 — marvin\n- **[NAMING]** a (`x.py`)\n- **[NAMING]** b (`x.py`) — auto-fix: done, PR #1 merged\n"
        "## 2026-07-02 — marvin\n- **[NAMING]** a (`x.py`)\n")
    assert len(oc._queue()[0]) == 2  # the old reader: one per dated section
    inbox.import_legacy("improvement-queue")
    assert [d.date().isoformat() for d in oc._queue()[0]] == ["2026-07-01"]  # one open item, its first day


def test_promotion_from_the_inbox_takes_the_top_open_items_in_priority_order_and_records_each(piles):
    inbox.import_legacy("suggestions")
    decisions = iter([{"promoted": True, "ticket_ref": "https://github.com/G-Eskayo/marvin/issues/400", "reasoning": "r"},
                      {"promoted": False, "ticket_ref": None, "reasoning": "one-off\n  really"}])
    seen = []
    tried = oc.promote_inbox(NOW, limit=2, promote=lambda f: seen.append(f) or next(decisions))
    assert tried == 2 and seen[0].startswith("## Use the classifier everywhere\n**Priority**: 9\n**Status**: pending")
    assert seen[1].startswith("## Newer idea")
    by_title = {i["title"]: i for i in inbox.list_items("suggestions")["items"]}
    assert by_title["Use the classifier everywhere"]["status"] == {
        "state": "promoted", "on": "2026-10-08", "note": "https://github.com/G-Eskayo/marvin/issues/400"}
    assert by_title["Newer idea"]["status"] == {"state": "declined", "on": "2026-10-08", "note": "(one-off really)"}
    assert (piles / "suggestions.md").read_text() == SUGGESTIONS  # the old file stays a read-only backup
    assert oc.promote_inbox(NOW, limit=2, promote=lambda f: pytest.fail("nothing is left to promote")) == 0


def test_a_promotion_with_no_ticket_stays_open_in_the_inbox(piles):
    inbox.import_legacy("suggestions")
    oc.promote_inbox(NOW, limit=1, promote=lambda f: {"promoted": True, "ticket_ref": None, "reasoning": "r"})
    assert len(inbox.open_items("suggestions")) == 2


def test_run_promotion_switches_to_the_inbox_once_it_exists(piles, monkeypatch):
    calls = []
    monkeypatch.setattr(oc, "_default_promote", lambda: lambda f: calls.append(f) or {"promoted": False, "reasoning": "n"})
    inbox.import_legacy("suggestions")
    oc.run_promotion(NOW)
    assert len(calls) == 2 and (piles / "suggestions.md").read_text() == SUGGESTIONS
    assert len(inbox.open_items("suggestions")) == 0
