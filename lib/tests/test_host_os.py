import pytest

import host_os


def test_os_name_maps_darwin_and_linux_and_refuses_the_rest(monkeypatch):
    monkeypatch.setattr(host_os.sys, "platform", "darwin")
    assert host_os.os_name() == "macos"
    monkeypatch.setattr(host_os.sys, "platform", "linux")
    assert host_os.os_name() == "linux"
    monkeypatch.setattr(host_os.sys, "platform", "win32")
    assert host_os.os_name() == "unknown"


def _installed(monkeypatch, *paths):
    # Pretend exactly these files are executable; nothing on the real disk is consulted.
    monkeypatch.setattr(host_os.os, "access", lambda p, mode: str(p) in paths)


def test_tailscale_on_a_mac_is_the_app_binary_even_when_path_has_none(monkeypatch):
    # launchd's PATH omits the shell's additions, so an absolute path must win on macOS.
    monkeypatch.setattr(host_os.sys, "platform", "darwin")
    monkeypatch.setattr(host_os.shutil, "which", lambda name: None)
    _installed(monkeypatch, "/Applications/Tailscale.app/Contents/MacOS/Tailscale")
    assert host_os.tailscale_bin() == "/Applications/Tailscale.app/Contents/MacOS/Tailscale"


@pytest.mark.parametrize("path", ["/opt/homebrew/bin/tailscale", "/usr/local/bin/tailscale"])
def test_tailscale_on_a_mac_with_only_homebrew_is_found_with_a_bare_path(monkeypatch, path):
    # marvin#889: the Mac mini runs Homebrew's tailscale and no app since 2026-10-26; the app-only path made every
    # peer read as offline for four days.
    monkeypatch.setattr(host_os.sys, "platform", "darwin")
    monkeypatch.setattr(host_os.shutil, "which", lambda name: None)
    _installed(monkeypatch, path)
    assert host_os.tailscale_bin() == path


def test_tailscale_on_a_mac_with_both_prefers_the_app(monkeypatch):
    # The app is what the MacBook runs; its CLI talks to the app's daemon.
    monkeypatch.setattr(host_os.sys, "platform", "darwin")
    _installed(monkeypatch, "/Applications/Tailscale.app/Contents/MacOS/Tailscale", "/opt/homebrew/bin/tailscale")
    assert host_os.tailscale_bin() == "/Applications/Tailscale.app/Contents/MacOS/Tailscale"


def test_tailscale_on_a_mac_with_neither_uses_path_then_says_none(monkeypatch):
    monkeypatch.setattr(host_os.sys, "platform", "darwin")
    _installed(monkeypatch)
    monkeypatch.setattr(host_os.shutil, "which", lambda name: "/somewhere/tailscale")
    assert host_os.tailscale_bin() == "/somewhere/tailscale"
    monkeypatch.setattr(host_os.shutil, "which", lambda name: None)
    assert host_os.tailscale_bin() is None
    assert host_os.tailscale_bin_or_default() == "/Applications/Tailscale.app/Contents/MacOS/Tailscale"


def test_peer_care_has_no_tailscale_lookup_of_its_own():
    # One answer to "where is tailscale" (ADR 0069); a second copy is how #889 happened.
    import peer_care
    assert peer_care.TAILSCALE_CANDIDATES is host_os.TAILSCALE_CANDIDATES
    assert peer_care.tailscale_bin is host_os.tailscale_bin


def test_tailscale_on_linux_is_found_on_path(monkeypatch):
    monkeypatch.setattr(host_os.sys, "platform", "linux")
    _installed(monkeypatch)
    monkeypatch.setattr(host_os.shutil, "which", lambda name: "/usr/local/bin/tailscale" if name == "tailscale" else None)
    assert host_os.tailscale_bin() == "/usr/local/bin/tailscale"


def test_tailscale_on_linux_falls_back_to_the_package_path_when_path_is_bare(monkeypatch):
    # systemd units get a minimal PATH too; the Debian package installs to /usr/bin.
    monkeypatch.setattr(host_os.sys, "platform", "linux")
    monkeypatch.setattr(host_os.shutil, "which", lambda name: None)
    _installed(monkeypatch, "/usr/bin/tailscale")
    assert host_os.tailscale_bin() == "/usr/bin/tailscale"


def test_task_dispatch_uses_the_host_os_tailscale_path():
    import task_dispatch
    assert task_dispatch.TAILSCALE_BIN == host_os.tailscale_bin_or_default()


