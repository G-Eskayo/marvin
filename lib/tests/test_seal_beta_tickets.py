"""Tests for seal_beta_tickets.py (marvin#409). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_seal_beta_tickets.py -v
"""
from __future__ import annotations

import copy
import json
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import seal_beta_tickets as sbt
import seal_beta_ingest as sbi

NOW = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)


class FakeGitHub:
    """In-memory GitHub state for testing issue creation/search/comment."""

    def __init__(self):
        self.issues = {}
        self.next_number = 1
        self.calls = []
        self.should_fail = None

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)

        if self.should_fail and self.should_fail(args):
            raise RuntimeError(f"FakeGitHub: simulated failure for {args[0]}")

        if args[0] == "issue" and args[1] == "create":
            title = None
            body = None
            i = 2
            while i < len(args):
                if args[i] == "--title":
                    title = args[i + 1]
                    i += 2
                elif args[i] == "--body":
                    body = args[i + 1]
                    i += 2
                else:
                    i += 1

            number = self.next_number
            self.next_number += 1
            self.issues[number] = {
                "number": number,
                "title": title,
                "body": body,
                "state": "OPEN",
                "comments": [],
            }
            repo = "G-Eskayo/clarity-captions"
            for idx, arg in enumerate(args):
                if arg == "--repo" and idx + 1 < len(args):
                    repo = args[idx + 1]
                    break
            return f"https://github.com/{repo}/issues/{number}\n"

        elif args[0] == "issue" and args[1] == "list":
            state = "open"
            search = None
            i = 2
            while i < len(args):
                if args[i] == "--state":
                    state = args[i + 1]
                    i += 2
                elif args[i] == "--search":
                    search = args[i + 1]
                    i += 2
                else:
                    i += 1

            results = []
            search_term = None
            if search:
                match = re.match(r'"([^"]*)"', search)
                search_term = match.group(1) if match else search

            for issue in self.issues.values():
                if state.lower() in ("open", "all") and issue["state"] == "OPEN":
                    if search_term is None or search_term in (issue.get("body") or ""):
                        results.append({"number": issue["number"], "title": issue["title"], "body": issue.get("body")})
                elif state.lower() == "closed" and issue["state"] == "CLOSED":
                    if search_term is None or search_term in (issue.get("body") or ""):
                        results.append({"number": issue["number"], "title": issue["title"], "body": issue.get("body")})

            return json.dumps(results)

        elif args[0] == "issue" and args[1] == "comment":
            number = int(args[2])
            body = None
            i = 4
            while i < len(args):
                if args[i] == "--body":
                    body = args[i + 1]
                    i += 2
                else:
                    i += 1

            if number in self.issues:
                self.issues[number]["comments"].append({"body": body})
                return json.dumps({"body": body})
            raise RuntimeError(f"Issue {number} not found")

        elif args[0] == "issue" and args[1] == "edit":
            number = int(args[2])
            if number in self.issues:
                return json.dumps(self.issues[number])
            raise RuntimeError(f"Issue {number} not found")

        return "{}"


def conv(id_, *, rating=8, p95=0.6, ending="userStop", os="iOS 27.0", note=None):
    c = copy.deepcopy(sbi.REAL["conversations"][0])
    c.update(id=id_, rating=rating, note=note)
    c["lag"] = {"p50Seconds": 0.3, "p95Seconds": p95, "samples": 900}
    c["ending"] = {"kind": ending}
    return c


def report(convs, *, model="iPhone15,4", build="3", os_str="iOS 27.0"):
    r = copy.deepcopy(sbi.REAL)
    r["conversations"] = convs
    r["device"]["model"] = model
    r["device"]["os"] = os_str
    r["app"]["build"] = build
    return r


def make_summary(devices: list[dict]) -> dict:
    """Construct a summary dict matching seal_beta_ingest's output shape."""
    return {
        "generated_at": NOW.isoformat(),
        "totals": {"conversations": 0, "reports": 0, "devices": len(devices)},
        "by_device": devices,
        "by_build": [],
    }


