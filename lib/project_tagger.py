#!/usr/bin/env python3
"""project_tagger.py — label tickets that clearly belong to another project (ADR 0060, #298).

A ticket's project is its repo's, unless it carries `project:<id>`. Work for the website or MARVIN Mobile is often
filed in MARVIN's repo because the code lives there; this finds those tickets by the words they use, no AI:

  qualifies  a project's signal in the TITLE, or two different signals in the body ("mobile backend" and
             "mobile-backend" are one signal); a single passing mention in the body is ignored
  clear      exactly one project qualifies -> `project:<id>` (hourly, as the `project_tag` ticket agent, audited)
  unclear    two or more qualify -> listed for Gil, never guessed

To keep a ticket where it is, give it its own repo's label (e.g. `project:marvin`): any project label is left alone.

Rules are data: config/project_tags.json ({"projects": {id: {"repo", "signals": [...]}}}), so a new project is a line.
A label a person took off is never put back. The unclear list and the count of tickets still waiting for a label go
to ~/.claude/logs/project-tags.json, which the Health tab reads.

    project_tagger.py check     what it would label and list, from the live boards
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parents[1] / "config" / "project_tags.json"
STATE_PATH = Path.home() / ".claude" / "logs" / "project-tags.json"
SKIP_LABELS = {"pinned"}


def load_rules(path: Path = RULES_PATH) -> dict:
    try:
        data = json.loads(Path(path).read_text())
        if isinstance(data, dict) and isinstance(data.get("projects"), dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"projects": {}}


def _labels(t) -> list[str]:
    return [l["name"] if isinstance(l, dict) else l for l in t.get("labels") or []]


def _hits(text: str, signals) -> list[str]:
    return [s for s in signals if re.search(r"(?<![\w])" + re.escape(s) + r"(?![\w])", text, re.IGNORECASE)]


def _distinct(hits) -> set[str]:
    """Spelling variants of one signal count once: mobile backend / mobile-backend, /wp-content/ / wp-content."""
    return {re.sub(r"[^a-z0-9]+", "", h.lower()) for h in hits}


def classify(t: dict, rules: dict, repo: str) -> dict | None:
    """None for a ticket that is not this agent's business (already has a project, or pinned)."""
    labels = _labels(t)
    if any(l.startswith("project:") for l in labels) or SKIP_LABELS & set(labels):
        return None
    qualified, why = [], {}
    for pid, r in rules.get("projects", {}).items():
        if r.get("repo") == repo:
            continue  # the repo's own project is the default, never a label
        in_title = _hits(t.get("title") or "", r.get("signals", []))
        in_body = _hits(t.get("body") or "", r.get("signals", []))
        if in_title or len(_distinct(in_body)) >= 2:
            qualified.append(pid)
            why[pid] = sorted(set(in_title + in_body))
    if len(qualified) == 1:
        pid = qualified[0]
        return {"verdict": "clear", "project": pid, "why": "mentions " + ", ".join(why[pid])}
    if qualified:
        return {"verdict": "unclear", "candidates": sorted(qualified),
                "why": "; ".join(f"{p}: {', '.join(why[p])}" for p in sorted(qualified))}
    return {"verdict": None}


def plan(repo: str, issues: list[dict], rules: dict, removed=frozenset()) -> tuple[list[dict], list[dict]]:
    """(label actions in ticket_agents' shape, unclear tickets for Gil)."""
    actions, unclear = [], []
    for t in issues:
        v = classify(t, rules, repo)
        if not v or not v["verdict"]:
            continue
        if v["verdict"] == "clear":
            label = f"project:{v['project']}"
            if (repo, t["number"], label) in removed:
                continue  # a person took it off: theirs
            actions.append({"agent": "project_tag", "repo": repo, "number": t["number"], "title": t.get("title", ""),
                            "op": "add_label", "arg": label, "why": v["why"]})
        else:
            unclear.append({"repo": repo, "number": t["number"], "title": t.get("title", ""),
                            "candidates": v["candidates"], "why": v["why"]})
    return actions, unclear


def removed_by_people(audit_rows, current_labels: dict) -> set:
    """(repo, number, label) the tagger applied that are no longer on the (still open) ticket."""
    applied = {(r["repo"], r["number"], r["arg"]) for r in audit_rows
               if r.get("agent") == "project_tag" and r.get("status") == "applied" and r.get("op") == "add_label"}
    return {k for k in applied if (k[0], k[1]) in current_labels and k[2] not in current_labels[(k[0], k[1])]}


def write_state(unclear: list[dict], pending: int, path: Path = STATE_PATH, now: str | None = None) -> None:
    """pending = clear tickets not labelled yet (the agent is proposing, or out of budget this hour)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"generated_at": now or datetime.now(timezone.utc).isoformat(),
                                   "pending": pending, "unclear": unclear}, indent=2) + "\n")
        tmp.replace(path)
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["check"])
    ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ticket_agents
    rules = load_rules()
    snap = ticket_agents.collect(ticket_agents.board_repos())
    for repo, data in snap.items():
        actions, unclear = plan(repo, data["issues"], rules)
        for a in actions:
            print(f"label  {repo.split('/')[1]}#{a['number']:<4} {a['arg']:<36} {a['title'][:60]}  ({a['why']})")
        for u in unclear:
            print(f"pick   {repo.split('/')[1]}#{u['number']:<4} {'/'.join(u['candidates']):<36} {u['title'][:60]}  ({u['why']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
