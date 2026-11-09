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
    {"name": "x", "command": ["x"], "schedule": {"keep_alive": False}},          # a service that never runs
    {"name": "x", "command": ["x"], "schedule": {"keep_alive": 1}},              # truthy is not true
    {"name": "x", "command": ["x"], "schedule": {"keep_alive": True, "every_s": 60}},   # both at once
    {"name": "x", "command": ["x"], "schedule": {"keep_alive": True, "at_load": False}},  # can't not start
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


# ── keep_alive: a long-running service (the site demo server, marvin#1007) ──

SERVICE = {"name": "svc", "command": ["~/bin/serve", "--port", "1"], "schedule": {"keep_alive": True}}


def test_keep_alive_on_launchd_starts_at_load_restarts_and_is_throttled():
    p = plistlib.loads(ju.render_plist(ju.validate(dict(SERVICE)), MAC_HOME))
    assert (p["RunAtLoad"], p["KeepAlive"], p["ThrottleInterval"]) == (True, True, ju.RESTART_S)
    assert "StartInterval" not in p and "StartCalendarInterval" not in p
    assert p["ProgramArguments"][0] == f"{MAC_HOME}/bin/serve"


def test_keep_alive_on_systemd_is_a_restarting_service_with_no_timer():
    service, timer = ju.render_systemd(ju.validate(dict(SERVICE)), BOX_HOME)
    u = _unit(service)
    assert timer is None
    assert u["Type"] == ["simple"] and u["Restart"] == ["always"] and u["RestartSec"] == [str(ju.RESTART_S)]
    assert u["WantedBy"] == ["default.target"]


def test_keep_alive_linux_install_enables_the_service_and_restarts_it_on_change(tmp_path, monkeypatch):
    monkeypatch.setattr(ju, "JOBS_DIR", tmp_path / "jobs")
    (tmp_path / "jobs").mkdir()
    (tmp_path / "jobs" / "svc.json").write_text(json.dumps(SERVICE))
    run = FakeRun()
    out = ju.install(["svc"], os_name="linux", home=tmp_path, run=run)
    d = tmp_path / ".config" / "systemd" / "user"
    assert (d / "marvin-svc.service").exists() and not (d / "marvin-svc.timer").exists()
    assert ["systemctl", "--user", "restart", "marvin-svc.service"] in run.calls
    assert ["systemctl", "--user", "enable", "--now", "marvin-svc.service"] in run.calls
    assert out == [{"job": "svc", "changed": True, "ok": True}]
    run2 = FakeRun()
    ju.install(["svc"], os_name="linux", home=tmp_path, run=run2)
    assert ["systemctl", "--user", "restart", "marvin-svc.service"] not in run2.calls   # unchanged: left running


def test_site_demo_job_is_a_keep_alive_service_with_no_machine_paths():
    job = ju.load("site-demo")
    assert job["schedule"] == {"keep_alive": True}
    assert all(a.startswith("~/") or not a.startswith("/") for a in job["command"])
    assert "serve" in job["command"]


def test_install_refuses_an_os_it_has_no_adapter_for(tmp_path):
    with pytest.raises(ju.JobError, match="windows"):
        ju.install(["usage-scan"], os_name="windows", home=tmp_path, run=FakeRun())


# ── tidy-agent runs on the venv Python (marvin#1123 0.6) ────────────────────────────────────────────────────────────
# macOS privacy (TCC) checks a launchd job by its interpreter. /usr/bin/python3 lost Full Disk Access on the Mini and
# tidy-agent failed every night from 2026-10-15 with PermissionError on ~/Desktop; the venv Python (Homebrew's
# Python.app) holds the grant on both Macs (probed with `launchctl submit`, 2026-11-04).

def test_tidy_agent_runs_the_organizer_daily_on_the_venv_python():
    job = ju.load("tidy-agent")
    assert job["command"] == ["~/.agents/venv/bin/python", "~/.claude/organize/tidy_agent.py"]
    assert job["schedule"] == {"calendar": {"hour": 3, "minute": 0}}
    plist = plistlib.loads(ju.render_plist(job, MAC_HOME))
    assert plist["Label"] == "com.marvin.tidy-agent"
    assert plist["ProgramArguments"][0] == f"{MAC_HOME}/.agents/venv/bin/python"
    assert plist["StandardErrorPath"] == f"{MAC_HOME}/.claude/logs/tidy-agent-error.log"


