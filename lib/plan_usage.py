#!/usr/bin/env python3
"""The Claude plan's own limit readings: the 5-hour and weekly meters, recorded when they change (marvin#872, slice 1).

The budget governor needs the plan's real numbers, not our token counts. Claude Code 2.1.317 gives them in two places
(docs: code.claude.com/docs/en/statusline, "Available data"; both captured live on 2026-11-03):

- the **status line**'s stdin: `rate_limits.five_hour` / `rate_limits.seven_day`, each `{used_percentage: 0-100,
  resets_at: epoch seconds}`. Pro/Max/Ultra only, and only after the session's first API response; each window may be
  absent, and Claude Code drops one once its reset passes. Interactive sessions only (`claude -p` runs no status line).
- a **stream-json** `rate_limit_event` from `claude -p --output-format stream-json --verbose`:
  `rate_limit_info.unifiedWindows.{five_hour,seven_day}.{utilization: 0-1, resetsAt, status}`.

`record` takes either shape and appends one row to ~/.claude/logs/plan-usage.jsonl only when a reading differs from
this Mac's last row. It runs from the status line (`statusline`), which Claude Code re-runs on each assistant message
and when a window resets: trigger-based, no timer of our own. Row:

    {"ts": "2026-11-03T15:30:00Z", "machine": "<registry id>", "source": "statusline" | "stream",
     "five_hour": {"used_percentage": 18.0, "resets_at": 1793737800} | null,
     "seven_day": {"used_percentage": 71.0, "resets_at": 1793941200} | null,
     "limit_hit": [] | ["five_hour"] | ["seven_day"] | ["five_hour", "seven_day"]}

Each Mac keeps its own file, like token-usage.json; `report` reads the peers' over ssh (usage_report's helpers) and
`summarize` merges them, since both Macs draw on one plan.

    plan_usage.py statusline [-- <previous status line command...>]   record stdin, then run the previous one
    plan_usage.py record                                                 record one payload (either shape) from stdin
    plan_usage.py summary [--text]                                       this week across Macs, as JSON (or text)

The status line path imports only the standard library and looks the machine up only when it writes a row.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
LOG_PATH = HOME / ".claude" / "logs" / "plan-usage.jsonl"
AGENTS = HOME / ".agents"
PY = str(AGENTS / "venv" / "bin" / "python")
SCRIPT = AGENTS / "lib" / "plan_usage.py"
WINDOWS = ("five_hour", "seven_day")
FIVE_HOURS = 5 * 3600
WEEK = 7 * 24 * 3600
SAME_WINDOW_S = 300      # two readings whose 5-hour resets are this close are the same window
NEARLY_UNUSED_PCT = 10.0  # a closed 5-hour window that peaked below this was nearly unused
STALE_AFTER_S = 6 * 3600  # a weekly reading older than this may be well below the real number
MIN_PACE_S = 3600         # pace and projection need at least an hour of the week behind them
TAIL_BYTES = 8192         # enough to hold the last row many times over
COVERAGE = ("Readings come from interactive sessions' status line. A 5-hour window used only by headless "
            "(claude -p) runs is not seen and shows as unused time.")


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(ts) -> float | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _num(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def _window(pct, resets) -> dict | None:
    pct, resets = _num(pct), _num(resets)
    if pct is None or resets is None:
        return None
    return {"used_percentage": round(pct, 1), "resets_at": int(resets)}


def normalize(payload) -> dict | None:
    """What a status-line payload or a stream-json rate_limit_event says about the plan, or None when it says nothing
    (an older Claude Code, an API-key session, before the first response). Never invents a 0. O(1) time and space."""
    if not isinstance(payload, dict):
        return None
    hit: list[str] = []
    info = payload.get("rate_limit_info") if payload.get("type") == "rate_limit_event" else None
    if isinstance(info, dict):
        source, wins = "stream", info.get("unifiedWindows") if isinstance(info.get("unifiedWindows"), dict) else {}
        out = {}
        for name in WINDOWS:
            w = wins.get(name) if isinstance(wins.get(name), dict) else {}
            u = _num(w.get("utilization"))
            out[name] = _window(None if u is None else u * 100, w.get("resetsAt"))
            if w.get("status") not in (None, "allowed", "allowed_warning"):
                hit.append(name)
        if info.get("status") not in (None, "allowed", "allowed_warning") and info.get("rateLimitType") in WINDOWS \
                and info["rateLimitType"] not in hit:
            hit.append(info["rateLimitType"])
    else:
        source, rl = "statusline", payload.get("rate_limits")
        rl = rl if isinstance(rl, dict) else {}
        out = {}
        for name in WINDOWS:
            w = rl.get(name) if isinstance(rl.get(name), dict) else {}
            out[name] = _window(w.get("used_percentage"), w.get("resets_at"))
    if not any(out.values()):
        return None
    for name in WINDOWS:
        if out[name] and out[name]["used_percentage"] >= 100 and name not in hit:
            hit.append(name)
    return {"source": source, **out, "limit_hit": [n for n in WINDOWS if n in hit]}


def this_machine() -> str:
    """This Mac's registry id (machine_profile), the same name usage_report and the dashboard use."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import machine_profile
    return machine_profile.registry_id()


