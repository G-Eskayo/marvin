"""model_cache (#1114): a project's gitignored models, fetched once per machine into a checked cache and linked into
each worktree. The tests try to break it: corrupt and partial caches, failed fetches, races, stale links."""
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_cache  # noqa: E402

LIB = Path(__file__).resolve().parents[1]


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=cwd, check=True,
                   capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """A worktree-like repo with a fetch script (the cache key) and a gitignored models folder."""
    r = tmp_path / "wt"
    (r / "scripts").mkdir(parents=True)
    (r / "scripts" / "fetch.sh").write_text("v1\n")
    (r / ".gitignore").write_text("App/Models/\n")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "init")
    return r


@pytest.fixture
def root(tmp_path):
    return tmp_path / "cache"


def fetcher(tmp_path, files=None, fail=False, empty=False):
    """A fetch command that counts its runs and writes `files` into $MODEL_CACHE_DEST."""
    counter = tmp_path / "fetches"
    files = files or {"weights.bin": "abc", "sub/config.json": "{}"}
    lines = [f"echo x >> {counter}"]
    if fail:
        lines += ["echo 'curl: (6) Could not resolve host' >&2", "exit 6"]
    elif not empty:
        for rel, body in files.items():
            lines += [f'mkdir -p "$MODEL_CACHE_DEST/{os.path.dirname(rel)}"', f"printf '{body}' > \"$MODEL_CACHE_DEST/{rel}\""]
    return ["bash", "-c", "\n".join(lines)], counter


def runs(counter):
    return len(counter.read_text().splitlines()) if counter.exists() else 0


def ensure(repo, root, fetch, targets=("App/Models/M",), keys=("scripts/fetch.sh",), name="M"):
    return model_cache.ensure(name, [repo / k for k in keys], [repo / t for t in targets], fetch, cwd=repo, root=root,
                              project="proj")


# ── the happy path ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_first_run_fetches_and_links_every_target(repo, root, tmp_path):
    fetch, counter = fetcher(tmp_path)
    ensure(repo, root, fetch, targets=("App/Models/M", "Mac/Models/M"))
    assert runs(counter) == 1
    for t in ("App/Models/M", "Mac/Models/M"):
        link = repo / t
        assert link.is_symlink()
        assert (link / "weights.bin").read_text() == "abc"
        assert (link / "sub" / "config.json").read_text() == "{}"


def test_second_run_never_calls_the_fetch(repo, root, tmp_path):
    fetch, counter = fetcher(tmp_path)
    ensure(repo, root, fetch)
    ensure(repo, root, fetch)
    assert runs(counter) == 1


def test_a_second_worktree_reuses_the_cache(repo, root, tmp_path):
    fetch, counter = fetcher(tmp_path)
    ensure(repo, root, fetch)
    other = tmp_path / "wt2"
    _git(repo, "worktree", "add", "-q", str(other))
    ensure(other, root, fetch)
    assert runs(counter) == 1
    assert (other / "App/Models/M/weights.bin").read_text() == "abc"


def test_a_changed_key_file_fetches_a_new_copy_and_keeps_the_old(repo, root, tmp_path):
    fetch, counter = fetcher(tmp_path)
    ensure(repo, root, fetch)
    old = (repo / "App/Models/M").resolve()
    (repo / "scripts" / "fetch.sh").write_text("v2\n")
    ensure(repo, root, fetch)
    assert runs(counter) == 2
    new = (repo / "App/Models/M").resolve()
    assert new != old
    assert (old / "weights.bin").exists()


def test_git_status_stays_clean(repo, root, tmp_path):
    fetch, _ = fetcher(tmp_path)
    ensure(repo, root, fetch, targets=("App/Models/M", "Elsewhere/M"))   # Elsewhere/ has no ignore rule
    out = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
    assert out == ""


# ── corrupt and partial caches ──────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("damage", ["delete", "resize", "extra", "manifest"])
def test_a_damaged_cache_is_fetched_again(repo, root, tmp_path, damage):
    fetch, counter = fetcher(tmp_path)
    ensure(repo, root, fetch)
    content = (repo / "App/Models/M").resolve()
    if damage == "delete":
        (content / "weights.bin").unlink()
    elif damage == "resize":
        (content / "weights.bin").write_text("abcdef")
    elif damage == "extra":
        (content / "stray.tmp").write_text("x")
    else:
        (content.parent / model_cache.MANIFEST).write_text("not json")
    ensure(repo, root, fetch)
    assert runs(counter) == 2
    assert (repo / "App/Models/M/weights.bin").read_text() == "abc"
    assert not (repo / "App/Models/M/stray.tmp").exists()


def test_a_staging_folder_left_by_a_killed_run_is_cleared(repo, root, tmp_path):
    fetch, counter = fetcher(tmp_path)
    key = model_cache.cache_key([repo / "scripts/fetch.sh"])
    stale = root / "proj" / "M" / f"{key}.partial-99999"
    (stale / "M").mkdir(parents=True)
    (stale / "M" / "half.bin").write_text("x")
    ensure(repo, root, fetch)
    assert runs(counter) == 1
    assert not stale.exists()
    assert not (repo / "App/Models/M/half.bin").exists()


def test_a_fetch_that_produced_nothing_is_an_error(repo, root, tmp_path):
    fetch, _ = fetcher(tmp_path, empty=True)
    with pytest.raises(model_cache.FetchFailed, match="produced no files"):
        ensure(repo, root, fetch)
    assert not (repo / "App/Models/M").exists()
    assert not list((root / "proj" / "M").glob("*.partial-*"))


