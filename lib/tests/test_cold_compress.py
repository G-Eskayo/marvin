"""Tests for cold_compress.py. Real afsctool on real files: the point is that nothing a reader sees changes.
    ~/.agents/venv/bin/python -m pytest lib/tests/test_cold_compress.py -v
"""
from __future__ import annotations
import os
import shutil
import stat
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cold_compress as cc  # noqa: E402

needs_afsctool = pytest.mark.skipif(shutil.which("afsctool") is None and not Path(cc.AFSCTOOL).exists(),
                                    reason="afsctool not installed")
DAY = 86400


def _transcript(path: Path, age_days: float, kb: int = 256) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = '{"type":"assistant","message":{"content":"the same words again and again"}}\n'
    path.write_text(line * (kb * 1024 // len(line)))
    old = time.time() - age_days * DAY
    os.utime(path, (old, old))
    return path


def _compressed(path: Path) -> bool:
    return bool(os.stat(path).st_flags & stat.UF_COMPRESSED)


@needs_afsctool
def test_a_cold_file_is_compressed_and_reads_back_byte_for_byte(tmp_path):
    f = _transcript(tmp_path / "p" / "s.jsonl", age_days=10)
    before, mtime = f.read_bytes(), f.stat().st_mtime
    out = cc.compress_cold(tmp_path, "*.jsonl", min_age_days=7)
    assert [r["path"] for r in out["compressed"]] == [f]
    assert _compressed(f)
    assert f.read_bytes() == before
    assert f.stat().st_mtime == mtime  # usage accounting picks transcripts by mtime


@needs_afsctool
def test_a_recent_file_is_left_alone(tmp_path):
    f = _transcript(tmp_path / "s.jsonl", age_days=2)
    assert cc.compress_cold(tmp_path, "*.jsonl", min_age_days=7)["compressed"] == []
    assert not _compressed(f)


@needs_afsctool
def test_running_twice_does_no_work_the_second_time(tmp_path):
    _transcript(tmp_path / "s.jsonl", age_days=10)
    cc.compress_cold(tmp_path, "*.jsonl", min_age_days=7)
    again = cc.compress_cold(tmp_path, "*.jsonl", min_age_days=7)
    assert again["compressed"] == [] and again["already"] == 1


@needs_afsctool
def test_it_saves_space_and_reports_how_much(tmp_path):
    _transcript(tmp_path / "s.jsonl", age_days=10, kb=1024)
    out = cc.compress_cold(tmp_path, "*.jsonl", min_age_days=7)
    assert out["saved_kb"] > 500


def test_only_matching_files_are_touched(tmp_path):
    seen = []
    _transcript(tmp_path / "s.jsonl", age_days=10)
    _transcript(tmp_path / "notes.md", age_days=10)
    cc.compress_cold(tmp_path, "*.jsonl", min_age_days=7, compress=lambda p: seen.append(p.name) or True)
    assert seen == ["s.jsonl"]


def test_a_symlink_is_never_followed(tmp_path):
    """A link could point anywhere on the disk; compressing its target is not this job's business."""
    target = _transcript(tmp_path / "elsewhere" / "real.txt", age_days=10)
    (tmp_path / "root").mkdir()
    (tmp_path / "root" / "link.jsonl").symlink_to(target)
    seen = []
    cc.compress_cold(tmp_path / "root", "*.jsonl", min_age_days=7, compress=lambda p: seen.append(p) or True)
    assert seen == []


def test_a_file_that_disappears_mid_run_does_not_stop_the_rest(tmp_path):
    a = _transcript(tmp_path / "a.jsonl", age_days=10)
    _transcript(tmp_path / "b.jsonl", age_days=10)
    def compress(p):
        if p.name == "a.jsonl":
            a.unlink()
            raise FileNotFoundError(p)
        return True
    out = cc.compress_cold(tmp_path, "*.jsonl", min_age_days=7, compress=compress)
    assert [r["path"].name for r in out["compressed"]] == ["b.jsonl"]
    assert out["failed"][0]["path"].name == "a.jsonl"


def test_a_missing_tool_is_reported_once_and_nothing_is_touched(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "AFSCTOOL", str(tmp_path / "no-such-afsctool"))
    monkeypatch.setattr(cc.shutil, "which", lambda name: None)
    f = _transcript(tmp_path / "s.jsonl", age_days=10)
    before = f.read_bytes()
    out = cc.compress_cold(tmp_path, "*.jsonl", min_age_days=7)
    assert out["skipped"] == "afsctool not installed" and out["compressed"] == []
    assert f.read_bytes() == before


def test_a_missing_root_is_not_an_error(tmp_path):
    assert cc.compress_cold(tmp_path / "nope", "*.jsonl", min_age_days=7)["compressed"] == []


@needs_afsctool
def test_a_file_whose_content_changes_after_compression_is_reported_not_trusted(tmp_path):
    """Lossless is the whole promise: if the bytes read back differ, say so loudly."""
    f = _transcript(tmp_path / "s.jsonl", age_days=10)
    def corrupting(p):
        ok = cc._afsctool_compress(p)
        mtime = p.stat().st_mtime
        p.write_text("changed")
        os.utime(p, (mtime, mtime))
        return ok
    out = cc.compress_cold(tmp_path, "*.jsonl", min_age_days=7, compress=corrupting)
    assert out["compressed"] == [] and "content changed" in out["failed"][0]["reason"]
