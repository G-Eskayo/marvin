"""Tests for lib/pr_images.py: UI PRs carry current, working images (marvin #735). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_pr_images.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pr_images as pi  # noqa: E402

SHA = "a7174e5642d35c6272c1787ae7db24aa2015db34"
OLD = "1111111111111111111111111111111111111111"
RAW = f"https://raw.githubusercontent.com/G-Eskayo/marvin-voice/{SHA}/docs/images/pr/icon-light.png"


# ── which images a body shows ───────────────────────────────────────────────

def test_finds_markdown_and_html_images_but_not_plain_links_to_pictures():
    body = f"![light]({RAW})\n<img width=300 src=\"https://x.test/a.gif\">\n[a link](https://x.test/b.png)"
    assert pi.image_urls(body) == [RAW, "https://x.test/a.gif"]
    assert pi.image_urls("") == [] and pi.image_urls(None) == []


def test_a_markdown_image_with_a_title_or_angle_brackets_still_counts():
    assert pi.image_urls(f'![x](<{RAW}> "title")') == [RAW]


# ── links that break ────────────────────────────────────────────────────────

def test_an_image_pinned_to_a_full_commit_on_the_raw_host_is_fine():
    assert pi.link_problem(RAW) is None


def test_images_dragged_into_github_are_fine():
    assert pi.link_problem("https://github.com/user-attachments/assets/0b1c-2d3e") is None
    assert pi.link_problem("https://private-user-images.githubusercontent.com/1/2.png?jwt=x") is None


def test_a_blob_raw_true_link_is_refused_because_it_404s_for_private_repos():
    url = f"https://github.com/G-Eskayo/marvin-voice/blob/{SHA}/docs/images/pr/icon.png?raw=true"
    assert pi.link_problem(url) == "blob"


def test_an_image_linked_by_branch_name_is_refused_because_it_shows_whatever_is_newest():
    assert pi.link_problem("https://raw.githubusercontent.com/G-Eskayo/x/feat/2-icon/docs/a.png") == "branch"
    assert pi.link_problem("https://raw.githubusercontent.com/G-Eskayo/x/a7174e5/docs/a.png") == "branch"  # short SHA


def test_a_repo_relative_path_is_refused_because_it_doesnt_render_in_a_pr():
    assert pi.link_problem("docs/images/pr/a.png") == "relative"


def test_pinned_commits_come_from_raw_links_only():
    body = f"![a]({RAW})\n![b](https://raw.githubusercontent.com/o/r/{OLD}/x.png)\n![c](https://x.test/c.png)"
    assert pi.pinned_shas(pi.image_urls(body)) == {SHA, OLD}


# ── the verdict ─────────────────────────────────────────────────────────────

def codes(problems):
    return [c for c, _ in problems]


def test_a_change_that_doesnt_touch_the_look_needs_no_images():
    assert pi.verdict(["lib/x.py", "docs/a.md"], "no pictures") == []


def test_a_ui_change_with_no_image_is_refused_and_says_which_files():
    problems = pi.verdict(["site/gift.html", "lib/x.py"], "words only")
    assert codes(problems) == ["NO_UI_EVIDENCE"]
    assert "site/gift.html" in problems[0][1] and "pr-shots" in problems[0][1]


def test_the_projects_own_ui_paths_count():
    files = ["App/Sources/MenuBarIcon.swift"]
    assert pi.verdict(files, "none") == []
    assert codes(pi.verdict(files, "none", extra_patterns=["App/Sources/**/*.swift"])) == ["NO_UI_EVIDENCE"]


def test_a_ui_change_with_a_broken_link_is_refused_naming_the_link():
    body = f"![x](https://github.com/o/r/blob/{SHA}/a.png?raw=true)"
    problems = pi.verdict(["a/View.swift", "a/MainView.swift"], body)
    assert codes(problems) == ["BAD_IMAGE_LINK"]
    assert "?raw=true" in problems[0][1]


def test_images_older_than_a_later_ui_change_are_stale():
    changed_since = {SHA: ["site/index.html"]}.get
    problems = pi.verdict(["site/index.html"], f"![x]({RAW})", changed_since=changed_since)
    assert codes(problems) == ["STALE_UI_EVIDENCE"]
    assert "site/index.html" in problems[0][1]


def test_images_are_current_when_only_non_ui_files_or_the_images_changed_since():
    changed_since = {SHA: ["lib/x.py", "docs/images/pr/a.png"]}.get
    assert pi.verdict(["site/index.html"], f"![x]({RAW})", changed_since=changed_since) == []


def test_with_several_pinned_commits_the_newest_one_decides():
    body = f"![x]({RAW})\n![y](https://raw.githubusercontent.com/o/r/{OLD}/b.png)"
    changed_since = {SHA: [], OLD: ["site/index.html"]}.get
    assert pi.verdict(["site/index.html"], body, changed_since=changed_since) == []


def test_staleness_cant_be_judged_without_pinned_commits_so_dragged_images_pass():
    body = "![x](https://github.com/user-attachments/assets/abc)"
    assert pi.verdict(["site/index.html"], body, changed_since=lambda s: ["site/index.html"]) == []


def test_when_github_cant_say_what_changed_since_the_images_it_isnt_called_stale():
    assert pi.verdict(["site/index.html"], f"![x]({RAW})", changed_since=lambda s: None) == []


# ── which gh calls are checked ──────────────────────────────────────────────

def test_parses_pr_create_with_its_repo_branches_and_body():
    call = pi.parse_pr_call(["pr", "create", "-R", "o/r", "--draft", "--base", "main", "--head", "feat/x",
                             "--title", "t", "--body", "hi ![a](b)"])
    assert call == {"action": "create", "repo": "o/r", "base": "main", "head": "feat/x", "body": "hi ![a](b)",
                    "body_file": None, "target": None}


def test_parses_the_long_and_equals_forms_and_a_body_file(tmp_path):
    call = pi.parse_pr_call(["pr", "create", "--repo=o/r", "--body-file", "/tmp/b.md", "--title=t"])
    assert (call["repo"], call["body_file"], call["head"]) == ("o/r", "/tmp/b.md", None)


def test_parses_merge_and_ready_with_their_target():
    assert pi.parse_pr_call(["pr", "merge", "173", "-R", "o/r", "--merge"])["target"] == "173"
    assert pi.parse_pr_call(["pr", "ready", "https://github.com/o/r/pull/9"])["action"] == "ready"


def test_other_calls_are_not_checked():
    assert pi.parse_pr_call(["pr", "view", "9"]) is None
    assert pi.parse_pr_call(["pr", "edit", "9", "--body-file", "b"]) is None
    assert pi.parse_pr_call(["issue", "create"]) is None
    assert pi.parse_pr_call(["pr", "create", "--help"]) is None
    assert pi.parse_pr_call([]) is None


def test_the_shots_section_is_replaced_not_duplicated():
    first = pi.with_shots_section("Intro.\n\n## Decisions\nx", "![a](u1)")
    assert first.count(pi.SHOTS_START) == 1 and "![a](u1)" in first
    assert first.index("![a](u1)") < first.index("## Decisions")
    second = pi.with_shots_section(first, "![b](u2)")
    assert second.count(pi.SHOTS_START) == 1 and "u1" not in second and "![b](u2)" in second
    assert "## Decisions" in second and second.startswith("Intro.")


def test_the_shots_section_goes_at_the_end_when_there_are_no_decisions():
    assert pi.with_shots_section("Intro.", "![a](u)").startswith("Intro.\n\n" + pi.SHOTS_START)
