#!/usr/bin/env python3
"""marvin-bench — compare base Claude Code (clean profile) vs the MARVIN-
optimized setup on the same tasks.

Usage:
    python3 bench.py tasks/task-002-recall          # one task, both profiles
    python3 bench.py tasks/*                          # whole suite
    python3 bench.py tasks/task-002-recall --profiles clean    # one profile
    python3 bench.py tasks/* --repeat 5             # 5 runs each; reports mean ± σ
    python3 bench.py tasks/* --judge                # LLM-judge semantic grading
    python3 bench.py tasks/* --repeat 3 --judge     # both
    python3 bench.py tasks/* --model claude-haiku-4-5-20251001  # swap model
    python3 bench.py tasks/* --model claude-haiku-4-5-20251001 --profiles clean,marvin
    python3 bench.py tasks/task-002-recall --runner ollama --ollama-model qwen2.5:7b
    python3 bench.py tasks/task-002-recall --runner ollama --ollama-model qwen2.5:7b --profiles clean,marvin --judge

Each task runs identically through every profile; results land in results/ and a
comparison table prints to stdout. Run profiles/setup.sh first.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import statistics as _stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lib"))
from score import parse_stream, score_correctness  # noqa: E402
from memory_rag import query_memory  # noqa: E402

PROFILES = {
    "clean":  ROOT / "profiles" / "clean",           # base Claude Code (control)
    "marvin": ROOT / "profiles" / "marvin",          # symlink overlay of ~/.claude (rich)
    "lean":   ROOT / "profiles" / "lean",            # symlink overlay of ~/.claude-lean (no memory overhead)
}

# Substrings that mean "this run never actually attempted the task" — an
# account-level rate/session limit or a stale credential, not a real
# correctness failure. Runs matching these must never be scored as 0.00; they
# get flagged as infra errors and excluded from the correctness aggregate so a
# quota outage can't masquerade as a MARVIN-vs-clean finding.
INFRA_ERROR_MARKERS = (
    "hit your session limit",
    "not logged in",
    "please run /login",
)


def _is_infra_error(result_text: str) -> bool:
    t = (result_text or "").lower()
    return any(m in t for m in INFRA_ERROR_MARKERS)

OLLAMA_BASE = "http://localhost:11434"


def _load_marvin_context() -> str:
    """Load MEMORY.md + all linked memory files for Ollama context injection.

    Scans ~/.claude/projects/ for the first MEMORY.md found. Loads the index
    and all .md files it links to (via markdown link syntax).
    Returns empty string if no memory dir found.
    """
    projects_dir = Path.home() / ".claude" / "projects"
    memory_index: Path | None = None
    if projects_dir.exists():
        for candidate in sorted(projects_dir.rglob("MEMORY.md")):
            memory_index = candidate
            break
    if not memory_index or not memory_index.exists():
        return ""

    memory_dir = memory_index.parent
    index_text = memory_index.read_text()
    parts = ["# MARVIN Memory — injected context\n\n" + index_text]

    for m in re.finditer(r'\[.*?\]\((\S+\.md)\)', index_text):
        fpath = memory_dir / m.group(1)
        if fpath.exists():
            try:
                parts.append(f"## {m.group(1)}\n\n{fpath.read_text()}")
            except OSError:
                pass

    return "\n\n---\n\n".join(parts)


def _check_quota() -> dict | None:
    """One cheap claude -p call to read the account's current rate_limit_info
    off the stream-json output. Returns None if it couldn't be determined
    (treated as 'proceed, unknown' rather than blocking)."""
    try:
        proc = subprocess.run(
            ["claude", "-p", "ok", "--output-format", "stream-json", "--verbose",
             "--permission-mode", "bypassPermissions"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith('{"type":"rate_limit_event"'):
            continue
        try:
            return json.loads(line).get("rate_limit_info")
        except Exception:
            continue
    return None


def _ollama_available(model: str) -> tuple[bool, str]:
    """Return (ok, error_message). Checks server is up and model is pulled."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=5) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        return False, f"Ollama server not responding ({exc}). Start with: ollama serve"
    available = [m["name"] for m in data.get("models", [])]
    # accept exact match or prefix (e.g. "qwen2.5:7b" matches "qwen2.5:7b-instruct-q4_K_M")
    if not any(a == model or a.startswith(model.split(":")[0]) for a in available):
        return False, (f"Model '{model}' not found. Available: {available}\n"
                       f"Pull with: ollama pull {model}")
    return True, ""


