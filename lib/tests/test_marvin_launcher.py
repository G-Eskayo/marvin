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


# ── marvin#303: every model run goes through the launcher ──────────────────────

import re as _re

# Deliberate exceptions, each with its reason. Anything else that starts `claude -p` fails the guard.
_EXEMPT = {
    "bench": "measurement harness: compares profiles, including a no-MARVIN control, on purpose",
    "lib/dispatch_ticket.sh": "manual ad hoc dispatch to another machine, kept outside the pipeline (ticket_pipeline docstring)",
}
_RAW_CALL_PY = _re.compile(r'''\[\s*(["']claude["']|claude_bin\w*)\s*,\s*["']-p["']''')
_RAW_CALL_SH = _re.compile(r"^\s*claude -p ", _re.M)


def _sources():
    for path in AGENTS.rglob("*"):
        rel = path.relative_to(AGENTS).as_posix()
        if path.suffix not in {".py", ".sh"} or not path.is_file():
            continue
        if any(part in {"tests", "test", "node_modules", "venv", ".venv", "graphify-out"} for part in path.parts):
            continue
        if any(rel == e or rel.startswith(e + "/") for e in _EXEMPT) or rel == "lib/marvin_launcher.py":
            continue
        yield rel, path


def test_no_model_run_starts_outside_the_launcher():
    offenders = [rel for rel, path in _sources()
                 if (_RAW_CALL_SH if path.suffix == ".sh" else _RAW_CALL_PY).search(path.read_text(errors="ignore"))]
    assert offenders == [], f"start these through marvin_launcher.launch with a launch kind: {offenders}"


def test_the_phone_chat_runs_as_an_interactive_launch():
    src = (AGENTS / "dashboard/mobile-backend/session_runner.js").read_text()
    assert "MARVIN_LAUNCH_KIND" in src and "'interactive'" in src


@pytest.mark.parametrize("module_path, kind", [
    ("skills/improve/scripts/daily_digest.py", "background-analyst"),
    ("skills/research-colony/scripts/research_digest.py", "background-analyst"),
    ("skills/self-improve/scripts/background_review.py", "background-analyst"),
    ("skills/architecture-review/scripts/background_architecture_review.py", "background-analyst"),
    ("skills/improve/scripts/auto_fix.py", "background-analyst"),
    ("lib/ticket_promotion.py", "background-analyst"),
    ("lib/disk_forecast_notify.py", "utility-call"),
    ("lib/mr_notification.py", "utility-call"),
    ("skills/handoff/scripts/generate_handoff_from_transcript.py", "utility-call"),
    ("skills/safety-monitor/scripts/verify.py", "judge"),
])
def test_each_caller_declares_its_launch_kind(module_path, kind):
    src = (AGENTS / module_path).read_text()
    assert _re.search(rf'''launch\(\s*["']{kind}["']''', src), f"{module_path} should launch as {kind}"


def test_a_judge_runs_in_an_empty_folder_of_its_own(memory, tmp_path):
    fake = FakeRun()
    ml.launch("judge", "score it", tools="", log_path=tmp_path / "l.jsonl", runner=fake)
    (cmd, kw), = fake.calls
    assert kw["cwd"] and "marvin-judge-" in kw["cwd"]
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--model" not in cmd  # left to the caller


def test_a_reported_error_counts_as_a_failed_run(memory, tmp_path):
    fake = FakeRun(stdout=json.dumps({"result": "boom", "is_error": True}))
    assert ml.launch("utility-call", "x", log_path=tmp_path / "l.jsonl", runner=fake).exit_code == 1


# --- #597: every launch records WHY it exited, so the non-zero rate can be broken down in Vitals ---

class FakeRunErr(FakeRun):
    def __init__(self, stdout, stderr="", returncode=1):
        super().__init__(stdout=stdout, returncode=returncode)
        self.stderr = stderr

    def __call__(self, cmd, **kw):
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout, self.stderr)


def _cause(tmp_path, runner):
    log = tmp_path / "c.jsonl"
    try:
        ml.launch("utility-call", "x", log_path=log, runner=runner)
    except subprocess.TimeoutExpired:
        pass
    return json.loads(log.read_text().splitlines()[-1])


def test_a_clean_run_records_cause_ok(memory, tmp_path):
    assert _cause(tmp_path, FakeRun())["exit_cause"] == "ok"


@pytest.mark.parametrize("text", [
    "You've hit your session limit · resets 12:10am (America/Denver)",
    "Claude AI usage limit reached|1760000000",
    "You've hit your weekly limit",
    "HTTP 429 rate limit exceeded",
    "YOU'VE HIT YOUR SESSION LIMIT",
])
def test_usage_limit_text_is_classified_whatever_channel_carries_it(memory, tmp_path, text):
    in_result = FakeRunErr(json.dumps({"result": text, "is_error": True}), returncode=1)
    in_stderr = FakeRunErr("", stderr=text, returncode=1)
    assert _cause(tmp_path, in_result)["exit_cause"] == "usage-limit"
    assert _cause(tmp_path, in_stderr)["exit_cause"] == "usage-limit"


def test_a_timeout_is_recorded_not_lost_and_still_raises(memory, tmp_path):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 5)
    log = tmp_path / "t.jsonl"
    with pytest.raises(subprocess.TimeoutExpired):
        ml.launch("ticket-planner", "x", timeout=5, log_path=log, runner=boom, ticket="G-Eskayo/marvin#1")
    rec = json.loads(log.read_text())
    assert rec["exit_cause"] == "timeout" and rec["exit_code"] != 0 and rec["ticket"] == "G-Eskayo/marvin#1"


def test_overload_and_unknown_model_are_model_unavailable(memory, tmp_path):
    assert _cause(tmp_path, FakeRunErr("", stderr="API Error: 529 overloaded_error"))["exit_cause"] == "model-unavailable"
    assert _cause(tmp_path, FakeRunErr("", stderr="model: claude-x not_found_error"))["exit_cause"] == "model-unavailable"


def test_empty_garbage_or_signal_death_is_a_crash(memory, tmp_path):
    assert _cause(tmp_path, FakeRunErr("", stderr="", returncode=1))["exit_cause"] == "crash"
    assert _cause(tmp_path, FakeRunErr("\x00\xff garbage", stderr="Traceback", returncode=1))["exit_cause"] == "crash"
    assert _cause(tmp_path, FakeRunErr("", stderr="", returncode=-9))["exit_cause"] == "crash"


def test_a_reported_error_that_is_not_a_limit_is_an_error_not_a_crash(memory, tmp_path):
    rec = _cause(tmp_path, FakeRunErr(json.dumps({"result": "Reached max turns", "is_error": True}), returncode=0))
    assert rec["exit_code"] == 1 and rec["exit_cause"] == "error"


def test_a_successful_run_that_merely_mentions_a_limit_is_still_ok(memory, tmp_path):
    ok = FakeRun(stdout=json.dumps({"result": "I added a usage limit check", "total_cost_usd": 0.1}))
    assert _cause(tmp_path, ok)["exit_cause"] == "ok"


def test_classify_survives_non_string_input():
    assert ml.classify_exit(1, None, None) == "crash"
    assert ml.classify_exit(0, None, None) == "ok"
