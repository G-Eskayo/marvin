#!/usr/bin/env python3
"""PR cost metrics (marvin#449, G4): how many rows it took to merge each PR; cost efficiency per ticket."""
from __future__ import annotations
import json
import re
import sqlite3
from pathlib import Path

MERGED_PATTERN = re.compile(r"^merged: (\S+)$")


def merged_tickets(stages_dir: Path | str) -> dict[str, float]:
    """Scan ticket_stages.STAGES_DIR for the done/passed/merged: <url> convention.
    Returns {ticket_ref: timestamp} of merged tickets, keyed by "repo#number" string via parse_stage_key().
    Dedupes duplicate merge events per ticket (takes the first one)."""
    import ticket_stages

    stages_dir = Path(stages_dir)
    out = {}
    if not stages_dir.exists():
        return out

    for f in stages_dir.glob("*.json"):
        try:
            events = json.loads(f.read_text())
        except (ValueError, OSError):
            continue
        if not isinstance(events, list):
            continue

        # Extract ticket ref from filename via parse_stage_key
        parsed = ticket_stages.parse_stage_key(f.stem)
        if not parsed:
            continue
        repo, ticket_num = parsed
        ticket_ref = f"{repo}#{ticket_num}"

        # Find the first merged event for this ticket
        if ticket_ref in out:
            continue  # Already have this ticket's merge timestamp

        for e in events:
            if not isinstance(e, dict):
                continue
            if e.get("stage") == "done" and e.get("status") == "passed":
                m = MERGED_PATTERN.match(e.get("detail") or "")
                if m:
                    out[ticket_ref] = e.get("timestamp")
                    break  # Take the first merged event

    return out


def cost_per_merged_pr(conn: sqlite3.Connection, stages_dir: Path | str | None = None) -> list[dict]:
    """Cost (row count, tokens, cost_usd) per merged PR, from the history store's 'launches' stream.
    Filters to launches where the 'ticket' field matches a merged ticket.
    Returns [{ticket, timestamp, rows, cost_usd, paid_cost, local_cost, tokens_by_model}] sorted by cost_usd desc.
    Pre-populates one entry per merged ticket (with zero cost if no launches), then queries launches grouped by (ticket, model)."""
    import ticket_stages

    stages_dir = Path(stages_dir or ticket_stages.STAGES_DIR)
    merged = merged_tickets(stages_dir)
    if not merged:
        return []

    # Pre-populate result with one entry per merged ticket
    result = {ticket_ref: {
        "ticket": ticket_ref,
        "ts": ts,
        "rows": 0,
        "cost_usd": 0.0,
        "paid_cost": 0.0,
        "local_cost": 0.0,
        "tokens_by_model": {}
    } for ticket_ref, ts in merged.items()}

    # Query launches grouped by (ticket, model)
    placeholders = ",".join("?" * len(merged))
    rows = conn.execute(
        f"""SELECT ticket, model, COUNT(*) as row_count,
                  SUM(COALESCE(CAST(cost_usd AS REAL), 0)) as total_cost,
                  SUM(COALESCE(CAST(input_tokens AS INTEGER), 0)) as total_input_tokens,
                  SUM(COALESCE(CAST(output_tokens AS INTEGER), 0)) as total_output_tokens
           FROM runs
           WHERE ticket IN ({placeholders})
           GROUP BY ticket, model
           ORDER BY ticket, model""",
        list(merged.keys())
    ).fetchall()

    # Fold each (ticket, model) group into its ticket's entry
    for ticket_ref, model, row_count, total_cost, input_tokens, output_tokens in rows:
        if ticket_ref not in result:
            continue  # Shouldn't happen, but be defensive
        entry = result[ticket_ref]
        entry["rows"] += row_count
        entry["cost_usd"] += total_cost

        # Split cost by paid vs. local (model is None or starts with "claude" = paid)
        is_paid = model is None or (isinstance(model, str) and model.startswith("claude"))
        if is_paid:
            entry["paid_cost"] += total_cost
        else:
            entry["local_cost"] += total_cost

        # Accumulate tokens by model
        if model not in entry["tokens_by_model"]:
            entry["tokens_by_model"][model] = {"input": 0, "output": 0}
        entry["tokens_by_model"][model]["input"] += (input_tokens or 0)
        entry["tokens_by_model"][model]["output"] += (output_tokens or 0)

    # Sort by cost_usd descending
    return sorted(result.values(), key=lambda x: x["cost_usd"], reverse=True)
