"""The element pipeline: deploy/ -> dev site -> pages -> capture -> parity -> evaluation (lib/portfolio_sync_dev.py)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_sync_dev as sd  # noqa: E402


def _project(tmp_path):
    p = tmp_path / "proj"
    (p / "deploy/other-projects").mkdir(parents=True)
    (p / "deploy/mu-plugins").mkdir(parents=True)
    (p / "deploy/other-projects/other-projects.css").write_text("a{}")
    (p / "deploy/other-projects/project-card.html").write_text("<div/>")
    (p / "deploy/mu-plugins/enqueue-other-projects.php").write_text("<?php")
    return p


def test_sync_copies_only_files_that_differ_and_reports_them(tmp_path):
    proj, dev = _project(tmp_path), tmp_path / "dev"
    first = sd.sync_files(proj, dev)
    assert sorted(first) == ["mu-plugins/enqueue-other-projects.php", "other-projects/other-projects.css", "other-projects/project-card.html"]
    assert (dev / "wp-content/other-projects/other-projects.css").read_text() == "a{}"
    assert sd.sync_files(proj, dev) == []                                  # nothing changed -> nothing copied
    (proj / "deploy/other-projects/other-projects.css").write_text("a{color:red}")
    assert sd.sync_files(proj, dev) == ["other-projects/other-projects.css"]


def test_sync_never_writes_outside_the_dev_sites_wp_content(tmp_path):
    proj, dev = _project(tmp_path), tmp_path / "dev"
    sd.sync_files(proj, dev)
    written = {p.relative_to(dev).parts[0] for p in dev.rglob("*") if p.is_file()}
    assert written == {"wp-content"}
    assert not (tmp_path / "proj" / "wp-content").exists()


def _steps(**over):
    ok = lambda: (True, "fine")
    base = {"sync": ok, "pages": ok, "capture": ok, "parity": ok, "evaluate": ok}
    base.update(over)
    return base


def test_a_clean_run_records_every_step_and_is_ok(tmp_path):
    out = sd.run(tmp_path / "p", tmp_path / "d", tmp_path / "status.json", steps=_steps())
    assert out["ok"] and [s["name"] for s in out["steps"]] == ["sync", "pages", "capture", "parity", "evaluate"]
    assert json.loads((tmp_path / "status.json").read_text())["ok"] is True


def test_a_failing_check_is_recorded_and_makes_the_run_not_ok(tmp_path):
    out = sd.run(tmp_path / "p", tmp_path / "d", tmp_path / "s.json", steps=_steps(parity=lambda: (False, "card: title.fontFamily differs")))
    assert out["ok"] is False and next(s for s in out["steps"] if s["name"] == "parity")["detail"].startswith("card")
    assert len(out["steps"]) == 5                                          # checks all run: you see every problem at once


def test_a_failed_sync_or_page_rebuild_stops_before_measuring_a_half_updated_site(tmp_path):
    out = sd.run(tmp_path / "p", tmp_path / "d", tmp_path / "s.json", steps=_steps(pages=lambda: (False, "dev site down")))
    assert [s["name"] for s in out["steps"]] == ["sync", "pages"] and out["ok"] is False


def test_a_step_that_raises_is_a_failed_step_not_a_crashed_pipeline(tmp_path):
    def boom():
        raise RuntimeError("playwright missing")
    out = sd.run(tmp_path / "p", tmp_path / "d", tmp_path / "s.json", steps=_steps(capture=boom))
    step = next(s for s in out["steps"] if s["name"] == "capture")
    assert step["ok"] is False and "playwright missing" in step["detail"]


def test_deploy_pipeline_test_markers_are_not_copied_to_the_dev_site(tmp_path):
    proj, dev = _project(tmp_path), tmp_path / "dev"
    (proj / "deploy/mu-plugins/marvin-pipeline-test.php").write_text("<?php // marker")
    assert "mu-plugins/marvin-pipeline-test.php" not in sd.sync_files(proj, dev)
    assert not (dev / "wp-content/mu-plugins/marvin-pipeline-test.php").exists()


def test_the_evaluate_step_fails_on_errors_but_only_reports_warnings():
    # Content checks (ADR 0051) are heuristics that flag for a person; they must not turn the pipeline red.
    warn = {"rule": "copy-ai-phrase", "severity": "warning", "page": "/a/", "detail": "x"}
    err = {"rule": "page-overflow", "severity": "error", "page": "/b/", "detail": "y"}
    assert sd.judge_evaluation({"findings": []}) == (True, "no findings")
    ok, detail = sd.judge_evaluation({"findings": [warn, warn]})
    assert ok and "2 warning(s)" in detail
    ok, detail = sd.judge_evaluation({"findings": [warn, err]})
    assert not ok and "1 error(s)" in detail and "page-overflow" in detail
