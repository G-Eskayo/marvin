"""The dashboard's safety-review cards (approved 2026-10-26): list the pending quarantine entries and answer one.

Tests try to break the reader and the one writer: empty, missing, torn, duplicate, huge and hostile entries; the file
changing between read and write; two answers at once; an answer for an entry answered elsewhere; and a git merge of
two Macs answering different entries. Every test works in tmp_path; none touches the real ~/.claude.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
# Another test in the same worker may already have imported these by bare name from a different checkout (the
# session-start report loads the installed ~/.agents copy): this file tests the ones next to it.
for _name in ("calibrate", "process_quarantine_reviews", "verify"):
    _mod = sys.modules.get(_name)
    if _mod is not None and Path(getattr(_mod, "__file__", "") or "").resolve().parent != SCRIPTS:
        del sys.modules[_name]

import calibrate  # noqa: E402
import process_quarantine_reviews as q  # noqa: E402
import verify  # noqa: E402

PREAMBLE = "# Quarantine\n\nArtifacts flagged by the safety monitor, awaiting review.\n"
FOOTER = "- [ ] approve (ships as-is)\n- [ ] modify: ____________\n- [ ] deny\n"


def entry(date="2026-10-24", loop="research_colony", score="0.35", tau="0.30", body="A method for audits.",
          reason="possible unsupported claim", footer=FOOTER) -> str:
    quoted = "\n".join(f"> {line}" for line in body.splitlines())
    text = f"\n---\n## {date} — {loop} [SAFETY, score {score}, tau {tau}]\n{quoted}\n\n"
    if reason:
        text += f"Flagged reason: {reason}\n\n"
    return text + footer


@pytest.fixture
def qfile(tmp_path, monkeypatch):
    path = tmp_path / ".claude" / "quarantine.md"
    path.parent.mkdir()
    monkeypatch.setattr(q, "QUARANTINE_FILE", path)
    monkeypatch.setattr(verify, "QUARANTINE_FILE", path)
    state = tmp_path / ".claude" / "safety-monitor"
    monkeypatch.setattr(calibrate, "STATE_DIR", state)
    monkeypatch.setattr(calibrate, "CALIBRATION_FILE", state / "calibration.jsonl")
    monkeypatch.setattr(calibrate, "TAU_FILE", state / "tau.json")
    return path


def labels(qfile: Path) -> list[dict]:
    f = qfile.parent / "safety-monitor" / "calibration.jsonl"
    return [json.loads(line) for line in f.read_text().splitlines()] if f.exists() else []


# --- reading -------------------------------------------------------------------------------------------------------

def test_lists_source_date_score_tau_reason_and_excerpt(qfile):
    qfile.write_text(PREAMBLE + entry())
    out = q.list_pending()
    assert out["pending"] == 1 and out["unreadable"] == 0
    e = out["entries"][0]
    assert (e["date"], e["loop"], e["score"], e["tau"]) == ("2026-10-24", "research_colony", 0.35, 0.30)
    assert e["reason"] == "possible unsupported claim"
    assert e["excerpt"] == "A method for audits."
    assert e["body"] == "A method for audits."
    assert len(e["id"]) == 16


def test_missing_and_empty_files_are_no_entries(qfile):
    assert q.list_pending() == {"entries": [], "pending": 0, "unreadable": 0}
    qfile.write_text("")
    assert q.list_pending() == {"entries": [], "pending": 0, "unreadable": 0}
    qfile.write_text(PREAMBLE)
    assert q.list_pending()["entries"] == []


def test_no_reason_line_is_an_empty_reason(qfile):
    qfile.write_text(PREAMBLE + entry(reason=""))
    assert q.list_pending()["entries"][0]["reason"] == ""


def test_a_torn_entry_is_counted_unreadable_not_shown_and_cannot_be_answered(qfile):
    torn = entry(footer="- [ ] approve (ships as-")  # the write stopped mid-footer
    qfile.write_text(PREAMBLE + entry(body="good one") + torn)
    out = q.list_pending()
    assert [e["body"] for e in out["entries"]] == ["good one"]
    assert out["unreadable"] == 1
    tid = q.entry_id(q._split_entries(qfile.read_text())[1][1])
    before = qfile.read_text()
    assert q.answer(tid, "deny")["status"] == "invalid"
    assert qfile.read_text() == before


def test_an_entry_that_lost_its_whole_footer_is_shown_and_answerable(qfile):
    # Seen in the real file: older entries whose boxes were lost in a past sync conflict.
    bare = "\n---\n## 2026-07-17 — research_colony [SAFETY, score 0.38, tau 0.30]\n> lost its footer\n"
    qfile.write_text(PREAMBLE + bare + entry(body="after"))
    out = q.list_pending()
    assert [e["body"] for e in out["entries"]] == ["lost its footer", "after"] and out["unreadable"] == 0
    assert q.answer(out["entries"][0]["id"], "modify", "keep it")["status"] == "answered"
    assert labels(qfile) == [{"loop": "research_colony", "score": 0.38, "label": 0, "note": "keep it"}]
    assert [e["body"] for e in q.list_pending()["entries"]] == ["after"]


def test_answered_entries_are_not_pending(qfile):
    qfile.write_text(PREAMBLE + entry(body="one", footer=FOOTER.replace("- [ ] deny", "- [x] deny")) + entry(body="two"))
    out = q.list_pending()
    assert [e["body"] for e in out["entries"]] == ["two"]


def test_a_legacy_entry_with_an_unquoted_divider_in_its_body_parses_as_one_entry(qfile):
    legacy = "\n---\n## 2026-07-04 — daily_digest [SAFETY, score 0.78, tau 0.30]\n> first line\n\n---\nmore body\n\n" + FOOTER
    qfile.write_text(PREAMBLE + legacy)
    e = q.list_pending()["entries"]
    assert len(e) == 1 and "more body" in e[0]["body"]


def test_script_in_an_entry_comes_back_as_plain_text(qfile):
    nasty = '<script>alert(1)</script><img src=x onerror="alert(2)">'
    qfile.write_text(PREAMBLE + entry(body=nasty, reason="<b>bold</b>"))
    e = q.list_pending()["entries"][0]
    assert e["body"] == nasty and e["reason"] == "<b>bold</b>"  # unchanged text; the UI renders it as text


def test_a_huge_entry_is_capped_for_display_but_the_file_is_untouched(qfile):
    huge = "x" * 2_000_000
    qfile.write_text(PREAMBLE + entry(body=huge))
    e = q.list_pending()["entries"][0]
    assert e["truncated"] is True
    assert len(e["body"]) == q.BODY_CAP
    assert len(e["excerpt"]) <= q.EXCERPT_CAP + 1
    assert q.answer(e["id"], "approve")["status"] == "answered"
    assert labels(qfile) == [{"loop": "research_colony", "score": 0.35, "label": 0}]


def test_duplicate_headers_with_different_content_are_two_entries(qfile):
    qfile.write_text(PREAMBLE + entry(body="first") + entry(body="second"))
    out = q.list_pending()["entries"]
    assert [e["body"] for e in out] == ["first", "second"]
    assert out[0]["id"] != out[1]["id"]
    q.answer(out[1]["id"], "deny")
    assert [e["body"] for e in q.list_pending()["entries"]] == ["first"]


def test_byte_identical_duplicates_are_answered_one_at_a_time(qfile):
    qfile.write_text(PREAMBLE + entry() + entry())
    ids = [e["id"] for e in q.list_pending()["entries"]]
    assert ids[0] == ids[1]
    assert q.answer(ids[0], "approve")["status"] == "answered"
    assert q.list_pending()["pending"] == 1
    assert q.answer(ids[0], "deny")["status"] == "answered"
    assert q.list_pending()["pending"] == 0
    assert [r["label"] for r in labels(qfile)] == [0, 1]


# --- answering -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind,label", [("approve", 0), ("deny", 1)])
def test_answer_records_the_label_and_removes_only_that_entry(qfile, kind, label):
    qfile.write_text(PREAMBLE + entry(body="one") + entry(body="two", loop="daily_digest", score="0.55") + entry(body="three"))
    before = qfile.read_text()
    target = q.list_pending()["entries"][1]
    res = q.answer(target["id"], kind)
    assert res["status"] == "answered" and res["remaining"] == 2
    assert labels(qfile) == [{"loop": "daily_digest", "score": 0.55, "label": label}]
    after = qfile.read_text()
    # Everything else is byte-for-byte where it was: the preamble and the two other entries, in order. Only the
    # answered entry's own lines went; its trailing divider stays (so two Macs' removals never touch).
    two_block = q._split_entries(before)[1][1]
    assert after == before.replace(two_block, "\n---\n")
    assert "> two" not in after
    assert [e["body"] for e in q.list_pending()["entries"]] == ["one", "three"]


def test_modify_keeps_the_typed_text_as_data(qfile):
    qfile.write_text(PREAMBLE + entry())
    eid = q.list_pending()["entries"][0]["id"]
    typed = "drop the second claim; $(rm -rf ~) `whoami`\n## 2026-01-01 — fake [SAFETY, score 0.99, tau 0.10]"
    res = q.answer(eid, "modify", typed)
    assert res["status"] == "answered"
    rows = labels(qfile)
    assert rows[0]["label"] == 0
    # One line, never a new entry header; kept verbatim otherwise.
    assert "\n" not in rows[0]["note"] and rows[0]["note"].startswith("drop the second claim; $(rm -rf ~) `whoami`")
    assert q.list_pending()["pending"] == 0 and "fake" not in qfile.read_text()


@pytest.mark.parametrize("text", [None, "", "   ", "\n\t "])
def test_modify_with_empty_text_is_refused_and_changes_nothing(qfile, text):
    qfile.write_text(PREAMBLE + entry())
    before = qfile.read_text()
    eid = q.list_pending()["entries"][0]["id"]
    assert q.answer(eid, "modify", text) == {"status": "invalid", "reason": "empty"}
    assert qfile.read_text() == before and labels(qfile) == []


def test_unknown_kind_and_oversized_text_are_refused(qfile):
    qfile.write_text(PREAMBLE + entry())
    eid = q.list_pending()["entries"][0]["id"]
    assert q.answer(eid, "ship")["status"] == "invalid"
    assert q.answer(eid, "modify", "y" * (q.NOTE_CAP + 1)) == {"status": "invalid", "reason": "too-long"}
    assert q.list_pending()["pending"] == 1


def test_answer_on_a_missing_file_is_gone_not_a_crash(qfile):
    assert q.answer("0" * 16, "approve")["status"] == "gone"
    assert not qfile.exists()


def test_file_changed_between_read_and_write_matches_by_content_not_position(qfile):
    qfile.write_text(PREAMBLE + entry(body="alpha") + entry(body="beta"))
    beta = q.list_pending()["entries"][1]
    # Another Mac synced: a new entry landed in front and alpha was answered and removed there.
    qfile.write_text(PREAMBLE + entry(body="newcomer", date="2026-10-25") + entry(body="beta"))
    assert q.answer(beta["id"], "deny")["status"] == "answered"
    assert [e["body"] for e in q.list_pending()["entries"]] == ["newcomer"]
    assert labels(qfile)[0]["label"] == 1


def test_an_entry_answered_elsewhere_is_reported_and_not_answered_twice(qfile):
    qfile.write_text(PREAMBLE + entry(body="alpha") + entry(body="beta"))
    alpha = q.list_pending()["entries"][0]
    # Elsewhere: removed after its answer was recorded.
    qfile.write_text(PREAMBLE + entry(body="beta"))
    assert q.answer(alpha["id"], "approve")["status"] == "gone"
    assert labels(qfile) == []
    # Elsewhere: ticked by hand but not processed yet. Not ticked again; this run records the existing answer once.
    qfile.write_text(PREAMBLE + entry(body="alpha", footer=FOOTER.replace("- [ ] deny", "- [x] deny")) + entry(body="beta"))
    res = q.answer(alpha["id"], "approve")
    assert res["status"] == "already-answered" and res["kind"] == "deny"
    assert [r["label"] for r in labels(qfile)] == [1]


def test_a_write_that_races_a_sync_retries_on_the_fresh_text(qfile, monkeypatch):
    qfile.write_text(PREAMBLE + entry(body="alpha") + entry(body="beta"))
    alpha = q.list_pending()["entries"][0]
    real_read = q._read
    calls = {"n": 0}

    def racing_read(path):
        calls["n"] += 1
        if calls["n"] == 2:  # git rewrites the file right after our first read (outside our lock)
            path.write_text(PREAMBLE + entry(body="alpha") + entry(body="beta") + entry(body="synced in"))
        return real_read(path)

    monkeypatch.setattr(q, "_read", racing_read)
    assert q.answer(alpha["id"], "approve")["status"] == "answered"
    assert [e["body"] for e in q.list_pending()["entries"]] == ["beta", "synced in"]


def test_two_concurrent_answers_both_land(qfile):
    qfile.write_text(PREAMBLE + "".join(entry(body=f"item {i}") for i in range(12)))
    ids = [e["id"] for e in q.list_pending()["entries"]]
    results = []
    threads = [threading.Thread(target=lambda i=i: results.append(q.answer(i, "deny"))) for i in ids[:6]]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r["status"] for r in results) == ["answered"] * 6
    assert [e["body"] for e in q.list_pending()["entries"]] == [f"item {i}" for i in range(6, 12)]
    assert len(labels(qfile)) == 6


def test_two_processes_answering_at_once_both_land(qfile, tmp_path):
    qfile.write_text(PREAMBLE + "".join(entry(body=f"item {i}") for i in range(6)))
    ids = [e["id"] for e in q.list_pending()["entries"]]
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    script = str(SCRIPTS / "process_quarantine_reviews.py")
    procs = [subprocess.Popen([sys.executable, script, "answer", "--id", i, "--kind", "approve"], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in ids[:4]]
    outs = [json.loads(p.communicate(timeout=60)[0]) for p in procs]
    assert [o["status"] for o in outs] == ["answered"] * 4
    assert [e["body"] for e in q.list_pending()["entries"]] == ["item 4", "item 5"]


def test_quarantine_appends_wait_for_the_lock_and_are_not_lost(qfile):
    qfile.write_text(PREAMBLE + "".join(entry(body=f"item {i}") for i in range(4)))
    ids = [e["id"] for e in q.list_pending()["entries"]]
    threads = [threading.Thread(target=q.answer, args=(i, "approve")) for i in ids]
    threads += [threading.Thread(target=verify.quarantine, args=(f"new artifact {n}", 0.5, f"loop_{n}", 0.3)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(e["body"] for e in q.list_pending()["entries"]) == [f"new artifact {n}" for n in range(4)]


def test_no_temp_files_are_left_behind(qfile):
    qfile.write_text(PREAMBLE + entry())
    q.answer(q.list_pending()["entries"][0]["id"], "approve")
    leftovers = [p.name for p in qfile.parent.iterdir() if p.name not in ("quarantine.md", "safety-monitor", ".quarantine.md.lock")]
    assert leftovers == []


def test_process_alone_no_longer_adds_a_divider_before_every_entry(qfile):
    qfile.write_text(PREAMBLE + entry(body="a", footer=FOOTER.replace("- [ ] deny", "- [x] deny")) + entry(body="b") + entry(body="c"))
    before = qfile.read_text()
    q.process()
    text = qfile.read_text()
    # The old rebuild put an extra "\n---\n" before every remaining entry (a whole-file rewrite on every review).
    assert text == before.replace(q._split_entries(before)[1][0], "\n---\n")
    q.process()  # run twice: nothing else changes
    assert qfile.read_text() == text


def test_cli_list_and_answer_speak_json(qfile, tmp_path):
    qfile.write_text(PREAMBLE + entry(body="<script>x</script>"))
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    script = str(SCRIPTS / "process_quarantine_reviews.py")
    listed = json.loads(subprocess.run([sys.executable, script, "list"], env=env, capture_output=True, text=True, timeout=60).stdout)
    assert listed["entries"][0]["body"] == "<script>x</script>"
    run = subprocess.run([sys.executable, script, "answer", "--id", listed["entries"][0]["id"], "--kind", "modify", "--text", "tighten it"],
                         env=env, capture_output=True, text=True, timeout=60)
    assert json.loads(run.stdout)["status"] == "answered"
    empty = subprocess.run([sys.executable, script, "answer", "--id", "x", "--kind", "modify", "--text", ""],
                           env=env, capture_output=True, text=True, timeout=60)
    assert json.loads(empty.stdout) == {"status": "invalid", "reason": "empty"}


# --- two Macs, one git-synced file ---------------------------------------------------------------------------------

def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, capture_output=True, text=True)


@pytest.mark.parametrize("first,second", [(0, 1), (1, 0), (0, 2), (2, 1)])
def test_two_macs_answering_different_entries_merge_cleanly(qfile, monkeypatch, tmp_path, first, second):
    """Adjacent entries answered on two Macs between syncs must merge with no conflict and lose neither answer.
    (Deleting the whole block made adjacent removals touch, which git reports as a conflict.)"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "quarantine.md").write_text(PREAMBLE + entry(body="zero") + entry(body="one") + entry(body="two"))
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    ids = [e["id"] for e in (monkeypatch.setattr(q, "QUARANTINE_FILE", repo / "quarantine.md") or q.list_pending()["entries"])]

    _git(repo, "checkout", "-qb", "mac2")
    q.answer(ids[second], "deny")
    _git(repo, "commit", "-qam", "mac2 answer")
    _git(repo, "checkout", "-q", "main")
    q.answer(ids[first], "approve")
    _git(repo, "commit", "-qam", "mac1 answer")
    merged = _git(repo, "merge", "-q", "mac2", "-m", "sync")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    left = {0, 1, 2} - {first, second}
    assert [e["body"] for e in q.list_pending()["entries"]] == [["zero", "one", "two"][i] for i in sorted(left)]
    assert "<<<<<<<" not in (repo / "quarantine.md").read_text()


def test_two_macs_ticking_different_entries_without_processing_merge_cleanly(qfile, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    f = repo / "quarantine.md"
    f.write_text(PREAMBLE + entry(body="zero") + entry(body="one"))
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    blocks = q._split_entries(f.read_text())[1]
    _git(repo, "checkout", "-qb", "mac2")
    f.write_text(f.read_text().replace(blocks[1], q._tick(blocks[1], "deny", "")))
    _git(repo, "commit", "-qam", "mac2 tick")
    _git(repo, "checkout", "-q", "main")
    f.write_text(f.read_text().replace(blocks[0], q._tick(blocks[0], "modify", "fix it")))
    _git(repo, "commit", "-qam", "mac1 tick")
    assert _git(repo, "merge", "-q", "mac2", "-m", "sync").returncode == 0
    infos = [q._parse_block(b) for b in q._split_entries(f.read_text())[1]]
    assert [i["checked"] for i in infos] == ["modify", "deny"]
