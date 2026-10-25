#!/usr/bin/env python3
"""Seal beta feedback ingestion pipeline: reads feedback JSON files from Messages attachments,
validates them, deduplicates against seen IDs, appends valid conversations to reports.jsonl,
logs issues to quarantine.jsonl, and maintains a summary with per-device and per-build views.

    seal_beta_ingest.py          scan ~/Library/Messages/Attachments/ and ingest new files
    seal_beta_ingest.py summary  rebuild the summary from the reports file

Schema (Seal v1):
- Each seal-feedback-*.json file contains: { "schema": 1, "device": { "model": "..." },
    "app": { "build": "..." }, "conversations": [...] }
- Each conversation: { "id": "...", "rating": <int|null>, "ratingSkipped": <bool>,
    "lag": { "p50Seconds": <float>, "p95Seconds": <float>, "samples": <int> },
    "rewriteRate": <float>, "speakers": { "relabelsPerMinute": <float> },
    "ending": { "kind": "..." }, "battery": { "dropPercentPer30Min": <float>,
    "maxThermalState": <int> }, "minutes": <float> }
"""
from __future__ import annotations

import fcntl
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

HOME = Path.home()
REPORTS_DIR = HOME / ".claude" / "seal-beta"
REPORTS_JSONL = REPORTS_DIR / "reports.jsonl"
QUARANTINE_JSONL = REPORTS_DIR / "quarantine.jsonl"
SUMMARY_JSON = REPORTS_DIR / "summary.json"

THERMAL_RANK = {
    "nominal": 0,
    "fair": 1,
    "serious": 2,
    "critical": 3,
}

DEVICE_MODEL_NAMES = {
    "iPhone15,3": "iPhone 15 Pro",
    "iPhone15,4": "iPhone 15 Pro Max",
    "iPhone16,1": "iPhone 16",
    "iPhone16,2": "iPhone 16 Plus",
    "iPhone17,1": "iPhone 17",
    "iPhone17,2": "iPhone 17 Plus",
    "iPhone18,1": "iPhone 17",
}


def device_plain_name(identifier: str) -> str:
    """Map device model identifiers to plain English names, with safe fallback."""
    return DEVICE_MODEL_NAMES.get(identifier, identifier or "unknown-device")


def find_report_files(attachments_dir: Path) -> list[Path]:
    """Find all seal-feedback-*.json files recursively. Raise on permission error,
    return empty list on missing directory."""
    if not attachments_dir.exists():
        return []
    try:
        return sorted(attachments_dir.glob("**/seal-feedback-*.json"))
    except PermissionError:
        raise


def load_report(path: Path) -> tuple[dict, str | None]:
    """Parse a JSON file and validate top-level structure.
    Returns (report_dict, error_reason). If error_reason is not None, report_dict should not be used."""
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return {}, f"JSON parse error: {e}"

    # Validate schema version and required top-level fields.
    if data.get("schema") != 1:
        return {}, f"unsupported schema version: {data.get('schema')}"

    required = ["device", "app", "conversations"]
    for field in required:
        if field not in data:
            return {}, f"missing required field: {field}"

    # Validate device.model and app.build exist.
    if not isinstance(data.get("device"), dict) or "model" not in data["device"]:
        return {}, "device.model is required"
    if not isinstance(data.get("app"), dict) or "build" not in data["app"]:
        return {}, "app.build is required"

    if not isinstance(data.get("conversations"), list):
        return {}, "conversations is not a list"

    return data, None


