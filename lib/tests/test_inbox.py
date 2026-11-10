"""Tests for inbox.py (marvin#1123 section 3, ADR 0083): one JSON file per item, one reader and writer. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_inbox.py -v

Real files in tmp_path, real processes for the concurrency tests. Never the real ~/.claude: every test passes its own
root (tmp/.claude/inbox), and the legacy markdown files sit beside it as they do in ~/.claude.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import inbox  # noqa: E402

TODAY = date(2026, 11, 4)

SUGGESTIONS_MD = """# Suggestions

Priority-ordered backlog.

## Low one
**Priority**: 3
**Status**: pending
**Impact**: robustness
**Effort**: high
**Why**: small thing
**What**: change it
**How**:
- step
**Added**: 2026-10-01

## High one
**Priority**: 9
**Status**: pending
**Impact**: speed
**Effort**: low
**Why**: big thing
**What**: change it more
**How**:
- step 1
- step 2
**Added**: 2026-10-02

## Done one
**Priority**: 10
**Status**: promoted 2026-10-15 https://github.com/G-Eskayo/marvin/issues/470
**Impact**: token-reduction
**Effort**: low
**Why**: was big
**Added**: 2026-09-01

## Tie on priority, better impact
**Priority**: 3
**Status**: open
**Impact**: token-reduction
**Effort**: high
**Why**: x
**Added**: 2026-10-03
"""

QUEUE_MD = """# Improvement Queue

---
## 2026-07-01 — marvin

- **[NAMING]** Generic parameter name `data` in `total()` at line 1. (`lib/widget.py`)
- **[KISS]** Function 'total' at line 1 is 6 lines long. (`lib/widget.py`) — auto-fix: done, PR #944 merged

*2 item(s). Run `qa_scan.py <project> --dry-run` for the full list.*
---
## 2026-07-02 — marvin

