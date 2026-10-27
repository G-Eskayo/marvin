"""Two Macs drifting apart, and building on each other again (2026-10-26). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_code_sync_drift.py -v

Measured that day: one Mac's synced Claude dir went 4 days without a successful push. One file under a live edit
deferred every push; the growing pile was stashed on each pull and popped over the remote's changes, conflicted, and
the leftover stash then refused every run until a person dropped it; files edited in place (suggestions.md, memory
notes) conflicted even with union (ADR 0076); and nobody was told. The fixes, tested here:
  A. partial push: only files under a live-edit lease (or holding conflict markers) wait;
  B. the Claude dir commits before it merges (a real merge, no stash);
  C. conflicts in suggestions.md and memory notes are resolved by keeping both sides, and shown for a person;
  D. a sync stuck for 30+ min tells the owner once, and once again when it clears; a leftover stash HEAD already
     contains is dropped.

Two real clones of one bare origin play the two Macs, each under its own temp HOME (never the real dirs). Time is
passed in explicitly, so days of edits run in a second.
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
import session_work as sw  # noqa: E402

T = 1_800_000_000.0
DAY = 24 * 3600
MEM = "projects/p/memory"
NOTE = f"{MEM}/shared-note.md"
SUGGESTIONS = (
    "# Suggestions\n\nPriority-ordered backlog.\n\n"
    "## Fix the widget\n**Priority**: 5\n**Status**: pending\n**Impact**: speed\n**Effort**: low\n**Why**: slow\n\n"
    "## Tidy the docs\n**Priority**: 3\n**Status**: pending\n**Impact**: organization\n**Effort**: low\n**Why**: messy\n\n"
    "## Cache the index\n**Priority**: 7\n**Status**: pending\n**Impact**: speed\n**Effort**: medium\n**Why**: repeated reads\n"
)
SEED = {
    "sync-log.md": "# log\n",
    "quarantine.md": "# Quarantine\n",
    f"{MEM}/MEMORY.md": "# Memory Index\n\n- [Shared](shared-note.md) — a note both Macs edit\n",
    NOTE: "---\nname: shared\n---\n\nStatus: draft\nOwner line: unchanged\n",
    "lexicon.md": "# Lexicon\n\n- **term** — v1\n",
    "suggestions.md": SUGGESTIONS,
    **{f"handoffs/h{i:02d}.md": f"handoff {i} v0\n" for i in range(20)},
}


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _git(repo: Path, *args: str) -> str:
    r = _run(repo, *args)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class World:
    """The two Macs, the origin, and what the owner was told."""

    def __init__(self, tmp_path: Path, monkeypatch, name: str = ".claude"):
        self.origin = tmp_path / "origin.git"
        _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(self.origin))
        seed = tmp_path / "seed"
        seed.mkdir()
        _git(seed, "init", "-q", "-b", "main")
        self._ident(seed)
        for rel, text in SEED.items():
            (seed / rel).parent.mkdir(parents=True, exist_ok=True)
            (seed / rel).write_text(text)
        _git(seed, "add", "-A")
        _git(seed, "commit", "-q", "-m", "seed")
        _git(seed, "push", "-q", str(self.origin), "main")
        state = tmp_path / "state"
        state.mkdir()
        self.notes: list[tuple[str, str]] = []
        self.mac = "mac-a"
        monkeypatch.setattr(cs, "LOG_PATH", state / "sync-log.md")
        monkeypatch.setattr(cs, "notify", lambda title, msg, **kw: self.notes.append((title, msg)))
        monkeypatch.setattr(cs, "machine_label", lambda: self.mac)
        monkeypatch.setattr(cs.error_log, "record", lambda *a, **kw: None)
        self.a = self._clone(tmp_path / "home-a", name)
        self.b = self._clone(tmp_path / "home-b", name)

    @staticmethod
    def _ident(repo: Path) -> None:
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test")

    def _clone(self, home: Path, name: str) -> Path:
        home.mkdir(parents=True)
        repo = home / name
        subprocess.run(["git", "clone", "-q", str(self.origin), str(repo)], check=True, capture_output=True)
        self._ident(repo)
        return repo

    def on(self, repo: Path) -> Path:
        self.mac = "mac-a" if repo == self.a else "mac-b"
        return repo

    def push(self, repo: Path, now: float = T) -> None:
        cs.push(self.on(repo), now=now)

    def pull(self, repo: Path, now: float = T) -> None:
        cs.pull(self.on(repo), now=now)

    def log(self) -> str:
        return cs.LOG_PATH.read_text() if cs.LOG_PATH.exists() else ""

    def origin_file(self, rel: str) -> str | None:
        r = _run(self.origin, "cat-file", "blob", f"main:{rel}")
        return r.stdout if r.returncode == 0 else None

    def stuck_alerts(self) -> list[str]:
        return [m for t, m in self.notes if t == "MARVIN code-sync STUCK"]

    def cleared(self) -> list[str]:
        return [m for t, m in self.notes if "back in sync" in m]


@pytest.fixture
def w(tmp_path, monkeypatch) -> World:
    return World(tmp_path, monkeypatch)


@pytest.fixture
def engine(tmp_path, monkeypatch) -> World:
    """The same, but clones named like the engine repo: the Claude dir's rules must not apply."""
    return World(tmp_path, monkeypatch, name=".agents")


