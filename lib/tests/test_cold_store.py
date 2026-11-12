"""Tests for cold_store.py. Real rsync, real files, a real shell standing in for the cold host: the fake `ssh` runs
the command through /bin/sh exactly as sshd's login shell would, so quoting, paths with spaces and rsync's server
mode are all exercised for real. Each test tries to break park or ensure.
    ~/.agents/venv/bin/python -m pytest lib/tests/test_cold_store.py -v
"""
from __future__ import annotations
import json
import os
import shutil
import threading
from pathlib import Path

import pytest

import cold_store as cs

FAKE_SSH = """#!/bin/sh
# ssh HOST CMD...: run CMD here through a shell, like the remote login shell. DOWN next to this file = host off.
here="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$here/DOWN" ]; then echo "ssh: connect to host $1 port 22: Host is down" >&2; exit 255; fi
echo "$*" >> "$here/ssh.log"
shift
exec /bin/sh -c "$*"
"""


def _script(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(0o755)
    return path


@pytest.fixture
def world(tmp_path):
    """A home with a big-ish folder, a cold host root, and a store wired to the fake ssh."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh = _script(bin_dir / "ssh", FAKE_SSH)
    home = tmp_path / "home"
    data = home / "eval bench"            # a space in the folder's own name
    (data / "models" / "release" / "he model").mkdir(parents=True)
    (data / "models" / "release" / "he model" / "weights.bin").write_bytes(os.urandom(200_000))
    (data / "models" / "big.bin").write_bytes(os.urandom(300_000))
    (data / "results").mkdir()
    (data / "results" / "run 203.jsonl").write_text('{"wer": 0.1}\n' * 50)
    (data / "venv" / "bin").mkdir(parents=True)
    (data / "venv" / "bin" / "python3.12").write_text("#!/bin/sh\n")
    os.symlink("python3.12", data / "venv" / "bin" / "python")
    os.symlink("../models", data / "venv" / "models-link")
    cold = tmp_path / "cold root"         # a space in the remote root too
    store = cs.Store(host="cold-host", host_id="mac-mini-2012", root=str(cold), machine="mac-mini-1",
                     state_dir=tmp_path / "state", home=home, ssh=[str(ssh)], min_free_bytes=0,
                     in_use=lambda p: [], say=lambda m: None)
    return {"store": store, "home": home, "data": data, "cold": cold, "bin": bin_dir, "tmp": tmp_path}


def _tree(folder: Path) -> dict:
    out = {}
    for p in sorted(folder.rglob("*")):
        rel = str(p.relative_to(folder))
        out[rel] = ("link", os.readlink(p)) if p.is_symlink() else (p.read_bytes() if p.is_file() else "dir")
    return out


def _rsync_wrapper(world, body: str) -> None:
    """Point the store at an rsync wrapper; the wrapper logs every call and then runs `body` (shell)."""
    real = shutil.which("rsync")
    w = _script(world["bin"] / "rsync-wrap", f"""#!/bin/sh
here="$(cd "$(dirname "$0")" && pwd)"
echo "$*" >> "$here/rsync.log"
REAL={real}
{body}
""")
    world["store"].rsync = str(w)
    world["store"]._old_args_cache = cs._rsync_old_args(real)


def _rsync_calls(world) -> int:
    log = world["bin"] / "rsync.log"
    return len(log.read_text().splitlines()) if log.exists() else 0


# ---- park -------------------------------------------------------------------------------------------------------

def test_park_moves_the_folder_leaves_a_marker_and_ensure_brings_back_every_byte(world):
    before = _tree(world["data"])
    entry = world["store"].park(world["data"])
    assert entry["name"] == "eval-bench" and entry["origin_path"] == "~/eval bench"
    left = sorted(p.name for p in world["data"].iterdir())
    assert left == [cs.MARKER_JSON, cs.MARKER_TXT]                     # only the marker stays
    assert "marvin-cold ensure ~/eval bench" in (world["data"] / cs.MARKER_TXT).read_text()
    assert _tree(world["cold"] / "eval-bench" / "data") == before      # the cold copy is exact, links included
    assert not list(world["home"].glob(".*cold*"))                     # no stage or trash left behind

    got = world["store"].ensure(str(world["data"]))
    assert got == world["data"]
    assert _tree(world["data"]) == before                              # back byte for byte, marker gone
    assert world["store"].catalog("eval-bench")["state"] == "restored"


def test_park_twice_is_idempotent_and_copies_nothing_the_second_time(world):
    _rsync_wrapper(world, 'exec "$REAL" "$@"')
    first = world["store"].park(world["data"])
    calls = _rsync_calls(world)
    assert world["store"].park(world["data"])["manifest_sha256"] == first["manifest_sha256"]
    assert _rsync_calls(world) == calls


def test_an_interrupted_copy_leaves_the_folder_untouched_and_the_next_park_resumes(world):
    # First call: copy only part of the tree, then die like a dropped link. Later calls are real.
    _rsync_wrapper(world, f"""
if [ ! -f "$here/once" ]; then touch "$here/once"; "$REAL" --exclude big.bin "$@"; exit 20; fi
exec "$REAL" "$@"
""")
    before = _tree(world["data"])
    with pytest.raises(cs.ColdError) as e:
        world["store"].park(world["data"])
    assert e.value.code == cs.COPY_STOPPED
    assert _tree(world["data"]) == before                              # nothing local removed
    assert world["store"].catalog("eval-bench") is None
    assert not (world["cold"] / "eval-bench" / "entry.json").exists()
    world["store"].park(world["data"])
    assert _tree(world["cold"] / "eval-bench" / "data") == before


def test_a_file_corrupted_in_transit_is_caught_and_repaired_before_anything_is_deleted(world):
    target = world["cold"] / "eval-bench" / "data" / "models" / "big.bin"
    _rsync_wrapper(world, f"""
"$REAL" "$@"; rc=$?
if [ ! -f "$here/once" ]; then touch "$here/once"; printf 'X' | dd of="{target}" bs=1 seek=1000 conv=notrunc 2>/dev/null; fi
exit $rc
""")
    before = _tree(world["data"])
    world["store"].park(world["data"])
    assert _tree(world["cold"] / "eval-bench" / "data") == before      # the repair pass fixed it
    assert _rsync_calls(world) == 2


def test_corruption_that_keeps_happening_fails_the_park_and_keeps_the_local_copy(world):
    target = world["cold"] / "eval-bench" / "data" / "models" / "big.bin"
    _rsync_wrapper(world, f"""
"$REAL" "$@"; rc=$?
printf 'X' | dd of="{target}" bs=1 seek=1000 conv=notrunc 2>/dev/null
exit $rc
""")
    before = _tree(world["data"])
    with pytest.raises(cs.ColdError) as e:
        world["store"].park(world["data"])
    assert e.value.code == cs.VERIFY_FAILED and "big.bin" in str(e.value)
    assert _tree(world["data"]) == before
    assert world["store"].catalog("eval-bench") is None


def test_a_folder_written_to_during_the_park_is_not_deleted(world):
    _rsync_wrapper(world, f"""
"$REAL" "$@"; rc=$?
echo late >> "{world['data']}/results/run 203.jsonl"
exit $rc
""")
    with pytest.raises(cs.ColdError) as e:
        world["store"].park(world["data"])
    assert e.value.code == cs.BUSY
    assert (world["data"] / "results" / "run 203.jsonl").read_text().endswith("late\n")
    assert not (world["data"] / cs.MARKER_JSON).exists()


def test_a_folder_with_open_files_is_refused(world):
    world["store"].in_use = lambda p: ["python3 4242"]
    with pytest.raises(cs.ColdError) as e:
        world["store"].park(world["data"])
    assert e.value.code == cs.BUSY and "4242" in str(e.value)
    assert not (world["cold"] / "eval-bench").exists()


def test_the_cold_host_being_off_fails_calmly_and_changes_nothing(world):
    (world["bin"] / "DOWN").touch()
    before = _tree(world["data"])
    with pytest.raises(cs.ColdError) as e:
        world["store"].park(world["data"])
    assert e.value.code == cs.UNREACHABLE and "asleep or off" in str(e.value)
    assert _tree(world["data"]) == before


@pytest.mark.parametrize("rel", [".ssh/keys", ".claude/projects", ".agents/var", "Library/Keychains"])
def test_secret_and_state_folders_are_never_parked(world, rel):
    d = world["home"] / rel
    d.mkdir(parents=True)
    (d / "x").write_text("secret")
    with pytest.raises(cs.ColdError) as e:
        world["store"].park(d)
    assert "never parked" in str(e.value)
    assert not world["cold"].exists()


def test_the_same_name_from_another_machine_is_refused(world):
    world["store"].park(world["data"])
    other = world["home"] / "elsewhere" / "eval bench"
    other.mkdir(parents=True)
    (other / "f").write_text("different")
    with pytest.raises(cs.ColdError) as e:
        world["store"].park(other)
    assert "already has" in str(e.value)
    assert (other / "f").read_text() == "different"


def test_a_swap_interrupted_after_the_rename_is_finished_by_the_next_call(world):
    world["store"].park(world["data"])
    trash = world["home"] / ".eval bench.cold-trash"
    trash.mkdir()
    (trash / "leftover").write_text("x")                               # as if the delete had been cut short
    world["store"].park(world["data"])
    assert not trash.exists()


# ---- ensure ------------------------------------------------------------------------------------------------------

def test_ensure_on_a_local_folder_returns_at_once_without_the_network(world):
    (world["bin"] / "DOWN").touch()                                    # any ssh would fail
    assert world["store"].ensure(str(world["data"])) == world["data"]
    assert world["store"].ensure(str(world["data"]), part="models") == world["data"] / "models"
    assert not (world["bin"] / "ssh.log").exists()


def test_ensure_when_the_cold_host_is_off_says_so_and_keeps_the_marker(world):
    world["store"].park(world["data"])
    (world["bin"] / "DOWN").touch()
    with pytest.raises(cs.ColdError) as e:
        world["store"].ensure(str(world["data"]))
    assert e.value.code == cs.UNREACHABLE and "mac-mini-2012" in str(e.value) and "asleep or off" in str(e.value)
    assert world["store"].marker(world["data"]) is not None


def test_two_ensure_calls_at_once_fetch_only_once(world):
    world["store"].park(world["data"])
    _rsync_wrapper(world, 'sleep 1; exec "$REAL" "$@"')
    results, errors = [], []

    def run():
        try:
            results.append(world["store"].ensure(str(world["data"])))
        except Exception as e:  # noqa: BLE001 - surfaced by the assert below
            errors.append(e)
    threads = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and results == [world["data"], world["data"]]
    assert _rsync_calls(world) == 1


def test_a_marker_without_its_catalog_still_fetches_and_rebuilds_the_catalog(world):
    before = _tree(world["data"])
    world["store"].park(world["data"])
    shutil.rmtree(world["tmp"] / "state")
    assert world["store"].ensure(str(world["data"])) == world["data"]
    assert _tree(world["data"]) == before
    assert world["store"].catalog("eval-bench")["state"] == "restored"


def test_a_tampered_manifest_on_the_cold_host_is_not_trusted_when_the_catalog_is_gone(world):
    world["store"].park(world["data"])
    shutil.rmtree(world["tmp"] / "state")
    mf = world["cold"] / "eval-bench" / "manifest.json"
    m = json.loads(mf.read_text())
    m["files"]["models/big.bin"][1] = "0" * 64
    mf.write_text(json.dumps(m))
    with pytest.raises(cs.ColdError) as e:
        world["store"].ensure(str(world["data"]))
    assert e.value.code == cs.VERIFY_FAILED and "not trusting" in str(e.value)


def test_data_corrupted_at_rest_on_the_cold_host_is_caught_and_the_folder_stays_parked(world):
    world["store"].park(world["data"])
    bad = world["cold"] / "eval-bench" / "data" / "models" / "big.bin"
    b = bytearray(bad.read_bytes())
    b[5] ^= 0xFF
    bad.write_bytes(bytes(b))
    with pytest.raises(cs.ColdError) as e:
        world["store"].ensure(str(world["data"]))
    assert e.value.code == cs.VERIFY_FAILED and "big.bin" in str(e.value)
    assert world["store"].marker(world["data"]) is not None


def test_no_room_for_the_fetch_is_refused_before_any_byte_moves(world):
    world["store"].park(world["data"])
    _rsync_wrapper(world, 'exec "$REAL" "$@"')
    world["store"].free = lambda p: 400_000                            # less than the ~500 KB it needs
    with pytest.raises(cs.ColdError) as e:
        world["store"].ensure(str(world["data"]))
    assert e.value.code == cs.NO_SPACE
    assert _rsync_calls(world) == 0
    world["store"].min_free_bytes = 10**9
    world["store"].free = lambda p: 10**9 + 100                        # fits, but would go under the floor
    with pytest.raises(cs.ColdError):
        world["store"].ensure(str(world["data"]))
    assert world["store"].ensure(str(world["data"]), min_free_bytes=0) == world["data"]


def test_ensure_part_fetches_only_that_sub_folder_then_the_rest_on_a_full_ensure(world):
    before = _tree(world["data"])
    world["store"].park(world["data"])
    got = world["store"].ensure(str(world["data"]), part="models/release/he model")
    assert got == world["data"] / "models" / "release" / "he model"
    assert (got / "weights.bin").read_bytes() == before["models/release/he model/weights.bin"]
    assert not (world["data"] / "models" / "big.bin").exists()
    assert world["store"].marker(world["data"])["parts"] == ["models/release/he model"]
    _rsync_wrapper(world, 'exec "$REAL" "$@"')
    world["store"].ensure(str(world["data"]), part="models/release/he model")
    assert _rsync_calls(world) == 0                                    # already here: no fetch
    world["store"].ensure(str(world["data"]))
    assert _tree(world["data"]) == before


def test_ensure_part_of_a_single_file_and_of_something_missing(world):
    before = _tree(world["data"])
    world["store"].park(world["data"])
    world["store"].ensure(str(world["data"]), part="results/run 203.jsonl")
    assert (world["data"] / "results" / "run 203.jsonl").read_bytes() == before["results/run 203.jsonl"]
    with pytest.raises(cs.ColdError) as e:
        world["store"].ensure(str(world["data"]), part="nope")
    assert e.value.code == cs.NOT_PARKED
    with pytest.raises(cs.ColdError):
        world["store"].ensure(str(world["data"]), part="../../etc")


def test_ensure_by_name_and_on_another_machine_that_never_parked_it(world, tmp_path):
    before = _tree(world["data"])
    world["store"].park(world["data"])
    shutil.rmtree(world["data"])                                       # another Mac: no marker, no catalog
    other = cs.Store(host="cold-host", host_id="mac-mini-2012", root=world["store"].root, machine="macbook-pro-1",
                     state_dir=tmp_path / "other-state", home=world["home"], ssh=world["store"].ssh, min_free_bytes=0,
                     say=lambda m: None)
    assert other.ensure("~/eval bench".replace("~", str(world["home"]))) == world["data"]
    assert _tree(world["data"]) == before
    shutil.rmtree(world["data"])
    assert other.ensure("eval-bench") == world["data"]                 # by name


def test_ensure_optional_of_something_never_parked_succeeds_quietly(world):
    assert world["store"].ensure(str(world["home"] / "never"), optional=True) is None
    with pytest.raises(cs.ColdError) as e:
        world["store"].ensure(str(world["home"] / "never"))
    assert e.value.code == cs.NOT_PARKED


def test_listing_shows_what_is_parked_and_falls_back_to_the_catalog_when_the_host_is_off(world):
    world["store"].park(world["data"])
    out = world["store"].listing()
    assert out["reachable"] and [e["name"] for e in out["parked"]] == ["eval-bench"]
    assert out["parked"][0]["here"] == "parked" and "mac-mini-1" in out["free_gb"]
    (world["bin"] / "DOWN").touch()
    out = world["store"].listing()
    assert not out["reachable"] and [e["name"] for e in out["parked"]] == ["eval-bench"]
    assert "manifest" not in out["parked"][0]


def test_the_remote_hasher_is_the_same_code_as_the_local_one(world):
    world["store"].park(world["data"])
    assert world["store"].remote_manifest("eval-bench") == cs.build_manifest(str(world["cold"] / "eval-bench" / "data"))


def test_ensure_of_a_path_inside_a_parked_folder_fetches_just_that_part(world, tmp_path):
    before = _tree(world["data"])
    world["store"].park(world["data"])
    inside = world["data"] / "models" / "release" / "he model"
    assert world["store"].ensure(str(inside)) == inside
    assert (inside / "weights.bin").read_bytes() == before["models/release/he model/weights.bin"]
    assert not (world["data"] / "models" / "big.bin").exists()
    # A folder that exists only because a part came back is not mistaken for the whole: the marker still rules.
    assert world["store"].ensure(str(world["data"] / "models"), part="big.bin") == world["data"] / "models" / "big.bin"
    assert (world["data"] / "models" / "big.bin").read_bytes() == before["models/big.bin"]
    # Another machine (no marker, no catalog) asking for a path inside it.
    shutil.rmtree(world["data"])
    other = cs.Store(host="cold-host", host_id="mac-mini-2012", root=world["store"].root, machine="macbook-pro-1",
                     state_dir=tmp_path / "other-state", home=world["home"], ssh=world["store"].ssh, min_free_bytes=0,
                     say=lambda m: None)
    assert other.ensure(str(inside)) == inside
    assert sorted(p.name for p in world["data"].iterdir()) == [cs.MARKER_JSON, cs.MARKER_TXT, "models"]


def test_optional_lookup_with_the_cold_host_off_says_so_and_does_not_fail(world):
    (world["bin"] / "DOWN").touch()
    msgs = []
    world["store"].say = msgs.append
    assert world["store"].ensure(str(world["home"] / "gone"), optional=True) is None
    assert any("asleep or off" in m for m in msgs)
    with pytest.raises(cs.ColdError) as e:
        world["store"].ensure(str(world["home"] / "gone"))
    assert e.value.code == cs.UNREACHABLE


def test_the_cli_prints_the_path_and_returns_the_exit_code(world, monkeypatch, capsys):
    monkeypatch.setattr(cs, "default_store", lambda: (world["store"], {}))
    world["store"].park(world["data"])
    (world["bin"] / "DOWN").touch()
    assert cs.main(["ensure", str(world["data"])]) == cs.UNREACHABLE
    assert "asleep or off" in capsys.readouterr().err
    (world["bin"] / "DOWN").unlink()
    assert cs.main(["ensure", str(world["data"]), "--part", "results"]) == 0
    assert capsys.readouterr().out.strip() == str(world["data"] / "results")
    assert cs.main(["list"]) == 0 and "eval-bench" in capsys.readouterr().out


# ---- re-park (marvin#1271): what ensure brought back can go away again ------------------------------------------

def _local_files(world) -> list[str]:
    return sorted(str(p.relative_to(world["data"])) for p in world["data"].rglob("*")
                  if p.is_file() or p.is_symlink())


def _parked_only(world) -> None:
    assert sorted(p.name for p in world["data"].iterdir()) == [cs.MARKER_JSON, cs.MARKER_TXT]
    assert not list(world["home"].glob(".*cold*"))


def test_repark_after_a_partial_ensure_drops_the_fetched_part_and_keeps_every_unfetched_file(world):
    before = _tree(world["data"])
    first = world["store"].park(world["data"])
    world["store"].ensure(str(world["data"]), part="models")
    _rsync_wrapper(world, 'exec "$REAL" "$@"')
    again = world["store"].park(world["data"])
    _parked_only(world)
    assert again["manifest_sha256"] == first["manifest_sha256"]         # nothing changed: same manifest
    assert world["store"].marker(world["data"])["parts"] == []
    assert world["store"].ensure(str(world["data"])) == world["data"]
    assert _tree(world["data"]) == before                              # results/ and venv/ were never lost


def test_a_file_changed_after_ensure_is_kept_by_repark_and_returned_by_the_next_ensure(world):
    world["store"].park(world["data"])
    world["store"].ensure(str(world["data"]), part="results")
    (world["data"] / "results" / "run 203.jsonl").write_text('{"wer": 0.05}\n')
    new_dir = world["data"] / "results" / "new run" / "deep"
    new_dir.mkdir(parents=True)                                        # a new sub-folder the cold copy lacks
    (new_dir / "scores.json").write_text("[1, 2, 3]")
    os.symlink("scores.json", new_dir / "latest")                      # and a new link
    entry = world["store"].park(world["data"])
    _parked_only(world)
    marker = world["store"].marker(world["data"])
    assert marker["manifest_sha256"] == entry["manifest_sha256"]       # marker follows the new manifest
    assert world["store"].catalog("eval-bench")["manifest_sha256"] == entry["manifest_sha256"]
    assert json.loads((world["cold"] / "eval-bench" / "entry.json").read_text())["manifest_sha256"] == \
        entry["manifest_sha256"]
    world["store"].ensure(str(world["data"]))
    assert (world["data"] / "results" / "run 203.jsonl").read_text() == '{"wer": 0.05}\n'
    assert (new_dir / "scores.json").read_text() == "[1, 2, 3]"
    assert os.readlink(new_dir / "latest") == "scores.json"
    assert (world["data"] / "models" / "big.bin").stat().st_size == 300_000


def test_a_new_manifest_survives_a_lost_catalog(world):
    world["store"].park(world["data"])
    world["store"].ensure(str(world["data"]), part="results")
    (world["data"] / "results" / "run 203.jsonl").write_text("changed\n")
    world["store"].park(world["data"])
    shutil.rmtree(world["tmp"] / "state")                              # only the marker's sha is left to trust
    world["store"].ensure(str(world["data"]))
    assert (world["data"] / "results" / "run 203.jsonl").read_text() == "changed\n"


def test_a_file_deleted_inside_a_fetched_part_is_gone_from_the_cold_copy(world):
    world["store"].park(world["data"])
    world["store"].ensure(str(world["data"]), part="models")
    (world["data"] / "models" / "big.bin").unlink()
    world["store"].park(world["data"])
    assert not (world["cold"] / "eval-bench" / "data" / "models" / "big.bin").exists()
    world["store"].ensure(str(world["data"]))
    assert not (world["data"] / "models" / "big.bin").exists()
    assert (world["data"] / "results" / "run 203.jsonl").exists()


def test_files_written_next_to_the_marker_are_parked_too(world):
    world["store"].park(world["data"])
    (world["data"] / "notes.txt").write_text("written while parked")
    world["store"].park(world["data"])
    _parked_only(world)
    world["store"].ensure(str(world["data"]))
    assert (world["data"] / "notes.txt").read_text() == "written while parked"


def test_repark_of_a_folder_in_use_is_refused_and_moves_nothing(world):
    world["store"].park(world["data"])
    world["store"].ensure(str(world["data"]), part="models")
    held = _local_files(world)
    world["store"].in_use = lambda p: ["python3 4242"]
    with pytest.raises(cs.ColdError) as e:
        world["store"].park(world["data"])
    assert e.value.code == cs.BUSY
    assert _local_files(world) == held


def test_repark_refuses_when_the_cold_manifest_does_not_match_the_marker(world):
    world["store"].park(world["data"])
    world["store"].ensure(str(world["data"]), part="models")
    held = _tree(world["data"])
    mf = world["cold"] / "eval-bench" / "manifest.json"
    m = json.loads(mf.read_text())
    m["files"]["results/run 203.jsonl"][1] = "0" * 64
    mf.write_text(json.dumps(m))
    with pytest.raises(cs.ColdError) as e:
        world["store"].park(world["data"])
    assert e.value.code == cs.VERIFY_FAILED
    assert _tree(world["data"]) == held                                # local data never dropped


def test_repark_never_drops_a_local_file_the_cold_copy_has_lost(world):
    world["store"].park(world["data"])
    world["store"].ensure(str(world["data"]), part="models")
    shutil.rmtree(world["cold"] / "eval-bench" / "data" / "results")  # an un-fetched part lost at rest
    held = _tree(world["data"])
    with pytest.raises(cs.ColdError) as e:
        world["store"].park(world["data"])
    assert e.value.code == cs.VERIFY_FAILED and "results" in str(e.value)
    assert _tree(world["data"]) == held


def test_a_repark_interrupted_after_the_upload_is_finished_by_the_next_park_and_ensure_still_works(world):
    world["store"].park(world["data"])
    world["store"].ensure(str(world["data"]), part="results")
    (world["data"] / "results" / "run 203.jsonl").write_text("v2\n")
    real_write = world["store"]._remote_write
    calls = []

    def die_after_manifest(rpath, data):
        real_write(rpath, data)
        calls.append(rpath)
        if rpath.endswith("manifest.json"):
            raise cs.ColdError(cs.UNREACHABLE, "link dropped")
    world["store"]._remote_write = die_after_manifest
    with pytest.raises(cs.ColdError):
        world["store"].park(world["data"])
    assert (world["data"] / "results" / "run 203.jsonl").read_text() == "v2\n"     # nothing local lost
    # ensure in between: an un-changed part still comes back
    world["store"]._remote_write = real_write
    world["store"].ensure(str(world["data"]), part="venv")
    # and the user changes the file again before the next park: the half-written state must not block it
    (world["data"] / "results" / "run 203.jsonl").write_text("v3\n")
    world["store"].park(world["data"])
    _parked_only(world)
    world["store"].ensure(str(world["data"]))
    assert (world["data"] / "results" / "run 203.jsonl").read_text() == "v3\n"


def test_a_repark_interrupted_before_the_swap_still_lets_ensure_verify(world):
    world["store"].park(world["data"])
    world["store"].ensure(str(world["data"]), part="results")
    (world["data"] / "results" / "run 203.jsonl").write_text("v2\n")
    calls = []
    world["store"].in_use = lambda p: calls.append(p) or (["python3 4242"] if len(calls) > 1 else [])
    with pytest.raises(cs.ColdError) as e:                             # opened just before the swap
        world["store"].park(world["data"])
    assert e.value.code == cs.BUSY
    world["store"].in_use = lambda p: []
    world["store"].ensure(str(world["data"]))                           # marker and cold copy agree: verifies
    assert (world["data"] / "results" / "run 203.jsonl").read_text() == "v2\n"


def test_listing_shows_local_bytes_so_a_half_fetched_entry_is_visible(world):
    world["store"].park(world["data"])
    assert world["store"].listing()["parked"][0]["local_bytes"] == 0
    world["store"].ensure(str(world["data"]), part="models")
    assert world["store"].listing()["parked"][0]["local_bytes"] == 500_000


def test_fetched_context_parks_again_when_the_job_ends_even_if_it_fails(world):
    before = _tree(world["data"])
    world["store"].park(world["data"])
    with pytest.raises(RuntimeError):
        with world["store"].fetched(str(world["data"]), part="models") as got:
            assert (got / "big.bin").exists()
            raise RuntimeError("eval crashed")
    _parked_only(world)
    world["store"].ensure(str(world["data"]))
    assert _tree(world["data"]) == before


def test_cli_then_park_runs_the_command_with_its_flags_and_parks_the_whole_folder(world, monkeypatch, capfd):
    monkeypatch.setattr(cs, "default_store", lambda: (world["store"], {}))
    world["store"].park(world["data"])
    rc = cs.main(["ensure", str(world["data"]), "--part", "models", "--then-park", "--", "ls", "-la",
                  str(world["data"] / "models")])
    assert rc == 0 and "big.bin" in capfd.readouterr().out
    _parked_only(world)
    assert not (world["cold"] / "models").exists()                     # the parent was re-parked, not a new entry
    assert sorted(p.name for p in world["cold"].iterdir()) == ["eval-bench"]


def test_cli_then_park_keeps_the_commands_exit_code_and_survives_a_missing_command(world, monkeypatch, capsys):
    monkeypatch.setattr(cs, "default_store", lambda: (world["store"], {}))
    world["store"].park(world["data"])
    assert cs.main(["ensure", str(world["data"]), "--part", "models", "--then-park", "--", "sh", "-c",
                    "exit 3"]) == 3
    _parked_only(world)
    assert cs.main(["ensure", str(world["data"]), "--part", "models", "--then-park", "--",
                    "no-such-command-xyz"]) == 127
    _parked_only(world)


def test_cli_then_park_without_a_command_is_refused_before_anything_is_fetched(world, monkeypatch, capsys):
    monkeypatch.setattr(cs, "default_store", lambda: (world["store"], {}))
    world["store"].park(world["data"])
    assert cs.main(["ensure", str(world["data"]), "--then-park"]) == cs.NOT_PARKED
    _parked_only(world)
    assert cs.main(["ensure", str(world["data"]), "--", "ls"]) == cs.NOT_PARKED   # a command needs --then-park
    _parked_only(world)


def test_cli_a_failed_repark_after_a_failing_command_reports_both_and_keeps_the_commands_code(world, monkeypatch,
                                                                                            capsys):
    monkeypatch.setattr(cs, "default_store", lambda: (world["store"], {}))
    world["store"].park(world["data"])
    world["store"].in_use = lambda p: ["python3 4242"]
    assert cs.main(["ensure", str(world["data"]), "--part", "models", "--then-park", "--", "sh", "-c",
                    "exit 4"]) == 4
    assert "in use" in capsys.readouterr().err
    assert cs.main(["ensure", str(world["data"]), "--part", "models", "--then-park", "--", "true"]) == cs.BUSY
