"""The house diagram kit for portfolio pages (lib/portfolio_diagrams.py, ADR 0051)."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_diagrams as pd  # noqa: E402


def make_project(tmp_path):
    kit = tmp_path / "templates" / "diagrams"
    kit.mkdir(parents=True)
    (kit / "theme.json").write_text('{"theme": "base"}')
    for k in ("setup", "run", "marvin"):
        (kit / f"{k}.mmd").write_text(f"flowchart TD\n  A[{k}] --> B")
    return tmp_path


def test_new_copies_the_chosen_starters_and_never_overwrites(tmp_path):
    project = make_project(tmp_path)
    made = pd.new(project, "my-tool", ["setup", "run"])
    target = project / "docs" / "diagrams" / "my-tool"
    assert sorted(p.name for p in made) == ["run.mmd", "setup.mmd"] and (target / "setup.mmd").read_text().startswith("flowchart")
    (target / "setup.mmd").write_text("edited")
    pd.new(project, "my-tool", ["setup"])
    assert (target / "setup.mmd").read_text() == "edited"


def test_render_reuses_render_diagrams_with_every_source_for_the_page(tmp_path):
    project = make_project(tmp_path)
    pd.new(project, "my-tool", ["setup", "run"])
    seen = {}
    def renderer(diagrams, out_dir):
        seen.update(diagrams); seen["out"] = out_dir
        return {n: Path(out_dir) / f"{n}.svg" for n in diagrams}
    out = pd.render(project, "my-tool", renderer=renderer)
    figures = project / "deploy" / "longform" / "figures" / "my-tool"
    assert sorted(p.name for p in out) == ["run.svg", "setup.svg"] and seen["out"] == figures
    assert seen["setup"].startswith("flowchart")


def test_render_reports_which_page_had_no_sources(tmp_path):
    project = make_project(tmp_path)
    try:
        pd.render(project, "nothing-here", renderer=lambda d, o: {})
    except pd.DiagramError as e:
        assert "nothing-here" in str(e)
    else:
        raise AssertionError("expected DiagramError")