def _write(repo: Path, rel: str, text: str) -> None:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text)


def _append(repo: Path, rel: str, text: str) -> None:
    with (repo / rel).open("a") as f:
        f.write(text)


def _live_edit(repo: Path, rel: str, at: float, sid: str = "live-chat") -> None:
    repo_id, _ = sw.file_key(str(repo / rel))
    with sw._Locked() as st:
        sw.record_prompt(st, sid, "a long chat", at)
        sw.record_edit(st, sid, (repo_id, rel), at)


def _publish(repo: Path, msg: str = "other mac") -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    _git(repo, "push", "-q", "origin", "main")


def _no_markers(repo: Path) -> None:
    for rel in _git(repo, "ls-files").splitlines():
        p = repo / rel
        if p.is_file():
            assert not cs.CONFLICT_MARKER_RE.search(p.read_text(errors="ignore")), f"conflict markers in {rel}"


def _healthy(repo: Path) -> None:
    assert _git(repo, "stash", "list") == "", "a stash was left behind"
    assert cs._stuck_from_previous_run(repo) is None
    _no_markers(repo)


# ── A. partial push ────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_file_under_a_live_edit_for_days_never_holds_back_the_twenty_others(w):
    """The laptop's case: a chat edits one file all day, every day, while twenty others change. Every cycle the twenty
    reach origin; the hot file waits, and goes out the first cycle after the session goes quiet."""
    hot = "lexicon.md"
    now = T
    for day in range(4):
        for cycle in range(6):
            now = T + day * DAY + cycle * 1800
            _write(w.a, hot, f"# Lexicon\n\n- mid-write {day}.{cycle}\n")
            _live_edit(w.a, hot, now - 60)
            for i in range(20):
                _write(w.a, f"handoffs/h{i:02d}.md", f"handoff {i} day {day} cycle {cycle}\n")
            w.push(w.a, now)
            for i in range(20):
                assert w.origin_file(f"handoffs/h{i:02d}.md") == f"handoff {i} day {day} cycle {cycle}\n"
            assert w.origin_file(hot) == SEED[hot], "a file under a live edit was committed mid-write"
    assert "deferring" not in w.log(), "the whole push was deferred for one file"
    assert "left 1 file(s) for the next cycle (lexicon.md was edited" in w.log()

    w.push(w.a, now + sw.LIVE_S + 60)   # the chat ended
    assert w.origin_file(hot) == "# Lexicon\n\n- mid-write 3.5\n"
    assert _git(w.a, "status", "--porcelain") == ""
    assert w.stuck_alerts() == []


def test_when_every_changed_file_is_leased_the_push_defers_and_that_is_not_a_failure(w):
    _write(w.a, "lexicon.md", "# Lexicon\n\n- typing\n")
    before = _git(w.a, "rev-parse", "HEAD")
    for k in range(5):   # 2 h of a session still typing in it
        _live_edit(w.a, "lexicon.md", T + k * 1800)
        w.push(w.a, T + 60 + k * 1800)
    assert _git(w.a, "rev-parse", "HEAD") == before
    assert "deferring — lexicon.md was edited" in w.log()
    assert w.stuck_alerts() == [] and not cs._episodes_path().exists()


def test_a_leased_file_already_staged_by_hand_is_still_not_swept_in(w):
    _write(w.a, "lexicon.md", "# Lexicon\n\n- staged half\n")
    _git(w.a, "add", "lexicon.md")
    _live_edit(w.a, "lexicon.md", T)
    _write(w.a, "handoffs/h00.md", "new\n")
    w.push(w.a, T + 60)
    assert w.origin_file("handoffs/h00.md") == "new\n"
    assert w.origin_file("lexicon.md") == SEED["lexicon.md"]