def test_no_job_definition_runs_the_system_python():
    # /usr/bin/python3 is the xcode-select shim: TCC needs its own grant for it, separate from the venv's, and it is
    # the one that broke. Any job that names it fails the same way on a Mac without that grant.
    for name in ju.available():
        assert ju.load(name)["command"][0] not in ("/usr/bin/python3", "python3", "/usr/bin/python"), name


def test_the_catalog_and_cron_health_read_tidy_agents_new_logs():
    import cron_health
    import job_catalog
    entry = job_catalog.JOBS["tidy-agent"]
    assert entry.get("label", "com.marvin.tidy-agent") == "com.marvin.tidy-agent"
    assert entry["reporter"] == "~/.claude/logs/tidy-agent-error.log"
    _, logs = cron_health.JOBS["tidy-agent"]
    assert logs == [".claude/logs/tidy-agent.log", ".claude/logs/tidy-agent-error.log"]


# ── tidy-agent runs on the Mini only (owner's decision on PR #1129) ────────────────────────────────────────────────
# ~/Desktop and ~/Documents are one iCloud copy shared by both Macs. Two Macs filing the same files at 03:00 fight
# each other, so the catalog places tidy-agent on the Mini, and install refuses to put it anywhere else. These tests
# try to sneak it onto the laptop, the Linux box and an unknown machine, and repeat the install.

def _la(home):
    return home / "Library" / "LaunchAgents"


def test_the_catalog_places_tidy_agent_on_the_mini_only():
    import job_catalog
    import health_checks as hc
    assert job_catalog.JOBS["tidy-agent"]["machine"] == "mini"
    assert hc.JOB_PLACEMENT["tidy-agent"] == "mini"


def test_health_flags_tidy_agent_on_the_laptop_and_missing_on_the_mini():
    import health_checks as hc
    laptop = [j for j, w in hc.JOB_PLACEMENT.items() if w in ("both", "laptop")]
    sev, detail = hc.evaluate_job_placement(laptop + ["tidy-agent"], "laptop")
    assert sev == "yellow" and "meant for the other machine: tidy-agent" in detail
    mini = [j for j, w in hc.JOB_PLACEMENT.items() if w in ("both", "mini") and j != "tidy-agent"]
    sev, detail = hc.evaluate_job_placement(mini, "mini")
    assert sev == "yellow" and "missing: tidy-agent" in detail


def test_install_on_the_mini_installs_tidy_agent(tmp_path):
    run = FakeRun()
    out = ju.install(["tidy-agent"], os_name="macos", home=tmp_path, run=run, uid=501, role="mini")
    assert out == [{"job": "tidy-agent", "changed": True, "ok": True}]
    assert (_la(tmp_path) / "com.marvin.tidy-agent.plist").exists()


def test_install_on_the_laptop_writes_nothing_and_loads_nothing(tmp_path):
    run = FakeRun()
    out = ju.install(["tidy-agent"], os_name="macos", home=tmp_path, run=run, uid=501, role="laptop")
    assert out == [{"job": "tidy-agent", "changed": False, "ok": True, "skipped": "placed on the mini only"}]
    assert not (_la(tmp_path) / "com.marvin.tidy-agent.plist").exists()
    assert not any("bootstrap" in c for c in run.calls)


def test_install_on_the_laptop_removes_a_copy_already_installed_there(tmp_path):
    ju.install(["tidy-agent"], os_name="macos", home=tmp_path, run=FakeRun(), uid=501, role="mini")
    run = FakeRun()
    out = ju.install(["tidy-agent"], os_name="macos", home=tmp_path, run=run, uid=501, role="laptop")
    assert out == [{"job": "tidy-agent", "changed": True, "ok": True, "skipped": "placed on the mini only"}]
    assert ["launchctl", "bootout", "gui/501/com.marvin.tidy-agent"] in run.calls
    assert not (_la(tmp_path) / "com.marvin.tidy-agent.plist").exists()
    # A repeat finds nothing to remove and touches launchd not at all.
    run2 = FakeRun()
    out = ju.install(["tidy-agent"], os_name="macos", home=tmp_path, run=run2, uid=501, role="laptop")
    assert out[0]["changed"] is False and run2.calls == []


