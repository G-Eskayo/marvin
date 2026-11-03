"""Portable scheduled jobs (marvin#911): one definition per job in config/jobs/, rendered as a launchd plist on the
Macs and as a systemd user service + timer on mac-mini-2012. These tests try to break the renderer: quoting that
systemd would read differently, schedules that drift between the two, and a rendered plist that isn't what the Macs
have installed."""
from __future__ import annotations

import json
import os
import plistlib
import pwd
import shlex
from pathlib import Path

import pytest

import job_units as ju

REPO = Path(__file__).resolve().parents[2]
JOBS = ("health-check", "cleanup-sweep", "usage-scan")
# The home folder the repo's plists were written for (what the Macs install): read from one, never written here.
MAC_HOME = plistlib.loads((REPO / "config" / "launchd" / "com.marvin.cleanup-sweep.plist").read_bytes())["EnvironmentVariables"]["HOME"]
BOX_HOME = "/home/marvin"


# ── definitions ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", JOBS)
def test_every_first_job_has_one_definition_that_loads(name):
    job = ju.load(name)
    assert job["name"] == name
    assert job["command"][0] == "~/.agents/venv/bin/python"


@pytest.mark.parametrize("bad", [
    {"command": ["x"], "schedule": {"every_s": 60}},                          # no name
    {"name": "x", "schedule": {"every_s": 60}},                                # no command
    {"name": "x", "command": [], "schedule": {"every_s": 60}},                # empty command
    {"name": "x", "command": ["x"]},                                           # no schedule
    {"name": "x", "command": ["x"], "schedule": {}},                          # schedule says nothing
    {"name": "x", "command": ["x"], "schedule": {"every_s": 0}},              # zero interval would spin
    {"name": "x", "command": ["x"], "schedule": {"every_s": True}},           # bool is not a number
    {"name": "x", "command": ["x"], "schedule": {"calendar": {"hour": 24, "minute": 0}}},
    {"name": "x", "command": ["x"], "schedule": {"calendar": {"hour": 4, "minute": 60}}},
    {"name": "x", "command": ["x"], "schedule": {"calendar": {"hour": 4}}},  # half a time
    {"name": "x", "command": ["x"], "schedule": {"every_s": 60, "calendar": {"hour": 1, "minute": 0}}},
    {"name": "x", "command": ["x"], "schedule": {"every_s": 60, "sometimes": 1}},
    {"name": "../evil", "command": ["x"], "schedule": {"every_s": 60}},      # a name becomes a file name
    {"name": "Has Space", "command": ["x"], "schedule": {"every_s": 60}},
    {"name": "x", "command": ["x"], "schedule": {"every_s": 60}, "env": {"A": 1}},
    {"name": "x", "command": ["x\nExecStartPost=/bin/rm -rf ~"], "schedule": {"every_s": 60}},
    {"name": "x", "command": ["x"], "schedule": {"every_s": 60}, "surprise": True},
])
def test_a_malformed_definition_is_refused_not_rendered(bad):
    with pytest.raises(ju.JobError):
        ju.validate(bad)


def test_a_missing_definition_names_what_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(ju, "JOBS_DIR", tmp_path)
    (tmp_path / "a.json").write_text(json.dumps({"name": "a", "command": ["x"], "schedule": {"every_s": 60}}))
    with pytest.raises(ju.JobError, match="a"):
        ju.load("nope")


def test_a_definition_whose_name_disagrees_with_its_file_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(ju, "JOBS_DIR", tmp_path)
    (tmp_path / "a.json").write_text(json.dumps({"name": "b", "command": ["x"], "schedule": {"every_s": 60}}))
    with pytest.raises(ju.JobError, match="b"):
        ju.load("a")


# ── launchd: the Macs see exactly what they have today ─────────────────

def _repo_plist(name):
    return plistlib.loads((REPO / "config" / "launchd" / f"com.marvin.{name}.plist").read_bytes())


