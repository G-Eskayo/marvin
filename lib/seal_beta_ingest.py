#!/usr/bin/env python3
"""Seal Speak beta report ingest (marvin#407; design: clarity-captions ADR 0024 + docs/beta/metrics-schema.md).

Testers tap *Send feedback to Gil* in a TestFlight build and the app texts a `seal-feedback-*.json` report. Messages
stores it on the Mac under ~/Library/Messages/Attachments/<xx>/<yy>/<UUID>/. This job, run by launchd on the Mac Mini:

1. finds those files (only those: never message text, never other attachments)
2. validates each against `schema: 1` and skips conversations already stored (by conversation `id`)
3. appends new conversations to a private store, ~/.claude/seal-beta/reports.jsonl (never a repo; ~/.claude's sync
   ignores it)
4. rewrites summary.json, grouped by device model (plain name, then by build) and by build, and status.json, which
   the Health check reads

Reading ~/Library/Messages needs Full Disk Access for the interpreter launchd runs. A Homebrew Python upgrade resets
that grant, so a denied read is a loud failure (exit 2, status `ok: false`), never "0 reports".

    ~/.agents/venv/bin/python seal_beta_ingest.py run        # ingest (what launchd runs)
    ~/.agents/venv/bin/python seal_beta_ingest.py summary    # print the per-device table
"""
from __future__ import annotations

import argparse
import fcntl
import fnmatch
import json
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ATTACHMENTS_DIR = Path.home() / "Library" / "Messages" / "Attachments"
STORE_DIR = Path.home() / ".claude" / "seal-beta"
REPORT_GLOB = "seal-feedback-*.json"
SCHEMA = 1

# A session this short says little about lag or battery; its rating still counts.
LOW_SAMPLE_MIN_LAG_SAMPLES = 30
LOW_SAMPLE_MIN_MINUTES = 1.0

THERMAL_ORDER = ["nominal", "fair", "serious", "critical"]

# Apple model identifiers for phones that can run Seal Speak (iOS 26+). Unknown ids show as themselves.
DEVICE_NAMES = {
    "iPhone12,1": "iPhone 11", "iPhone12,3": "iPhone 11 Pro", "iPhone12,5": "iPhone 11 Pro Max",
    "iPhone12,8": "iPhone SE (2nd generation)",
    "iPhone13,1": "iPhone 12 mini", "iPhone13,2": "iPhone 12", "iPhone13,3": "iPhone 12 Pro",
    "iPhone13,4": "iPhone 12 Pro Max",
    "iPhone14,4": "iPhone 13 mini", "iPhone14,5": "iPhone 13", "iPhone14,2": "iPhone 13 Pro",
    "iPhone14,3": "iPhone 13 Pro Max", "iPhone14,6": "iPhone SE (3rd generation)",
    "iPhone14,7": "iPhone 14", "iPhone14,8": "iPhone 14 Plus", "iPhone15,2": "iPhone 14 Pro",
    "iPhone15,3": "iPhone 14 Pro Max",
    "iPhone15,4": "iPhone 15", "iPhone15,5": "iPhone 15 Plus", "iPhone16,1": "iPhone 15 Pro",
    "iPhone16,2": "iPhone 15 Pro Max",
    "iPhone17,3": "iPhone 16", "iPhone17,4": "iPhone 16 Plus", "iPhone17,1": "iPhone 16 Pro",
    "iPhone17,2": "iPhone 16 Pro Max", "iPhone17,5": "iPhone 16e",
    "iPhone18,3": "iPhone 17", "iPhone18,4": "iPhone Air", "iPhone18,1": "iPhone 17 Pro",
    "iPhone18,2": "iPhone 17 Pro Max",
    "arm64": "Simulator", "x86_64": "Simulator",
}


class IngestError(Exception):
    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind, self.detail = kind, detail


def device_name(model) -> str:
    if model is None or model == "":
        return "Unknown device"
    return DEVICE_NAMES.get(str(model), str(model))


# ── finding report files ────────────────────────────────────────────────────

def find_reports(root: Path) -> list[Path]:
    """Every seal-feedback-*.json under root. Raises IngestError rather than returning a short list: a folder macOS
    won't let us read must never look like 'no reports'."""
    try:
        os.stat(root)
    except FileNotFoundError:
        raise IngestError("missing", f"{root} does not exist: is Messages signed in on this Mac?")
    except PermissionError:
        raise _denied(root)
    found, stack = [], [str(root)]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                    elif fnmatch.fnmatch(e.name, REPORT_GLOB) and e.is_file(follow_symlinks=False):
                        found.append(Path(e.path))
        except PermissionError:
            raise _denied(d)
        except FileNotFoundError:
            continue  # removed between listing and reading (Messages tidying up)
    return sorted(found)


