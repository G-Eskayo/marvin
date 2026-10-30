#!/usr/bin/env python3
"""Health reads each pull-only node's mirror from a Mac (marvin#910, ADR 0069).

A pull-only node (mac-mini-2012: Linux, never writes to the Macs or to ~/.claude) keeps its ~/.agents and ~/.claude
current with `code_sync.py mirror`, and records each failure only in its own ~/.claude/logs/errors.jsonl. From
2026-10-26 to 10-30 every fetch failed (a dead Tailscale IP in its ssh config) and Health on the Mini never said so:
the fetch-based repo probe re-ran the box's broken fetch and hung into "unverifiable", and the failures were one more
line in a "Recent errors" row that was red for other reasons. This check names it: one row per pull-only node.

The Mac reads the box over ssh with one fixed script that only reads (no fetch, no writes). Then it judges:
  behind   the box's HEAD for each repo against this Mac's origin/main. "Since when" is when the commits the box
           lacks ARRIVED here (this Mac's origin/main reflog), not their commit dates: code-sync fast-forwards
           days-old laptop commits. Yellow at 30 min, red at 2 h; the mirror runs every 10 min.
  failing  `sync:mirror` entries in the last hour by the box's own clock, so skew neither hides nor prolongs them.
           Red at 3, yellow at 1.
Anything it can't read is yellow, never green. An offline box is not a sync failure: it's yellow here and the
machine:<id> row says it is down; an asleep one is `asleep`.

O(1) ssh call and O(R) local git calls per node (R = 2 repos). The box's log tail is bounded (TAIL_LINES).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cron_health import SSH_OPTS  # noqa: E402

HOME = Path.home()
REPOS = (".agents", ".claude")
REF = "refs/remotes/origin/main"
ERRORS_MARK = "--- sync:mirror errors ---"
TAIL_LINES = 5000
WINDOW_S = 3600            # failures counted over the last hour on the box's clock
FUTURE_SKEW_S = 300        # an entry stamped this far past the box's "now" was written while its clock was wrong
FAILURES_RED = 3           # half of an hour's six mirror runs
BEHIND_YELLOW_S = 30 * 60
BEHIND_RED_S = 2 * 3600
REFLOG_DEPTH = 500
SSH_TIMEOUT_S = 20
GIT_TIMEOUT_S = 10
_SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")

# Read-only by construction (tested): prints the box's clock, each repo's HEAD, and its recent mirror errors.
PROBE_SCRIPT = f'''
echo "now=$(date +%s)"
for r in {" ".join(REPOS)}; do
  h=""
  [ -e "$HOME/$r/.git" ] && h=$(git -C "$HOME/$r" rev-parse --verify -q HEAD 2>/dev/null)
  echo "head:$r=$h"
done
echo "{ERRORS_MARK}"
tail -n {TAIL_LINES} "$HOME/.claude/logs/errors.jsonl" 2>/dev/null | grep -F 'sync:mirror'
true
'''


def pull_only(devices: dict) -> dict:
    """Registered devices that aren't Macs (machine_profile.remote_macs: no `os` means a Mac)."""
    return {k: v for k, v in devices.items() if v.get("os", "macos") != "macos"}


# ── what the box sent ──────────────────────────────────────────────────────────────────────────────────────────────

def parse_probe(text: str) -> dict:
    """{"now": box epoch seconds | None, "heads": {rel: sha | ""}, "errors": [entry dicts]}. Raises ValueError when the
    output isn't the probe's (empty, a banner, cut off before the marker): that is "couldn't read", never "clean"."""
    lines = (text or "").splitlines()
    if ERRORS_MARK not in lines:
        raise ValueError("the box's answer was empty or cut off")
    cut = lines.index(ERRORS_MARK)
    now, heads = None, {}
    for line in lines[:cut]:
        key, sep, value = line.partition("=")
        if not sep:
            continue
        if key == "now":
            now = float(value) if value.strip().isdigit() else None
        elif key.startswith("head:"):
            heads[key[5:]] = value.strip()
    errors = []
    for line in lines[cut + 1:]:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("source") == "sync:mirror":
            errors.append(e)
    return {"now": now, "heads": heads, "errors": errors}


def _epoch(t) -> float | None:
    if not isinstance(t, str):
        return None
    try:
        d = datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()