- **[NAMING]** Generic parameter name `data` in `total()` at line 1. (`lib/widget.py`)
- **[VERBOSITY]** Filler word `just` (`lib/widget.py`) — auto-fix: skipped 2026-10-27, no tests cover lib
- free text bullet with no kind
"""


@pytest.fixture
def root(tmp_path):
    return tmp_path / ".claude" / "inbox"


def item(**over):
    base = {"title": "Something to look at", "body": "Details.", "source": "test"}
    base.update(over)
    return base


# --- add / list / act -----------------------------------------------------------------------------------------------

def test_add_list_round_trip(root):
    rec, created = inbox.add("notes", item(fields={"n": 1}), root, TODAY)
    assert created and inbox.ID_RE.fullmatch(rec["id"]) and rec["pile"] == "notes"
    listed = inbox.list_items("notes", root)
    assert listed["problems"] == []
    [got] = listed["items"]
    assert got["id"] == rec["id"] and got["status"] == {"state": "open"} and got["added"] == "2026-11-04"
    assert got["fields"] == {"n": 1} and got["history"] == []
    assert json.loads((root / "notes" / f"{rec['id']}.json").read_text())["title"] == "Something to look at"


def test_act_sets_status_and_records_history(root):
    rec, _ = inbox.add("notes", item(), root, TODAY)
    out = inbox.act("notes", rec["id"], "done", {"note": "fixed in #12"}, root, TODAY)
    assert out["status"] == {"state": "done", "on": "2026-11-04", "note": "fixed in #12"}
    out = inbox.act("notes", rec["id"], "open", None, root, TODAY)
    again = inbox.get("notes", rec["id"], root)
    assert [h["state"] for h in again["history"]] == ["done", "open"] and again["status"]["state"] == "open"


def test_act_cannot_forge_a_bad_state_or_date(root):
    rec, _ = inbox.add("notes", item(), root, TODAY)
    for bad in ("", "Done", "../x", "a" * 41, "done now"):
        with pytest.raises(inbox.InboxError):
            inbox.act("notes", rec["id"], bad, None, root, TODAY)
    out = inbox.act("notes", rec["id"], "done", {"state": "hacked", "on": "never"}, root, TODAY)
    assert out["status"]["state"] == "done" and out["status"]["on"] == "2026-11-04"  # extra can't override them
    with pytest.raises(inbox.InboxError, match="too big"):
        inbox.act("notes", rec["id"], "done", {"note": "x" * 5000}, root, TODAY)


def test_update_fields_merges_and_is_recorded(root):
    rec, _ = inbox.add("suggestions", item(fields={"priority": 3, "impact": "speed"}), root, TODAY)
    out = inbox.update_fields("suggestions", rec["id"], {"priority": 8}, root, TODAY)
    assert out["fields"] == {"priority": 8, "impact": "speed"}
    assert out["history"][-1] == {"fields": {"priority": 8}, "on": "2026-11-04"}
    with pytest.raises(inbox.InboxError):
        inbox.update_fields("suggestions", rec["id"], {}, root, TODAY)


def test_act_on_a_missing_item_is_an_error_not_a_new_file(root):
    inbox.add("notes", item(), root, TODAY)
    with pytest.raises(inbox.InboxError, match="no item"):
        inbox.act("notes", "nope-123", "done", None, root, TODAY)
    assert not (root / "notes" / "nope-123.json").exists()


# --- bad input ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [None, [], "text", {"title": ""}, {"title": "   "}, {"title": 5},
                                 {"title": "x" * 501}, {"title": "ok", "body": "x" * (64 * 1024 + 1)},
                                 {"title": "ok", "fields": []}, {"title": "ok", "added": "yesterday"},
                                 {"title": "ok", "status": {"state": "Open!"}}, {"title": "ok", "status": "open"}])
def test_bad_items_are_refused_and_nothing_is_written(root, bad):
    with pytest.raises(inbox.InboxError):
        inbox.add("notes", bad, root, TODAY)
    assert not list((root / "notes").glob("*.json")) if (root / "notes").exists() else True


@pytest.mark.parametrize("pile", ["", "..", "../etc", "a/b", "Notes", "-x", "x" * 41, ".locks", "no tes", None, 3])
def test_path_traversal_and_bad_pile_names_are_refused(root, tmp_path, pile):
    with pytest.raises(inbox.InboxError, match="pile"):
        inbox.add(pile, item(), root, TODAY)
    with pytest.raises(inbox.InboxError):
        inbox.list_items(pile, root)
    assert not any(p.is_file() for p in tmp_path.rglob("*"))  # nothing written anywhere


@pytest.mark.parametrize("iid", ["../../etc/passwd", "../notes/x", "A", "", ".hidden", "x/y", "_pile", None, 7])
def test_path_traversal_in_ids_is_refused(root, iid):
    inbox.add("notes", item(), root, TODAY)
    with pytest.raises(inbox.InboxError):
        inbox.act("notes", iid, "done", None, root, TODAY)
    with pytest.raises(inbox.InboxError):
        inbox.get("notes", iid, root)


def test_unicode_titles_and_bodies_survive_and_get_a_safe_id(root):
    rec, _ = inbox.add("notes", item(title="שלום — 日本語 🚀", body="naïve café ✓"), root, TODAY)
    assert inbox.ID_RE.fullmatch(rec["id"]) and rec["id"].startswith("item-")
    got = inbox.get("notes", rec["id"], root)
    assert got["title"] == "שלום — 日本語 🚀" and got["body"] == "naïve café ✓"


def test_duplicate_titles_get_distinct_ids(root):
    a, _ = inbox.add("notes", item(), root, TODAY)
    b, _ = inbox.add("notes", item(), root, TODAY)
    assert a["id"] != b["id"] and len(inbox.list_items("notes", root)["items"]) == 2


# --- keys: dedupe ---------------------------------------------------------------------------------------------------

def test_a_keyed_item_is_added_once_and_its_id_is_the_same_everywhere(root, tmp_path):
    a, c1 = inbox.add("notes", item(key="k1"), root, TODAY)
    b, c2 = inbox.add("notes", item(key="k1", title="different words"), root, date(2026, 12, 1))
    assert c1 and not c2 and b["id"] == a["id"] and b["added"] == "2026-11-04"  # the first date is kept
    other, _ = inbox.add("notes", item(key="k1"), tmp_path / "other-mac" / "inbox", TODAY)
    assert other["id"] == a["id"]  # the same item on the other Mac: one file name, so git sync merges it


# --- a bad file is a problem, never fatal ---------------------------------------------------------------------------

def test_malformed_huge_empty_half_written_and_mismatched_files_are_problems(root):
    good, _ = inbox.add("notes", item(), root, TODAY)
    d = root / "notes"
    (d / "garbage.json").write_text("{not json")
    (d / "empty.json").write_text("")
    (d / "half.json").write_text(json.dumps({**good, "id": "half"})[:40])
    (d / "huge.json").write_text("x" * (inbox.MAX_FILE_BYTES + 1))
    (d / "array.json").write_text("[1, 2]")
    (d / "wrong-id.json").write_text(json.dumps({**good}))
    (d / "wrong-pile.json").write_text(json.dumps({**good, "id": "wrong-pile", "pile": "other"}))
    (d / "no-status.json").write_text(json.dumps({**{k: v for k, v in good.items() if k != "status"}, "id": "no-status",
                                                  "status": None}))
    (d / "bad-bytes.json").write_bytes(b"\xff\xfe\x00garbage")
    out = inbox.list_items("notes", root)
    assert [i["id"] for i in out["items"]] == [good["id"]]
    assert sorted(p["file"] for p in out["problems"]) == sorted(
        ["array.json", "bad-bytes.json", "empty.json", "garbage.json", "half.json", "huge.json", "no-status.json",
         "wrong-id.json", "wrong-pile.json"])
    with pytest.raises(inbox.InboxError):
        inbox.act("notes", "garbage", "done", None, root, TODAY)
    assert (d / "garbage.json").read_text() == "{not json"  # a bad file is reported, never rewritten


def test_symlinks_are_never_read_or_written_through(root, tmp_path):
    good, _ = inbox.add("notes", item(), root, TODAY)
    secret = tmp_path / "secret.json"
    secret.write_text(json.dumps({**good, "id": "leak", "title": "SECRET"}))
    (root / "notes" / "leak.json").symlink_to(secret)
    out = inbox.list_items("notes", root)
    assert "SECRET" not in json.dumps(out["items"]) and any(p["file"] == "leak.json" for p in out["problems"])
    with pytest.raises(inbox.InboxError):
        inbox.act("notes", "leak", "done", None, root, TODAY)
    assert json.loads(secret.read_text())["title"] == "SECRET"


def test_a_symlinked_pile_folder_is_refused(root, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    root.mkdir(parents=True)
    (root / "notes").symlink_to(elsewhere)
    with pytest.raises(inbox.InboxError, match="symlink"):
        inbox.add("notes", item(), root, TODAY)
    assert not inbox.pile_exists("notes", root) and not list(elsewhere.iterdir())


def test_a_crash_mid_write_leaves_the_old_file_whole(root, monkeypatch):
    rec, _ = inbox.add("notes", item(), root, TODAY)
    before = (root / "notes" / f"{rec['id']}.json").read_text()

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(inbox.os, "replace", boom)
    with pytest.raises(OSError):
        inbox.act("notes", rec["id"], "done", None, root, TODAY)
    assert (root / "notes" / f"{rec['id']}.json").read_text() == before
    assert not list((root / "notes").glob(".*.tmp"))


def test_no_reader_sees_an_empty_claimed_file(root, monkeypatch):
    """The claim and the content land together (a hard link of a finished temp file)."""
    seen = []
    real_link = os.link

    def watching_link(src, dst):
        seen.append(Path(src).read_text())
        return real_link(src, dst)
    monkeypatch.setattr(inbox.os, "link", watching_link)
    rec, _ = inbox.add("notes", item(), root, TODAY)
    assert json.loads(seen[0])["id"] == rec["id"]


# --- concurrency (two real processes) -------------------------------------------------------------------------------

_ADDER = """
import sys
sys.path.insert(0, {lib!r})
import inbox
from pathlib import Path
root = Path({root!r})
for n in range(40):
    inbox.add("notes", {{"title": "same title", "key": f"k{{n}}"}}, root)
    inbox.add("notes", {{"title": "same title"}}, root)