def device_entry(name="iPhone 15", *, lag_p95=0.8, rating=7, endings=None, conversations=10, reports=2, os_versions=None, build="3"):
    if endings is None:
        endings = {"userStop": conversations}
    if os_versions is None:
        os_versions = ["iOS 27.0"]
    return {
        "device": name,
        "model_ids": ["iPhone15,4"],
        "conversations": conversations,
        "reports": reports,
        "low_sample": 0,
        "rated": conversations,
        "skipped": 0,
        "unrated": 0,
        "median_rating": rating,
        "lag_p50": 0.3,
        "lag_p95": lag_p95,
        "rewrite_rate": 0.1,
        "relabels_per_min": 0.5,
        "battery_drop_per_30min": 3.0,
        "max_thermal": "nominal",
        "endings": endings,
        "minutes_total": 100.0,
        "os_versions": os_versions,
        "builds": [{"build": build, "conversations": conversations, "lag_p95": lag_p95, "median_rating": rating,
                    "endings": endings, "os_versions": os_versions}],
        "notes": [],
    }


@pytest.fixture
def paths(tmp_path):
    att = tmp_path / "Attachments"
    att.mkdir()
    store = tmp_path / "seal-beta"
    store.mkdir()
    return att, store


# ── threshold detection ───────────────────────────────────────────────────────

def test_high_lag_detected(tmp_path):
    summary = make_summary([device_entry(lag_p95=2.5)])
    (tmp_path / "summary.json").write_text(json.dumps(summary))
    breaches = sbt.detect_breaches(summary)
    assert len(breaches) == 1
    assert breaches[0]["problem"] == "lag"
    assert breaches[0]["measurements"]["lag_p95"] == 2.5


def test_poor_rating_detected(tmp_path):
    summary = make_summary([device_entry(rating=4.0)])
    breaches = sbt.detect_breaches(summary)
    assert len(breaches) == 1
    assert breaches[0]["problem"] == "rating"
    assert breaches[0]["measurements"]["median_rating"] == 4.0


def test_stuck_endings_detected(tmp_path):
    summary = make_summary([device_entry(conversations=10, endings={"stuck": 4, "userStop": 6})])
    breaches = sbt.detect_breaches(summary)
    assert len(breaches) == 1
    assert breaches[0]["problem"] == "ending"
    assert breaches[0]["measurements"]["stuck_pct"] == 40.0


def test_three_problems_on_one_device_file_three_breaches():
    summary = make_summary([device_entry(lag_p95=2.5, rating=4.0, endings={"stuck": 4, "userStop": 6})])
    breaches = sbt.detect_breaches(summary)
    assert len(breaches) == 3
    problems = {b["problem"] for b in breaches}
    assert problems == {"lag", "rating", "ending"}


def test_no_thresholds_crossed():
    summary = make_summary([device_entry(lag_p95=1.0, rating=8.0, endings={"userStop": 10})])
    breaches = sbt.detect_breaches(summary)
    assert len(breaches) == 0


def test_malformed_summary_returns_empty_breaches():
    assert sbt.detect_breaches({}) == []
    assert sbt.detect_breaches({"by_device": "not a list"}) == []
    assert sbt.detect_breaches({"by_device": []}) == []
    assert sbt.detect_breaches({"by_device": [{"device": "A"}]}) == []  # missing required fields is ok


# ── rendering ─────────────────────────────────────────────────────────────────

def test_lag_breach_renders_with_measurements():
    breach = {
        "device": "iPhone 15",
        "problem": "lag",
        "measurements": {
            "device_name": "iPhone 15",
            "os_versions": ["iOS 27.0"],
            "build": "3",
            "lag_p95": 2.5,
            "median_rating": 7.0,
            "stuck_pct": 10.0,
            "conversations": 10,
            "reports": 2,
        }
    }
    title = sbt.render_title(breach)
    assert "high latency" in title
    assert "iPhone 15" in title
    assert "build 3" in title

    body = sbt.render_body(breach)
    assert "<!-- marvin:seal-beta:iphone15:lag -->" in body
    assert "2.5" in body
    assert ">2.0s" in body


def test_rating_breach_renders():
    breach = {
        "device": "iPhone 15",
        "problem": "rating",
        "measurements": {
            "device_name": "iPhone 15",
            "os_versions": ["iOS 27.0", "iOS 27.1"],
            "build": "4",
            "lag_p95": 0.8,
            "median_rating": 3.5,
            "stuck_pct": 10.0,
            "conversations": 20,
            "reports": 3,
        }
    }
    title = sbt.render_title(breach)
    assert "poor rating" in title

    body = sbt.render_body(breach)
    assert "<!-- marvin:seal-beta:iphone15:rating -->" in body
    assert "3.5" in body


