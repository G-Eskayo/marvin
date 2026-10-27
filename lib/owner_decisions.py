#!/usr/bin/env python3
"""Owner decisions waiting on MARVIN (marvin#607).

The gap (PR #577, 2026-10-22): Gil submitted Decisions from the dashboard, the "### Decisions from the owner" record
comment asked an open question, and nothing reacted. The ticket pipeline only dispatches tickets, so a PR whose owner
has answered sits there, and the wrap-up still listed it under "Needs Gil".

A PR is **waiting on MARVIN** when its latest owner Decisions comment (authored by the repo owner's account; the
dashboard posts as Gil) has not been followed by
  - an owner-account reply carrying ADDRESSED_MARKER (agents post as the same account, so a plain later comment
    proves nothing: the 06:15 "Owner idea" note on #577 was not an answer), or
  - a completed follow-up ticket for that same comment.
A commit alone no longer counts (marvin #733): it tells the owner nothing, so the follow-up asks for the reply.
Once it has waited GRACE_HOURS (default 4; MARVIN_DECISIONS_GRACE_HOURS overrides), the hourly ticket scan files ONE
follow-up ticket "Act on owner decisions on PR #N" (ready-for-agent, label owner-decisions), so the existing
dispatch machinery acts on it. The follow-up is closed again when the PR is addressed or closes. The dashboard's
ranked attention list (needs_you.js) shows the open follow-ups at the top from the issue list it already caches.

Triggers over polling: there is no new loop. "Nothing happened for N hours" needs a clock, and the hourly scan is
already that clock; the dashboard reacts to the follow-up ticket through its existing change watch.

Cost: one GraphQL search call per scan covers every registered repo's open PRs (last commit + last 30 comments each)
and the follow-up tickets: measured 2 points, ~32 KB for 19 PRs. Filing adds at most 3 calls per overdue PR, once.
Time O(P x C) over P open PRs and C comments each (P <= 100 per page, C <= 30); no local state is stored: GitHub is
the record, so both Macs agree.

Idempotent across Macs: only the scanner (primary, or the standby when the primary is quiet) files; before filing it
lists the follow-up label (a plain list, not search, so it is never stale); after filing it lists again and closes
every duplicate for the same comment except the lowest-numbered one, so a race still ends with exactly one.

    owner_decisions.py waiting [--json]   # PRs whose decisions are in and not yet acted on (not "Needs Gil")
    owner_decisions.py scan [--dry-run]   # what the hourly scan runs: file / close follow-ups
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

HEADING = "### Decisions from the owner"
ADDRESSED_MARKER = "<!-- marvin:decisions-addressed -->"
FOLLOWUP_LABEL = "owner-decisions"
DEFAULT_GRACE_HOURS = 4.0
COMMENTS_PER_PR = 30
MAX_PAGES = 5
_MARKER_RE = re.compile(r"<!-- marvin:owner-decisions pr=(\d+) comment=(\d+) since=(\S+) question=(yes|no) -->")
_JSON_BLOCK_RE = re.compile(r"```marvin-decisions[ \t]*\n(.*?)\n```", re.S)

_QUERY = """
query($q: String!, $f: String!, $after: String) {
  prs: search(query: $q, type: ISSUE, first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      number title url headRefName
      repository { nameWithOwner }
      commits(last: 1) { nodes { commit { committedDate } } }
      comments(last: %d) { nodes { databaseId url createdAt body author { login } } }
    } }
  }
  followups: search(query: $f, type: ISSUE, first: 100) {
    nodes { ... on Issue { number title url state stateReason body repository { nameWithOwner } } }
  }
}
""" % COMMENTS_PER_PR


def grace_hours(env=None) -> float:
    """MARVIN_DECISIONS_GRACE_HOURS when it is a sane number of hours (0 < h <= 168), else the default."""
    raw = (os.environ if env is None else env).get("MARVIN_DECISIONS_GRACE_HOURS")
    try:
        h = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_GRACE_HOURS
    return h if 0 < h <= 168 else DEFAULT_GRACE_HOURS


def _ts(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


# ── question detection ─────────────────────────────────────────────────────────────────────────────────────────

_STRIP_RE = re.compile(r"```.*?```|`[^`\n]*`|https?://\S+", re.S)
# Gil often types a question without its "?" (dyslexia): an auxiliary verb + a pronoun opening a sentence counts too.
_ASK_RE = re.compile(r"(?:^|[.!:\n])\s*(?:[-*]\s+)?(?:do|does|did|is|are|can|could|should|would|will|have|has)\s+"
                     r"(?:you|we|i|it|there|this|that|they|marvin)\b", re.I)


def has_question(texts) -> bool:
    for t in texts or []:
        if not isinstance(t, str):
            continue
        clean = _STRIP_RE.sub(" ", t)
        if "?" in clean or _ASK_RE.search(clean.strip()):
            return True
    return False


def parse_decisions_comment(body: str | None) -> dict | None:
    """None unless the body is a Decisions record. Malformed JSON still counts (the heading is the record's mark):
    the question check then reads the readable part instead."""
    if not isinstance(body, str) or not body.lstrip().startswith(HEADING):
        return None
    texts: list[str] = []
    malformed = True
    m = _JSON_BLOCK_RE.search(body)
    if m:
        try:
            answers = json.loads(m.group(1)).get("answers")
            if isinstance(answers, dict):
                malformed = False
                for a in answers.values():
                    if isinstance(a, dict):
                        texts += [a[k] for k in ("note", "text") if isinstance(a.get(k), str) and a[k].strip()]
        except (ValueError, AttributeError):
            malformed = True
    if malformed:
        # The readable rows are "- **<question>** <answer>": the questions MARVIN asked are not the owner's.
        texts = [re.sub(r"\*\*[^*\n]*\*\*", " ", body.split("<details>", 1)[0][len(body) - len(body.lstrip()) + len(HEADING):])]
    return {"malformed": malformed, "texts": texts, "question": has_question(texts)}


# ── per-PR status ──────────────────────────────────────────────────────────────────────────────────────────────

def _login(c: dict) -> str:
    return str(((c.get("author") or {}).get("login")) or "").lower()


def pr_status(pr: dict, now: datetime, grace: float, completed_comments: set[int] | frozenset = frozenset()) -> dict | None:
    """Where this PR's latest owner Decisions comment stands, or None if it has none."""
    repo = pr.get("repo") or ""
    owner = repo.split("/")[0].lower()
    comments = sorted((c for c in pr.get("comments") or [] if isinstance(c, dict) and _ts(c.get("createdAt"))),
                      key=lambda c: _ts(c["createdAt"]))
    latest, parsed = None, None
    for c in comments:
        p = parse_decisions_comment(c.get("body")) if owner and _login(c) == owner else None
        if p:
            latest, parsed = c, p
    if not latest:
        return None
    since = _ts(latest["createdAt"])
    last_commit = _ts(pr.get("last_commit_at"))
    # A commit alone tells the owner nothing (marvin #733: on clarity-captions #155 he couldn't tell whether the
    # screenshots were redone), so only a marked reply or a completed follow-up counts; the commit is noted for the ask.
    committed_since = bool(last_commit and last_commit > since)
    by = None
    if any(_login(c) == owner and ADDRESSED_MARKER in (c.get("body") or "") and _ts(c["createdAt"]) > since
             for c in comments):
        by = "reply"
    elif latest.get("databaseId") in completed_comments:
        by = "follow-up"
    age = (now - since).total_seconds() / 3600
    return {"repo": repo, "number": pr.get("number"), "title": pr.get("title") or "", "url": pr.get("url") or "",
            "branch": pr.get("headRefName") or "", "comment_id": latest.get("databaseId"),
            "comment_url": latest.get("url") or "", "since": latest["createdAt"], "question": parsed["question"],
            "malformed": parsed["malformed"], "texts": parsed["texts"], "addressed_by": by, "age_hours": age,
            "committed_since": committed_since,
            "overdue": by is None and age >= grace}


# ── GitHub (one call) ──────────────────────────────────────────────────────────────────────────────────────────

def _gh(args, run=subprocess.run):
    return run(["gh", *args], capture_output=True, text=True, timeout=60)


def fetch(repos, run=subprocess.run) -> dict | None:
    """{prs, followups, complete} for these repos, or None if GitHub could not be read (never act blind).
    complete=False when the PR list was cut short: then nothing is closed for 'PR no longer open'."""
    repos = {r for r in repos if isinstance(r, str) and "/" in r}
    if not repos:
        return {"prs": [], "followups": [], "complete": True}
    users = " ".join(f"user:{o}" for o in sorted({r.split("/")[0] for r in repos}))
    q = f"is:pr is:open archived:false {users}"
    f = f"is:issue label:{FOLLOWUP_LABEL} sort:updated-desc {users}"
    prs, followups, after, complete = [], [], None, False
    for _ in range(MAX_PAGES):
        args = ["api", "graphql", "-f", f"query={_QUERY}", "-F", f"q={q}", "-F", f"f={f}"]
        if after:
            args += ["-F", f"after={after}"]
        out = _gh(args, run)
        if out.returncode != 0:
            return None
        try:
            data = json.loads(out.stdout)["data"]
            page = data["prs"]
            for n in page["nodes"]:
                if not n or n["repository"]["nameWithOwner"] not in repos:
                    continue
                commits = (n.get("commits") or {}).get("nodes") or []
                prs.append({"repo": n["repository"]["nameWithOwner"], "number": n["number"], "title": n["title"],
                            "url": n["url"], "headRefName": n.get("headRefName"),
                            "last_commit_at": commits[-1]["commit"]["committedDate"] if commits else None,
                            "comments": (n.get("comments") or {}).get("nodes") or []})
            if after is None:
                followups = [x for x in (data.get("followups") or {}).get("nodes") or []
                             if x and x["repository"]["nameWithOwner"] in repos]
        except (ValueError, KeyError, TypeError):
            return None
        if not page["pageInfo"]["hasNextPage"]:
            complete = True
            break
        after = page["pageInfo"]["endCursor"]
    return {"prs": prs, "followups": followups, "complete": complete}


def followup_marker(body: str | None) -> dict | None:
    m = _MARKER_RE.search(body or "")
    return {"pr": int(m.group(1)), "comment": int(m.group(2)), "since": m.group(3), "question": m.group(4) == "yes"} if m else None


def _completed_comments(followups) -> set[int]:
    out = set()
    for x in followups or []:
        mk = followup_marker(x.get("body"))
        if mk and x.get("state") == "CLOSED" and x.get("stateReason") == "COMPLETED":
            out.add(mk["comment"])
    return out


def statuses(fetched: dict, now: datetime, grace: float) -> list[dict]:
    done = _completed_comments(fetched.get("followups"))
    return [s for s in (pr_status(p, now, grace, done) for p in fetched.get("prs") or []) if s]


def waiting(repos, now: datetime | None = None, run=subprocess.run) -> list[dict] | None:
    """PRs whose owner decisions are in and not yet acted on, any age (they wait on MARVIN, not on Gil)."""
    data = fetch(repos, run)
    if data is None:
        return None
    return [s for s in statuses(data, now or datetime.now(timezone.utc), grace_hours()) if not s["addressed_by"]]


# ── the follow-up ticket ───────────────────────────────────────────────────────────────────────────────────────

def followup_title(number: int) -> str:
    return f"Act on owner decisions on PR #{number}"


def followup_body(s: dict) -> str:
    quoted = "\n".join(f"> {line}" for t in s["texts"] for line in str(t).strip().splitlines()) or "> (no notes)"
    ask = ("**The owner asked a question.** Answer it on the PR. " if s["question"] else "")
    state = ("The PR already has commits since then, but no reply says what they changed, so the owner can't tell. "
             "Check whether they carry out every choice, finish what they don't, and post the reply."
             if s.get("committed_since") else "Nothing has acted on them: no commit and no reply.")
    return f"""<!-- marvin:owner-decisions pr={s['number']} comment={s['comment_id']} since={s['since']} question={'yes' if s['question'] else 'no'} -->
## What to build

The owner submitted Decisions on PR #{s['number']} {s['title']} ({s['url']}) at {s['since']}, {s['age_hours']:.0f} hours
ago. {state} {ask}Record: {s['comment_url']}

{quoted}

Read the whole Decisions comment and the PR. Carry out the chosen options on the PR's branch (`{s['branch']}`) where you
can; if the work belongs in a new PR, link PR #{s['number']} from it. Answer every question the owner asked in a PR
comment that contains `{ADDRESSED_MARKER}`. The reply says what changed (with the commit), and whether the screenshots
were retaken and pinned to that commit, or why not (for example "the look didn't change, so the images stand"). If the
answer needs the owner to choose again, give him a Decisions section (docs/agents/decisions-format.md), never a question
in prose.

## Acceptance criteria

- [ ] Every chosen option is carried out or, if it can't be, the reply says why.
- [ ] Every owner question is answered in a reply on PR #{s['number']} carrying the addressed marker.
- [ ] The reply says what changed and whether the screenshots were retaken and pinned to the new commit, or why not.

## How we'll try to break it

- The notes contradict a chosen option: say so in the reply instead of guessing.
- The PR changed since the decisions: re-read it before acting.

Filed by the ticket scan (lib/owner_decisions.py, marvin#607). It closes itself once PR #{s['number']} is addressed or closed.
"""


def _list_label(repo: str, run) -> list[dict] | None:
    out = _gh(["issue", "list", "--repo", repo, "--label", FOLLOWUP_LABEL, "--state", "all", "--limit", "200",
               "--json", "number,state,body"], run)
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except ValueError:
        return None


def _file(s: dict, run, dry_run: bool) -> str:
    repo, cid = s["repo"], s["comment_id"]
    existing = _list_label(repo, run)
    if existing is None:
        return "skipped: could not list follow-ups"
    if any((followup_marker(i.get("body")) or {}).get("comment") == cid for i in existing):
        return "already filed"
    if dry_run:
        return "would file"
    _gh(["label", "create", FOLLOWUP_LABEL, "--repo", repo, "--color", "fbca04", "--force",
         "--description", "Follow-up: act on owner decisions on a PR"], run)
    labels = ["ready-for-agent", FOLLOWUP_LABEL] + (["project:marvin"] if repo == "G-Eskayo/marvin" else [])
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(followup_body(s))
        body_file = fh.name
    try:
        args = ["issue", "create", "--repo", repo, "--title", followup_title(s["number"]), "--body-file", body_file]
        for lab in labels:
            args += ["--label", lab]
        out = _gh(args, run)
    finally:
        os.unlink(body_file)
    if out.returncode != 0:
        return f"failed: {out.stderr.strip()[:120]}"
    _dedupe(repo, cid, run)
    return "filed " + out.stdout.strip()


def _dedupe(repo: str, cid: int, run) -> list[int]:
    """Both Macs racing each file one: keep the lowest-numbered open follow-up for this comment, close the rest."""
    issues = _list_label(repo, run) or []
    same = sorted(i["number"] for i in issues
                  if i.get("state") == "OPEN" and (followup_marker(i.get("body")) or {}).get("comment") == cid)
    for n in same[1:]:
        _gh(["issue", "close", str(n), "--repo", repo, "--reason", "not planned",
             "--comment", f"Duplicate of #{same[0]} (filed at the same moment from another Mac)."], run)
    return same[1:]


def sync(repos, now: datetime | None = None, run=subprocess.run, dry_run: bool = False, grace: float | None = None) -> dict:
    """The hourly scan's step: file follow-ups for overdue PRs, close follow-ups that are no longer needed."""
    now = now or datetime.now(timezone.utc)
    grace = grace_hours() if grace is None else grace
    data = fetch(repos, run)
    if data is None:
        return {"ok": False, "filed": [], "closed": [], "waiting": [], "note": "could not read GitHub; try next scan"}
    sts = statuses(data, now, grace)
    by_pr = {(s["repo"], s["number"]): s for s in sts}
    open_prs = {(p["repo"], p["number"]) for p in data["prs"]}
    open_fu: dict[tuple, list[dict]] = {}
    for x in data["followups"]:
        mk = followup_marker(x.get("body"))
        if mk and x.get("state") == "OPEN":
            open_fu.setdefault((x["repository"]["nameWithOwner"], mk["pr"]), []).append(x)
    filed, closed = [], []
    for s in sts:
        if s["overdue"] and (s["repo"], s["number"]) not in open_fu:
            filed.append({"repo": s["repo"], "pr": s["number"], "result": _file(s, run, dry_run)})
    for (repo, pr), items in open_fu.items():
        s = by_pr.get((repo, pr))
        if s and s["addressed_by"] == "reply":
            why = f"PR #{pr} was addressed (a {s['addressed_by']} after the decisions)."
        elif (repo, pr) not in open_prs and data["complete"]:
            why = f"PR #{pr} is no longer open."
        else:
            continue
        for x in items:
            if not dry_run:
                _gh(["issue", "close", str(x["number"]), "--repo", repo, "--comment", why], run)
            closed.append({"repo": repo, "number": x["number"], "pr": pr, "why": why})
    return {"ok": True, "filed": filed, "closed": closed, "waiting": [s for s in sts if not s["addressed_by"]]}


def summary_line(sync_result: dict) -> str:
    if not sync_result.get("ok"):
        return sync_result.get("note", "could not read GitHub")
    parts = [f"{len(sync_result['waiting'])} PR(s) waiting on MARVIN"]
    parts += [f"{f['repo'].split('/')[-1]} PR #{f['pr']}: {f['result']}" for f in sync_result["filed"]]
    parts += [f"closed #{c['number']} ({c['why']})" for c in sync_result["closed"]]
    return "; ".join(parts)


def _registered_repos() -> list[str]:
    import board_registry
    return [b["repo"] for b in board_registry.list_boards() if b.get("repo")]


def _describe(s: dict) -> str:
    repo = "" if s["repo"] == "G-Eskayo/marvin" else f"{s['repo'].split('/')[-1]} "
    flag = "owner asked a question, " if s["question"] else ""
    return f"{repo}PR #{s['number']} {s['title']} ({flag}decisions in {s['age_hours']:.0f} h ago)"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["waiting"]:
        rows = waiting(_registered_repos())
        if rows is None:
            print("could not read GitHub", file=sys.stderr)
            return 1
        if "--json" in argv:
            print(json.dumps([{k: v for k, v in r.items() if k != "texts"} for r in rows], indent=2))
        else:
            print("\n".join(_describe(r) for r in rows) or "No PR is waiting on MARVIN.")
        return 0
    if argv[:1] == ["scan"]:
        print(summary_line(sync(_registered_repos(), dry_run="--dry-run" in argv)))
        return 0
    print("usage: owner_decisions.py waiting [--json] | scan [--dry-run]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