def _settings(tmp_path, monkeypatch, body):
    claude = tmp_path / "home" / ".claude"
    claude.mkdir(parents=True)
    if body is not None:
        (claude / "settings.json").write_text(body)
    monkeypatch.setattr(host_os.Path, "home", lambda: tmp_path / "home")
    return claude


def test_memory_dir_follows_the_synced_setting_on_a_machine_with_a_different_home(tmp_path, monkeypatch):
    # The setting names the Mac's absolute path; on mac-mini-2012 (/home/marvin) it must land in this home's .claude.
    claude = _settings(tmp_path, monkeypatch,
                       '{"autoMemoryDirectory": "/Users/someone/.claude/projects/-Users-someone/memory"}')
    assert host_os.memory_dir() == claude / "projects" / "-Users-someone" / "memory"


def test_memory_dir_accepts_a_tilde_setting(tmp_path, monkeypatch):
    claude = _settings(tmp_path, monkeypatch, '{"autoMemoryDirectory": "~/.claude/projects/-x/memory"}')
    assert host_os.memory_dir() == claude / "projects" / "-x" / "memory"


@pytest.mark.parametrize("body", [None, "not json", "{}", '{"autoMemoryDirectory": 5}',
                                  '{"autoMemoryDirectory": "/etc/passwd"}', '{"autoMemoryDirectory": "/a/.claude/../../etc"}'])
def test_memory_dir_falls_back_to_claude_codes_own_default_when_the_setting_is_missing_or_bad(tmp_path, monkeypatch, body):
    claude = _settings(tmp_path, monkeypatch, body)
    home = str(tmp_path / "home")
    assert host_os.memory_dir() == claude / "projects" / home.replace("/", "-") / "memory"


def test_boot_time_on_macos_parses_sysctl_kern_boottime(monkeypatch):
    monkeypatch.setattr(host_os, "os_name", lambda: "macos")
    # Typical sysctl output: "{ sec = 1727000000, usec = 500000 }"
    monkeypatch.setattr(host_os.subprocess, "run",
                       lambda *a, **kw: type('P', (), {'returncode': 0, 'stdout': '{ sec = 1727000000, usec = 500000 }'}))
    result = host_os.boot_time()
    assert result == 1727000000.0


def test_boot_time_on_linux_parses_who_b_output(monkeypatch):
    monkeypatch.setattr(host_os, "os_name", lambda: "linux")
    who_output = "                      system boot  2026-11-10 10:30"
    monkeypatch.setattr(host_os.subprocess, "run",
                       lambda *a, **kw: type('P', (), {'returncode': 0, 'stdout': who_output}))
    result = host_os.boot_time()
    assert result is not None and isinstance(result, float)


def test_boot_time_returns_none_on_error(monkeypatch):
    monkeypatch.setattr(host_os, "os_name", lambda: "macos")
    monkeypatch.setattr(host_os.subprocess, "run",
                       lambda *a, **kw: type('P', (), {'returncode': 1, 'stdout': ''}))
    assert host_os.boot_time() is None


def test_boot_time_returns_none_for_unknown_os(monkeypatch):
    monkeypatch.setattr(host_os, "os_name", lambda: "unknown")
    assert host_os.boot_time() is None


def test_process_start_time_on_macos_parses_ps_lstart(monkeypatch):
    monkeypatch.setattr(host_os, "os_name", lambda: "macos")
    ps_output = "Mon Nov 10 10:30:45 2026"
    monkeypatch.setattr(host_os.subprocess, "run",
                       lambda *a, **kw: type('P', (), {'returncode': 0, 'stdout': ps_output}))
    result = host_os.process_start_time(1234)
    assert result is not None and isinstance(result, float)


def test_process_start_time_returns_none_for_dead_process_on_macos(monkeypatch):
    monkeypatch.setattr(host_os, "os_name", lambda: "macos")
    monkeypatch.setattr(host_os.subprocess, "run",
                       lambda *a, **kw: type('P', (), {'returncode': 1, 'stdout': ''}))
    assert host_os.process_start_time(999999999) is None


def test_process_start_time_returns_none_for_invalid_pid(monkeypatch):
    assert host_os.process_start_time(-1) is None
    assert host_os.process_start_time(0) is None
    assert host_os.process_start_time("not a pid") is None


def test_process_start_time_returns_none_on_unreadable_proc(monkeypatch):
    monkeypatch.setattr(host_os, "os_name", lambda: "linux")
    # Simulate /proc/stat read failure
    def fake_open(*args, **kwargs):
        raise FileNotFoundError("No such process")
    monkeypatch.setattr("builtins.open", fake_open)
    assert host_os.process_start_time(999999) is None
