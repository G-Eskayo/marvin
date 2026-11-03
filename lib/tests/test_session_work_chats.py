"""marvin#1060: each MARVIN chat tab is recorded in the session store, keyed by (Mac, GUI socket, pane), and listed
only while WezTerm and the claude process say it is alive."""
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import session_work as sw  # noqa: E402

SOCK = "/Users/g/.local/share/wezterm/gui-sock-13044"
ENV = {"WEZTERM_PANE": "16", "WEZTERM_UNIX_SOCKET": SOCK}
CLAUDE = sw.Proc(pid=59044, started="Tue Nov 3 10:20:41 2026", tty="ttys004", interactive=True)


def _ps(rows):
    """A fake ps: rows = {pid: (ppid, tty, lstart, command)}."""
    def run(cmd, **k):
        pid = int(cmd[cmd.index("-p") + 1])
        if pid not in rows:
            return subprocess.CompletedProcess(cmd, 1, "", "")
        ppid, tty, start, command = rows[pid]
        return subprocess.CompletedProcess(cmd, 0, f"{pid} {ppid} {tty} {start} {command}\n", "")
    return run


TREE = {3152: (59044, "??", "Tue Nov  3 12:57:48 2026", "/bin/bash -c hook"),
        59044: (13044, "ttys004", "Tue Nov  3 10:20:41 2026", "claude"),
        13044: (1, "??", "Wed Oct 28 22:58:21 2026", "/Users/g/.local/bin/wezterm-gui start")}


# ── finding the chat's claude process ───────────────────────────────────────────────────────

def test_the_claude_process_is_found_by_walking_up_from_the_hook():
    p = sw.claude_proc(start_pid=3152, run=_ps(TREE))
    assert p == CLAUDE


def test_a_print_mode_claude_is_not_interactive():
    tree = {**TREE, 59044: (13044, "ttys004", "Tue Nov  3 10:20:41 2026", "claude -p summarise this")}
    assert sw.claude_proc(start_pid=3152, run=_ps(tree)).interactive is False
    tree = {**TREE, 59044: (13044, "ttys004", "Tue Nov  3 10:20:41 2026", "/opt/node/bin/node /x/claude --print hi")}
    assert sw.claude_proc(start_pid=3152, run=_ps(tree)).interactive is False


def test_no_claude_in_the_ancestry_means_none():
    tree = {3152: (1, "??", "Tue Nov  3 12:57:48 2026", "/bin/bash -c hook")}
    assert sw.claude_proc(start_pid=3152, run=_ps(tree)) is None


def test_a_ps_that_fails_or_loops_never_hangs():
    assert sw.claude_proc(start_pid=3152, run=_ps({})) is None
    loop = {1: (2, "??", "Tue Nov  3 12:57:48 2026", "a"), 2: (1, "??", "Tue Nov  3 12:57:48 2026", "b")}
    assert sw.claude_proc(start_pid=1, run=_ps(loop)) is None


# ── the record ──────────────────────────────────────────────────────────────────────────────

def _rec(**over):
    base = dict(mac="macbook-pro", socket=SOCK, pane=16, tty="ttys004", claude_pid=59044,
                claude_started="Tue Nov 3 10:20:41 2026", session="s1", cwd="/w/ticket-1060-chat-records",
                repo="G-Eskayo/marvin", ticket=1060)
    base.update(over)
    return base


def test_chat_from_env_builds_the_record():
    rec = sw.chat_from_env({"session_id": "s1", "cwd": "/w/t"}, ENV, proc=CLAUDE, mac="macbook-pro",
                           git=lambda cwd: ("G-Eskayo/marvin", "ticket/1060-chat-records"))
    assert rec["socket"] == SOCK and rec["pane"] == 16 and rec["tty"] == "ttys004"
    assert rec["repo"] == "G-Eskayo/marvin" and rec["ticket"] == 1060 and rec["session"] == "s1"


@pytest.mark.parametrize("env", [{}, {"WEZTERM_PANE": "x"}, {"WEZTERM_PANE": "-3"},
                                 {**ENV, "MARVIN_HELPER_TAB": "1"}])