def test_ending_breach_renders():
    breach = {
        "device": "iPhone 17 Pro",
        "problem": "ending",
        "measurements": {
            "device_name": "iPhone 17 Pro",
            "os_versions": ["iOS 27.0"],
            "build": "2",
            "lag_p95": 0.5,
            "median_rating": 8.0,
            "stuck_pct": 45.0,
            "conversations": 20,
            "reports": 2,
        }
    }
    title = sbt.render_title(breach)
    assert "abnormal endings" in title

    body = sbt.render_body(breach)
    assert "45.0%" in body


def test_sanitization_in_body_marker():
    breach = {
        "device": "iPhone 15 (fake\"marker)",
        "problem": "lag",
        "measurements": {
            "device_name": "iPhone 15 (fake\"marker)",
            "os_versions": [],
            "build": "3",
            "lag_p95": 2.5,
            "median_rating": 7.0,
            "stuck_pct": 0,
            "conversations": 10,
            "reports": 1,
        }
    }
    body = sbt.render_body(breach)
    assert "-->" not in body or body.count("-->") == 1  # marker closes properly, no injection
    assert '<!-- marvin:seal-beta:iphone15fakemarker:lag -->' in body


def test_update_comment_renders():
    breach = {
        "device": "iPhone 15",
        "problem": "lag",
        "measurements": {
            "device_name": "iPhone 15",
            "os_versions": ["iOS 27.0"],
            "build": "3",
            "lag_p95": 2.2,
            "median_rating": 7.0,
            "stuck_pct": 10.0,
            "conversations": 15,
            "reports": 2,
        }
    }
    comment = sbt.render_update_comment(breach)
    assert "Updated metrics:" in comment
    assert "2.2" in comment
    assert "15" in comment


# ── GitHub interaction ────────────────────────────────────────────────────────

def test_same_breach_on_later_run_updates_not_duplicates():
    gh = FakeGitHub()

    breach1 = {
        "device": "iPhone 15",
        "problem": "lag",
        "measurements": {
            "device_name": "iPhone 15",
            "os_versions": ["iOS 27.0"],
            "build": "3",
            "lag_p95": 2.5,
            "median_rating": 7.0,
            "stuck_pct": 10.0,
            "conversations": 10,
            "reports": 2,
        }
    }

    res1 = sbt.file_or_update(breach1, "test/repo", gh, mode="act")
    assert res1["status"] == "created"
    assert len(gh.issues) == 1

    breach2 = copy.deepcopy(breach1)
    breach2["measurements"]["lag_p95"] = 2.7
    res2 = sbt.file_or_update(breach2, "test/repo", gh, mode="act")
    assert res2["status"] == "updated"
    assert len(gh.issues) == 1  # still only one issue


def test_closed_issue_is_not_reused():
    gh = FakeGitHub()
    breach = {
        "device": "iPhone 15",
        "problem": "lag",
        "measurements": {
            "device_name": "iPhone 15",
            "os_versions": ["iOS 27.0"],
            "build": "3",
            "lag_p95": 2.5,
            "median_rating": 7.0,
            "stuck_pct": 10.0,
            "conversations": 10,
            "reports": 2,
        }
    }

    res1 = sbt.file_or_update(breach, "test/repo", gh, mode="act")
    assert res1["status"] == "created"
    issue_num = res1["issue"]

    gh.issues[issue_num]["state"] = "CLOSED"

    res2 = sbt.file_or_update(breach, "test/repo", gh, mode="act")
    assert res2["status"] == "created"
    assert len(gh.issues) == 2


def test_propose_mode_never_calls_create():
    gh = FakeGitHub()
    breach = {
        "device": "iPhone 15",
        "problem": "lag",
        "measurements": {
            "device_name": "iPhone 15",
            "os_versions": ["iOS 27.0"],
            "build": "3",
            "lag_p95": 2.5,
            "median_rating": 7.0,
            "stuck_pct": 10.0,
            "conversations": 10,
            "reports": 2,
        }
    }

    res = sbt.file_or_update(breach, "test/repo", gh, mode="propose")
    assert res["status"] == "deferred"
    assert len([c for c in gh.calls if "create" in c]) == 0


def test_rate_limit_error_defers_not_fails():
    class RateLimitException(Exception):
        def __init__(self, msg):
            super().__init__(msg)
            self.returncode = 75

    class RateLimitGitHub(FakeGitHub):
        def __call__(self, args):
            if "issue" in args and "create" in args:
                raise RateLimitException("API rate limit exceeded; rc=75")
            return super().__call__(args)

    gh = RateLimitGitHub()

    breach = {
        "device": "iPhone 15",
        "problem": "lag",
        "measurements": {
            "device_name": "iPhone 15",
            "os_versions": ["iOS 27.0"],
            "build": "3",
            "lag_p95": 2.5,
            "median_rating": 7.0,
            "stuck_pct": 10.0,
            "conversations": 10,
            "reports": 2,
        }
    }

    res = sbt.file_or_update(breach, "test/repo", gh, mode="act")
    assert res["status"] == "deferred"


