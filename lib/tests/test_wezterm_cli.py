"""marvin#1059: one wrapper for every `wezterm cli` call, aimed at the right WezTerm GUI when two run."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wezterm_cli as wz  # noqa: E402

LIB = Path(__file__).resolve().parents[1]

PS = (" 7097 Tue Nov  3 11:40:02 2026     /Users/g/.local/bin/wezterm-gui\n"
      "13044 Mon Nov  2 09:15:44 2026     /Applications/WezTerm.app/Contents/MacOS/wezterm-gui\n"
      "12966 Mon Nov  2 09:15:40 2026     /Users/g/.local/bin/wezterm\n"
      "12992 Mon Nov  2 09:15:41 2026     /Users/g/.local/bin/wezterm-mux-server\n"
      "  501 Mon Nov  2 09:00:00 2026     /usr/sbin/cfprefsd\n")


def _ps(out=PS, rc=0):
    return lambda cmd, **k: subprocess.CompletedProcess(cmd, rc, out, "")


def _socks(tmp_path, *pids):
    for p in pids:
        (tmp_path / f"gui-sock-{p}").touch()
    return tmp_path


# ── the binary ──────────────────────────────────────────────────────────────────────────────

def test_an_explicit_override_wins(tmp_path):
    fake = tmp_path / "wezterm"; fake.touch()
    assert wz.find_binary(env={"MARVIN_WEZTERM": str(fake)}, candidates=()) == str(fake)


def test_the_first_existing_candidate_is_used(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"; b.touch()
    assert wz.find_binary(env={}, candidates=(a, b), which=lambda n: None) == str(b)


def test_falls_back_to_the_path(tmp_path):
    assert wz.find_binary(env={}, candidates=(tmp_path / "none",), which=lambda n: "/usr/local/bin/wezterm") \
        == "/usr/local/bin/wezterm"


def test_an_override_that_does_not_exist_is_not_trusted(tmp_path):
    real = tmp_path / "real"; real.touch()
    assert wz.find_binary(env={"MARVIN_WEZTERM": str(tmp_path / "gone")}, candidates=(real,)) == str(real)


def test_no_wezterm_anywhere_is_a_clear_error(tmp_path):
    with pytest.raises(wz.WeztermError, match="isn't installed"):
        wz.find_binary(env={}, candidates=(tmp_path / "none",), which=lambda n: None)


# ── which GUI ───────────────────────────────────────────────────────────────────────────────

def test_guis_lists_only_gui_processes_oldest_first_with_their_sockets(tmp_path):
    d = _socks(tmp_path, 7097, 13044)
    guis = wz.guis(run=_ps(), sock_dir=d)
    assert [g.pid for g in guis] == [13044, 7097]
    assert guis[0].socket == str(d / "gui-sock-13044")
    assert guis[0].started == "Mon Nov 2 09:15:44 2026"   # single-spaced, as marvin_session has always saved it
    assert guis[0].identity == "13044 Mon Nov 2 09:15:44 2026"


def test_a_gui_without_a_socket_file_has_no_socket(tmp_path):
    guis = wz.guis(run=_ps(), sock_dir=tmp_path)
    assert all(g.socket is None for g in guis)


@pytest.mark.parametrize("run", [_ps(rc=1), _ps(out=""), _ps(out="garbage line\n\n   \n")])
def test_ps_failing_or_garbled_means_no_guis(tmp_path, run):
    assert wz.guis(run=run, sock_dir=tmp_path) == []


def test_ps_that_cannot_run_means_no_guis(tmp_path):
    def boom(cmd, **k):
        raise OSError("no ps")
    assert wz.guis(run=boom, sock_dir=tmp_path) == []


def test_main_gui_is_the_one_this_pane_belongs_to_when_inside_wezterm(tmp_path):
    d = _socks(tmp_path, 7097, 13044)
    g = wz.main_gui(run=_ps(), sock_dir=d, env={"WEZTERM_UNIX_SOCKET": str(d / "gui-sock-7097")})
    assert g.pid == 7097


def test_main_gui_outside_wezterm_is_the_oldest_running_gui(tmp_path):
    d = _socks(tmp_path, 7097, 13044)
    assert wz.main_gui(run=_ps(), sock_dir=d, env={}).pid == 13044


def test_a_stale_socket_in_the_environment_is_ignored(tmp_path):
    d = _socks(tmp_path, 13044)
    g = wz.main_gui(run=_ps(), sock_dir=d, env={"WEZTERM_UNIX_SOCKET": str(d / "gui-sock-99999")})
    assert g.pid == 13044


def test_no_gui_running_means_no_main_gui(tmp_path):
    assert wz.main_gui(run=_ps(out=""), sock_dir=tmp_path, env={}) is None


# ── the cli calls ───────────────────────────────────────────────────────────────────────────

class Rec:
    """Records each call; answers per subcommand."""
    def __init__(self, answers=None):
        self.calls, self.envs, self.answers = [], [], answers or {}

    def __call__(self, cmd, **k):
        self.calls.append(cmd)
        self.envs.append(k.get("env") or {})
        sub = wz.subcommand(cmd)
        a = self.answers.get(sub, (0, "", ""))
        if isinstance(a, Exception):
            raise a
        return subprocess.CompletedProcess(cmd, *a)


def test_every_call_never_auto_starts_a_hidden_mux_and_targets_its_socket():
    r = Rec({"list": (0, "[]", "")})
    w = wz.Wezterm(binary="/x/wezterm", socket="/s/gui-sock-1", run=r)
    w.list()
    assert r.calls[0][:3] == ["/x/wezterm", "cli", "--no-auto-start"]
    assert r.envs[0]["WEZTERM_UNIX_SOCKET"] == "/s/gui-sock-1"


def test_two_guis_are_addressed_separately():
    r = Rec({"list": (0, "[]", "")})
    wz.Wezterm(binary="/x/w", socket="/s/gui-sock-1", run=r).list()
    wz.Wezterm(binary="/x/w", socket="/s/gui-sock-2", run=r).list()
    assert [e["WEZTERM_UNIX_SOCKET"] for e in r.envs] == ["/s/gui-sock-1", "/s/gui-sock-2"]


def test_without_a_socket_the_inherited_one_is_dropped_so_nothing_is_aimed_by_accident(monkeypatch):
    monkeypatch.setenv("WEZTERM_UNIX_SOCKET", "/s/someone-elses")
    r = Rec({"list": (0, "[]", "")})
    wz.Wezterm(binary="/x/w", socket=None, run=r).list()
    assert "WEZTERM_UNIX_SOCKET" not in r.envs[0]


def test_list_returns_panes():
    rows = [{"pane_id": 3, "window_id": 1, "tab_id": 2, "title": "zsh", "tty_name": "/dev/ttys004", "cwd": "file:///x"}]
    w = wz.Wezterm(binary="/x/w", socket="/s", run=Rec({"list": (0, json.dumps(rows), "")}))
    assert w.list() == rows


@pytest.mark.parametrize("answer", [(1, "", "failed to connect"), (0, "", ""), (0, "  \n", "")])
def test_no_gui_reachable_lists_as_none(answer):
    assert wz.Wezterm(binary="/x/w", socket="/s", run=Rec({"list": answer})).list() is None


@pytest.mark.parametrize("out", ["{not json", '{"pane_id": 1}', '[1, 2]'])
def test_malformed_list_output_is_an_error_not_a_guess(out):
    with pytest.raises(wz.WeztermError, match="list"):
        wz.Wezterm(binary="/x/w", socket="/s", run=Rec({"list": (0, out, "")})).list()


def test_a_hung_call_fails_within_its_time_limit():
    r = Rec({"list": subprocess.TimeoutExpired(["wezterm"], 5)})
    with pytest.raises(wz.WeztermError, match="didn't answer"):
        wz.Wezterm(binary="/x/w", socket="/s", run=r, timeout=5).list()


def test_every_call_carries_a_time_limit():
    seen = {}
    def run(cmd, **k):
        seen.update(k)
        return subprocess.CompletedProcess(cmd, 0, "[]", "")
    wz.Wezterm(binary="/x/w", socket="/s", run=run, timeout=7).list()
    assert seen["timeout"] == 7


def test_a_binary_that_vanished_is_an_error():
    r = Rec({"list": FileNotFoundError("gone")})
    with pytest.raises(wz.WeztermError):
        wz.Wezterm(binary="/x/w", socket="/s", run=r).list()


def test_spawn_returns_the_new_pane_and_passes_window_cwd_and_program():
    r = Rec({"spawn": (0, "42\n", "")})
    pane = wz.Wezterm(binary="/x/w", socket="/s", run=r).spawn(Path("/work"), ["zsh", "-c", "echo hi"], window_id=5)
    assert pane == 42
    assert r.calls[0][3:] == ["spawn", "--window-id", "5", "--cwd", "/work", "--", "zsh", "-c", "echo hi"]


def test_spawn_can_open_a_new_window():
    r = Rec({"spawn": (0, "7", "")})
    wz.Wezterm(binary="/x/w", socket="/s", run=r).spawn(Path("/w"), ["zsh"], new_window=True)
    assert "--new-window" in r.calls[0]


def test_spawn_refuses_both_a_window_and_a_new_window():
    with pytest.raises(ValueError):
        wz.Wezterm(binary="/x/w", socket="/s", run=Rec()).spawn(Path("/w"), ["zsh"], window_id=1, new_window=True)


@pytest.mark.parametrize("answer", [(1, "", "no window 5"), (0, "not a number", "")])
def test_a_failed_or_odd_spawn_is_an_error(answer):
    with pytest.raises(wz.WeztermError, match="spawn"):
        wz.Wezterm(binary="/x/w", socket="/s", run=Rec({"spawn": answer})).spawn(Path("/w"), ["zsh"], window_id=5)


def test_title_activate_get_text_and_send_text_shape_their_commands():
    r = Rec({"get-text": (0, "screen\n", "")})
    w = wz.Wezterm(binary="/x/w", socket="/s", run=r)
    w.set_tab_title(4, "● MARVIN · #1059")
    w.activate_pane(4)
    assert w.get_text(4) == "screen\n"
    w.send_text(4, "hello")
    w.send_text(4, "\r", paste=False)
    tails = [c[3:] for c in r.calls]
    assert tails == [["set-tab-title", "--pane-id", "4", "● MARVIN · #1059"], ["activate-pane", "--pane-id", "4"],
                     ["get-text", "--pane-id", "4"], ["send-text", "--pane-id", "4", "hello"],
                     ["send-text", "--pane-id", "4", "--no-paste", "\r"]]


@pytest.mark.parametrize("pane", [-1, True, "4", None, 1.5])
def test_pane_ids_must_be_real_non_negative_ints(pane):
    with pytest.raises(ValueError):
        wz.Wezterm(binary="/x/w", socket="/s", run=Rec()).activate_pane(pane)


def test_a_title_that_looks_like_an_option_still_reaches_wezterm_as_text():
    r = Rec()
    wz.Wezterm(binary="/x/w", socket="/s", run=r).set_tab_title(4, "--help")
    assert r.calls[0][-2:] == ["4", "--help"] or r.calls[0][-3:] == ["4", "--", "--help"]


def test_send_text_that_looks_like_an_option_still_reaches_wezterm_as_text():
    r = Rec()
    wz.Wezterm(binary="/x/w", socket="/s", run=r).send_text(4, "--no-paste")
    assert r.calls[0][-2:] == ["--", "--no-paste"]


def test_a_failed_title_or_activate_is_an_error():
    w = wz.Wezterm(binary="/x/w", socket="/s", run=Rec({"activate-pane": (1, "", "no such pane")}))
    with pytest.raises(wz.WeztermError, match="activate-pane"):
        w.activate_pane(9)


def test_start_runs_detached_and_opens_wezterm_itself():
    started = []
    wz.Wezterm(binary="/x/w", socket=None, run=Rec(), start=started.append).start(Path("/w"), ["zsh"])
    assert started == [["/x/w", "start", "--cwd", "/w", "--", "zsh"]]


def test_subcommand_skips_global_options():
    assert wz.subcommand(["/x/w", "cli", "--no-auto-start", "spawn", "--cwd", "/w"]) == "spawn"
    assert wz.subcommand(["/x/w", "cli", "list"]) == "list"
    assert wz.subcommand(["/x/w", "start"]) is None


# ── one place ───────────────────────────────────────────────────────────────────────────────

def test_no_other_code_calls_wezterm_cli_directly():
    """Every wezterm cli call goes through wezterm_cli.py, so the binary, the socket and the time limit are decided
    once (marvin#1059)."""
    offenders = []
    for f in list(LIB.glob("*.py")) + list((LIB.parent / "bin").glob("*")):
        if f.name == "wezterm_cli.py" or not f.is_file():
            continue
        try:
            text = f.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if re.search(r"""(WEZTERM|wezterm)\b[^\n]*["']cli["']""", line) and "wezterm_cli" not in line:
                offenders.append(f"{f.name}:{n}: {line.strip()}")
    assert offenders == []