def peer_machines() -> dict[str, str]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import usage_report
    return usage_report.peer_machines()


def _last_row(f) -> dict | None:
    """The last whole row of an open file, read from its tail: O(1) time and space in the file's length."""
    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(max(0, size - TAIL_BYTES))
    for line in reversed(f.read().splitlines()):
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict):
            return doc
    return None


def _changed(reading: dict, last: dict | None) -> bool:
    """A present window that differs from the last row, or a new hit. An absent window is no reading, not a change."""
    if last is None:
        return True
    for name in WINDOWS:
        if reading[name] is not None and reading[name] != last.get(name):
            return True
    return bool(set(reading["limit_hit"]) - set(last.get("limit_hit") or []))


def record(payload, now: float | None = None, path: Path | None = None, machine: str | None = None) -> dict | None:
    """Append one row when `payload` carries a reading that differs from this file's last row; return it, else None.
    Locked, so two sessions rendering at once write one row. O(1) time and space: only the file's tail is read."""
    reading = normalize(payload)
    if reading is None:
        return None
    path = Path(path or LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        if not _changed(reading, _last_row(f)):
            return None
        f.seek(0, os.SEEK_END)
        if f.tell():
            f.seek(f.tell() - 1)
            torn = f.read(1) != "\n"
            f.seek(0, os.SEEK_END)
            if torn:
                f.write("\n")  # a cut-off last line must not swallow this row
        row = {"ts": iso(time.time() if now is None else now), "machine": machine or this_machine(), **reading}
        f.write(json.dumps(row) + "\n")
        return row


def statusline_main(stdin: str, next_command: list[str], path: Path | None = None, machine: str | None = None,
                    now: float | None = None) -> int:
    """The status line: record the plan reading, then run the status line that was there before (same stdin) so its
    output shows unchanged. Never fails the status line: a bad payload or an unwritable log is ignored."""
    try:
        record(json.loads(stdin), now=now, path=path, machine=machine)
    except Exception:  # noqa: BLE001  (the status line must keep rendering whatever happens here)
        pass
    if next_command:
        try:
            sys.stdout.flush()
            subprocess.run(next_command, input=stdin, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
    return 0


def _ours() -> str:
    return f"{PY} {SCRIPT} statusline".replace(str(HOME) + "/", "$HOME/")


def statusline_setting(existing: dict | None) -> dict:
    """The `statusLine` block for settings.json: ours, wrapping whatever status line was already set so it keeps
    working. Idempotent. Home written as $HOME, since settings.json is synced to Macs whose homes differ."""
    existing = dict(existing or {})
    cmd = existing.get("command") if existing.get("type") == "command" else None
    if cmd and "lib/plan_usage.py statusline" in cmd:
        return existing
    wrapped = f"{_ours()} -- /bin/sh -c {shlex.quote(cmd)}" if cmd else _ours()
    return {**existing, "type": "command", "command": wrapped}


def load_rows(path: Path) -> list[dict]:
    """Every whole row in a log; torn or foreign lines are skipped. O(n) time and space in the file's rows."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    return _parse_lines(text)


def _parse_lines(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict):
            out.append(doc)
    return out


def _clean(rows) -> list[tuple[float, str, dict | None, dict | None, list]]:
    """(time, machine, five_hour, seven_day, hits) for each usable row, oldest first. O(n log n)."""
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        t = _epoch(r.get("ts"))
        if t is None:
            continue
        wins = [_window(*(w.get("used_percentage"), w.get("resets_at"))) if isinstance(w, dict) else None
                for w in (r.get("five_hour"), r.get("seven_day"))]
        hits = r.get("limit_hit") if isinstance(r.get("limit_hit"), list) else []
        if any(wins):
            out.append((t, str(r.get("machine") or "unknown"), wins[0], wins[1], hits))
    out.sort(key=lambda x: x[0])
    return out


def _week(clean, now: float) -> dict:
    """The current week's meter. Within one week it only rises, so the highest reading for the latest reset wins:
    an idle session re-sends the number it last saw, which may be older than another Mac's (seen 2026-11-03). O(n)."""
    latest = next((c for c in reversed(clean) if c[3] is not None), None)
    if latest is None or latest[3]["resets_at"] <= now:
        return {"status": "not_enough_data"}
    resets_now = latest[3]["resets_at"]
    same_week = [c for c in clean if c[3] is not None and c[3]["resets_at"] == resets_now]
    t, _, _, seven, hits = max(same_week, key=lambda c: (c[3]["used_percentage"], c[0]))
    pct, resets = seven["used_percentage"], seven["resets_at"]
    start = resets - WEEK
    elapsed_s = min(max(now - start, 0), WEEK)
    frac = elapsed_s / WEEK
    enough = elapsed_s >= MIN_PACE_S
    projected = round(pct / frac, 1) if enough else None
    return {"status": "ok", "used_percentage": pct, "started_at": iso(start), "resets_at": iso(resets),
            "elapsed_fraction": round(frac, 3), "expected_percentage": round(frac * 100, 1),
            "pace": round(pct / (frac * 100), 2) if enough else None, "projected_at_reset": projected,
            "left_at_reset_percentage": None if projected is None else round(max(0.0, 100 - projected), 1),
            "hit": "seven_day" in hits or pct >= 100,
            "reading_at": iso(t), "reading_age_min": round((now - t) / 60), "stale": now - t > STALE_AFTER_S}


def _five_hour_windows(clean, now: float) -> list[dict]:
    """5-hour windows, one per reset time (readings within SAME_WINDOW_S of each other merge), oldest first."""
    groups: list[dict] = []
    for t, machine, five, _, hits in sorted((c for c in clean if c[2]), key=lambda c: c[2]["resets_at"]):
        resets = five["resets_at"]
        g = groups[-1] if groups and resets - groups[-1]["_last"] <= SAME_WINDOW_S else None
        if g is None:
            g = {"_reset": resets, "_last": resets, "peak": 0.0, "hit": False, "readings": 0, "machines": set()}
            groups.append(g)
        g["_last"] = resets
        g["peak"] = max(g["peak"], five["used_percentage"])
        g["hit"] = g["hit"] or "five_hour" in hits or five["used_percentage"] >= 100
        g["readings"] += 1
        g["machines"].add(machine)
    return [{"started_at": iso(g["_reset"] - FIVE_HOURS), "resets_at": iso(g["_reset"]),
             "peak_percentage": g["peak"], "hit": g["hit"], "open": g["_reset"] > now, "readings": g["readings"],
             "machines": sorted(g["machines"]), "_start": g["_reset"] - FIVE_HOURS, "_end": g["_reset"]}
            for g in groups]


def _unused(windows, observed_from: float, now: float) -> dict:
    """Time from `observed_from` to now when no 5-hour window was open, as whole 5-hour blocks that could have run.
    O(w log w) in the windows."""
    gaps, cursor = [], observed_from
    for s, e in sorted((w["_start"], min(w["_end"], now)) for w in windows):
        if s > cursor:
            gaps.append((cursor, min(s, now)))
        cursor = max(cursor, e)
    if now > cursor:
        gaps.append((cursor, now))
    gaps = [(a, b) for a, b in gaps if b > a]
    out = [{"from": iso(a), "to": iso(b), "hours": round((b - a) / 3600, 1), "windows": int((b - a) // FIVE_HOURS)}
           for a, b in gaps]
    return {"observed_from": iso(observed_from), "windows": sum(g["windows"] for g in out),
            "hours": round(sum(b - a for a, b in gaps) / 3600, 1), "gaps": out}


def summarize(rows, now: float | None = None) -> dict:
    """This week across every machine's rows: weekly used and pace, 5-hour windows that hit the limit, closed ones
    that were nearly unused, and the time no window ran. Missing readings are "not_enough_data", never 0%.
    O(n log n) time and O(n) space in the rows."""
    now = time.time() if now is None else now
    clean = _clean(rows)
    week = _week(clean, now)
    week_start = _epoch(week["started_at"]) if week["status"] == "ok" else now - WEEK
    windows = [w for w in _five_hour_windows(clean, now) if w["_end"] > week_start]
    in_week = [c for c in clean if c[0] >= week_start]
    observed_from = max(week_start, clean[0][0]) if clean else None
    five = {"current": next((w for w in windows if w["open"]), None), "windows": windows,
            "hit": [w for w in windows if w["hit"]],
            "nearly_unused": [w for w in windows if not w["open"] and w["peak_percentage"] < NEARLY_UNUSED_PCT],
            "unused": _unused(windows, observed_from, now) if observed_from is not None and in_week else None}
    if week["status"] != "ok":
        binding = "unknown"
    elif week["hit"]:
        binding = "seven_day"
    elif five["hit"] and (week["projected_at_reset"] or 0) < 100:
        binding = "five_hour"
    else:
        binding = "none"
    out = {"generated_at": iso(now), "status": "ok" if clean else "not_enough_data", "week": week,
           "five_hour": five, "binding_limit": binding, "coverage": COVERAGE}
    return json.loads(json.dumps(out, default=list), object_hook=_drop_private)


def _drop_private(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


def report(now: float | None = None, ssh=None) -> dict:
    """This Mac's rows plus each peer's, read over ssh the way usage_report reads token-usage.json, summarised.
    A peer with no file answered (0 rows); one that didn't answer is `reachable: false`. O(n) in all rows."""
    if ssh is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import usage_report
        ssh = usage_report.default_ssh
    local = load_rows(LOG_PATH)
    machines = [{"machine": this_machine(), "this": True, "reachable": True, "rows": len(local)}]
    every = list(local)
    for dev, host in peer_machines().items():
        try:
            peer = _parse_lines(ssh(host, f"cat ~/.claude/logs/{LOG_PATH.name}"))
            reachable = True
        except FileNotFoundError:
            peer, reachable = [], True
        except (OSError, ValueError, subprocess.SubprocessError):
            peer, reachable = [], False
        machines.append({"machine": dev, "this": False, "reachable": reachable, "rows": len(peer)})
        every += peer
    return {**summarize(every, now=now), "machines": machines}


def as_text(s: dict) -> str:
    w, f = s["week"], s["five_hour"]
    lines = []
    if w["status"] == "ok":
        pace = f", pace {w['pace']}x (projected {w['projected_at_reset']}% at reset)" if w["pace"] is not None else ""
        lines.append(f"Week: {w['used_percentage']}% used, {w['expected_percentage']}% of the week gone{pace}; "
                     f"resets {w['resets_at']}" + (" [reading stale]" if w["stale"] else ""))
    else:
        lines.append("Week: not enough data yet")
    if f["current"]:
        lines.append(f"5-hour window now: {f['current']['peak_percentage']}%, resets {f['current']['resets_at']}")
    lines.append(f"5-hour windows this week: {len(f['windows'])}, hit the limit: {len(f['hit'])}, "
                 f"nearly unused: {len(f['nearly_unused'])}")
    if f["unused"]:
        lines.append(f"No window running: {f['unused']['hours']} h ({f['unused']['windows']} whole 5-hour windows) "
                     f"since {f['unused']['observed_from']}")
    lines.append(f"Binding limit: {s['binding_limit']}")
    lines += [f"  {m['machine']}: unreachable" for m in s.get("machines", []) if not m["reachable"]]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if argv[:1] == ["statusline"]:
        rest = argv[1:]
        return statusline_main(sys.stdin.read(), rest[1:] if rest[:1] == ["--"] else [])
    if argv == ["record"]:
        try:
            row = record(json.loads(sys.stdin.read()))
        except ValueError:
            row = None
        print(json.dumps(row))
        return 0
    if argv[:1] == ["summary"]:
        s = report()
        print(as_text(s) if "--text" in argv[1:] else json.dumps(s, indent=2))
        return 0
    print("usage: plan_usage.py statusline [-- <command...>] | record | summary [--text]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