def _denied(where) -> IngestError:
    return IngestError("permission", f"macOS refused to read {where}. Full Disk Access is off for this job's Python "
                       f"({os.path.realpath(sys.executable)}); a Homebrew Python upgrade resets it. Turn it on in "
                       "System Settings > Privacy & Security > Full Disk Access.")


# ── validating and flattening ───────────────────────────────────────────────

def validate(doc) -> str | None:
    """None if usable, else the reason in plain words."""
    if not isinstance(doc, dict):
        return "not a JSON object"
    if doc.get("schema") != SCHEMA:
        return f"schema is {doc.get('schema')!r}, expected {SCHEMA}"
    for key in ("device", "app"):
        if not isinstance(doc.get(key), dict):
            return f"missing or malformed '{key}'"
    if not isinstance(doc.get("sentAt"), str):
        return "missing 'sentAt'"
    convs = doc.get("conversations")
    if not isinstance(convs, list):
        return "'conversations' is not a list"
    for i, c in enumerate(convs):
        if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not c["id"]:
            return f"conversation {i} has no 'id'"
    return None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _sub(d, key):
    v = d.get(key) if isinstance(d, dict) else None
    return v if isinstance(v, dict) else {}


def flatten(doc: dict, source_name: str, ingested_at: str) -> list[dict]:
    """One record per conversation, carrying the report's device/app/settings so each line stands alone."""
    dev, app = doc["device"], doc["app"]
    out = []
    for c in doc["conversations"]:
        lag, bat, spk, end = _sub(c, "lag"), _sub(c, "battery"), _sub(c, "speakers"), _sub(c, "ending")
        rating = _num(c.get("rating"))
        if rating is not None and not 1 <= rating <= 10:
            rating = None
        state = "rated" if rating is not None else ("skipped" if c.get("ratingSkipped") is True else "unrated")
        minutes, samples = _num(c.get("minutes")), _num(lag.get("samples"))
        low = (samples is None or samples < LOW_SAMPLE_MIN_LAG_SAMPLES
               or minutes is None or minutes < LOW_SAMPLE_MIN_MINUTES)
        out.append({
            "id": c["id"],
            "sent_at": doc["sentAt"],
            "started_at": c.get("startedAt"),
            "device_model": dev.get("model"),
            "device": device_name(dev.get("model")),
            "os": dev.get("os"),
            "low_power_seen": dev.get("lowPowerModeSeen"),
            "build": str(app.get("build")),
            "version": app.get("version"),
            "environment": app.get("environment"),
            "settings": doc.get("settings") if isinstance(doc.get("settings"), dict) else {},
            "minutes": minutes,
            "rating": rating,
            "rating_state": state,
            "note": c.get("note") if isinstance(c.get("note"), str) and c.get("note").strip() else None,
            "lag_p50": _num(lag.get("p50Seconds")),
            "lag_p95": _num(lag.get("p95Seconds")),
            "lag_samples": samples,
            "rewrite_rate": _num(c.get("rewriteRate")),
            "speakers_detected": _num(spk.get("detected")),
            "relabels_per_min": _num(spk.get("relabelsPerMinute")),
            "launch_to_start_s": _num(c.get("launchToStartSeconds")),
            "start_to_first_caption_s": _num(c.get("startToFirstCaptionSeconds")),
            "ending": end.get("kind") if isinstance(end.get("kind"), str) else "unknown",
            "ending_reason": end.get("reason"),
            "battery_drop_per_30min": _num(bat.get("dropPercentPer30Min")),
            "max_thermal": bat.get("maxThermalState") if bat.get("maxThermalState") in THERMAL_ORDER else None,
            "low_sample": low,
            "source_file": source_name,
            "ingested_at": ingested_at,
        })
    return out


# ── the private store ───────────────────────────────────────────────────────

def _private_dir(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)


def load_store(path: Path) -> tuple[list[dict], int]:
    """Records, plus how many lines couldn't be read (a run killed mid-write leaves a partial last line)."""
    if not path.exists():
        return [], 0
    recs, bad = [], 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(r, dict) and isinstance(r.get("id"), str):
            recs.append(r)
        else:
            bad += 1
    return recs, bad


