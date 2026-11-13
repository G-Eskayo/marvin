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
    def changed_since(pin):
        return ["site/index.html"] if pin.get("sha") == SHA else None
    problems = pi.verdict(["site/index.html"], f"![x]({RAW})", changed_since=changed_since)
    assert codes(problems) == ["STALE_UI_EVIDENCE"]
    assert "site/index.html" in problems[0][1]


def test_images_are_current_when_only_non_ui_files_or_the_images_changed_since():
    def changed_since(pin):
        return ["lib/x.py", "docs/images/pr/a.png"] if pin.get("sha") == SHA else None
    assert pi.verdict(["site/index.html"], f"![x]({RAW})", changed_since=changed_since) == []


def test_with_several_pinned_commits_if_any_is_stale_the_pr_is_stale():
    body = f"![x]({RAW})\n![y](https://raw.githubusercontent.com/o/r/{OLD}/b.png)"
    def changed_since(pin):
        if pin.get("sha") == SHA:
            return []
        elif pin.get("sha") == OLD:
            return ["site/index.html"]
        return None
    problems = pi.verdict(["site/index.html"], body, changed_since=changed_since)
    assert codes(problems) == ["STALE_UI_EVIDENCE"]


def test_staleness_cant_be_judged_without_pinned_commits_so_dragged_images_pass():
    body = "![x](https://github.com/user-attachments/assets/abc)"
    assert pi.verdict(["site/index.html"], body, changed_since=lambda s: ["site/index.html"]) == []


def test_when_github_cant_say_what_changed_since_the_images_the_pr_fails_closed():
    problems = pi.verdict(["site/index.html"], f"![x]({RAW})", changed_since=lambda p: None, fail_closed=True)
    assert codes(problems) == ["UI_EVIDENCE_UNCHECKED"]


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


# ── image_pins ──────────────────────────────────────────────────────────────

def test_image_pins_extracts_owner_repo_and_sha_from_raw_links():
    body = f"![a]({RAW})\n![b](https://raw.githubusercontent.com/o/r/{OLD}/x.png)"
    pins = pi.image_pins(body)
    assert len(pins) == 2
    assert pins[0] == {"repo": "G-Eskayo/marvin-voice", "sha": SHA}
    assert pins[1] == {"repo": "o/r", "sha": OLD}


def test_image_pins_ignores_non_pinned_images():
    body = f"![a]({RAW})\n![b](https://github.com/user-attachments/assets/abc)\n![c](https://raw.githubusercontent.com/o/r/feat-x/x.png)"
    pins = pi.image_pins(body)
    assert len(pins) == 1 and pins[0]["sha"] == SHA


def test_image_pins_deduplicates_same_repo_and_sha():
    body = f"![a]({RAW})\n![b]({RAW})"
    pins = pi.image_pins(body)
    assert len(pins) == 1


# ── parse_pr_url ────────────────────────────────────────────────────────────

def test_parses_pr_url_into_owner_repo_number():
    url = "https://github.com/G-Eskayo/marvin/pull/42"
    result = pi.parse_pr_url(url)
    assert result == {"owner": "G-Eskayo", "repo": "marvin", "number": "42"}


def test_parse_pr_url_rejects_invalid_urls():
    assert pi.parse_pr_url("not a url") is None
    assert pi.parse_pr_url("https://github.com/o/r/issues/42") is None
    assert pi.parse_pr_url("https://github.com/o/r") is None


# ── make_changed_since ──────────────────────────────────────────────────────

def test_make_changed_since_builds_a_callable_that_compares_commits():
    def ask_gh(args):
        if args[:2] == ["api", f"repos/o/r/compare/{SHA}...{OLD}"]:
            return {"files": [{"filename": "a.js"}, {"filename": "b.js"}]}
        return {"files": []}

    changed_since = pi.make_changed_since("o/r", OLD, ask_gh)
    assert changed_since({"repo": "o/r", "sha": SHA}) == ["a.js", "b.js"]


def test_make_changed_since_returns_none_on_error():
    def ask_gh(args):
        raise Exception("offline")

    changed_since = pi.make_changed_since("o/r", OLD, ask_gh)
    assert changed_since({"repo": "o/r", "sha": SHA}) is None


# ── CLI entry point ─────────────────────────────────────────────────────────

def test_cli_main_requires_check_subcommand_with_url():
    rc = pi.main(["check"])
    assert rc == 2  # missing URL argument