"""


def test_two_processes_adding_at_once_lose_nothing_and_never_duplicate_a_key(root):
    script = _ADDER.format(lib=str(LIB), root=str(root))
    procs = [subprocess.Popen([sys.executable, "-c", script]) for _ in range(2)]
    assert all(p.wait(timeout=120) == 0 for p in procs)
    out = inbox.list_items("notes", root)
    assert out["problems"] == []
    keys = [i.get("key") for i in out["items"] if i.get("key")]
    assert sorted(keys) == sorted(f"k{n}" for n in range(40))  # each key once, though both processes added it
    assert len([i for i in out["items"] if not i.get("key")]) == 80  # every unkeyed add kept


_ACTOR = """
import sys
sys.path.insert(0, {lib!r})
import inbox
from pathlib import Path
for n in range(50):
    inbox.act("notes", {iid!r}, "open", {{"note": "{who}-" + str(n)}}, Path({root!r}))
"""


def test_two_processes_acting_on_one_item_lose_no_history(root):
    rec, _ = inbox.add("notes", item(), root, TODAY)
    procs = [subprocess.Popen([sys.executable, "-c", _ACTOR.format(lib=str(LIB), iid=rec["id"], root=str(root), who=w)])
             for w in ("a", "b")]
    assert all(p.wait(timeout=120) == 0 for p in procs)
    assert len(inbox.get("notes", rec["id"], root)["history"]) == 100


# --- suggestions: import and read-time order (ADR 0017) -------------------------------------------------------------

def test_suggestions_import_parses_every_field(root):
    (root.parent).mkdir(parents=True)
    (root.parent / "suggestions.md").write_text(SUGGESTIONS_MD)
    out = inbox.import_legacy("suggestions", root, today=TODAY)
    assert out["added"] == 4 and out["problems"] == []
    items = {i["title"]: i for i in inbox.list_items("suggestions", root)["items"]}
    high = items["High one"]
    assert high["fields"] == {"priority": 9, "impact": "speed", "effort": "low"} and high["added"] == "2026-10-02"
    assert high["status"] == {"state": "open"} and high["source"] == "suggestions.md"
    assert high["body"].startswith("**Why**: big thing") and "- step 2" in high["body"]
    assert "**Priority**" not in high["body"] and "**Added**" not in high["body"]
    assert items["Done one"]["status"] == {"state": "promoted", "on": "2026-10-15",
                                            "note": "https://github.com/G-Eskayo/marvin/issues/470"}
    assert items["Tie on priority, better impact"]["status"]["state"] == "open"  # "open" is the same as pending


def test_suggestions_are_read_in_adr_0017_order(root):
    (root.parent).mkdir(parents=True)
    (root.parent / "suggestions.md").write_text(SUGGESTIONS_MD)
    inbox.import_legacy("suggestions", root, today=TODAY)
    titles = [i["title"] for i in inbox.list_items("suggestions", root)["items"]]
    assert titles == ["High one", "Tie on priority, better impact", "Low one", "Done one"]


def test_rendered_suggestion_parses_back_to_the_same_item(root):
    [orig] = [i for i in inbox.parse_suggestions(SUGGESTIONS_MD) if i["title"] == "High one"]
    [back] = inbox.parse_suggestions(inbox.render_suggestion(orig))
    assert {k: back[k] for k in ("title", "body", "fields", "status", "added")} == \
        {k: orig[k] for k in ("title", "body", "fields", "status", "added")}


def test_re_running_the_import_adds_nothing_and_never_touches_the_old_file(root):
    (root.parent).mkdir(parents=True)
    md = root.parent / "suggestions.md"
    md.write_text(SUGGESTIONS_MD)
    mtime = md.stat().st_mtime_ns
    first = inbox.import_legacy("suggestions", root, today=TODAY)
    second = inbox.import_legacy("suggestions", root, today=date(2026, 12, 1))
    assert first["added"] == 4 and second == {**second, "added": 0, "already_there": 4}
    assert md.read_text() == SUGGESTIONS_MD and md.stat().st_mtime_ns == mtime
    assert len(inbox.list_items("suggestions", root)["items"]) == 4


def test_an_item_acted_on_after_import_is_not_reimported(root):
    (root.parent).mkdir(parents=True)
    (root.parent / "suggestions.md").write_text(SUGGESTIONS_MD)
    inbox.import_legacy("suggestions", root, today=TODAY)
    [high] = [i for i in inbox.list_items("suggestions", root)["items"] if i["title"] == "High one"]
    inbox.act("suggestions", high["id"], "declined", {"note": "no"}, root, TODAY)
    assert inbox.import_legacy("suggestions", root, today=TODAY)["added"] == 0
    assert inbox.get("suggestions", high["id"], root)["status"]["state"] == "declined"


def test_import_on_two_machines_writes_identical_files(tmp_path):
    """Deterministic ids and content: the Macs' git sync sees the same file twice, not a conflict."""
    trees = []
    for mac in ("mini", "laptop"):
        r = tmp_path / mac / ".claude" / "inbox"
        r.parent.mkdir(parents=True)
        (r.parent / "suggestions.md").write_text(SUGGESTIONS_MD)
        inbox.import_legacy("suggestions", r, today=date(2026, 11, 4) if mac == "mini" else date(2026, 11, 9))
        trees.append({p.name: p.read_text() for p in (r / "suggestions").glob("*.json")})
    assert trees[0] == trees[1] and len(trees[0]) == 4