def _append(path: Path, recs: list[dict]) -> None:
    if not recs:
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        prefix = b""
        if os.fstat(fd).st_size:
            with open(path, "rb") as f:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    prefix = b"\n"  # never glue a new record onto a partial line
        os.write(fd, prefix + "".join(json.dumps(r, sort_keys=True) + "\n" for r in recs).encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def _write_json(path: Path, data) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


# ── summarising ─────────────────────────────────────────────────────────────

def _median(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), 3) if vals else None


def _stats(recs: list[dict]) -> dict:
    full = [r for r in recs if not r.get("low_sample")]
    endings: dict[str, int] = {}
    for r in recs:
        endings[r.get("ending") or "unknown"] = endings.get(r.get("ending") or "unknown", 0) + 1
    thermals = [r["max_thermal"] for r in recs if r.get("max_thermal") in THERMAL_ORDER]
    os_versions = sorted({r.get("os") for r in recs if r.get("os")})
    return {
        "conversations": len(recs),
        "reports": len({(r.get("device_model"), r.get("build"), r.get("sent_at")) for r in recs}),
        "low_sample": len(recs) - len(full),
        "rated": sum(r.get("rating_state") == "rated" for r in recs),
        "skipped": sum(r.get("rating_state") == "skipped" for r in recs),
        "unrated": sum(r.get("rating_state") == "unrated" for r in recs),
        "median_rating": _median([r.get("rating") for r in recs]),
        "lag_p50": _median([r.get("lag_p50") for r in full]),
        "lag_p95": _median([r.get("lag_p95") for r in full]),
        "rewrite_rate": _median([r.get("rewrite_rate") for r in full]),
        "relabels_per_min": _median([r.get("relabels_per_min") for r in full]),
        "battery_drop_per_30min": _median([r.get("battery_drop_per_30min") for r in full]),
        "max_thermal": max(thermals, key=THERMAL_ORDER.index) if thermals else None,
        "endings": endings,
        "minutes_total": round(sum(r.get("minutes") or 0 for r in recs), 1),
        "os_versions": os_versions,
    }


def _build_key(b: str):
    return (0, int(b)) if str(b).isdigit() else (-1, str(b))


def summarize(recs: list[dict], now: datetime) -> dict:
    by_dev: dict[str, list[dict]] = {}
    by_build: dict[str, list[dict]] = {}
    for r in recs:
        by_dev.setdefault(r.get("device") or device_name(r.get("device_model")), []).append(r)
        by_build.setdefault(str(r.get("build")), []).append(r)
    devices = []
    for name, rs in by_dev.items():
        builds: dict[str, list[dict]] = {}
        for r in rs:
            builds.setdefault(str(r.get("build")), []).append(r)
        devices.append({
            "device": name,
            "model_ids": sorted({str(r.get("device_model")) for r in rs}),
            **_stats(rs),
            "builds": [{"build": b, **_stats(builds[b])} for b in sorted(builds, key=_build_key, reverse=True)],
            "notes": [{"build": r.get("build"), "started_at": r.get("started_at"), "rating": r.get("rating"),
                       "note": r["note"]} for r in sorted(rs, key=lambda r: r.get("started_at") or "") if r.get("note")],
        })
    devices.sort(key=lambda d: (-d["conversations"], d["device"]))
    return {
        "generated_at": now.isoformat(),
        "totals": {"conversations": len(recs),
                   "reports": len({(r.get("device_model"), r.get("build"), r.get("sent_at")) for r in recs}),
                   "devices": len(by_dev)},
        "by_device": devices,
        "by_build": [{"build": b, **_stats(by_build[b])} for b in sorted(by_build, key=_build_key, reverse=True)],
    }


def _latest(stamps: list[str]) -> str | None:
    best = None
    for s in stamps:
        try:
            t = datetime.fromisoformat(s)
        except (TypeError, ValueError):
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if best is None or t > best[0]:
            best = (t, s)
    return best[1] if best else None


# ── the run ─────────────────────────────────────────────────────────────────