def test_check_pr_with_good_images():
    """check_pr returns [] when a PR with UI changes has current pinned images (including cross-repo pins)."""
    def ask_gh(args):
        if args[:2] == ["pr", "view"]:
            return {"files": [{"path": "site/page.html"}], "body": f"![x]({RAW})", "headRefOid": "f" * 40}
        # Must compare in the pin's repo (G-Eskayo/marvin-voice), not the PR's repo (o/r)
        if args[:2] == ["api", f"repos/G-Eskayo/marvin-voice/compare/{SHA}...{'f' * 40}"]:
            return {"files": []}  # no changes since the image
        raise AssertionError(f"unexpected call: {args}")

    result = pi.check_pr(f"https://github.com/o/r/pull/42", None, ask_gh, None)
    assert result == []


def test_check_pr_with_no_images_fails():
    """check_pr returns a refusal when UI changes have no images."""
    def ask_gh(args):
        if args[:2] == ["pr", "view"]:
            return {"files": [{"path": "site/page.html"}], "body": "no pictures", "headRefOid": "f" * 40}
        raise AssertionError(args)

    result = pi.check_pr(f"https://github.com/o/r/pull/42", None, ask_gh, None)
    assert len(result) == 1
    assert result[0][0] == "NO_UI_EVIDENCE"


def test_check_pr_invalid_url_fails_open_by_default():
    """check_pr returns [] for invalid URLs when strict=False (default)."""
    def ask_gh(args):
        raise AssertionError("should not call gh")

    result = pi.check_pr("not-a-url", None, ask_gh, None, strict=False)
    assert result == []


def test_check_pr_invalid_url_throws_when_strict():
    """check_pr throws for invalid URLs when strict=True."""
    def ask_gh(args):
        raise AssertionError("should not call gh")

    try:
        pi.check_pr("not-a-url", None, ask_gh, None, strict=True)
        assert False, "should have raised"
    except ValueError as e:
        assert "Invalid PR URL" in str(e)


def test_check_pr_github_offline_fails_open_by_default():
    """check_pr returns [] when GitHub is offline and strict=False (default)."""
    def ask_gh(args):
        raise RuntimeError("offline")

    result = pi.check_pr(f"https://github.com/o/r/pull/42", None, ask_gh, None, strict=False)
    assert result == []


def test_check_pr_github_offline_throws_when_strict():
    """check_pr throws when GitHub is offline and strict=True."""
    def ask_gh(args):
        raise RuntimeError("offline")

    try:
        pi.check_pr(f"https://github.com/o/r/pull/42", None, ask_gh, None, strict=True)
        assert False, "should have raised"
    except RuntimeError:
        pass  # expected


def test_check_pr_cross_repo_pin_fails_open_by_default():
    """check_pr returns [] for cross-repo pins when strict=False (fail open), since we can't check them."""
    def ask_gh(args):
        if args[:2] == ["pr", "view"]:
            return {"files": [{"path": "site/page.html"}], "body": f"![x]({RAW})", "headRefOid": "f" * 40}
        # We don't even try to compare cross-repo pins
        raise AssertionError(f"unexpected call: {args}")

    result = pi.check_pr(f"https://github.com/o/r/pull/42", None, ask_gh, None, strict=False)
    assert result == []


def test_check_pr_cross_repo_pin_fails_strict():
    """check_pr fails strictly when a cross-repo pin can't be checked."""
    def ask_gh(args):
        if args[:2] == ["pr", "view"]:
            return {"files": [{"path": "site/page.html"}], "body": f"![x]({RAW})", "headRefOid": "f" * 40}
        # Strict mode fails closed: we try to check but can't
        raise RuntimeError("404")

    result = pi.check_pr(f"https://github.com/o/r/pull/42", None, ask_gh, None, strict=True)
    assert codes(result) == ["UI_EVIDENCE_UNCHECKED"]


def test_verdict_skips_stale_check_when_changed_since_returns_none_and_fail_closed_is_false():
    """verdict with fail_closed=False skips stale check when changed_since fails."""
    def changed_since(pin):
        return None  # Can't check
    problems = pi.verdict(["site/index.html"], f"![x]({RAW})", changed_since=changed_since, fail_closed=False)
    assert codes(problems) == []


def test_verdict_fails_when_changed_since_returns_none_and_fail_closed_is_true():
    """verdict with fail_closed=True (default) fails when changed_since returns None."""
    def changed_since(pin):
        return None  # Can't check
    problems = pi.verdict(["site/index.html"], f"![x]({RAW})", changed_since=changed_since, fail_closed=True)
    assert codes(problems) == ["UI_EVIDENCE_UNCHECKED"]
