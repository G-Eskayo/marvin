"""lib/session_usage.py: how many tokens the Claude sessions on this machine used, when, by what kind of run, for which project/ticket."""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import session_usage as tu  # noqa: E402

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def line(msg_id, ts="2026-10-05T10:00:00.000Z", inp=2, out=100, cw=1000, cr=5000, model="claude-sonnet-5", entry="cli",
         side=False, cwd="/Users/g/proj", req="req_1", typ="assistant"):
    return json.dumps({"type": typ, "timestamp": ts, "requestId": req, "cwd": cwd, "isSidechain": side, "entrypoint": entry,
                       "message": {"id": msg_id, "model": model, "usage": {"input_tokens": inp, "output_tokens": out,
                                                                           "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr}}})


def write(tmp_path, name, lines):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n")
    return p


def test_one_api_response_split_over_several_transcript_lines_is_counted_once(tmp_path):
    """Claude Code writes one line per content block with the same message id and the same usage: 53 lines were 19 messages."""
    f = write(tmp_path, "a.jsonl", [line("m1", out=100), line("m1", out=100), line("m1", out=100), line("m2", out=50)])
    r = tu.aggregate([f], now=NOW)
    assert r["totals"]["output"] == 150 and r["totals"]["messages"] == 2


def test_a_later_line_of_the_same_message_wins_when_its_usage_grew(tmp_path):
    f = write(tmp_path, "a.jsonl", [line("m1", out=10), line("m1", out=120)])
    assert tu.aggregate([f], now=NOW)["totals"]["output"] == 120


def test_totals_split_into_input_output_and_cache(tmp_path):
    f = write(tmp_path, "a.jsonl", [line("m1", inp=3, out=7, cw=11, cr=13)])
    t = tu.aggregate([f], now=NOW)["totals"]
    assert (t["input"], t["output"], t["cache_write"], t["cache_read"]) == (3, 7, 11, 13)


def test_the_kind_of_run_comes_from_the_entrypoint_and_sidechain_flag(tmp_path):
    f = write(tmp_path, "a.jsonl", [line("a", entry="cli"), line("b", entry="sdk-cli"), line("c", entry="cli", side=True)])
    kinds = {row["kind"] for row in tu.aggregate([f], now=NOW)["rows"]}
    assert kinds == {"interactive", "headless", "subagent"}


def test_rows_are_per_day_kind_and_model_and_old_messages_fall_out_of_the_window(tmp_path):
    f = write(tmp_path, "a.jsonl", [line("a", ts="2026-10-05T10:00:00Z"), line("b", ts="2026-10-05T23:00:00Z", model="claude-opus-5"),
                                    line("old", ts="2026-08-01T10:00:00Z")])
    r = tu.aggregate([f], now=NOW, window_days=30)
    assert {(x["day"], x["model"]) for x in r["rows"]} == {("2026-10-05", "claude-sonnet-5"), ("2026-10-05", "claude-opus-5")}
    assert r["totals"]["messages"] == 2


def test_pipeline_worktrees_are_attributed_to_their_project_and_ticket():
    assert tu.attribute("/Users/g/.agents-pipeline-worktrees/pipeline-g-eskayo-marvin-141") == ("marvin", 141)
    assert tu.attribute("/Users/g/.agents-pipeline-worktrees/pipeline-g-eskayo-clarity-captions-51") == ("clarity-captions", 51)
    assert tu.attribute("/Users/g/.agents-pipeline-worktrees/pipeline-g-eskayo-marvin#28") == ("marvin", 28)       # older '#' directory names
    assert tu.attribute("/Users/g/.agents-pipeline-worktrees/pipeline-g-eskayo-clarity-captions-51/Packages/CaptionCore") == ("clarity-captions", 51)
    assert tu.attribute("/Users/g/Developer/killer-sudoku") == ("killer-sudoku", None)
    assert tu.attribute("/Users/g/Developer/clarity-captions/Packages/CaptionCore") == ("clarity-captions", None)
    assert tu.attribute("/Users/g/Documents/Projects/experiments/anomaly-detection-v2") == ("anomaly-detection-v2", None)
    assert tu.attribute("/Users/g/.agents/lib") == ("marvin", None)
    assert tu.attribute("/Users/g/.agents") == ("marvin", None)
    assert tu.attribute(str(Path.home())) == ("(home)", None)
    assert tu.attribute(None) == ("(unknown)", None)


def test_by_ticket_adds_up_the_runs_for_each_ticket_so_retry_storms_show(tmp_path):
    wt = "/Users/g/.agents-pipeline-worktrees/pipeline-g-eskayo-marvin-9"
    f = write(tmp_path, "a.jsonl", [line("a", cwd=wt, out=100, entry="sdk-cli"), line("b", cwd=wt, out=300, entry="sdk-cli"),
                                    line("c", cwd="/Users/g/.agents", out=40)])
    r = tu.aggregate([f], now=NOW)
    ticket = next(t for t in r["by_ticket"] if t["ticket"] == 9)
    assert ticket["project"] == "marvin" and ticket["output"] == 400 and ticket["messages"] == 2
    assert all(t["ticket"] is not None for t in r["by_ticket"])
    assert next(p for p in r["by_project"] if p["project"] == "marvin")["output"] == 440


def test_lines_that_are_not_assistant_usage_are_ignored(tmp_path):
    f = write(tmp_path, "a.jsonl", ["not json", line("u", typ="user"), json.dumps({"type": "assistant", "message": {"id": "x"}}), line("ok")])
    assert tu.aggregate([f], now=NOW)["totals"]["messages"] == 1


def test_refresh_writes_the_result_with_the_machine_name(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    write(root, "s.jsonl", [line("a", ts="2026-10-05T10:00:00Z")])
    monkeypatch.setattr(tu, "machine_id", lambda: "mac-mini-1")
    import job_events
    monkeypatch.setattr(job_events, "JOBS_DIR", tmp_path / "jobs")
    out = tmp_path / "token-usage.json"
    tu.refresh(out_path=out, root=root, now=NOW)
    data = json.loads(out.read_text())
    assert data["machine"] == "mac-mini-1" and data["totals"]["messages"] == 1


# ── autonomous field and by_job aggregation ──────────────────────────────

def test_autonomous_classification_from_entrypoint(tmp_path):
    """Autonomous = entrypoint not in (None, 'cli'); headless are autonomous, subagents inherit from their parent."""
    f = write(tmp_path, "a.jsonl", [
        line("a", entry="cli"),           # interactive: False
        line("b", entry="sdk-cli"),       # headless: True
        line("c", entry="cli", side=True),  # subagent from interactive: False
        line("e", entry="sdk-cli", side=True),  # subagent from headless: True
        line("d"),  # entrypoint=None (default): False
    ])
    r = tu.aggregate([f], now=NOW)
    rows_by_kind = {row["kind"]: row.get("autonomous") for row in r["rows"] if row["kind"] in ("interactive", "headless", "subagent")}
    assert rows_by_kind.get("interactive") is False
    assert rows_by_kind.get("headless") is True
    # Subagent's autonomy depends on parent entrypoint
    subagent_rows = [row for row in r["rows"] if row["kind"] == "subagent"]
    assert len(subagent_rows) == 2
    assert {row.get("autonomous") for row in subagent_rows} == {True, False}


def test_autonomous_defaults_false_when_entrypoint_missing(tmp_path):
    """A transcript line with no entrypoint key defaults to non-autonomous (matches _kind's None handling)."""
    # Manually construct a line with no entrypoint key
    def line_no_entry(msg_id):
        return json.dumps({"type": "assistant", "timestamp": "2026-10-05T10:00:00.000Z", "requestId": "req_1",
                          "cwd": "/Users/g/proj", "isSidechain": False,  # no entrypoint
                          "message": {"id": msg_id, "model": "claude-sonnet-5", "usage": {"input_tokens": 2, "output_tokens": 100,
                                                                               "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 5000}}})
    f = write(tmp_path, "a.jsonl", [line_no_entry("m1")])
    r = tu.aggregate([f], now=NOW)
    assert r["rows"][0].get("autonomous") is False


def test_by_job_sums_output_tokens_cost_and_runs(tmp_path, monkeypatch):
    """by_job aggregates launches.jsonl by (kind, ticket), summing output_tokens, cost_usd, and run count."""
    launches = tmp_path / "launches.jsonl"
    lines = [
        json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "clarity-captions",
                    "output_tokens": 100, "cost_usd": 0.5}),
        json.dumps({"at": "2026-10-05T11:00:00Z", "kind": "background-analyst", "ticket": "clarity-captions",
                    "output_tokens": 50, "cost_usd": 0.25}),
        json.dumps({"at": "2026-10-05T12:00:00Z", "kind": "background-analyst", "ticket": "marvin",
                    "output_tokens": 200, "cost_usd": 1.0}),
    ]
    launches.write_text("\n".join(lines) + "\n")
    monkeypatch.setattr(tu, "LAUNCHES_LOG", launches)
    r = tu.by_job(window_days=30, now=NOW)
    assert len(r) == 2
    cc = next((j for j in r if j["job"] == "clarity-captions"), None)
    assert cc is not None
    assert cc["output_tokens"] == 150
    assert cc["cost_usd"] == 0.75
    assert cc["runs"] == 2


def test_by_job_missing_launches_log_returns_empty(tmp_path, monkeypatch):
    """Missing launches.jsonl returns [], no crash."""
    monkeypatch.setattr(tu, "LAUNCHES_LOG", tmp_path / "nonexistent.jsonl")
    r = tu.by_job(window_days=30, now=NOW)
    assert r == []


def test_by_job_empty_launches_log_returns_empty(tmp_path, monkeypatch):
    """Empty launches.jsonl returns [], no crash."""
    launches = tmp_path / "launches.jsonl"
    launches.write_text("")
    monkeypatch.setattr(tu, "LAUNCHES_LOG", launches)
    r = tu.by_job(window_days=30, now=NOW)
    assert r == []


def test_by_job_skips_malformed_lines(tmp_path, monkeypatch):
    """Malformed JSON on one line is skipped; good lines are still counted."""
    launches = tmp_path / "launches.jsonl"
    good = json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "marvin",
                       "output_tokens": 100, "cost_usd": 0.5})
    launches.write_text(f"{good}\nnot json\n{good}\n")
    monkeypatch.setattr(tu, "LAUNCHES_LOG", launches)
    r = tu.by_job(window_days=30, now=NOW)
    assert len(r) == 1
    assert r[0]["output_tokens"] == 200
    assert r[0]["runs"] == 2


def test_by_job_skips_non_dict_json(tmp_path, monkeypatch):
    """Non-dict JSON (array, number, string) is skipped, not crashed."""
    launches = tmp_path / "launches.jsonl"
    good = json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "marvin",
                       "output_tokens": 100, "cost_usd": 0.5})
    launches.write_text(f"{good}\n[1,2,3]\n\"string\"\n42\n{good}\n")
    monkeypatch.setattr(tu, "LAUNCHES_LOG", launches)
    r = tu.by_job(window_days=30, now=NOW)
    assert len(r) == 1
    assert r[0]["output_tokens"] == 200


def test_by_job_treats_null_output_tokens_as_zero(tmp_path, monkeypatch):
    """output_tokens/cost_usd null values are treated as 0."""
    launches = tmp_path / "launches.jsonl"
    launches.write_text(json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "marvin",
                                    "output_tokens": None, "cost_usd": None}) + "\n")
    monkeypatch.setattr(tu, "LAUNCHES_LOG", launches)
    r = tu.by_job(window_days=30, now=NOW)
    assert r[0]["output_tokens"] == 0
    assert r[0]["cost_usd"] == 0


def test_by_job_excludes_launches_older_than_window(tmp_path, monkeypatch):
    """Launches older than window_days are excluded."""
    launches = tmp_path / "launches.jsonl"
    old = json.dumps({"at": "2026-08-01T10:00:00Z", "kind": "background-analyst", "ticket": "marvin",
                     "output_tokens": 100, "cost_usd": 0.5})
    new = json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "marvin",
                     "output_tokens": 50, "cost_usd": 0.25})
    launches.write_text(f"{old}\n{new}\n")
    monkeypatch.setattr(tu, "LAUNCHES_LOG", launches)
    r = tu.by_job(window_days=30, now=NOW)
    assert len(r) == 1
    assert r[0]["output_tokens"] == 50


