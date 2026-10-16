import host_os


def test_os_name_maps_darwin_and_linux_and_refuses_the_rest(monkeypatch):
    monkeypatch.setattr(host_os.sys, "platform", "darwin")
    assert host_os.os_name() == "macos"
    monkeypatch.setattr(host_os.sys, "platform", "linux")
    assert host_os.os_name() == "linux"
    monkeypatch.setattr(host_os.sys, "platform", "win32")
    assert host_os.os_name() == "unknown"


def test_tailscale_on_a_mac_is_the_app_binary_even_when_path_has_none(monkeypatch):
    # launchd's PATH omits the shell's additions, so the app's absolute path must win on macOS.
    monkeypatch.setattr(host_os.sys, "platform", "darwin")
    monkeypatch.setattr(host_os.shutil, "which", lambda name: None)
    assert host_os.tailscale_bin() == "/Applications/Tailscale.app/Contents/MacOS/Tailscale"


def test_tailscale_on_linux_is_found_on_path(monkeypatch):
    monkeypatch.setattr(host_os.sys, "platform", "linux")
    monkeypatch.setattr(host_os.shutil, "which", lambda name: "/usr/local/bin/tailscale" if name == "tailscale" else None)
    assert host_os.tailscale_bin() == "/usr/local/bin/tailscale"


def test_tailscale_on_linux_falls_back_to_the_package_path_when_path_is_bare(monkeypatch):
    # systemd units get a minimal PATH too; the Debian package installs to /usr/bin.
    monkeypatch.setattr(host_os.sys, "platform", "linux")
    monkeypatch.setattr(host_os.shutil, "which", lambda name: None)
    assert host_os.tailscale_bin() == "/usr/bin/tailscale"


def test_task_dispatch_uses_the_host_os_tailscale_path():
    import task_dispatch
    assert task_dispatch.TAILSCALE_BIN == host_os.tailscale_bin()
