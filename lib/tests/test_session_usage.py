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


def test_autonomous_classification_independent_of_kind(tmp_path):
    f = write(tmp_path, "a.jsonl", [
        line("interactive", entry="cli"),           # autonomous=False
        line("headless", entry="sdk-cli"),          # autonomous=True
        line("subagent_cli", entry="cli", side=True),      # autonomous=False (interactive spawned subagent)
        line("subagent_headless", entry="sdk-cli", side=True),  # autonomous=True (headless spawned subagent)
    ])
    r = tu.aggregate([f], now=NOW)
    # Check that autonomous field is present and correctly classified in every row
    for row in r["rows"]:
        assert "autonomous" in row
    autonomy_values = {(row["kind"], row["autonomous"]) for row in r["rows"]}
    assert autonomy_values == {
        ("interactive", False), ("headless", True), ("subagent", False), ("subagent", True)
    }


def test_by_job_aggregates_launches_from_same_kind_and_job(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "daily-digest", "output_tokens": 100, "cost_usd": 0.01}) + "\n"
        + json.dumps({"at": "2026-10-05T11:00:00Z", "kind": "background-analyst", "ticket": "daily-digest", "output_tokens": 150, "cost_usd": 0.015}) + "\n"
    )
    r = tu.aggregate([], now=NOW, launches_path=launches)
    job = next((j for j in r["by_job"] if j["job"] == "daily-digest"), None)
    assert job and job["output_tokens"] == 250 and job["cost_usd"] == 0.025 and job["runs"] == 2


def test_by_job_missing_or_empty_doesnt_crash(tmp_path):
    missing_path = tmp_path / "nonexistent.jsonl"
    r = tu.aggregate([], now=NOW, launches_path=missing_path)
    assert r["by_job"] == []


def test_by_job_skips_malformed_json_lines(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "auto-fix", "output_tokens": 50, "cost_usd": 0.005}) + "\n"
        + "not json at all\n"  # malformed, skipped
        + json.dumps({"at": "2026-10-05T11:00:00Z", "kind": "background-analyst", "ticket": "auto-fix", "output_tokens": 75, "cost_usd": 0.0075}) + "\n"
    )
    r = tu.aggregate([], now=NOW, launches_path=launches)
    job = next((j for j in r["by_job"] if j["job"] == "auto-fix"), None)
    assert job and job["output_tokens"] == 125


def test_by_job_handles_null_tokens_and_cost(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "self-improve", "output_tokens": None, "cost_usd": None}) + "\n"
    )
    r = tu.aggregate([], now=NOW, launches_path=launches)
    job = next((j for j in r["by_job"] if j["job"] == "self-improve"), None)
    assert job and job["output_tokens"] == 0 and job["cost_usd"] == 0.0


def test_by_job_excludes_old_launches_outside_window(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        json.dumps({"at": "2026-08-01T10:00:00Z", "kind": "background-analyst", "ticket": "old-job", "output_tokens": 100, "cost_usd": 0.01}) + "\n"
        + json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "recent-job", "output_tokens": 50, "cost_usd": 0.005}) + "\n"
    )
    r = tu.aggregate([], now=NOW, window_days=30, launches_path=launches)
    jobs = {j["job"]: j for j in r["by_job"]}
    assert "recent-job" in jobs and "old-job" not in jobs


def test_by_job_skips_launch_with_null_ticket(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": None, "output_tokens": 100, "cost_usd": 0.01}) + "\n"
        + json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "valid-job", "output_tokens": 50, "cost_usd": 0.005}) + "\n"
    )
    r = tu.aggregate([], now=NOW, launches_path=launches)
    jobs = {j["job"]: j for j in r["by_job"]}
    assert "valid-job" in jobs and len([j for j in r["by_job"] if j["job"] is None or j["job"] == "None"]) == 0


def test_by_job_skips_non_dict_json_lines(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "job1", "output_tokens": 100, "cost_usd": 0.01}) + "\n"
        + '"just a string"\n'
        + '[1,2,3]\n'
        + json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "job2", "output_tokens": 50, "cost_usd": 0.005}) + "\n"
    )
    r = tu.aggregate([], now=NOW, launches_path=launches)
    jobs = {j["job"] for j in r["by_job"]}
    assert jobs == {"job1", "job2"}


def test_by_job_skips_truncated_final_line(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "job1", "output_tokens": 100, "cost_usd": 0.01}) + "\n"
        + json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "job2", "output_tokens": 50, "cost_usd": 0.005})
        + "\n{\"incomplete\":"  # truncated partial line
    )
    r = tu.aggregate([], now=NOW, launches_path=launches)
    jobs = {j["job"] for j in r["by_job"]}
    assert jobs == {"job1", "job2"}


def test_by_job_handles_unrecognized_future_entrypoint_without_exception(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "future-kind", "ticket": "job1", "output_tokens": 100, "cost_usd": 0.01}) + "\n"
    )
    r = tu.aggregate([], now=NOW, launches_path=launches)
    jobs = [j for j in r["by_job"] if j["job"] == "job1"]
    assert len(jobs) == 1 and jobs[0]["kind"] == "future-kind"


def test_by_job_handles_exact_float_cost_assertion(tmp_path):
    launches = tmp_path / "launches.jsonl"
    launches.write_text(
        json.dumps({"at": "2026-10-05T10:00:00Z", "kind": "background-analyst", "ticket": "daily-digest", "output_tokens": 100, "cost_usd": 0.01}) + "\n"
        + json.dumps({"at": "2026-10-05T11:00:00Z", "kind": "background-analyst", "ticket": "daily-digest", "output_tokens": 150, "cost_usd": 0.015}) + "\n"
    )
    r = tu.aggregate([], now=NOW, launches_path=launches)
    job = next((j for j in r["by_job"] if j["job"] == "daily-digest"), None)
    assert job and abs(job["cost_usd"] - 0.025) < 1e-9