def test_by_job_null_ticket_falls_back_to_kind(tmp_path, monkeypatch):
    """ticket null falls back to kind as the job label; launch still counted."""
    launches = tmp_path / "launches.jsonl"
    launches.write_text(json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": None,
                                    "output_tokens": 100, "cost_usd": 0.5}) + "\n")
    monkeypatch.setattr(tu, "LAUNCHES_LOG", launches)
    r = tu.by_job(window_days=30, now=NOW)
    assert len(r) == 1
    assert r[0]["job"] == "background-analyst"


def test_by_job_same_job_under_two_kinds_stays_split(tmp_path, monkeypatch):
    """Same job name under two different kinds doesn't collapse; stays two separate rows."""
    launches = tmp_path / "launches.jsonl"
    lines = [
        json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "x",
                    "output_tokens": 100, "cost_usd": 0.5}),
        json.dumps({"at": "2026-10-05T11:00:00Z", "kind": "utility-call", "ticket": "x",
                    "output_tokens": 50, "cost_usd": 0.25}),
    ]
    launches.write_text("\n".join(lines) + "\n")
    monkeypatch.setattr(tu, "LAUNCHES_LOG", launches)
    r = tu.by_job(window_days=30, now=NOW)
    assert len(r) == 2
    assert {(x["job"], x.get("kind")) for x in r} == {("x", "background-analyst"), ("x", "utility-call")}