@pytest.mark.parametrize("name", ["cleanup-sweep", "usage-scan"])
def test_rendered_plist_is_the_one_in_the_repo(name):
    # The repo copy is what the Macs install (`cp` + launchctl bootstrap). Parsed, so comments and spacing don't count;
    # every key and value launchd reads does.
    assert plistlib.loads(ju.render_plist(ju.load(name), MAC_HOME)) == _repo_plist(name)


# The Mac mini's installed health-check plist (2026-10-30, ~/Library/LaunchAgents/com.marvin.health-check.plist):
# the only one of the three with no repo copy, so its content is pinned here.
MINI_HEALTH_CHECK = {
    "Label": "com.marvin.health-check",
    "EnvironmentVariables": {"HOME": MAC_HOME,
                             "PATH": f"{MAC_HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:"
                                     f"{MAC_HOME}/.agents/venv/bin"},
    "ProgramArguments": [f"{MAC_HOME}/.agents/venv/bin/python", f"{MAC_HOME}/.agents/lib/health_checks.py"],
    "StartInterval": 900,
    "RunAtLoad": True,
    "StandardOutPath": f"{MAC_HOME}/.claude/logs/health-check.log",
    "StandardErrorPath": f"{MAC_HOME}/.claude/logs/health-check-error.log",
}


def test_rendered_health_check_plist_is_the_mac_minis():
    assert plistlib.loads(ju.render_plist(ju.load("health-check"), MAC_HOME)) == MINI_HEALTH_CHECK


@pytest.mark.parametrize("name", JOBS)
def test_rendered_plist_matches_what_this_mac_has_installed(name):
    """On a Mac that runs the job, the renderer must produce its installed plist exactly (parsed): only then may the
    Macs' launchd setup ever be switched to it."""
    real_home = pwd.getpwuid(os.getuid()).pw_dir   # the suite points HOME at a temp folder; this reads the real one
    installed = Path(real_home) / "Library" / "LaunchAgents" / f"com.marvin.{name}.plist"
    if not installed.exists():
        pytest.skip(f"{name} is not installed on this machine")
    assert plistlib.loads(ju.render_plist(ju.load(name), real_home)) == plistlib.loads(installed.read_bytes())


def test_plist_keeps_a_path_with_xml_specials_intact():
    job = ju.validate({"name": "x", "command": ["~/a&b<c>/run", "--q=\"1\""], "schedule": {"every_s": 60}})
    parsed = plistlib.loads(ju.render_plist(job, "/Users/o'neil"))
    assert parsed["ProgramArguments"] == ["/Users/o'neil/a&b<c>/run", "--q=\"1\""]


def test_low_priority_maps_to_launchds_three_keys():
    job = ju.validate({"name": "x", "command": ["x"], "schedule": {"every_s": 60}, "low_priority": True})
    p = plistlib.loads(ju.render_plist(job, MAC_HOME))
    assert (p["ProcessType"], p["LowPriorityIO"], p["Nice"]) == ("Background", True, 10)


# ── systemd: same schedule, same command ───────────────────────────────

def _unit(text: str) -> dict[str, list[str]]:
    """Every key=value in a unit file, by key (keys repeat in systemd)."""
    out: dict[str, list[str]] = {}
    for line in text.splitlines():
        if "=" in line and not line.startswith(("#", "[")):
            k, v = line.split("=", 1)
            out.setdefault(k, []).append(v)
    return out


def _unescape(arg: str) -> str:
    """How systemd reads one already-split ExecStart word back: %% -> %, $$ -> $."""
    return arg.replace("%%", "%").replace("$$", "$")


@pytest.mark.parametrize("name", JOBS)
def test_systemd_service_runs_the_same_command_as_launchd(name):
    job = ju.load(name)
    plist = plistlib.loads(ju.render_plist(job, BOX_HOME))
    service, _timer = ju.render_systemd(job, BOX_HOME)
    [exec_start] = _unit(service)["ExecStart"]
    assert [_unescape(a) for a in shlex.split(exec_start)] == plist["ProgramArguments"]
    assert all(a.startswith(BOX_HOME) for a in plist["ProgramArguments"][:2])
    assert "/Users/" not in service