def test_odd_file_names_are_committed_exactly(w):
    names = ["handoffs/with space.md", "handoffs/ünïcode — dash.md", "handoffs/glob[1]*.md", "handoffs/-dash.md"]
    for n in names:
        _write(w.a, n, f"{n}\n")
    _live_edit(w.a, "handoffs/glob[1]*.md", T)   # leased: a glob-like name must not sweep in its look-alikes
    w.push(w.a, T + 60)
    for n in names:
        assert w.origin_file(n) == (None if n == "handoffs/glob[1]*.md" else f"{n}\n"), n


# ── conflict markers ───────────────────────────────────────────────────────────────────────────────────────────────

def test_conflict_markers_in_a_non_scoped_file_still_stop_for_a_person_but_hold_back_only_that_file(w):
    broken = "# Lexicon\n<<<<<<< Updated upstream\n- a\n=======\n- b\n>>>>>>> Stashed changes\n"
    _write(w.a, "lexicon.md", broken)
    _write(w.a, "handoffs/h01.md", "fine\n")
    w.push(w.a, T)
    assert w.origin_file("lexicon.md") == SEED["lexicon.md"], "markers were committed"
    assert w.origin_file("handoffs/h01.md") == "fine\n"
    last = w.log().rstrip().split("\n## ")[-1]
    assert "REFUSING to commit — conflict markers found in 1 file(s)" in last and "lexicon.md" in last
    w.push(w.a, T + 1800)
    w.push(w.a, T + 3700)   # still refusing an hour later: one alert
    assert len(w.stuck_alerts()) == 1 and w.origin_file("lexicon.md") == SEED["lexicon.md"]
    _write(w.a, "lexicon.md", "# Lexicon\n\n- b\n")   # a person fixes it
    w.push(w.a, T + 4000)
    assert w.origin_file("lexicon.md") == "# Lexicon\n\n- b\n" and len(w.cleared()) == 1


def test_markers_alone_refuse_and_commit_nothing(w):
    _write(w.a, "lexicon.md", "<<<<<<< ours\nx\n=======\ny\n>>>>>>> theirs\n")
    before = _git(w.a, "rev-parse", "HEAD")
    w.push(w.a, T)
    assert _git(w.a, "rev-parse", "HEAD") == before and "REFUSING to commit" in w.log()


# ── B. commit before pull ──────────────────────────────────────────────────────────────────────────────────────────

def test_a_pull_while_dirty_commits_first_and_merges_without_a_stash(w, monkeypatch):
    _append(w.a, "lexicon.md", "- **other** — from A\n")      # same file, different spot: 3-way merges it
    _append(w.a, "quarantine.md", "## A's entry\n")
    _publish(w.a)
    _write(w.b, "lexicon.md", SEED["lexicon.md"].replace("# Lexicon", "# Lexicon (B)"))
    _append(w.b, "quarantine.md", "## B's entry\n")
    _write(w.b, "handoffs/new.md", "B's new handoff\n")        # untracked
    stash_calls, real = [], cs._git_ok
    monkeypatch.setattr(cs, "_git_ok", lambda repo, args, env=None:
                        (stash_calls.append(args) if "stash" in args or "--autostash" in args else None) or real(repo, args, env))
    w.pull(w.b)
    assert not stash_calls, f"the Claude dir's pull stashed: {stash_calls}"
    _healthy(w.b)
    lex = (w.b / "lexicon.md").read_text()
    assert "# Lexicon (B)" in lex and "from A" in lex
    q = (w.b / "quarantine.md").read_text()
    assert "## A's entry" in q and "## B's entry" in q
    assert (w.b / "handoffs/new.md").read_text() == "B's new handoff\n"
    assert _git(w.b, "status", "--porcelain") == ""
    w.push(w.b, T + 60)   # the pull's commit goes out with the next push
    assert w.origin_file("handoffs/new.md") == "B's new handoff\n"


def test_the_sync_log_alone_is_never_committed_by_a_pull(w, monkeypatch):
    """Two Macs committing each other's log entries would trade commits forever. A log inside the repo, dirty alone,
    is carried over the merge (union, so its restore can't conflict) and left uncommitted."""
    monkeypatch.setattr(cs, "LOG_PATH", w.b / "sync-log.md")
    _append(w.a, "sync-log.md", "\n## A's entry\n")
    _publish(w.a)
    _append(w.b, "sync-log.md", "\n## B's own entry\n")
    before = _git(w.b, "rev-parse", "HEAD")
    w.pull(w.b)
    assert _git(w.b, "rev-parse", "HEAD") == _git(w.b, "rev-parse", "origin/main") != before   # fast-forward only
    log = (w.b / "sync-log.md").read_text()
    assert "## A's entry" in log and "## B's own entry" in log
    _healthy(w.b)