def test_by_job_result_sorted_descending_by_output_tokens(tmp_path, monkeypatch):
    """Result is sorted descending by output_tokens."""
    launches = tmp_path / "launches.jsonl"
    lines = [
        json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "a",
                    "output_tokens": 50, "cost_usd": 0.25}),
        json.dumps({"at": "2026-10-05T11:00:00Z", "kind": "background-analyst", "ticket": "b",
                    "output_tokens": 200, "cost_usd": 1.0}),
        json.dumps({"at": "2026-10-05T12:00:00Z", "kind": "background-analyst", "ticket": "c",
                    "output_tokens": 100, "cost_usd": 0.5}),
    ]
    launches.write_text("\n".join(lines) + "\n")
    monkeypatch.setattr(tu, "LAUNCHES_LOG", launches)
    r = tu.by_job(window_days=30, now=NOW)
    assert [x["job"] for x in r] == ["b", "c", "a"]


def test_by_job_unreadable_file_returns_empty(tmp_path, monkeypatch):
    """Unreadable file (chmod 000) returns [], no crash; permissions are restored."""
    launches = tmp_path / "launches.jsonl"
    launches.write_text(json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "marvin",
                                   "output_tokens": 100, "cost_usd": 0.5}))
    launches.chmod(0o000)
    monkeypatch.setattr(tu, "LAUNCHES_LOG", launches)
    try:
        r = tu.by_job(window_days=30, now=NOW)
        assert r == []
    finally:
        launches.chmod(0o644)


