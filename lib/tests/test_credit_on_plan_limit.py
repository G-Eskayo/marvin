"""Plan first, credit only once the plan runs out (Gil, 2026-10-30). A model run that hits the plan's usage limit is
retried at once on the monthly API credit, and the Mac remembers the limit for an hour so its next builds start on the
credit; after that hour the plan is tried again. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_credit_on_plan_limit.py -v
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import dispatch_concurrency as dc  # noqa: E402
import sandbox_orchestration as so  # noqa: E402

KEY = "sk-ant-test-FAKE-894"
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
LIMIT_TEXT = "Claude AI usage limit reached|1793390400"
EXHAUSTED = "Your credit balance is too low to access the Anthropic API."


def _home(tmp_path, key=KEY, credit_state=None, plan_state=None):
    (tmp_path / ".claude" / "dispatch").mkdir(parents=True, exist_ok=True)
    if key is not None:
        (tmp_path / ".claude" / ".anthropic-api-key").write_text(key + "\n")
    if credit_state is not None:
        (tmp_path / ".claude" / "dispatch" / "credit-state.json").write_text(json.dumps(credit_state))
    if plan_state is not None:
        (tmp_path / ".claude" / "dispatch" / "plan-state.json").write_text(json.dumps(plan_state))
    return tmp_path


def _at(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- the plan's state ------------------------------------------------------------------------------------------------

def test_a_plan_never_marked_has_room(tmp_path):
    assert dc.plan_limited(_home(tmp_path), now=NOW) is False


def test_a_marked_plan_is_limited_for_an_hour_then_tried_again(tmp_path):
    h = _home(tmp_path)
    dc.mark_plan_limited(h, now=NOW - timedelta(minutes=59))
    assert dc.plan_limited(h, now=NOW) is True
    dc.mark_plan_limited(h, now=NOW - timedelta(minutes=61))
    assert dc.plan_limited(h, now=NOW) is False


def test_a_garbled_or_future_dated_plan_state_never_keeps_us_on_the_credit(tmp_path):
    """The wrong way to fail here spends money, so anything odd reads as 'the plan has room'."""
    h = _home(tmp_path / "a")
    (h / ".claude" / "dispatch" / "plan-state.json").write_text("{not json")
    assert dc.plan_limited(h, now=NOW) is False
    assert dc.plan_limited(_home(tmp_path / "b", plan_state={"limited_at": _at(-300)}), now=NOW) is False
    assert dc.plan_limited(_home(tmp_path / "c", plan_state={"limited_at": 5}), now=NOW) is False
    assert dc.plan_limited(_home(tmp_path / "d", plan_state=[]), now=NOW) is False


def test_plan_limited_cli_prints_true_or_false(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    assert dc._cli(["plan-limited"]) == 0 and capsys.readouterr().out.strip() == "false"
    dc.mark_plan_limited()
    assert dc._cli(["plan-limited"]) == 0 and capsys.readouterr().out.strip() == "true"


def test_credit_env_needs_a_key_and_no_recent_credit_failure(tmp_path):
    env = dc.credit_env(_home(tmp_path / "a"), base={"CLAUDE_CODE_OAUTH_TOKEN": "plan", "PATH": "/bin"}, now=NOW)
    assert env["ANTHROPIC_API_KEY"] == KEY and "CLAUDE_CODE_OAUTH_TOKEN" not in env and env["PATH"] == "/bin"
    assert dc.credit_env(_home(tmp_path / "b", key=None), base={}, now=NOW) is None
    spent = {"ok": False, "why": "credit-exhausted", "at": _at(30)}
    assert dc.credit_env(_home(tmp_path / "c", credit_state=spent), base={}, now=NOW) is None


# --- _launch: the switch, mid-run ------------------------------------------------------------------------------------

class _Result:
    def __init__(self, exit_code=0, text="done", cost=0.5):
        self.exit_code, self.text, self.stderr, self.cost_usd = exit_code, text, "", cost


@pytest.fixture
def launches(tmp_path, monkeypatch):
    """Records every launch's env; answers from a queue of results."""
    home = _home(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "plan-token")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    calls, queue = [], []

    def fake_launch(kind, prompt, *, ticket=None, env=None, **kw):
        calls.append(dict(env) if env is not None else None)
        return queue.pop(0)
    monkeypatch.setattr(so.marvin_launcher, "launch", fake_launch)

    def billing():
        log = home / ".claude" / "logs" / "builder-billing.jsonl"
        return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
    return {"home": home, "calls": calls, "queue": queue, "billing": billing}