@pytest.mark.parametrize("name", JOBS)
def test_systemd_logs_where_launchd_does(name):
    job = ju.load(name)
    plist = plistlib.loads(ju.render_plist(job, BOX_HOME))
    unit = _unit(ju.render_systemd(job, BOX_HOME)[0])
    assert unit["StandardOutput"] == [f"append:{plist['StandardOutPath']}"]
    assert unit["StandardError"] == [f"append:{plist['StandardErrorPath']}"]
    assert plist["StandardOutPath"] == f"{BOX_HOME}/.claude/logs/{name}.log"  # untracked logs only (ADR 0069)


@pytest.mark.parametrize("name", JOBS)
def test_systemd_environment_is_launchds(name):
    job = ju.load(name)
    plist = plistlib.loads(ju.render_plist(job, BOX_HOME))
    unit = _unit(ju.render_systemd(job, BOX_HOME)[0])
    env = dict(shlex.split(e)[0].split("=", 1) for e in unit.get("Environment", []))
    assert env == plist.get("EnvironmentVariables", {})


def test_interval_with_run_at_load_fires_on_start_then_every_interval():
    job = ju.load("health-check")
    timer = _unit(ju.render_systemd(job, BOX_HOME)[1])
    assert timer["OnActiveSec"] == ["0"]
    assert timer["OnUnitActiveSec"] == ["900s"]
    assert "OnCalendar" not in timer


def test_interval_without_run_at_load_waits_one_interval_first():
    job = ju.validate({"name": "x", "command": ["x"], "schedule": {"every_s": 120}})
    timer = _unit(ju.render_systemd(job, BOX_HOME)[1])
    assert timer["OnActiveSec"] == ["120s"] and timer["OnUnitActiveSec"] == ["120s"]
    assert "RunAtLoad" not in plistlib.loads(ju.render_plist(job, MAC_HOME))


def test_calendar_is_the_same_wall_clock_time_and_catches_up_after_sleep():
    # launchd runs a missed StartCalendarInterval on wake; systemd needs Persistent=true for the same.
    timer = _unit(ju.render_systemd(ju.load("cleanup-sweep"), BOX_HOME)[1])
    assert timer["OnCalendar"] == ["*-*-* 04:15:00"]
    assert timer["Persistent"] == ["true"]
    assert "OnUnitActiveSec" not in timer


def test_the_timer_starts_its_own_service_and_is_wanted_at_login():
    _service, timer = ju.render_systemd(ju.load("usage-scan"), BOX_HOME)
    u = _unit(timer)
    assert u["Unit"] == ["marvin-usage-scan.service"]
    assert u["WantedBy"] == ["timers.target"]


def test_low_priority_maps_to_nice_and_idle_io_on_linux():
    unit = _unit(ju.render_systemd(ju.load("cleanup-sweep"), BOX_HOME)[0])
    assert unit["Nice"] == ["10"] and unit["IOSchedulingClass"] == ["idle"]
    assert "Nice" not in _unit(ju.render_systemd(ju.load("usage-scan"), BOX_HOME)[0])


@pytest.mark.parametrize("arg", ["50%", "$HOME", "${HOME}", "a b", 'say "hi"', "back\\slash", "it's", "%h", "tab\there"])
def test_systemd_exec_start_passes_awkward_arguments_through_unchanged(arg):
    # systemd expands %specifiers and $VARS inside ExecStart and splits on spaces: every one must reach the program as
    # written, or a job would run something other than what launchd runs.
    job = ju.validate({"name": "x", "command": ["/bin/echo", arg], "schedule": {"every_s": 60}})
    [exec_start] = _unit(ju.render_systemd(job, BOX_HOME)[0])["ExecStart"]
    assert [_unescape(a) for a in shlex.split(exec_start)] == ["/bin/echo", arg]
    assert "%h" not in exec_start.replace("%%", "")
    assert "$H" not in exec_start.replace("$$", "")


def test_a_home_with_a_percent_or_space_is_escaped_in_every_path():
    job = ju.load("usage-scan")
    service, _ = ju.render_systemd(job, "/home/50% off")
    u = _unit(service)
    assert "/home/50%% off" in u["ExecStart"][0]
    assert u["StandardOutput"] == ["append:/home/50%% off/.claude/logs/usage-scan.log"]