def run_once_ollama(task: dict, profile: str, ollama_model: str,
                    context_mode: str = "full") -> dict | None:
    """Run a QA task against a local Ollama model via /api/chat.

    profile=clean  → no context injection (control)
    profile=marvin → context injection, mode controlled by context_mode:
                       "full" — dump all MEMORY.md + linked files (~4000 tok)
                       "rag"  — top-3 semantically relevant passages (~300 tok)
    profile=lean   → same as clean (lean's value is CLAUDE.md, irrelevant here)

    Returns None for fs tasks (tool use not supported).
    """
    if task.get("type") == "fs":
        return None  # caller prints skip

    system_content = ""
    if profile == "marvin":
        if context_mode == "rag":
            system_content = query_memory(task["prompt"], n_results=3)
        else:
            system_content = _load_marvin_context()

    messages: list[dict] = []
    if system_content:
        messages.append({"role": "system", "content": system_content})
    messages.append({"role": "user", "content": task["prompt"]})

    payload = json.dumps({
        "model": ollama_model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=task.get("timeout", 300)) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        return {
            "profile": profile, "model": ollama_model, "runner": "ollama",
            "result_text": "", "spawn_error": str(exc),
            "wall_s": round(time.time() - t0, 1),
            "cost_usd": 0.0, "total_tokens": 0, "num_turns": 1, "tool_calls": 0,
            "correctness": {"score": 0.0},
        }
    wall = time.time() - t0

    result_text = (data.get("message") or {}).get("content", "")
    prompt_tokens = data.get("prompt_eval_count", 0)
    gen_tokens = data.get("eval_count", 0)

    return {
        "profile":       profile,
        "model":         ollama_model,
        "runner":        "ollama",
        "result_text":   result_text,
        "wall_s":        round(wall, 1),
        "cost_usd":      0.0,
        "total_tokens":  prompt_tokens + gen_tokens,
        "num_turns":     1,
        "tool_calls":    0,
        "correctness":    score_correctness(task, result_text, None),
        "context_mode":   context_mode if profile == "marvin" else "none",
        "_prompt_tokens": prompt_tokens,
        "_gen_tokens":    gen_tokens,
    }


def load_task(task_dir: Path) -> dict:
    cfg = json.loads((task_dir / "task.json").read_text())
    cfg["dir"] = task_dir
    cfg["prompt"] = (task_dir / cfg.get("prompt_file", "prompt.md")).read_text()
    return cfg


def run_once(task: dict, profile: str, capture_snapshot: bool = False, model: str | None = None) -> dict:
    config_dir = PROFILES[profile]
    is_fs = task.get("type") == "fs"

    # fs tasks get an isolated temp workdir; qa/recall tasks run in a fixed cwd
    # (default: home) so the project-scoped memory layer engages for the marvin
    # profile. The clean profile loads no memory regardless of cwd.
    if is_fs:
        workdir = Path(tempfile.mkdtemp(prefix=f"mb-{task['id']}-{profile}-"))
        if (task["dir"] / "files").exists():
            shutil.copytree(task["dir"] / "files", workdir, dirs_exist_ok=True)
        cleanup = True
    else:
        workdir = Path(task.get("cwd", str(Path.home())))
        cleanup = False

    cmd = ["claude", "-p", task["prompt"],
           "--output-format", "stream-json", "--verbose"]
    if model:
        cmd += ["--model", model]
    if is_fs:
        cmd += ["--permission-mode", "bypassPermissions"]
    # Tasks that need file-read blocking to actually hold (memory-only
    # discriminators — the answer must ONLY be reachable via a skill/tool, not
    # disk) can set task.json's "disallow_tools". A prose "don't read files"
    # instruction in the prompt is not enforceable — Read isn't gated by the
    # Bash permission system and a model can use it anyway. See
    # marvin-bench-harness memory / task-014's compromise, Run 15.
    if task.get("disallow_tools"):
        cmd += ["--disallowedTools", ",".join(task["disallow_tools"])]

    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(config_dir)}
    # strip inherited Claude Code session vars so the child starts clean
    for k in list(env):
        if k.startswith("CLAUDE_CODE_") or k in ("CLAUDECODE", "CLAUDE_EFFORT"):
            env.pop(k, None)

    t0 = time.time()
    proc = subprocess.run(cmd, cwd=workdir, env=env,
                          capture_output=True, text=True, timeout=task.get("timeout", 600))
    wall = time.time() - t0

    parsed = parse_stream(proc.stdout)
    parsed["wall_s"] = round(wall, 1)
    parsed["infra_error"] = _is_infra_error(parsed.get("result_text"))
    parsed["correctness"] = (
        {"score": None, "matched": [], "missed": []} if parsed["infra_error"]
        else score_correctness(task, parsed["result_text"], workdir if is_fs else None)
    )
    parsed["profile"] = profile
    parsed["model"] = model or "default"
    if proc.returncode != 0 and not parsed.get("result_text"):
        parsed["spawn_error"] = proc.stderr[-500:]

    if cleanup:
        if capture_snapshot:
            # capture .py files before cleanup so LLM judge can read them
            parts = []
            for p in sorted(workdir.rglob("*.py")):
                if p.stat().st_size < 30_000:
                    try:
                        parts.append(f"--- {p.name} ---\n{p.read_text(errors='ignore')}")
                    except OSError:
                        pass
            parsed["workdir_snapshot"] = "\n".join(parts)
        shutil.rmtree(workdir, ignore_errors=True)

    return parsed


