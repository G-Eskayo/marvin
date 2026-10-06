"""The README audit (lib/readme_audit.py): mechanical checks against the criteria in docs/readme-criteria.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import readme_audit as ra  # noqa: E402

GOOD = """# Widget

Widget turns CSV files into charts so you can see trends without a spreadsheet.

![A bar chart produced by Widget from sales.csv](docs/images/chart.png)

Status: stable, used daily.

## Install

```bash
pip install widget
python scripts/make_chart.py sales.csv
```

## Usage

```python
import widget
widget.plot("sales.csv")
```

See [the design notes](docs/design.md) and the [license](LICENSE).
"""
TREE = {"README.md", "docs/images/chart.png", "docs/design.md", "scripts/make_chart.py", "LICENSE"}


def by(audit_result, check):
    return next(f for f in audit_result["findings"] if f["check"] == check)


def test_a_good_readme_has_no_failures():
    r = ra.audit(GOOD, TREE, {"description": "Charts from CSVs"})
    assert r["summary"]["fail"] == 0
    assert by(r, "visual-evidence")["status"] == "pass" and by(r, "commands-resolve")["status"] == "pass"


def test_no_picture_is_a_failure_of_the_show_dont_tell_goal():
    r = ra.audit(GOOD.replace("![A bar chart produced by Widget from sales.csv](docs/images/chart.png)\n", ""), TREE)
    assert by(r, "visual-evidence")["status"] == "fail"


def test_badges_do_not_count_as_visual_evidence():
    r = ra.audit("# X\n\nA tool that does things for people.\n\n![build](https://img.shields.io/badge/build-passing-green.svg)\n", set())
    assert by(r, "visual-evidence")["status"] == "fail"


def test_a_mermaid_diagram_counts_as_a_visual():
    r = ra.audit("# X\n\nA tool that does things.\n\n```mermaid\nflowchart LR\n  A-->B\n```\n", set())
    assert by(r, "visual-evidence")["status"] == "pass"


def test_images_need_alt_text_and_must_exist_in_the_repo():
    text = "# X\n\nA tool that does things for people.\n\n![](docs/images/missing.png)\n"
    r = ra.audit(text, {"README.md"})
    assert by(r, "alt-text")["status"] == "warn" and by(r, "images-exist")["status"] == "fail"


def test_a_command_that_names_a_missing_script_is_flagged():
    r = ra.audit("# X\n\nA tool for things.\n\n```bash\npython scripts/nope.py\nnpm run build\n```\n", {"README.md", "package.json"}, package_scripts={"test"})
    f = by(r, "commands-resolve")
    assert f["status"] == "fail" and any("nope.py" in e for e in f["evidence"]) and any("npm run build" in e for e in f["evidence"])


def test_relative_links_and_anchors_are_checked_against_the_repo():
    text = "# X\n\nA tool for things.\n\n## Usage\n\n[ok](docs/design.md) [bad](docs/gone.md) [anchor](#usage) [bad anchor](#nowhere)\n"
    f = by(ra.audit(text, {"README.md", "docs/design.md"}), "relative-links")
    assert f["status"] == "fail" and sorted(f["evidence"]) == ["#nowhere (no such heading)", "docs/gone.md"]


def test_external_links_use_the_status_function_and_unjudgeable_ones_are_not_failures():
    text = "# X\n\nA tool.\n\n[a](https://ok.example) [b](https://dead.example) [c](https://blocked.example)\n"
    codes = {"https://ok.example": 200, "https://dead.example": 404, "https://blocked.example": None}
    f = by(ra.audit(text, set(), status_of=codes.get), "external-links")
    assert f["status"] == "fail" and f["evidence"] == ["https://dead.example -> 404"]
    only_blocked = by(ra.audit("# X\n\n[c](https://blocked.example)\n", set(), status_of=codes.get), "external-links")
    assert only_blocked["status"] != "fail"


def test_links_inside_code_blocks_are_not_checked():
    text = "# X\n\nA tool for things.\n\n```markdown\n[example](nowhere.md)\n```\n"
    assert by(ra.audit(text, {"README.md"}), "relative-links")["status"] == "pass"


def test_docs_the_repo_has_but_the_readme_never_mentions_are_called_out():
    f = by(ra.audit("# X\n\nA tool for things.\n", {"README.md", "docs/a.md", "CONTRIBUTING.md", "LICENSE"}), "deeper-docs-reachable")
    assert f["status"] == "warn" and "docs" in f["message"] and "CONTRIBUTING" in f["message"] and "LICENSE" in f["message"]


def test_paths_named_in_the_text_must_exist():
    r = ra.audit("# X\n\nA tool for things. Config lives in `config/app.toml` and `lib/real.py`.\n", {"README.md", "lib/real.py"})
    f = by(r, "paths-exist")
    assert f["status"] == "fail" and f["evidence"] == ["config/app.toml"]


def test_counts_in_the_text_are_surfaced_for_verification():
    f = by(ra.audit("# X\n\nA tool with 27 skills and 23 tests.\n", set()), "numbers-to-verify")
    assert f["status"] == "info" and f["evidence"] == ["23 tests", "27 skills"]


def test_a_readme_left_behind_by_the_code_is_flagged_stale():
    meta = {"readme_commit_at": "2026-04-01T00:00:00Z", "repo_commit_at": "2026-10-05T00:00:00Z", "commits_since_readme": 99, "description": "d"}
    assert by(ra.audit("# X\n\nA tool for things.\n", set(), meta), "freshness")["status"] == "warn"
    fresh = dict(meta, readme_commit_at="2026-10-01T00:00:00Z", commits_since_readme=3)
    assert by(ra.audit("# X\n\nA tool for things.\n", set(), fresh), "freshness")["status"] == "pass"


def test_status_and_why_are_checked_because_studies_find_them_most_often_missing():
    r = ra.audit("# X\n\nX is a tool.\n", set())
    assert by(r, "status")["status"] == "warn" and by(r, "why")["status"] == "warn"


def test_a_long_readme_without_a_contents_list_is_flagged():
    long = "# X\n\nA tool for things.\n\n" + "\n".join(f"line {i}" for i in range(150))
    assert by(ra.audit(long, set()), "navigation-aid")["status"] == "warn"
    assert by(ra.audit("# X\n\nA tool for things.\n", set()), "navigation-aid")["status"] == "pass"


def test_goal_scores_are_pass_fractions_and_info_is_left_out():
    r = ra.audit(GOOD, TREE, {"description": "d"})
    assert set(r["score"]) == set(ra.GOALS) and all(0 <= v <= 1 for v in r["score"].values() if v is not None)


def test_anchor_of_matches_githubs_rule():
    assert ra.anchor_of("Quick Start: Install & Run!") == "quick-start-install--run"


def test_a_local_clone_can_be_audited_before_anything_is_pushed(tmp_path):
    import subprocess
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("x")
    (tmp_path / "README.md").write_text("# Local\n\nLocal is a tool that does a thing so you can do it faster.\n\n[docs](docs/a.md) [gone](docs/b.md)\n")
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    text, tree, meta, scripts = ra.fetch_local(str(tmp_path))
    assert "docs/a.md" in tree and scripts is None
    f = by(ra.audit(text, tree, meta), "relative-links")
    assert f["status"] == "fail" and f["evidence"] == ["docs/b.md"]


def test_a_head_404_is_confirmed_by_a_browser_get_before_a_link_counts_as_dead():
    import urllib.error
    import urllib.request
    import readme_audit as ra
    calls = []

    class Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def opener(req, timeout=10):
        calls.append(req.get_method())
        if req.get_method() == "HEAD":
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
        return Resp()

    assert ra.http_status("https://x/y", opener=opener) == 200 and calls == ["HEAD", "GET"]

    def always_404(req, timeout=10):
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)

    assert ra.http_status("https://x/y", opener=always_404) == 404


def test_percent_encoded_local_paths_resolve_to_files_with_spaces():
    import readme_audit as ra
    parsed = ra.parse("![alt](Confusion%20Matrix.jpg)\n\n[doc](docs/My%20Notes.md)\n")
    finds = {f.check: f for f in ra.check_prove(parsed, {"Confusion Matrix.jpg"})}
    assert finds["images-exist"].status == "pass"
