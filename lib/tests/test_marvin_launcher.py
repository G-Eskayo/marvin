"""MARVIN launcher v1 (marvin#302, ADR 0059): the one way a model run starts."""
import json
import subprocess
from pathlib import Path

import pytest

import marvin_launcher as ml

AGENTS = Path(__file__).resolve().parents[2]


@pytest.fixture
def memory(tmp_path, monkeypatch):
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "MEMORY.md").write_text("# Memory Index\n- [Robust](robust.md) — robust over quick\n")
    (mem / "robust.md").write_text(
        "---\nname: robust\ndescription: robust over quick\nmetadata:\n  type: feedback\n  tags: [work-rule]\n---\n\n"
        "Prefer the robust tool.\n")
    (mem / "trivia.md").write_text("---\nname: trivia\nmetadata:\n  type: project\n---\n\nSome project fact.\n")
    lex = tmp_path / "lexicon.md"
    lex.write_text("# Shared Lexicon\n- **wire** — symlink a skill\n")
    monkeypatch.setattr(ml, "MEMORY_DIR", mem)
    monkeypatch.setattr(ml, "LEXICON", lex)
    return mem


class FakeRun:
    def __init__(self, stdout=None, returncode=0):
        self.calls = []
        self.stdout = stdout if stdout is not None else json.dumps(
            {"result": "done", "total_cost_usd": 0.25, "usage": {"input_tokens": 10, "output_tokens": 20,
                                                                  "cache_read_input_tokens": 5, "cache_creation_input_tokens": 7}})
        self.returncode = returncode

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout, "")


def test_every_glossary_launch_kind_is_declared_and_nothing_else():
    assert set(ml.KINDS) == {"interactive", "ticket-planner", "ticket-executor", "background-analyst",
                             "utility-call", "judge"}
    context_md = (AGENTS / "CONTEXT.md").read_text()
    for kind in ml.KINDS.values():
        assert f"**{kind.title}**" in context_md, f"{kind.title} is not in the glossary"


def test_unknown_kind_is_refused():
    with pytest.raises(KeyError):
        ml.assemble_context("chat")


def test_planner_gets_north_stars_full_memory_index_and_lexicon(memory):
    ctx = ml.assemble_context("ticket-planner")
    assert "MARVIN raises the human experience" in ctx
    assert "robust over quick" in ctx  # the memory index
    assert "**wire**" in ctx


def test_executor_gets_the_work_rules_slice_and_lexicon_but_not_the_north_stars_or_index(memory):
    ctx = ml.assemble_context("ticket-executor")
    assert "Prefer the robust tool." in ctx
    assert "Some project fact." not in ctx
    assert "**wire**" in ctx
    assert "MARVIN raises the human experience" not in ctx
    assert "# Memory Index" not in ctx


def test_every_tagged_work_rule_reaches_the_executor(memory):
    # The probe from the glossary: a rule tagged work-rule that doesn't reach the executor is a failure.
    (memory / "tests-first.md").write_text("---\nname: tests-first\nmetadata:\n  tags: [work-rule, other]\n---\n\nWrite the test first.\n")
    ctx = ml.assemble_context("ticket-executor")
    for note in ml.work_rule_notes():
        assert note.read_text().split("---", 2)[2].strip() in ctx


def test_judge_and_utility_calls_get_no_marvin_layers(memory):
    for kind in ("judge", "utility-call"):
        ctx = ml.assemble_context(kind)
        assert "MARVIN raises" not in ctx and "robust" not in ctx and "**wire**" not in ctx


def test_the_real_memory_has_work_rules_tagged():
    # Guards against the slice silently going empty on a real machine.
    if not ml.MEMORY_DIR.exists():
        pytest.skip("no MARVIN memory on this machine")
    assert len(ml.work_rule_notes()) >= 4


def test_launch_runs_claude_with_the_kind_marker_context_and_leash(memory, tmp_path):
    fake = FakeRun()
    result = ml.launch("ticket-executor", "Implement it.", cwd=tmp_path, model="haiku",
                       allowed_tools="Read,Edit", disallowed_tools="Write(~/x/**)", timeout=5,
                       log_path=tmp_path / "launches.jsonl", runner=fake)
    (cmd, kw), = fake.calls
    assert cmd[1:3] == ["-p", cmd[2]] and cmd[2].endswith("Implement it.")
    assert "Prefer the robust tool." in cmd[2]
    assert cmd[cmd.index("--model") + 1] == "haiku"
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert cmd[cmd.index("--allowedTools") + 1] == "Read,Edit"
    assert cmd[cmd.index("--disallowedTools") + 1] == "Write(~/x/**)"
    assert cmd[-2:] == ["--output-format", "json"]
    assert kw["cwd"] == tmp_path and kw["timeout"] == 5
    assert kw["env"]["MARVIN_LAUNCH_KIND"] == "ticket-executor"
    assert (result.text, result.cost_usd) == ("done", 0.25)


def test_launch_records_the_run_for_metrics_and_health(memory, tmp_path):
    log = tmp_path / "launches.jsonl"
    ml.launch("ticket-planner", "Plan it.", cwd=tmp_path, model="sonnet", allowed_tools="Read", timeout=5,
              log_path=log, runner=FakeRun(), ticket="G-Eskayo/marvin#302")
    rec = json.loads(log.read_text().splitlines()[-1])
    assert rec["kind"] == "ticket-planner" and rec["model"] == "sonnet" and rec["ticket"] == "G-Eskayo/marvin#302"
    assert rec["input_tokens"] == 10 and rec["output_tokens"] == 20 and rec["cache_read_tokens"] == 5
    assert rec["cache_write_tokens"] == 7
    assert rec["cost_usd"] == 0.25 and rec["exit_code"] == 0 and rec["context_chars"] > 0


def test_a_failed_preflight_spends_no_tokens(memory, tmp_path):
    fake = FakeRun()

    def preflight():
        raise RuntimeError("preflight: wrong branch")

    with pytest.raises(RuntimeError, match="wrong branch"):
        ml.launch("ticket-executor", "x", cwd=tmp_path, model="haiku", allowed_tools="Read", timeout=5,
                  log_path=tmp_path / "l.jsonl", runner=fake, preflight=preflight)
    assert fake.calls == []


def test_non_json_output_comes_back_as_text(memory, tmp_path):
    result = ml.launch("utility-call", "x", cwd=tmp_path, model="haiku", allowed_tools="", timeout=5,
                       log_path=tmp_path / "l.jsonl", runner=FakeRun(stdout="plain"))
    assert (result.text, result.cost_usd) == ("plain", 0.0)


def test_the_pipeline_planner_and_executor_go_through_the_launcher():
    src = (AGENTS / "lib/sandbox_orchestration.py").read_text()
    assert '["claude", "-p"' not in src
    assert "marvin_launcher" in src