def test_not_a_chat_tab_means_no_record(env):
    assert sw.chat_from_env({"session_id": "s1", "cwd": "/w"}, env, proc=CLAUDE, mac="m", git=lambda c: (None, None)) \
        is None


def test_a_print_mode_or_missing_claude_is_not_recorded():
    one_off = sw.Proc(pid=1, started="x", tty="ttys004", interactive=False)
    assert sw.chat_from_env({"session_id": "s"}, ENV, proc=one_off, mac="m", git=lambda c: (None, None)) is None
    assert sw.chat_from_env({"session_id": "s"}, ENV, proc=None, mac="m", git=lambda c: (None, None)) is None


@pytest.mark.parametrize("branch,ticket", [("ticket/1060-chat-records", 1060), ("ticket/42", 42),
                                            ("pipeline/g-eskayo/marvin#870", 870), ("main", None), (None, None),
                                            ("feat/1038-profile-parity", None)])
def test_ticket_comes_from_the_branch_like_the_cleanup_sweep_reads_it(branch, ticket):
    assert sw.ticket_from_branch(branch) == ticket


def test_register_keys_by_mac_socket_and_pane():
    st = {}
    sw.register_chat(st, _rec(), now=100)
    assert list(st["chats"]) == [f"macbook-pro|{SOCK}|16"]


def test_clear_in_the_same_pane_keeps_one_record_with_the_newest_session():
    st = {}
    sw.register_chat(st, _rec(session="s1"), now=100)
    sw.register_chat(st, _rec(session="s2"), now=200)
    assert len(st["chats"]) == 1 and next(iter(st["chats"].values()))["session"] == "s2"


def test_a_reused_pane_id_with_another_tty_starts_a_fresh_record():
    st = {}
    sw.register_chat(st, _rec(tty="ttys004", ticket=1060), now=100)
    sw.register_chat(st, _rec(tty="ttys009", ticket=None, session="other", claude_pid=777), now=200)
    rec = next(iter(st["chats"].values()))
    assert rec["tty"] == "ttys009" and rec["ticket"] is None and rec["started_at"] == 200


def test_the_age_prune_never_touches_chats():
    st = {}
    sw.register_chat(st, _rec(), now=100)
    sw.prune(st, now=100 + 10 * 24 * 3600)
    assert st["chats"]


# ── live list ───────────────────────────────────────────────────────────────────────────────

def _panes(*rows):
    return [dict(pane_id=p, tty_name=f"/dev/{t}", window_id=1, tab_id=1, title="✳ x") for p, t in rows]


def test_a_live_chat_is_listed_with_its_pane_and_title():
    st = {}
    sw.register_chat(st, _rec(), now=100)
    out = sw.live_chats(st, panes={SOCK: _panes((16, "ttys004"))}, alive=lambda pid, started: True)
    assert [c["pane"] for c in out] == [16] and out[0]["title"] == "✳ x"


def test_a_closed_tab_drops_out():
    st = {}
    sw.register_chat(st, _rec(), now=100)
    assert sw.live_chats(st, panes={SOCK: _panes((3, "ttys001"))}, alive=lambda *a: True) == []
    assert st["chats"] == {}


def test_a_crashed_claude_drops_out_even_if_the_tab_stays_open():
    st = {}
    sw.register_chat(st, _rec(), now=100)
    assert sw.live_chats(st, panes={SOCK: _panes((16, "ttys004"))}, alive=lambda *a: False) == []


def test_a_pane_id_reused_by_another_tab_drops_the_old_record():
    st = {}
    sw.register_chat(st, _rec(), now=100)
    assert sw.live_chats(st, panes={SOCK: _panes((16, "ttys011"))}, alive=lambda *a: True) == []


def test_a_wezterm_that_has_gone_drops_its_chats():
    st = {}
    sw.register_chat(st, _rec(), now=100)
    assert sw.live_chats(st, panes={SOCK: None}, alive=lambda *a: True) == []