def validate_conversation(row: dict) -> tuple[bool, str | None]:
    """Validate a single conversation row. Returns (is_valid, error_reason).
    Requires: id, rating, ratingSkipped, lag, rewriteRate, speakers, ending, battery, minutes."""
    required_fields = ["id", "rating", "ratingSkipped", "lag", "rewriteRate", "speakers", "ending", "battery", "minutes"]
    for field in required_fields:
        if field not in row:
            return False, f"missing field: {field}"

    # Type checks for top-level fields.
    if not isinstance(row.get("id"), str) or not row["id"].strip():
        return False, "id must be non-empty string"

    if not isinstance(row.get("ratingSkipped"), bool):
        return False, "ratingSkipped must be boolean"

    rating = row.get("rating")
    if rating is not None and not isinstance(rating, int):
        return False, "rating must be int or null"

    if not isinstance(row.get("minutes"), (int, float)):
        return False, "minutes must be numeric"

    if not isinstance(row.get("rewriteRate"), (int, float)):
        return False, "rewriteRate must be numeric"

    # Validate lag object.
    lag = row.get("lag")
    if not isinstance(lag, dict):
        return False, "lag must be a dict"
    for lag_field in ["p50Seconds", "p95Seconds", "samples"]:
        if lag_field not in lag:
            return False, f"lag.{lag_field} is required"
        if lag_field == "samples":
            if not isinstance(lag[lag_field], int):
                return False, f"lag.{lag_field} must be int"
        else:
            if not isinstance(lag[lag_field], (int, float)):
                return False, f"lag.{lag_field} must be numeric"

    # Validate speakers object.
    speakers = row.get("speakers")
    if not isinstance(speakers, dict):
        return False, "speakers must be a dict"
    if "relabelsPerMinute" not in speakers:
        return False, "speakers.relabelsPerMinute is required"
    if not isinstance(speakers["relabelsPerMinute"], (int, float)):
        return False, "speakers.relabelsPerMinute must be numeric"

    # Validate ending object.
    ending = row.get("ending")
    if not isinstance(ending, dict):
        return False, "ending must be a dict"
    if "kind" not in ending:
        return False, "ending.kind is required"
    if not isinstance(ending["kind"], str):
        return False, "ending.kind must be string"

    # Validate battery object.
    battery = row.get("battery")
    if not isinstance(battery, dict):
        return False, "battery must be a dict"
    if "dropPercentPer30Min" not in battery:
        return False, "battery.dropPercentPer30Min is required"
    if not isinstance(battery["dropPercentPer30Min"], (int, float)):
        return False, "battery.dropPercentPer30Min must be numeric"

    if "maxThermalState" not in battery:
        return False, "battery.maxThermalState is required"
    thermal = battery.get("maxThermalState")
    if not isinstance(thermal, str) or not thermal.strip():
        return False, "battery.maxThermalState must be non-empty string"
    if thermal not in THERMAL_RANK:
        return False, f"battery.maxThermalState must be one of {list(THERMAL_RANK.keys())}, got {thermal!r}"

    return True, None


def load_seen_ids(reports_path: Path) -> set[str]:
    """Load all conversation IDs from reports.jsonl to track which ones we've seen."""
    seen = set()
    if not reports_path.exists():
        return seen
    for line in reports_path.read_text().splitlines():
        if line.strip():
            try:
                row = json.loads(line)
                if "id" in row:
                    seen.add(row["id"])
            except (json.JSONDecodeError, ValueError):
                pass
    return seen


def is_low_sample(conv: dict) -> bool:
    """Check if a conversation has low duration (< 1 minute) or low sample count (< 30)."""
    minutes = conv.get("minutes", 0)
    samples = conv.get("lag", {}).get("samples", 0)
    return minutes < 1.0 or samples < 30