def judge_run(task: dict, run: dict) -> dict:
    """Call claude as an LLM judge to semantically grade a completed run.
    Pinned to the `clean` profile's CLAUDE_CONFIG_DIR AND given zero tools
    (`--tools ""`) so the judge has no skills/memory/tools of its own — it
    grades strictly from the task prompt and the candidate's transcribed
    response, never its own environment.
    (Previously ran under the live default profile, which let the judge's own
    tool/skill list leak into its rationale — e.g. claiming a skill was
    "available in this session" for a run that never had it. See
    marvin-bench-harness memory, Run 13. Then, after pinning to `clean` with
    `--permission-mode bypassPermissions`, a second leak appeared: the judge
    used Bash to check ITS OWN clean/memory-less filesystem and wrongly
    rejected a correct answer with "the memory directory in this environment
    is empty" — confusing its own empty environment for the candidate's real
    one. `--tools ""` closes this off entirely: the judge can't invoke
    anything, so it can only reason from the text it's handed. See Run 15.)

    Also passes task['expect'] (the same ground-truth phrase list the
    deterministic substring scorer uses) when present, and instructs the
    judge to grade content-match against it rather than guess at whether the
    response is "fabricated." Without a ground truth to check against, the
    judge has no way to tell a correct-but-specific answer from a
    confident-sounding hallucination — it was instead reacting to how
    specific/confident the phrasing *sounded*, which flipped its verdict
    on near-identical-quality answers across repeats (e.g. run 1 "grounded",
    run 2 of the same candidate "fabrication", no change in actual accuracy).
    See Run 15.
    Returns a correctness dict with score 0.0 or 1.0 + rationale.
    """
    snapshot = run.get("workdir_snapshot", "")
    expect = task.get("expect") or []
    judge_prompt = (
        "You are grading whether a coding assistant correctly completed a task.\n\n"
        f"TASK PROMPT:\n{task['prompt']}\n\n"
        f"ASSISTANT RESPONSE:\n{run.get('result_text') or '(empty)'}\n\n"
        + (f"FILES IN WORKDIR AFTER RUN:\n{snapshot}\n\n" if snapshot else "")
        + (f"GROUND-TRUTH PHRASE(S) THE ANSWER SHOULD CONVEY: {expect}\n"
           "Grade content-match against these — verbatim or clearly equivalent wording "
           "both count as correct. Do NOT try to guess whether the assistant genuinely "
           "retrieved this from memory versus already knew it, and do NOT penalize extra "
           "specific detail beyond what's listed here as suspected fabrication — that is "
           "normal elaboration. Grade only whether the core content matches.\n\n"
           if expect else "")
        + "Did the assistant correctly and completely implement what the task asked?\n"
        "Grade only what is shown above. Do not assume the assistant had access to any "
        "tool, skill, or MCP server unless its response demonstrates using it — you do "
        "not share its environment and cannot know what was available to it.\n"
        "Reply with exactly two lines:\n"
        "VERDICT: PASS\n"
        "REASON: one sentence\n\n"
        "or\n\n"
        "VERDICT: FAIL\n"
        "REASON: one sentence explaining the specific gap"
    )

    judge_env = {**os.environ, "CLAUDE_CONFIG_DIR": str(PROFILES["clean"])}
    for k in list(judge_env):
        if k.startswith("CLAUDE_CODE_") or k in ("CLAUDECODE", "CLAUDE_EFFORT"):
            judge_env.pop(k, None)

    try:
        proc = subprocess.run(
            ["claude", "-p", judge_prompt, "--output-format", "text", "--tools", ""],
            capture_output=True, text=True, timeout=90, env=judge_env
        )
        text = proc.stdout.strip()
    except Exception as exc:
        return {"score": None, "judge": "llm", "rationale": f"judge call failed: {exc}"}

    verdict_line = next((l for l in text.splitlines() if "VERDICT" in l.upper()), "")
    passed = "PASS" in verdict_line.upper()
    reason_m = re.search(r"REASON\s*:\s*(.+)", text, re.IGNORECASE)
    reason = reason_m.group(1).strip() if reason_m else text[:300]

    return {
        "score": 1.0 if passed else 0.0,
        "judge": "llm",
        "rationale": reason,
    }


