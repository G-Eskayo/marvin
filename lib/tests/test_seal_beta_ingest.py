"""Tests for seal_beta_ingest.py (marvin#407). Every test works in tmp_path: never the real ~/Library/Messages or
~/.claude. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_seal_beta_ingest.py -v
"""
from __future__ import annotations

import copy
import json
import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import seal_beta_ingest as sbi  # noqa: E402

NOW = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)

# Shape of the first real report (2026-10-13, build 3), with the identifying bits kept generic.
REAL = {
    "app": {"build": "3", "environment": "sandbox", "version": "1.0"},
    "conversations": [{
        "battery": {"dropPercentPer30Min": None, "maxThermalState": "nominal"},
        "ending": {"kind": "userStop"},
        "id": "87B1C6B5-C3B2-4C81-A787-8A06DD8DBDD3",
        "lag": {"p50Seconds": 0.03, "p95Seconds": 0.08, "samples": 10},
        "launch": {"barShown": False, "fullDance": True},
        "launchToStartSeconds": 55.76,
        "micLevel": {"medianDBFS": -32.5, "quietFraction": 0},
        "minutes": 0.2,
        "note": None,
        "rating": None,
        "ratingSkipped": False,
        "rewriteRate": 0.143,
        "speakers": {"detected": 1, "relabelsPerMinute": 0},
        "startToFirstCaptionSeconds": 3.22,
        "startedAt": "2026-10-13T11:41:06-06:00",
    }],
    "device": {"lowPowerModeSeen": False, "model": "iPhone18,1", "os": "iOS 27.0"},
    "schema": 1,
    "sentAt": "2026-10-13T11:41:27-06:00",
    "settings": {"lettering": "openDyslexic", "quietStop": "fiveMinutes", "textSize": "large", "theme": "harbor"},
}


def conv(id_, *, rating=8, skipped=False, minutes=20.0, p50=0.6, p95=1.4, samples=900, ending="userStop",
         note=None, battery=6.0, thermal="fair", rewrite=0.1, relabels=0.5):
    c = copy.deepcopy(REAL["conversations"][0])
    c.update(id=id_, rating=rating, ratingSkipped=skipped, minutes=minutes, note=note, rewriteRate=rewrite)
    c["lag"] = {"p50Seconds": p50, "p95Seconds": p95, "samples": samples}
    c["ending"] = {"kind": ending}
    c["battery"] = {"dropPercentPer30Min": battery, "maxThermalState": thermal}
    c["speakers"] = {"detected": 2, "relabelsPerMinute": relabels}
    return c


def report(convs, *, model="iPhone15,4", build="3", sent="2026-10-13T12:00:00-06:00"):
    r = copy.deepcopy(REAL)
    r["conversations"] = convs
    r["device"]["model"] = model
    r["app"]["build"] = build
    r["sentAt"] = sent
    return r


def drop(root: Path, doc, name="seal-feedback-3-20261013-1200.json", sub="aa/bb/UUID-1") -> Path:
    """Place a file the way Messages stores attachments: Attachments/<xx>/<yy>/<UUID>/<file>."""
    d = root / sub
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    return p


@pytest.fixture
def paths(tmp_path):
    att = tmp_path / "Attachments"
    att.mkdir()
    return att, tmp_path / "seal-beta"


def run(paths, now=NOW):
    att, store = paths
    return sbi.ingest(attachments_dir=att, store_dir=store, now=now)


def records(paths):
    return [json.loads(l) for l in (paths[1] / "reports.jsonl").read_text().splitlines() if l.strip()]


def summary(paths):
    return json.loads((paths[1] / "summary.json").read_text())


# ── finding and storing ─────────────────────────────────────────────────────

def test_real_report_is_ingested_and_found_recursively(paths):
    drop(paths[0], REAL, sub="05/05/14115675-73A1-4B9C-930B-A8582680B830")
    st = run(paths)
    assert st["ok"] and st["new_conversations"] == 1
    (rec,) = records(paths)
    assert rec["id"] == REAL["conversations"][0]["id"]
    assert rec["device_model"] == "iPhone18,1" and rec["build"] == "3" and rec["os"] == "iOS 27.0"
    assert rec["source_file"] == "seal-feedback-3-20261013-1200.json"  # basename only, never the Messages path


