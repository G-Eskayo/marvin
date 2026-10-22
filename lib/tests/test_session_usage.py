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


# ── autonomous launches ──────────────────────────────────────────────────

def test_autonomous_detects_headless_runs():
    """Headless runs (not interactive, not subagent) are autonomous."""
    assert tu._autonomous({"entrypoint": "sdk-cli"}) == True
    assert tu._autonomous({"entrypoint": None}) == False
    assert tu._autonomous({"entrypoint": "cli"}) == False
    assert tu._autonomous({"isSidechain": True}) == False


def test_load_launches_reads_ticket_field(tmp_path):
    """_load_launches reads the ticket field from launches.jsonl and maps (cwd, timestamp[:19]) -> job."""
    launches = tmp_path / "launches.jsonl"
    launches.write_text(json.dumps({
        "at": "2026-10-05T10:00:00.000Z", "cwd": "/Users/g/proj", "ticket": "daily-digest", "kind": "background-analyst"
    }) + "\n")
    result = tu._load_launches(launches, now=NOW, window_days=30)
    assert result[("/Users/g/proj", "2026-10-05T10:00:00")] == "daily-digest"


def test_load_launches_ignores_malformed_lines(tmp_path):
    """_load_launches skips malformed JSON and entries missing required fields."""
    launches = tmp_path / "launches.jsonl"
    launches.write_text("\n".join([
        "not json",
        json.dumps({"at": "2026-10-05T10:00:00.000Z", "cwd": "/Users/g/proj"}),  # no ticket
        json.dumps({"at": "2026-10-05T10:00:00.000Z", "ticket": "daily-digest"}),  # no cwd
        json.dumps({"at": "2026-10-05T10:00:00.000Z", "cwd": "/Users/g/proj", "ticket": "daily-digest", "kind": "background-analyst"}),  # valid
    ]) + "\n")
    result = tu._load_launches(launches, now=NOW, window_days=30)
    assert len(result) == 1
    assert result[("/Users/g/proj", "2026-10-05T10:00:00")] == "daily-digest"


def test_load_launches_handles_missing_file(tmp_path):
    """_load_launches returns empty dict if file doesn't exist."""
    result = tu._load_launches(tmp_path / "nope.jsonl", now=NOW)
    assert result == {}


def test_load_launches_handles_permission_error(tmp_path, monkeypatch):
    """_load_launches returns empty dict if file can't be read."""
    launches = tmp_path / "launches.jsonl"
    launches.write_text(json.dumps({"at": "2026-10-05T10:00:00.000Z", "cwd": "/Users/g", "ticket": "daily-digest"}) + "\n")

    def bad_read(*a, **k):
        raise OSError("permission denied")
    monkeypatch.setattr(launches, "read_text", bad_read)
    result = tu._load_launches(launches, now=NOW)
    assert result == {}


def test_load_launches_respects_window_days(tmp_path):
    """_load_launches filters out entries older than the window."""
    launches = tmp_path / "launches.jsonl"
    launches.write_text("\n".join([
        json.dumps({"at": "2026-10-05T10:00:00.000Z", "cwd": "/Users/g/proj", "ticket": "daily-digest"}),  # within 30 days
        json.dumps({"at": "2026-08-01T10:00:00.000Z", "cwd": "/Users/g/proj", "ticket": "research-colony"}),  # outside window
    ]) + "\n")
    result = tu._load_launches(launches, now=NOW, window_days=30)
    assert len(result) == 1
    assert result[("/Users/g/proj", "2026-10-05T10:00:00")] == "daily-digest"