# ── aggregation ───────────────────────────────────────────────────────────────

def aggregate_runs(runs: list[dict]) -> dict:
    """Reduce N repeated runs into a summary row with mean + stddev fields.
    The raw runs are preserved in _raw for JSON export.

    Runs flagged infra_error (hit an account rate/session limit, or a stale
    credential) never attempted the task — they're excluded from cost/token/
    correctness stats so a quota outage can't read as a real 0.00 finding.
    """
    n = len(runs)
    agg: dict = {"profile": runs[0]["profile"], "_n": n, "_raw": runs}
    agg["_n_infra_error"] = sum(1 for r in runs if r.get("infra_error"))

    ok_runs = [r for r in runs if not r.get("infra_error")]
    if not ok_runs:
        agg["all_infra_error"] = True
        for field in ("cost_usd", "total_tokens", "num_turns", "tool_calls", "wall_s"):
            agg[field] = 0.0
            agg[field + "_std"] = 0.0
        agg["correctness"] = {"score": None}
        agg["_n_correct"] = 0
        return agg

    for field in ("cost_usd", "total_tokens", "num_turns", "tool_calls", "wall_s"):
        vals = [r[field] for r in ok_runs]
        agg[field] = _stat.mean(vals)
        agg[field + "_std"] = _stat.stdev(vals) if len(vals) > 1 else 0.0

    scores = [(r.get("correctness") or {}).get("score") or 0.0 for r in ok_runs]
    agg["correctness"] = {"score": _stat.mean(scores)}
    agg["_n_correct"] = sum(1 for s in scores if s == 1.0)

    # judge scores if present
    j_scores = [
        (r.get("judge_correctness") or {}).get("score")
        for r in runs
        if (r.get("judge_correctness") or {}).get("score") is not None
    ]
    if j_scores:
        agg["judge_correctness"] = {
            "score": _stat.mean(j_scores),
            "judge": "llm",
            "_n_pass": sum(1 for s in j_scores if s == 1.0),
        }

    return agg


# ── formatting ────────────────────────────────────────────────────────────────

def _ms(mean: float, std: float, fmt: str) -> str:
    """Format mean ± std; omit ±0 when std is zero."""
    m = format(mean, fmt)
    if std == 0:
        return m
    s = format(std, fmt)
    return f"{m}(±{s})"