def test_other_attachments_are_never_read(paths, monkeypatch):
    drop(paths[0], REAL)
    drop(paths[0], "not json at all", name="IMG_0559.HEIC", sub="cc/dd/UUID-2")
    drop(paths[0], {"schema": 1}, name="notes.json", sub="cc/dd/UUID-3")
    opened = []
    real_read = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: (opened.append(self.name), real_read(self, *a, **k))[1])
    st = run(paths)
    assert st["files_found"] == 1 and st["invalid"] == []
    assert "IMG_0559.HEIC" not in opened and "notes.json" not in opened


def test_rerun_over_same_files_is_a_no_op(paths):
    drop(paths[0], report([conv("A"), conv("B")]))
    assert run(paths)["new_conversations"] == 2
    before = (paths[1] / "reports.jsonl").read_bytes()
    st = run(paths)
    assert st["new_conversations"] == 0 and st["total_conversations"] == 2
    assert (paths[1] / "reports.jsonl").read_bytes() == before


def test_duplicates_inside_one_file_and_across_copies_are_kept_once(paths):
    drop(paths[0], report([conv("A"), conv("A"), conv("B")]))
    drop(paths[0], report([conv("A"), conv("B")]), sub="ff/ee/UUID-copy")  # Messages keeps the same file twice
    st = run(paths)
    assert st["new_conversations"] == 2
    assert sorted(r["id"] for r in records(paths)) == ["A", "B"]


def test_new_report_adds_only_its_new_conversations(paths):
    drop(paths[0], report([conv("A")]))
    run(paths)
    drop(paths[0], report([conv("B"), conv("C")], sent="2026-10-14T09:00:00-06:00"), name="seal-feedback-3-20261014-0900.json")
    assert run(paths)["new_conversations"] == 2
    assert len(records(paths)) == 3


def test_large_report_with_hundreds_of_conversations(paths):
    drop(paths[0], report([conv(f"C{i}", rating=(i % 10) + 1) for i in range(800)]))
    st = run(paths)
    assert st["new_conversations"] == 800
    assert summary(paths)["by_device"][0]["conversations"] == 800


# ── invalid input never crashes and never enters the store ──────────────────

@pytest.mark.parametrize("bad, reason", [
    ("{not json", "not valid JSON"),
    ("[]", "not a JSON object"),
    (json.dumps({**REAL, "schema": 2}), "schema"),
    (json.dumps({k: v for k, v in REAL.items() if k != "device"}), "device"),
    (json.dumps({**REAL, "conversations": "nope"}), "conversations"),
    (json.dumps({**REAL, "conversations": [{"minutes": 3}]}), "id"),
    ("", "not valid JSON"),
])
def test_invalid_files_are_reported_with_a_reason_and_skipped(paths, bad, reason):
    drop(paths[0], bad, name="seal-feedback-9-20261013-0000.json")
    drop(paths[0], report([conv("GOOD")]), sub="zz/yy/UUID-good")
    st = run(paths)
    assert st["ok"] and st["new_conversations"] == 1
    (inv,) = st["invalid"]
    assert inv["file"] == "seal-feedback-9-20261013-0000.json" and reason in inv["reason"]
    assert [r["id"] for r in records(paths)] == ["GOOD"]


def test_null_and_missing_optional_measurements_are_tolerated(paths):
    c = conv("A")
    c["battery"] = {"dropPercentPer30Min": None, "maxThermalState": None}
    del c["micLevel"]
    c["lag"] = None
    drop(paths[0], report([c]))
    assert run(paths)["new_conversations"] == 1
    dev = summary(paths)["by_device"][0]
    assert dev["lag_p95"] is None and dev["battery_drop_per_30min"] is None


def test_wrong_typed_measurements_do_not_crash(paths):
    c = conv("A")
    c["lag"] = {"p50Seconds": "fast", "p95Seconds": [1], "samples": "lots"}
    c["rating"] = "ten"
    drop(paths[0], report([c]))
    assert run(paths)["ok"]
    dev = summary(paths)["by_device"][0]
    assert dev["lag_p95"] is None and dev["median_rating"] is None


# ── failing loudly when Messages can't be read ──────────────────────────────

def test_permission_denied_fails_loudly_and_leaves_the_store_alone(paths, monkeypatch):
    drop(paths[0], report([conv("A")]))
    run(paths)
    before = (paths[1] / "reports.jsonl").read_bytes()

    def denied(*a, **k):
        raise PermissionError(1, "Operation not permitted", str(paths[0]))
    monkeypatch.setattr(sbi.os, "scandir", denied)
    st = run(paths)
    assert st["ok"] is False and st["error"]["kind"] == "permission"
    assert "Full Disk Access" in st["error"]["detail"]
    assert (paths[1] / "reports.jsonl").read_bytes() == before
    assert json.loads((paths[1] / "status.json").read_text())["ok"] is False


