"""lib/plan_usage.py: the Claude plan's own 5-hour and weekly limit readings, recorded on change, summarised across Macs.

Payload shapes are the real ones captured from Claude Code 2.1.317 on 2026-11-03 (the status line's stdin, and a
`claude -p --output-format stream-json` rate_limit_event), trimmed to the fields that matter.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import plan_usage as pu  # noqa: E402

H = 3600
WEEK = 7 * 24 * H
FIVE = 5 * H
# 2026-11-03 18:30 UTC and 2026-11-06 05:00 UTC: the resets the real capture carried.
R5, R7 = 1793737800, 1793941200
NOW = R5 - 2 * H  # three hours into that 5-hour window


def statusline(five=18, seven=71, r5=R5, r7=R7, version="2.1.317"):
    """The status line's stdin, as Claude Code 2.1.317 sent it (other keys trimmed)."""
    rl = {}
    if five is not None:
        rl["five_hour"] = {"used_percentage": five, "resets_at": r5}
    if seven is not None:
        rl["seven_day"] = {"used_percentage": seven, "resets_at": r7}
    doc = {"version": version, "model": {"id": "claude-haiku"}, "context_window": {"used_percentage": 3}}
    if rl:
        doc["rate_limits"] = rl
    return doc


STREAM_EVENT = {"type": "rate_limit_event", "rate_limit_info": {
    "status": "allowed", "resetsAt": R5, "rateLimitType": "five_hour", "overageStatus": "rejected",
    "isUsingOverage": False, "unifiedWindows": {
        "five_hour": {"utilization": 0.18, "resetsAt": R5, "status": "allowed"},
        "seven_day": {"utilization": 0.71, "resetsAt": R7, "status": "allowed"}}}}


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---- normalize: what a payload says about the plan ----

def test_reads_the_status_line_payload():
    r = pu.normalize(statusline())
    assert r == {"source": "statusline",
                 "five_hour": {"used_percentage": 18.0, "resets_at": R5},
                 "seven_day": {"used_percentage": 71.0, "resets_at": R7},
                 "limit_hit": []}


def test_reads_the_stream_json_event_as_percent_not_fraction():
    r = pu.normalize(STREAM_EVENT)
    assert r["source"] == "stream"
    assert r["five_hour"] == {"used_percentage": 18.0, "resets_at": R5}
    assert r["seven_day"] == {"used_percentage": 71.0, "resets_at": R7}


def test_older_claude_code_without_rate_limits_is_no_reading_not_zero():
    assert pu.normalize(statusline(five=None, seven=None, version="2.0.10")) is None
    assert pu.normalize({}) is None
    assert pu.normalize({"rate_limits": None}) is None
    assert pu.normalize({"rate_limits": {"five_hour": {}}}) is None


def test_garbage_values_are_dropped_not_guessed():
    doc = {"rate_limits": {"five_hour": {"used_percentage": "lots", "resets_at": R5},
                           "seven_day": {"used_percentage": 40, "resets_at": None},
                           "spend_limit": {"used_percentage": 5, "resets_at": R7}}}
    assert pu.normalize(doc) is None
    assert pu.normalize(["not", "a", "dict"]) is None
    assert pu.normalize({"rate_limits": {"five_hour": {"used_percentage": True, "resets_at": R5}}}) is None


def test_one_window_missing_keeps_the_other():
    r = pu.normalize(statusline(five=None))
    assert r["five_hour"] is None and r["seven_day"]["used_percentage"] == 71.0


def test_a_full_meter_or_a_rejected_status_is_a_hit():
    assert pu.normalize(statusline(five=100))["limit_hit"] == ["five_hour"]
    assert pu.normalize(statusline(five=100, seven=100))["limit_hit"] == ["five_hour", "seven_day"]
    rejected = json.loads(json.dumps(STREAM_EVENT))
    rejected["rate_limit_info"]["status"] = "rejected"
    rejected["rate_limit_info"]["unifiedWindows"]["five_hour"]["status"] = "rejected"
    assert pu.normalize(rejected)["limit_hit"] == ["five_hour"]


# ---- record: one row per change ----

def test_records_one_row_then_nothing_while_unchanged(tmp_path):
    log = tmp_path / "plan-usage.jsonl"
    first = pu.record(statusline(), now=NOW, path=log, machine="mac-a")
    assert first is not None
    for i in range(5):
        assert pu.record(statusline(), now=NOW + i, path=log, machine="mac-a") is None
    [row] = rows(log)
    assert row == {"ts": pu.iso(NOW), "machine": "mac-a", "source": "statusline",
                   "five_hour": {"used_percentage": 18.0, "resets_at": R5},
                   "seven_day": {"used_percentage": 71.0, "resets_at": R7}, "limit_hit": []}


