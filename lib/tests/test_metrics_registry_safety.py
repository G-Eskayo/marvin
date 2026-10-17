"""A half-written metrics file blinded Health for a week (2026-10-09..16): health_checks crashed on
bench/metrics/health-monitor.mac-mini.json ("Extra data") and never wrote health-status.json. These try to break the
write path and the reader."""
import json

import pytest

import metrics_registry as mr


@pytest.fixture
def mdir(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "METRICS_DIR", tmp_path)
    return tmp_path


M = {"x": {"value": 1, "higher_is_better": False}}


def test_a_crash_mid_write_leaves_the_old_file_intact(mdir, monkeypatch):
    mr.record("s", M, machine="m")
    before = (mdir / "s.m.json").read_bytes()

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(mr.os, "replace", boom)
    with pytest.raises(OSError):
        mr.record("s", M, machine="m")
    assert (mdir / "s.m.json").read_bytes() == before
    assert not list(mdir.glob("*.tmp*")), "a failed write must not leave temp files behind"


def test_a_corrupt_history_is_never_overwritten(mdir):
    bad = b'[{"timestamp": "t", "metrics": {}}]\n}\n]'
    (mdir / "s.m.json").write_bytes(bad)
    with pytest.raises(ValueError):
        mr.record("s", M, machine="m")
    assert (mdir / "s.m.json").read_bytes() == bad


def test_records_still_accumulate(mdir):
    for _ in range(3):
        mr.record("s", M, machine="m")
    assert len(json.loads((mdir / "s.m.json").read_text())) == 3


def test_health_reports_a_broken_metrics_file_as_one_red_check_instead_of_dying(monkeypatch):
    import health_checks as hc

    def broken(results):
        raise json.JSONDecodeError("Extra data", "x", 0)
    monkeypatch.setattr(hc, "record_anomaly_metrics", broken)
    anomaly, extra = hc.anomaly_or_red([{"id": "a", "value": 1, "severity": "green"}])
    assert anomaly is None
    assert len(extra) == 1 and extra[0]["severity"] == "red" and "Extra data" in extra[0]["detail"]
