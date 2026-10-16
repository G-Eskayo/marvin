"""vm_run: disposable VMs from golden images on mac-mini-2012 (ADR 0069). Every run gets a throwaway copy of a
frozen image and the copy is always destroyed -- on success, failure, timeout or a crash mid-run."""
import subprocess

import pytest

import vm_run


class FakeHost:
    """Records every host command; `fail_on` makes the first command containing that word fail."""

    def __init__(self, fail_on=None, ip="192.168.122.50", output="hello\n", exit_code=0):
        self.calls, self.fail_on, self.ip, self.output, self.exit_code = [], fail_on, ip, output, exit_code

    def __call__(self, cmd, timeout=None, check=True):
        """Same contract as vm_run's real host runner: a CompletedProcess, raising on failure when check=True."""
        self.calls.append(cmd)
        text = " ".join(cmd)
        if self.fail_on and self.fail_on in text:
            if check:
                raise subprocess.CalledProcessError(1, cmd, "", f"{self.fail_on} broke")
            return subprocess.CompletedProcess(cmd, 1, "", f"{self.fail_on} broke")
        out = ""
        if "domifaddr" in text:
            out = f" vnet0  52:54:00:aa:bb:cc  ipv4  {self.ip}/24\n" if self.ip else ""
        elif cmd[0] == "ssh" and cmd[-1] != "true":
            return subprocess.CompletedProcess(cmd, self.exit_code, self.output, "")
        return subprocess.CompletedProcess(cmd, 0, out, "")

    def ran(self, word):
        return any(word in " ".join(c) for c in self.calls)


@pytest.fixture(autouse=True)
def fast(monkeypatch, tmp_path):
    monkeypatch.setattr(vm_run, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(vm_run, "GOLDEN_DIR", tmp_path / "golden")
    (tmp_path / "golden").mkdir()
    (tmp_path / "golden" / "marvin-test.qcow2").write_text("img")
    (tmp_path / "golden" / "quarantine.qcow2").write_text("img")
    monkeypatch.setattr(vm_run.time, "sleep", lambda s: None)


def test_a_run_returns_the_command_output_and_cleans_up(tmp_path):
    host = FakeHost()
    r = vm_run.run("marvin-test", "echo hello", host=host)
    assert r.ok and r.output == "hello\n"
    assert host.ran("destroy") and host.ran("undefine")
    assert not list((tmp_path / "runs").glob("*.qcow2")), "the throwaway disk must be deleted"


def test_the_golden_image_is_only_ever_a_read_only_backing_file():
    host = FakeHost()
    vm_run.run("marvin-test", "true", host=host)
    create = next(c for c in host.calls if c[:2] == ["qemu-img", "create"])
    assert "-b" in create and create[create.index("-b") + 1].endswith("golden/marvin-test.qcow2")
    install = " ".join(next(c for c in host.calls if c[0] == "virt-install"))
    assert "golden/" not in install, "the VM must boot from the copy, never the golden image"


@pytest.mark.parametrize("step", ["virt-install", "domifaddr", "rsync"])
def test_cleanup_happens_even_when_a_step_fails(step, tmp_path):
    host = FakeHost(fail_on=step)
    r = vm_run.run("marvin-test", "true", host=host, repo_dir=tmp_path, boot_timeout=1)
    assert not r.ok and (step in r.error or "no IP" in r.error)
    assert host.ran("undefine")
    assert not list((tmp_path / "runs").glob("*.qcow2"))


def test_a_failing_command_is_reported_with_its_exit_code():
    r = vm_run.run("marvin-test", "pytest", host=FakeHost(exit_code=3, output="1 failed"))
    assert not r.ok and r.exit_code == 3 and "1 failed" in r.output


@pytest.mark.parametrize("name", ["../etc/passwd", "marvin-test/../../x", "", "MARVIN-TEST", "nope"])
def test_only_known_images_can_be_run(name):
    host = FakeHost()
    r = vm_run.run(name, "true", host=host)
    assert not r.ok and "unknown image" in r.error
    assert host.calls == [], "nothing may be created for an unknown image"


def test_quarantine_vms_get_the_isolated_network_and_test_vms_get_nat():
    q, t = FakeHost(), FakeHost()
    vm_run.run("quarantine", "true", host=q)
    vm_run.run("marvin-test", "true", host=t)
    q_install = " ".join(next(c for c in q.calls if c[0] == "virt-install"))
    t_install = " ".join(next(c for c in t.calls if c[0] == "virt-install"))
    assert "network=marvin-isolated" in q_install and "network=default" not in q_install
    assert "network=default" in t_install


def test_two_runs_never_share_a_name_or_disk():
    a, b = FakeHost(), FakeHost()
    vm_run.run("marvin-test", "true", host=a)
    vm_run.run("marvin-test", "true", host=b)
    disk = lambda h: next(c for c in h.calls if c[:2] == ["qemu-img", "create"])[-1]
    assert disk(a) != disk(b)


def test_no_ip_within_the_boot_timeout_fails_and_cleans_up(tmp_path):
    host = FakeHost(ip="")
    r = vm_run.run("marvin-test", "true", host=host, boot_timeout=1)
    assert not r.ok and "no IP" in r.error
    assert host.ran("undefine")


def test_vms_always_get_a_video_device_and_vnc_only_listens_locally():
    # Without one, Debian's GRUB reset-loops under libvirt on the box (2026-10-16).
    host = FakeHost()
    vm_run.run("marvin-test", "true", host=host)
    install = next(c for c in host.calls if c[0] == "virt-install")
    assert "--video" in install and install[install.index("--graphics") + 1] != "none"
    assert "listen=127.0.0.1" in install[install.index("--graphics") + 1]


def test_each_image_is_reached_with_its_own_key_and_quarantine_never_sees_the_test_key():
    q, t = FakeHost(), FakeHost()
    vm_run.run("quarantine", "true", host=q)
    vm_run.run("marvin-test", "true", host=t)
    q_ssh = [" ".join(c) for c in q.calls if c[0] == "ssh"]
    t_ssh = [" ".join(c) for c in t.calls if c[0] == "ssh"]
    assert q_ssh and all("marvin_quarantine" in c and "marvin_vm" not in c for c in q_ssh)
    assert t_ssh and all("marvin_vm" in c for c in t_ssh)