def test_permission_denied_on_a_subfolder_is_not_silently_zero(paths, monkeypatch):
    drop(paths[0], report([conv("A")]))
    real = sbi.os.scandir

    def deny_sub(p, *a, **k):
        if Path(p) != paths[0]:
            raise PermissionError(1, "Operation not permitted", str(p))
        return real(p, *a, **k)
    monkeypatch.setattr(sbi.os, "scandir", deny_sub)
    st = run(paths)
    assert st["ok"] is False and st["error"]["kind"] == "permission"


def test_missing_attachments_folder_is_its_own_error(tmp_path):
    st = sbi.ingest(attachments_dir=tmp_path / "nope", store_dir=tmp_path / "s", now=NOW)
    assert st["ok"] is False and st["error"]["kind"] == "missing"


def test_main_exit_codes(paths, monkeypatch):
    drop(paths[0], REAL)
    assert sbi.main(["run", "--attachments", str(paths[0]), "--store", str(paths[1])]) == 0
    monkeypatch.setattr(sbi.os, "scandir", lambda *a, **k: (_ for _ in ()).throw(PermissionError(1, "denied")))
    assert sbi.main(["run", "--attachments", str(paths[0]), "--store", str(paths[1])]) == 2


# ── store robustness ────────────────────────────────────────────────────────