@pytest.mark.parametrize("text", ["", "no headers at all\n**Priority**: 5\n", "## \n", "## only a title",
                                  "## t\n**Priority**: lots\n**Status**:\n**Added**: someday\n", "\x00\x01## x\n"])
def test_odd_suggestion_files_import_without_crashing(root, text):
    root.parent.mkdir(parents=True)
    (root.parent / "suggestions.md").write_text(text)
    out = inbox.import_legacy("suggestions", root, today=TODAY)
    assert out["problems"] == []
    for i in inbox.list_items("suggestions", root)["items"]:
        assert i["status"]["state"] == "open" and "priority" not in i["fields"] and i["title"]


def test_duplicate_suggestion_titles_with_different_text_are_both_kept(root):
    root.parent.mkdir(parents=True)
    (root.parent / "suggestions.md").write_text("## Same\n**Why**: one\n\n## Same\n**Why**: two\n\n## Same\n**Why**: one\n")
    out = inbox.import_legacy("suggestions", root, today=TODAY)
    assert out["added"] == 2 and out["already_there"] == 1  # the exact repeat is folded


def test_a_huge_suggestions_file_imports_in_one_pass(root):
    root.parent.mkdir(parents=True)
    blocks = [f"## Item {n}\n**Priority**: {n % 10}\n**Status**: pending\n**Why**: w{n}\n**Added**: 2026-10-01\n"
              for n in range(1500)]
    (root.parent / "suggestions.md").write_text("\n".join(blocks))
    out = inbox.import_legacy("suggestions", root, today=TODAY)
    assert out["added"] == 1500
    assert len(inbox.open_items("suggestions", root)) == 1500


