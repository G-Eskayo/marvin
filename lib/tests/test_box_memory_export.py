"""box_memory_export.py (ADR 0082): what a Claude session on the Linux box changed in memory and handoffs, as box items.

Runs against a real git repo laid out like the box's ~/.claude mirror, and the real mirror (code_sync.mirror) where it
matters: an edit must survive the mirror's reset by being captured first. Tries to break it with symlinks out of the
folder, oversized and non-UTF-8 files, odd names, a corrupt outbox file, and items that already landed.

    ~/.agents/venv/bin/python -m pytest lib/tests/test_box_memory_export.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))
for _name in ("box_memory_items", "box_memory_export"):
    _mod = sys.modules.get(_name)
    if _mod is not None and Path(getattr(_mod, "__file__", "") or "").resolve().parent != LIB:
        del sys.modules[_name]

import box_memory_export as bx  # noqa: E402
import box_memory_items as bi  # noqa: E402

MEM = "projects/-Users-gileskayo/memory"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "claude"
    (r / MEM).mkdir(parents=True)
    (r / "handoffs").mkdir()
    (r / MEM / "MEMORY.md").write_text("# Memory Index\n- [A](project-a.md) — a\n")
    (r / MEM / "project-a.md").write_text("fact a\n")
    (r / MEM / "feedback-b.md").write_text("rule b\n")
    (r / "handoffs" / "handoff-1.md").write_text("old handoff\n")
    git(r, "init", "-q", "-b", "main")
    git(r, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    return r


def kinds(items):
    return sorted((i["kind"], i["name"], i.get("op") or "") for i in items)


def test_a_clean_mirror_has_nothing_to_send(repo):
    assert bx.changes(repo) == ([], [])


def test_every_kind_of_change_becomes_a_valid_item(repo):
    (repo / MEM / "project-new.md").write_text("new fact\n")
    (repo / MEM / "project-a.md").write_text("fact a, revised\n")
    (repo / MEM / "feedback-b.md").unlink()
    (repo / MEM / "MEMORY.md").write_text("# Memory Index\n- [New](project-new.md) — new\n")
    (repo / "handoffs" / "handoff-2.md").write_text("new handoff\n")
    (repo / "handoffs" / "handoff-1.md").unlink()
    items, skipped = bx.changes(repo)
    assert skipped == []
    assert kinds(items) == [
        ("handoff", "handoff-2.md", ""), ("handoff-delete", "handoff-1.md", ""),
        ("index-line", "MEMORY.md", "add"), ("index-line", "MEMORY.md", "remove"),
        ("memory-delete", "feedback-b.md", ""), ("memory-edit", "project-a.md", ""),
        ("memory-new", "project-new.md", "")]
    assert all(bi.check(i) is None for i in items)
    edit = next(i for i in items if i["kind"] == "memory-edit")
    assert edit["base"] == bi.sha("fact a\n") and edit["content"] == "fact a, revised\n"


def test_symlinks_odd_names_huge_and_binary_files_are_skipped_not_sent(repo, tmp_path):
    secret = tmp_path / "id_ed25519"
    secret.write_text("PRIVATE\n")
    os.symlink(secret, repo / MEM / "project-link.md")
    (repo / MEM / "-rf.md").write_text("x\n")
    (repo / MEM / "project-huge.md").write_text("x" * (bi.MEMORY_CAP + 1))
    (repo / "handoffs" / "handoff-huge.md").write_text("x" * (bi.HANDOFF_CAP + 1))
    (repo / MEM / "project-bin.md").write_bytes(b"\xff\xfe\x00")
    (repo / MEM / "project-bidi.md").write_text("fine‮text\n")
    items, skipped = bx.changes(repo)
    assert items == []
    reasons = {s["name"]: s["reason"] for s in skipped}
    assert reasons["project-link.md"] == "not a plain file" and reasons["-rf.md"] == "bad name"
    assert reasons["project-huge.md"] == "too big" and reasons["handoff-huge.md"] == "too big"
    assert reasons["project-bin.md"] == "unreadable" and reasons["project-bidi.md"].startswith("hidden character")
    assert "PRIVATE" not in json.dumps(bx.export(repo, tmp_path / "outbox"))


def test_a_symlinked_index_is_not_read(repo, tmp_path):
    other = tmp_path / "other.md"
    other.write_text("- [Planted](x.md)\n")
    (repo / MEM / "MEMORY.md").unlink()
    os.symlink(other, repo / MEM / "MEMORY.md")
    assert [i for i in bx.changes(repo)[0] if i["kind"] == "index-line"] == []


def test_an_edit_survives_the_mirrors_reset_by_being_captured_first(repo, tmp_path, monkeypatch):
    """The real mirror: code_sync.mirror resets the box's ~/.claude to origin/main, and captures box items first."""
    import code_sync
    origin = tmp_path / "origin.git"
    git(tmp_path, "clone", "-q", "--bare", str(repo), str(origin))
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "fetch", "-q", "origin")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    home_claude = tmp_path / "home" / ".claude"
    home_claude.parent.mkdir()
    os.symlink(repo, home_claude)   # ~/.claude is this repo
    monkeypatch.setattr(code_sync, "MIRROR_LOG_PATH", tmp_path / "mirror.log")
    monkeypatch.setattr(code_sync, "MIRROR_BACKUP_DIR", tmp_path / "backups")
    outbox = tmp_path / "outbox"
    monkeypatch.setattr(bx, "OUTBOX", outbox)
    monkeypatch.setattr(bx.capture, "__defaults__", (bx.CLAUDE, outbox, None))
    (repo / MEM / "project-a.md").write_text("fact a, learned on the box\n")
    code_sync.mirror(home_claude)
    assert (repo / MEM / "project-a.md").read_text() == "fact a\n"       # the mirror reset it...
    [item] = bx.outbox_items(repo, outbox)                                # ...but it was captured
    assert item["kind"] == "memory-edit" and item["content"] == "fact a, learned on the box\n"
    assert "box outbox" in (tmp_path / "mirror.log").read_text()