def test_other_errors_fail():
    gh = FakeGitHub()

    def fail_with_auth(*args):
        raise RuntimeError("GitHub error 401 Unauthorized")

    gh.should_fail = fail_with_auth

    breach = {
        "device": "iPhone 15",
        "problem": "lag",
        "measurements": {
            "device_name": "iPhone 15",
            "os_versions": ["iOS 27.0"],
            "build": "3",
            "lag_p95": 2.5,
            "median_rating": 7.0,
            "stuck_pct": 10.0,
            "conversations": 10,
            "reports": 2,
        }
    }

    res = sbt.file_or_update(breach, "test/repo", gh, mode="act")
    assert res["status"] == "failed"
    assert "error" in res


# ── main run ───────────────────────────────────────────────────────────────────

def test_no_summary_yet_is_clean_noop(tmp_path):
    result = sbt.run(store_dir=tmp_path / "store")
    assert result["processed"] == 0
    assert result["breaches"] == 0
    assert result["ok"]


def test_two_overlapping_runs_do_not_double_file(paths):
    store = paths[1]
    summary = make_summary([device_entry(lag_p95=2.5)])
    (store / "summary.json").write_text(json.dumps(summary))

    gh = FakeGitHub()
    results = []

    def run_with_delay():
        result = sbt.run(store_dir=store, gh=gh, mode="act")
        results.append(result)

    t1 = threading.Thread(target=run_with_delay)
    t2 = threading.Thread(target=run_with_delay)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(gh.issues) == 1
    assert sum(r["created"] for r in results) == 1


def test_max_tickets_per_run(tmp_path):
    devices = [device_entry(f"Device {i}", lag_p95=2.5) for i in range(15)]
    summary = make_summary(devices)
    (tmp_path / "summary.json").write_text(json.dumps(summary))

    gh = FakeGitHub()
    result = sbt.run(store_dir=tmp_path, gh=gh)

    assert result["breaches"] == 15
    assert result["processed"] == sbt.MAX_TICKETS_PER_RUN
    assert result["deferred"] >= 5


def test_batch_processing_with_multiple_breaches(tmp_path):
    gh = FakeGitHub()

    summary = make_summary([
        device_entry("Device 1", lag_p95=2.5),
        device_entry("Device 2", lag_p95=2.5),
        device_entry("Device 3", lag_p95=2.5),
    ])

    (tmp_path / "summary.json").write_text(json.dumps(summary))
    result = sbt.run(store_dir=tmp_path, gh=gh, mode="act")

    assert result["created"] >= 3
    assert len(gh.issues) >= 3


# ── new tests for plan fixes ──────────────────────────────────────────────────

@pytest.fixture
def monkeypatch_paths(monkeypatch, tmp_path):
    """Monkeypatch CONFIG_PATH and PROPOSALS_PATH for tests that call run()."""
    config_path = tmp_path / "config.json"
    proposals_path = tmp_path / "proposals.json"
    monkeypatch.setattr(sbt, "CONFIG_PATH", config_path)
    monkeypatch.setattr(sbt, "PROPOSALS_PATH", proposals_path)
    return config_path, proposals_path


def test_4_parse_issue_number_from_url(monkeypatch_paths):
    """Test 4: parse issue number from gh issue create URL output."""
    gh = FakeGitHub()
    breach = {
        "device": "iPhone 15",
        "problem": "lag",
        "measurements": {
            "device_name": "iPhone 15",
            "os_versions": ["iOS 27.0"],
            "build": "3",
            "lag_p95": 2.5,
            "median_rating": 7.0,
            "stuck_pct": 10.0,
            "conversations": 10,
            "reports": 2,
        }
    }
    res = sbt.file_or_update(breach, "test/repo", gh, mode="act")
    assert res["status"] == "created"
    assert isinstance(res["issue"], int)
    assert res["issue"] == 1