def _on_credit(env):
    return env is not None and env.get("ANTHROPIC_API_KEY") == KEY and "CLAUDE_CODE_OAUTH_TOKEN" not in env


def test_a_plan_with_room_runs_once_on_the_plan(launches):
    launches["queue"].append(_Result())
    assert so._launch("executor", "p", ticket_ref="o/r#1") == ("done", 0.5)
    assert len(launches["calls"]) == 1 and not _on_credit(launches["calls"][0])
    assert launches["billing"]() == []


def test_hitting_the_plan_limit_retries_the_same_run_on_the_credit(launches):
    launches["queue"] += [_Result(1, LIMIT_TEXT, 0), _Result(text="built on credit", cost=1.2)]
    assert so._launch("executor", "p", ticket_ref="o/r#7") == ("built on credit", 1.2)
    assert len(launches["calls"]) == 2 and _on_credit(launches["calls"][1])
    assert dc.plan_limited(launches["home"]) is True
    assert launches["billing"]()[-1] == {**launches["billing"]()[-1], "task": "o/r#7", "mode": "api", "why": "plan-limit"}


def test_while_the_plan_is_limited_runs_start_on_the_credit(launches):
    dc.mark_plan_limited(launches["home"])
    launches["queue"].append(_Result())
    so._launch("planner", "p", ticket_ref="o/r#2")
    assert len(launches["calls"]) == 1 and _on_credit(launches["calls"][0])


def test_a_failure_that_isnt_the_plan_limit_is_not_retried_and_doesnt_mark_the_plan(launches):
    launches["queue"].append(_Result(1, "Error: tool crashed", 0))
    with pytest.raises(so.ModelRunFailed):
        so._launch("executor", "p", ticket_ref="o/r#3")
    assert len(launches["calls"]) == 1 and dc.plan_limited(launches["home"]) is False


def test_the_plan_limit_with_no_key_fails_as_before_but_remembers_the_limit(launches):
    (launches["home"] / ".claude" / ".anthropic-api-key").unlink()
    launches["queue"].append(_Result(1, LIMIT_TEXT, 0))
    with pytest.raises(so.ModelRunFailed) as exc:
        so._launch("executor", "p", ticket_ref="o/r#4")
    assert exc.value.usage_limit and len(launches["calls"]) == 1
    assert dc.plan_limited(launches["home"]) is True


def test_a_spent_credit_closes_the_credit_and_the_run_fails_as_a_usage_limit(launches):
    launches["queue"] += [_Result(1, LIMIT_TEXT, 0), _Result(1, EXHAUSTED, 0)]
    with pytest.raises(so.ModelRunFailed) as exc:
        so._launch("executor", "p", ticket_ref="o/r#5")
    assert exc.value.usage_limit
    state = json.loads((launches["home"] / ".claude" / "dispatch" / "credit-state.json").read_text())
    assert state["ok"] is False and state["why"] == "credit-exhausted"
    assert dc.credit_ready_local(launches["home"]) is False
    assert launches["billing"]()[-1]["why"] == "credit-exhausted"


def test_a_run_already_on_the_credit_is_never_retried(launches, monkeypatch):
    """builder_auth.sh put the whole build on the credit: a limit now is the credit's, not the plan's."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    launches["queue"].append(_Result(1, LIMIT_TEXT, 0))
    with pytest.raises(so.ModelRunFailed):
        so._launch("executor", "p", ticket_ref="o/r#6")
    assert len(launches["calls"]) == 1 and dc.plan_limited(launches["home"]) is False


def test_a_callers_own_env_is_kept_on_the_credit_retry(launches):
    launches["queue"] += [_Result(1, LIMIT_TEXT, 0), _Result()]
    so._launch("executor", "p", ticket_ref="o/r#8", env={"DEVELOPER_DIR": "/X", "CLAUDE_CODE_OAUTH_TOKEN": "plan"})
    retry = launches["calls"][1]
    assert retry["DEVELOPER_DIR"] == "/X" and _on_credit(retry)


def test_the_key_never_reaches_the_billing_log(launches):
    launches["queue"] += [_Result(1, LIMIT_TEXT, 0), _Result()]
    so._launch("executor", "p", ticket_ref="o/r#9")
    log = launches["home"] / ".claude" / "logs" / "builder-billing.jsonl"
    assert KEY not in log.read_text()
