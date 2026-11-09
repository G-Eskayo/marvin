#!/usr/bin/env python3
"""The one alert path (ADR 0083, marvin#1123): every way MARVIN tells the owner something goes through `_fire`.

Channels, each tried on its own so one failing never stops another, and each reporting its REAL result:

- **desktop**: this Mac's banner (`notify.desktop`: terminal-notifier with a click action, else osascript).
- **dashboard**: a POST to the local webhook server's `/mr-ready`, so an open dashboard refreshes at once; the alert
  itself is in the `alerts` run log, which Vitals' "Can MARVIN reach you?" row reads.
- **phone**: an empty slot until MARVIN Mobile's Apple push (#958) fills it (`phone_notify`). Gil's answer on #1123:
  phone alerts wait for #958. The old headless `claude -p` PushNotification call is gone; it spent plan usage per
  alert.

Every alert is recorded as a `job_events` run of job `alerts` (one step per channel; the run fails when no channel
delivered), and as a "Told the owner" step on the caller's own run, so nothing logs "told" that wasn't.

`alert_on_change` is the shared memory for "alert when it turns bad, not on every poll": it alerts when an item turns
bad, changes from one bad state to another, or clears, and reminds once a day while it stays bad.

    mr_notification.py test          # send a test alert; prints each channel's result as JSON
    mr_notification.py reach         # the last alerts (what Vitals shows), as JSON
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import notify as _notify  # noqa: E402

DASHBOARD_REFRESH_URL = "http://localhost:7878/mr-ready"
DASHBOARD_REFRESH_TIMEOUT_S = 3
CHANNELS = ("desktop", "dashboard", "phone")
PHONE_NOT_SET_UP = "not set up (waits for MARVIN Mobile push, #958)"
ALERTS_JOB = "alerts"
GOOD_STATES = ("ok", "works", "green", "yellow")


def _default_dashboard_refresh_ping() -> None:
    urllib.request.urlopen(
        urllib.request.Request(DASHBOARD_REFRESH_URL, data=b"{}", method="POST"),
        timeout=DASHBOARD_REFRESH_TIMEOUT_S,
    )


desktop_notify: Callable = _notify.desktop
dashboard_refresh_ping: Callable = _default_dashboard_refresh_ping
phone_notify: Callable | None = None  # #958 plugs MARVIN Mobile's push in here: phone_notify(title, message, open_target)


def _try(send: Callable[[], object]) -> str:
    try:
        r = send()
        return r if isinstance(r, str) and r.startswith("sent") else "sent"
    except Exception as exc:  # noqa: BLE001 -- one channel failing never stops the others
        return f"failed: {type(exc).__name__}: {exc}"[:200]


def _record(title: str, results: dict, delivered: list[str]) -> None:
    """The alerts run log and the caller's own run. Best effort: recording never breaks telling."""
    try:
        import job_events
        summary = f"told the owner by {', '.join(delivered)}" if delivered else "NOT delivered on any channel"
        job_events.step("Told the owner", f"{summary}: {title}"[:200])
        with job_events.job_run(ALERTS_JOB, "Alerts to the owner") as run:
            for ch in CHANNELS:
                run.step(ch, results[ch])
            run.summary(title[:200])
            if not delivered:
                run.fail("no channel delivered: " + "; ".join(f"{c} {results[c]}" for c in CHANNELS))
    except Exception:  # noqa: BLE001
        pass


def _fire(title: str, message: str, open_target: str | None = None, desktop_result: str | None = None) -> dict:
    """Send one alert on every channel. Never raises. `desktop_result`: the caller already showed its own banner
    (peer care's actionable one) and says how it went. Returns {"channels": {name: result}, "delivered": [...]} plus
    the older flat keys its first callers read."""
    title, message = str(title or "MARVIN")[:200], str(message or "")[:1000]
    results = {
        "desktop": desktop_result or _try(lambda: desktop_notify(title, message, open_target=open_target)),
        "dashboard": _try(dashboard_refresh_ping),
        "phone": PHONE_NOT_SET_UP if phone_notify is None else _try(lambda: phone_notify(title, message, open_target)),
    }
    delivered = [c for c in CHANNELS if results[c].startswith("sent")]
    _record(title, results, delivered)
    return {
        "channels": results,
        "delivered": delivered,
        "desktop_sent": "desktop" in delivered,
        "push_attempted": phone_notify is not None,
        "push_succeeded": "phone" in delivered,
        "dashboard_ping_attempted": True,
        "dashboard_ping_succeeded": "dashboard" in delivered,
    }


def told_text(result) -> str:
    """One line for a log: what the alert path really did (#1123), never a fixed "told the owner"."""
    if not isinstance(result, dict):
        return "told the owner (result not reported)"
    if result.get("delivered"):
        return f"told the owner by {', '.join(result['delivered'])}"
    why = "; ".join(f"{c} {r}" for c, r in (result.get("channels") or {}).items()) or result.get("error") or "no result"
    return f"COULD NOT tell the owner ({why})"[:300]


def notify_mr_ready(ticket_ref: str, pr_url: str) -> dict:
    """A newly raised MR. Never raises."""
    return _fire("MARVIN: MR ready for review", f"MR ready for review: {ticket_ref} -> {pr_url}", pr_url)


def notify_needs_you(ticket_ref: str, why: str, url: str | None = None) -> dict:
    """A ticket the pipeline stopped retrying and handed to Gil (it shows in the dashboard's Needs you). Never raises."""
    why = " ".join(str(why or "no reason recorded").split())[:200]
    return _fire("MARVIN: a ticket needs you", f"Needs you: {ticket_ref}: {why}", url)


