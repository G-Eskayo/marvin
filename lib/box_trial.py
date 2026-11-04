#!/usr/bin/env python3
"""The box trial (marvin #932): the five work types the owner chose for mac-mini-2012 (`trial-work` on
the instance's calibration PR #6, marvin #623), each sent through task_dispatch with its work tag and its timeout. Nothing else goes to
the box from here; ticket builds never do.

    box_trial.py suite        full Python suite at -n 8          --needs test        480 s (3x 158 s)
    box_trial.py vitest       dashboard vitest                    --needs test        120 s (3x 35 s)
    box_trial.py quarantine -- 'CMD'  a shell command in a disposable quarantine VM   --needs quarantine  boot 180 s + CMD's limit
    box_trial.py security -- TOOL ARGS   a Kali security/network tool    --needs security    600 s
    box_trial.py retrieval    the no-model retrieval bench        --needs bench       RETRIEVAL_TIMEOUT

test and bench work falls back to the less busy Mac when the box stalls (ADR 0069 amendment, #930); quarantine and
security never do. suite and vitest run in a throwaway git worktree of the box's own checkout, removed afterwards, so
a mirror pull mid-run can't change the files under the run.

The retrieval questions live only in the instance repo, and the box has no instance (ADR 0069). They are read here,
on the Mac, and handed to the run on stdin (`--questions /dev/stdin`): they are never written to the box's disk.

Every run appends one line to ~/.claude/logs/box-trial.jsonl on the Mac that sent it.
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task_dispatch  # noqa: E402

LOG = Path.home() / ".claude" / "logs" / "box-trial.jsonl"
PY = '"$HOME/.agents/venv/bin/python"'
VM_BOOT_S = 180          # vm_run's own boot limit
QUARANTINE_CMD_S = 300   # default limit for the command inside the quarantine VM
SECURITY_TIMEOUT_S = 600
# 3x the first measured run on the box: 158 s for graph update + the 30-question eval (2026-10-30, #932).
RETRIEVAL_TIMEOUT_S = 480
# Kali tools the security trial may run on the box host. A closed list keeps "security" from being a back door for
# arbitrary commands (or a ticket build) on the box.
SECURITY_TOOLS = frozenset({"nmap", "dig", "whois", "traceroute", "sslscan", "nikto", "whatweb", "tshark"})

# A throwaway worktree of the box's own checkout, in a subshell so its EXIT trap never replaces the dispatch
# wrapper's own (which clears the task record and busy flag).
_WORKTREE = ('wt="$(mktemp -d /tmp/box-trial-XXXXXX)"; '
             'trap \'git -C "$HOME/.agents" worktree remove --force "$wt" >/dev/null 2>&1; rm -rf "$wt"; '
             'git -C "$HOME/.agents" worktree prune >/dev/null 2>&1\' EXIT; '
             'git -C "$HOME/.agents" worktree add -q --detach "$wt" HEAD && cd "$wt" && '
             'echo "commit $(git rev-parse --short HEAD)" && ')


def _in_worktree(body: str) -> str:
    return f"( {_WORKTREE}{body} )"


def suite_command(workers: int = 8) -> str:
    return _in_worktree(f"{PY} -m pytest -q -n {int(workers)} -p no:cacheprovider 2>&1 | tail -n 40; "
                        "exit ${PIPESTATUS[0]}")


def vitest_command() -> str:
    # The box's own install, linked in: the worktree is at the same commit as the checkout it came from.
    return _in_worktree('ln -s "$HOME/.agents/dashboard/node_modules" dashboard/node_modules && cd dashboard && '
                        "npx vitest run 2>&1 | tail -n 40; exit ${PIPESTATUS[0]}")


def quarantine_command(cmd: list[str], cmd_timeout: int = QUARANTINE_CMD_S) -> str:
    if not cmd:
        raise ValueError("quarantine needs a command to run inside the VM (after --)")
    # vm_run joins its arguments into one shell command for the VM, so the words go as ONE argument: what the caller
    # typed after -- is exactly what the VM's shell runs (`quarantine -- 'uname -a; id'` or `quarantine -- uname -a`).
    return (f'{PY} "$HOME/.agents/lib/vm_run.py" --image quarantine --timeout {int(cmd_timeout)} -- '
            + shlex.quote(" ".join(cmd)))


def security_command(argv: list[str]) -> str:
    if not argv:
        raise ValueError("security needs a tool and its arguments (after --)")
    if argv[0] not in SECURITY_TOOLS:
        raise ValueError(f"'{argv[0]}' is not on the security trial's tool list: {', '.join(sorted(SECURITY_TOOLS))}")
    return " ".join(shlex.quote(a) for a in argv)


def retrieval_command() -> str:
    # Keeps the box's code graph current first (graphify update is incremental; graphify-out is git-ignored).
    return ('( cd "$HOME/.agents" && graphify update . >/dev/null 2>&1; '
            f'{PY} bench/retrieval_eval.py --questions /dev/stdin --repo "$HOME/.agents" )')


def read_questions(path: Path) -> str:
    """The question file's text, checked before anything is sent: missing, empty or malformed is refused here."""
    if not path.is_file():
        raise ValueError(f"no retrieval question file at {path} (it lives in the instance: bench/retrieval-questions.json)")
    text = path.read_text()
    try:
        qs = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not JSON: {exc}") from None
    if not isinstance(qs, list) or not qs:
        raise ValueError(f"{path} has no questions")
    return text