def test_5_find_existing_raises_not_returns_none():
    """Test 5: find_existing raises on gh errors, doesn't catch them."""
    gh = FakeGitHub()

    def fail_with_auth(*args):
        raise RuntimeError("GitHub error 401 Unauthorized")

    gh.should_fail = fail_with_auth

    with pytest.raises(RuntimeError, match="Unauthorized"):
        sbt.find_existing("test-marker", "test/repo", gh)


def test_6_find_existing_defers_on_rate_limit():
    """Test 6: file_or_update defers if find_existing hits rate limit."""
    class RateLimitException(Exception):
        def __init__(self, msg):
            super().__init__(msg)
            self.returncode = 75

    class RateLimitGitHub(FakeGitHub):
        def __call__(self, args):
            if "issue" in args and "list" in args:
                raise RateLimitException("API rate limit exceeded; rc=75")
            return super().__call__(args)

    gh = RateLimitGitHub()

    breach = {
        "device": "iPhone 15",
        "problem": "lag",
        "measurements": {
            "device_name": "iPhone 15",
            "os_versions": ["iOS 27.0"],
            "build": "3",
            "lag_p95": 2.5,
            "median_rating": 7.0,
            "stuck_pct": 10.0,
            "conversations": 10,
            "reports": 2,
        }
    }

    res = sbt.file_or_update(breach, "test/repo", gh, mode="act")
    assert res["status"] == "deferred"


def test_7_no_lock_cleanup(monkeypatch_paths, tmp_path):
    """Test 7: lock file is not deleted after run (mirrors seal_beta_ingest behavior)."""
    store = tmp_path / "store"
    store.mkdir()
    summary = make_summary([device_entry(lag_p95=2.5)])
    (store / "summary.json").write_text(json.dumps(summary))

    gh = FakeGitHub()
    sbt.run(store_dir=store, gh=gh, mode="act")

    lock_path = store / ".tickets-lock"
    assert lock_path.exists(), "lock file should not be deleted"


def test_8_early_returns_include_mode(monkeypatch_paths, tmp_path):
    """Test 8: all early-return dicts from run() include 'mode' field."""
    store = tmp_path / "store"
    store.mkdir()

    # No summary.json case
    result = sbt.run(store_dir=store, mode="propose")
    assert "mode" in result
    assert result["mode"] == "propose"

    # Bad JSON case
    (store / "summary.json").write_text("not json")
    result = sbt.run(store_dir=store, mode="act")
    assert "mode" in result
    assert result["mode"] == "act"


def test_9_malformed_device_entry_skipped():
    """Test 9: detect_breaches skips non-dict device entries and non-dict endings, non-numeric metrics."""
    summary = make_summary([
        device_entry(lag_p95=2.5),  # valid
        "not a dict",  # skip
        {"device": "Test", "lag_p95": "not a number"},  # skip malformed lag_p95
        {"device": "Test", "endings": "not a dict", "median_rating": 4.0, "conversations": 10, "reports": 2},  # skip bad endings
    ])
    breaches = sbt.detect_breaches(summary)
    assert len(breaches) == 1
    assert breaches[0]["device"] == device_entry(lag_p95=2.5)["device"]


def test_13_malformed_summary_with_missing_by_device():
    """Test 13: detect_breaches handles edge cases (missing by_device, empty list, etc.)."""
    assert sbt.detect_breaches(None) == []
    assert sbt.detect_breaches({}) == []
    assert sbt.detect_breaches({"by_device": None}) == []
    assert sbt.detect_breaches({"by_device": "not a list"}) == []


def test_21_rating_breach_with_min_reports_gate(monkeypatch_paths):
    """Test 21: rating breach requires >= MIN_REPORTS_FOR_RATING reports."""
    # Only 1 report: no breach even though rating < 5.0
    summary = make_summary([device_entry(rating=4.0, reports=1, conversations=5)])
    breaches = sbt.detect_breaches(summary)
    assert len(breaches) == 0

    # >= 2 reports: breach triggered
    summary = make_summary([device_entry(rating=4.0, reports=2, conversations=5)])
    breaches = sbt.detect_breaches(summary)
    assert len(breaches) == 1
    assert breaches[0]["problem"] == "rating"


def test_22_stuck_ending_breach_detects_any_stuck():
    """Test 22: stuck ending breach triggered by any literal 'stuck' count > 0."""
    # Exactly the old percentage would be 10%, well under 30%: old code no breach, new code breach
    summary = make_summary([device_entry(conversations=10, endings={"stuck": 1, "userStop": 9})])
    breaches = sbt.detect_breaches(summary)
    assert len(breaches) == 1
    assert breaches[0]["problem"] == "ending"
    assert breaches[0]["measurements"]["stuck_pct"] == 10.0  # shown for context

    # Zero stuck: no breach
    summary = make_summary([device_entry(conversations=10, endings={"userStop": 10})])
    breaches = sbt.detect_breaches(summary)
    assert len(breaches) == 0


