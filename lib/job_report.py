#!/usr/bin/env python3
"""Run any scheduled job as a job_events run (ADR 0083, marvin#1123): every launchd job reports, honestly.

    job_report.py <job> [--label TEXT] -- <command> [args...]

The command runs unchanged: its stdout and stderr still go to the job's own launchd logs, line by line, and its exit status is
passed on. The run is recorded in ~/.claude/logs/jobs/<job>.json (what Activity, Health and the Loops panel read) and
counts as FAILED when:
- it exits non-zero, or is killed;
- a line starts with "REFUSING" (code-sync's and the launcher's refusal; it used to exit 0 and look green);
- a line says it skipped because of an error ("skipped ... error", "skipping ... failed").
A run that skips on purpose ("skipped: the Mini already ran today") stays a pass.

job_units wraps every scheduled job in config/jobs with this, unless the job declares "reports_itself" (its script
already uses job_events.reported) or is a keep-alive service (a server never finishes, so it has no runs).
Complexity: O(output lines), streamed (one thread per stream); memory holds only the last line.
"""
from __future__ import annotations

import re
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import job_events  # noqa: E402

JOB_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
REFUSING_RE = re.compile(r"^\s*(\S+\s+)?REFUSING\b")
ERROR_SKIP_RE = re.compile(r"\bskip(?:ped|ping)?\b.*\b(error|failed|failure|exception|traceback)\b", re.I)


def failure_in(line: str) -> str | None:
    """Why this output line makes the run a failure, or None. Pure."""
    if REFUSING_RE.match(line):
        return line.strip()[:200]
    if ERROR_SKIP_RE.search(line):
        return line.strip()[:200]
    return None


def run(job: str, command: list[str], label: str | None = None, directory: Path | None = None,
        out=None, err=None) -> int:
    if not JOB_RE.match(job or ""):
        print(f"job_report: not a job name: {str(job)[:60]!r}", file=sys.stderr)
        return 2
    if not command:
        print("job_report: no command after --", file=sys.stderr)
        return 2
    out = out or sys.stdout
    with job_events.job_run(job, label or job.replace("-", " ").capitalize(), directory=directory) as rec:
        seen = {"reason": None, "last": ""}
        try:
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    errors="replace", bufsize=1)
        except OSError as exc:
            rec.fail(f"could not start: {exc}"[:300])
            print(f"job_report: could not start {command[0]}: {exc}", file=sys.stderr)
            return 127

        def pump(src, dst):
            for line in src:
                dst.write(line)
                dst.flush()
                if line.strip():
                    seen["last"] = line.strip()[:200]
                seen["reason"] = seen["reason"] or failure_in(line)

        side = threading.Thread(target=pump, args=(proc.stderr, err or sys.stderr), daemon=True)
        side.start()
        pump(proc.stdout, out)
        side.join()
        reason, last = seen["reason"], seen["last"]
        rc = proc.wait()
        if rc != 0:
            rec.fail(f"exited with status {rc}" + (f": {last}" if last else ""))
        elif reason:
            rec.fail(reason)
        rec.summary(last)
    return rc if rc >= 0 else 128 - rc


def main(argv: list[str]) -> int:
    if "--" not in argv:
        print("usage: job_report.py <job> [--label TEXT] -- <command> [args...]", file=sys.stderr)
        return 2
    i = argv.index("--")
    head, command = argv[:i], argv[i + 1:]
    label = None
    if len(head) == 3 and head[1] == "--label":
        label = head[2]
    elif len(head) != 1:
        print("usage: job_report.py <job> [--label TEXT] -- <command> [args...]", file=sys.stderr)
        return 2
    return run(head[0], command, label)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