def test_a_crash_between_the_commit_and_the_merge_loses_nothing_and_the_next_run_finishes(w, monkeypatch):
    _append(w.a, "quarantine.md", "## A\n")
    _publish(w.a)
    _write(w.b, "handoffs/h05.md", "B's work\n")
    real = cs._merge_claude_dir
    monkeypatch.setattr(cs, "_merge_claude_dir", lambda repo: (_ for _ in ()).throw(RuntimeError("power cut")))
    with pytest.raises(RuntimeError):
        w.pull(w.b)
    assert _git(w.b, "show", "HEAD:handoffs/h05.md") == "B's work", "the work was not committed before the merge"
    assert _git(w.b, "status", "--porcelain") == ""
    monkeypatch.setattr(cs, "_merge_claude_dir", real)
    w.pull(w.b, T + 600)
    w.push(w.b, T + 700)
    _healthy(w.b)
    assert w.origin_file("handoffs/h05.md") == "B's work\n" and "## A" in w.origin_file("quarantine.md")


def test_a_file_under_a_live_edit_that_the_remote_also_changed_waits_then_merges(w):
    _write(w.a, NOTE, SEED[NOTE].replace("Status: draft", "Status: A's"))
    _publish(w.a)
    _write(w.b, NOTE, SEED[NOTE].replace("Status: draft", "Status: B typing"))
    _live_edit(w.b, NOTE, T)
    _write(w.b, "handoffs/h02.md", "B\n")
    w.pull(w.b, T + 60)
    assert "deferring the merge" in w.log()
    assert (w.b / NOTE).read_text().count("Status: B typing") == 1, "the live file was touched"
    assert _git(w.b, "show", "HEAD:handoffs/h02.md") == "B", "the rest is committed anyway"
    _healthy(w.b)
    w.pull(w.b, T + sw.LIVE_S + 120)   # the session went quiet: committed, merged, auto-resolved
    note = (w.b / NOTE).read_text()
    assert "Status: A's" in note and "Status: B typing" in note
    _healthy(w.b)
    assert w.stuck_alerts() == []


def test_a_fast_forward_only_remote_and_a_machine_set_to_ff_only_still_converge(w):
    _git(w.origin, "config", "receive.denyNonFastForwards", "true")
    for repo in (w.a, w.b):
        _git(repo, "config", "merge.ff", "only")
        _git(repo, "config", "pull.ff", "only")
    _write(w.a, "handoffs/h03.md", "A\n")
    w.push(w.a)
    _write(w.b, "handoffs/h04.md", "B\n")
    w.push(w.b, T + 60)   # rejected, merged (a real merge despite ff-only), pushed as a fast-forward of origin
    _write(w.a, "handoffs/h06.md", "A again\n")
    w.pull(w.a, T + 120)
    w.push(w.a, T + 180)
    for rel, text in (("handoffs/h03.md", "A\n"), ("handoffs/h04.md", "B\n"), ("handoffs/h06.md", "A again\n")):
        assert w.origin_file(rel) == text
    _healthy(w.a)
    _healthy(w.b)


def test_the_engine_repo_keeps_its_stash_path_and_never_auto_commits_on_pull(engine):
    w = engine
    _append(w.a, "lexicon.md", "- A\n")
    _publish(w.a)
    _write(w.b, "handoffs/h00.md", "B's uncommitted WIP\n")
    w.pull(w.b)
    assert _git(w.b, "rev-parse", "HEAD") == _git(w.b, "rev-parse", "origin/main"), "the engine's pull committed WIP"
    assert (w.b / "handoffs/h00.md").read_text() == "B's uncommitted WIP\n" and "local WIP restored" in w.log()
    assert not (w.b / ".git" / "info" / "attributes").exists() or "union" not in (w.b / ".git/info/attributes").read_text()


# ── C. in-place edits both Macs made ───────────────────────────────────────────────────────────────────────────────