def _recent(errors: list[dict], box_now: float | None, fallback_now: float | None = None,
            window_s: float = WINDOW_S) -> list[dict]:
    now = box_now if box_now is not None else fallback_now
    if now is None:
        now = datetime.now(timezone.utc).timestamp()
    out = []
    for e in errors:
        t = _epoch(e.get("t")) if isinstance(e, dict) and e.get("source") == "sync:mirror" else None
        if t is not None and now - window_s <= t <= now + FUTURE_SKEW_S:
            out.append(e)
    return out


def recent_failures(errors: list[dict], box_now: float | None, fallback_now: float | None = None,
                    window_s: float = WINDOW_S) -> int:
    """Mirror failures in the last `window_s` (an hour) by the box's clock (this Mac's if the box's is unread)."""
    return len(_recent(errors, box_now, fallback_now, window_s))


# ── how far behind, measured here ──────────────────────────────────────────────────────────────────────────────────

def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=GIT_TIMEOUT_S)


def local_lag(repo: Path, box_head: str) -> dict:
    """{"known", "missing", "since"} for a box at `box_head` against this Mac's copy of `repo`. known=False when the
    head isn't a commit this Mac has (its copy may be older, or the box sent junk: only a bare sha is ever passed to
    git). since = epoch when the oldest commit the box still lacks arrived here."""
    unknown = {"known": False, "missing": 0, "since": None}
    if not _SHA.fullmatch(box_head or "") or not Path(repo).is_dir():
        return unknown
    if _git(repo, "cat-file", "-e", f"{box_head}^{{commit}}").returncode != 0:
        return unknown
    if _git(repo, "rev-parse", "--verify", "-q", REF).returncode != 0:
        return unknown
    proc = _git(repo, "rev-list", f"{box_head}..{REF}")
    if proc.returncode != 0:
        return unknown
    missing = set(proc.stdout.split())
    if not missing:
        return {"known": True, "missing": 0, "since": None}
    return {"known": True, "missing": len(missing), "since": _missing_since(repo, box_head, missing)}


def _missing_since(repo: Path, box_head: str, missing: set[str]) -> float | None:
    # Newest first: each reflog entry is where this Mac's origin/main moved, and when. The run of entries the box
    # doesn't contain ends at the first one it does; the oldest entry in that run is when it started lagging.
    log = _git(repo, "log", "-g", "-n", str(REFLOG_DEPTH), "--format=%H%x09%gd", "--date=unix", REF)
    since = None
    for line in log.stdout.splitlines() if log.returncode == 0 else []:
        sha, _, sel = line.partition("\t")
        m = re.search(r"@\{(\d+)\}$", sel)
        if sha not in missing or not m:
            break
        since = float(m.group(1))
    if since is not None:
        return since
    # No reflog (expired, or a fresh clone): the oldest missing commit's date, as the Mac repo check does.
    fp = _git(repo, "log", "--first-parent", "--format=%ct", f"{box_head}..{REF}")
    stamps = [int(s) for s in fp.stdout.split() if s.isdigit()] if fp.returncode == 0 else []
    return float(stamps[-1]) if stamps else None


# ── judging one box ────────────────────────────────────────────────────────────────────────────────────────────────

def _ago(seconds: float) -> str:
    if seconds >= 48 * 3600:
        return f"{seconds / 86400:.0f} days"
    if seconds >= 2 * 3600:
        return f"{seconds / 3600:.0f} h"
    return f"{max(0, seconds) / 60:.0f} min"


_RANK = {"green": 0, "yellow": 1, "red": 2}


