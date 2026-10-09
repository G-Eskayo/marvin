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
