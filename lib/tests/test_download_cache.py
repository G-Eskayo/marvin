"""Tests for download_cache.py (marvin#765 item 4: helpers' downloads go in one capped cache). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_download_cache.py -v
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import download_cache as dc  # noqa: E402

MiB = 2**20
OLD = time.time() - 3 * 86400   # well past the in-progress grace window


def _put(name, size, used_at, is_dir=False):
    root = dc.cache_dir()
    p = root / name
    if is_dir:
        p.mkdir()
        (p / "part1.bin").write_bytes(b"x" * (size // 2))
        (p / "part2.bin").write_bytes(b"x" * (size - size // 2))
        for f in p.iterdir():
            os.utime(f, (used_at, used_at))
    else:
        p.write_bytes(b"x" * size)
    os.utime(p, (used_at, used_at))
    return p


def test_the_cache_lives_outside_downloads_and_icloud():
    # The tidy agent files ~/Downloads, and ~/Documents is iCloud (and TCC-blocked under launchd).
    d = dc.cache_dir()
    assert d.is_dir()
    assert "Downloads" not in d.parts and "Documents" not in d.parts


def test_under_the_cap_nothing_is_removed():
    a = _put("a.bin", 2 * MiB, OLD)
    r = dc.enforce_cap(cap_bytes=10 * MiB)
    assert a.exists() and r["removed"] == [] and r["freed_bytes"] == 0


def test_over_the_cap_the_oldest_unused_go_first_until_it_fits():
    old = _put("old.bin", 4 * MiB, OLD - 300)
    mid = _put("mid", 4 * MiB, OLD - 200, is_dir=True)
    new = _put("new.bin", 4 * MiB, OLD - 100)
    r = dc.enforce_cap(cap_bytes=5 * MiB)
    assert not old.exists() and not mid.exists() and new.exists()
    assert [x["name"] for x in r["removed"]] == ["old.bin", "mid"]
    assert r["freed_bytes"] == 8 * MiB and r["total_after"] == 4 * MiB


def test_using_a_file_moves_it_to_the_back_of_the_queue():
    a = _put("a.bin", 4 * MiB, OLD - 300)
    b = _put("b.bin", 4 * MiB, OLD - 100)
    dc.touch("a.bin")
    dc.enforce_cap(cap_bytes=5 * MiB)
    assert a.exists() and not b.exists()


def test_a_pinned_file_is_never_deleted_even_when_oldest():
    a = _put("model.bin", 8 * MiB, OLD - 300)
    b = _put("b.bin", 4 * MiB, OLD - 100)
    dc.pin("model.bin", os.getpid())
    r = dc.enforce_cap(cap_bytes=1 * MiB)
    assert a.exists() and not b.exists()
    assert "model.bin" in r["kept_pinned"]


def test_a_pin_held_by_a_finished_job_no_longer_protects():
    a = _put("model.bin", 8 * MiB, OLD)
    p = subprocess.Popen(["true"])
    p.wait()
    dc.pin("model.bin", p.pid)   # that process is gone
    dc.enforce_cap(cap_bytes=1 * MiB)
    assert not a.exists()


def test_unpin_releases():
    a = _put("model.bin", 8 * MiB, OLD)
    dc.pin("model.bin", os.getpid())
    dc.unpin("model.bin", os.getpid())
    dc.enforce_cap(cap_bytes=1 * MiB)
    assert not a.exists()


def test_a_file_still_being_written_is_left_alone():
    # curl writing right now: its mtime is fresh even if nothing pinned it.
    a = _put("partial.bin", 8 * MiB, time.time())
    r = dc.enforce_cap(cap_bytes=1 * MiB)
    assert a.exists() and "partial.bin" in r["kept_recent"]


def test_names_that_escape_the_cache_are_refused():
    for bad in ("../x", "a/b", ".pins", "", ".hidden"):
        with pytest.raises(ValueError):
            dc.pin(bad, os.getpid())


def test_a_link_inside_the_cache_is_unlinked_never_followed(tmp_path):
    precious = tmp_path / "precious"
    precious.mkdir()
    (precious / "keep.txt").write_text("keep me")
    link = dc.cache_dir() / "link"
    link.symlink_to(precious)
    os.utime(link, (OLD, OLD), follow_symlinks=False)
    _put("big.bin", 4 * MiB, OLD + 10)
    dc.enforce_cap(cap_bytes=1)
    assert (precious / "keep.txt").read_text() == "keep me"
    assert not link.is_symlink()


def test_enforcing_the_cap_records_what_it_freed():
    import disk_triggers
    _put("a.bin", 4 * MiB, OLD)
    dc.enforce_cap(cap_bytes=1 * MiB)
    last = json.loads(disk_triggers.LOG_PATH.read_text().splitlines()[-1])
    assert last["trigger"] == "download-cache" and last["freed_bytes"] == 4 * MiB


def test_cap_comes_from_the_config(tmp_path, monkeypatch):
    import disk_triggers
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"download_cache_cap_gb": 2}))
    monkeypatch.setattr(disk_triggers, "CONFIG_PATH", cfg)
    assert dc.cap_bytes() == 2 * 2**30
    cfg.write_text("nonsense")
    assert dc.cap_bytes() == dc.DEFAULT_CAP_BYTES


def test_fetch_downloads_into_the_cache_pinned_while_it_runs(monkeypatch):
    seen = {}

    def fake_curl(argv, **kw):
        out = Path(argv[argv.index("-o") + 1])
        seen["pinned_during"] = dc.is_pinned("data.zip")
        seen["argv"] = argv
        out.write_bytes(b"z" * 100)
        return subprocess.CompletedProcess(argv, 0)
    path = dc.fetch("https://example.com/data.zip", run=fake_curl)
    assert path == dc.cache_dir() / "data.zip" and path.read_bytes() == b"z" * 100
    assert seen["pinned_during"] is True and not dc.is_pinned("data.zip")
    assert "-f" in seen["argv"] and "-L" in seen["argv"]


def test_a_failed_fetch_leaves_no_partial_file(monkeypatch):
    def failing(argv, **kw):
        Path(argv[argv.index("-o") + 1]).write_bytes(b"half")
        return subprocess.CompletedProcess(argv, 22)
    with pytest.raises(RuntimeError):
        dc.fetch("https://example.com/data.zip", run=failing)
    assert [p.name for p in dc.cache_dir().iterdir() if "data.zip" in p.name] == []
    assert not dc.is_pinned("data.zip")


def test_cli_prints_the_cache_path(capsys):
    assert dc.main(["path"]) == 0
    assert capsys.readouterr().out.strip() == str(dc.cache_dir())
