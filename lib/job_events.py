#!/usr/bin/env python3
"""Run log for background jobs, so the dashboard's Activity tab can show what each one
is doing right now and how its last runs went. Per ticket the pipeline already has
`ticket_stages`; this is the same idea for jobs that aren't tickets (catalog refresh,
tidy agent, the hourly pipeline scan, dashboard rebuild...).

    with job_run("project-catalog") as run:
        run.step("GitHub repos", "18 found")
        ...
        run.summary("30 projects")

One file per job (~/.claude/logs/jobs/<job>.json) with its last KEEP_RUNS runs, rewritten
after every step so progress is visible mid-run. Recording is strictly best-effort: it must
never break, slow or change the job it observes. Per machine (logs are not synced).
"""
from __future__ import annotations
import fcntl
import functools
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

JOBS_DIR = Path.home() / ".claude" / "logs" / "jobs"
KEEP_RUNS = 20
CRASHED_AFTER_S = 30 * 60  # a run "in progress" this long with no finish is a crashed run, not a slow one


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts):
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


class _Run:
    def __init__(self, job: str, directory: Path, label: str | None):
        self._file = directory / f"{job}.json"
        self._dir = directory
        self._job = job
        self._label = label
        self.record = {"id": uuid.uuid4().hex[:8], "status": "running", "started_at": _now().isoformat(),
                       "finished_at": None, "steps": [], "summary": "", "error": ""}
        self._ok = True
        self._failed = ""

    def _mutate(self, fn) -> None:
        """Read-modify-write under a lock; any failure disables recording for this run."""
        if not self._ok:
            return
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with open(self._dir / f".{self._job}.lock", "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    doc = json.loads(self._file.read_text())
                    if not isinstance(doc.get("runs"), list):
                        raise ValueError("bad shape")
                except (OSError, ValueError):
                    doc = {"job": self._job, "label": self._label or self._job, "runs": []}
                doc["label"] = self._label or doc.get("label") or self._job
                runs = [r for r in doc["runs"] if r.get("id") != self.record["id"]]
                fn(self.record)
                runs.append(self.record)
                doc["runs"] = runs[-KEEP_RUNS:]
                tmp = self._file.with_suffix(".tmp")
                tmp.write_text(json.dumps(doc))
                os.replace(tmp, self._file)
        except Exception:  # noqa: BLE001 -- observing must never break the job
            self._ok = False

    def step(self, name: str, detail: str = "") -> None:
        def apply(r):
            entry = {"step": name, "detail": detail, "at": _now().isoformat()}
            if r["steps"] and r["steps"][-1]["step"] == name:
                r["steps"][-1] = entry  # same step reporting again (started -> done): update in place
            else:
                r["steps"].append(entry)
        self._mutate(apply)

    def fail(self, error: str) -> None:
        """Mark this run failed without raising -- for jobs that handle their own failure."""
        self._failed = error

    def summary(self, text: str) -> None:
        self._mutate(lambda r: r.update(summary=text))

    def _finish(self, status: str, error: str = "") -> None:
        self._mutate(lambda r: r.update(status=status, finished_at=_now().isoformat(), error=error))


@contextmanager
def job_run(job: str, label: str | None = None, directory: Path | None = None):
    run = _Run(job, directory or JOBS_DIR, label)
    run._mutate(lambda r: None)  # appear immediately as "running"
    try:
        yield run
    except SystemExit as e:
        # sys.exit(0) / sys.exit() is how many scripts end normally; only a non-zero code is a failure
        if e.code in (None, 0) and not run._failed:
            run._finish("passed")
        else:
            run._finish("failed", run._failed or f"exited with status {e.code}")
        raise
    except BaseException as e:  # noqa: BLE001
        run._finish("failed", f"{type(e).__name__}: {e}")
        raise
    else:
        run._finish("failed" if run._failed else "passed", run._failed)


_CURRENT: list = []  # the active run(s), so any code can call step() without threading `run` through


def job_id(default: str) -> str:
    """launchd names the job it starts in XPC_SERVICE_NAME ("com.marvin.research-colony"), which is
    how one script run under two schedules (daily-digest / research-colony) gets two run logs. A
    terminal session sets it to something else, so we fall back to the script's own name."""
    label = os.environ.get("XPC_SERVICE_NAME", "")
    if label.startswith("com."):
        return label.split(".", 2)[2]
    return default


def step(name: str, detail: str = "") -> None:
    """Report a step on the current run, if there is one. Safe to call anywhere."""
    if _CURRENT:
        _CURRENT[-1].step(name, detail)


def reported(default_name: str, label: str | None = None):
    """Decorator for a job's entry point: records the run (start, steps, outcome) under the launchd
    label's name. One line per script; the script may call `job_events.step(...)` for detail."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            jid = job_id(default_name)
            with job_run(jid, label or jid.replace("-", " ").capitalize()) as run:
                _CURRENT.append(run)
                try:
                    return fn(*args, **kwargs)
                except SystemExit as e:
                    if e.code not in (None, 0):
                        run.fail(f"exited with status {e.code}")
                    raise
                finally:
                    _CURRENT.pop()
        return wrapper
    return deco


def status_of(doc: dict, now: datetime | None = None) -> str:
    """running | idle | failed | crashed | never -- what the dashboard shows as the job's state."""
    runs = doc.get("runs") or []
    if not runs:
        return "never"
    last = runs[-1]
    if last.get("status") == "running":
        started = _parse(last.get("started_at"))
        age = ((now or _now()) - started).total_seconds() if started else CRASHED_AFTER_S + 1
        return "running" if age <= CRASHED_AFTER_S else "crashed"
    return "failed" if last.get("status") == "failed" else "idle"
