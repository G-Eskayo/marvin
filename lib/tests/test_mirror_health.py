"""Health reads a pull-only node's mirror from a Mac (marvin#910, ADR 0069).

mac-mini-2012's mirror failed every fetch for 4 days (2026-10-26..30) and Health on the Mini never said so: the box
logged 391 `sync:mirror` errors to its own errors.jsonl and the Mini's fetch-based repo probe hung into "unverifiable".
These tests try to break the replacement: unreachable boxes, garbled logs, clock skew, empty output, and real git repos
where old commits arrive late.
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

import mirror_health as mh  # noqa: E402

NOW = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)
SHA_A = "a" * 40
SHA_C = "c" * 40


def _err(t: datetime | str, source: str = "sync:mirror", message: str = "fetch failed in .claude",
         raw: str = "ssh: connect to host 100.102.74.64 port 22: Connection timed out") -> str:
    when = t.isoformat() if isinstance(t, datetime) else t
    return json.dumps({"t": when, "machine": "mac-mini-2012", "source": source, "message": message, "raw": raw})


def _probe_text(now: datetime | None = NOW, agents: str = SHA_A, claude: str = SHA_C, errors=()) -> str:
    lines = []
    if now is not None:
        lines.append(f"now={int(now.timestamp())}")
    lines += [f"head:.agents={agents}", f"head:.claude={claude}", mh.ERRORS_MARK, *errors]
    return "\n".join(lines) + "\n"


CURRENT = {".agents": {"known": True, "missing": 0, "since": None},
           ".claude": {"known": True, "missing": 0, "since": None}}


def _current_lag(_rel, _head):
    return dict(CURRENT[_rel])


# ── parsing what the box sent ──────────────────────────────────────────────────────────────────────────────────────

def test_the_probe_reads_the_box_clock_heads_and_mirror_errors():
    p = mh.parse_probe(_probe_text(errors=[_err(NOW - timedelta(minutes=5))]))
    assert p["now"] == NOW.timestamp()
    assert p["heads"] == {".agents": SHA_A, ".claude": SHA_C}
    assert len(p["errors"]) == 1 and p["errors"][0]["source"] == "sync:mirror"


def test_empty_probe_output_is_an_error_not_a_clean_box():
    # ssh can exit 0 and print nothing (a broken login shell). That is "couldn't read", never "no failures".
    with pytest.raises(ValueError):
        mh.parse_probe("")
    with pytest.raises(ValueError):
        mh.parse_probe("Welcome to Kali\n")


def test_garbled_error_lines_are_skipped_and_the_good_ones_still_count():
    junk = ["{not json", "[1, 2, 3]", '"a string"', '{"source": "sync:mirror"}',          # no t
            '{"t": "yesterday-ish", "source": "sync:mirror"}', "\x00\x01binary",
            _err(NOW - timedelta(minutes=1))[:40]]                                       # truncated mid-write
    p = mh.parse_probe(_probe_text(errors=junk + [_err(NOW - timedelta(minutes=2))]))
    assert mh.recent_failures(p["errors"], p["now"]) == 1


def test_only_the_mirror_source_counts():
    # grep -F on the box matches the text anywhere; a message that merely mentions sync:mirror isn't a mirror failure.
    lines = [_err(NOW - timedelta(minutes=3), source="dashboard:mr:list", message="sync:mirror mentioned"),
             _err(NOW - timedelta(minutes=3), source="sync:mirror-ish")]
    p = mh.parse_probe(_probe_text(errors=lines))
    assert mh.recent_failures(p["errors"], p["now"]) == 0


def test_a_missing_box_clock_falls_back_to_this_macs_clock():
    p = mh.parse_probe(_probe_text(now=None, errors=[_err(NOW - timedelta(minutes=5))]))
    assert p["now"] is None
    assert mh.recent_failures(p["errors"], p["now"], fallback_now=NOW.timestamp()) == 1


def test_a_garbled_box_clock_is_treated_as_missing():
    text = _probe_text().replace(f"now={int(NOW.timestamp())}", "now=soon")
    assert mh.parse_probe(text)["now"] is None


# ── the failure window is measured on the box's clock ──────────────────────────────────────────────────────────────

def test_the_window_is_the_last_hour_on_the_box_clock():
    errs = [{"t": (NOW - timedelta(minutes=m)).isoformat(), "source": "sync:mirror"} for m in (5, 30, 59, 61, 600)]
    assert mh.recent_failures(errs, NOW.timestamp()) == 3


def test_clock_skew_box_ahead_still_counts_its_own_recent_failures():
    # The box's clock runs 3 h ahead of the Mac: its entries are "in the future" to the Mac but recent to the box.
    box_now = NOW + timedelta(hours=3)
    errs = [{"t": (box_now - timedelta(minutes=m)).isoformat(), "source": "sync:mirror"} for m in (1, 11, 21)]
    assert mh.recent_failures(errs, box_now.timestamp()) == 3


def test_clock_skew_box_behind_does_not_hide_failures():
    box_now = NOW - timedelta(hours=5)
    errs = [{"t": (box_now - timedelta(minutes=m)).isoformat(), "source": "sync:mirror"} for m in (1, 11, 21)]
    assert mh.recent_failures(errs, box_now.timestamp()) == 3


def test_future_dated_entries_do_not_count_forever():
    # One entry stamped while the clock was wrong (a day ahead) must not keep the row red for a day.
    errs = [{"t": (NOW + timedelta(days=1)).isoformat(), "source": "sync:mirror"}]
    assert mh.recent_failures(errs, NOW.timestamp()) == 0


def test_z_suffix_and_naive_timestamps_parse():
    errs = [{"t": (NOW - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "source": "sync:mirror"},
            {"t": (NOW - timedelta(minutes=2)).replace(tzinfo=None).isoformat(), "source": "sync:mirror"}]
    assert mh.recent_failures(errs, NOW.timestamp()) == 2


# ── judging one box ────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_current_box_with_no_failures_is_green():
    sev, detail = mh.evaluate(mh.parse_probe(_probe_text()), _current_lag, NOW.timestamp())
    assert sev == "green"
    assert "no mirror failures" in detail


def test_the_outage_that_happened_is_red():
    # The real 2026-10-30 state: a failure every ~11 min, all with the dead IP.
    errs = [_err(NOW - timedelta(minutes=m)) for m in (2, 13, 24, 35, 46, 57)]
    lag = lambda rel, head: ({"known": True, "missing": 40, "since": (NOW - timedelta(days=4)).timestamp()}
                             if rel == ".claude" else dict(CURRENT[rel]))
    sev, detail = mh.evaluate(mh.parse_probe(_probe_text(errors=errs)), lag, NOW.timestamp())
    assert sev == "red"
    assert "6 mirror failure" in detail
    assert "~/.claude" in detail and "behind" in detail


def test_repeated_failures_alone_turn_it_red_within_one_cycle():
    # The ~/.claude HEAD hasn't fallen 2 h behind yet, but the mirror has failed 3 times: red now, not in 2 h.
    errs = [_err(NOW - timedelta(minutes=m)) for m in (2, 13, 24)]
    sev, _ = mh.evaluate(mh.parse_probe(_probe_text(errors=errs)), _current_lag, NOW.timestamp())
    assert sev == "red"


def test_a_single_blip_is_amber_not_red():
    sev, detail = mh.evaluate(mh.parse_probe(_probe_text(errors=[_err(NOW - timedelta(minutes=4))])),
                              _current_lag, NOW.timestamp())
    assert sev == "yellow"
    assert "1 mirror failure" in detail


def test_the_cause_of_the_failures_is_named():
    errs = [_err(NOW - timedelta(minutes=m)) for m in (2, 13, 24)]
    _, detail = mh.evaluate(mh.parse_probe(_probe_text(errors=errs)), _current_lag, NOW.timestamp())
    assert "fetch failed in .claude" in detail


def test_behind_is_judged_by_age_not_count():
    def lag_at(minutes):
        return lambda rel, head: {"known": True, "missing": 3, "since": (NOW - timedelta(minutes=minutes)).timestamp()}
    assert mh.evaluate(mh.parse_probe(_probe_text()), lag_at(10), NOW.timestamp())[0] == "green"   # one mirror cycle
    assert mh.evaluate(mh.parse_probe(_probe_text()), lag_at(45), NOW.timestamp())[0] == "yellow"
    assert mh.evaluate(mh.parse_probe(_probe_text()), lag_at(150), NOW.timestamp())[0] == "red"


def test_a_head_this_mac_has_not_seen_is_amber_never_green():
    lag = lambda rel, head: {"known": False, "missing": 0, "since": None}
    sev, detail = mh.evaluate(mh.parse_probe(_probe_text()), lag, NOW.timestamp())
    assert sev == "yellow"
    assert "hasn't seen" in detail


def test_a_missing_repo_on_the_box_is_red():
    sev, detail = mh.evaluate(mh.parse_probe(_probe_text(claude="")), _current_lag, NOW.timestamp())
    assert sev == "red"
    assert "no git repo at ~/.claude" in detail


def test_a_lag_reader_that_crashes_is_amber_not_green():
    def lag(rel, head):
        raise subprocess.TimeoutExpired("git", 10)
    sev, detail = mh.evaluate(mh.parse_probe(_probe_text()), lag, NOW.timestamp())
    assert sev == "yellow"
    assert "couldn't compare" in detail


# ── the sweep row, per pull-only device ────────────────────────────────────────────────────────────────────────────

BOX = {"mac-mini-2012": {"os": "linux", "kind": "desktop", "tailscale_hostname": "mac-mini-2012"}}


def _sweep(reach, runner=None, lag=_current_lag, devices=BOX):
    runner = runner or (lambda host: _probe_text())
    return mh.check_mirror_sync_everywhere(reach, devices=devices, runner=runner, lag=lag, now=NOW)


def test_one_row_per_pull_only_device():
    rows = _sweep({"machine:mac-mini-2012": "green"})
    assert [r["id"] for r in rows] == ["mirror:sync@mac-mini-2012"]
    assert rows[0]["severity"] == "green"


def test_macs_are_not_pull_only_nodes():
    devices = {**BOX, "macbook-pro-1": {"kind": "laptop", "tailscale_hostname": "lap"},
               "mac-mini-1": {"os": "macos", "tailscale_hostname": "gils-mac-mini"}}
    assert mh.pull_only(devices) == {"mac-mini-2012": BOX["mac-mini-2012"]}


def test_an_unreachable_box_is_amber_and_never_runs_the_probe():
    called = []
    rows = _sweep({"machine:mac-mini-2012": "red"}, runner=lambda h: called.append(h) or _probe_text())
    assert rows[0]["severity"] == "yellow"
    assert "unreachable" in rows[0]["detail"]
    assert called == []


def test_a_box_with_no_reachability_reading_is_amber():
    assert _sweep({})[0]["severity"] == "yellow"


def test_an_asleep_box_is_asleep_not_a_sync_failure():
    assert _sweep({"machine:mac-mini-2012": "asleep"})[0]["severity"] == "asleep"


def test_ssh_failing_after_reachability_passed_is_amber():
    def runner(host):
        raise OSError("ssh: connect to host mac-mini-2012 port 22: Operation timed out")
    row = _sweep({"machine:mac-mini-2012": "green"}, runner=runner)[0]
    assert row["severity"] == "yellow"
    assert "couldn't read" in row["detail"]


def test_ssh_timing_out_is_amber():
    def runner(host):
        raise subprocess.TimeoutExpired("ssh", 20)
    assert _sweep({"machine:mac-mini-2012": "green"}, runner=runner)[0]["severity"] == "yellow"


def test_empty_ssh_output_is_amber_not_green():
    assert _sweep({"machine:mac-mini-2012": "green"}, runner=lambda h: "")[0]["severity"] == "yellow"


def test_no_registered_hostname_is_amber():
    devices = {"mac-mini-2012": {"os": "linux"}}
    row = _sweep({"machine:mac-mini-2012": "green"}, devices=devices)[0]
    assert row["severity"] == "yellow"


def test_a_failing_box_is_red_in_the_sweep():
    errs = [_err(NOW - timedelta(minutes=m)) for m in (2, 13, 24)]
    row = _sweep({"machine:mac-mini-2012": "green"}, runner=lambda h: _probe_text(errors=errs))[0]
    assert row["severity"] == "red"


def test_the_probe_script_never_fetches_or_writes():
    # ADR 0069: the Mac reads the box. The old probe ran `git fetch` on the box over the very path that was broken.
    script = mh.PROBE_SCRIPT
    for verb in ("fetch", "pull", "reset", "checkout", "commit", " > ", ">>", "rm ", "mv "):
        assert verb not in script, verb


def test_the_probe_script_runs_against_a_real_home(tmp_path):
    # Run the script as the box would: real bash, real git, a real errors.jsonl with junk in it.
    home = tmp_path / "home"
    for rel in (".agents", ".claude"):
        _git(home / rel, "init", "-q", "-b", "main")
        _commit(home / rel, "first", NOW - timedelta(days=1))
    logs = home / ".claude" / "logs"
    logs.mkdir()
    (logs / "errors.jsonl").write_text("\n".join(["garbage{", _err(NOW - timedelta(minutes=1)),
                                                   _err(NOW, source="job:other")]) + "\n")
    out = subprocess.run(["bash", "-s"], input=mh.PROBE_SCRIPT, capture_output=True, text=True,
                         env={**os.environ, "HOME": str(home)}, timeout=30).stdout
    p = mh.parse_probe(out)
    assert set(p["heads"]) == {".agents", ".claude"} and all(len(h) == 40 for h in p["heads"].values())
    assert [e["source"] for e in p["errors"]] == ["sync:mirror"]


def test_the_probe_script_on_a_box_with_no_logs_and_no_repos(tmp_path):
    out = subprocess.run(["bash", "-s"], input=mh.PROBE_SCRIPT, capture_output=True, text=True,
                         env={**os.environ, "HOME": str(tmp_path)}, timeout=30).stdout
    p = mh.parse_probe(out)
    assert p["heads"] == {".agents": "", ".claude": ""} and p["errors"] == []
    assert mh.evaluate(p, _current_lag, NOW.timestamp())[0] == "red"   # no repos on a mirror is a broken mirror


# ── how far behind, measured in real git repos ─────────────────────────────────────────────────────────────────────

def _git(repo: Path, *args, when: datetime | None = None) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    if when is not None:
        stamp = f"{int(when.timestamp())} +0000"
        env.update(GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env=env).stdout.strip()


def _commit(repo: Path, msg: str, when: datetime) -> str:
    (repo / "f.txt").write_text(msg)
    _git(repo, "add", "f.txt", when=when)
    _git(repo, "commit", "-q", "-m", msg, when=when)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def origin_and_mac(tmp_path):
    """An upstream repo and this Mac's clone of it, whose origin/main reflog records when each fetch landed."""
    up = tmp_path / "upstream"
    _git(up, "init", "-q", "-b", "main")
    first = _commit(up, "one", NOW - timedelta(days=5))
    mac = tmp_path / "mac"
    subprocess.run(["git", "clone", "-q", str(up), str(mac)], check=True, capture_output=True)
    return up, mac, first


