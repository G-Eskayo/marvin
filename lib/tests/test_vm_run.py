"""vm_run: disposable VMs from golden images on mac-mini-2012 (ADR 0069). Every run gets a throwaway copy of a
frozen image and the copy is always destroyed -- on success, failure, timeout or a crash mid-run."""
import subprocess

import pytest

import vm_run


class FakeHost:
    """Records every host command; `fail_on` makes the first command containing that word fail."""

    def __init__(self, fail_on=None, ip="192.168.122.50", output="hello\n", exit_code=0):
        self.calls, self.fail_on, self.ip, self.output, self.exit_code = [], fail_on, ip, output, exit_code

    def __call__(self, cmd, timeout=None, check=True, input=None):
        """Same contract as vm_run's real host runner: a CompletedProcess, raising on failure when check=True."""
        self.calls.append(cmd)
        self.inputs = getattr(self, "inputs", []) + [input]
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


SECRET = "ghp_" + "x" * 36


def test_a_secret_reaches_the_command_only_through_stdin_never_argv():
    host = FakeHost()
    r = vm_run.run("marvin-test", "gh auth status", host=host, secrets={"GH_TOKEN": SECRET})
    assert r.ok
    assert not any(SECRET in " ".join(c) for c in host.calls), "a token in argv is visible to every process on the box"
    assert any(i and SECRET in i for i in host.inputs)


def test_quarantine_refuses_secrets_before_creating_anything():
    host = FakeHost()
    r = vm_run.run("quarantine", "true", host=host, secrets={"GH_TOKEN": SECRET})
    assert not r.ok and "quarantine" in r.error
    assert host.calls == []


@pytest.mark.parametrize("name", ["GH TOKEN", "1ABC", "A;rm -rf /", "", "PATH"])
def test_secret_names_must_be_plain_and_not_override_the_shell(name):
    host = FakeHost()
    r = vm_run.run("marvin-test", "true", host=host, secrets={name: "v"})
    assert not r.ok and host.calls == []


def test_a_secret_with_a_newline_is_refused():
    r = vm_run.run("marvin-test", "true", host=FakeHost(), secrets={"GH_TOKEN": "a\nexport EVIL=1"})
    assert not r.ok


# ── marvin-build: the image box ticket builds run in (marvin #950) ─────────────────────────────────────────────────

@pytest.fixture
def built(tmp_path):
    d = tmp_path / "runs" / "golden"
    d.mkdir(parents=True)
    (d / "marvin-build.qcow2").write_text("img")
    return d


def test_marvin_build_boots_from_its_own_frozen_image_on_nat_with_the_test_key(built):
    host = FakeHost()
    r = vm_run.run("marvin-build", "true", host=host)
    assert r.ok
    create = next(c for c in host.calls if c[:2] == ["qemu-img", "create"])
    assert create[create.index("-b") + 1] == str(built / "marvin-build.qcow2")
    install = " ".join(next(c for c in host.calls if c[0] == "virt-install"))
    assert "network=default" in install
    assert all("marvin_vm" in " ".join(c) for c in host.calls if c[0] == "ssh")


def test_a_missing_golden_image_fails_before_anything_is_created(tmp_path):
    host = FakeHost()
    r = vm_run.run("marvin-build", "true", host=host)
    assert not r.ok and "golden image" in r.error and "build-builder-image.sh" in r.error
    assert host.calls == []


def test_vcpus_and_memory_are_passed_through(built):
    host = FakeHost()
    vm_run.run("marvin-build", "true", host=host, memory_mb=5120, vcpus=4)
    install = next(c for c in host.calls if c[0] == "virt-install")
    assert install[install.index("--memory") + 1] == "5120" and install[install.index("--vcpus") + 1] == "4"


@pytest.mark.parametrize("vcpus", [0, -1, 99, True, "4"])
def test_silly_vcpus_are_refused(built, vcpus):
    host = FakeHost()
    assert not vm_run.run("marvin-build", "true", host=host, vcpus=vcpus).ok and host.calls == []


