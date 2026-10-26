#!/usr/bin/env python3
"""The ticket agents: five small autonomous jobs that keep every project's tickets moving, run from the
hourly ticket-pipeline scan. They only ever change LABELS and add COMMENTS, every change is written to
an audit log with what was there before (so any of it can be reversed), and each agent starts in
"propose" mode: it lists what it WOULD do and does nothing, until a date (or until you flip it).

  prioritize    scores each open ticket (what it unblocks, deadlines, bug-ness, age) -> priority:p0..p3
  triage        untriaged tickets -> ready-for-agent / ready-for-human / needs-info (deterministic, no model)
  stale_claims  releases a claim:* nobody has touched for 2 days, if no work is in flight for it
  refeed        a denied ticket (needs-reengagement) goes back to the queue; after 2 tries, to a person
  project_tag   a ticket that clearly belongs to another project gets project:<id> (lib/project_tagger.py, ADR 0060);
                unclear ones are listed for Gil in Health, never guessed

Rules live in ticket_policy.py (pure). Config: ~/.agents/config/ticket_agents.json
  mode     "auto" (propose until act_after, then act) | "propose" | "act" | "off"
  agents   per-agent override: "propose" (never flips), "act", "off"
A ticket labelled `pinned` is never touched by any agent; `held` also protects its claim.

    ticket_agents.py run [--mode propose|act]    one pass now
    ticket_agents.py status                       the latest proposals and what was applied
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ticket_policy as pol  # noqa: E402
import project_tagger  # noqa: E402

HOME = Path.home()
CONFIG_PATH = HOME / ".agents" / "config" / "ticket_agents.json"
AUDIT_PATH = HOME / ".claude" / "logs" / "ticket-agent-actions.jsonl"
PROPOSALS_PATH = HOME / ".claude" / "logs" / "ticket-agent-proposals.json"
OVERRIDES_PATH = HOME / ".claude" / "catalog" / "overrides.json"
AGENTS = ("prioritize", "triage", "stale_claims", "refeed", "project_tag", "revisit")
APPLY_ORDER = ("stale_claims", "refeed", "revisit", "triage", "prioritize", "project_tag")
MAX_ACTIONS_PER_RUN = 30
MAX_REFEEDS = 2
DEAD_CLAIM_HOURS = 6       # a claim with no live run anywhere, idle this long, belongs to a run that died (#453)
MAX_CLAIM_RELEASES = 2     # released this often and still stuck: a person looks at it instead (#453)
TRIAGE_DISCLAIMER = pol.TRIAGE_DISCLAIMER          # defined in ticket_policy so run_ticket can tell our comments apart (#605)
AGENT_COMMENT_PREFIX = pol.AGENT_COMMENT_PREFIX


# ── config / modes ──────────────────────────────────────────────────────────

def load_config(path: Path = CONFIG_PATH) -> dict:
    try:
        cfg = json.loads(path.read_text())
        if isinstance(cfg, dict) and cfg.get("mode") in ("auto", "propose", "act", "off"):
            cfg.setdefault("agents", {})
            return cfg
    except (OSError, json.JSONDecodeError):
        pass
    return {"mode": "propose", "agents": {}}  # anything unreadable fails SAFE


def effective_mode(cfg: dict, agent: str, now: datetime) -> str:
    own = (cfg.get("agents") or {}).get(agent)
    if own in ("propose", "act", "off"):
        return own
    mode = cfg.get("mode", "propose")
    if mode == "auto":
        try:
            act_after = datetime.fromisoformat(cfg["act_after"] + "T00:00:00+00:00")
        except (KeyError, ValueError, TypeError):
            return "propose"
        return "act" if now >= act_after else "propose"
    return mode


# ── planners (pure) ─────────────────────────────────────────────────────────

def _act(agent, repo, t, op, arg, why):
    return {"agent": agent, "repo": repo, "number": t["number"], "title": t.get("title", ""), "op": op, "arg": arg, "why": why}


def _skippable(t) -> bool:
    return bool(set(pol.label_names(t)) & pol.SKIP_LABELS)


def plan_prioritize(repo, issues, due, owned, now):
    open_numbers = {t["number"] for t in issues}
    blocks: dict[int, int] = {}
    for t in issues:
        for b in pol.open_blockers(t, open_numbers):
            blocks[b] = blocks.get(b, 0) + 1
    out = []
    for t in issues:
        if _skippable(t):
            continue
        current = next((l for l in pol.label_names(t) if l in pol.PRIORITY_LABELS), None)
        if current and owned.get(t["number"]) != current:
            continue  # a person chose this priority; it is theirs
        score, reasons = pol.score_ticket(t, blocks.get(t["number"], 0), due, now)
        want = pol.priority_for(score)
        if want == current:
            continue
        why = f"score {score}: " + ("; ".join(reasons) or "nothing urgent")
        if current:
            out.append(_act("prioritize", repo, t, "remove_label", current, why))
        out.append(_act("prioritize", repo, t, "add_label", want, why))
    return out


def plan_triage(repo, issues, owned_needs_info=frozenset()):
    out = []
    for t in issues:
        if t["number"] in owned_needs_info and "needs-info" in pol.label_names(t):
            # "you answer -> triaged again": a ticket this agent parked is looked at again once it is complete
            v = pol.triage_verdict(t, recheck=True)
            if v and v["state"] != "needs-info":
                out.append(_act("triage", repo, t, "remove_label", "needs-info", "now " + v["why"]))
                out.append(_act("triage", repo, t, "add_label", v["state"], v["why"]))
            continue
        v = pol.triage_verdict(t)
        if not v:
            continue
        if "needs-triage" in pol.label_names(t):
            out.append(_act("triage", repo, t, "remove_label", "needs-triage", v["why"]))
        out.append(_act("triage", repo, t, "add_label", v["state"], v["why"]))
        if v["category"]:
            out.append(_act("triage", repo, t, "add_label", v["category"], "inferred from the title"))
        if v["state"] == "needs-info":
            ask = "\n".join(f"- {m}" for m in v["missing"])
            out.append(_act("triage", repo, t, "comment",
                            f"{TRIAGE_DISCLAIMER}\n\nThis ticket is missing:\n\n{ask}\n\nAdd those and it can be picked up.", v["why"]))
    return out


def plan_stale_claims(repo, issues, in_flight, now, running=None, releases=None):
    """Release claims nobody is using, so the queue never freezes behind them (#453).

    stale: untouched STALE_CLAIM_HOURS, no PR or branch in flight (the original rule; also the fallback when the
           process tables can't all be read).
    dead:  `running` (the tickets with a live run_ticket on any machine) was readable and this ticket has none, it
           has been idle DEAD_CLAIM_HOURS, and no PR or branch is in flight: the run that held it died or failed.
    A ticket already released MAX_CLAIM_RELEASES times (`releases`, from this agent's own audit log) is not put back
    a third time: it goes to ready-for-human, shown in the dashboard's Needs you, and Gil is notified.
    `held` keeps a claim (an interactive session that wants a long quiet claim adds it); `pinned` is never touched."""
    out = []
    releases = releases or {}
    for t in issues:
        names = set(pol.label_names(t))
        if names & pol.SKIP_LABELS or "held" in names or t["number"] in in_flight:
            continue
        s = pol.stale_claim(t, now, hours=DEAD_CLAIM_HOURS) if running is not None and t["number"] not in running else None
        why = f"claimed by {s['machine']}, idle {s['idle_hours']}h, no run alive for it anywhere" if s else ""
        if not s:
            s = pol.stale_claim(t, now)
            why = f"claimed by {s['machine']}, untouched {s['idle_hours']}h, no work in flight" if s else ""
        if not s:
            continue
        claim = f"claimed:{s['machine']}"
        n = releases.get(t["number"], 0)
        out.append(_act("stale_claims", repo, t, "remove_label", claim, why))
        if n >= MAX_CLAIM_RELEASES:
            if "ready-for-agent" in names:
                out.append(_act("stale_claims", repo, t, "remove_label", "ready-for-agent", "loop guard"))
            out.append(_act("stale_claims", repo, t, "add_label", "ready-for-human", f"claim released {n} times already"))
            out.append(_act("stale_claims", repo, t, "comment",
                            f"{AGENT_COMMENT_PREFIX} the claim by `{s['machine']}` was released {n} times already and the ticket is "
                            f"stuck again ({why}), so it is handed to a person instead of going back to the queue. To retry "
                            f"it, remove `ready-for-human` and add `ready-for-agent`.\n{pol.HANDOFF_MARKER}", "loop guard"))
            out.append(_act("stale_claims", repo, t, "notify", f"claim released {n} times and stuck again", "loop guard"))
            continue
        out.append(_act("stale_claims", repo, t, "comment",
                        f"{AGENT_COMMENT_PREFIX} released the claim by `{s['machine']}` ({why}), so the ticket is back in the "
                        f"queue. Add the `held` label to keep a claim.", "released claim"))
    return out


def plan_refeed(repo, issues, counts):
    """A sent-back ticket goes back to the queue, or after MAX_REFEEDS to a person (pol.NEEDS_PERSON_LABELS). Going to
    a person takes ready-for-agent and every claim off, so the dispatcher stops starting it (#605: #218 kept
    ready-for-agent beside ready-for-human and was planned every ~15 min). A ticket already with a person only loses a
    stray sent-back flag, quietly: it is told "needs a person" once, not on every scan. O(tickets x labels), no I/O."""
    out = []
    for t in issues:
        names = set(pol.label_names(t))
        if "needs-reengagement" not in names or names & pol.SKIP_LABELS or "held" in names:
            continue
        if pol.needs_person(names):
            out.append(_act("refeed", repo, t, "remove_label", "needs-reengagement", "already with a person"))
            continue
        n = counts.get(t["number"], 0)
        out.append(_act("refeed", repo, t, "remove_label", "needs-reengagement", "denied or failed the merge gate"))
        if n >= MAX_REFEEDS:
            out.append(_act("refeed", repo, t, "add_label", "ready-for-human", f"re-queued {n} times already"))
            for label in sorted(l for l in names if l == "ready-for-agent" or l.startswith("claimed:")):
                out.append(_act("refeed", repo, t, "remove_label", label, "loop guard"))
            out.append(_act("refeed", repo, t, "comment",
                            f"{AGENT_COMMENT_PREFIX} this was sent back {n} times and still was not accepted. It needs a "
                            f"person. To retry it, remove `ready-for-human` and add `ready-for-agent`.\n{pol.HANDOFF_MARKER}",
                            "loop guard"))
        else:
            out.append(_act("refeed", repo, t, "add_label", "ready-for-agent", f"attempt {n + 1} of {MAX_REFEEDS}"))
            out.append(_act("refeed", repo, t, "comment",
                            f"{AUTOMATED_NOTE(n)}", "re-queue with the denial feedback"))
    return out


def AUTOMATED_NOTE(n: int) -> str:
    return (f"{AGENT_COMMENT_PREFIX} re-queued for the pipeline (attempt {n + 1} of {MAX_REFEEDS}). "
            f"The comments above, including the denial feedback, are requirements for the next attempt.")


def _ref_number(condition) -> int | None:
    """The ticket a revisit condition names ("#412 merges" -> 412), else None. A date-only "Revisit by:" line has
    condition None: reading it as a string crashed every ticket-agents pass from 10-09 to 10-21 (270 of 273 scans),
    so no agent (prioritize, triage, stale claims, refeed, tags) applied anything in that time."""
    m = re.match(r"#(\d+)\b", condition.strip()) if isinstance(condition, str) else None
    return int(m.group(1)) if m else None


def plan_revisit(repo, issues, hold_comments, ref_states, now):
    """Return tickets on hold that are due for revisit (date passed or condition closed).
    ref_states: {number: {"state": "OPEN"|"CLOSED"}} for condition refs."""
    out = []
    for t in issues:
        names = set(pol.label_names(t))
        if "hold" not in names or "pinned" in names:
            continue
        revisit = pol.latest_revisit(hold_comments.get(t["number"], []))
        if not revisit:
            continue  # no revisit line: that's Health's job, not this agent's
        ref_num = _ref_number(revisit.get("condition"))
        ref_state = ref_states.get(ref_num, {}) if ref_num else {}
        # is_revisit_due wants the whole {number: state} map; handed one ticket's state it never saw a closed
        # condition, so a hold only ever lifted on its date.
        if not pol.is_revisit_due(revisit, now, ref_states):
            continue
        why = "revisit date passed"
        if ref_num and ref_state.get("state") == "CLOSED":
            why = f"condition #{ref_num} closed"
        out.append(_act("revisit", repo, t, "remove_label", "hold", why))
        out.append(_act("revisit", repo, t, "add_label", "needs-triage", "ready for re-evaluation"))
        comment_body = f"{AGENT_COMMENT_PREFIX} released from hold: {why}."
        out.append(_act("revisit", repo, t, "comment", comment_body, why))
    return out


# ── audit ───────────────────────────────────────────────────────────────────

def _read_audit(path: Path) -> list[dict]:
    try:
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    except (OSError, json.JSONDecodeError):
        return []


def owned_priorities(path: Path, repo: str) -> dict[int, str]:
    """Priority labels this agent set (last applied one wins) -- anything else on a ticket is a person's choice."""
    owned: dict[int, str] = {}
    for r in _read_audit(path):
        if r.get("status") != "applied" or r.get("agent") != "prioritize" or r.get("repo") != repo:
            continue
        if r["op"] == "add_label":
            owned[r["number"]] = r["arg"]
        elif r["op"] == "remove_label" and owned.get(r["number"]) == r["arg"]:
            owned.pop(r["number"], None)
    return owned


def owned_needs_info(path: Path, repo: str) -> set[int]:
    """Tickets the triage agent marked needs-info (and hasn't taken it off since): it may look at them again;
    a needs-info a person set stays theirs."""
    owned: set[int] = set()
    for r in _read_audit(path):
        if r.get("status") != "applied" or r.get("agent") != "triage" or r.get("repo") != repo or r.get("arg") != "needs-info":
            continue
        (owned.add if r["op"] == "add_label" else owned.discard)(r["number"])
    return owned


def release_counts(path: Path, repo: str) -> dict[int, int]:
    """How often this agent has released each ticket's claim (applied releases in its own audit log)."""
    counts: dict[int, int] = {}
    for r in _read_audit(path):
        if (r.get("status") == "applied" and r.get("agent") == "stale_claims" and r.get("repo") == repo
                and r.get("op") == "remove_label" and str(r.get("arg", "")).startswith("claimed:")):
            counts[r["number"]] = counts.get(r["number"], 0) + 1
    return counts


def refeed_counts(path: Path, repo: str) -> dict[int, int]:
    counts: dict[int, int] = {}
    for r in _read_audit(path):
        if r.get("status") == "applied" and r.get("agent") == "refeed" and r.get("repo") == repo and r["op"] == "add_label" and r["arg"] == "ready-for-agent":
            counts[r["number"]] = counts.get(r["number"], 0) + 1
    return counts


HOLD_REVISIT_PATH = HOME / ".claude" / "logs" / "hold-revisit.json"


def collect_hold_comments(repo: str, held_numbers: set[int], gh) -> dict[int, list]:
    """Fetch comments for all held tickets in one gh call. Returns {number: [comments]}.
    Returns {} on any error (network, permissions, malformed)."""
    if not held_numbers:
        return {}
    try:
        issues_json = gh(["issue", "list", "--repo", repo, "--label", "hold",
                          "--state", "open", "--json", "number,comments"])
        issues = json.loads(issues_json)
    except Exception:  # noqa: BLE001
        return {}
    result = {}
    for issue in issues:
        n = issue.get("number")
        comments = issue.get("comments", [])
        if n and isinstance(comments, list):
            result[n] = comments
    return result


def write_revisit_state(tickets_without_revisit: list[dict], path: Path, now: datetime) -> None:
    """Write {generated_at, without_revisit: []} atomically via tmp-then-rename.
    Mirrors project_tagger.write_state pattern."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_stem(path.stem + ".tmp")
        data = {
            "generated_at": now.isoformat(),
            "without_revisit": [{"repo": t["repo"], "number": t["number"], "title": t.get("title", "")}
                               for t in tickets_without_revisit[:50]]  # truncate at 50 like project_tags
        }
        tmp.write_text(json.dumps(data) + "\n")
        tmp.replace(path)
    except OSError:
        pass  # never stop the run


# ── applying ────────────────────────────────────────────────────────────────

def apply_action(a: dict, gh) -> None:
    base = ["--repo", a["repo"]]
    if a["op"] == "add_label":
        try:
            gh(["issue", "edit", str(a["number"]), *base, "--add-label", a["arg"]])
        except Exception as e:  # noqa: BLE001
            # gh puts the reason on stderr; CalledProcessError's message doesn't include it
            if "not found" not in f"{e} {getattr(e, 'stderr', '') or ''}".lower():
                raise
            # a project that has never had this label (priority:p1, ready-for-human...): create it, retry once
            gh(["label", "create", a["arg"], *base])
            gh(["issue", "edit", str(a["number"]), *base, "--add-label", a["arg"]])
    elif a["op"] == "remove_label":
        gh(["issue", "edit", str(a["number"]), *base, "--remove-label", a["arg"]])
    elif a["op"] == "comment":
        gh(["issue", "comment", str(a["number"]), *base, "--body", a["arg"]])
    elif a["op"] == "notify":   # it is in Needs you now: tell Gil where he will see it (mr_notification's channels)
        import mr_notification
        mr_notification.notify_needs_you(f"{a['repo'].split('/')[-1]}#{a['number']}", a["arg"],
                                         f"https://github.com/{a['repo']}/issues/{a['number']}")


def _write(path: Path, rows: list[dict], mode="a") -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, mode) as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    except OSError:
        pass  # the audit must never stop the job; the proposals file still tells the story


def run(snapshot, gh, cfg, now, audit_path=AUDIT_PATH, proposals_path=PROPOSALS_PATH, in_flight=lambda repo: set(),
        due_for=lambda repo: None, report=None, executable=None, project_rules=None, tags_state_path=None, revisit_state_path=None,
        running=lambda repo: None) -> dict:
    """One pass over every repo in `snapshot` ({repo: {"issues": [...], "prs": [...]}}).
    `tags_state_path`: where the project tagger's unclear list goes (the real run passes project_tagger.STATE_PATH).
    `revisit_state_path`: where the revisit agent's "without revisit" list goes."""
    report = report or (lambda *a, **k: None)
    rules = project_rules if project_rules is not None else project_tagger.load_rules()
    labels_now = {(r, t["number"]): pol.label_names(t) for r, d in snapshot.items() for t in d["issues"]}
    removed = project_tagger.removed_by_people(_read_audit(audit_path), labels_now)
    unclear: list[dict] = []
    without_revisit: list[dict] = []
    executable = set(executable) if executable else {"G-Eskayo/marvin"}  # projects the executor can run
    modes = {a: effective_mode(cfg, a, now) for a in AGENTS}
    planned: list[dict] = []
    for repo, data in snapshot.items():
        issues = data["issues"]
        if modes["prioritize"] != "off":
            planned += plan_prioritize(repo, issues, due_for(repo), owned_priorities(audit_path, repo), now)
        if modes["triage"] != "off":
            planned += plan_triage(repo, issues, owned_needs_info(audit_path, repo))
        if repo in executable:  # claims and re-queues belong to the executor, so only projects it can run
            if modes["stale_claims"] != "off":
                planned += plan_stale_claims(repo, issues, in_flight(repo), now, running=running(repo),
                                             releases=release_counts(audit_path, repo))
            if modes["refeed"] != "off":
                planned += plan_refeed(repo, issues, refeed_counts(audit_path, repo))
            if modes["revisit"] != "off":
                held_numbers = {t["number"] for t in issues if "hold" in pol.label_names(t)}
                hold_comments = collect_hold_comments(repo, held_numbers, gh)
                ref_numbers = {n for t in issues if "hold" in pol.label_names(t)
                               for n in [_ref_number((pol.latest_revisit(hold_comments.get(t["number"], [])) or {}).get("condition"))]
                               if n is not None}
                ref_states = {}
                for ref_num in ref_numbers:
                    try:
                        ref_info = json.loads(gh(["issue", "view", str(ref_num), "--repo", repo, "--json", "state"]))
                        ref_states[ref_num] = {"state": ref_info.get("state", "OPEN")}
                    except Exception:  # noqa: BLE001
                        pass
                planned += plan_revisit(repo, issues, hold_comments, ref_states, now)
                for t in issues:
                    if "hold" in pol.label_names(t) and "pinned" not in pol.label_names(t):
                        if not pol.latest_revisit(hold_comments.get(t["number"], [])):
                            without_revisit.append({"repo": repo, "number": t["number"], "title": t.get("title", "")})
        if modes["project_tag"] != "off":
            tags, unsure = project_tagger.plan(repo, issues, rules, removed)
            planned += tags
            unclear += unsure

    # Unfreezing the queue goes first: claims, re-queues and lifted holds before labels. With a backlog (12 days of
    # crashed passes left 100+ label changes) the per-pass budget would otherwise hold claim releases back for hours.
    planned.sort(key=lambda a: APPLY_ORDER.index(a["agent"]) if a["agent"] in APPLY_ORDER else len(APPLY_ORDER))
    by_agent = {a: {"mode": modes[a], "planned": sum(1 for p in planned if p["agent"] == a)} for a in AGENTS}
    applied = failed = deferred = 0
    rows, proposals = [], []
    ts = now.isoformat()
    labels_before = {(r, t["number"]): pol.label_names(t) for r, d in snapshot.items() for t in d["issues"]}
    budget = MAX_ACTIONS_PER_RUN
    for a in planned:
        before = labels_before.get((a["repo"], a["number"]), [])
        if modes[a["agent"]] != "act":
            proposals.append(a)
            rows.append({**a, "at": ts, "status": "proposed", "before_labels": before})
            continue
        if budget <= 0:
            deferred += 1
            proposals.append(a)  # waits for the next hourly pass
            continue
        try:
            apply_action(a, gh)
            budget -= 1
            applied += 1
            rows.append({**a, "at": ts, "status": "applied", "before_labels": before})
        except Exception as e:  # noqa: BLE001
            failed += 1
            why = f"{e} {getattr(e, 'stderr', '') or ''}".strip()  # gh's own reason is on stderr
            rows.append({**a, "at": ts, "status": "failed", "error": why[-300:], "before_labels": before})
    for agent, info in by_agent.items():
        report(agent, f"{info['mode']}: {info['planned']} change(s) planned")
    if tags_state_path is not None:
        pending = sum(1 for p in proposals if p["agent"] == "project_tag")
        project_tagger.write_state(unclear, pending, tags_state_path, ts)
    if revisit_state_path is not None:
        write_revisit_state(without_revisit, revisit_state_path, now)
    _write(audit_path, rows)
    _write(proposals_path, [{
        "generated_at": ts, "mode": cfg.get("mode"), "act_after": cfg.get("act_after"),
        "effective_mode": modes["prioritize"], "by_agent": by_agent, "proposals": proposals,
    }], mode="w")
    return {"proposed": len(proposals), "applied": applied, "failed": failed, "deferred": deferred, "by_agent": by_agent}


# ── real data sources ───────────────────────────────────────────────────────

def _gh(args):
    from project_catalog import run_env
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True, timeout=60, env=run_env()).stdout


def collect(repos, gh=_gh) -> dict:
    snap = {}
    for repo in repos:
        try:
            issues = json.loads(gh(["issue", "list", "--repo", repo, "--state", "open", "--limit", "1000",
                                    "--json", "number,title,labels,body,createdAt,updatedAt"]))
            prs = json.loads(gh(["pr", "list", "--repo", repo, "--state", "open", "--limit", "100", "--json", "number,body,headRefName"]))
            snap[repo] = {"issues": issues, "prs": prs}
        except Exception:  # noqa: BLE001 -- one repo being unreachable must not stop the others
            continue
    return snap


_BRANCH_NUM = re.compile(r"(?:#|(?:issue|ticket)[-_/]?|(?<=[/-]))(\d+)(?=[-_/.]|$)")


def in_flight_numbers(repo, snapshot, git_runner=None) -> set[int]:
    """Tickets with work that a release would orphan: an open PR that closes/mentions them, or a pushed branch named
    for them (pipeline/...#454, fix/457-main-health, ticket-336). Rescue refs are NOT in flight: they are a finished
    or dead attempt, already preserved, and counting them kept every ticket that ever failed claimed for ever (#453)."""
    nums: set[int] = set()
    for p in snapshot.get(repo, {}).get("prs", []):
        nums |= {int(n) for n in re.findall(r"#(\d+)", (p.get("body") or "") + " " + (p.get("headRefName") or ""))}
        nums |= {int(n) for n in _BRANCH_NUM.findall(p.get("headRefName") or "")}
    try:
        out = (git_runner or (lambda: subprocess.run(["git", "-C", str(HOME / ".agents"), "ls-remote", "origin", "refs/heads/*"],
                                                     capture_output=True, text=True, timeout=30).stdout))()
    except Exception:  # noqa: BLE001
        out = ""
    for line in out.splitlines():
        ref = line.split("\t")[-1]
        if ref.startswith("refs/rescue/"):
            continue
        nums |= {int(n) for n in _BRANCH_NUM.findall(ref.removeprefix("refs/heads/"))}
    return nums


def due_for_repo(repo, overrides_path: Path = OVERRIDES_PATH):
    try:
        data = json.loads(overrides_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    pid = re.sub(r"[^a-z0-9]+", "-", repo.split("/")[-1].lower()).strip("-")
    o = data.get(pid) or {}
    return ({"date": o["due"], "hard": bool(o.get("dueHard")), "excludes": [str(b).upper() for b in o.get("dueExcludes", [])]}
            if o.get("due") else None)


def ready_elsewhere(snapshot, executable=None) -> dict[str, int]:
    """Projects the executor cannot run (yet) that have tickets ready for an agent: they wait for an
    execution profile with dispatch switched on. Shown, not hidden."""
    executable = set(executable) if executable else {"G-Eskayo/marvin"}
    out = {}
    for repo, data in snapshot.items():
        if repo in executable:
            continue
        open_numbers = {t["number"] for t in data["issues"]}
        n = sum(1 for t in data["issues"] if "ready-for-agent" in pol.label_names(t) and not pol.claim_of(t)
                and not pol.open_blockers(t, open_numbers) and "pinned" not in pol.label_names(t))
        if n:
            out[repo] = n
    return out


def board_repos() -> list[str]:
    import board_registry
    return [b["repo"] for b in board_registry.list_boards()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--mode", choices=["propose", "act"])
    sub.add_parser("status")
    a = ap.parse_args()
    if a.cmd == "status":
        try:
            p = json.loads(PROPOSALS_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            print("no run recorded yet")
            return 0
        print(f"{p['generated_at']}  mode={p['effective_mode']}  proposals={len(p['proposals'])}")
        for x in p["proposals"][:40]:
            print(f"  {x['agent']:<13} {x['repo'].split('/')[1]}#{x['number']:<4} {x['op']:<13} {x['arg'][:40]:<40} {x['why'][:70]}")
        return 0
    cfg = load_config()
    if a.mode:
        cfg = {**cfg, "mode": a.mode, "agents": {}}
    snap = collect(board_repos())
    res = run(snap, _gh, cfg, datetime.now(timezone.utc), in_flight=lambda repo: in_flight_numbers(repo, snap), due_for=due_for_repo,
              tags_state_path=project_tagger.STATE_PATH, revisit_state_path=HOLD_REVISIT_PATH)
    print(json.dumps({k: v for k, v in res.items() if k != "by_agent"}), {k: v["mode"] for k, v in res["by_agent"].items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