def test_median_rating_at_half_point_does_not_breach_ADR_threshold():
    """Test 1: median_rating exactly at 4.0 breaches; 4.5 and 4.9 do not."""
    # 4.0 should breach (<=)
    summary = make_summary([device_entry(rating=4.0, reports=2, conversations=5)])
    breaches = sbt.detect_breaches(summary)
    assert len(breaches) == 1
    assert breaches[0]["problem"] == "rating"
    assert breaches[0]["measurements"]["median_rating"] == 4.0

    # 4.5 should NOT breach (> 4)
    summary = make_summary([device_entry(rating=4.5, reports=2, conversations=5)])
    breaches = sbt.detect_breaches(summary)
    assert len(breaches) == 0

    # 4.9 should NOT breach (> 4)
    summary = make_summary([device_entry(rating=4.9, reports=2, conversations=5)])
    breaches = sbt.detect_breaches(summary)
    assert len(breaches) == 0

    # 3.0 should breach (< 4)
    summary = make_summary([device_entry(rating=3.0, reports=2, conversations=5)])
    breaches = sbt.detect_breaches(summary)
    assert len(breaches) == 1
    assert breaches[0]["problem"] == "rating"


def test_note_with_name_and_phone_number_never_reaches_rendered_ticket(tmp_path):
    """Test 2: notes with PII (name, phone) in summary don't leak into rendered issue body."""
    # Create a device entry with a note containing PII
    device = device_entry(name="iPhone 15", rating=4.0, reports=2, conversations=5)
    device["notes"] = [
        {
            "timestamp": "2026-10-13T18:00:00Z",
            "note": "User: John Smith, Phone: 555-1234. App crashed on startup.",
        }
    ]
    summary = make_summary([device])
    breaches = sbt.detect_breaches(summary)
    assert len(breaches) == 1
    breach = breaches[0]

    # Render the issue body
    body = sbt.render_body(breach)

    # Ensure PII from notes does not appear in the body
    # (The render_body function should only use measurements, not device["notes"])
    assert "John Smith" not in body
    assert "555-1234" not in body
    assert "crashed" not in body  # The note text itself


def test_gate_refusal_on_one_breach_leaves_batch_and_proposals_consistent(monkeypatch_paths, tmp_path):
    """Test 3: when one breach fails, batch state and proposals remain consistent."""
    store = tmp_path / "store"
    store.mkdir()

    # Create a summary with two breaches: one will succeed, one will be refused
    summary = make_summary([
        device_entry("Device 1", lag_p95=2.5),  # lag breach
        device_entry("Device 2", rating=3.0, reports=2),  # rating breach
    ])
    (store / "summary.json").write_text(json.dumps(summary))

    # GitHub mock that refuses the second breach's creation (rate limit)
    class SelectiveFailGitHub(FakeGitHub):
        def __init__(self):
            super().__init__()
            self.call_count = 0

        def __call__(self, args):
            self.call_count += 1
            # Fail on the second issue create (for Device 2)
            if "issue" in args and "create" in args and self.call_count == 2:
                class RateLimitException(Exception):
                    def __init__(self):
                        super().__init__("rate limit")
                        self.returncode = 75
                raise RateLimitException()
            return super().__call__(args)

    gh = SelectiveFailGitHub()
    config_path, proposals_path = monkeypatch_paths

    result = sbt.run(store_dir=store, gh=gh, mode="act")

    # Verify results: one created, one deferred
    assert result["created"] >= 1
    assert result["deferred"] >= 1
    assert result["processed"] == result["created"] + result["deferred"] + result["failed"]

    # Verify proposals file was written and is consistent
    assert proposals_path.exists(), "proposals file should be written"
    proposals_data = json.loads(proposals_path.read_text())
    assert "proposals" in proposals_data
    assert len(proposals_data["proposals"]) == result["processed"]

    # Each proposal should have device, problem, outcome
    for proposal in proposals_data["proposals"]:
        assert "device" in proposal
        assert "problem" in proposal
        assert "outcome" in proposal
        outcome = proposal["outcome"]
        assert "status" in outcome
        assert outcome["status"] in ("created", "deferred", "failed")