def test_outbox_items_are_pruned_once_they_land_or_expire_and_a_corrupt_one_is_dropped(repo, tmp_path):
    outbox = tmp_path / "outbox"
    (repo / MEM / "project-a.md").write_text("fact a v2\n")
    (repo / MEM / "project-c.md").write_text("fact c\n")
    bx.capture(repo, outbox)
    (outbox / "junk.json").write_text("{torn")
    forged = bi.make("memory-new", "project-z.md", content="z\n")
    forged["content"] = "changed\n"
    (outbox / "forged.json").write_text(json.dumps(forged))
    assert len(bx.outbox_items(repo, outbox)) == 2
    assert not (outbox / "junk.json").exists() and not (outbox / "forged.json").exists()
    # a Mac approved the edit: the mirror's HEAD now carries it
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", f"{MEM}/project-a.md")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "approved")
    [left] = bx.outbox_items(repo, outbox)
    assert left["name"] == "project-c.md"
    assert bx.outbox_items(repo, outbox, now=10**12) == []


def test_export_is_one_json_object_a_mac_can_check(repo, tmp_path, capsys, monkeypatch):
    (repo / MEM / "project-new.md").write_text("new fact\n")
    out = bx.export(repo, tmp_path / "outbox")
    assert out["version"] == 1 and [i["name"] for i in out["items"]] == ["project-new.md"]
    monkeypatch.setattr(bx, "export", lambda: out)
    assert bx.main(["export"]) == 0
    assert json.loads(capsys.readouterr().out) == out
    assert bx.main(["push"]) == 2


def test_capture_twice_writes_each_item_once(repo, tmp_path):
    (repo / MEM / "project-new.md").write_text("new fact\n")
    outbox = tmp_path / "outbox"
    assert bx.capture(repo, outbox) == 1
    assert bx.capture(repo, outbox) == 0
