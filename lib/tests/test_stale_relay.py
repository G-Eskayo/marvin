"""stale-relay probe (marvin#1224): caught vs leaked stale claims, per Mac, per week. Piece 4 of
instance/docs/plans/data-freshness-2026-11-09.md: it proves the resume check (#1221) and its siblings work.

  caught   distinct (handoff, item) pairs the resume check found changed (~/.agents/var/resume-checks.jsonl)
  leaked   question-log entries with kind=stale, plus Gil's own replies correcting a relayed claim
           ("that's already fixed", "this is old") in this Mac's interactive transcripts

Tests try to break it (ADR 0063): Gil quoting an old message (not a correction), "already done" said about a new
task, a pasted document, the same transcript copied on two Macs (no double count), a week with no sessions (unknown,
not 0), a garbled log, an unreachable Mac. Temp dirs only.

    ~/.agents/venv/bin/python -m pytest lib/tests/test_stale_relay.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import question_log as ql  # noqa: E402
import stale_relay as sr  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def ts(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def user(text, days_ago=1.0, uuid=None, entrypoint="cli", **extra):
    return {"type": "user", "entrypoint": entrypoint, "timestamp": ts(days_ago), "uuid": uuid or f"u{abs(hash(text))}",
            "message": {"role": "user", "content": text}, **extra}


def transcript(root: Path, name: str, rows: list[dict]) -> Path:
    p = root / "proj" / f"{name}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return p


@pytest.fixture
def env(tmp_path):
    return {"transcripts": tmp_path / "projects", "resume_log": tmp_path / "var" / "resume-checks.jsonl",
            "question_log": tmp_path / "var" / "question-log.jsonl", "cache": tmp_path / "var" / "stale-relay.json"}


def week(env, **kw):
    return sr.week(now=NOW, machine="macbook-pro-1", **env, **kw)


# ── what counts as a correction ──────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "11 looks like it's already been done, so that's a deprecated ticket",
    "that's already fixed",
    "This was already merged yesterday.",
    "that is already restored, the media came back on the 4th",
    "this is old",
    "That's out of date.",
])
def test_corrections_are_counted(text):
    assert sr.is_correction(text)


@pytest.mark.parametrize("text", [
    "I've already done the design, now build the settings page",       # "already done" about a new task
    "we already merged the plan; next is the tickets",
    "> that's already fixed\nwhat about the second one?",               # quoting an old message
    'you said "that is already fixed" last week, is that true?',        # quoting, in quotes
    "the pages are out of date, please redo them",                     # not about a relayed claim
    "the `stale` flag is set",
    "x" * 900 + " that's already fixed",                               # a pasted document, not a reply
    "<command-name>/x</command-name> that's already fixed",             # system text
])
def test_non_corrections_are_not_counted(text):
    assert not sr.is_correction(text)


# ── the week ─────────────────────────────────────────────────────────────────

def test_a_week_counts_caught_and_both_kinds_of_leaked(env):
    env["resume_log"].parent.mkdir(parents=True)
    rows = [{"at": ts(1), "handoff": "h1.md", "changed_keys": ["G-Eskayo/x#17", "G-Eskayo/marvin#5"]},
            {"at": ts(0.5), "handoff": "h1.md", "changed_keys": ["G-Eskayo/x#17"]},   # same handoff checked again
            {"at": ts(2), "handoff": "h2.md", "changed_keys": ["G-Eskayo/x#17"]},
            {"at": ts(9), "handoff": "h0.md", "changed_keys": ["G-Eskayo/old#1"]}]     # outside the week
    env["resume_log"].write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    ql.add("Why did you say #17 was urgent?", kind="stale", path=env["question_log"])
    ql.add("Where is the build running?", path=env["question_log"])
    transcript(env["transcripts"], "s1", [user("that's already fixed", 1), user("ok go on", 0.9)])
    w = week(env)
    assert w["caught"] == 3 and w["logged"] == 1 and w["said"] == 1 and w["leaked"] == 2
    assert w["sessions"] == 1 and w["known"] is True and w["machine"] == "macbook-pro-1"


def test_a_week_with_no_sessions_is_unknown_not_zero(env):
    transcript(env["transcripts"], "old", [user("hello", 20)])
    w = week(env)
    assert w["known"] is False and w["sessions"] == 0


def test_headless_runs_and_subagents_are_not_gils_replies(env):
    transcript(env["transcripts"], "s", [user("that's already fixed", 1, entrypoint="sdk-cli"),
                                         user("that's already fixed", 1, uuid="side", isSidechain=True),
                                         user("hi", 1)])
    assert week(env)["said"] == 0


def test_tool_results_are_not_replies(env):
    transcript(env["transcripts"], "s", [
        {"type": "user", "entrypoint": "cli", "timestamp": ts(1), "uuid": "t1",
         "message": {"content": [{"type": "tool_result", "content": "that's already fixed"}]}},
        user("hi", 1)])
    assert week(env)["said"] == 0


def test_the_same_transcript_on_two_macs_counts_once(env):
    rows = [user("that's already fixed", 1, uuid="same-uuid")]
    transcript(env["transcripts"], "s", rows)
    transcript(env["transcripts"] / "copy", "s", rows)  # a copy (another Mac's sync, a backup) of the same messages
    assert week(env)["said"] == 1


def test_an_unchanged_transcript_is_not_reread(env, monkeypatch):
    transcript(env["transcripts"], "s", [user("that's already fixed", 1)])
    assert week(env)["said"] == 1
    calls = []
    real = sr._scan
    monkeypatch.setattr(sr, "_scan", lambda p: calls.append(p) or real(p))
    assert week(env)["said"] == 1 and calls == [], "the cache answers for a file whose size and mtime didn't change"


def test_a_garbled_cache_or_log_never_raises(env):
    env["cache"].parent.mkdir(parents=True)
    env["cache"].write_text("{nope")
    env["resume_log"].write_text("\x00\x01garbage\n{\"at\": 5}\n")
    transcript(env["transcripts"], "s", [user("hi", 1)])
    w = week(env)
    assert w["caught"] == 0 and w["known"] is True


# ── question log kind ────────────────────────────────────────────────────────

def test_question_log_kind_stale_and_top_filter(tmp_path):
    p = tmp_path / "q.jsonl"
    ql.add("Why was #17 urgent?", kind="stale", path=p)
    ql.add("Why was #17 urgent?", kind="stale", path=p)
    ql.add("Where is it running?", path=p)
    assert [r["question"] for r in ql.top(path=p, kind="stale")] == ["Why was #17 urgent?"]
    assert ql.top(path=p, kind="stale")[0]["count"] == 2
    assert len(ql.top(path=p)) == 2


def test_question_log_refuses_a_made_up_kind(tmp_path):
    with pytest.raises(ValueError):
        ql.add("q", kind="DROP TABLE", path=tmp_path / "q.jsonl")


def test_question_log_cli_takes_kind(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert ql.main(["add", "Why #17?", "--kind", "stale"]) == 0
    assert ql.main(["top", "--kind", "stale"]) == 0
    assert "Why #17?" in capsys.readouterr().out


# ── the Vitals row ───────────────────────────────────────────────────────────

def test_the_row_says_caught_vs_leaked_per_mac():
    per = [{"machine": "macbook-pro-1", "caught": 3, "leaked": 1, "logged": 0, "said": 1, "sessions": 4, "known": True},
           {"machine": "mac-mini-1", "caught": 0, "leaked": 0, "logged": 0, "said": 0, "sessions": 0, "known": False}]
    row = sr.row(per, now=NOW)
    assert row["id"] == "freshness:stale-relay" and row["severity"] == "yellow"
    assert "caught 3, leaked 1" in row["detail"]
    assert "macbook-pro-1: caught 3, leaked 1" in row["detail"] and "mac-mini-1: unknown (no sessions)" in row["detail"]


def test_no_leaks_is_green_and_all_unknown_is_unknown():
    ok = [{"machine": "a", "caught": 2, "leaked": 0, "logged": 0, "said": 0, "sessions": 3, "known": True}]
    assert sr.row(ok, now=NOW)["severity"] == "green"
    none = [{"machine": "a", "known": False, "sessions": 0}, {"machine": "b", "known": False, "error": "unreachable"}]
    r = sr.row(none, now=NOW)
    assert r["severity"] == "unknown" and "b: unknown (unreachable)" in r["detail"]


def test_an_unreachable_mac_is_unknown_not_a_crash(env):
    def remote(host):
        raise subprocess.TimeoutExpired("ssh", 30)

    per = sr.everywhere(now=NOW, macs=[("mac-mini-1", "mini")], remote=remote, local=lambda: {"machine": "me",
                        "caught": 0, "leaked": 0, "logged": 0, "said": 0, "sessions": 1, "known": True})
    assert per[1] == {"machine": "mac-mini-1", "known": False, "error": "unreachable (TimeoutExpired)"}


def test_a_remote_reply_that_isnt_a_week_is_unknown(env):
    per = sr.everywhere(now=NOW, macs=[("m", "h")], remote=lambda h: "rm -rf /", local=lambda: {"machine": "me",
                        "known": False, "sessions": 0})
    assert per[1]["known"] is False and "unreadable" in per[1]["error"]


def test_the_probe_is_registered_with_a_zero_limit_and_unknown_raises():
    import purpose_metrics as pm
    assert pm.PROBES["stale-relay-leaked"][1] == 0.0 and "stale-relay-caught" in pm.MEASURES


def test_the_health_row_marks_an_asleep_mac_unknown_without_asking_it(monkeypatch):
    import health_checks as hc
    import purpose_metrics as pm
    asked = []
    monkeypatch.setattr(pm, "_macs", lambda only=None: iter([("mac-mini-1", "mini")]))
    monkeypatch.setattr(sr, "everywhere", lambda macs=None, **k: asked.append(macs) or [
        {"machine": "me", "caught": 1, "leaked": 0, "logged": 0, "said": 0, "sessions": 2, "known": True}])
    r = hc.check_stale_relay({"machine:mac-mini-1": "grey"})
    assert asked == [[]] and "mac-mini-1: unknown (asleep)" in r["detail"] and r["severity"] == "green"
