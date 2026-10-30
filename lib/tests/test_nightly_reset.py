"""Tests for nightly_reset.py (marvin#847, design #769): the guarded nightly restart. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_nightly_reset.py -v

Nothing here restarts anything. The run loop gets a fake clock, fake facts and a restart that only records the call;
the one test that touches the real restart path runs the root script in --dry-run as this (non-root) user.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import nightly_reset as nr  # noqa: E402

TZ = ZoneInfo("America/Denver")
CFG = nr.load_config()


def at(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 10, day, hh, mm, tzinfo=TZ)


def quiet(**kw) -> nr.Facts:
    """A Mac nobody is using, with nothing running and its watcher up."""
    base = dict(idle_s=3600.0, watching_video=False, screen_sharing=False, ssh_logins=0, work=[],
                peer_healthy=True, peer_name="the 2012 mini", on_power=True, at_home=True, needs_home_power=False)
    base.update(kw)
    return nr.Facts(**base)


MINI = nr.night_window("mac-mini-1", at(31, 0, 30), CFG)
BOOK = nr.night_window("macbook-pro-1", at(31, 2, 30), CFG)


# ── the owner's answers, pinned ─────────────────────────────────────────────────────────────────────────────────

def test_config_carries_the_owner_answers_from_769():
    assert CFG["reset"]["slots"] == {"mac-mini-1": "00:30", "macbook-pro-1": "02:30"}
    assert CFG["reset"]["limit"] == "05:00"
    assert CFG["reset"]["recheck_minutes"] == 15
    assert CFG["reset"]["notice_minutes"] == 5
    assert CFG["attempts_per_incident"] == 3
    # the watchers are the two always-home machines, not the laptop
    assert CFG["watch"] == {"mac-mini-1": ["mac-mini-2012"], "mac-mini-2012": ["mac-mini-1"]}


def test_night_window_is_the_slot_to_the_limit_on_the_same_night():
    assert MINI == (at(31, 0, 30), at(31, 5, 0))
    assert BOOK == (at(31, 2, 30), at(31, 5, 0))


def test_night_window_before_midnight_points_at_the_coming_night():
    # launchd fires at the slot, but a manual run at 23:50 must not reset "last night"
    assert nr.night_window("mac-mini-1", at(30, 23, 50), CFG) == (at(31, 0, 30), at(31, 5, 0))


def test_night_window_after_the_limit_points_at_the_next_night():
    assert nr.night_window("mac-mini-1", at(31, 9, 0), CFG) == (at(32 - 1, 0, 30) + timedelta(days=1),
                                                                at(31, 5, 0) + timedelta(days=1))


def test_slots_never_overlap():
    assert nr.slot_conflicts(CFG) == []
    bad = json.loads(json.dumps(CFG))
    bad["reset"]["slots"]["macbook-pro-1"] = "00:30"
    assert nr.slot_conflicts(bad)


def test_a_mac_with_no_slot_has_no_window():
    assert nr.night_window("mac-mini-2012", at(31, 0, 30), CFG) is None


# ── decide(): one pure verdict per check ────────────────────────────────────────────────────────────────────────

def test_quiet_mac_at_the_slot_gets_the_notice_first_never_a_bare_restart():
    v = nr.decide(at(31, 0, 30), MINI, quiet(), {}, CFG)
    assert v.action == "notice"
    assert v.until == at(31, 0, 35)


def test_restart_only_after_the_full_notice():
    st = {"notice_at": at(31, 0, 30).isoformat()}
    assert nr.decide(at(31, 0, 34), MINI, quiet(), st, CFG).action == "wait-notice"
    assert nr.decide(at(31, 0, 35), MINI, quiet(), st, CFG).action == "restart"


def test_before_the_slot_waits_for_it():
    v = nr.decide(at(31, 0, 10), MINI, quiet(), {}, CFG)
    assert (v.action, v.until) == ("wait-slot", at(31, 0, 30))


@pytest.mark.parametrize("facts,why", [
    (dict(idle_s=60.0), "in use"),
    (dict(watching_video=True), "playing"),
    (dict(screen_sharing=True), "Screen Sharing"),
    (dict(ssh_logins=1), "logged in"),
    (dict(idle_s=None), "couldn't tell"),
])
def test_owner_active_waits_and_rechecks_in_15_minutes(facts, why):
    v = nr.decide(at(31, 0, 30), MINI, quiet(**facts), {}, CFG)
    assert v.action == "wait-owner"
    assert v.until == at(31, 0, 45)
    assert why in v.reason


def test_owner_recheck_never_lands_past_the_limit():
    v = nr.decide(at(31, 4, 50), MINI, quiet(idle_s=5.0), {}, CFG)
    assert v.until == at(31, 5, 0)


def test_helper_running_waits_for_its_exit_not_a_clock():
    work = [{"what": "helper Seal Speak: #60", "pid": 4242}]
    v = nr.decide(at(31, 0, 30), MINI, quiet(work=work), {}, CFG)
    assert v.action == "wait-work"
    assert v.pids == [4242]
    assert v.until == at(31, 5, 0)          # the only clock is the limit
    assert "Seal Speak: #60" in v.reason


def test_at_the_limit_it_skips_the_night_and_says_what_held_it():
    st = {"last_wait": "helper Seal Speak: #60 is running"}
    v = nr.decide(at(31, 5, 0), MINI, quiet(work=[{"what": "x", "pid": 1}]), st, CFG)
    assert v.action == "skip"
    assert "05:00" in v.reason and "Seal Speak" in v.reason


def test_skip_tonight_is_final():
    v = nr.decide(at(31, 0, 31), MINI, quiet(), {"skipped": True}, CFG)
    assert v.action == "skip"
    assert "Skip tonight" in v.reason


def test_postponed_waits_until_the_postpone_ends():
    st = nr.postpone({"notice_at": at(31, 0, 30).isoformat()}, at(31, 0, 32), CFG, MINI)
    assert st["notice_at"] is None              # a fresh notice comes after a postpone
    v = nr.decide(at(31, 0, 40), MINI, quiet(), st, CFG)
    assert v.action == "postponed"
    assert v.until == at(31, 0, 32) + timedelta(minutes=CFG["reset"]["postpone_minutes"])


def test_postpone_past_the_limit_skips_the_night():
    st = nr.postpone({}, at(31, 4, 50), CFG, MINI)
    assert st["skipped"] is True
    assert nr.decide(at(31, 4, 51), MINI, quiet(), st, CFG).action == "skip"


def test_peer_down_waits_so_one_machine_stays_up():
    v = nr.decide(at(31, 0, 30), MINI, quiet(peer_healthy=False), {}, CFG)
    assert v.action == "wait-peer"
    assert "the 2012 mini" in v.reason
    assert v.until == at(31, 0, 45)


def test_peer_unknown_counts_as_down():
    assert nr.decide(at(31, 0, 30), MINI, quiet(peer_healthy=None), {}, CFG).action == "wait-peer"


@pytest.mark.parametrize("facts,why", [(dict(on_power=False), "battery"), (dict(at_home=False), "home"),
                                       (dict(on_power=None), "battery"), (dict(at_home=None), "home")])
def test_macbook_skips_unless_home_and_on_power(facts, why):
    v = nr.decide(at(31, 2, 30), BOOK, quiet(needs_home_power=True, **facts), {}, CFG)
    assert v.action == "skip"
    assert why in v.reason


def test_the_mini_ignores_power_and_home():
    assert nr.decide(at(31, 0, 30), MINI, quiet(on_power=None, at_home=None), {}, CFG).action == "notice"


def test_a_finished_night_stays_finished():
    for outcome in ("restarted", "skipped", "restart-failed"):
        assert nr.decide(at(31, 0, 40), MINI, quiet(), {"outcome": outcome}, CFG).action == "done"


# ── the run loop, on a fake clock ───────────────────────────────────────────────────────────────────────────────

class Sim:
    """A fake night: a clock, a facts timeline, and a restart that only records. wait() jumps the clock to the
    earlier of its deadline and the next scripted event (a pid exiting, a button pressed)."""

    def __init__(self, start, facts_at, events=None):
        self.now = start
        self.facts_at = facts_at
        self.events = sorted(events or [], key=lambda e: e[0])
        self.notices, self.restarts, self.waits = [], [], []
        self.state: dict = {}

    def clock(self):
        return self.now

    def gather(self):
        return self.facts_at(self.now)

    def notice(self, when, reason=""):
        self.notices.append((self.now, when))

    def restart(self):
        self.restarts.append(self.now)
        return True, "restarted (fake)"

    def wait(self, until, pids=(), wake_on_state=False):
        self.waits.append((self.now, until, tuple(pids)))
        nxt = until
        while self.events and self.events[0][0] <= nxt:
            t, fn = self.events.pop(0)
            self.now = max(t, self.now)
            fn(self)
            return
        self.now = nxt

    def load(self):
        return dict(self.state)

    def save(self, st):
        self.state = dict(st)

    def run(self, window=MINI):
        return nr.run_night(window, CFG, now=self.clock, gather=self.gather, send_notice=self.notice,
                            restart=self.restart, wait=self.wait, load=self.load, save=self.save)


def test_run_quiet_night_notice_then_restart_five_minutes_later():
    s = Sim(at(31, 0, 30), lambda t: quiet())
    assert s.run() == "restarted"
    assert s.notices == [(at(31, 0, 30), at(31, 0, 35))]
    assert s.restarts == [at(31, 0, 35)]


def test_run_owner_active_until_0110_rechecks_every_15_minutes_then_resets():
    s = Sim(at(31, 0, 30), lambda t: quiet(idle_s=30.0 if t < at(31, 1, 10) else 1200.0))
    assert s.run() == "restarted"
    owner_waits = [w for w in s.waits if w[1] - w[0] == timedelta(minutes=15)]
    assert [w[0] for w in owner_waits] == [at(31, 0, 30), at(31, 0, 45), at(31, 1, 0)]
    assert s.notices[0][0] == at(31, 1, 15)
    assert s.restarts == [at(31, 1, 20)]


def test_run_helper_exit_triggers_the_reset_without_a_timer():
    exited = {"done": False}
    s = Sim(at(31, 0, 30), lambda t: quiet(work=[] if exited["done"] else [{"what": "helper a: b", "pid": 77}]),
            events=[(at(31, 2, 7), lambda sim: exited.update(done=True))])
    assert s.run() == "restarted"
    assert s.waits[0] == (at(31, 0, 30), at(31, 5, 0), (77,))   # one wait, on the pid, bounded by the limit
    assert s.restarts == [at(31, 2, 12)]


def test_run_helper_still_running_at_0500_skips_and_never_restarts():
    s = Sim(at(31, 0, 30), lambda t: quiet(work=[{"what": "helper a: b", "pid": 77}]))
    assert s.run() == "skipped"
    assert s.restarts == []
    assert s.state["outcome"] == "skipped"
    assert "helper a: b" in s.state["reason"]


def test_run_owner_back_during_the_notice_cancels_it_and_a_fresh_notice_follows():
    s = Sim(at(31, 0, 30), lambda t: quiet(idle_s=10.0 if at(31, 0, 33) <= t < at(31, 0, 50) else 3000.0),
            events=[(at(31, 0, 33), lambda sim: None)])
    assert s.run() == "restarted"
    assert [n[0] for n in s.notices] == [at(31, 0, 30), at(31, 1, 3)]
    assert s.restarts == [at(31, 1, 8)]


def test_run_postpone_pressed_during_the_notice():
    def press(sim):
        sim.state = nr.postpone(sim.state, sim.now, CFG, MINI)
    s = Sim(at(31, 0, 30), lambda t: quiet(), events=[(at(31, 0, 32), press)])
    assert s.run() == "restarted"
    p = CFG["reset"]["postpone_minutes"]
    assert [n[0] for n in s.notices] == [at(31, 0, 30), at(31, 0, 32) + timedelta(minutes=p)]
    assert s.restarts == [at(31, 0, 37) + timedelta(minutes=p)]


def test_run_skip_tonight_pressed_during_the_notice_never_restarts():
    s = Sim(at(31, 0, 30), lambda t: quiet(), events=[(at(31, 0, 31), lambda sim: sim.state.update(skipped=True))])
    assert s.run() == "skipped"
    assert s.restarts == []
    assert "Skip tonight" in s.state["reason"]


def test_run_restart_failure_is_recorded_and_not_retried():
    s = Sim(at(31, 0, 30), lambda t: quiet())
    s.restart = lambda: (False, "setup not done")
    assert s.run() == "restart-failed"
    assert s.state["outcome"] == "restart-failed" and "setup not done" in s.state["reason"]
    assert s.run() == "restart-failed"          # a second launchd fire the same night does nothing new


def test_run_a_second_fire_after_a_restart_does_nothing():
    s = Sim(at(31, 0, 30), lambda t: quiet())
    s.run()
    assert s.run() == "restarted"
    assert len(s.restarts) == 1


def test_run_writes_the_go_token_only_right_before_restart():
    seen = []
    s = Sim(at(31, 0, 30), lambda t: quiet())
    s.restart = lambda: (seen.append(s.state.get("go_at")), (True, "ok"))[1]
    s.run()
    assert seen == [at(31, 0, 35).isoformat()]


def test_run_bounded_even_if_the_clock_never_moves():
    s = Sim(at(31, 0, 30), lambda t: quiet(idle_s=1.0))
    s.wait = lambda until, pids=(), wake_on_state=False: None   # a broken waiter
    assert nr.run_night(MINI, CFG, now=s.clock, gather=s.gather, send_notice=s.notice, restart=s.restart,
                        wait=s.wait, load=s.load, save=s.save) == "gave-up"
    assert s.restarts == []


# ── reading the facts (parsers over real command output) ───────────────────────────────────────────────────────

def test_idle_seconds_from_ioreg():
    out = '    |   "HIDIdleTime" = 2946123456789\n'
    assert nr.parse_hid_idle(out) == pytest.approx(2946.123456789)
    assert nr.parse_hid_idle("nothing") is None


def test_video_assertion_from_pmset():
    out = ("Assertion status system-wide:\n   PreventUserIdleDisplaySleep    1\n   PreventSystemSleep 0\n")
    assert nr.parse_display_assertion(out) is True
    assert nr.parse_display_assertion(out.replace("Sleep    1", "Sleep    0")) is False


def test_on_power_from_pmset_batt():
    assert nr.parse_on_power("Now drawing from 'AC Power'\n") is True
    assert nr.parse_on_power("Now drawing from 'Battery Power'\n -InternalBattery-0 80%") is False
    assert nr.parse_on_power("") is None


def test_ssh_logins_from_who_ignore_the_console():
    out = ("gileskayo console  Oct 29 15:55\n"
           "gileskayo ttys001  Oct 29 22:01 (100.80.189.85)\n"
           "gileskayo ttys002  Oct 29 22:03\n")
    assert nr.parse_ssh_logins(out) == 1


def test_screen_sharing_from_netstat():
    est = "tcp4  0  0  192.168.0.41.5900   192.168.0.12.50122   ESTABLISHED\n"
    assert nr.parse_screen_sharing(est) is True
    assert nr.parse_screen_sharing(est.replace("ESTABLISHED", "LISTEN")) is False


def test_work_from_ps_finds_helpers_builds_and_tests_but_not_itself():
    ps = ("  101 /Users/x/.agents/venv/bin/python /Users/x/.agents/lib/helper_tab.py run --group Seal --title #60 -- x\n"
          "  102 /Applications/Xcode.app/Contents/MacOS/Xcode\n"
          "  103 /usr/bin/xcodebuild -scheme Seal test\n"
          "  104 /Users/x/.agents/venv/bin/python -m pytest lib/tests\n"
          "  105 /Users/x/.agents/venv/bin/python /Users/x/.agents/lib/nightly_reset.py run\n"
          "  106 /usr/sbin/cfprefsd agent\n"
          "  107 node /opt/homebrew/bin/claude -p do something\n")
    work = nr.parse_work(ps, own_pid=105)
    assert [w["pid"] for w in work] == [101, 102, 103, 104, 107]
    assert work[0]["what"] == "helper Seal: #60"


# ── the restart path: always through the root script, which tests only ever run in --dry-run ───────────────────

def test_restart_command_is_the_root_script_via_sudo_n():
    assert nr.restart_command() == ["/usr/bin/sudo", "-n", "/usr/local/libexec/marvin-authrestart"]
    assert nr.restart_command(dry_run=True)[-1] == "--dry-run"


def test_restart_refuses_without_the_installed_script(tmp_path):
    ok, why = nr.restart(script=tmp_path / "missing", dry_run=True)
    assert not ok
    assert "marvin-reset-setup" in why        # tells the owner the one-line setup


def test_the_real_script_dry_run_restarts_nothing_and_reads_no_password(tmp_path):
    """The repo's own script, run as this user in --dry-run: it names what it would do and exits 0. If it ever
    called the real fdesetup or security, the fake bins below would record it."""
    script = LIB.parent / "bin" / "marvin-authrestart"
    calls = tmp_path / "calls"
    for name in ("fdesetup", "security", "shutdown", "reboot"):
        fake = tmp_path / name
        fake.write_text(f'#!/bin/sh\necho "{name} $*" >> "{calls}"\n')
        fake.chmod(0o755)
    token = tmp_path / "go"
    token.write_text(datetime.now().isoformat())
    r = subprocess.run([str(script), "--dry-run"], capture_output=True, text=True, timeout=30,
                       env={"PATH": f"{tmp_path}:/usr/bin:/bin", "MARVIN_RESET_GO_TOKEN": str(token)})
    assert r.returncode == 0, r.stderr
    assert "dry run" in r.stdout.lower()
    assert not calls.exists()


# marvin#623: the token's age came from BSD `stat -f %m`, which GNU stat (the Linux box) reads as "file system
# info for %m" and fails. Each fake below speaks only one dialect and answers with the real mtime.
_GNU_STAT = """#!/bin/sh
[ "$1" = -c ] && [ "$2" = %Y ] || { echo "stat: cannot read file system information for '$2'" >&2; exit 1; }
exec python3 -c 'import os,sys; print(int(os.stat(sys.argv[1]).st_mtime))' "$3"
"""
_BSD_STAT = """#!/bin/sh
[ "$1" = -f ] && [ "$2" = %m ] || { echo "stat: illegal option -- ${1#-}" >&2; exit 1; }
exec python3 -c 'import os,sys; print(int(os.stat(sys.argv[1]).st_mtime))' "$3"
"""


@pytest.mark.parametrize("dialect", [_GNU_STAT, _BSD_STAT], ids=["gnu-stat", "bsd-stat"])
@pytest.mark.parametrize("age_s, verdict", [(0, "go token: fresh"), (600, "a real run would refuse")])
def test_the_token_age_is_read_with_either_stat_dialect(tmp_path, dialect, age_s, verdict):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "stat").write_text(dialect)
    (bindir / "stat").chmod(0o755)
    token = tmp_path / "go"
    token.write_text("x")
    t = datetime.now().timestamp() - age_s
    os.utime(token, (t, t))
    r = subprocess.run([str(LIB.parent / "bin" / "marvin-authrestart"), "--dry-run"], capture_output=True, text=True,
                       timeout=30, env={"PATH": f"{bindir}:/usr/bin:/bin", "MARVIN_RESET_GO_TOKEN": str(token)})
    assert r.returncode == 0, r.stderr
    assert verdict in r.stdout, r.stdout + r.stderr


def _fake_root_env(tmp_path, password, token_age_s=0):
    """Fake fdesetup/security for the script's real path, run as this (non-root) user. fdesetup records its argv,
    environment and stdin; security hands out `password` like the System keychain would."""
    rec = tmp_path / "rec"
    rec.mkdir()
    (tmp_path / "fdesetup").write_text(
        f'#!/bin/sh\nif [ "$1" = supportsauthrestart ]; then echo true; exit 0; fi\n'
        f'echo "$@" > "{rec}/argv"; env > "{rec}/env"; cat > "{rec}/stdin"\n')
    pw_file = tmp_path / "pw"
    pw_file.write_text(password)
    (tmp_path / "security").write_text(
        f'#!/bin/sh\necho "$@" >> "{rec}/security-argv"\n'
        f'case "$*" in *" -w "*) cat "{pw_file}";; *) echo \'    "acct"<blob>="owner"\';; esac\n')
    for n in ("fdesetup", "security"):
        (tmp_path / n).chmod(0o755)
    token = tmp_path / "go"
    token.write_text("x")
    if token_age_s:
        t = datetime.now().timestamp() - token_age_s
        os.utime(token, (t, t))
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin", "MARVIN_RESET_GO_TOKEN": str(token), "MARVIN_AUTHRESTART_TEST": "1",
           "HOME": str(tmp_path)}
    return rec, token, env


def test_script_pipes_the_password_on_stdin_never_argv_env_or_file(tmp_path):
    pw = 'pa<ss>&"w0rd'
    rec, token, env = _fake_root_env(tmp_path, pw)
    script = LIB.parent / "bin" / "marvin-authrestart"
    r = subprocess.run([str(script)], capture_output=True, text=True, timeout=30, env=env)
    assert r.returncode == 0, r.stderr
    assert (rec / "argv").read_text().split() == ["authrestart", "-inputplist"]
    assert pw not in (rec / "env").read_text()
    assert pw not in (rec / "security-argv").read_text()
    assert pw not in r.stdout + r.stderr
    import plistlib
    plist = plistlib.loads((rec / "stdin").read_bytes())
    assert plist == {"Username": "owner", "Password": pw}      # XML-escaped on the way in, exact on the way out
    assert not token.exists()                                  # one restart per token
    leftovers = [f for f in tmp_path.rglob("*") if f.is_file() and pw in f.read_text(errors="ignore")]
    assert leftovers == [tmp_path / "pw"]                      # only the fake keychain (fdesetup got it escaped)


def test_script_refuses_a_stale_go_token(tmp_path):
    rec, token, env = _fake_root_env(tmp_path, "pw", token_age_s=120)
    r = subprocess.run([str(LIB.parent / "bin" / "marvin-authrestart")], capture_output=True, text=True, timeout=30,
                       env=env)
    assert r.returncode == 75
    assert not (rec / "argv").exists()
    assert not (rec / "security-argv").exists()               # refused before reading the password


def test_script_refuses_without_a_token(tmp_path):
    rec, token, env = _fake_root_env(tmp_path, "pw")
    token.unlink()
    r = subprocess.run([str(LIB.parent / "bin" / "marvin-authrestart")], capture_output=True, text=True, timeout=30,
                       env=env)
    assert r.returncode == 75 and not (rec / "argv").exists()


def test_script_takes_no_arguments_a_caller_could_steer():
    r = subprocess.run([str(LIB.parent / "bin" / "marvin-authrestart"), "--user", "x"], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 64


# ── the launchd entry: one plist fires at both slots, each Mac acts only at its own ─────────────────────────────

@pytest.mark.parametrize("device,fired,acts", [
    ("mac-mini-1", at(31, 0, 30), True),
    ("mac-mini-1", at(31, 2, 30), True),        # its own night already decided: run() reads "done" and stops
    ("macbook-pro-1", at(31, 0, 30), False),    # two hours early: don't sit blocked till 02:30
    ("macbook-pro-1", at(31, 2, 30), True),
    ("macbook-pro-1", at(31, 2, 25), True),     # launchd a little early still counts
])
def test_starts_now_only_near_or_after_this_macs_slot(device, fired, acts):
    w = nr.night_window(device, fired, CFG)
    assert nr.starts_now(fired, w) is acts


# ── after the restart: the watcher is told to expect it back (design #769 section 6) ────────────────────────────

class _Done:
    returncode, stdout, stderr = 0, "restarting", ""


def test_a_real_restart_tells_the_watchers_first_then_runs_the_script(tmp_path):
    script = tmp_path / "marvin-authrestart"
    script.write_text("#!/bin/sh\n")
    order = []
    ok, _ = nr.restart(script=script, device="mac-mini-1", cfg=CFG,
                       announce=lambda dev, cfg: order.append(("announce", dev)),
                       runner=lambda cmd, **kw: order.append(("run", cmd[-1])) or _Done())
    assert ok and order == [("announce", "mac-mini-1"), ("run", str(script))]


def test_a_dry_run_restart_tells_nobody(tmp_path):
    script = tmp_path / "marvin-authrestart"
    script.write_text("#!/bin/sh\n")
    told = []
    nr.restart(script=script, dry_run=True, device="mac-mini-1", cfg=CFG, announce=lambda d, c: told.append(d),
               runner=lambda cmd, **kw: _Done())
    assert told == []


def test_expect_back_command_runs_detached_on_the_watcher():
    cmd = nr.expect_back_ssh("mac-mini-1", "gils-2012-mini")
    assert cmd[:2] == ["ssh", "-o"] and "gils-2012-mini" in cmd
    remote = cmd[-1]
    assert "peer_care.py expect-back mac-mini-1" in remote and remote.startswith("nohup ") and remote.endswith("&")


@pytest.mark.parametrize("plist", ["com.marvin.nightly-reset.plist"])
def test_the_launchd_job_fires_at_every_configured_slot(plist):
    import plistlib
    p = plistlib.loads((LIB.parent / "config" / "launchd" / plist).read_bytes())
    fires = sorted(f"{d['Hour']:02d}:{d['Minute']:02d}" for d in p["StartCalendarInterval"])
    assert fires == sorted(CFG["reset"]["slots"].values())
    assert p["ProgramArguments"][-1] == "run"


def test_command_output_that_isnt_utf8_never_crashes_the_guard():
    """Found on the Mini: `pmset -g assertions` printed a 0xd5 byte (a process name) and the decode raised."""
    out = nr._out(["/bin/sh", "-c", r"printf 'PreventUserIdleDisplaySleep    1\n\325 name\n'"])
    assert nr.parse_display_assertion(out) is True
