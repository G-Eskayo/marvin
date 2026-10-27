#!/usr/bin/env python3
"""One calibration for every Mac (decided 2026-10-26): review answers given on any machine are recorded on the
primary automation host, and every machine uses the tau map computed there.

The primary is the network registry's macOS desktop (the same rule as the dashboard's
device_identity.primaryHostTailscaleName, plus "not Linux": the Linux box is a quarantine node, ADR 0069). No
registry, or no desktop in it, means this machine is the primary (a single-machine install records locally).

Other machines reach it the way the dashboard does: the primary's webhook server over Tailscale (port 7878),
`POST /safety/label` and `GET /safety/taus` (dashboard/webhook-server/safety_labels.js). A label is first appended to a
local outbox (~/.claude/safety-monitor/outbox.jsonl, never synced) and removed only once the primary has answered for
it, so an offline primary loses nothing; delivery is retried on every process() run (session start, the 20:00 job,
each dashboard answer). Re-delivery is safe: the primary ignores a second label for the same entry hash.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import calibrate  # noqa: E402

PORT = 7878
TIMEOUT_S = 5


def _registry() -> dict:
    try:
        data = json.loads((Path.home() / ".claude" / "marvin-network.json").read_text())
        devices = data.get("devices", {}) if isinstance(data, dict) else {}
        return devices if isinstance(devices, dict) else {}
    except (OSError, ValueError):
        return {}


def _my_id() -> str | None:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
        import machine_profile
        return machine_profile.registry_id()
    except Exception:
        return None


def primary() -> tuple[str, str] | None:
    for dev, info in _registry().items():
        if isinstance(info, dict) and info.get("kind") == "desktop" and info.get("os", "macos") == "macos" \
                and info.get("tailscale_hostname"):
            return dev, info["tailscale_hostname"]
    return None


def is_primary() -> bool:
    p = primary()
    return p is None or _my_id() == p[0]


def base_url() -> str:
    env = os.environ.get("MARVIN_SAFETY_URL")
    if env:
        return env.rstrip("/")
    p = primary()
    return f"http://{p[1] if p else 'localhost'}:{PORT}"


def _post(url: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(1_000_000))


def _get(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read(1_000_000))


def _outbox() -> Path:
    return calibrate.STATE_DIR / "outbox.jsonl"


def submit(loop_name: str | dict, score: float | None = None, label: int | None = None, note: str | None = None,
           entry_id: str | None = None) -> None:
    """Records one review answer: on the primary straight into the calibration, elsewhere into the local outbox
    (fast, no network: callers may hold the quarantine lock). deliver() sends the outbox."""
    if isinstance(loop_name, dict):
        row = dict(loop_name)
    else:
        row = {"loop": loop_name, "score": score, "label": label, "note": note, "entry_id": entry_id}
    row = {k: v for k, v in row.items() if v is not None}
    if is_primary():
        calibrate.record_label(row["loop"], row["score"], row["label"], row.get("note"), row.get("entry_id"))
        return
    why = calibrate.valid_label(row.get("loop"), row.get("score"), row.get("label"), row.get("note"), row.get("entry_id"))
    if why:
        raise ValueError(f"invalid label: {why}")
    with calibrate._locked():
        with _outbox().open("a") as f:
            f.write(json.dumps(row) + "\n")


def deliver() -> dict:
    """Sends queued labels to the primary, oldest first; stops at the first failure to reach it (the rest wait for
    the next run). A label the primary refuses as invalid is dropped (and logged): it would never be accepted."""
    out = {"delivered": 0, "queued": 0, "dropped": 0}
    if is_primary():
        return out
    with calibrate._locked():
        path = _outbox()
        try:
            lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
        except FileNotFoundError:
            return out
        keep: list[str] = []
        taus = None
        reachable = True
        for line in lines:
            if not reachable:
                keep.append(line)
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("not an object")
            except ValueError:
                out["dropped"] += 1
                print(f"[shared-labels] dropped a torn outbox line: {line[:80]!r}", file=sys.stderr)
                continue
            try:
                res = _post(f"{base_url()}/safety/label", row, TIMEOUT_S)
            except Exception as e:  # offline, timeout, reply lost: keep it for next time
                reachable = False
                keep.append(line)
                print(f"[shared-labels] primary not reached ({e}); {len(lines)} label(s) kept for later", file=sys.stderr)
                continue
            if isinstance(res, dict) and res.get("ok"):
                out["delivered"] += 1
                taus = res.get("taus", taus)
            else:
                out["dropped"] += 1
                print(f"[shared-labels] primary refused a label ({(res or {}).get('error')}): {line[:80]!r}", file=sys.stderr)
        out["queued"] = len(keep)
        if keep:
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".outbox.", suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                f.write("".join(k + "\n" for k in keep))
            os.replace(tmp, path)
        else:
            path.unlink(missing_ok=True)
    if taus:
        calibrate.store_taus(taus)
    return out


def sync() -> dict:
    """deliver(), then refresh this machine's tau cache from the primary. Offline keeps the last known map."""
    out = deliver()
    if not is_primary():
        try:
            calibrate.store_taus(_get(f"{base_url()}/safety/taus", TIMEOUT_S))
        except Exception as e:
            print(f"[shared-labels] tau map not refreshed ({e}); using the cached one", file=sys.stderr)
    return out