def fmt_table(task_id: str, rows: list[dict], show_judge: bool = False) -> str:
    multi = rows[0].get("_n", 1) > 1

    if not multi:
        return _fmt_single(task_id, rows, show_judge)
    return _fmt_multi(task_id, rows, show_judge)


def _fmt_single(task_id: str, rows: list[dict], show_judge: bool) -> str:
    judge_col = [("judge", 6)] if show_judge else []
    cols = ([("profile", 8), ("cost_usd", 10), ("total_tokens", 13),
              ("num_turns", 6), ("tool_calls", 6), ("wall_s", 7), ("correct", 10)]
            + judge_col
            + [("tok/ok", 10), ("tools/ok", 9)])
    head = "  ".join(name.ljust(w) for name, w in cols)
    lines = [f"\n=== {task_id} ===", head, "-" * len(head)]
    for r in rows:
        c = (r.get("correctness") or {}).get("score")
        jc = (r.get("judge_correctness") or {}).get("score")
        fully_correct = c == 1.0
        cell = {
            "profile":      r["profile"],
            "cost_usd":     f"${r['cost_usd']:.4f}",
            "total_tokens": str(r["total_tokens"]),
            "num_turns":    str(r["num_turns"]),
            "tool_calls":   str(r["tool_calls"]),
            "wall_s":       str(r["wall_s"]),
            "correct":      ("INFRA-ERR" if r.get("infra_error") else
                              "n/a" if c is None else f"{c:.2f}"),
            "judge":        ("n/a" if jc is None else ("pass" if jc == 1.0 else "FAIL")),
            "tok/ok":       str(r["total_tokens"]) if fully_correct else "-",
            "tools/ok":     str(r["tool_calls"])   if fully_correct else "-",
        }
        lines.append("  ".join(cell[name].ljust(w) for name, w in cols))
        # judge rationale on a second line when it fails
        if show_judge and jc is not None and jc < 1.0:
            rationale = (r.get("judge_correctness") or {}).get("rationale", "")
            if rationale:
                lines.append(f"  {'':8}  {'':10}  {'':13}  {'':6}  {'':6}  {'':7}  {'':8}  "
                              f"⚠ {rationale[:80]}")
    return "\n".join(lines)