def test_days_of_both_macs_adding_memories_and_editing_one_note_converge_with_nothing_lost(w):
    for day in range(5):
        now = T + day * DAY
        for repo, who in ((w.a, "A"), (w.b, "B")):
            _write(repo, f"{MEM}/{who.lower()}-day{day}.md", f"---\nname: {who} {day}\n---\n\nlearned on day {day}\n")
            _append(repo, f"{MEM}/MEMORY.md", f"- [{who} day {day}]({who.lower()}-day{day}.md) — new\n")
            note = (repo / NOTE).read_text().replace("Status: draft", f"Status: {who} rewrote it")
            _write(repo, NOTE, note + f"{who} line on day {day}\n")
        w.push(w.a, now)
        w.pull(w.b, now + 60)
        w.push(w.b, now + 120)
        w.pull(w.a, now + 180)
    _healthy(w.a)
    _healthy(w.b)
    assert _git(w.a, "rev-parse", "HEAD^{tree}") == _git(w.b, "rev-parse", "HEAD^{tree}"), "the Macs did not converge"
    index = (w.a / MEM / "MEMORY.md").read_text()
    note = (w.a / NOTE).read_text()
    for day in range(5):
        for who in ("A", "B"):
            assert (w.a / MEM / f"{who.lower()}-day{day}.md").exists()
            assert index.count(f"- [{who} day {day}]({who.lower()}-day{day}.md) — new") == 1
            assert f"{who} line on day {day}" in note, f"lost {who}'s day {day} line:\n{note}"
    assert note.startswith("---\nname: shared\n---\n") and "## Also from mac-b (" in note
    kinds = {(i["kind"], i["file"]) for i in cs.union_review_open()}
    assert ("auto-resolved", NOTE) in kinds
    assert "CONFLICT" not in w.log() and "REFUSING" not in w.log()
    assert w.stuck_alerts() == []


def test_keep_both_note_puts_the_remote_first_then_a_marked_section(w):
    _write(w.a, NOTE, "---\nname: shared\n---\n\nStatus: A's view\nOwner line: unchanged\n")
    w.push(w.a)
    _write(w.b, NOTE, "---\nname: shared\n---\n\nStatus: B's view\nOwner line: unchanged\nB extra ünïcode\n")
    w.pull(w.b, T + 60)
    note = (w.b / NOTE).read_text()
    head, _, section = note.partition("\n## Also from mac-b (")
    assert head == "---\nname: shared\n---\n\nStatus: A's view\nOwner line: unchanged\n"
    assert section.split("\n", 1)[1] == "\nStatus: B's view\nB extra ünïcode\n"
    item = [i for i in cs.union_review_open() if i["file"] == NOTE]
    assert item and item[0]["line"].startswith("## Also from mac-b (")
    assert "both machines edited it, kept both sides" in w.log()
    _write(w.b, NOTE, "---\nname: shared\n---\n\nStatus: both views, tidied\n")   # a person tidies it: card clears
    assert [i for i in cs.union_review_open() if i["file"] == NOTE] == []


def test_a_note_one_mac_deleted_and_the_other_edited_keeps_the_edit(w):
    (w.a / NOTE).unlink()
    w.push(w.a)
    _write(w.b, NOTE, SEED[NOTE] + "B kept working on it\n")
    w.pull(w.b, T + 60)
    assert "B kept working on it" in (w.b / NOTE).read_text()
    _healthy(w.b)


def test_the_same_new_note_created_on_both_macs_keeps_both(w):
    rel = f"{MEM}/born-twice.md"
    _write(w.a, rel, "---\nname: twice\n---\n\nA's take\n")
    w.push(w.a)
    _write(w.b, rel, "---\nname: twice\n---\n\nB's take\n")
    w.pull(w.b, T + 60)
    text = (w.b / rel).read_text()
    assert text.startswith("---\nname: twice\n---\n\nA's take\n") and "B's take" in text
    _healthy(w.b)