def test_a_change_in_either_window_appends(tmp_path):
    log = tmp_path / "plan-usage.jsonl"
    pu.record(statusline(), now=NOW, path=log, machine="m")
    pu.record(statusline(five=19), now=NOW + 60, path=log, machine="m")
    pu.record(statusline(five=19, seven=72), now=NOW + 120, path=log, machine="m")
    pu.record(statusline(five=0, r5=R5 + FIVE), now=R5 + 60, path=log, machine="m")  # a new window
    assert [(r["five_hour"]["used_percentage"], r["seven_day"]["used_percentage"]) for r in rows(log)] == \
        [(18.0, 71.0), (19.0, 71.0), (19.0, 72.0), (0.0, 71.0)]


def test_the_stream_and_status_line_saying_the_same_thing_is_one_row(tmp_path):
    log = tmp_path / "plan-usage.jsonl"
    pu.record(statusline(), now=NOW, path=log, machine="m")
    assert pu.record(STREAM_EVENT, now=NOW + 1, path=log, machine="m") is None


def test_a_dropped_window_is_not_a_change(tmp_path):
    """Claude Code drops a window once its reset passes; that is 'no reading', not a new value worth a row."""
    log = tmp_path / "plan-usage.jsonl"
    pu.record(statusline(), now=NOW, path=log, machine="m")
    assert pu.record(statusline(five=None), now=NOW + 1, path=log, machine="m") is None
    assert pu.record({"version": "2.0.1"}, now=NOW + 2, path=log, machine="m") is None
    assert len(rows(log)) == 1


def test_no_reading_never_creates_the_file(tmp_path):
    log = tmp_path / "logs" / "plan-usage.jsonl"
    assert pu.record({"version": "2.0.1"}, now=NOW, path=log, machine="m") is None
    assert not log.exists()


def test_survives_a_torn_last_line(tmp_path):
    log = tmp_path / "plan-usage.jsonl"
    pu.record(statusline(), now=NOW, path=log, machine="m")
    with log.open("a") as f:
        f.write('{"ts": "2026-11-03T1')  # a write cut off mid-line
    assert pu.record(statusline(five=20), now=NOW + 5, path=log, machine="m") is not None
    assert [r["five_hour"]["used_percentage"] for r in pu.load_rows(log)] == [18.0, 20.0]


def test_machine_name_is_derived_not_hardcoded(tmp_path, monkeypatch):
    log = tmp_path / "plan-usage.jsonl"
    monkeypatch.setattr(pu, "this_machine", lambda: "derived-id")
    pu.record(statusline(), now=NOW, path=log)
    assert rows(log)[0]["machine"] == "derived-id"


def test_machine_lookup_only_happens_when_a_row_is_written(tmp_path, monkeypatch):
    """The status line runs on every message; the unchanged path must stay a file read."""
    log = tmp_path / "plan-usage.jsonl"
    calls = []
    monkeypatch.setattr(pu, "this_machine", lambda: calls.append(1) or "m")
    pu.record(statusline(), now=NOW, path=log)
    pu.record(statusline(), now=NOW + 1, path=log)
    pu.record({}, now=NOW + 2, path=log)
    assert len(calls) == 1


# ---- the status line entry point ----

def test_statusline_records_and_prints_nothing_without_a_next_command(tmp_path, capsys):
    log = tmp_path / "plan-usage.jsonl"
    out = pu.statusline_main(json.dumps(statusline()), [], path=log, machine="m", now=NOW)
    assert out == 0 and capsys.readouterr().out == "" and len(rows(log)) == 1


def test_statusline_passes_stdin_to_the_previous_status_line_and_keeps_its_output(tmp_path, capfd):
    log = tmp_path / "plan-usage.jsonl"
    pu.statusline_main(json.dumps(statusline()), ["/bin/sh", "-c", "python3 -c 'import json,sys;print(json.load(sys.stdin)[\"model\"][\"id\"])'"],
                       path=log, machine="m", now=NOW)
    assert capfd.readouterr().out.strip() == "claude-haiku"


def test_statusline_never_breaks_on_bad_input_or_an_unwritable_log(tmp_path, capfd):
    blocked = tmp_path / "file"
    blocked.write_text("")
    assert pu.statusline_main("not json{", ["/bin/echo", "still here"], path=tmp_path / "x.jsonl", machine="m") == 0
    assert pu.statusline_main(json.dumps(statusline()), ["/bin/echo", "still here"],
                              path=blocked / "plan-usage.jsonl", machine="m") == 0
    assert capfd.readouterr().out.count("still here") == 2


def test_statusline_setting_installs_ours_when_there_is_none():
    s = pu.statusline_setting(None)
    assert s["type"] == "command" and s["command"].endswith("lib/plan_usage.py statusline")
    assert "$HOME/" in s["command"] and str(Path.home()) + "/" not in s["command"]


