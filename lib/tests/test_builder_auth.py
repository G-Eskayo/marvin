"""lib/builder_auth.sh: dispatched builders bill the plan's monthly API credit when the machine has an API key, and
fall back to the plan's token when the credit is spent, the key is rejected or the API can't be reached (marvin #775).

Runs the real shell function in bash, with a throwaway HOME and a fake `curl` first on PATH, so nothing here reaches
the real API. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_builder_auth.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import task_dispatch as td  # noqa: E402

AUTH_SH = LIB / "builder_auth.sh"
KEY = "sk-ant-test-NOT-A-REAL-KEY-775"
EXHAUSTED = ('{"type":"error","error":{"type":"invalid_request_error","message":"Your credit balance is too low to '
             'access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."}}')


def _fake_curl(bin_dir: Path, status: str, body: str = "{}") -> None:
    """A curl that records its argv and stdin-free headers, writes `body` to the -o file and prints `status`."""
    script = f"""#!/bin/bash
printf '%s\\n' "$@" > "$FAKE_CURL_ARGS"
out=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2;;
    -H) if [ "${{2:0:1}}" = "@" ]; then cat "${{2:1}}" >> "$FAKE_CURL_HEADERS"; else printf '%s\\n' "$2" >> "$FAKE_CURL_HEADERS"; fi; shift 2;;
    *) shift;;
  esac
done
[ -n "$out" ] && printf '%s' '{body}' > "$out"
printf '%s' '{status}'
[ "{status}" = "000" ] && exit 28
exit 0
"""
    curl = bin_dir / "curl"
    curl.write_text(script)
    curl.chmod(0o755)


def _fake_python(home: Path, others: int | None) -> None:
    """MARVIN's venv python, answering only `-m lib.dispatch_concurrency others-running --exclude <task>`.
    None: the count can't be read (the command fails)."""
    py = home / ".agents" / "venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    out = "exit 1" if others is None else f'[ "$4" = "--exclude" ] && echo {others} || exit 1'
    py.write_text(f"#!/bin/bash\n[ \"$2\" = lib.dispatch_concurrency ] && [ \"$3\" = others-running ] && {{ {out}; }} || exit 1\n")
    py.chmod(0o755)


def _run(tmp_path: Path, *, key: str | None = KEY, status: str = "200", body: str = "{}",
         plan_slots: str = "2", others: int | None = 5) -> dict:
    """Default: the plan's 2 slots are full (5 others running), so the build is overflow and may use the credit."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    _fake_python(home, others)
    if key is not None:
        (home / ".claude" / ".anthropic-api-key").write_text(key + "\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_curl(bin_dir, status, body)
    env = {
        "HOME": str(home),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "CLAUDE_CODE_OAUTH_TOKEN": "plan-token",
        "FAKE_CURL_ARGS": str(tmp_path / "curl-args"),
        "FAKE_CURL_HEADERS": str(tmp_path / "curl-headers"),
    }
    out = subprocess.run(
        ["bash", "-c", f'. "{AUTH_SH}"; marvin_builder_auth task-775 {plan_slots}; '
                       'echo "API=${ANTHROPIC_API_KEY-unset}"; echo "PLAN=${CLAUDE_CODE_OAUTH_TOKEN-unset}"'],
        env=env, capture_output=True, text=True, timeout=30)
    log = home / ".claude" / "logs" / "builder-billing.jsonl"
    lines = log.read_text().splitlines() if log.exists() else []
    args = Path(env["FAKE_CURL_ARGS"])
    state = home / ".claude" / "dispatch" / "credit-state.json"
    return {
        "credit_state": json.loads(state.read_text()) if state.exists() else None,
        "stdout": out.stdout, "stderr": out.stderr, "rc": out.returncode,
        "log": [json.loads(l) for l in lines], "log_text": "\n".join(lines),
        "curl_args": args.read_text() if args.exists() else None,
        "curl_headers": Path(env["FAKE_CURL_HEADERS"]).read_text() if Path(env["FAKE_CURL_HEADERS"]).exists() else "",
    }


def test_a_working_key_bills_the_api_credit_and_drops_the_plan_token(tmp_path):
    r = _run(tmp_path)
    assert f"API={KEY}" in r["stdout"]
    assert "PLAN=unset" in r["stdout"]
    assert r["log"][-1]["mode"] == "api" and r["log"][-1]["task"] == "task-775"


def test_no_key_file_keeps_todays_plan_token_and_never_calls_the_api(tmp_path):
    r = _run(tmp_path, key=None)
    assert "API=unset" in r["stdout"] and "PLAN=plan-token" in r["stdout"]
    assert r["curl_args"] is None
    assert r["log"][-1] == {**r["log"][-1], "mode": "plan", "why": "no-key"}


def test_spent_credit_falls_back_to_the_plan(tmp_path):
    r = _run(tmp_path, status="400", body=EXHAUSTED)
    assert "API=unset" in r["stdout"] and "PLAN=plan-token" in r["stdout"]
    assert r["log"][-1]["mode"] == "plan" and r["log"][-1]["why"] == "credit-exhausted"


def test_a_rejected_key_falls_back_to_the_plan(tmp_path):
    r = _run(tmp_path, status="401", body='{"type":"error","error":{"type":"authentication_error"}}')
    assert "PLAN=plan-token" in r["stdout"] and "API=unset" in r["stdout"]
    assert r["log"][-1]["why"] == "key-rejected"


def test_an_unreachable_api_falls_back_to_the_plan(tmp_path):
    r = _run(tmp_path, status="000")
    assert "PLAN=plan-token" in r["stdout"] and "API=unset" in r["stdout"]
    assert r["log"][-1]["why"] == "unreachable"


def test_any_other_error_falls_back_to_the_plan_and_names_the_status(tmp_path):
    r = _run(tmp_path, status="529", body='{"type":"error","error":{"type":"overloaded_error"}}')
    assert "PLAN=plan-token" in r["stdout"]
    assert r["log"][-1]["why"] == "http-529"


def test_an_empty_key_file_counts_as_no_key(tmp_path):
    r = _run(tmp_path, key="   ")
    assert "PLAN=plan-token" in r["stdout"] and "API=unset" in r["stdout"]
    assert r["curl_args"] is None


def test_the_key_never_appears_in_curls_argv_or_the_log(tmp_path):
    """argv is visible to every process on the machine through `ps`; the key goes in a header file instead."""
    r = _run(tmp_path)
    assert KEY not in r["curl_args"]
    assert f"x-api-key: {KEY}" in r["curl_headers"]
    assert KEY not in r["log_text"]


def test_the_check_is_one_tiny_haiku_request(tmp_path):
    r = _run(tmp_path)
    body = next(a for a in r["curl_args"].splitlines() if a.startswith("{"))
    assert json.loads(body)["max_tokens"] == 1
    assert "haiku" in json.loads(body)["model"]
    assert "--max-time" in r["curl_args"]


def test_the_wrapper_sources_it_after_the_plan_token_and_before_the_command():
    script = td._build_wrapper_script("echo the-real-command", "task123", "my task", "mac-mini-1")
    use = script.index("marvin_builder_auth task123 ")
    assert script.index("CLAUDE_CODE_OAUTH_TOKEN") < use < script.index("echo the-real-command")
    assert '"$HOME/.agents/lib/builder_auth.sh"' in script
    assert KEY not in script and "ANTHROPIC_API_KEY=" not in script   # read at run time, never baked into the text


def test_the_wrapper_still_runs_on_a_machine_without_builder_auth_sh(tmp_path):
    """An older checkout on the other machine has no builder_auth.sh yet: the build must go on with the plan token."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    script = td._build_wrapper_script('echo "ran with ${CLAUDE_CODE_OAUTH_TOKEN-none}"', "t1", "lbl", "dev")
    path = tmp_path / "wrapper.sh"
    path.write_text(script)
    out = subprocess.run(["bash", str(path)], env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
                         capture_output=True, text=True, timeout=30)
    assert "ran with none" in out.stdout