def test_suggestions_resorted_on_both_macs_merge_every_entry_and_are_sorted_again(w):
    def add(text: str, title: str, prio: int) -> str:
        return text + f"\n## {title}\n**Priority**: {prio}\n**Status**: pending\n**Impact**: speed\n**Effort**: low\n**Why**: x\n"

    def resort(repo: Path) -> None:
        subprocess.run([sys.executable, str(cs.SORT_SUGGESTIONS)], env={"HOME": str(repo.parent), "PATH": "/usr/bin:/bin"},
                       check=True, capture_output=True)

    _write(w.a, "suggestions.md", add(SUGGESTIONS, "A's urgent idea", 9))
    resort(w.a)
    w.push(w.a)
    b_text = add(SUGGESTIONS.replace("**Why**: messy", "**Why**: messy, B looked closer"), "B's small idea", 1)
    _write(w.b, "suggestions.md", b_text.replace("## Fix the widget\n**Priority**: 5", "## Fix the widget\n**Priority**: 8"))
    resort(w.b)
    w.pull(w.b, T + 60)
    _healthy(w.b)
    text = (w.b / "suggestions.md").read_text()
    titles = [line[3:] for line in text.splitlines() if line.startswith("## ")]
    assert sorted(titles) == sorted(["A's urgent idea", "B's small idea", "Fix the widget", "Tidy the docs", "Cache the index"])
    assert "B looked closer" in text and "## Fix the widget\n**Priority**: 8" in text
    prios = [int(line.split(": ")[1]) for line in text.splitlines() if line.startswith("**Priority**")]
    assert prios == sorted(prios, reverse=True), f"not re-sorted: {prios}"
    assert ("auto-resolved", "suggestions.md") in {(i["kind"], i["file"]) for i in cs.union_review_open()}


def test_an_entry_both_macs_edited_differently_keeps_both_versions(w):
    _write(w.a, "suggestions.md", SUGGESTIONS.replace("**Why**: slow", "**Why**: slow (A)"))
    w.push(w.a)
    _write(w.b, "suggestions.md", SUGGESTIONS.replace("**Why**: slow", "**Why**: slow (B)"))
    w.pull(w.b, T + 60)
    text = (w.b / "suggestions.md").read_text()
    assert "slow (A)" in text and "slow (B)" in text
    _healthy(w.b)


def test_an_entry_one_mac_removed_and_the_other_left_alone_stays_removed(w):
    gone = "## Tidy the docs\n**Priority**: 3\n**Status**: pending\n**Impact**: organization\n**Effort**: low\n**Why**: messy\n\n"
    _write(w.a, "suggestions.md", SUGGESTIONS.replace(gone, "").replace("**Why**: slow", "**Why**: slow (A)"))
    w.push(w.a)
    _write(w.b, "suggestions.md", SUGGESTIONS.replace("**Why**: repeated reads", "**Why**: repeated reads (B)"))
    w.pull(w.b, T + 60)
    text = (w.b / "suggestions.md").read_text()
    assert "Tidy the docs" not in text and "slow (A)" in text and "repeated reads (B)" in text


def test_a_scoped_conflict_beside_a_real_one_resolves_nothing_and_stops(w):
    _write(w.a, NOTE, SEED[NOTE].replace("draft", "A"))
    _write(w.a, "lexicon.md", SEED["lexicon.md"].replace("v1", "A"))
    w.push(w.a)
    _write(w.b, NOTE, SEED[NOTE].replace("draft", "B"))
    _write(w.b, "lexicon.md", SEED["lexicon.md"].replace("v1", "B"))
    w.pull(w.b, T + 60)
    assert "CONFLICT merging origin/main" in w.log()
    assert not (w.b / ".git" / "MERGE_HEAD").exists() and _git(w.b, "status", "--porcelain") == ""
    assert "Also from" not in (w.b / NOTE).read_text() and (w.b / NOTE).read_text() == SEED[NOTE].replace("draft", "B")
    assert cs.union_review_open() == []


def test_the_engine_repo_never_auto_resolves_a_memory_shaped_path(engine):
    w = engine
    _write(w.a, NOTE, SEED[NOTE].replace("draft", "A"))
    _publish(w.a)
    _write(w.b, NOTE, SEED[NOTE].replace("draft", "B"))
    _git(w.b, "commit", "-qam", "B")
    w.push(w.b)
    assert "CONFLICT" in w.log() and "Also from" not in (w.b / NOTE).read_text()


# ── D. leftover stashes and the stuck alert ────────────────────────────────────────────────────────────────────────