def notify_regression(title: str, message: str, url: str | None = None) -> dict:
    """The incident ladder (incident_ladder.py): a solved problem came back. Never raises."""
    return _fire(title, " ".join(str(message or "").split())[:300], url)


# ── alert on a change, remind once a day ─────────────────────────────────────────────────────────────────────────

def changes_due(items: list[dict], last: dict, bad: tuple[str, ...], today: str) -> tuple[list[dict], dict]:
    """Pure. items: [{key, state, ...}]. Returns (the items to alert about, each tagged with `why`; the new memory).

    - turned bad, or moved from one bad state to another: why="new"
    - still bad, and not alerted today: why="reminder"
    - was bad, now a good state: why="cleared"
    Any other state (unreachable, unknown, None) leaves the memory as it was, so a blip can't re-send an alert when it
    clears. Memory: {key: {"state": s, "day": "YYYY-MM-DD"}}. The older {key: "state"} form (accounts-alerted.json)
    reads as alerted today, so upgrading never sends a burst."""
    due, seen = [], {}
    for k, v in last.items():
        if isinstance(v, dict) and isinstance(v.get("state"), str):
            seen[k] = v
        elif isinstance(v, str):
            seen[k] = {"state": v, "day": today}
    for it in items:
        if not isinstance(it, dict):
            continue
        key, state = it.get("key"), it.get("state")
        if not isinstance(key, str) or not key:
            continue
        before = seen.get(key) or {}
        was = before.get("state")
        if state in bad:
            if was != state:
                due.append({**it, "why": "new"})
            elif before.get("day") != today:
                due.append({**it, "why": "reminder"})
            seen[key] = {"state": state, "day": today if (was != state or before.get("day") != today) else before["day"]}
        elif state in GOOD_STATES:
            if was in bad:
                due.append({**it, "why": "cleared"})
            if key in seen:
                seen[key] = {"state": state, "day": today}
    return due, seen


def _read_memory(path: Path) -> dict:
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_memory(path: Path, memory: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(memory, indent=1, sort_keys=True))
    os.replace(tmp, path)


_HEADS = {"new": "turned red", "reminder": "still red", "cleared": "back to normal"}


def alert_on_change(items: list[dict], path: Path, bad: tuple[str, ...] = ("red",),
                    message: Callable[[dict], tuple[str, str]] | None = None, fire: Callable | None = None,
                    today: date | None = None, batch_over: int | None = None) -> list[dict]:
    """Alert on what changed since the memory at `path`, then remember. Returns the items alerted about.

    message(item) -> (title, body); the default uses item["title"] and item["message"]. With `batch_over`=n, more than
    n alerts of one kind (new, reminder, cleared) go out as one summary instead of n banners."""
    fire = fire or (lambda t, m: _fire(t, m))
    message = message or (lambda it: (it.get("title") or it["key"], it.get("message") or ""))
    due, seen = changes_due(items, _read_memory(path), bad, (today or date.today()).isoformat())
    groups: dict[str, list[dict]] = {}
    for it in due:
        groups.setdefault(it["why"], []).append(it)
    for why in ("new", "cleared", "reminder"):
        its = groups.get(why) or []
        if batch_over is not None and len(its) > batch_over:
            names = ", ".join(str(message(i)[0]).removeprefix("MARVIN: ") for i in its[:6]) + (" …" if len(its) > 6 else "")
            sends = [(f"MARVIN: {len(its)} things {_HEADS[why]}", names)]
        else:
            sends = []
            for i in its:
                title, body = message(i)
                sends.append((f"{title} (daily reminder)" if why == "reminder" else title, body))
        for title, body in sends:
            try:
                fire(title, body)
            except Exception:  # noqa: BLE001 -- one alert failing never stops the others or the caller
                pass
    _write_memory(path, seen)
    return due


# ── what Vitals shows: "Can MARVIN reach you?" ─────────────────────────────────────────────────────────────────

def reach(directory: Path | None = None) -> dict:
    """The last alerts and what each channel did, newest first. Read-only."""
    import job_events
    path = (directory or job_events.JOBS_DIR) / f"{ALERTS_JOB}.json"
    try:
        runs = json.loads(path.read_text()).get("runs") or []
        runs = runs if isinstance(runs, list) else []
    except (OSError, ValueError, AttributeError):
        runs = []
    recent = []
    for r in reversed(runs[-5:]):
        if not isinstance(r, dict):
            continue
        steps = {s.get("step"): str(s.get("detail", "")) for s in r.get("steps") or [] if isinstance(s, dict)}
        recent.append({"at": r.get("finished_at") or r.get("started_at"), "title": str(r.get("summary", ""))[:200],
                       "status": r.get("status"), "channels": {c: steps.get(c, "") for c in CHANNELS}})
    last = recent[0] if recent else None
    verdict = "unknown" if last is None else "unreachable" if last["status"] == "failed" else "reachable"
    return {"verdict": verdict, "last": last, "recent": recent,
            "phone": PHONE_NOT_SET_UP if phone_notify is None else "set up"}


def main(argv: list[str]) -> int:
    if argv == ["test"]:
        stamp = datetime.now(timezone.utc).astimezone().strftime("%H:%M")
        out = _fire("MARVIN: test alert", f"Sent from Vitals at {stamp}. If you can read this, MARVIN can reach you here.")
        print(json.dumps(out))
        return 0 if out["delivered"] else 1
    if argv == ["reach"]:
        print(json.dumps(reach()))
        return 0
    print("usage: mr_notification.py test | reach", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
