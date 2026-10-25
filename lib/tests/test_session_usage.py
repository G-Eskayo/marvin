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


def test_by_ticket_includes_by_kind_split(tmp_path):
    """Test 1: by_ticket entries should have by_kind field like by_project does."""
    wt = "/Users/g/.agents-pipeline-worktrees/pipeline-g-eskayo-marvin-5"
    f = write(tmp_path, "a.jsonl", [line("a", cwd=wt, out=100, entry="sdk-cli"), line("b", cwd=wt, out=50, entry="cli")])
    r = tu.aggregate([f], now=NOW)
    ticket = next(t for t in r["by_ticket"] if t["ticket"] == 5)
    assert "by_kind" in ticket
    assert ticket["by_kind"]["headless"] == 100  # sdk-cli is headless
    assert ticket["by_kind"]["interactive"] == 50  # cli is interactive


def test_by_ticket_merges_by_kind_across_machines(tmp_path):
    """Test 2: by_kind should merge output tokens per kind for the same ticket."""
    wt = "/Users/g/.agents-pipeline-worktrees/pipeline-g-eskayo-clarity-captions-12"
    # Simulating two lines with different kinds for same ticket
    f = write(tmp_path, "a.jsonl", [line("a", cwd=wt, out=200, entry="sdk-cli"), line("b", cwd=wt, out=300, entry="cli")])
    r = tu.aggregate([f], now=NOW)
    ticket = next(t for t in r["by_ticket"] if t["project"] == "clarity-captions" and t["ticket"] == 12)
    assert ticket["by_kind"]["headless"] == 200
    assert ticket["by_kind"]["interactive"] == 300


def test_by_ticket_tracks_subagent_runs(tmp_path):
    """Test 3: by_kind should properly track subagent runs (isSidechain=true)."""
    wt = "/Users/g/.agents-pipeline-worktrees/pipeline-g-eskayo-nourished-7"
    # subagent runs have isSidechain=True
    f = write(tmp_path, "a.jsonl", [line("a", cwd=wt, out=150, entry="cli", side=True)])
    r = tu.aggregate([f], now=NOW)
    ticket = next(t for t in r["by_ticket"] if t["ticket"] == 7)
    assert ticket["by_kind"]["subagent"] == 150
    assert ticket["by_kind"]["headless"] == 0
    assert ticket["by_kind"]["interactive"] == 0


def test_by_ticket_all_kinds_initialized_even_if_empty(tmp_path):
    """Test 4: by_kind should have all three kinds (interactive, headless, subagent) even if some are 0."""
    wt = "/Users/g/.agents-pipeline-worktrees/pipeline-g-eskayo-finance-os-3"
    # Only interactive runs for this ticket
    f = write(tmp_path, "a.jsonl", [line("a", cwd=wt, out=75, entry="cli")])
    r = tu.aggregate([f], now=NOW)
    ticket = next(t for t in r["by_ticket"] if t["ticket"] == 3)
    assert set(ticket["by_kind"].keys()) == {"interactive", "headless", "subagent"}
    assert ticket["by_kind"]["interactive"] == 75
    assert ticket["by_kind"]["headless"] == 0
    assert ticket["by_kind"]["subagent"] == 0


def test_aggregate_multi_file_loop_merges_same_ticket_across_files(tmp_path):
    """Test 15: aggregate() should correctly merge data for the same ticket from multiple files."""
    wt = "/Users/g/.agents-pipeline-worktrees/pipeline-g-eskayo-marvin-8"
    f1 = write(tmp_path, "file1.jsonl", [line("m1", cwd=wt, out=100, entry="sdk-cli")])
    f2 = write(tmp_path, "file2.jsonl", [line("m2", cwd=wt, out=200, entry="sdk-cli")])
    r = tu.aggregate([f1, f2], now=NOW)
    ticket = next(t for t in r["by_ticket"] if t["ticket"] == 8)
    assert ticket["output"] == 300, "aggregate() should sum output across files"
    assert ticket["messages"] == 2, "aggregate() should count messages from both files"
    assert ticket["by_kind"]["headless"] == 300, "aggregate() should merge by_kind across files"


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