def test_builder_auth_sh_passes_the_push_guard():
    """Found 2026-10-29: the compact JSON request body matched the guard's transcript shape, so the push was refused."""
    import re
    lines = (LIB.parent / "config" / "push-guard" / "patterns.txt").read_text().splitlines()
    patterns = [l for l in lines if l.strip() and not l.startswith("#")]
    text = AUTH_SH.read_text()
    assert not [p for p in patterns if re.search(p, text)]


# Plan first, credit for overflow (#849): the plan's slots are the priority; the credit only adds builds on top.

def test_a_free_plan_slot_bills_the_plan_and_never_calls_the_api(tmp_path):
    r = _run(tmp_path, plan_slots="2", others=1)
    assert "PLAN=plan-token" in r["stdout"] and "API=unset" in r["stdout"]
    assert r["curl_args"] is None
    assert r["log"][-1]["mode"] == "plan" and r["log"][-1]["why"] == "plan-slot"


def test_the_build_that_fills_the_last_plan_slot_is_still_on_the_plan(tmp_path):
    r = _run(tmp_path, plan_slots="2", others=1)   # 1 other + this one = 2 = the plan's slots
    assert r["log"][-1]["why"] == "plan-slot"


def test_full_plan_slots_with_credit_left_bill_the_credit(tmp_path):
    r = _run(tmp_path, plan_slots="2", others=2)
    assert f"API={KEY}" in r["stdout"] and "PLAN=unset" in r["stdout"]
    assert r["credit_state"]["ok"] is True


def test_full_plan_slots_with_the_credit_spent_stay_on_the_plan_and_close_the_extra_slots(tmp_path):
    r = _run(tmp_path, plan_slots="2", others=3, status="400", body=EXHAUSTED)
    assert "PLAN=plan-token" in r["stdout"]
    assert r["credit_state"]["ok"] is False and r["credit_state"]["why"] == "credit-exhausted"


def test_an_unreadable_running_count_bills_the_plan(tmp_path):
    r = _run(tmp_path, plan_slots="2", others=None)
    assert "PLAN=plan-token" in r["stdout"] and r["curl_args"] is None
    assert r["log"][-1]["why"] == "plan-slot"


def test_no_slot_count_given_means_one_plan_slot(tmp_path):
    r = _run(tmp_path, plan_slots="", others=0)
    assert r["log"][-1]["why"] == "plan-slot"
    r2 = _run(tmp_path / "b", plan_slots="", others=1)
    assert r2["log"][-1]["mode"] == "api"


def test_the_wrapper_passes_the_machines_plan_slots(monkeypatch):
    monkeypatch.setattr(td.dispatch_concurrency, "load", lambda: {"parallel": True, "max_total": 3, "max_per_project": 3,
                        "machine_slots": {"mac-mini-1": 2}, "credit_slots": {"mac-mini-1": 2},
                        "guards": {"min_disk_gb": 15, "min_github_budget_pct": 20}})
    script = td._build_wrapper_script("echo hi", "task9", "lbl", "mac-mini-1")
    assert "marvin_builder_auth task9 2" in script   # the plan's 2, not 2 + the credit's 2