def test_statusline_setting_wraps_an_existing_one_and_keeps_its_options():
    s = pu.statusline_setting({"type": "command", "command": "~/bin/my line.sh", "padding": 2, "refreshInterval": 5})
    assert s["padding"] == 2 and s["refreshInterval"] == 5
    assert s["command"].endswith("statusline -- /bin/sh -c '~/bin/my line.sh'")


def test_statusline_setting_is_idempotent():
    once = pu.statusline_setting({"type": "command", "command": "echo hi"})
    assert pu.statusline_setting(once) == once
    plain = pu.statusline_setting(None)
    assert pu.statusline_setting(plain) == plain


# ---- summary ----

def row(t, machine="mac-a", five=None, r5=None, seven=None, r7=R7, hit=()):
    out = {"ts": pu.iso(t), "machine": machine, "source": "statusline",
           "five_hour": None if five is None else {"used_percentage": float(five), "resets_at": r5},
           "seven_day": None if seven is None else {"used_percentage": float(seven), "resets_at": r7},
           "limit_hit": list(hit)}
    return out


WEEK_START = R7 - WEEK


def test_no_rows_is_not_enough_data_never_zero():
    s = pu.summarize([], now=NOW)
    assert s["status"] == "not_enough_data"
    assert s["week"]["status"] == "not_enough_data" and "used_percentage" not in s["week"]
    assert s["binding_limit"] == "unknown"


def test_a_weekly_reading_from_last_week_is_not_this_weeks_number():
    old = [row(WEEK_START - 3 * H, five=40, r5=WEEK_START, seven=95, r7=WEEK_START)]
    s = pu.summarize(old, now=WEEK_START + H)
    assert s["week"]["status"] == "not_enough_data"


def test_weekly_used_and_pace():
    now = WEEK_START + WEEK // 2  # half the week gone
    s = pu.summarize([row(now - 600, five=10, r5=now + H, seven=40)], now=now)
    w = s["week"]
    assert w["status"] == "ok" and w["used_percentage"] == 40.0
    assert w["elapsed_fraction"] == 0.5 and w["expected_percentage"] == 50.0
    assert w["pace"] == 0.8 and w["projected_at_reset"] == 80.0
    assert w["resets_at"] == pu.iso(R7) and w["started_at"] == pu.iso(WEEK_START)
    assert w["reading_age_min"] == 10 and w["stale"] is False


def test_latest_reading_wins_across_machines():
    now = WEEK_START + WEEK // 2
    rs = [row(now - 300, "mac-b", five=30, r5=now + H, seven=55), row(now - 900, "mac-a", five=20, r5=now + H, seven=50)]
    assert pu.summarize(rs, now=now)["week"]["used_percentage"] == 55.0


def test_an_old_reading_is_flagged_stale_not_hidden():
    now = WEEK_START + WEEK // 2
    s = pu.summarize([row(now - 8 * H, five=10, r5=now - 3 * H, seven=40)], now=now)
    assert s["week"]["stale"] is True and s["week"]["used_percentage"] == 40.0


def test_pace_is_withheld_in_the_first_hour():
    s = pu.summarize([row(WEEK_START + 60, five=1, r5=WEEK_START + FIVE, seven=1)], now=WEEK_START + 120)
    assert s["week"]["pace"] is None and s["week"]["projected_at_reset"] is None


def test_five_hour_windows_grouped_by_reset_across_machines_with_hits():
    now = WEEK_START + 3 * 24 * H
    w1 = WEEK_START + 10 * H  # a window that ran 5h..10h into the week and hit the limit
    w2 = WEEK_START + 20 * H
    rs = [row(w1 - 4 * H, "mac-a", five=30, r5=w1, seven=10),
          row(w1 - 2 * H, "mac-b", five=80, r5=w1 + 1, seven=14),    # same window, a second off
          row(w1 - H, "mac-a", five=100, r5=w1, seven=18, hit=["five_hour"]),
          row(w2 - 4 * H, "mac-b", five=5, r5=w2, seven=19)]
    s = pu.summarize(rs, now=now)
    ws = s["five_hour"]["windows"]
    assert len(ws) == 2
    assert ws[0]["peak_percentage"] == 100.0 and ws[0]["hit"] is True
    assert ws[0]["machines"] == ["mac-a", "mac-b"] and ws[0]["readings"] == 3
    assert ws[0]["started_at"] == pu.iso(w1 - FIVE) and ws[0]["resets_at"] == pu.iso(w1)
    assert [w["resets_at"] for w in s["five_hour"]["hit"]] == [pu.iso(w1)]
    assert [w["resets_at"] for w in s["five_hour"]["nearly_unused"]] == [pu.iso(w2)]