def test_a_wezterm_that_did_not_answer_keeps_its_chats_unknown_not_dead():
    st = {}
    sw.register_chat(st, _rec(), now=100)
    out = sw.live_chats(st, panes={}, alive=lambda *a: True)
    assert [c["pane"] for c in out] == [16] and out[0]["unknown"] is True
    assert st["chats"]


def test_malformed_records_are_dropped_not_fatal():
    st = {"chats": {"junk": "x", "also": {"pane": "nope"}}}
    sw.register_chat(st, _rec(), now=1)
    out = sw.live_chats(st, panes={SOCK: _panes((16, "ttys004"))}, alive=lambda *a: True)
    assert [c["pane"] for c in out] == [16]


def test_proc_alive_checks_pid_and_start_time():
    run = _ps(TREE)
    assert sw.proc_alive(59044, "Tue Nov 3 10:20:41 2026", run=run) is True
    assert sw.proc_alive(59044, "Mon Nov 2 10:20:41 2026", run=run) is False   # pid reused by another process
    assert sw.proc_alive(99999, "Tue Nov 3 10:20:41 2026", run=run) is False


# ── the hook ────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "STATE_PATH", tmp_path / "sessions-active.json")
    monkeypatch.setattr(sw, "claude_proc", lambda **k: CLAUDE)
    monkeypatch.setattr(sw, "_git_info", lambda cwd: ("G-Eskayo/marvin", "ticket/1060-chat-records"))
    monkeypatch.setattr(sw, "_mac", lambda: "macbook-pro")
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("MARVIN_HELPER_TAB", raising=False)
    return tmp_path / "sessions-active.json"


def test_session_start_records_the_chat_and_prints_nothing(store):
    assert sw.handle("start", {"session_id": "s1", "cwd": "/w"}) is None
    chats = json.loads(store.read_text())["chats"]
    assert next(iter(chats.values()))["ticket"] == 1060


def test_session_start_keeps_the_existing_sessions_data(store):
    sw.handle("prompt", {"session_id": "s1", "prompt": "build #1060"})
    sw.handle("start", {"session_id": "s1", "cwd": "/w"})
    st = json.loads(store.read_text())
    assert st["sessions"]["s1"]["request"] == "build #1060" and st["chats"]


def test_a_corrupt_store_still_records(store):
    store.write_text("{not json")
    sw.handle("start", {"session_id": "s1", "cwd": "/w"})
    assert json.loads(store.read_text())["chats"]


def test_a_failure_inside_the_hook_never_escapes(store, monkeypatch):
    monkeypatch.setattr(sw, "claude_proc", lambda **k: 1 / 0)
    assert sw.handle("start", {"session_id": "s1"}) is None


def test_parallel_session_starts_in_different_panes_all_land(store, monkeypatch):
    panes = list(range(20, 32))
    errors = []

    def go(pane):
        try:
            payload = {"session_id": f"s{pane}", "cwd": "/w"}
            env = {**ENV, "WEZTERM_PANE": str(pane)}
            sw.handle("start", payload, env=env)
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    ts = [threading.Thread(target=go, args=(p,)) for p in panes]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    assert sorted(c["pane"] for c in json.loads(store.read_text())["chats"].values()) == panes


def test_the_hook_entry_point_exits_zero_on_garbage_input(store, monkeypatch, capsys):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert sw.main(["hook", "start"]) == 0
    assert capsys.readouterr().out == ""


def test_the_branch_rule_matches_the_cleanup_sweeps():
    import cleanup_sweep
    assert sw.BRANCH_TICKET_RE.pattern == cleanup_sweep.ISSUE_NUMBER_RE.pattern


def test_the_start_hook_is_wired_for_interactive_sessions_only():
    import marvin_hooks
    hooks = [h for h in marvin_hooks.HOOKS if h.event == "SessionStart" and "session_work.py" in " ".join(h.command)]
    assert len(hooks) == 1 and hooks[0].kinds == frozenset({"interactive"}) and hooks[0].timeout


def test_helper_tabs_mark_their_command_so_it_is_never_a_chat():
    import helper_tab
    assert '"MARVIN_HELPER_TAB": "1"' in Path(helper_tab.__file__).read_text()