def test_unit_names_are_the_marvin_prefix_on_both():
    assert ju.unit_name("cleanup-sweep") == "marvin-cleanup-sweep"
    assert ju.launchd_label("cleanup-sweep") == "com.marvin.cleanup-sweep"


# ── install: thin host adapter ─────────────────────────────────────────

class FakeRun:
    def __init__(self, fail_on: str | None = None):
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, cmd):
        self.calls.append(cmd)
        return 1 if self.fail_on and self.fail_on in " ".join(cmd) else 0


def test_linux_install_writes_both_units_reloads_and_enables_the_timer(tmp_path):
    run = FakeRun()
    out = ju.install(["usage-scan"], os_name="linux", home=tmp_path, run=run)
    d = tmp_path / ".config" / "systemd" / "user"
    assert (d / "marvin-usage-scan.service").exists() and (d / "marvin-usage-scan.timer").exists()
    assert ["systemctl", "--user", "daemon-reload"] in run.calls
    assert ["systemctl", "--user", "enable", "--now", "marvin-usage-scan.timer"] in run.calls
    assert (tmp_path / ".claude" / "logs").is_dir()   # append: needs the folder to exist
    assert out == [{"job": "usage-scan", "changed": True, "ok": True}]


def test_linux_install_twice_changes_nothing_the_second_time(tmp_path):
    ju.install(["usage-scan"], os_name="linux", home=tmp_path, run=FakeRun())
    run = FakeRun()
    out = ju.install(["usage-scan"], os_name="linux", home=tmp_path, run=run)
    assert out == [{"job": "usage-scan", "changed": False, "ok": True}]
    assert ["systemctl", "--user", "daemon-reload"] not in run.calls
    assert ["systemctl", "--user", "enable", "--now", "marvin-usage-scan.timer"] in run.calls  # still ensured on


def test_install_reports_a_failed_enable_instead_of_claiming_success(tmp_path):
    out = ju.install(["usage-scan"], os_name="linux", home=tmp_path, run=FakeRun(fail_on="enable"))
    assert out[0]["ok"] is False


def test_a_bad_job_name_installs_nothing_at_all(tmp_path):
    run = FakeRun()
    with pytest.raises(ju.JobError):
        ju.install(["usage-scan", "no-such-job"], os_name="linux", home=tmp_path, run=run)
    assert run.calls == [] and not (tmp_path / ".config").exists()


def test_mac_install_leaves_an_identical_installed_plist_alone(tmp_path):
    la = tmp_path / "Library" / "LaunchAgents"
    la.mkdir(parents=True)
    # Same content, different formatting (a hand-written comment): parsed-identical, so it is not rewritten.
    original = ju.render_plist(ju.load("usage-scan"), str(tmp_path)).replace(b"<dict>", b"<!-- hand note --><dict>", 1)
    (la / "com.marvin.usage-scan.plist").write_bytes(original)
    run = FakeRun()
    out = ju.install(["usage-scan"], os_name="macos", home=tmp_path, run=run)
    assert out == [{"job": "usage-scan", "changed": False, "ok": True}]
    assert (la / "com.marvin.usage-scan.plist").read_bytes() == original
    assert run.calls == []


def test_mac_install_of_a_changed_plist_reloads_it(tmp_path):
    run = FakeRun()
    out = ju.install(["usage-scan"], os_name="macos", home=tmp_path, run=run, uid=501)
    plist = tmp_path / "Library" / "LaunchAgents" / "com.marvin.usage-scan.plist"
    assert plistlib.loads(plist.read_bytes())["Label"] == "com.marvin.usage-scan"
    assert ["launchctl", "bootout", "gui/501/com.marvin.usage-scan"] in run.calls
    assert ["launchctl", "bootstrap", "gui/501", str(plist)] in run.calls
    assert out[0]["changed"] is True


def test_install_refuses_an_os_it_has_no_adapter_for(tmp_path):
    with pytest.raises(ju.JobError, match="windows"):
        ju.install(["usage-scan"], os_name="windows", home=tmp_path, run=FakeRun())