def test_a_failed_fetch_says_which_model_and_why_and_caches_nothing(repo, root, tmp_path):
    fetch, _ = fetcher(tmp_path, fail=True)
    with pytest.raises(model_cache.FetchFailed) as e:
        ensure(repo, root, fetch)
    msg = str(e.value)
    assert "M" in msg and "exited 6" in msg and "Could not resolve host" in msg
    assert "by hand" in msg
    assert not (repo / "App/Models/M").exists()
    key_dirs = [p for p in (root / "proj" / "M").iterdir() if not p.name.startswith(".")]
    assert key_dirs == []


def test_a_failed_fetch_leaves_an_older_good_copy_alone(repo, root, tmp_path):
    fetch, _ = fetcher(tmp_path)
    ensure(repo, root, fetch)
    old = (repo / "App/Models/M").resolve()
    (repo / "scripts" / "fetch.sh").write_text("v2\n")
    bad, _ = fetcher(tmp_path, fail=True)
    with pytest.raises(model_cache.FetchFailed):
        ensure(repo, root, bad)
    assert (old / "weights.bin").read_text() == "abc"


def test_a_fetch_never_writes_through_an_existing_link_into_the_cache(repo, root, tmp_path):
    fetch, _ = fetcher(tmp_path)
    ensure(repo, root, fetch)
    old = (repo / "App/Models/M").resolve()
    (repo / "scripts" / "fetch.sh").write_text("v2\n")
    # A project fetch script that writes at the in-tree path (as Seal's diarizer script does) before moving it out.
    sneaky = ["bash", "-c", 'mkdir -p App/Models/M && echo overwritten > App/Models/M/weights.bin && '
                            'mv App/Models/M "$MODEL_CACHE_DEST"']
    ensure(repo, root, sneaky)
    assert (old / "weights.bin").read_text() == "abc"
    assert (repo / "App/Models/M/weights.bin").read_text().strip() == "overwritten"


def test_the_fetch_gets_an_empty_scratch_folder(repo, root, tmp_path):
    fetch = ["bash", "-c", 'test -d "$MODEL_CACHE_WORK" && test -z "$(ls -A "$MODEL_CACHE_WORK")" && '
                           'mkdir -p "$MODEL_CACHE_DEST" && echo ok > "$MODEL_CACHE_DEST/f"']
    ensure(repo, root, fetch)
    assert (repo / "App/Models/M/f").read_text().strip() == "ok"


# ── races ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_two_worktrees_at_once_fetch_once(repo, root, tmp_path):
    counter = tmp_path / "fetches"
    slow = ["bash", "-c", f"echo x >> {counter}; sleep 1; mkdir -p \"$MODEL_CACHE_DEST\"; echo hi > \"$MODEL_CACHE_DEST/w\""]
    other = tmp_path / "wt2"
    _git(repo, "worktree", "add", "-q", str(other))
    errors = []

    def go(w):
        try:
            ensure(w, root, slow)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=go, args=(w,)) for w in (repo, other)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == []
    assert runs(counter) == 1
    assert (repo / "App/Models/M/w").read_text().strip() == "hi"
    assert (other / "App/Models/M/w").read_text().strip() == "hi"


# ── targets ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_dangling_link_is_replaced(repo, root, tmp_path):
    fetch, _ = fetcher(tmp_path)
    (repo / "App/Models").mkdir(parents=True)
    (repo / "App/Models/M").symlink_to(tmp_path / "gone")
    ensure(repo, root, fetch)
    assert (repo / "App/Models/M/weights.bin").read_text() == "abc"


def test_a_real_folder_already_there_is_kept(repo, root, tmp_path):
    fetch, counter = fetcher(tmp_path)
    (repo / "App/Models/M").mkdir(parents=True)
    (repo / "App/Models/M/mine.bin").write_text("own copy")
    notes = ensure(repo, root, fetch)
    assert not (repo / "App/Models/M").is_symlink()
    assert (repo / "App/Models/M/mine.bin").read_text() == "own copy"
    assert any("kept" in n for n in notes)


def test_a_missing_key_file_is_a_clear_error(repo, root, tmp_path):
    fetch, counter = fetcher(tmp_path)
    with pytest.raises(model_cache.FetchFailed, match="nope.sha256"):
        ensure(repo, root, fetch, keys=("scripts/fetch.sh", "scripts/nope.sha256"))
    assert runs(counter) == 0


def test_a_target_outside_the_worktree_is_refused(repo, root, tmp_path):
    fetch, _ = fetcher(tmp_path)
    with pytest.raises(model_cache.FetchFailed, match="outside"):
        ensure(repo, root, fetch, targets=("../escape/M",))


# ── the command line the profile calls ──────────────────────────────────────────────────────────────────────────────

def test_cli_links_and_reports(repo, root, tmp_path):
    fetch, counter = fetcher(tmp_path)
    cmd = [sys.executable, str(LIB / "model_cache.py"), "link", "--project", "proj", "--name", "M", "--root", str(root),
           "--key", "scripts/fetch.sh", "--into", "App/Models/M", "--", *fetch]
    first = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    second = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
    assert second.returncode == 0
    assert runs(counter) == 1
    assert "cached" in second.stdout


def test_cli_failure_exits_non_zero_with_the_message(repo, root, tmp_path):
    fetch, _ = fetcher(tmp_path, fail=True)
    r = subprocess.run([sys.executable, str(LIB / "model_cache.py"), "link", "--project", "proj", "--name", "M",
                        "--root", str(root), "--key", "scripts/fetch.sh", "--into", "App/Models/M", "--", *fetch],
                       cwd=repo, capture_output=True, text=True)
    assert r.returncode == 1
    assert "Could not resolve host" in r.stderr


def test_cli_needs_a_fetch_command(repo, root):
    r = subprocess.run([sys.executable, str(LIB / "model_cache.py"), "link", "--project", "proj", "--name", "M",
                        "--key", "scripts/fetch.sh", "--into", "App/Models/M"], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 2
