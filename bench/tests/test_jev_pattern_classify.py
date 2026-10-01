"""Tests for jev_pattern_classify.py. Run via:
    ~/.agents/venv/bin/python -m pytest bench/tests/test_jev_pattern_classify.py -v
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))

import jev_pattern_classify as jpc  # noqa: E402


class _FakeProc:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _result_line(**overrides):
    ev = {"type": "result", "total_cost_usd": 0.01, "duration_ms": 1500,
          "structured_output": {"choice": "coding", "confidence": 0.9}}
    ev.update(overrides)
    return json.dumps(ev)


def test_classify_jev_parses_a_successful_result():
    stdout = "\n".join([
        '{"type": "system", "subtype": "init"}',
        _result_line(),
    ])
    fake_run = lambda cmd, **kw: _FakeProc(stdout)
    out = jpc.classify_jev("fix the bug", run=fake_run)
    assert out == {"choice": "coding", "confidence": 0.9,
                    "cost_usd": 0.01, "latency_s": 1.5, "error": None}


def test_classify_jev_passes_the_description_into_the_prompt():
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _FakeProc(_result_line())

    jpc.classify_jev("what did we decide last time", run=fake_run)
    assert "what did we decide last time" in captured["cmd"][2]


def test_classify_jev_uses_zero_tools_and_haiku():
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _FakeProc(_result_line())

    jpc.classify_jev("anything", run=fake_run)
    cmd = captured["cmd"]
    assert "--tools" in cmd and cmd[cmd.index("--tools") + 1] == ""
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == jpc.MODEL
    assert "--json-schema" in cmd


def test_classify_jev_handles_missing_structured_output():
    stdout = json.dumps({"type": "result", "total_cost_usd": 0.005,
                          "duration_ms": 800, "result": "I'm not sure"})
    out = jpc.classify_jev("anything", run=lambda cmd, **kw: _FakeProc(stdout))
    assert out["choice"] is None
    assert out["error"] is not None
    assert out["cost_usd"] == 0.005


def test_classify_jev_handles_no_result_event_at_all():
    out = jpc.classify_jev("anything", run=lambda cmd, **kw: _FakeProc("not json\n", returncode=1, stderr="boom"))
    assert out["choice"] is None
    assert "boom" in out["error"] or "rc=1" in out["error"]


def test_classify_jev_handles_timeout():
    import subprocess

    def fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=60)

    out = jpc.classify_jev("anything", run=fake_run)
    assert out["choice"] is None
    assert out["error"] == "timeout"


def test_schema_enum_covers_every_reference_examples_intent():
    schema = json.loads(jpc.SCHEMA)
    assert set(schema["properties"]["choice"]["enum"]) == set(jpc.REFERENCE_EXAMPLES.keys())