def test_a_box_at_this_macs_origin_is_not_behind(origin_and_mac):
    _up, mac, first = origin_and_mac
    assert mh.local_lag(mac, first) == {"known": True, "missing": 0, "since": None}


def test_behind_since_is_when_the_commits_arrived_here_not_their_commit_date(origin_and_mac):
    # code-sync fast-forwards: a laptop's 3-day-old commits can land on the Mini minutes ago. The box is 5 min late,
    # not 3 days late, and must not read red.
    up, mac, first = origin_and_mac
    _commit(up, "two", NOW - timedelta(days=3))
    _commit(up, "three", NOW - timedelta(days=3))
    _git(mac, "fetch", "-q", "origin", when=NOW - timedelta(minutes=5))
    lag = mh.local_lag(mac, first)
    assert lag["known"] and lag["missing"] == 2
    assert lag["since"] == pytest.approx((NOW - timedelta(minutes=5)).timestamp())


def test_behind_since_is_the_oldest_arrival_the_box_still_lacks(origin_and_mac):
    up, mac, first = origin_and_mac
    _commit(up, "two", NOW - timedelta(hours=5))
    _git(mac, "fetch", "-q", "origin", when=NOW - timedelta(hours=4))
    _commit(up, "three", NOW - timedelta(hours=1))
    _git(mac, "fetch", "-q", "origin", when=NOW - timedelta(hours=1))
    lag = mh.local_lag(mac, first)
    assert lag["missing"] == 2
    assert lag["since"] == pytest.approx((NOW - timedelta(hours=4)).timestamp())


