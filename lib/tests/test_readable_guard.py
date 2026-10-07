"""readable_guard: decide, without hanging, whether tests that read another repo on disk can run here.

Found 2026-10-06: on the mac-mini, ~/Documents is an iCloud File Provider folder. A launchd process (the
merge gate, the pipeline) sees the portfolio repo's files exist, but open() blocks forever, so pytest hung
at collection for hours and every merge queued behind it.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import readable_guard as rg  # noqa: E402


def test_a_readable_file_is_readable(tmp_path):
    f = tmp_path / "templates.json"
    f.write_text("{}")
    assert rg.readable_within(f, seconds=5) is True


def test_a_missing_file_is_not_readable(tmp_path):
    assert rg.readable_within(tmp_path / "nope.json", seconds=5) is False


def test_a_read_that_blocks_counts_as_unreadable_and_returns_in_time(tmp_path):
    # A FIFO with no writer blocks open() for reading, the same way the iCloud file did.
    fifo = tmp_path / "blocks"
    os.mkfifo(fifo)
    import time
    start = time.monotonic()
    assert rg.readable_within(fifo, seconds=1) is False
    assert time.monotonic() - start < 5


def test_test_files_that_read_the_portfolio_repo_are_recognised():
    assert rg.reads_portfolio_repo('import portfolio_templates as pt\n')
    assert rg.reads_portfolio_repo('from portfolio_eval import rules\n')
    assert rg.reads_portfolio_repo('FIGS = Path.home() / "Documents" / "Projects" / "portfolio-website-updater" / "deploy"\n')


def test_a_test_that_only_names_the_repo_is_not_caught():
    # test_project_catalog uses the repo's name as sample data; it never reads the repo.
    assert not rg.reads_portfolio_repo('build([gh_repo("portfolio-website-updater")], [], [])\n')