def test_a_symlinked_legacy_file_is_not_imported(root, tmp_path):
    root.parent.mkdir(parents=True)
    real = tmp_path / "elsewhere.md"
    real.write_text(SUGGESTIONS_MD)
    (root.parent / "suggestions.md").symlink_to(real)
    with pytest.raises(inbox.InboxError, match="symlink"):
        inbox.import_legacy("suggestions", root, today=TODAY)


def test_a_pile_without_an_importer_is_refused(root):
    with pytest.raises(inbox.InboxError, match="importer"):
        inbox.import_legacy("notes", root, today=TODAY)


# --- improvement-queue: import --------------------------------------------------------------------------------------

def test_queue_import_folds_identical_bullets_keeping_the_first_date(root):
    root.parent.mkdir(parents=True)
    (root.parent / "improvement-queue.md").write_text(QUEUE_MD)
    out = inbox.import_legacy("improvement-queue", root, today=TODAY)
    assert out["added"] == 4
    items = {i["fields"].get("kind") or "none": i for i in inbox.list_items("improvement-queue", root)["items"]}
    naming = items["NAMING"]
    assert naming["added"] == "2026-07-01" and naming["status"] == {"state": "open"}
    assert naming["fields"] == {"entry": "**[NAMING]** Generic parameter name `data` in `total()` at line 1. (`lib/widget.py`)",
                                "project": "marvin", "kind": "NAMING", "path": "lib/widget.py",
                                "message": "Generic parameter name `data` in `total()` at line 1."}
    assert items["KISS"]["status"] == {"state": "done", "note": "done, PR #944 merged", "on": "2026-07-01"}
    assert items["VERBOSITY"]["status"] == {"state": "skipped", "note": "skipped 2026-10-27, no tests cover lib",
                                            "on": "2026-10-27"}
    assert items["none"]["title"] == "free text bullet with no kind"


def test_queue_bullets_outside_a_dated_section_are_ignored():
    assert inbox.parse_queue("# Improvement Queue\n- **[NAMING]** x (`a.py`)\n## not a date — x\n- y\n") == []


