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


def test_find_chrome_returns_the_first_browser_that_exists(tmp_path):
    real = tmp_path / "Chrome"; real.write_text("")
    assert pd.find_chrome([tmp_path / "missing", real]) == real
    assert pd.find_chrome([tmp_path / "missing"]) is None


def test_render_builds_one_mermaid_command_per_source_into_the_figures_folder(tmp_path):
    project = make_project(tmp_path)
    pd.new(project, "my-tool", ["setup", "run"])
    calls = []
    def runner(cmd, **kw):
        calls.append(cmd)
        Path(cmd[cmd.index("-o") + 1]).write_text("<svg/>")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    out = pd.render(project, "my-tool", runner=runner, chrome=Path("/Applications/Chrome"))
    figures = project / "deploy" / "longform" / "figures" / "my-tool"
    assert sorted(p.name for p in out) == ["run.svg", "setup.svg"] and all(p.parent == figures for p in out)
    cmd = calls[0]
    assert "@mermaid-js/mermaid-cli@11" in " ".join(cmd) and cmd[cmd.index("-c") + 1].endswith("theme.json")
    assert cmd[cmd.index("-b") + 1] == "white" and "-p" in cmd


def test_render_reports_which_diagram_failed(tmp_path):
    project = make_project(tmp_path)
    pd.new(project, "my-tool", ["run"])
    bad = lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="Parse error on line 2")
    try:
        pd.render(project, "my-tool", runner=bad, chrome=Path("/x"))
    except pd.DiagramError as e:
        assert "run.mmd" in str(e) and "Parse error" in str(e)
    else:
        raise AssertionError("expected DiagramError")