def test_unused_time_counts_whole_five_hour_blocks_from_when_recording_began():
    now = WEEK_START + 40 * H
    first = WEEK_START + 2 * H             # recording began 2h into the week
    wa = WEEK_START + 9 * H                # window 4h..9h
    wb = WEEK_START + 30 * H               # window 25h..30h
    rs = [row(first, five=1, r5=WEEK_START + 3 * H, seven=1),   # a window 0h..3h, seen at its tail
          row(wa - 4 * H, five=50, r5=wa, seven=5), row(wb - 4 * H, five=50, r5=wb, seven=9)]
    u = pu.summarize(rs, now=now)["five_hour"]["unused"]
    # covered: 0-3 (clipped to 2-3), 4-9, 25-30. Gaps from 2h: 3-4 (1h), 9-25 (16h = 3 blocks), 30-40 (10h = 2 blocks)
    assert u["windows"] == 5
    assert u["hours"] == 27.0
    assert [(g["hours"], g["windows"]) for g in u["gaps"]] == [(1.0, 0), (16.0, 3), (10.0, 2)]
    assert u["observed_from"] == pu.iso(first)


def test_the_open_window_is_current_not_nearly_unused():
    now = NOW
    s = pu.summarize([row(now - 600, five=2, r5=R5, seven=71)], now=now)
    assert s["five_hour"]["current"]["open"] is True
    assert s["five_hour"]["nearly_unused"] == []


def test_binding_limit_five_hour_when_hits_but_week_has_room():
    now = WEEK_START + WEEK // 2
    w1 = now - 2 * H
    rs = [row(w1 - H, five=100, r5=w1, seven=30, hit=["five_hour"])]
    s = pu.summarize(rs, now=now)
    assert s["binding_limit"] == "five_hour"
    assert s["week"]["left_at_reset_percentage"] == 40.0


def test_binding_limit_seven_day_and_none():
    now = WEEK_START + WEEK // 2
    assert pu.summarize([row(now - 60, five=10, r5=now + H, seven=100, hit=["seven_day"])], now=now)["binding_limit"] == "seven_day"
    assert pu.summarize([row(now - 60, five=10, r5=now + H, seven=30)], now=now)["binding_limit"] == "none"


def test_rows_with_bad_timestamps_or_shapes_are_skipped():
    now = WEEK_START + WEEK // 2
    rs = [{"ts": "yesterday"}, {"nope": 1}, "a string", row(now - 60, five=10, r5=now + H, seven=30),
          {"ts": pu.iso(now - 30), "five_hour": {"used_percentage": None, "resets_at": "x"}, "seven_day": 5}]
    s = pu.summarize(rs, now=now)
    assert s["week"]["used_percentage"] == 30.0 and len(s["five_hour"]["windows"]) == 1


# ---- report: this Mac plus its peers, read the way usage_report reads them ----

class Peers:
    def __init__(self, files, down=()):
        self.files, self.down, self.calls = files, set(down), []

    def __call__(self, host, command, timeout=20):
        self.calls.append((host, command))
        if host in self.down:
            raise OSError("unreachable")
        if host not in self.files:
            raise FileNotFoundError("No such file")
        return self.files[host]


def test_report_merges_peer_rows_and_names_unreachable_ones(tmp_path, monkeypatch):
    now = WEEK_START + WEEK // 2
    log = tmp_path / "plan-usage.jsonl"
    log.write_text(json.dumps(row(now - 900, "mac-a", five=20, r5=now + H, seven=50)) + "\n")
    monkeypatch.setattr(pu, "LOG_PATH", log)
    monkeypatch.setattr(pu, "this_machine", lambda: "mac-a")
    monkeypatch.setattr(pu, "peer_machines", lambda: {"mac-b": "host-b", "box": "host-box", "gone": "host-gone"})
    peer_line = json.dumps(row(now - 300, "mac-b", five=30, r5=now + H, seven=55)) + "\nnot json\n"
    s = pu.report(now=now, ssh=Peers({"host-b": peer_line}, down={"host-gone"}))
    assert s["week"]["used_percentage"] == 55.0
    by = {m["machine"]: m for m in s["machines"]}
    assert by["mac-a"]["this"] is True and by["mac-a"]["rows"] == 1
    assert by["mac-b"]["reachable"] is True and by["mac-b"]["rows"] == 1
    assert by["box"]["reachable"] is True and by["box"]["rows"] == 0
    assert by["gone"]["reachable"] is False


def test_report_with_no_file_anywhere_is_not_enough_data(tmp_path, monkeypatch):
    monkeypatch.setattr(pu, "LOG_PATH", tmp_path / "missing.jsonl")
    monkeypatch.setattr(pu, "this_machine", lambda: "mac-a")
    monkeypatch.setattr(pu, "peer_machines", lambda: {})
    s = pu.report(now=NOW, ssh=Peers({}))
    assert s["status"] == "not_enough_data"
    json.dumps(s)  # the dashboard reads it as JSON