def test_a_box_that_caught_up_part_way_is_judged_from_what_it_still_lacks(origin_and_mac):
    up, mac, _first = origin_and_mac
    two = _commit(up, "two", NOW - timedelta(hours=5))
    _git(mac, "fetch", "-q", "origin", when=NOW - timedelta(hours=4))
    _commit(up, "three", NOW - timedelta(minutes=20))
    _git(mac, "fetch", "-q", "origin", when=NOW - timedelta(minutes=20))
    lag = mh.local_lag(mac, two)
    assert lag["missing"] == 1
    assert lag["since"] == pytest.approx((NOW - timedelta(minutes=20)).timestamp())


def test_with_no_reflog_it_falls_back_to_commit_dates(origin_and_mac):
    up, mac, first = origin_and_mac
    _commit(up, "two", NOW - timedelta(hours=6))
    _git(mac, "fetch", "-q", "origin", when=NOW - timedelta(hours=1))
    _git(mac, "reflog", "expire", "--expire=all", "--all")
    lag = mh.local_lag(mac, first)
    assert lag["missing"] == 1
    assert lag["since"] == pytest.approx((NOW - timedelta(hours=6)).timestamp())


def test_a_head_this_mac_has_never_seen_is_unknown(origin_and_mac):
    _up, mac, _first = origin_and_mac
    assert mh.local_lag(mac, "f" * 40)["known"] is False


def test_a_garbage_head_is_unknown_not_an_injection(origin_and_mac, tmp_path):
    # The box's output is the box's to garble; it never reaches a shell here and a bad value is just "unknown".
    _up, mac, _first = origin_and_mac
    for bad in ("--upload-pack=touch pwned", "HEAD;rm -rf /", "../../etc", "main"):
        assert mh.local_lag(mac, bad)["known"] is False
    assert not (tmp_path / "pwned").exists()


def test_a_missing_local_repo_is_unknown(tmp_path):
    assert mh.local_lag(tmp_path / "nope", SHA_A)["known"] is False
