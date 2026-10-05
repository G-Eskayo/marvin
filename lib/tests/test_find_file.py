"""Tests for ~/.claude/organize/find_file.py (the `findit` command), now also a library.
Run via: ~/.agents/venv/bin/python -m pytest lib/tests/test_find_file.py -v
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ORGANIZE = Path.home() / ".claude" / "organize"
sys.path.insert(0, str(ORGANIZE))

import find_file as ff  # noqa: E402

HOME = Path.home()


def fake_mdfind(by_name, by_text):
    def run(args):
        return list(by_name if args and args[0] == "-name" else by_text)
    return run


def test_search_separates_name_matches_from_content_only_matches():
    a, b, c = HOME / "Documents/Money-and-Admin/lease.pdf", HOME / "Documents/Career/cv.pdf", HOME / "Documents/School/notes.pdf"
    out = ff.search("lease", mdfind=fake_mdfind([a], [a, b, c]))
    assert [r["path"] for r in out["name"]] == [str(a)]
    assert [r["path"] for r in out["content"]] == [str(b), str(c)]


def test_search_describes_each_hit_with_bucket_name_and_kind(tmp_path, monkeypatch):
    f = HOME / "Documents" / "Career" / "x.pdf"
    out = ff.search("x", mdfind=fake_mdfind([f], [f]))
    r = out["name"][0]
    assert r["bucket"] == "Career" and r["name"] == "x.pdf" and r["match"] == "name"
    assert {"path", "name", "bucket", "mtime", "size", "isDir", "match"} <= set(r)


def test_search_drops_noise_and_caps_each_group():
    noisy = HOME / "Documents/Projects/app/node_modules/pkg/readme.md"
    many = [HOME / f"Documents/School/f{i}.pdf" for i in range(80)]
    out = ff.search("f", mdfind=fake_mdfind(many[:40], [noisy, *many]), limit=30)
    assert len(out["name"]) == 30
    assert all("node_modules" not in r["path"] for r in out["content"])
    assert len(out["content"]) <= 30


def test_blank_query_returns_nothing():
    assert ff.search("   ", mdfind=fake_mdfind([HOME / "Documents/a"], [])) == {"name": [], "content": []}


def test_json_flag_prints_machine_readable_results():
    # Runs the real script with a query that should match nothing; proves the CLI contract.
    r = subprocess.run([sys.executable, str(ORGANIZE / "find_file.py"), "--json", "zzqxnonexistentphrase9931"],
                       capture_output=True, text=True, timeout=60)
    data = json.loads(r.stdout)
    assert set(data) == {"name", "content"}