def default_questions() -> Path:
    import instance
    return instance.instance_dir() / "bench" / "retrieval-questions.json"


def plan(kind: str, args: argparse.Namespace) -> dict:
    """What to send: command, tag, timeout and any stdin. Raises ValueError for anything not in the trial."""
    if kind == "suite":
        return {"command": suite_command(args.workers), "need": "test", "timeout": args.timeout or 480}
    if kind == "vitest":
        return {"command": vitest_command(), "need": "test", "timeout": args.timeout or 120}
    if kind == "quarantine":
        cmd_t = args.timeout or QUARANTINE_CMD_S
        return {"command": quarantine_command(args.rest, cmd_t), "need": "quarantine", "timeout": VM_BOOT_S + cmd_t + 30}
    if kind == "security":
        return {"command": security_command(args.rest), "need": "security", "timeout": args.timeout or SECURITY_TIMEOUT_S}
    if kind == "retrieval":
        return {"command": retrieval_command(), "need": "bench", "timeout": args.timeout or RETRIEVAL_TIMEOUT_S,
                "stdin": read_questions(args.questions or default_questions())}
    raise ValueError(f"'{kind}' is not a box trial work type")


def run(kind: str, args: argparse.Namespace, dispatch=task_dispatch.dispatch) -> dict:
    p = plan(kind, args)
    started = time.monotonic()
    r = dispatch(p["command"], need=p["need"], timeout=p["timeout"], task_label=f"box-trial {kind}",
                 stdin=p.get("stdin"))
    out = (r.output or "").strip().splitlines()
    record = {"t": datetime.now(timezone.utc).isoformat(), "kind": kind, "need": p["need"], "timeout": p["timeout"],
              "ran_on": r.device_id, "fell_back_from": r.fell_back_from, "ok": r.ok,
              "seconds": round(time.monotonic() - started, 1), "summary": out[-1][:300] if out else None,
              "error": (r.error or "")[:300] or None}
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass
    record["output"] = r.output
    return record


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kind", choices=["suite", "vitest", "quarantine", "security", "retrieval"])
    ap.add_argument("--timeout", type=int, default=None, help="override the work type's limit (seconds)")
    ap.add_argument("--workers", type=int, default=8, help="suite: pytest-xdist workers (8 is the box's best)")
    ap.add_argument("--questions", type=Path, default=None, help="retrieval: question file (default: the instance's)")
    ap.add_argument("rest", nargs=argparse.REMAINDER, help="quarantine/security: -- COMMAND ...")
    args = ap.parse_args(argv)
    if args.rest[:1] == ["--"]:
        args.rest = args.rest[1:]
    try:
        rec = run(args.kind, args)
    except ValueError as exc:
        print(f"[box-trial] refused: {exc}", file=sys.stderr)
        return 2
    if rec["output"]:
        print(rec["output"], end="")
    where = rec["ran_on"] + (f" (fell back from {rec['fell_back_from']})" if rec["fell_back_from"] else "") \
        if rec["ran_on"] else "nowhere"
    print(f"[box-trial] {args.kind}: {'ok' if rec['ok'] else 'FAILED'} on {where} in {rec['seconds']} s"
          + (f": {rec['error']}" if rec["error"] else ""), file=sys.stderr)
    return 0 if rec["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