def _leave_stash(repo: Path, contained: bool, untracked: bool = False) -> None:
    _write(repo, "handoffs/h07.md", "stashed work\n")
    if untracked:
        _write(repo, "handoffs/stashed-untracked.md", "untracked work\n")
    _git(repo, "stash", "push", "-u", "-m", "code_sync auto-stash")
    if contained:   # a person later committed the very same content by hand
        _write(repo, "handoffs/h07.md", "stashed work\n")
        if untracked:
            _write(repo, "handoffs/stashed-untracked.md", "untracked work\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "by hand")


@pytest.mark.parametrize("untracked", [False, True])
@pytest.mark.parametrize("kind", ["claude", "engine"])
def test_a_leftover_stash_already_in_head_is_dropped_and_logged(kind, untracked, tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, name=".claude" if kind == "claude" else ".agents")
    _leave_stash(w.b, contained=True, untracked=untracked)
    sha = _git(w.b, "rev-parse", "stash@{0}")
    w.pull(w.b)
    assert _git(w.b, "stash", "list") == ""
    assert f"dropped 1 leftover stash(es) whose every file already matches HEAD" in w.log() and sha[:8] in w.log()
    assert "REFUSING" not in w.log()
    assert _git(w.b, "cat-file", "-t", sha) == "commit", "the dropped stash must stay recoverable by its sha"


@pytest.mark.parametrize("variant", ["tracked-differs", "untracked-not-in-head", "index-differs"])
def test_a_leftover_stash_not_in_head_is_kept_and_refuses(w, variant):
    if variant == "tracked-differs":
        _leave_stash(w.b, contained=False)
    elif variant == "untracked-not-in-head":
        _leave_stash(w.b, contained=True)
        _write(w.b, "handoffs/only-in-stash.md", "u\n")
        _git(w.b, "stash", "drop")
        _write(w.b, "handoffs/h07.md", "stashed work\n")
        _git(w.b, "stash", "push", "-u")   # tracked part matches HEAD, the untracked file is only in the stash
    else:
        _write(w.b, "handoffs/h07.md", "staged version\n")
        _git(w.b, "add", "handoffs/h07.md")
        _write(w.b, "handoffs/h07.md", "v0 again\n")
        _git(w.b, "stash", "push")
        _write(w.b, "handoffs/h07.md", "v0 again\n")
        _git(w.b, "commit", "-qam", "working tree part only")   # the staged version exists only in the stash
    w.pull(w.b)
    assert _git(w.b, "stash", "list") != "", "a stash with content HEAD lacks was dropped"
    assert "REFUSING to run" in w.log()


def test_a_stuck_episode_longer_than_30_minutes_alerts_exactly_once_then_clears_once(w):
    _leave_stash(w.b, contained=False)
    for k, action in enumerate(["pull", "push"] * 6):   # 3 hours of 15-minute cycles
        getattr(w, action)(w.b, T + k * 900)
        assert len(w.stuck_alerts()) == (0 if k * 900 < cs.STUCK_ALERT_AFTER_S else 1), k
    assert "told the owner: sync has been failing for 30 min" in w.log()
    _git(w.b, "stash", "drop")   # a person resolves it
    w.pull(w.b, T + 4 * 3600)
    assert w.cleared() == [], "cleared while push had not yet run healthy"
    w.push(w.b, T + 4 * 3600 + 60)
    assert len(w.cleared()) == 1 and "stuck 241 min" in w.cleared()[0]
    w.pull(w.b, T + 5 * 3600)
    w.push(w.b, T + 5 * 3600)
    assert len(w.stuck_alerts()) == 1 and len(w.cleared()) == 1
    _leave_stash(w.b, contained=False)   # a new episode alerts again
    w.pull(w.b, T + 6 * 3600)
    w.pull(w.b, T + 7 * 3600)
    assert len(w.stuck_alerts()) == 2


def test_a_short_failure_tells_nobody(w):
    _leave_stash(w.b, contained=False)
    w.pull(w.b, T)
    _git(w.b, "stash", "drop")
    w.pull(w.b, T + 600)
    assert w.stuck_alerts() == [] and w.cleared() == [] and not cs._episodes_path().exists()


def test_a_corrupt_episode_file_is_rebuilt_and_never_breaks_sync(w):
    cs._episodes_path().parent.mkdir(parents=True, exist_ok=True)
    cs._episodes_path().write_text("{not json")
    _leave_stash(w.b, contained=False)
    w.pull(w.b, T)
    w.pull(w.b, T + 3600)
    assert len(w.stuck_alerts()) == 1
    assert json.loads(cs._episodes_path().read_text())[str(w.b)]["alerted"] is True


def test_neutral_runs_neither_open_nor_close_an_episode(w):
    _leave_stash(w.b, contained=False)
    w.pull(w.b, T)
    _git(w.b, "stash", "drop")
    _git(w.b, "checkout", "-qb", "side")   # skipped: a branch is checked out
    w.pull(w.b, T + 600)
    assert str(w.b) in json.loads(cs._episodes_path().read_text())
    w.pull(w.b, T + 3600)
    assert w.stuck_alerts() == [], "a skipped run counted as still failing"


# ── the pull-only mirror (ADR 0069) ────────────────────────────────────────────────────────────────────────────────

def test_the_pull_only_mirror_is_unaffected(w, monkeypatch):
    monkeypatch.setattr(cs, "MIRROR_LOG_PATH", cs.LOG_PATH.parent / "mirror.log")
    monkeypatch.setattr(cs, "MIRROR_BACKUP_DIR", cs.LOG_PATH.parent / "backups")
    _append(w.a, "quarantine.md", "## A\n")
    _publish(w.a)
    _write(w.b, NOTE, "local edit the mirror discards\n")
    _write(w.b, "handoffs/untracked.md", "left alone\n")
    cs.mirror(w.b)
    assert _git(w.b, "rev-parse", "HEAD") == _git(w.origin, "rev-parse", "main")
    assert (w.b / NOTE).read_text() == SEED[NOTE] and (w.b / "handoffs/untracked.md").exists()
    assert "auto-sync" not in _git(w.b, "log", "--format=%s")
    assert w.notes == [] and not cs._episodes_path().exists() and not cs.LOG_PATH.exists()


# ── the resolvers on their own: bad, empty and odd input ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("base, ours, theirs", [
    (None, "", ""),
    ("", "## Only ours\nx\n", ""),
    (None, "no headings at all, ours\n", "no headings at all, theirs\n"),
    (SUGGESTIONS, "", SUGGESTIONS),                       # ours emptied the file, theirs untouched: emptied
    (SUGGESTIONS, SUGGESTIONS + "## Dup\na\n## Dup\nb\n", SUGGESTIONS + "## Dup\na\n"),
    ("## X\n1\n", "## X\n1\n\n\n\n", "## X\n1"),          # spacing only: one entry, not two
])
def test_union_suggestions_never_loses_a_line_either_side_changed(base, ours, theirs):
    out = cs._union_suggestions(base, ours, theirs)
    base_lines = set((base or "").splitlines())
    for side in (ours, theirs):
        for line in side.splitlines():
            if line.strip() and line not in base_lines:
                assert line in out.splitlines(), f"lost {line!r}:\n{out}"
    assert not cs.CONFLICT_MARKER_RE.search(out)
    assert out.count("## X") <= 1


