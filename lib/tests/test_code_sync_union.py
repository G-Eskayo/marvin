"""ADR 0076: files both Macs only ever add to merge with git's `union` driver, so a stash pop or merge on them never
stops sync. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_code_sync_union.py -v

2026-10-22..26: three stash-pop conflicts on the synced Claude dir (quarantine.md, improvement-queue.md, a memory index
and memory notes) blocked code sync for up to four days. Every one was "each Mac added different lines; keep both."

Two real clones of one bare origin play the two Macs, each under its own temp HOME. Never the real Claude dir.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import code_sync as cs  # noqa: E402
import health_checks  # noqa: E402

MEM = "projects/p/memory"
SEED = {
    "sync-log.md": "# log\n",
    "auto-fix-log.md": "# auto-fix log\n",
    "quarantine.md": "# Quarantine\n\n## 2026-10-01 — digest [SAFETY]\nfirst body\n",
    "improvement-queue.md": "# Improvement Queue\n\n## 2026-10-01 — one\n",
    f"{MEM}/MEMORY.md": "# Memory Index\n\n- [Alpha](alpha.md) — a\n- [Beta](beta.md) — b\n",
    f"{MEM}/alpha.md": "---\nname: alpha\n---\n\nalpha note line\n",
    "lexicon.md": "# Lexicon\n\n- **term** — v1\n",
}
SCOPED = ["sync-log.md", "auto-fix-log.md", "quarantine.md", "improvement-queue.md", f"{MEM}/MEMORY.md", f"{MEM}/alpha.md"]


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _git(repo: Path, *args: str) -> str:
    r = _run(repo, *args)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _clone(origin: Path, home: Path) -> Path:
    home.mkdir(parents=True)
    repo = home / ".claude"
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    return repo


@pytest.fixture
def macs(tmp_path, monkeypatch):
    """(mac_a, mac_b): two clones named like the real synced dir, each in its own temp HOME. The sync log and the
    review file live in a third temp dir, so they never dirty either clone."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-q", "-b", "main")
    _git(seed, "config", "user.email", "test@example.com")
    _git(seed, "config", "user.name", "Test")
    for rel, text in SEED.items():
        (seed / rel).parent.mkdir(parents=True, exist_ok=True)
        (seed / rel).write_text(text)
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "seed")
    _git(seed, "push", "-q", str(origin), "main")

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(cs, "LOG_PATH", state / "sync-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)
    monkeypatch.setattr(cs, "_live_edit_lease", lambda *a, **kw: None)
    monkeypatch.setattr(cs.error_log, "record", lambda *a, **kw: None)
    return _clone(origin, tmp_path / "home-a"), _clone(origin, tmp_path / "home-b")


def _append(repo: Path, rel: str, text: str) -> None:
    with (repo / rel).open("a") as f:
        f.write(text)


def _publish(repo: Path, msg: str = "other mac") -> None:
    """The other Mac commits and pushes with plain git (only the pulling side runs code_sync)."""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    _git(repo, "push", "-q", "origin", "main")


def _log() -> str:
    return cs.LOG_PATH.read_text() if cs.LOG_PATH.exists() else ""


def _attributes(repo: Path) -> Path:
    return repo / ".git" / "info" / "attributes"


def _assert_unstuck(repo: Path) -> None:
    assert _git(repo, "stash", "list") == "", "a stash was left behind"
    assert cs._stuck_from_previous_run(repo) is None
    for rel in SCOPED:
        assert not cs.CONFLICT_MARKER_RE.search((repo / rel).read_text()), f"conflict markers in {rel}"
    assert "CONFLICT" not in _log() and "conflicted" not in _log(), _log()


# ── both Macs append different entries ──────────────────────────────────────────────────────────────────────────────

def test_both_macs_append_different_entries_to_every_scoped_file_and_nothing_is_lost(macs):
    a, b = macs
    for rel in SCOPED:
        _append(a, rel, f"from A: {rel}\n")
    _publish(a)
    for rel in SCOPED:
        _append(b, rel, f"from B: {rel}\n")   # B's WIP, uncommitted: pull() stashes, merges and pops it

    cs.pull(b)

    _assert_unstuck(b)
    for rel in SCOPED:
        text = (b / rel).read_text()
        assert f"from A: {rel}\n" in text and f"from B: {rel}\n" in text, f"{rel} lost a side:\n{text}"
        assert text.startswith(SEED[rel]), f"{rel} lost its original content"
    # a memory note is edited in place, so it is no longer union: both appends at one spot are a real conflict,
    # auto-resolved by keeping both sides and shown for a person to tidy (the one item)
    assert [(i["kind"], i["file"]) for i in cs.union_review_open()] == [("auto-resolved", f"{MEM}/alpha.md")]


def test_both_macs_commit_appends_and_push_merges_them_without_stopping(macs):
    """The push path: B committed its own entries, its push is rejected, it merges origin and retries."""
    a, b = macs
    for rel in SCOPED:
        _append(a, rel, f"from A: {rel}\n")
    _publish(a)
    for rel in SCOPED:
        _append(b, rel, f"from B: {rel}\n")

    cs.push(b)

    _assert_unstuck(b)
    assert _git(b, "rev-parse", "HEAD") == _git(b, "rev-parse", "origin/main"), _log()
    _git(a, "pull", "-q", "--no-rebase", "origin", "main")
    for rel in SCOPED:
        text = (a / rel).read_text()
        assert f"from A: {rel}\n" in text and f"from B: {rel}\n" in text, rel


def test_a_file_new_on_both_macs_in_scope_merges_too(macs):
    """A memory note both Macs created independently (an add/add) is also in scope."""
    a, b = macs
    (a / MEM / "gamma.md").write_text("gamma from A\n")
    _publish(a)
    (b / MEM / "gamma.md").write_text("gamma from B\n")
    _git(b, "add", "-A")
    _git(b, "commit", "-q", "-m", "B's own gamma")

    cs.pull(b)

    _assert_unstuck(b)
    text = (b / MEM / "gamma.md").read_text()
    assert "gamma from A" in text and "gamma from B" in text


# ── both append the same line ───────────────────────────────────────────────────────────────────────────────────────

def test_both_append_the_identical_line_at_the_same_place_it_is_kept_once(macs):
    a, b = macs
    line = "- [Gamma](gamma.md) — g\n"
    _append(a, f"{MEM}/MEMORY.md", line)
    _publish(a)
    _append(b, f"{MEM}/MEMORY.md", line)

    cs.pull(b)

    _assert_unstuck(b)
    assert (b / MEM / "MEMORY.md").read_text().count(line) == 1
    assert cs.union_review_open() == []


def test_the_same_index_line_added_beside_different_lines_is_deduplicated_and_logged(macs):
    """Union keeps both sides' hunks whole, so a shared line inside them lands twice. That copy is removed."""
    a, b = macs
    shared = "- [Gamma](gamma.md) — g"
    _append(a, f"{MEM}/MEMORY.md", f"{shared}\n- [Delta](delta.md) — d\n")
    _publish(a)
    _append(b, f"{MEM}/MEMORY.md", f"- [Eps](eps.md) — e\n{shared}\n")

    cs.pull(b)

    _assert_unstuck(b)
    lines = (b / MEM / "MEMORY.md").read_text().splitlines()
    assert lines.count(shared) == 1, lines
    assert "- [Delta](delta.md) — d" in lines and "- [Eps](eps.md) — e" in lines
    assert lines[:4] == SEED[f"{MEM}/MEMORY.md"].splitlines()
    log = _log()
    assert "removed 1 exact duplicate" in log and shared in log, log
    assert cs.union_review_open() == []


def test_the_same_memory_linked_twice_with_different_text_is_flagged_not_deleted(macs):
    a, b = macs
    _append(a, f"{MEM}/MEMORY.md", "- [Gamma](gamma.md) — from A\n")
    _publish(a)
    _append(b, f"{MEM}/MEMORY.md", "- [Gamma note](gamma.md) — from B\n")

    cs.pull(b)

    _assert_unstuck(b)
    text = (b / MEM / "MEMORY.md").read_text()
    assert "— from A" in text and "— from B" in text, "a line that isn't an exact duplicate was deleted"
    items = cs.union_review_open()
    assert [i["kind"] for i in items] == ["linked-twice"] and items[0]["target"] == "gamma.md"
    assert health_checks.check_union_merge_review()["severity"] == "yellow"

    # A person keeps one of them: the item clears on its own (a live reading, nothing to dismiss).
    (b / MEM / "MEMORY.md").write_text(text.replace("- [Gamma note](gamma.md) — from B\n", ""))
    assert cs.union_review_open() == []
    assert health_checks.check_union_merge_review()["severity"] == "green"


def test_a_quarantine_heading_both_macs_added_is_flagged_not_merged_away(macs):
    """Two different quarantine entries can share a heading (same day, source and score) -- the real file has two
    such pairs -- so a doubled heading is reported, never removed."""
    a, b = macs
    heading = "## 2026-10-26 — research_colony [SAFETY, score 0.35]"
    _append(a, "quarantine.md", f"\n{heading}\nA's finding\n")
    _publish(a)
    _append(b, "quarantine.md", f"\n## 2026-10-26 — other [SAFETY]\nB's other\n\n{heading}\nB's finding\n")

    cs.pull(b)

    _assert_unstuck(b)
    text = (b / "quarantine.md").read_text()
    assert text.count(heading) == 2 and "A's finding" in text and "B's finding" in text
    assert [i["kind"] for i in cs.union_review_open()] == ["heading-twice"]


def test_headings_that_were_already_doubled_before_the_merge_are_not_flagged(macs):
    a, b = macs
    heading = "## 2026-10-13 — research_colony [SAFETY]"
    _append(a, "quarantine.md", f"\n{heading}\none\n\n{heading}\ntwo\n")
    _publish(a)
    _git(b, "pull", "-q", "--no-rebase", "origin", "main")
    _append(a, "quarantine.md", "\n## later A\n")
    _publish(a)
    _append(b, "quarantine.md", "\n## later B\n")

    cs.pull(b)

    _assert_unstuck(b)
    assert cs.union_review_open() == []


# ── an edit in the middle while the other Mac appends ───────────────────────────────────────────────────────────────

def test_an_edit_away_from_the_other_macs_append_merges_normally_with_nothing_kept_twice(macs):
    a, b = macs
    path = f"{MEM}/MEMORY.md"
    (a / path).write_text(SEED[path].replace("— a\n", "— a, edited\n"))
    _publish(a)
    _append(b, path, "- [Gamma](gamma.md) — g\n")

    cs.pull(b)

    _assert_unstuck(b)
    text = (b / path).read_text()
    assert "— a, edited" in text and "- [Gamma](gamma.md) — g" in text
    assert "- [Alpha](alpha.md) — a\n" not in text, "union resurrected the line A edited"
    assert cs.union_review_open() == []


def test_an_edit_touching_the_other_macs_append_interleaves_and_is_flagged_not_silent(macs):
    """The interleave: A edits the last line, B appends right after it. Union keeps A's hunk and B's whole, so the
    old line comes back beside the edited one. Nothing is lost, but the edit is undone in effect: flagged."""
    a, b = macs
    path = f"{MEM}/MEMORY.md"
    (a / path).write_text(SEED[path].replace("- [Beta](beta.md) — b\n", "- [Beta](beta.md) — b, edited\n"))
    _publish(a)
    _append(b, path, "- [Gamma](gamma.md) — g\n")

    cs.pull(b)

    _assert_unstuck(b)
    text = (b / path).read_text()
    assert "- [Beta](beta.md) — b, edited\n" in text and "- [Gamma](gamma.md) — g\n" in text
    assert "- [Beta](beta.md) — b\n" in text, "expected union to keep the old line; the test's premise changed"
    kinds = sorted(i["kind"] for i in cs.union_review_open())
    assert kinds == ["kept-changed-line", "linked-twice"], cs.union_review_open()
    assert "kept a line the other side changed or removed" in _log()
    result = health_checks.check_union_merge_review()
    assert result["severity"] == "yellow" and "MEMORY.md" in result["detail"]

    (b / path).write_text(text.replace("- [Beta](beta.md) — b\n", ""))
    assert cs.union_review_open() == []


def test_a_deletion_next_to_the_other_macs_append_is_flagged(macs):
    """improvement-queue items get removed when done; a removal beside an append comes back."""
    a, b = macs
    (a / "improvement-queue.md").write_text("# Improvement Queue\n\n")
    _publish(a)
    _append(b, "improvement-queue.md", "## 2026-10-26 — two\n")

    cs.pull(b)

    _assert_unstuck(b)
    assert "## 2026-10-01 — one" in (b / "improvement-queue.md").read_text()
    items = cs.union_review_open()
    assert [(i["kind"], i["line"]) for i in items] == [("kept-changed-line", "## 2026-10-01 — one")]


# ── outside the scope a conflict still stops for a person ───────────────────────────────────────────────────────────

def test_a_conflict_outside_the_scope_still_stops_for_a_person_with_nothing_lost(macs):
    """The Claude dir commits local work before merging (no stash): a real conflict aborts the merge, B's edit is safe
    in its own commit, and every later pull stops again until a person merges it."""
    a, b = macs
    (a / "lexicon.md").write_text(SEED["lexicon.md"].replace("v1", "A's wording"))
    _publish(a)
    (b / "lexicon.md").write_text(SEED["lexicon.md"].replace("v1", "B's wording"))

    cs.pull(b)

    assert "CONFLICT merging origin/main" in _log() and "committed locally, nothing lost" in _log()
    assert _git(b, "stash", "list") == "", "no stash on the Claude dir's path"
    assert "B's wording" in _git(b, "show", "HEAD:lexicon.md")
    assert not (b / ".git" / "MERGE_HEAD").exists() and _git(b, "status", "--porcelain") == ""
    cs.pull(b)
    assert _log().count("CONFLICT merging origin/main") == 2, "it must keep stopping, not merge it away"


def test_a_conflict_outside_the_scope_still_stops_on_merge_while_scoped_files_alone_would_not(macs):
    a, b = macs
    (a / "lexicon.md").write_text(SEED["lexicon.md"].replace("v1", "A's wording"))
    _append(a, "quarantine.md", "A\n")
    _publish(a)
    (b / "lexicon.md").write_text(SEED["lexicon.md"].replace("v1", "B's wording"))
    _append(b, "quarantine.md", "B\n")
    _git(b, "add", "-A")
    _git(b, "commit", "-q", "-m", "B")
    head = _git(b, "rev-parse", "HEAD")

    cs.pull(b)

    assert "CONFLICT merging origin/main" in _log() and "lexicon.md" in _log()
    assert "Merge conflict in quarantine.md" not in _log(), "a scoped file conflicted"
    assert _git(b, "rev-parse", "HEAD") == head and _git(b, "status", "--porcelain") == ""


# ── the duplicate check removes only exact duplicate index lines ────────────────────────────────────────────────────

def test_dedupe_removes_only_exact_duplicate_index_lines(tmp_path):
    index = tmp_path / "MEMORY.md"
    original = (
        "# Memory Index\n"
        "\n"
        "- [Alpha](alpha.md) — a\n"
        "- [Beta](beta.md) — b\n"
        "- [Alpha](alpha.md) — a\n"            # exact duplicate: removed
        "- [Alpha](alpha.md) — a \n"           # trailing space: not exact, kept
        "- [Alpha](alpha.md) — a, longer\n"    # same link, other text: kept
        "\n"                                   # blank line twice: kept
        "Some prose line.\n"
        "Some prose line.\n"                   # duplicate prose (not an index line): kept
        "## Section\n"
        "## Section\n"                         # duplicate heading: kept
        "- [Beta](beta.md) — b\n"              # exact duplicate after other content: removed
        "- [Gamma](gamma.md) — g"              # no trailing newline: kept, and the file still ends without one
    )
    index.write_text(original)

    removed = cs._dedupe_index_lines(index)

    assert removed == ["- [Alpha](alpha.md) — a", "- [Beta](beta.md) — b"]
    expected = original.replace("- [Beta](beta.md) — b\n- [Alpha](alpha.md) — a\n", "- [Beta](beta.md) — b\n", 1)
    expected = expected.replace("## Section\n- [Beta](beta.md) — b\n", "## Section\n", 1)
    assert index.read_text() == expected
    assert cs._dedupe_index_lines(index) == [], "a second run must change nothing"


@pytest.mark.parametrize("content", ["", "\n\n", "no index here\n", "- [x](x.md)\n"])
def test_dedupe_leaves_files_with_nothing_to_remove_byte_identical(tmp_path, content):
    index = tmp_path / "MEMORY.md"
    index.write_text(content)
    mtime = index.stat().st_mtime_ns
    assert cs._dedupe_index_lines(index) == []
    assert index.read_text() == content and index.stat().st_mtime_ns == mtime


def test_dedupe_never_touches_a_file_with_conflict_markers(tmp_path):
    index = tmp_path / "MEMORY.md"
    text = "<<<<<<< Updated upstream\n- [A](a.md)\n=======\n- [A](a.md)\n>>>>>>> Stashed changes\n"
    index.write_text(text)
    assert cs._dedupe_index_lines(index) == []
    assert index.read_text() == text


def test_dedupe_runs_on_the_index_only_never_on_memory_notes_or_logs(macs):
    a, b = macs
    dup = "- [Gamma](gamma.md) — g"
    for rel in (f"{MEM}/alpha.md", "sync-log.md", "quarantine.md"):
        _append(a, rel, f"{dup}\nA\n")
    _publish(a)
    for rel in (f"{MEM}/alpha.md", "sync-log.md", "quarantine.md"):
        _append(b, rel, f"B\n{dup}\n")

    cs.pull(b)

    _assert_unstuck(b)
    for rel in ("sync-log.md", "quarantine.md"):
        assert (b / rel).read_text().count(dup) == 2, rel
    note = (b / MEM / "alpha.md").read_text()   # auto-resolved: A's note, then B's lines A lacks; nothing removed
    assert dup in note and "\nA\n" in note and "\nB\n" in note


# ── the rule is installed on every machine ──────────────────────────────────────────────────────────────────────────

def test_attributes_missing_on_one_machine_are_added_before_the_stash_and_merge(macs):
    a, b = macs
    assert not _attributes(b).exists() or "merge=union" not in _attributes(b).read_text()
    _append(a, "quarantine.md", "A\n")
    _publish(a)
    _append(b, "quarantine.md", "B\n")

    cs.pull(b)

    assert "merge=union" in _attributes(b).read_text()
    _assert_unstuck(b)
    assert _git(b, "check-attr", "merge", "--", "quarantine.md").endswith("union")


def test_installing_the_rule_is_idempotent_and_keeps_a_persons_own_lines(macs):
    _, b = macs
    _attributes(b).parent.mkdir(parents=True, exist_ok=True)
    _attributes(b).write_text("*.png binary\n")

    assert cs.ensure_union_rule(b) is True
    first = _attributes(b).read_text()
    assert first.startswith("*.png binary\n") and first.count("merge=union") == len(cs.UNION_MERGE_PATHS)
    for _ in range(3):
        assert cs.ensure_union_rule(b) is False
    assert _attributes(b).read_text() == first


def test_a_stale_managed_block_is_replaced_not_duplicated(macs):
    _, b = macs
    _attributes(b).parent.mkdir(parents=True, exist_ok=True)
    _attributes(b).write_text(f"mine\n{cs._UNION_BEGIN}\n/old.md merge=union\n{cs._UNION_END}\nalso mine\n")

    cs.ensure_union_rule(b)

    text = _attributes(b).read_text()
    assert "/old.md" not in text and text.count(cs._UNION_BEGIN) == 1
    assert "mine\n" in text and "also mine\n" in text


def test_the_rule_covers_exactly_the_scope(macs):
    _, b = macs
    cs.ensure_union_rule(b)
    union = {"sync-log.md", "auto-fix-log.md", "quarantine.md", "improvement-queue.md",
             "projects/x/memory/MEMORY.md"}
    not_union = {"lexicon.md", "CLAUDE.md", "suggestions.md", "projects/x/memory/sub/deep.md", "projects/x/memory/project-y.md",
                 "projects/x/notes.md", "handoffs/quarantine.md", "a/projects/x/memory/MEMORY.md", "projects/x/memory/a.json"}
    for rel in union | not_union:
        out = _git(b, "check-attr", "merge", "--", rel)
        assert out.endswith(": union") == (rel in union), out


def test_the_rule_is_only_installed_in_the_claude_dir_never_the_engine_repo(tmp_path):
    repo = tmp_path / ".agents"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    assert cs.ensure_union_rule(repo) is False
    assert not _attributes(repo).exists()


def test_a_path_that_is_not_a_git_repo_is_left_alone(tmp_path):
    d = tmp_path / ".claude"
    d.mkdir()
    assert cs.ensure_union_rule(d) is False
    assert list(d.iterdir()) == []


def test_push_installs_the_rule_too(macs):
    _, b = macs
    cs.push(b)
    assert "merge=union" in _attributes(b).read_text()


# ── the stash-pop path with a dirty tree ────────────────────────────────────────────────────────────────────────────

def test_pull_with_staged_unstaged_and_untracked_wip_keeps_everything_and_merges_it(macs):
    a, b = macs
    _append(a, f"{MEM}/MEMORY.md", "- [A](a-new.md) — A\n")
    _append(a, "quarantine.md", "A's quarantine\n")
    _publish(a)
    _append(b, f"{MEM}/MEMORY.md", "- [B](b-new.md) — B\n")
    _git(b, "add", f"{MEM}/MEMORY.md")                         # staged
    _append(b, "quarantine.md", "B's quarantine\n")            # unstaged
    (b / MEM / "b-new.md").write_text("B's new note\n")       # untracked
    (b / "handoffs").mkdir()
    (b / "handoffs" / "h.md").write_text("handoff\n")

    cs.pull(b)

    _assert_unstuck(b)
    assert "- [A](a-new.md)" in (b / MEM / "MEMORY.md").read_text() and "- [B](b-new.md)" in (b / MEM / "MEMORY.md").read_text()
    assert "A's quarantine" in (b / "quarantine.md").read_text() and "B's quarantine" in (b / "quarantine.md").read_text()
    assert (b / MEM / "b-new.md").read_text() == "B's new note\n"
    assert (b / "handoffs" / "h.md").read_text() == "handoff\n"
    assert "committed 4 local file(s), then merged" in _log()   # no stash on the Claude dir's path any more


def test_stash_pop_with_only_a_scoped_file_dirty_and_a_merge_commit_reviews_both(macs):
    """The merge itself (B had a commit) and the stash pop (B had WIP) both union-merge; both are reviewed."""
    a, b = macs
    path = f"{MEM}/MEMORY.md"
    shared = "- [Gamma](gamma.md) — g"
    _append(a, path, f"{shared}\n- [Delta](delta.md) — d\n")
    _append(a, "quarantine.md", "A\n")
    _publish(a)
    _append(b, "quarantine.md", "B committed\n")
    _git(b, "commit", "-q", "-am", "B's commit")
    _append(b, path, f"- [Eps](eps.md) — e\n{shared}\n")      # dirty: rides the stash

    cs.pull(b)

    _assert_unstuck(b)
    assert (b / path).read_text().splitlines().count(shared) == 1
    assert "A\n" in (b / "quarantine.md").read_text() and "B committed\n" in (b / "quarantine.md").read_text()
    assert _run(b, "rev-parse", "-q", "--verify", "HEAD^2").returncode == 0, "expected a real merge commit"


def test_dedup_does_not_run_while_stash_pop_is_still_pending(macs, monkeypatch):
    """Dedup edits the working tree; doing it between the merge and the pop would make the pop conflict on it."""
    a, b = macs
    path = f"{MEM}/MEMORY.md"
    shared = "- [Gamma](gamma.md) — g"
    _append(a, path, f"{shared}\n- [Delta](delta.md) — d\n")
    _publish(a)
    _append(b, path, f"- [Eps](eps.md) — e\n{shared}\n")
    _git(b, "commit", "-q", "-am", "B's commit")
    _append(b, path, "- [Zeta](zeta.md) — z\n")

    cs.pull(b)

    _assert_unstuck(b)
    lines = (b / path).read_text().splitlines()
    assert lines.count(shared) == 1 and "- [Zeta](zeta.md) — z" in lines


# ── the review file and its Health card ─────────────────────────────────────────────────────────────────────────────

def test_health_is_green_with_no_review_file_and_unknown_when_it_is_unreadable(macs):
    assert health_checks.check_union_merge_review()["severity"] == "green"
    path = cs._review_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    assert health_checks.check_union_merge_review()["severity"] == "yellow"
    path.write_text(json.dumps({"items": [{"kind": "bogus"}, "junk", {"kind": "kept-changed-line"}]}))
    assert cs.union_review_open() == []


def test_an_item_whose_file_was_deleted_clears(macs):
    a, b = macs
    path = f"{MEM}/MEMORY.md"
    (a / path).write_text(SEED[path].replace("— b\n", "— b, edited\n"))
    _publish(a)
    _append(b, path, "- [Gamma](gamma.md) — g\n")
    cs.pull(b)
    assert cs.union_review_open()
    (b / path).unlink()
    assert cs.union_review_open() == []


def test_review_items_are_not_repeated_across_runs(macs):
    a, b = macs
    _append(a, f"{MEM}/MEMORY.md", "- [Gamma](gamma.md) — from A\n")
    _publish(a)
    _append(b, f"{MEM}/MEMORY.md", "- [Gamma note](gamma.md) — from B\n")
    cs.pull(b)
    cs.push(b)
    _git(a, "pull", "-q", "--no-rebase", "origin", "main")
    _append(a, f"{MEM}/MEMORY.md", "- [Later A](later-a.md)\n")
    _publish(a)
    _append(b, f"{MEM}/MEMORY.md", "- [Later B](later-b.md)\n")
    cs.pull(b)
    _assert_unstuck(b)
    assert len(cs.union_review_open()) == 1
    assert _log().count("needs a look") == 1, _log()


def test_fast_forwarding_onto_the_other_macs_merge_reviews_nothing_here(macs):
    """A's own code sync reviewed the merge it made; B only fast-forwards onto it and must not report it again."""
    a, b = macs
    path = f"{MEM}/MEMORY.md"
    cs.ensure_union_rule(a)
    (b / path).write_text(SEED[path].replace("— b\n", "— b, edited\n"))
    _publish(b)
    _append(a, path, "- [Gamma](gamma.md) — g\n")
    _git(a, "commit", "-q", "-am", "A")
    _git(a, "pull", "-q", "--no-rebase", "--no-edit", "origin", "main")   # A's union merge keeps the old line
    _git(a, "push", "-q", "origin", "main")
    assert "- [Beta](beta.md) — b\n" in (a / path).read_text()

    cs.pull(b)

    assert _git(b, "rev-parse", "HEAD") == _git(a, "rev-parse", "HEAD")
    assert cs.union_review_open() == [] and "union" not in _log()


def test_push_merge_path_also_removes_duplicate_index_lines_and_flags_the_rest(macs):
    a, b = macs
    path = f"{MEM}/MEMORY.md"
    shared = "- [Gamma](gamma.md) — g"
    _append(a, path, f"{shared}\n- [Delta](delta.md) — d\n")
    (a / "improvement-queue.md").write_text("# Improvement Queue\n\n")
    _publish(a)
    _append(b, path, f"- [Eps](eps.md) — e\n{shared}\n")
    _append(b, "improvement-queue.md", "## 2026-10-26 — two\n")

    cs.push(b)

    _assert_unstuck(b)
    assert _git(b, "rev-parse", "HEAD") == _git(b, "rev-parse", "origin/main")
    assert (b / path).read_text().splitlines().count(shared) == 1
    assert [i["kind"] for i in cs.union_review_open()] == ["kept-changed-line"]
    cs.push(b)   # the dedup edit trails like any other change, and the next push ships it
    _git(a, "pull", "-q", "--no-rebase", "origin", "main")
    assert (a / path).read_text().splitlines().count(shared) == 1
