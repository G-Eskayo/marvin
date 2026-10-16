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


def test_autonomous_is_true_for_non_cli_entrypoint(tmp_path):
    f = write(tmp_path, "a.jsonl", [line("a", entry="sdk-cli"), line("b", entry="cli"), line("c", entry=None)])
    r = tu.aggregate([f], now=NOW)
    autonomous = [row["autonomous"] for row in r["rows"]]
    assert True in autonomous and False in autonomous


def test_rows_include_autonomous_in_bucket_key(tmp_path):
    f = write(tmp_path, "a.jsonl", [line("a", entry="cli", out=100), line("b", entry="sdk-cli", out=200)])
    r = tu.aggregate([f], now=NOW)
    assert len(r["rows"]) == 2 and all("autonomous" in row for row in r["rows"])


def test_by_job_aggregates_from_launches_jsonl(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(json.dumps({"at": "2026-10-05T10:00:00Z", "ticket": "daily-digest", "output_tokens": 100,
                                     "input_tokens": 10, "cache_write_tokens": 500, "cache_read_tokens": 2000}) + "\n")
    r = tu.aggregate([], now=NOW, launches_path=launches)
    assert len(r["by_job"]) == 1 and r["by_job"][0]["ticket"] == "daily-digest" and r["by_job"][0]["output"] == 100


def test_by_job_requires_launches_path_non_none(tmp_path):
    r = tu.aggregate([], now=NOW, launches_path=None)
    assert r["by_job"] == []


def test_by_job_sums_tokens_per_ticket(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        json.dumps({"at": "2026-10-05T10:00:00Z", "ticket": "daily-digest", "output_tokens": 100,
                    "input_tokens": 10, "cache_write_tokens": 500, "cache_read_tokens": 2000}) + "\n" +
        json.dumps({"at": "2026-10-05T11:00:00Z", "ticket": "daily-digest", "output_tokens": 50,
                    "input_tokens": 5, "cache_write_tokens": 250, "cache_read_tokens": 1000}) + "\n"
    )
    r = tu.aggregate([], now=NOW, launches_path=launches)
    job = r["by_job"][0]
    assert job["output"] == 150 and job["input"] == 15 and job["messages"] == 2


def test_by_job_ignores_missing_launches_file(tmp_path):
    r = tu.aggregate([], now=NOW, launches_path=tmp_path / "nonexistent.jsonl")
    assert r["by_job"] == []


def test_by_job_tolerates_malformed_lines(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        "not json\n" +
        json.dumps({"at": "2026-10-05T10:00:00Z", "ticket": "daily-digest", "output_tokens": 100, "input_tokens": 10, "cache_write_tokens": 500, "cache_read_tokens": 2000}) + "\n" +
        json.dumps([1, 2, 3]) + "\n"
    )
    r = tu.aggregate([], now=NOW, launches_path=launches)
    assert len(r["by_job"]) == 1 and r["by_job"][0]["ticket"] == "daily-digest"


def test_by_job_tolerates_null_token_fields(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        json.dumps({"at": "2026-10-05T10:00:00Z", "ticket": "research-colony", "output_tokens": None, "input_tokens": 10}) + "\n" +
        json.dumps({"at": "2026-10-05T11:00:00Z", "ticket": "daily-digest", "output_tokens": 100, "input_tokens": 10, "cache_write_tokens": 500, "cache_read_tokens": 2000}) + "\n"
    )
    r = tu.aggregate([], now=NOW, launches_path=launches)
    assert len(r["by_job"]) == 1 and r["by_job"][0]["ticket"] == "daily-digest"


def test_by_job_respects_window_days_cutoff(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        json.dumps({"at": "2026-08-01T10:00:00Z", "ticket": "old", "output_tokens": 100, "input_tokens": 10, "cache_write_tokens": 500, "cache_read_tokens": 2000}) + "\n" +
        json.dumps({"at": "2026-10-05T10:00:00Z", "ticket": "recent", "output_tokens": 50, "input_tokens": 5, "cache_write_tokens": 250, "cache_read_tokens": 1000}) + "\n"
    )
    r = tu.aggregate([], now=NOW, window_days=30, launches_path=launches)
    assert len(r["by_job"]) == 1 and r["by_job"][0]["ticket"] == "recent"


def test_by_job_sorted_by_output_descending(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        json.dumps({"at": "2026-10-05T10:00:00Z", "ticket": "a", "output_tokens": 50, "input_tokens": 10, "cache_write_tokens": 500, "cache_read_tokens": 2000}) + "\n" +
        json.dumps({"at": "2026-10-05T11:00:00Z", "ticket": "b", "output_tokens": 100, "input_tokens": 10, "cache_write_tokens": 500, "cache_read_tokens": 2000}) + "\n"
    )
    r = tu.aggregate([], now=NOW, launches_path=launches)
    assert [j["ticket"] for j in r["by_job"]] == ["b", "a"]


def test_by_job_handles_permission_errors_gracefully(tmp_path, monkeypatch):
    launches = tmp_path / "launches.jsonl"
    def raise_perm(*args, **kwargs):
        raise PermissionError("access denied")
    monkeypatch.setattr("pathlib.Path.read_text", raise_perm)
    r = tu.aggregate([], now=NOW, launches_path=launches)
    assert r["by_job"] == []


def test_by_job_falls_back_to_kind_when_ticket_missing(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "daily-digest-job", "output_tokens": 100, "input_tokens": 10, "cache_write_tokens": 500, "cache_read_tokens": 2000}) + "\n"
    )
    r = tu.aggregate([], now=NOW, launches_path=launches)
    assert len(r["by_job"]) == 1 and r["by_job"][0]["ticket"] == "daily-digest-job" and r["by_job"][0]["output"] == 100


