"""Linux device identity (ADR 0069): mac-mini-2012 gets the same registry fields as the Macs, read from the
firmware tables instead of ioreg, plus an os field."""
import pytest

import machine_profile as mp


@pytest.fixture
def linux_box(monkeypatch, tmp_path):
    """A fake Linux box: DMI files under tmp_path; the uuid/serial files are root-only unless made readable."""
    dmi = tmp_path / "dmi"
    dmi.mkdir()
    (dmi / "product_name").write_text("Macmini6,2\n")
    (dmi / "product_uuid").write_text("b080693d-2b90-405f-bf62-603682494206\n")
    (dmi / "product_serial").write_text("C07ABC123DWYL\n")
    monkeypatch.setattr(mp.host_os, "os_name", lambda: "linux")
    monkeypatch.setattr(mp, "DMI_DIR", dmi)
    sudo_calls = []

    def fake_run(cmd):
        if cmd[:2] == ["sudo", "-n"]:
            sudo_calls.append(cmd)
            path = cmd[-1]
            return open(path).read().strip() if not state["sudo_denied"] else ""
        if cmd == ["hostname"]:
            return "mac-mini-2012"
        if cmd == ["uname", "-m"]:
            return "x86_64"
        return ""

    state = {"sudo_denied": False, "sudo_calls": sudo_calls}
    monkeypatch.setattr(mp, "_run", fake_run)
    return state


def test_linux_identity_comes_from_dmi_with_sudo_when_the_file_is_root_only(linux_box, monkeypatch):
    real_read = mp.Path.read_text

    def root_only(self, *a, **k):
        if self.name in ("product_uuid", "product_serial"):
            raise PermissionError(13, "Permission denied")
        return real_read(self, *a, **k)

    monkeypatch.setattr(mp.Path, "read_text", root_only)
    assert mp._hardware_uuid() == "B080693D-2B90-405F-BF62-603682494206"   # uppercased like macOS's ioreg
    assert mp._serial() == "C07ABC123DWYL"
    assert linux_box["sudo_calls"], "should have fallen back to sudo -n"


def test_linux_identity_reads_dmi_directly_when_allowed(linux_box):
    assert mp._hardware_uuid() == "B080693D-2B90-405F-BF62-603682494206"
    assert not linux_box["sudo_calls"]


def test_linux_identity_is_empty_not_wrong_when_dmi_is_unreadable_and_sudo_is_refused(linux_box, monkeypatch):
    linux_box["sudo_denied"] = True
    monkeypatch.setattr(mp.Path, "read_text", lambda self, *a, **k: (_ for _ in ()).throw(PermissionError(13, "no")))
    assert mp._hardware_uuid() == ""
    assert mp._serial() == ""


def test_linux_profile_has_os_fields_and_its_own_label(linux_box):
    p = mp.build_profile()
    assert p["os"] == "linux"
    assert p["hw_model"] == "Macmini6,2"
    assert p["hostname"] == "mac-mini-2012"
    # The label must not claim to be "mac-mini": that's the M4 Mini's label and would mislabel tagged output.
    assert p["label"] == "mac-mini-2012"
    assert p["chip_arch"] == "x86_64"


def test_registry_match_ignores_uuid_case(monkeypatch):
    monkeypatch.setattr(mp, "load_or_build", lambda **k: {"hardware_uuid": "b080693d-2b90-405f-bf62-603682494206"})
    monkeypatch.setattr(mp, "_load_registry", lambda: {
        "mac-mini-2012": {"hardware_uuid": "B080693D-2B90-405F-BF62-603682494206"}})
    assert mp.registry_id() == "mac-mini-2012"


def test_an_empty_uuid_never_matches_an_entry_with_an_empty_uuid(monkeypatch):
    monkeypatch.setattr(mp, "load_or_build", lambda **k: {"hardware_uuid": "", "label": "x"})
    monkeypatch.setattr(mp, "machine_label", lambda: "x")
    monkeypatch.setattr(mp, "_load_registry", lambda: {"broken": {"hardware_uuid": ""}})
    assert mp.registry_id() == "x"