def _fmt_multi(task_id: str, rows: list[dict], show_judge: bool) -> str:
    n = rows[0]["_n"]
    judge_col = [("judge", 10)] if show_judge else []
    cols = ([("profile", 8), ("cost_usd", 18), ("total_tokens", 18),
              ("num_turns", 12), ("tool_calls", 12), ("wall_s", 12),
              ("correct", 16)]
            + judge_col
            + [("tok/ok", 18), ("tools/ok", 12)])
    head = "  ".join(name.ljust(w) for name, w in cols)
    lines = [f"\n=== {task_id} (N={n}) ===", head, "-" * len(head)]

    for r in rows:
        c = (r.get("correctness") or {}).get("score")
        n_ok = r.get("_n_correct", 0)
        jc_entry = r.get("judge_correctness") or {}
        jc = jc_entry.get("score")
        j_n_pass = jc_entry.get("_n_pass")

        # tok/ok and tools/ok: stats over runs that scored 1.0 substring-correct
        ok_runs = [x for x in r.get("_raw", [])
                   if (x.get("correctness") or {}).get("score") == 1.0]
        if ok_runs:
            tv = [x["total_tokens"] for x in ok_runs]
            cv = [x["tool_calls"] for x in ok_runs]
            tok_ok = _ms(_stat.mean(tv), _stat.stdev(tv) if len(tv) > 1 else 0.0, ".0f")
            tools_ok = _ms(_stat.mean(cv), _stat.stdev(cv) if len(cv) > 1 else 0.0, ".1f")
        else:
            tok_ok = tools_ok = "-"

        cell = {
            "profile":      r["profile"],
            "cost_usd":     "$" + _ms(r["cost_usd"], r["cost_usd_std"], ".4f"),
            "total_tokens": _ms(r["total_tokens"], r["total_tokens_std"], ".0f"),
            "num_turns":    _ms(r["num_turns"], r["num_turns_std"], ".1f"),
            "tool_calls":   _ms(r["tool_calls"], r["tool_calls_std"], ".1f"),
            "wall_s":       _ms(r["wall_s"], r["wall_s_std"], ".1f"),
            "correct":      (f"INFRA-ERR({r.get('_n_infra_error', 0)}/{n})"
                              if r.get("all_infra_error")
                              else "n/a" if c is None else f"{n_ok}/{n}={c:.2f}"),
            "judge":        ("n/a" if jc is None else f"{j_n_pass}/{n}={jc:.2f}"),
            "tok/ok":       tok_ok,
            "tools/ok":     tools_ok,
        }
        lines.append("  ".join(cell[name].ljust(w) for name, w in cols))
    return "\n".join(lines)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks", nargs="+", help="task directories")
    ap.add_argument("--profiles", default="clean,lean,marvin",
                    help="comma list (default: clean,lean,marvin)")
    ap.add_argument("--repeat", type=int, default=1, metavar="N",
                    help="run each profile N times; report mean ± σ (default 1)")
    ap.add_argument("--judge", action="store_true",
                    help="add LLM-judge semantic grading alongside substring grading")
    ap.add_argument("--model", default=None, metavar="MODEL",
                    help="model ID passed to claude (e.g. claude-haiku-4-5-20251001); "
                         "default = Claude Code's configured default")
    ap.add_argument("--runner", default="claude", choices=["claude", "ollama"],
                    help="execution backend: 'claude' (default) or 'ollama' (local model)")
    ap.add_argument("--ollama-model", default="qwen2.5:7b", metavar="MODEL",
                    help="Ollama model to use with --runner ollama (default: qwen2.5:7b)")
    ap.add_argument("--context", default="full", choices=["full", "rag"],
                    help="context injection mode for marvin profile with --runner ollama: "
                         "'full' = dump all memory files (default), "
                         "'rag' = top-3 semantically relevant passages")
    args = ap.parse_args()

    # derive short display name for headers / filenames
    _MODEL_SHORT = None
    if args.runner == "ollama":
        _MODEL_SHORT = args.ollama_model.replace(":", "-")
    elif args.model:
        _MODEL_SHORT = next(
            (m for m in ("haiku", "sonnet", "opus", "fable") if m in args.model.lower()),
            args.model.split("-")[1] if "-" in args.model else args.model,
        )

    # pre-flight check for ollama runner
    if args.runner == "ollama":
        ok, err = _ollama_available(args.ollama_model)
        if not ok:
            sys.exit(err)

    profiles = args.profiles.split(",")
    for p in profiles:
        if p not in PROFILES:
            sys.exit(f"unknown profile '{p}'; choose from {list(PROFILES)}")
    if "clean" in profiles and not PROFILES["clean"].exists():
        sys.exit("clean profile missing — run profiles/setup.sh first")

    # pre-flight quota check (claude runner only — ollama is local/free).
    # Every candidate run is a full separate `claude -p` session, and --judge
    # doubles that with a grading session; a --repeat N run across the full
    # suite can be dozens of sessions against the SAME account-wide 5-hour
    # limit this interactive session also draws from. Warn with an estimate,
    # and abort early if the account is already at/over its limit instead of
    # burning through a run that will fail partway (see marvin-bench-harness
    # memory, Run 13/14 — this is exactly how two sessions ran out early).
    if args.runner == "claude":
        n_valid_tasks = sum(1 for t in args.tasks if (Path(t) / "task.json").exists())
        est = n_valid_tasks * len(profiles) * args.repeat * (2 if args.judge else 1)
        print(f"preflight: ~{est} claude session(s) planned "
              f"(tasks={n_valid_tasks} x profiles={len(profiles)} x repeat={args.repeat}"
              f"{' x 2 [judge]' if args.judge else ''})", flush=True)
        quota = _check_quota()
        if quota is None:
            print("preflight: could not determine account quota — proceeding anyway", flush=True)
        else:
            status = quota.get("status")
            reset_s = quota.get("resetsAt")
            reset_str = (time.strftime("%H:%M %Z", time.localtime(reset_s))
                         if reset_s else "unknown")
            print(f"preflight: quota status={status} "
                  f"type={quota.get('rateLimitType')} resets={reset_str}", flush=True)
            if status != "allowed":
                sys.exit(f"aborting — account is already at its "
                         f"{quota.get('rateLimitType')} limit (resets {reset_str}); "
                         f"re-run after that, or narrow --profiles/--repeat.")

    for task_path in args.tasks:
        task_dir = Path(task_path)
        if not (task_dir / "task.json").exists():
            print(f"skip {task_dir} (no task.json)")
            continue
        task = load_task(task_dir)
        rows = []
        all_raw: list[dict] = []

        for profile in profiles:
            if args.runner == "ollama":
                run = run_once_ollama(task, profile, args.ollama_model, args.context)
                if run is None:
                    print(f"  skip {task['id']} @ {profile} [ollama] — fs tasks require tool use")
                    continue
                ctx_label = f"/{args.context}" if profile == "marvin" else ""
                print(f"running {task['id']} @ {profile}{ctx_label} [ollama/{args.ollama_model}] ...", flush=True)
                if args.judge:
                    print(f"  judging {task['id']} @ {profile} ...", flush=True)
                    run["judge_correctness"] = judge_run(task, run)
                rows.append(run)
                all_raw.append(run)
            elif args.repeat == 1:
                print(f"running {task['id']} @ {profile} ...", flush=True)
                run = run_once(task, profile, capture_snapshot=args.judge, model=args.model)
                if run.get("infra_error"):
                    print(f"  ! infra error (rate/session limit or auth) — skipping judge, "
                          f"not scored as a real failure", flush=True)
                elif args.judge:
                    print(f"  judging {task['id']} @ {profile} ...", flush=True)
                    run["judge_correctness"] = judge_run(task, run)
                rows.append(run)
                all_raw.append(run)
            else:
                profile_runs = []
                stop_repeat = False
                for i in range(args.repeat):
                    print(f"running {task['id']} @ {profile} [{i+1}/{args.repeat}] ...",
                          flush=True)
                    run = run_once(task, profile, capture_snapshot=args.judge, model=args.model)
                    if run.get("infra_error"):
                        print(f"  ! infra error (rate/session limit or auth) on repeat "
                              f"{i+1}/{args.repeat} — stopping this profile early, "
                              f"not scoring as a real failure", flush=True)
                        profile_runs.append(run)
                        stop_repeat = True
                        break
                    if args.judge:
                        print(f"  judging [{i+1}/{args.repeat}] ...", flush=True)
                        run["judge_correctness"] = judge_run(task, run)
                    profile_runs.append(run)
                all_raw.extend(profile_runs)
                rows.append(aggregate_runs(profile_runs))
                if stop_repeat:
                    print(f"  (stopped after infra error — remaining profiles/tasks "
                          f"will likely hit the same wall)", flush=True)

        if not rows:
            print(f"  (all profiles skipped for {task['id']} — nothing to display)")
            continue

        runner_tag = (f"ollama/{args.ollama_model}/{args.context}"
                      if args.runner == "ollama" else None)
        display_id = task["id"]
        if runner_tag:
            display_id = f"{task['id']} [{runner_tag}]"
        elif _MODEL_SHORT:
            display_id = f"{task['id']} [{_MODEL_SHORT}]"
        print(fmt_table(display_id, rows, show_judge=args.judge))

        stamp = time.strftime("%Y%m%d-%H%M%S")
        model_tag = f"-{_MODEL_SHORT}" if _MODEL_SHORT else ""
        out = ROOT / "results" / f"{task['id']}{model_tag}-{stamp}.json"
        out.write_text(json.dumps(
            {"task": task["id"], "runner": args.runner,
             "model": args.ollama_model if args.runner == "ollama" else (args.model or "default"),
             "repeat": args.repeat, "judge": args.judge, "runs": all_raw},
            indent=2, default=str,
        ))
        print(f"saved {out}")


if __name__ == "__main__":
    main()