class FreezeHost(FakeHost):
    """domstate says "running" until poweroff was sent, then "shut off"; `convert_fails` breaks qemu-img convert."""

    def __init__(self, convert_fails=False, never_stops=False, **kw):
        super().__init__(**kw)
        self.convert_fails, self.never_stops, self.off = convert_fails, never_stops, False

    def __call__(self, cmd, timeout=None, check=True, input=None):
        text = " ".join(cmd)
        if cmd[0] == "ssh" and "poweroff" in text:
            self.calls.append(cmd)
            self.off = not self.never_stops
            return subprocess.CompletedProcess(cmd, 255, "", "connection closed")
        if "domstate" in text:
            self.calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "shut off\n" if self.off else "running\n", "")
        if cmd[:2] == ["qemu-img", "convert"]:
            self.calls.append(cmd)
            if self.convert_fails:
                raise subprocess.CalledProcessError(1, cmd, "", "No space left on device")
            from pathlib import Path
            Path(cmd[-1]).write_text("flattened")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return super().__call__(cmd, timeout=timeout, check=check, input=input)


def test_freeze_shuts_the_vm_down_then_flattens_it_read_only(tmp_path):
    out = tmp_path / "frozen" / "marvin-build.qcow2"
    out.parent.mkdir()
    host = FreezeHost()
    r = vm_run.run("marvin-test", "bash provision.sh", host=host, freeze_to=out)
    assert r.ok, r.error
    order = [" ".join(c) for c in host.calls]
    poweroff = next(i for i, c in enumerate(order) if "poweroff" in c)
    convert = next(i for i, c in enumerate(order) if c.startswith("qemu-img convert"))
    assert poweroff < convert, "a disk is only copied once its VM has stopped writing to it"
    assert out.read_text() == "flattened" and (out.stat().st_mode & 0o777) == 0o444
    assert host.ran("undefine") and not list((tmp_path / "runs").glob("run-*.qcow2"))


def test_a_failed_provisioning_is_never_frozen(tmp_path):
    out = tmp_path / "marvin-build.qcow2"
    host = FreezeHost(exit_code=1)
    r = vm_run.run("marvin-test", "bash provision.sh", host=host, freeze_to=out)
    assert not r.ok and not out.exists() and not host.ran("convert")
    assert host.ran("undefine")


def test_a_failed_flatten_leaves_the_old_image_untouched_and_no_partial_file(tmp_path):
    out = tmp_path / "marvin-build.qcow2"
    out.write_text("the image builds run on today")
    host = FreezeHost(convert_fails=True)
    r = vm_run.run("marvin-test", "true", host=host, freeze_to=out)
    assert not r.ok and "No space" in r.error
    assert out.read_text() == "the image builds run on today"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith("marvin-build")] == ["marvin-build.qcow2"]


def test_a_vm_that_never_shuts_down_is_not_frozen(tmp_path):
    out = tmp_path / "marvin-build.qcow2"
    host = FreezeHost(never_stops=True)
    r = vm_run.run("marvin-test", "true", host=host, freeze_to=out, boot_timeout=1)
    assert not r.ok and "shut" in r.error and not out.exists()
    assert host.ran("undefine")


def test_freezing_over_a_golden_image_in_use_or_into_the_runs_dir_is_refused(tmp_path, built):
    for bad in (tmp_path / "golden" / "marvin-test.qcow2", tmp_path / "runs" / "run-marvin-test-deadbeef.qcow2"):
        host = FreezeHost()
        r = vm_run.run("marvin-test", "true", host=host, freeze_to=bad)
        assert not r.ok and host.calls == [], bad


# ── owner records and the orphan sweep ─────────────────────────────────────────────────────────────────────────────