def test_a_later_mark_wins_over_an_unmarked_first_copy():
    text = ("## 2026-07-01 — marvin\n- **[NAMING]** x (`a.py`)\n"
            "## 2026-07-02 — marvin\n- **[NAMING]** x (`a.py`) — auto-fix: in PR #9 (2026-07-03)\n")
    [only] = inbox.parse_queue(text)
    assert only["added"] == "2026-07-01" and only["status"] == {"state": "in_pr", "note": "in PR #9 (2026-07-03)",
                                                                "on": "2026-07-03"}


# --- the first write to a pile imports its legacy file first --------------------------------------------------------

def test_first_add_to_a_pile_imports_the_legacy_file_before_it(root):
    root.parent.mkdir(parents=True)
    (root.parent / "improvement-queue.md").write_text(QUEUE_MD)
    assert not inbox.pile_exists("improvement-queue", root)
    inbox.add("improvement-queue", inbox.queue_item("**[LOGIC]** new (`b.py`)", "LOGIC", "new", "b.py", "marvin",
                                                    "2026-11-04"), root, TODAY)
    assert len(inbox.list_items("improvement-queue", root)["items"]) == 5
    out = inbox.import_legacy("improvement-queue", root, today=TODAY)
    assert out["added"] == 0  # an explicit import afterwards is a no-op


def test_making_a_pile_leaves_no_staging_folder(root):
    inbox.add("notes", item(), root, TODAY)
    assert [p.name for p in root.iterdir()] == ["notes"]


# --- CLI ------------------------------------------------------------------------------------------------------------

def run_cli(home, *args):
    env = {**os.environ, "HOME": str(home)}
    out = subprocess.run([sys.executable, str(LIB / "inbox.py"), *args], capture_output=True, text=True, env=env)
    return out.returncode, json.loads(out.stdout)


def test_cli_add_list_act_import(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "suggestions.md").write_text(SUGGESTIONS_MD)
    rc, out = run_cli(tmp_path, "import", "suggestions")
    assert rc == 0 and out["ok"] and out["added"] == 4
    rc, out = run_cli(tmp_path, "import", "suggestions")
    assert rc == 0 and out["added"] == 0
    rc, out = run_cli(tmp_path, "add", "suggestions", "--json", json.dumps({"title": "New", "fields": {"priority": 10}}))
    assert rc == 0 and out["created"]
    rc, listed = run_cli(tmp_path, "list", "suggestions")
    assert rc == 0 and listed["items"][0]["title"] == "New"
    rc, out = run_cli(tmp_path, "act", "suggestions", out["item"]["id"], "done", "--json", '{"note": "shipped"}')
    assert rc == 0 and out["item"]["status"]["state"] == "done"
    rc, out = run_cli(tmp_path, "set", "suggestions", out["item"]["id"], "--json", '{"priority": 1}')
    assert rc == 0 and out["item"]["fields"]["priority"] == 1


@pytest.mark.parametrize("args", [("list", "../x"), ("act", "notes", "../../x", "done"), ("add", "notes", "--json", "{bad"),
                                  ("import", "notes"), ("bogus",), ()])
def test_cli_errors_are_json_with_nonzero_exit(tmp_path, args):
    rc, out = run_cli(tmp_path, *args)
    assert rc == 1 and out["ok"] is False and out["error"]


def test_an_item_that_would_outgrow_the_size_cap_is_refused_and_the_file_stays_readable(root):
    rec, _ = inbox.add("notes", item(fields={"blob": "x" * 200_000}), root, TODAY)
    with pytest.raises(inbox.InboxError, match="bigger"):
        inbox.update_fields("notes", rec["id"], {"more": "y" * 100_000}, root, TODAY)
    with pytest.raises(inbox.InboxError, match="bigger"):
        inbox.add("notes", item(fields={"blob": "x" * 300_000}), root, TODAY)
    assert inbox.list_items("notes", root)["problems"] == []
    assert inbox.get("notes", rec["id"], root)["fields"] == {"blob": "x" * 200_000}


def test_a_value_json_cannot_store_is_refused(root):
    with pytest.raises(inbox.InboxError, match="JSON"):
        inbox.add("notes", item(fields={"when": date(2026, 1, 1)}), root, TODAY)
    assert not list((root / "notes").glob("*"))  or all(p.name == ".locks" for p in (root / "notes").iterdir())