def ingest_file(path: Path, reports_jsonl: Path, quarantine_jsonl: Path) -> dict:
    """Ingest a single report file: validate, dedupe, and append to reports.jsonl.
    Invalid rows go to quarantine.jsonl. Returns stats dict."""
    report_data, err = load_report(path)
    if err:
        # Log file-level error to quarantine.
        reports_jsonl.parent.mkdir(parents=True, exist_ok=True)
        _write_quarantine(
            quarantine_jsonl,
            {"file": str(path), "error": err, "timestamp": datetime.now(timezone.utc).isoformat()}
        )
        return {"file": str(path), "valid": 0, "invalid": 0, "duplicate": 0, "error": err}

    seen_ids = load_seen_ids(reports_jsonl)

    n_valid = 0
    n_invalid = 0
    n_duplicate = 0
    invalid_rows = []

    # Process each conversation in the report.
    device_model = report_data.get("device", {}).get("model", "unknown")
    app_build = report_data.get("app", {}).get("build", "unknown")

    for conv in report_data.get("conversations", []):
        if conv.get("id") in seen_ids:
            n_duplicate += 1
            continue

        is_valid, err_msg = validate_conversation(conv)
        if not is_valid:
            n_invalid += 1
            invalid_rows.append({"conv_id": conv.get("id"), "error": err_msg})
            continue

        # Enrich with report-level metadata using allowlist.
        allowlist = ["id", "rating", "ratingSkipped", "lag", "rewriteRate", "speakers", "ending", "battery", "minutes"]
        enriched = {
            k: conv[k] for k in allowlist if k in conv
        }
        enriched["device_model"] = device_model
        enriched["app_build"] = app_build

        # Append to reports.jsonl with file lock.
        _write_report(reports_jsonl, enriched)
        seen_ids.add(conv["id"])
        n_valid += 1

    # Log invalid rows to quarantine.
    if invalid_rows:
        for row in invalid_rows:
            _write_quarantine(
                quarantine_jsonl,
                {
                    "file": str(path),
                    "conversation": row,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

    return {
        "file": str(path),
        "valid": n_valid,
        "invalid": n_invalid,
        "duplicate": n_duplicate,
    }


def _write_report(path: Path, row: dict) -> None:
    """Append a single report row to reports.jsonl with file-level locking."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(json.dumps(row) + "\n")
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _write_quarantine(path: Path, row: dict) -> None:
    """Append a single quarantine entry with file-level locking."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(json.dumps(row) + "\n")
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def aggregate(rows: list[dict]) -> dict:
    """Aggregate a list of conversation rows: compute counts, medians, and breakdowns.
    Assumes all rows belong to the same group (device/build)."""
    if not rows:
        return {
            "count": 0,
            "median_rating": None,
            "skips": 0,
            "unrated": 0,
            "median_lag_p50": None,
            "median_lag_p95": None,
            "median_rewrite_rate": None,
            "median_relabels_per_minute": None,
            "endings": {},
            "median_battery_drop": None,
            "worst_thermal_state": None,
        }

    count = len(rows)

    # Rating stats (excluding null ratings).
    ratings = [r.get("rating") for r in rows if r.get("rating") is not None]
    skips = sum(1 for r in rows if r.get("ratingSkipped"))
    unrated = count - len(ratings) - skips

    median_rating = None
    if ratings:
        sorted_ratings = sorted(ratings)
        n = len(sorted_ratings)
        if n % 2 == 0:
            median_rating = (sorted_ratings[n // 2 - 1] + sorted_ratings[n // 2]) / 2
        else:
            median_rating = sorted_ratings[n // 2]

    # Lag p50/p95 (excluding low-sample rows).
    high_sample_rows = [r for r in rows if not is_low_sample(r)]
    lag_p50s = [r.get("lag", {}).get("p50Seconds") for r in high_sample_rows
                if isinstance(r.get("lag", {}).get("p50Seconds"), (int, float))]
    lag_p95s = [r.get("lag", {}).get("p95Seconds") for r in high_sample_rows
                if isinstance(r.get("lag", {}).get("p95Seconds"), (int, float))]

    def median(vals: list) -> float | None:
        if not vals:
            return None
        sorted_vals = sorted(vals)
        n = len(sorted_vals)
        return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2 if n % 2 == 0 else sorted_vals[n // 2]

    median_lag_p50 = median(lag_p50s)
    median_lag_p95 = median(lag_p95s)

    # Rewrite rate.
    rewrite_rates = [r.get("rewriteRate") for r in rows if isinstance(r.get("rewriteRate"), (int, float))]
    median_rewrite_rate = median(rewrite_rates)

    # Relabels per minute.
    relabels = [r.get("speakers", {}).get("relabelsPerMinute") for r in rows
                if isinstance(r.get("speakers", {}).get("relabelsPerMinute"), (int, float))]
    median_relabels = median(relabels)

    # Endings breakdown.
    endings: dict[str, int] = {}
    for r in rows:
        kind = r.get("ending", {}).get("kind", "unknown")
        endings[kind] = endings.get(kind, 0) + 1

    # Battery drop.
    battery_drops = [r.get("battery", {}).get("dropPercentPer30Min") for r in rows
                     if isinstance(r.get("battery", {}).get("dropPercentPer30Min"), (int, float))]
    median_battery_drop = median(battery_drops)

    # Worst thermal state (ranked via THERMAL_RANK, return string label).
    thermal_states = [r.get("battery", {}).get("maxThermalState") for r in rows
                      if isinstance(r.get("battery", {}).get("maxThermalState"), str)
                      and r.get("battery", {}).get("maxThermalState") in THERMAL_RANK]
    if thermal_states:
        worst_rank = max(THERMAL_RANK[state] for state in thermal_states)
        worst_thermal = [k for k, v in THERMAL_RANK.items() if v == worst_rank][0]
    else:
        worst_thermal = None

    return {
        "count": count,
        "median_rating": median_rating,
        "skips": skips,
        "unrated": unrated,
        "median_lag_p50": median_lag_p50,
        "median_lag_p95": median_lag_p95,
        "median_rewrite_rate": median_rewrite_rate,
        "median_relabels_per_minute": median_relabels,
        "endings": endings,
        "median_battery_drop": median_battery_drop,
        "worst_thermal_state": worst_thermal,
    }


def summarize(reports_path: Path, now: datetime | None = None) -> dict:
    """Build summary from reports.jsonl: both per-device→per-build tree
    and a flat per-build view. Writes to summary.json."""
    now = now or datetime.now(timezone.utc)
    reports_dir = reports_path.parent
    reports_dir.mkdir(parents=True, exist_ok=True)

    by_device: dict[str, dict[str, Any]] = {}
    by_build: dict[str, Any] = {}
    last_report_seen_at = None

    if not reports_path.exists():
        return {
            "by_device": {},
            "by_build": {},
            "last_report_seen_at": None,
            "generated_at": now.isoformat(),
        }

    for line in reports_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        # Track last report timestamp (use 'id' as proxy for row freshness).
        if last_report_seen_at is None:
            last_report_seen_at = now.isoformat()

        device_model = row.get("device_model", "unknown")
        device_name = device_plain_name(device_model)
        app_build = row.get("app_build", "unknown")

        # By device tree.
        if device_model not in by_device:
            by_device[device_model] = {
                "model": device_model,
                "plain_name": device_name,
                "builds": {},
            }

        device_entry = by_device[device_model]
        if app_build not in device_entry["builds"]:
            device_entry["builds"][app_build] = []
        device_entry["builds"][app_build].append(row)

        # By build flat.
        if app_build not in by_build:
            by_build[app_build] = {
                "app_build": app_build,
                "devices": {},
                "rows": [],
            }

        if device_model not in by_build[app_build]["devices"]:
            by_build[app_build]["devices"][device_model] = device_name
        by_build[app_build]["rows"].append(row)

    # Compute aggregates for each group.
    for device_model in by_device:
        for app_build in by_device[device_model]["builds"]:
            rows = by_device[device_model]["builds"][app_build]
            agg = aggregate(rows)
            by_device[device_model]["builds"][app_build] = agg

    for app_build in by_build:
        rows = by_build[app_build]["rows"]
        agg = aggregate(rows)
        by_build[app_build] = {**by_build[app_build], **agg}
        del by_build[app_build]["rows"]  # Don't include raw rows in summary.

    summary = {
        "by_device": by_device,
        "by_build": by_build,
        "last_report_seen_at": last_report_seen_at,
        "generated_at": now.isoformat(),
    }

    summary_path = reports_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    return summary


import job_events  # noqa: E402


@job_events.reported("seal-beta-ingest", "Seal beta feedback ingest")
def _cli() -> None:
    """Main CLI: scan attachments, ingest new files, rebuild summary."""
    attachments_dir = HOME / "Library" / "Messages" / "Attachments"

    # Get list of files to process.
    try:
        files = find_report_files(attachments_dir)
    except PermissionError:
        print("Error: permission denied accessing Messages Attachments — Full Disk Access required", file=sys.stderr)
        raise

    if not files:
        print("No seal-feedback files found.")
        job_events.step("Scan complete", f"0 files")
        return

    # Ingest each file.
    total_valid = 0
    total_invalid = 0
    total_duplicate = 0

    for file_path in files:
        result = ingest_file(file_path, REPORTS_JSONL, QUARANTINE_JSONL)
        total_valid += result["valid"]
        total_invalid += result["invalid"]
        total_duplicate += result["duplicate"]
        if result.get("error"):
            print(f"File {file_path.name}: {result['error']}")
        else:
            print(f"File {file_path.name}: {result['valid']} new, {result['invalid']} invalid, {result['duplicate']} duplicate")

    # Rebuild summary.
    summarize(REPORTS_JSONL)

    job_events.step("Ingest complete", f"{total_valid} new, {total_invalid} invalid, {total_duplicate} duplicate")
    print(f"Summary: {total_valid} new, {total_invalid} invalid, {total_duplicate} duplicate")


if __name__ == "__main__":
    _cli()