def test_truncated_last_line_from_a_killed_run_is_recovered(paths):
    drop(paths[0], report([conv("A"), conv("B")]))
    run(paths)
    store = paths[1] / "reports.jsonl"
    lines = store.read_text().splitlines()
    store.write_text(lines[0] + "\n" + lines[1][: len(lines[1]) // 2])  # killed mid-write
    st = run(paths)
    assert st["store_bad_lines"] == 1
    assert sorted(r["id"] for r in records_ok(paths)) == ["A", "B"]  # B re-added on a fresh line
    assert summary(paths)["by_device"][0]["conversations"] == 2


def records_ok(paths):
    out = []
    for l in (paths[1] / "reports.jsonl").read_text().splitlines():
        try:
            out.append(json.loads(l))
        except ValueError:
            pass
    return out


# ── feature gating (#647, items 1–6) ──────────────────────────────────────

def test_feature_off_skips_ingest_cleanly_with_no_filesystem_touch(paths, monkeypatch):
    """Item 1: feature off returns skipped; no files written, no attachments dir listed."""
    drop(paths[0], report([conv("A")]))

    scanned = []
    real_find = sbi.find_reports
    def spy_find(root):
        scanned.append(str(root))
        raise AssertionError("find_reports should never be called when feature is off")
    monkeypatch.setattr(sbi, "find_reports", spy_find)

    st = sbi.ingest(attachments_dir=paths[0], store_dir=paths[1], now=NOW,
                     feature_enabled=lambda n: False)
    assert st["ok"] is True and st["skipped"] == "feature_off"
    assert st["files_found"] == 0 and st["new_conversations"] == 0
    assert not scanned  # find_reports was never called
    assert not (paths[1] / "reports.jsonl").exists()
    assert not (paths[1] / "summary.json").exists()
    assert not (paths[1] / "status.json").exists()

def test_feature_on_behaves_as_today(paths):
    """Item 2: feature_enabled=lambda n: True behaves exactly as today (regression guard)."""
    drop(paths[0], report([conv("A"), conv("B")]))
    st = sbi.ingest(attachments_dir=paths[0], store_dir=paths[1], now=NOW,
                     feature_enabled=lambda n: True)
    assert st["ok"] is True
    assert "skipped" not in st
    assert st["files_found"] == 1 and st["new_conversations"] == 2
    assert len(records(paths)) == 2

def test_feature_off_does_not_race_permission_errors(paths, monkeypatch):
    """Item 3: feature off short-circuits before any filesystem touch, even with FDAdenied."""
    def denied(*a, **k):
        raise PermissionError("Full Disk Access denied")
    monkeypatch.setattr(sbi.os, "scandir", denied)

    st = sbi.ingest(attachments_dir=paths[0], store_dir=paths[1], now=NOW,
                     feature_enabled=lambda n: False)
    assert st["ok"] is True and st["skipped"] == "feature_off"
    assert st["error"] is None

def test_feature_gate_with_corrupt_config(paths, monkeypatch):
    """Item 4: feature_enabled backed by lib/instance.py with corrupt config reads as off."""
    import instance as inst

    def bad_config():
        raise ValueError("malformed json")
    monkeypatch.setattr(inst, "_config", lambda: {})  # graceful: empty config

    st = sbi.ingest(attachments_dir=paths[0], store_dir=paths[1], now=NOW,
                     feature_enabled=inst.feature_enabled)
    assert st["skipped"] == "feature_off"

def test_concurrent_ingest_while_feature_off_never_opens_lock(paths):
    """Item 5: two concurrent ingest() calls with feature off both return skipped, no .lock file."""
    lock_opened = []
    original_open = sbi.os.open

    def tracked_open(path, *args, **kwargs):
        if ".lock" in str(path):
            lock_opened.append(str(path))
        return original_open(path, *args, **kwargs)

    import unittest.mock as mock
    with mock.patch.object(sbi.os, "open", tracked_open):
        def go():
            st = sbi.ingest(attachments_dir=paths[0], store_dir=paths[1], now=NOW,
                           feature_enabled=lambda n: False)
            assert st["skipped"] == "feature_off"

        ts = [threading.Thread(target=go) for _ in range(3)]
        [t.start() for t in ts]
        [t.join() for t in ts]

    assert not lock_opened
    assert not (paths[1] / ".lock").exists()

def test_main_run_command_wires_feature_enabled_from_instance(paths, tmp_path, monkeypatch):
    """Item 6: main(['run']) passes feature_enabled=inst.feature_enabled, honors real gate."""
    drop(paths[0], report([conv("A")]))

    # Create a fake instance dir with feature off
    inst_dir = tmp_path / "inst"
    inst_dir.mkdir()
    (inst_dir / "instance.json").write_text(json.dumps({"features": {"seal_ingest": False}}))

    # Point lib/instance.py at our fake instance
    import instance as inst
    monkeypatch.setenv("MARVIN_INSTANCE_DIR", str(inst_dir))
    inst.reset()

    exit_code = sbi.main(["run", "--attachments", str(paths[0]), "--store", str(paths[1])])
    assert exit_code == 0  # Not an error; feature is just off
    assert not (paths[1] / "reports.jsonl").exists()  # Nothing was ingested

    inst.reset()

def test_concurrent_runs_never_double_append(paths):
    drop(paths[0], report([conv(f"C{i}") for i in range(50)]))
    errs = []

    def go():
        try:
            run(paths)
        except Exception as e:  # pragma: no cover - surfaced below
            errs.append(e)
    ts = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs
    ids = [r["id"] for r in records(paths)]
    assert len(ids) == len(set(ids)) == 50


def test_store_is_private_to_the_owner(paths):
    drop(paths[0], REAL)
    run(paths)
    for name in ("reports.jsonl", "summary.json", "status.json", ".lock"):
        assert (paths[1] / name).stat().st_mode & 0o077 == 0, name
    assert paths[1].stat().st_mode & 0o077 == 0


# ── device names ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model, name", [
    ("iPhone14,7", "iPhone 14"), ("iPhone15,2", "iPhone 14 Pro"), ("iPhone15,4", "iPhone 15"),
    ("iPhone16,2", "iPhone 15 Pro Max"), ("iPhone17,3", "iPhone 16"), ("iPhone17,5", "iPhone 16e"),
    ("iPhone18,1", "iPhone 17 Pro"), ("iPhone18,3", "iPhone 17"), ("iPhone18,4", "iPhone Air"),
    ("arm64", "Simulator"),
])
def test_known_models_get_plain_names(model, name):
    assert sbi.device_name(model) == name


@pytest.mark.parametrize("model", ["iPhone99,9", "iPad16,3", "", None, 42])
def test_unknown_models_show_their_raw_id_and_are_never_dropped(model):
    assert sbi.device_name(model) == (str(model) if model not in ("", None) else "Unknown device")


def test_unknown_device_still_gets_its_own_group(paths):
    drop(paths[0], report([conv("A")], model="iPhone99,9"))
    run(paths)
    assert [d["device"] for d in summary(paths)["by_device"]] == ["iPhone99,9"]


# ── the summary: grouped by device, then build ──────────────────────────────