def evaluate(probe: dict, lag: Callable[[str, str], dict], local_now: float) -> tuple[str, str]:
    """(severity, detail) for one pull-only node. The worst finding wins; every finding is named."""
    findings: list[tuple[str, str]] = []
    current = []
    for rel in REPOS:
        head = probe["heads"].get(rel, "")
        if not head:
            findings.append(("red", f"no git repo at ~/{rel} on the box"))
            continue
        try:
            l = lag(rel, head)
        except Exception as exc:  # noqa: BLE001 -- a local git hiccup is "can't tell", never "fine"
            findings.append(("yellow", f"couldn't compare ~/{rel} with this Mac: {str(exc)[:100]}"))
            continue
        if not l.get("known"):
            findings.append(("yellow", f"~/{rel} is at {head[:8]}, which this Mac hasn't seen (its own copy may be older)"))
        elif l.get("missing"):
            since = l.get("since")
            if since is None:
                findings.append(("yellow", f"~/{rel} is {l['missing']} commit(s) behind, since an unknown time"))
                continue
            age = local_now - since
            sev = "red" if age >= BEHIND_RED_S else "yellow" if age >= BEHIND_YELLOW_S else "green"
            if sev == "green":
                current.append(f"~/{rel} catching up ({l['missing']} new commit(s), {_ago(age)})")
            else:
                findings.append((sev, f"~/{rel} {l['missing']} commit(s) behind for {_ago(age)}"))
        else:
            current.append(f"~/{rel} current ({head[:8]})")

    recent = _recent(probe["errors"], probe["now"], local_now)
    clock = "" if probe["now"] is not None else " (box clock unread: this Mac's used)"
    if recent:
        last = max(recent, key=lambda e: _epoch(e.get("t")) or 0)
        import error_log
        cause = error_log.classify(f"{last.get('raw', '')}\n{last.get('message', '')}")["cause"]
        n = len(recent)
        findings.append(("red" if n >= FAILURES_RED else "yellow",
                         f"{n} mirror failure(s) in the last hour{clock}; last: {last.get('message', '?')}: {cause}"))
    else:
        current.append(f"no mirror failures in the last hour{clock}")

    if not findings:
        return "green", "; ".join(current)
    worst = max(findings, key=lambda f: _RANK[f[0]])[0]
    return worst, "; ".join(d for _, d in findings)


# ── the sweep ──────────────────────────────────────────────────────────────────────────────────────────────────────

def run_probe(host: str) -> str:
    """The box's answer to PROBE_SCRIPT. Raises on any ssh failure so the caller says "couldn't read"."""
    proc = subprocess.run(["ssh", *SSH_OPTS, host, "bash -s"], input=PROBE_SCRIPT, capture_output=True, text=True,
                          timeout=SSH_TIMEOUT_S)
    if proc.returncode != 0:
        raise OSError((proc.stderr or proc.stdout).strip()[:200] or f"ssh exit {proc.returncode}")
    return proc.stdout


def _row(cid: str, label: str, severity: str, detail: str) -> dict:
    return {"id": cid, "label": label, "severity": severity, "detail": detail, "value": None}


def check_mirror_sync_everywhere(reach: dict[str, str], devices: dict | None = None, runner=run_probe,
                                 lag: Callable[[str, str], dict] | None = None,
                                 now: datetime | None = None) -> list[dict]:
    """One `mirror:sync@<device>` row per pull-only node. `reach` maps machine:<id> -> severity from the sweep's
    reachability check, which already rates a down box; this row is red only for a measured sync failure."""
    if devices is None:
        import machine_profile
        devices = machine_profile.remote_devices()
    lag = lag or (lambda rel, head: local_lag(HOME / rel, head))
    local_now = (now or datetime.now(timezone.utc)).timestamp()
    rows = []
    for dev, info in pull_only(devices).items():
        cid, label = f"mirror:sync@{dev}", f"Mirror sync -- {dev}"
        r = reach.get(f"machine:{dev}")
        if r == "asleep":
            rows.append(_row(cid, label, "asleep", "can't check while the machine is asleep"))
            continue
        if r != "green":
            rows.append(_row(cid, label, "yellow",
                             f"can't verify: {dev} is unreachable ({r or 'not measured'}); being offline isn't a sync "
                             f"failure, its Machine row covers that"))
            continue
        host = info.get("tailscale_hostname")
        if not host:
            rows.append(_row(cid, label, "yellow", "can't verify: no tailscale_hostname registered"))
            continue
        try:
            probe = parse_probe(runner(host))
        except Exception as exc:  # noqa: BLE001
            rows.append(_row(cid, label, "yellow", f"couldn't read the box's mirror state: {str(exc)[:160]}"))
            continue
        sev, detail = evaluate(probe, lag, local_now)
        rows.append(_row(cid, label, sev, detail))
    return rows


if __name__ == "__main__":
    import health_checks
    reach = {r["id"]: r["severity"] for r in health_checks.check_machine_reachability()}
    for row in check_mirror_sync_everywhere(reach):
        print(f"[{row['severity']:>6}] {row['label']}: {row['detail']}")