def test_a_run_leaves_an_owner_record_while_it_runs_and_none_after(tmp_path):
    seen = []

    class Peek(FakeHost):
        def __call__(self, cmd, timeout=None, check=True, input=None):
            if cmd[0] == "ssh" and cmd[-1] != "true":
                seen.extend(p.name for p in (tmp_path / "runs").glob("*.owner"))
            return super().__call__(cmd, timeout=timeout, check=check, input=input)

    vm_run.run("marvin-test", "echo hi", host=Peek())
    assert len(seen) == 1 and seen[0].startswith("run-marvin-test-")
    assert not list((tmp_path / "runs").glob("*.owner"))


class SweepHost(FakeHost):
    def __init__(self, domains):
        super().__init__()
        self.domains = domains

    def __call__(self, cmd, timeout=None, check=True, input=None):
        if "list" in cmd and "--name" in cmd:
            self.calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "\n".join(self.domains) + "\n", "")
        return super().__call__(cmd, timeout=timeout, check=check, input=input)


def _owner(runs, name, pid):
    import json
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{name}.owner").write_text(json.dumps({"pid": pid}))


def test_the_sweep_removes_what_a_crashed_run_left_and_keeps_live_runs_and_everything_else(tmp_path, built):
    runs = tmp_path / "runs"
    dead, live, ownerless = "run-marvin-build-0badf00d", "run-marvin-build-a11ve000", "run-marvin-test-0000beef"
    _owner(runs, dead, 999_999)
    _owner(runs, live, 4242)
    for n in (dead, live, ownerless):
        (runs / f"{n}.qcow2").write_text("disk")
    (runs / "notes.qcow2").write_text("someone else's")
    host = SweepHost([dead, live, ownerless, "Whonix-Gateway", "run-evil; rm -rf /"])
    removed = vm_run.sweep(host=host, alive=lambda pid: pid == 4242)
    assert sorted(removed) == sorted([dead, ownerless])
    destroyed = [c[-1] for c in host.calls if "destroy" in c]
    assert sorted(destroyed) == sorted([dead, ownerless]), "never Whonix, a live run, or a name that isn't ours"
    assert (runs / f"{live}.qcow2").exists() and (runs / f"{live}.owner").exists()
    assert not (runs / f"{dead}.qcow2").exists() and not (runs / f"{dead}.owner").exists()
    assert not (runs / f"{ownerless}.qcow2").exists()
    assert (runs / "notes.qcow2").exists() and (built / "marvin-build.qcow2").exists()


def test_the_sweep_survives_virsh_failing_and_still_clears_orphaned_disks(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "run-quarantine-12345678.qcow2").write_text("disk")
    removed = vm_run.sweep(host=FakeHost(fail_on="list"), alive=lambda pid: False)
    assert removed == ["run-quarantine-12345678"] and not list(runs.glob("*.qcow2"))


def test_a_corrupt_owner_record_counts_as_dead(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "run-marvin-test-cafecafe.owner").write_text("{not json")
    (runs / "run-marvin-test-cafecafe.qcow2").write_text("disk")
    assert vm_run.sweep(host=SweepHost([]), alive=lambda pid: True) == ["run-marvin-test-cafecafe"]


def test_a_sigterm_mid_command_still_destroys_the_vm(tmp_path):
    # GNU timeout sends SIGTERM; main() turns it into SystemExit, which must still run run()'s cleanup.
    class Killed(FakeHost):
        def __call__(self, cmd, timeout=None, check=True, input=None):
            if cmd[0] == "ssh" and cmd[-1] != "true":
                self.calls.append(cmd)
                vm_run._terminate_cleanly(15, None)
            return super().__call__(cmd, timeout=timeout, check=check, input=input)

    host = Killed()
    with pytest.raises(SystemExit):
        vm_run.run("marvin-test", "sleep 999", host=host)
    assert host.ran("undefine") and not list((tmp_path / "runs").iterdir())