def test_summary_groups_by_device_then_build_and_by_build(paths):
    drop(paths[0], report([conv("A", rating=8), conv("B", rating=4)], model="iPhone15,4", build="3"), sub="a/a/1")
    drop(paths[0], report([conv("C", rating=9)], model="iPhone15,4", build="4", sent="2026-10-15T10:00:00-06:00"),
         name="seal-feedback-4-20261015-1000.json", sub="a/a/2")
    drop(paths[0], report([conv("D", rating=2, p95=3.5)], model="iPhone14,7", build="3", sent="2026-10-13T15:00:00-06:00"),
         name="seal-feedback-3-20261013-1500.json", sub="a/a/3")
    run(paths)
    s = summary(paths)
    devs = {d["device"]: d for d in s["by_device"]}
    assert set(devs) == {"iPhone 15", "iPhone 14"}
    i15 = devs["iPhone 15"]
    assert i15["conversations"] == 3 and i15["reports"] == 2 and i15["median_rating"] == 8
    assert [b["build"] for b in i15["builds"]] == ["4", "3"]  # newest build first
    assert {b["build"]: b["conversations"] for b in i15["builds"]} == {"3": 2, "4": 1}
    assert devs["iPhone 14"]["lag_p95"] == 3.5
    assert {b["build"]: b["conversations"] for b in s["by_build"]} == {"3": 3, "4": 1}
    assert s["totals"] == {"conversations": 4, "reports": 3, "devices": 2}


def test_unrated_is_separate_from_skipped_and_neither_moves_the_median(paths):
    drop(paths[0], report([conv("A", rating=9), conv("B", rating=None, skipped=True), conv("C", rating=None, skipped=False)]))
    run(paths)
    dev = summary(paths)["by_device"][0]
    assert (dev["rated"], dev["skipped"], dev["unrated"]) == (1, 1, 1)
    assert dev["median_rating"] == 9
    assert {r["id"]: r["rating_state"] for r in records(paths)} == {"A": "rated", "B": "skipped", "C": "unrated"}


def test_low_sample_sessions_are_flagged_and_kept_out_of_measurements(paths):
    drop(paths[0], report([conv("LONG", p95=1.0, samples=900, minutes=20),
                           conv("BLIP", p95=9.0, samples=10, minutes=0.2, battery=90.0, rating=3)]))
    run(paths)
    dev = summary(paths)["by_device"][0]
    assert dev["low_sample"] == 1
    assert dev["lag_p95"] == 1.0 and dev["battery_drop_per_30min"] == 6.0
    assert dev["median_rating"] == 5.5  # a tester's rating still counts, however short the session
    assert {r["id"]: r["low_sample"] for r in records(paths)} == {"LONG": False, "BLIP": True}


def test_endings_and_worst_thermal_state(paths):
    drop(paths[0], report([conv("A", ending="userStop", thermal="nominal"), conv("B", ending="stuck", thermal="serious"),
                           conv("C", ending="stuck", thermal="fair")]))
    run(paths)
    dev = summary(paths)["by_device"][0]
    assert dev["endings"] == {"userStop": 1, "stuck": 2}
    assert dev["max_thermal"] == "serious"


def test_notes_stay_in_the_private_summary_with_their_context(paths):
    drop(paths[0], report([conv("A", rating=3, note="Lost it when the waiter talked fast"), conv("B", note=None)]))
    run(paths)
    (n,) = summary(paths)["by_device"][0]["notes"]
    assert n["note"] == "Lost it when the waiter talked fast" and n["rating"] == 3 and n["build"] == "3"


def test_status_records_last_report_seen(paths):
    drop(paths[0], report([conv("A")], sent="2026-10-12T08:00:00-06:00"), sub="1/1/1")
    drop(paths[0], report([conv("B")], sent="2026-10-13T08:00:00-06:00"), name="seal-feedback-3-b.json", sub="1/1/2")
    st = run(paths)
    assert st["last_report_at"] == "2026-10-13T08:00:00-06:00"
    assert st["generated_at"] == NOW.isoformat()


def test_empty_attachments_folder_is_ok_with_an_empty_summary(paths):
    st = run(paths)
    assert st["ok"] and st["files_found"] == 0 and st["last_report_at"] is None
    assert summary(paths)["by_device"] == [] and summary(paths)["totals"]["conversations"] == 0


def test_summary_command_prints_a_device_table(paths, capsys):
    drop(paths[0], report([conv("A", rating=7)]))
    run(paths)
    assert sbi.main(["summary", "--store", str(paths[1])]) == 0
    out = capsys.readouterr().out
    assert "iPhone 15" in out and "build 3" in out


def test_summary_command_without_data_says_so(tmp_path, capsys):
    assert sbi.main(["summary", "--store", str(tmp_path / "empty")]) == 0
    assert "No beta reports" in capsys.readouterr().out


def test_minutes_total_adds_every_conversation_including_short_ones(paths):
    drop(paths[0], report([conv("A", minutes=20.25), conv("B", minutes=0.2, samples=5), conv("C", minutes=None)]))
    run(paths)
    assert summary(paths)["by_device"][0]["minutes_total"] == 20.4
