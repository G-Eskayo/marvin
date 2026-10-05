"""generated_paths: files a tool regenerates (graphify-out/, package-lock.json) must not make PRs conflict."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import generated_paths as gp  # noqa: E402

RULES = [{"path": "graphify-out"},
         {"path": "package-lock.json", "unless": "package.json", "regenerate": ["sh", "-c", "echo regenerated > package-lock.json"]}]


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout


# ── pure rules ───────────────────────────────────────────────────────────────

def test_a_path_is_generated_if_it_is_the_file_or_inside_the_directory():
    assert gp.is_generated("graphify-out/graph.json", RULES)
    assert gp.is_generated("package-lock.json", RULES)
    assert not gp.is_generated("graphify-outer/x", RULES) and not gp.is_generated("src/a.js", RULES)


def test_the_lockfile_is_only_generated_when_package_json_did_not_change():
    assert gp.generated_among(["package-lock.json", "src/a.js"], RULES) == ["package-lock.json"]
    assert gp.generated_among(["package-lock.json", "package.json"], RULES) == []   # a real dependency change keeps its lockfile
    assert gp.generated_among(["graphify-out/a", "package.json", "package-lock.json"], RULES) == ["graphify-out/a"]


def test_no_rules_means_nothing_is_generated():
    assert gp.generated_among(["graphify-out/a"], []) == []


# ── keeping them out of a commit ─────────────────────────────────────────────

@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@t.com"); git(tmp_path, "config", "user.name", "T")
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "graph.json").write_text("base\n")
    (tmp_path / "package-lock.json").write_text("lock-base\n")
    (tmp_path / "package.json").write_text("{}\n")
    (tmp_path / "src.js").write_text("a\n")
    git(tmp_path, "add", "-A"); git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def test_unstaging_leaves_real_changes_staged_and_generated_ones_out(repo):
    (repo / "src.js").write_text("b\n")
    (repo / "graphify-out" / "graph.json").write_text("regenerated\n")
    (repo / "graphify-out" / "new.html").write_text("x\n")
    (repo / "package-lock.json").write_text("lock-changed\n")
    git(repo, "add", "-A")
    out = gp.unstage_generated(repo, RULES)
    staged = git(repo, "diff", "--cached", "--name-only").split()
    assert staged == ["src.js"]
    assert sorted(out) == ["graphify-out/graph.json", "graphify-out/new.html", "package-lock.json"]


def test_a_dependency_change_keeps_both_package_json_and_its_lockfile(repo):
    (repo / "package.json").write_text('{"dependencies":{"x":"1"}}\n')
    (repo / "package-lock.json").write_text("lock-with-x\n")
    git(repo, "add", "-A")
    gp.unstage_generated(repo, RULES)
    assert sorted(git(repo, "diff", "--cached", "--name-only").split()) == ["package-lock.json", "package.json"]


# ── resolving a rebase that conflicts only in generated files ────────────────

def _diverge(repo, branch_edits, main_edits):
    git(repo, "checkout", "-q", "-b", "feature")
    for p, text in branch_edits.items():
        (repo / p).write_text(text)
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "feature")
    git(repo, "checkout", "-q", "main")
    for p, text in main_edits.items():
        (repo / p).write_text(text)
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "main moved")
    git(repo, "checkout", "-q", "feature")


def test_a_rebase_conflicting_only_in_generated_files_is_resolved_and_regenerated(repo):
    _diverge(repo, {"src.js": "feature work\n", "graphify-out/graph.json": "feature graph\n", "package-lock.json": "lock-feature\n"},
             {"graphify-out/graph.json": "main graph\n", "package-lock.json": "lock-main\n"})
    assert subprocess.run(["git", "rebase", "main"], cwd=repo, capture_output=True).returncode != 0
    res = gp.resolve_rebase(repo, RULES)
    assert res["ok"], res
    assert (repo / "src.js").read_text() == "feature work\n"                      # the real change survives
    assert (repo / "graphify-out" / "graph.json").read_text() == "main graph\n"   # generated: main's copy wins
    assert (repo / "package-lock.json").read_text() == "regenerated\n"            # and the regenerate command ran
    assert "rebase" not in git(repo, "status").lower() or "no rebase" in git(repo, "status").lower() or not (repo / ".git" / "rebase-merge").exists()


def test_a_real_code_conflict_is_not_papered_over(repo):
    _diverge(repo, {"src.js": "feature\n", "graphify-out/graph.json": "f\n"}, {"src.js": "main\n", "graphify-out/graph.json": "m\n"})
    assert subprocess.run(["git", "rebase", "main"], cwd=repo, capture_output=True).returncode != 0
    res = gp.resolve_rebase(repo, RULES)
    assert not res["ok"] and "src.js" in res["reason"]
    assert not (repo / ".git" / "rebase-merge").exists()  # left clean: the rebase was aborted


# ── a PR whose change to a file is ALREADY on main (parallel PRs that each added the same thing) ──

def _write_lines(repo, name, lines):
    (repo / name).write_text("\n".join(lines) + "\n")


def test_a_conflict_where_main_already_contains_the_prs_change_takes_mains_copy(repo):
    _write_lines(repo, "pkg.txt", ["a", "b", "c", "d"]); git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "pkg")
    git(repo, "checkout", "-q", "-b", "feature")
    _write_lines(repo, "pkg.txt", ["a", "B", "c", "d"]); (repo / "src.js").write_text("feature work\n")
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "feature: b->B and real work")
    git(repo, "checkout", "-q", "main")
    _write_lines(repo, "pkg.txt", ["a", "B", "C", "d"])      # main made the SAME change to b, plus a neighbouring one
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "main: b->B and c->C")
    git(repo, "checkout", "-q", "feature")
    assert subprocess.run(["git", "rebase", "main"], cwd=repo, capture_output=True).returncode != 0
    res = gp.resolve_rebase(repo, RULES)
    assert res["ok"], res
    assert (repo / "pkg.txt").read_text() == "a\nB\nC\nd\n"        # main's copy, nothing of the PR's lost
    assert (repo / "src.js").read_text() == "feature work\n"        # the PR's real work survives
    assert "pkg.txt" in res.get("already_on_base", [])


def test_a_conflict_where_the_pr_has_its_own_different_change_is_not_resolved(repo):
    _write_lines(repo, "pkg.txt", ["a", "b", "c", "d"]); git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "pkg")
    git(repo, "checkout", "-q", "-b", "feature")
    _write_lines(repo, "pkg.txt", ["a", "MINE", "c", "d"]); git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "feature")
    git(repo, "checkout", "-q", "main")
    _write_lines(repo, "pkg.txt", ["a", "THEIRS", "C", "d"]); git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "main")
    git(repo, "checkout", "-q", "feature")
    assert subprocess.run(["git", "rebase", "main"], cwd=repo, capture_output=True).returncode != 0
    res = gp.resolve_rebase(repo, RULES)
    assert not res["ok"] and "pkg.txt" in res["reason"]
    assert not (repo / ".git" / "rebase-merge").exists()


def test_a_commit_that_becomes_empty_is_dropped_not_a_failure(repo):
    _write_lines(repo, "pkg.txt", ["a", "b", "c", "d"]); git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "pkg")
    git(repo, "checkout", "-q", "-b", "feature")
    _write_lines(repo, "pkg.txt", ["a", "B", "c", "d"]); git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "feature only changes b")
    git(repo, "checkout", "-q", "main")
    _write_lines(repo, "pkg.txt", ["a", "B", "C", "d"]); git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "main")
    git(repo, "checkout", "-q", "feature")
    assert subprocess.run(["git", "rebase", "main"], cwd=repo, capture_output=True).returncode != 0
    res = gp.resolve_rebase(repo, RULES)
    assert res["ok"], res
    assert git(repo, "log", "--oneline", "main..HEAD").strip() == ""   # nothing left of the PR's commit: it was all on main already