def test_by_job_skips_rows_with_no_ticket_and_no_kind(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        json.dumps({"at": "2026-10-05T10:00:00Z", "output_tokens": 100, "input_tokens": 10, "cache_write_tokens": 500, "cache_read_tokens": 2000}) + "\n" +
        json.dumps({"at": "2026-10-05T11:00:00Z", "ticket": "daily-digest", "output_tokens": 50, "input_tokens": 5, "cache_write_tokens": 250, "cache_read_tokens": 1000}) + "\n"
    )
    r = tu.aggregate([], now=NOW, launches_path=launches)
    assert len(r["by_job"]) == 1 and r["by_job"][0]["ticket"] == "daily-digest"


def test_by_job_guards_non_numeric_token_fields(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        json.dumps({"at": "2026-10-05T10:00:00Z", "ticket": "test", "output_tokens": "100", "input_tokens": 10, "cache_write_tokens": 500, "cache_read_tokens": 2000}) + "\n" +
        json.dumps({"at": "2026-10-05T11:00:00Z", "ticket": "valid", "output_tokens": 50, "input_tokens": 5, "cache_write_tokens": 250, "cache_read_tokens": 1000}) + "\n"
    )
    r = tu.aggregate([], now=NOW, launches_path=launches)
    assert len(r["by_job"]) == 1 and r["by_job"][0]["ticket"] == "valid"


def test_by_job_skips_non_hashable_job_identifiers(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        json.dumps({"at": "2026-10-05T10:00:00Z", "ticket": ["unhashable", "list"], "output_tokens": 100, "input_tokens": 10, "cache_write_tokens": 500, "cache_read_tokens": 2000}) + "\n" +
        json.dumps({"at": "2026-10-05T11:00:00Z", "ticket": "valid", "output_tokens": 50, "input_tokens": 5, "cache_write_tokens": 250, "cache_read_tokens": 1000}) + "\n"
    )
    r = tu.aggregate([], now=NOW, launches_path=launches)
    assert len(r["by_job"]) == 1 and r["by_job"][0]["ticket"] == "valid"


def test_by_job_tolerates_float_token_values(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        json.dumps({"at": "2026-10-05T10:00:00Z", "ticket": "test", "output_tokens": 100.5, "input_tokens": 10.2, "cache_write_tokens": 500.7, "cache_read_tokens": 2000.1}) + "\n"
    )
    r = tu.aggregate([], now=NOW, launches_path=launches)
    assert len(r["by_job"]) == 1 and r["by_job"][0]["output"] == 100.5