@pytest.mark.parametrize("ours, theirs", [("", ""), ("a\n", ""), ("", "b\n"), ("same\n", "same\n"), ("x", "y"),
                                          ("## Also from mac-b (2026-01-01)\nold\n", "## Also from mac-b (2026-01-01)\n")])
def test_keep_both_note_keeps_every_line_and_never_reuses_a_heading(ours, theirs):
    text, heading = cs._keep_both_note(ours, theirs, "mac-b", "2026-01-01")
    assert text.startswith(theirs)
    for line in ours.splitlines() + theirs.splitlines():
        assert line in text.splitlines()
    if heading:
        assert text.splitlines().count(heading) == 1


def test_an_auto_resolved_merge_with_the_sync_log_dirty_inside_the_repo_restores_the_log_and_leaves_no_stash(w, monkeypatch):
    """The real layout: the log lives in the synced dir and trails every run. Its autostash must come back after the
    keep-both merge commit, not linger as a stash that would stop the next run."""
    monkeypatch.setattr(cs, "LOG_PATH", w.b / "sync-log.md")
    _write(w.a, NOTE, SEED[NOTE].replace("draft", "A"))
    _append(w.a, "sync-log.md", "\n## A's run\n")
    _publish(w.a)
    _write(w.b, NOTE, SEED[NOTE].replace("draft", "B"))
    _git(w.b, "commit", "-qam", "B's note")
    _append(w.b, "sync-log.md", "\n## B's trailing entry\n")
    w.pull(w.b, T)
    _healthy(w.b)
    log = (w.b / "sync-log.md").read_text()
    assert "## A's run" in log and "## B's trailing entry" in log
    note = (w.b / NOTE).read_text()
    assert "Status: A" in note and "Status: B" in note
    w.pull(w.b, T + 60)
    _healthy(w.b)


def test_deleted_and_renamed_files_are_pushed_too(w):
    (w.a / "handoffs/h08.md").unlink()
    (w.a / "handoffs/h09.md").rename(w.a / "handoffs/h09-renamed.md")
    w.push(w.a)
    assert w.origin_file("handoffs/h08.md") is None and w.origin_file("handoffs/h09.md") is None
    assert w.origin_file("handoffs/h09-renamed.md") == "handoff 9 v0\n"
    assert _git(w.a, "status", "--porcelain") == ""