def test_aggregate_correlates_launches_with_transcripts(tmp_path):
    """aggregate matches transcript messages with launch log entries by (cwd, timestamp[:19])."""
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    launches = tmp_path / "launches.jsonl"

    # A transcript with timestamp matching a launch entry
    f = write(transcripts, "s.jsonl", [line("m1", ts="2026-10-05T10:00:00.123Z", cwd="/Users/g/proj")])

    # Launch log entry for the same (cwd, timestamp[:19])
    launches.write_text(json.dumps({
        "at": "2026-10-05T10:00:00.000Z", "cwd": "/Users/g/proj", "ticket": "daily-digest"
    }) + "\n")

    result = tu.aggregate([f], now=NOW, launches_path=launches)
    msg = list(result["totals"].items())  # any message should be correlated
    assert len(result["by_job"]) == 1
    assert result["by_job"][0]["job"] == "daily-digest"


def test_aggregate_includes_by_job_aggregation(tmp_path):
    """aggregate groups usage by job (from the launch log ticket field)."""
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    launches = tmp_path / "launches.jsonl"

    f = write(transcripts, "s.jsonl", [
        line("m1", ts="2026-10-05T10:00:00.123Z", cwd="/Users/g/proj", out=100, entry="sdk-cli"),
        line("m2", ts="2026-10-05T11:00:00.456Z", cwd="/Users/g/proj", out=200, entry="sdk-cli"),
    ])

    launches.write_text("\n".join([
        json.dumps({"at": "2026-10-05T10:00:00.000Z", "cwd": "/Users/g/proj", "ticket": "daily-digest"}),
        json.dumps({"at": "2026-10-05T11:00:00.000Z", "cwd": "/Users/g/proj", "ticket": "auto-fix"}),
    ]) + "\n")

    result = tu.aggregate([f], now=NOW, launches_path=launches)
    jobs = {j["job"]: j["output"] for j in result["by_job"]}
    assert jobs["daily-digest"] == 100
    assert jobs["auto-fix"] == 200


def test_aggregate_by_job_limits_to_top_jobs(tmp_path):
    """aggregate by_job respects TOP_JOBS limit."""
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    launches = tmp_path / "launches.jsonl"

    lines = [line(f"m{i}", ts=f"2026-10-05T{10+i:02d}:00:00.000Z", cwd="/Users/g/proj", out=i*10, entry="sdk-cli")
             for i in range(50)]
    f = write(transcripts, "s.jsonl", lines)

    launch_lines = [json.dumps({
        "at": f"2026-10-05T{10+i:02d}:00:00.000Z", "cwd": "/Users/g/proj", "ticket": f"job-{i}"
    }) for i in range(50)]
    launches.write_text("\n".join(launch_lines) + "\n")

    result = tu.aggregate([f], now=NOW, launches_path=launches)
    assert len(result["by_job"]) <= tu.TOP_JOBS


def test_autonomous_marked_on_rows(tmp_path):
    """Rows in the aggregate output are marked with 'autonomous' field."""
    f = write(tmp_path, "s.jsonl", [
        line("a", ts="2026-10-05T10:00:00Z", entry="cli"),  # interactive
        line("b", ts="2026-10-05T10:00:00Z", entry="sdk-cli"),  # headless
    ])
    result = tu.aggregate([f], now=NOW)
    rows = {r["kind"]: r for r in result["rows"]}
    assert all("autonomous" in r for r in result["rows"])


def test_by_job_includes_all_fields(tmp_path):
    """by_job entries have all the same usage fields as other aggregations."""
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    launches = tmp_path / "launches.jsonl"

    f = write(transcripts, "s.jsonl", [
        line("m1", ts="2026-10-05T10:00:00.123Z", cwd="/Users/g/proj",
             inp=2, out=100, cw=1000, cr=5000, entry="sdk-cli")
    ])
    launches.write_text(json.dumps({
        "at": "2026-10-05T10:00:00.000Z", "cwd": "/Users/g/proj", "ticket": "daily-digest"
    }) + "\n")

    result = tu.aggregate([f], now=NOW, launches_path=launches)
    job = result["by_job"][0]
    assert job["job"] == "daily-digest"
    assert job["input"] == 2
    assert job["output"] == 100
    assert job["cache_write"] == 1000
    assert job["cache_read"] == 5000
    assert job["messages"] == 1