def test_a_mixed_install_on_the_laptop_still_installs_the_jobs_placed_there(tmp_path):
    out = ju.install(["tidy-agent", "usage-scan"], os_name="macos", home=tmp_path, run=FakeRun(), uid=501, role="laptop")
    assert [r["job"] for r in out] == ["tidy-agent", "usage-scan"]
    assert "skipped" in out[0] and "skipped" not in out[1]
    assert (_la(tmp_path) / "com.marvin.usage-scan.plist").exists()


def test_install_refuses_a_placed_job_when_it_cannot_tell_which_mac_this_is(tmp_path):
    run = FakeRun()
    with pytest.raises(ju.JobError, match="which Mac"):
        ju.install(["usage-scan", "tidy-agent"], os_name="macos", home=tmp_path, run=run, uid=501, role=None)
    assert run.calls == [] and not _la(tmp_path).exists()   # refused before anything was installed


def test_a_job_placed_on_both_needs_no_role(tmp_path, monkeypatch):
    monkeypatch.setattr(ju, "machine_role", lambda: None)
    out = ju.install(["usage-scan"], os_name="macos", home=tmp_path, run=FakeRun(), uid=501)
    assert out[0]["ok"] and "skipped" not in out[0]


def test_tidy_agent_is_never_installed_on_linux(tmp_path):
    # The box has no iCloud Desktop to file. The definition says macos; the catalog's Mac placement isn't consulted.
    assert ju.load("tidy-agent")["os"] == "macos"
    run = FakeRun()
    out = ju.install(["tidy-agent"], os_name="linux", home=tmp_path, run=run)
    assert out == [{"job": "tidy-agent", "changed": False, "ok": True, "skipped": "runs on macos only"}]
    assert not (tmp_path / ".config" / "systemd" / "user" / "marvin-tidy-agent.timer").exists()
    assert not any("enable" in c for c in run.calls)


def test_linux_removes_a_tidy_agent_unit_someone_installed_by_hand(tmp_path):
    d = tmp_path / ".config" / "systemd" / "user"
    d.mkdir(parents=True)
    (d / "marvin-tidy-agent.service").write_text("x")
    (d / "marvin-tidy-agent.timer").write_text("x")
    run = FakeRun()
    out = ju.install(["tidy-agent"], os_name="linux", home=tmp_path, run=run)
    assert out[0]["changed"] is True and out[0]["ok"] is True
    assert ["systemctl", "--user", "disable", "--now", "marvin-tidy-agent.timer"] in run.calls
    assert not (d / "marvin-tidy-agent.service").exists() and not (d / "marvin-tidy-agent.timer").exists()


def test_the_box_still_installs_health_check_although_the_catalog_says_mini(tmp_path):
    # Catalog placement is about the two Macs (Health checks launchd only); the box runs health-check by systemd.
    out = ju.install(["health-check"], os_name="linux", home=tmp_path, run=FakeRun())
    assert out == [{"job": "health-check", "changed": True, "ok": True}]


@pytest.mark.parametrize("bad", ["windows", "", ["macos"], 1, "MacOS"])
def test_a_bad_os_value_is_refused(bad):
    job = dict(ju.load("tidy-agent"), os=bad)
    with pytest.raises(ju.JobError, match="os"):
        ju.validate(job)


@pytest.mark.parametrize("kind,os_name,want", [
    ("laptop", "macos", "laptop"), ("desktop", "macos", "mini"), ("desktop", "linux", None), (None, "macos", None)])
def test_machine_role_comes_from_the_registry_entry(monkeypatch, kind, os_name, want):
    import machine_profile
    reg = {"me": {"kind": kind, "os": os_name}} if kind else {}
    monkeypatch.setattr(machine_profile, "_load_registry", lambda: reg)
    monkeypatch.setattr(machine_profile, "registry_id", lambda: "me")
    monkeypatch.setattr(ju.host_os, "os_name", lambda: os_name)
    assert ju.machine_role() == want