def ingest(attachments_dir: Path | None = None, store_dir: Path | None = None, now: datetime | None = None) -> dict:
    att = Path(attachments_dir or ATTACHMENTS_DIR)
    store = Path(store_dir or STORE_DIR)
    now = now or datetime.now(timezone.utc)
    _private_dir(store)
    with os.fdopen(os.open(store / ".lock", os.O_WRONLY | os.O_CREAT, 0o600), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # one run at a time: read-dedupe-append must not interleave
        status = {"generated_at": now.isoformat(), "ok": True, "error": None, "files_found": 0,
                  "new_conversations": 0, "total_conversations": 0, "invalid": [], "last_report_at": None,
                  "store_bad_lines": 0}
        reports_path = store / "reports.jsonl"
        try:
            files = find_reports(att)
        except IngestError as e:
            prev = _read_status(store)
            status.update(ok=False, error={"kind": e.kind, "detail": e.detail},
                          total_conversations=prev.get("total_conversations", 0),
                          last_report_at=prev.get("last_report_at"))
            _write_json(store / "status.json", status)
            return status
        existing, bad = load_store(reports_path)
        seen = {r["id"] for r in existing}
        new, sent = [], []
        for p in files:
            try:
                doc = json.loads(p.read_text())
            except (ValueError, UnicodeDecodeError):
                status["invalid"].append(_invalid(p, "not valid JSON"))
                continue
            except OSError as e:
                status["invalid"].append(_invalid(p, f"could not be read: {e.strerror or e}"))
                continue
            reason = validate(doc)
            if reason:
                status["invalid"].append(_invalid(p, reason))
                continue
            sent.append(doc["sentAt"])
            for rec in flatten(doc, p.name, now.isoformat()):
                if rec["id"] not in seen:
                    seen.add(rec["id"])
                    new.append(rec)
        _append(reports_path, new)
        recs = existing + new
        _write_json(store / "summary.json", summarize(recs, now))
        status.update(files_found=len(files), new_conversations=len(new), total_conversations=len(recs),
                      last_report_at=_latest(sent + [r.get("sent_at") for r in existing]), store_bad_lines=bad)
        _write_json(store / "status.json", status)
        return status


def _invalid(p: Path, reason: str) -> dict:
    try:
        mtime = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        mtime = None
    return {"file": p.name, "reason": reason, "mtime": mtime}


def _read_status(store: Path) -> dict:
    try:
        d = json.loads((store / "status.json").read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


# ── CLI ─────────────────────────────────────────────────────────────────────

def _fmt(v, unit="", digits=2):
    return "-" if v is None else f"{round(v, digits)}{unit}"


def print_summary(store: Path) -> None:
    try:
        s = json.loads((store / "summary.json").read_text())
    except (OSError, ValueError):
        s = None
    if not s or not s.get("by_device"):
        print("No beta reports yet.")
        return
    t = s["totals"]
    print(f"Seal Speak beta: {t['conversations']} conversations in {t['reports']} reports from {t['devices']} device model(s)\n")
    for d in s["by_device"]:
        print(f"{d['device']}  ({', '.join(d['model_ids'])})")
        for b in d["builds"]:
            print(f"  build {b['build']}: {b['conversations']} conv ({b['low_sample']} short), rating {_fmt(b['median_rating'])} "
                  f"[{b['rated']} rated/{b['skipped']} skipped/{b['unrated']} unrated], lag p95 {_fmt(b['lag_p95'], 's')}, "
                  f"rewrites {_fmt(b['rewrite_rate'])}, relabels/min {_fmt(b['relabels_per_min'])}, "
                  f"battery/30min {_fmt(b['battery_drop_per_30min'], '%', 1)}, thermal {b['max_thermal'] or '-'}, "
                  f"endings {b['endings']}")
        for n in d["notes"]:
            print(f"  note (build {n['build']}, rating {n['rating'] if n['rating'] is not None else '-'}): {n['note']}")
        print()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="ingest new reports (what launchd runs)")
    r.add_argument("--attachments", type=Path, default=None)
    r.add_argument("--store", type=Path, default=None)
    s = sub.add_parser("summary", help="print the per-device summary")
    s.add_argument("--store", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.cmd == "summary":
        print_summary(Path(a.store or STORE_DIR))
        return 0
    st = ingest(attachments_dir=a.attachments, store_dir=a.store)
    if not st["ok"]:
        print(f"seal-beta-ingest: {st['error']['kind']}: {st['error']['detail']}", file=sys.stderr)
        return 2 if st["error"]["kind"] == "permission" else 1
    print(f"seal-beta-ingest: {st['files_found']} report file(s), {st['new_conversations']} new conversation(s), "
          f"{st['total_conversations']} total, {len(st['invalid'])} invalid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