def test_by_job_duplicate_identical_lines_sum_both(tmp_path, monkeypatch):
    """Append-only log: duplicate identical lines sum both (no silent dedup)."""
    launches = tmp_path / "launches.jsonl"
    line = json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "marvin",
                       "output_tokens": 100, "cost_usd": 0.5})
    launches.write_text(f"{line}\n{line}\n")
    monkeypatch.setattr(tu, "LAUNCHES_LOG", launches)
    r = tu.by_job(window_days=30, now=NOW)
    assert len(r) == 1
    assert r[0]["output_tokens"] == 200
    assert r[0]["runs"] == 2


def test_by_job_huge_file_aggregates_correctly(tmp_path, monkeypatch):
    """Large file (5000+ lines) aggregates correctly with no pathological behavior."""
    launches = tmp_path / "launches.jsonl"
    lines = []
    for i in range(5000):
        lines.append(json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "marvin",
                               "output_tokens": 1, "cost_usd": 0.001}))
    launches.write_text("\n".join(lines) + "\n")
    monkeypatch.setattr(tu, "LAUNCHES_LOG", launches)
    r = tu.by_job(window_days=30, now=NOW)
    assert len(r) == 1
    assert r[0]["output_tokens"] == 5000
    assert r[0]["runs"] == 5000
