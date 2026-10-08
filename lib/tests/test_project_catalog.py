"""Tests for project_catalog.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_project_catalog.py -v
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import project_catalog as pc  # noqa: E402

NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)


def iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def gh_repo(name, days=1, vis="PUBLIC", archived=False, desc="", lang=None, topics=()):
    return {"name": name, "description": desc, "visibility": vis, "isArchived": archived, "pushedAt": iso(days),
            "primaryLanguage": {"name": lang} if lang else None,
            "repositoryTopics": [{"name": t} for t in topics]}


def local(path, origin=None, days=1, context=False, readme=False, adr=0, worktree=False):
    return {"path": path, "name": Path(path).name, "origin": origin, "last_activity": iso(days), "worktree": worktree,
            "docs": {"context": context, "readme": readme, "adrCount": adr}}


def build(github=(), locals_=(), manifest=(), memory=(), overrides=None, boards=()):
    return pc.build_catalog(list(github), list(locals_), list(manifest), list(memory), overrides or {}, set(boards), now=NOW)


def by_id(cat, pid):
    return next(p for p in cat["projects"] if p["id"] == pid)


# ── matching portfolio entries to repos ────────────────────────────────────

def entry(url, title="T", cat="AI & Machine Learning"):
    return {"title": title, "url": url, "category": cat, "description": ""}


def test_tokens_drop_noise_words_and_split_on_punctuation():
    assert pc.tokens("ML_supervised_learning-Regression-Classification-project") == {"supervised", "learning", "regression", "classification"}


def test_portfolio_entries_match_the_most_similar_repo_one_to_one():
    repos = ["resume-tailor", "ML-Powered-Resume-Selector-using-Naive-Bayes", "AI-algorithms", "Autonomous-Marketplace-Flipper"]
    entries = [entry("/ai-projects/resume-selector/"), entry("/ai-projects/resume-tailor/"),
               entry("/ai-projects/algorithms/"), entry("/ai-projects/marketplace-ml-agent/"), entry("/ai-projects/mancala/")]
    m = pc.match_portfolio(entries, repos)
    assert m["/ai-projects/resume-selector/"] == "ML-Powered-Resume-Selector-using-Naive-Bayes"
    assert m["/ai-projects/resume-tailor/"] == "resume-tailor"
    assert m["/ai-projects/algorithms/"] == "AI-algorithms"
    assert m["/ai-projects/marketplace-ml-agent/"] == "Autonomous-Marketplace-Flipper"
    assert "/ai-projects/mancala/" not in m


def test_a_repo_is_claimed_by_only_one_portfolio_entry():
    m = pc.match_portfolio([entry("/a/resume-tailor/"), entry("/b/resume-tailor-2/")], ["resume-tailor"])
    assert list(m.values()) == ["resume-tailor"]


# ── status ──────────────────────────────────────────────────────────────────

def test_status_comes_from_last_activity_and_archived_flag():
    assert pc.derive_status(iso(3), False, NOW) == "active"
    assert pc.derive_status(iso(90), False, NOW) == "recent"
    assert pc.derive_status(iso(400), False, NOW) == "dormant"
    assert pc.derive_status(iso(1), True, NOW) == "archived"
    assert pc.derive_status(None, False, NOW) == "dormant"


# ── building the catalog ────────────────────────────────────────────────────

def test_a_repo_with_a_local_clone_is_one_record_with_the_clone_attached():
    cat = build([gh_repo("clarity-captions")], [local("/h/Developer/clarity-captions", "clarity-captions", context=True, readme=True, adr=14)])
    assert [p["id"] for p in cat["projects"]] == ["clarity-captions"]
    p = by_id(cat, "clarity-captions")
    assert p["kind"] == "repo" and p["repo"] == "G-Eskayo/clarity-captions"
    assert p["localPaths"] == ["/h/Developer/clarity-captions"]
    assert p["docs"] == {"context": True, "readme": True, "adrCount": 14}


def test_several_clones_list_the_newest_first():
    cat = build([gh_repo("p")], [local("/old/p", "p", days=30), local("/new/p", "p", days=1)])
    assert by_id(cat, "p")["localPaths"] == ["/new/p", "/old/p"]


def test_a_local_folder_without_a_repo_is_its_own_local_project():
    cat = build([], [local("/h/Documents/Projects/Aero Heaven", None, days=200)])
    p = by_id(cat, "aero-heaven")
    assert p["kind"] == "local" and p["repo"] is None and p["status"] == "dormant"
    assert p["name"] == "Aero Heaven"


def test_repos_with_no_clone_still_appear_with_github_facts():
    cat = build([gh_repo("MechanicGPT", days=130, vis="PRIVATE", desc="car stuff", lang="Python", topics=["llm"])])
    p = by_id(cat, "mechanicgpt")
    assert p["localPaths"] == [] and p["visibility"] == "PRIVATE" and p["status"] == "recent"
    assert {"lang:python", "topic:llm", "kind:repo"} <= set(p["tags"])


def test_portfolio_entries_attach_to_matching_repos_and_unmatched_ones_become_projects():
    manifest = [entry("/ai-projects/algorithms/", "Algorithms in Python"), entry("/ai-projects/mancala/", "Mancala Game AI")]
    cat = build([gh_repo("AI-algorithms")], [], manifest)
    assert by_id(cat, "ai-algorithms")["portfolio"]["url"] == "/ai-projects/algorithms/"
    m = by_id(cat, "portfolio:mancala")
    assert m["kind"] == "portfolio-only" and m["name"] == "Mancala Game AI" and "kind:portfolio-only" in m["tags"]


def test_memory_notes_that_mention_a_project_become_pointers():
    memory = [{"file": "project-clarity-captions.md", "text": "---\nname: x\n---\nMom's captioning app clarity-captions"},
              {"file": "feedback-other.md", "text": "nothing relevant"}]
    cat = build([gh_repo("clarity-captions")], [], [], memory)
    assert by_id(cat, "clarity-captions")["memory"] == ["project-clarity-captions.md"]


def test_overrides_win_and_can_hide_a_project():
    overrides = {"mechanicgpt": {"name": "Mechanic GPT", "tags": ["automotive"], "status": "dormant", "notes": "paused"},
                 "personal-website": {"ignore": True},
                 "ai-algorithms": {"portfolio": "/ai-projects/algorithms/"}}
    cat = build([gh_repo("MechanicGPT", days=2), gh_repo("Personal-Website"), gh_repo("AI-algorithms")], [],
                [entry("/ai-projects/algorithms/", "Algorithms in Python")], overrides=overrides)
    p = by_id(cat, "mechanicgpt")
    assert p["name"] == "Mechanic GPT" and p["status"] == "dormant" and "automotive" in p["tags"] and p["notes"] == "paused"
    assert all(x["id"] != "personal-website" for x in cat["projects"])
    assert by_id(cat, "ai-algorithms")["portfolio"]["title"] == "Algorithms in Python"


def test_override_aliases_extend_memory_matching():
    memory = [{"file": "project-portfolio-updater.md", "text": "x"}]
    cat = build([gh_repo("portfolio-website-updater")], [], [], memory, overrides={"portfolio-website-updater": {"aliases": ["portfolio-updater"]}})
    assert by_id(cat, "portfolio-website-updater")["memory"] == ["project-portfolio-updater.md"]


def test_boards_are_flagged_and_tagged():
    cat = build([gh_repo("marvin")], [], [], boards={"G-Eskayo/marvin"})
    p = by_id(cat, "marvin")
    assert p["board"] is True and "has:board" in p["tags"]


def test_every_record_carries_a_project_card():
    cat = build([gh_repo("marvin", desc="MARVIN")], [local("/h/.agents", "marvin", context=True)], [entry("/ai-projects/marvin/", "MARVIN")])
    card = by_id(cat, "marvin")["summary_md"]
    assert card.startswith("# marvin") and "G-Eskayo/marvin" in card and "/ai-projects/marvin/" in card and "/h/.agents" in card


# ── the master doc ──────────────────────────────────────────────────────────

def test_master_section_groups_projects_by_status_and_lists_where_each_lives():
    cat = build([gh_repo("marvin", days=1), gh_repo("old", days=500)], [local("/h/.agents", "marvin", context=True)],
                [entry("/ai-projects/mancala/", "Mancala Game AI")])
    md = pc.render_master(cat)
    assert "## Projects" in md
    assert md.index("### Active") < md.index("### Dormant")
    assert "marvin" in md and "/h/.agents" in md and "G-Eskayo/marvin" in md
    assert "### Portfolio only" in md and "Mancala Game AI" in md


# ── persistence / freshness ────────────────────────────────────────────────

def test_write_and_read_roundtrip_and_staleness(tmp_path):
    cat = build([gh_repo("marvin")])
    path = tmp_path / "projects.dev.json"
    pc.write_catalog(cat, path)
    assert pc.read_catalog(path)["projects"][0]["id"] == "marvin"
    assert pc.is_stale(path, max_age_s=3600, now=NOW) is False
    assert pc.is_stale(path, max_age_s=3600, now=NOW + timedelta(hours=2)) is True
    assert pc.is_stale(tmp_path / "missing.json", max_age_s=3600, now=NOW) is True


def test_a_failed_discovery_keeps_the_last_good_catalog(tmp_path):
    path = tmp_path / "projects.dev.json"
    pc.write_catalog(build([gh_repo("marvin")]), path)

    def boom():
        raise RuntimeError("offline")

    out = pc.refresh(path=path, github=boom, local=lambda: [], manifest=lambda: [], memory=lambda: [],
                     overrides=lambda: {}, boards=lambda: set(), now=NOW)
    assert out["ok"] is False
    assert pc.read_catalog(path)["projects"][0]["id"] == "marvin"


def test_overrides_file_is_read_tolerantly(tmp_path):
    assert pc.load_overrides(tmp_path / "none.json") == {}
    bad = tmp_path / "o.json"
    bad.write_text("{nope")
    assert pc.load_overrides(bad) == {}
    good = tmp_path / "g.json"
    good.write_text(json.dumps({"marvin": {"tags": ["x"]}}))
    assert pc.load_overrides(good)["marvin"]["tags"] == ["x"]


def test_overrides_ignore_comment_keys_and_non_object_entries(tmp_path):
    f = tmp_path / "o.json"
    f.write_text(json.dumps({"_readme": "notes for humans", "marvin": {"tags": ["x"]}, "junk": 5}))
    assert pc.load_overrides(f) == {"marvin": {"tags": ["x"]}}


def test_run_environment_has_homebrew_on_path_and_the_shared_gh_token(monkeypatch, tmp_path):
    token = tmp_path / ".gh-token"
    token.write_text("tok123\n")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    env = pc.run_env(token_file=token)
    assert "/opt/homebrew/bin" in env["PATH"].split(":")
    assert env["GH_TOKEN"] == "tok123"
    monkeypatch.setenv("GH_TOKEN", "explicit")
    assert pc.run_env(token_file=token)["GH_TOKEN"] == "explicit"


def test_refresh_reports_each_phase_with_counts(tmp_path):
    steps = []
    out = pc.refresh(path=tmp_path / "p.json", github=lambda: [gh_repo("a"), gh_repo("b")], local=lambda: [], manifest=lambda: [entry("/x/m/")],
                     memory=lambda: [], overrides=lambda: {}, boards=lambda: set(), now=NOW, report=lambda step, detail="": steps.append((step, detail)))
    assert out["ok"] is True
    names = [s for i, (s, _) in enumerate(steps) if i == 0 or steps[i - 1][0] != s]  # collapse start/done pairs
    assert names[:5] == ["GitHub repos", "Local folders", "Portfolio manifest", "Memory notes", "Boards"]
    assert names[-1] == "Writing catalog"
    assert ("GitHub repos", "2 found") in steps
    assert out["count"] == 3  # 2 repos + 1 portfolio-only


def test_refresh_names_the_phase_that_failed(tmp_path):
    steps = []

    def boom():
        raise RuntimeError("rate limited")

    out = pc.refresh(path=tmp_path / "p.json", github=boom, local=lambda: [], manifest=lambda: [], memory=lambda: [],
                     overrides=lambda: {}, boards=lambda: set(), now=NOW, report=lambda s, d="": steps.append(s))
    assert out["ok"] is False and "GitHub repos" in out["error"] and "rate limited" in out["error"]


# ── portfolio_repo_path lookup ──────────────────────────────────────────────

def test_portfolio_repo_path_env_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVIN_PORTFOLIO_PATH", "/override/path")
    assert pc.portfolio_repo_path() == Path("/override/path")


def test_portfolio_repo_path_uses_catalog_local_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("MARVIN_PORTFOLIO_PATH", raising=False)
    cat_path = tmp_path / "catalog.json"
    cat_path.write_text(json.dumps({
        "projects": [
            {"id": "portfolio-website-updater", "localPaths": ["/catalog/portfolio-path"]},
        ]
    }))
    monkeypatch.setattr("project_catalog.catalog_path", lambda: cat_path)
    assert pc.portfolio_repo_path() == Path("/catalog/portfolio-path")


def test_portfolio_repo_path_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.delenv("MARVIN_PORTFOLIO_PATH", raising=False)
    cat_path = tmp_path / "catalog.json"
    cat_path.write_text(json.dumps({"projects": []}))
    monkeypatch.setattr("project_catalog.catalog_path", lambda: cat_path)
    assert pc.portfolio_repo_path() == pc._PORTFOLIO_DEFAULT


def test_no_hardcoded_portfolio_path_outside_default_fallback():
    import re
    import subprocess
    lib_dir = Path(__file__).resolve().parents[1]
    # any hard-coded location (the old iCloud ~/Documents/Projects one, or ~/Developer since #192)
    result = subprocess.run(["grep", "-rE", r'(\"Documents\"\s*/\s*\"Projects\"|\"Developer\")\s*/\s*\"portfolio-website-updater\"', ".",
                             "--include=*.py", "--exclude-dir=__pycache__"], cwd=lib_dir,
                            capture_output=True, text=True)
    lines = [l for l in result.stdout.split("\n") if l.strip()]
    assert len(lines) == 1 and "_PORTFOLIO_DEFAULT" in lines[0], f"Expected exactly one occurrence in _PORTFOLIO_DEFAULT, found: {lines}"


# ── one real copy per project, and a map you can click (2026-10-07) ─────────

H = str(pc.HOME)


def test_primary_copy_prefers_a_full_clone_in_developer_over_icloud_and_worktrees():
    cat = build(github=[gh_repo("clarity-captions")], locals_=[
        local(f"{H}/Developer/clarity-demo-wt", origin="clarity-captions", days=0, worktree=True),
        local(f"{H}/Documents/Projects/clarity-captions", origin="clarity-captions", days=1),
        local(f"{H}/Developer/clarity-captions", origin="clarity-captions", days=2)])
    p = by_id(cat, "clarity-captions")
    assert p["primaryPath"] == f"{H}/Developer/clarity-captions"
    assert p["localPaths"][0] == p["primaryPath"]  # everything that takes "the" path takes the primary


def test_primary_copy_override_wins():
    cat = build(github=[gh_repo("app")], locals_=[local(f"{H}/Developer/app", origin="app"),
                                                  local(f"{H}/Documents/Projects/app", origin="app")],
                overrides={"app": {"primaryPath": f"{H}/Documents/Projects/app"}})
    assert by_id(cat, "app")["primaryPath"] == f"{H}/Documents/Projects/app"


def test_primary_copy_is_none_without_a_local_folder():
    assert by_id(build(github=[gh_repo("remote-only")]), "remote-only")["primaryPath"] is None


def test_master_links_each_project_to_docs_and_to_its_folder_and_names_other_copies():
    cat = build(github=[gh_repo("clarity-captions")], locals_=[
        local(f"{H}/Developer/clarity-captions", origin="clarity-captions", context=True),
        local(f"{H}/Documents/Projects/clarity-captions", origin="clarity-captions")])
    md = pc.render_master(cat)
    assert "[Docs](dash://doc/clarity-captions/CONTEXT.md)" in md
    assert f"[Open folder](file://{H}/Developer/clarity-captions)" in md
    assert f"other copies: [Projects/clarity-captions](file://{H}/Documents/Projects/clarity-captions)" in md


def test_master_links_readme_when_there_is_no_context_and_nothing_when_no_docs():
    cat = build(github=[gh_repo("a"), gh_repo("b")], locals_=[local(f"{H}/Developer/a", origin="a", readme=True),
                                                              local(f"{H}/Developer/b", origin="b")])
    md = pc.render_master(cat)
    assert "[Docs](dash://doc/a/README.md)" in md
    assert "dash://doc/b/" not in md


def test_file_links_escape_spaces():
    cat = build(locals_=[local(f"{H}/Documents/Projects/My App")])
    assert f"(file://{H}/Documents/Projects/My%20App)" in pc.render_master(cat)
