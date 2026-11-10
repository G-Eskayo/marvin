#!/usr/bin/env python3
"""Resume check: a handoff's ticket and PR claims are checked against GitHub before SessionStart surfaces it
(marvin#1221; piece 1 of instance/docs/plans/data-freshness-2026-11-09.md).

A handoff is a cache: written once, read later. On 2026-11-09 a handoff rebuilt from a Nov 3 session called
portfolio-website-updater #17 "URGENT" two days after its PRs had merged, and it was relayed twice. The handoff skill
already said "check live state first"; prose didn't hold, so the check lives at the one choke point every resumed
claim passes through (session_start_report.check_handoff and check_remote_session's resume prompt):

  dated by content   front matter `as_of` (the last real activity), `machine`, `session`; no stamp means mtime,
                     labelled "undated"; an `as_of` in the future (clock skew between Macs) is clamped to now
  one parser         refs come from dashboard/electron/main/relations.js extractRefs through refs_cli.mjs (node),
                     the same shape as decisions_check.py + decisions_cli.js; there is no Python copy
  one call           one GraphQL query through bin/gh for every ref (capped at MAX_REFS), with a 5 s budget
  changed            closed, reopened or merged after `as_of`, or (for a ticket) a closing PR merged after it;
                     a PR merged before `as_of` is not a change
  fail labelled      node missing, gh missing, rate limit, timeout, network off: "as of <date>, unverified", never
                     silent; a ref GitHub can't read (private, deleted) is listed, not counted as changed
  logged             each run appends to ~/.agents/var/resume-checks.jsonl (the stale-relay probe reads it, #1224)

Titles from GitHub are data: they are flattened to one quoted line with markup removed before they're shown.

    resume_check.py [handoff.md]   # print the check for a handoff (default: the newest), for a person to run
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from decisions_check import find_node  # noqa: E402,F401  (one node finder; re-exported for callers and tests)

HOME = Path.home()
CLI = Path(__file__).resolve().parents[1] / "dashboard" / "electron" / "main" / "refs_cli.mjs"
LOG = HOME / ".agents" / "var" / "resume-checks.jsonl"
GH = HOME / ".agents" / "bin" / "gh"
BUDGET_S = 5.0
NODE_MAX_S = 2.0
MAX_REFS = 50          # one query stays well inside GitHub's node limits; the rest are reported "not checked"
MAX_SHOWN = 8          # changed items listed in the report (the session-start report has a 10 KB budget)
FUTURE_SLACK = timedelta(minutes=5)
TITLE_MAX = 80
UTC = timezone.utc

URGENT = re.compile(r"\b(urgent|do (?:this |it )?first|first thing|immediately|asap|before anything else|"
                    r"top priority|blocker|blocking)\b", re.IGNORECASE)
_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_KEY = re.compile(r"^[a-z_][a-z0-9_]*$")


# ── dating ───────────────────────────────────────────────────────────────────

@dataclass
class When:
    at: datetime            # the effective "as of" (clamped to now)
    dated: bool             # False: no usable as_of, `at` is the file's mtime
    note: str | None        # e.g. clock skew
    machine: str | None


def parse_front_matter(text: str) -> dict:
    """The `key: value` block between a leading `---` and the next `---`, or {} when absent or garbled."""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out = {}
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep or not _KEY.match(key.strip()):
            return {}
        out[key.strip()] = value.strip()
    return out


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def handoff_time_from_text(text: str, fallback: datetime, now: datetime) -> When:
    fm = parse_front_matter(text)
    at = _parse_time(fm.get("as_of"))
    machine = fm.get("machine") or None
    if at is None:
        return When(fallback, False, None, machine)
    if at > now + FUTURE_SLACK:
        return When(now, True, f"its as_of ({at:%Y-%m-%d %H:%M} UTC) is in the future: clock skew?", machine)
    return When(min(at, now), True, None, machine)


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def handoff_time(path: Path, now: datetime) -> When:
    try:
        with path.open(errors="replace") as f:
            head = f.read(4096)
    except OSError:
        head = ""
    return handoff_time_from_text(head, datetime.fromtimestamp(_mtime(path), tz=UTC), now)


def ranked_handoffs(directory: Path, now: datetime | None = None, pattern: str = "handoff-*.md") -> list[tuple[Path, When]]:
    """Newest first by content date (`as_of`), mtime breaking ties and dating the undated."""
    now = now or datetime.now(UTC)
    rows = [(p, handoff_time(p, now)) for p in directory.glob(pattern)] if directory.is_dir() else []
    return sorted(rows, key=lambda r: (r[1].at, _mtime(r[0])), reverse=True)


def resume_prompt(text: str) -> str:
    m = re.search(r"##\s*Resume prompt\s*\n(.*)$", text, re.DOTALL | re.IGNORECASE)
    return (m.group(1) if m else "").strip().strip("-").strip()


# ── refs (one parser: relations.js) ──────────────────────────────────────────

def default_repos() -> dict:
    """{short name: owner/repo} for every project profile, so "portfolio-website-updater #17" is that repo's."""
    try:
        import project_profile
        return {p["repo"].split("/", 1)[1]: p["repo"] for p in project_profile.all_profiles() if "/" in p["repo"]}
    except Exception:  # noqa: BLE001  (no profiles: qualified and bare refs still work)
        return {}


def _home_repo() -> str:
    """Where a bare "#N" in a handoff points: the tickets repo (lib/instance.py)."""
    import instance
    return instance.tickets_repo()


def extract_refs(texts: list[str], *, repos: dict, default_repo: str | None, node, cli: Path = CLI,
                 timeout: float = NODE_MAX_S) -> list[list[str]]:
    """Per text, its refs as "owner/repo#n" keys (a bare ref is "#n" when default_repo is None, for the caller to
    place). Raises RuntimeError when the parser can't run."""
    if not node:
        raise RuntimeError("node isn't installed, so the refs couldn't be read")
    p = subprocess.run([node, "--no-warnings", str(cli)], capture_output=True, text=True, timeout=timeout,
                       input=json.dumps({"texts": texts, "repos": repos, "defaultRepo": default_repo,
                                         "keepBare": default_repo is None}))
    if p.returncode != 0:
        raise RuntimeError(f"the refs parser failed ({(p.stderr or '').strip()[-160:] or p.returncode})")
    out = json.loads(p.stdout)["refs"]

    def key(r):
        if r["repo"] is None:
            return f"#{r['number']}"
        repo = str(r["repo"])
        return f"{repo}#{r['number']}" if repo.count("/") == 1 and all(_NAME.match(x) for x in repo.split("/")) else None

    return [[k for k in map(key, refs) if k] for refs in out]


# ── GitHub (one call) ────────────────────────────────────────────────────────

_FIELDS = (
    "__typename "
    "... on Issue { title state url "
    "timelineItems(itemTypes: [CLOSED_EVENT, REOPENED_EVENT], last: 10) "
    "{ nodes { __typename ... on ClosedEvent { createdAt } ... on ReopenedEvent { createdAt } } } "
    "closedByPullRequestsReferences(first: 5, includeClosedPrs: true) "
    "{ nodes { number mergedAt repository { nameWithOwner } } } } "
    "... on PullRequest { title state url mergedAt "
    "timelineItems(itemTypes: [CLOSED_EVENT, REOPENED_EVENT, MERGED_EVENT], last: 10) "
    "{ nodes { __typename ... on ClosedEvent { createdAt } ... on ReopenedEvent { createdAt } "
    "... on MergedEvent { createdAt } } } }"
)


_EXTRA = "body labels(first: 20) { nodes { name } } "   # for callers that judge the ticket itself (lib/parked.py)


def build_query(keys: list[str], with_body: bool = False) -> str:
    parts = []
    for i, key in enumerate(keys):
        repo, n = key.rsplit("#", 1)
        owner, name = repo.split("/", 1)
        if not (_NAME.match(owner) and _NAME.match(name) and n.isdigit()):
            continue  # never interpolate anything that isn't a plain name
        parts.append(f'i{i}: repository(owner: "{owner}", name: "{name}") '
                     f'{{ issueOrPullRequest(number: {int(n)}) {{ {_FIELDS.replace("... on Issue { ", "... on Issue { " + _EXTRA) if with_body else _FIELDS} }} }}')
    return "query { " + " ".join(parts) + " }"


def fetch(keys: list[str], *, run, timeout: float, gh=None, with_body: bool = False) -> dict:
    """{key: node or None}. Raises RuntimeError with a reason a person can read when GitHub gave no answer."""
    gh = gh or (str(GH) if GH.exists() else "gh")
    try:
        p = run([gh, "api", "graphql", "-f", f"query={build_query(keys, with_body)}"], capture_output=True, text=True,
                timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"GitHub timed out after {timeout:g} s") from None
    except OSError as e:
        raise RuntimeError(f"gh couldn't run ({e.__class__.__name__})") from None
    err = (p.stderr or "").strip()
    if p.returncode == 75 or "rate limit" in err.lower():
        raise RuntimeError("GitHub rate limit (the gate is cooling down)")
    try:
        data = json.loads(p.stdout or "")["data"]
    except (ValueError, KeyError, TypeError):
        if p.returncode != 0:
            raise RuntimeError(f"GitHub unreachable ({err.splitlines()[-1][:120] if err else f'exit {p.returncode}'})") from None
        raise RuntimeError("GitHub's reply was unreadable") from None
    if not isinstance(data, dict):
        raise RuntimeError("GitHub's reply was unreadable")
    out = {}
    for i, key in enumerate(keys):
        hit = data.get(f"i{i}")
        out[key] = (hit or {}).get("issueOrPullRequest") if isinstance(hit, dict) else None
    return out


def _day(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%d")


def changes_since(node: dict, as_of: datetime, repo: str) -> list[str]:
    is_pr = node.get("__typename") == "PullRequest"
    merged = _parse_time(node.get("mergedAt"))
    events = []
    for e in ((node.get("timelineItems") or {}).get("nodes") or []):
        t = _parse_time((e or {}).get("createdAt"))
        if t is None or t <= as_of:
            continue
        kind = e.get("__typename")
        if kind == "MergedEvent":
            events.append((t, "merged"))
        elif kind == "ReopenedEvent":
            events.append((t, "reopened"))
        elif kind == "ClosedEvent":
            if is_pr and merged and abs((t - merged).total_seconds()) <= 120:
                continue  # a merge also closes; say it once, as "merged"
            events.append((t, "closed unmerged" if is_pr else "closed"))
    if not is_pr:
        for c in ((node.get("closedByPullRequestsReferences") or {}).get("nodes") or []):
            t = _parse_time((c or {}).get("mergedAt"))
            if t and t > as_of:
                other = (c.get("repository") or {}).get("nameWithOwner")
                name = f"#{c.get('number')}" if not other or other == repo else f"{other}#{c.get('number')}"
                events.append((t, f"PR {name} merged"))
    return [f"{what} {_day(t)}" for t, what in sorted(events, key=lambda x: x[0])]


def sanitize(text: str) -> str:
    """A GitHub title as data: one line, no markup that could render or read as an instruction heading."""
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", str(text or ""))
    s = re.sub(r"[`<>\[\]#~*|\\]", "", s).replace('"', "'")
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= TITLE_MAX else s[:TITLE_MAX - 1].rstrip() + "…"


# ── the check ────────────────────────────────────────────────────────────────

@dataclass
class Changed:
    key: str
    title: str
    events: list[str]

    def line(self) -> str:
        return f'{self.key} "{sanitize(self.title)}": {", ".join(self.events)}'


@dataclass
class Report:
    status: str                       # verified | unverified | no-refs
    when: When
    checked: int = 0
    changed: list[Changed] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    skipped: int = 0
    reason: str | None = None
    refs: int = 0
    line_refs: dict = field(default_factory=dict)   # urgent line (stripped) -> its ref keys

    def struck_lines(self) -> list[str]:
        changed = {c.key for c in self.changed}
        return [ln for ln, keys in self.line_refs.items() if changed & set(keys)]


def check(text: str, when: When, *, run=subprocess.run, repos: dict | None = None, now: datetime | None = None,
          node=True, cli: Path = CLI, default_repo: str | None = None, budget: float = BUDGET_S, gh=None) -> Report:
    start = time.monotonic()
    node = find_node() if node is True else node
    repos = default_repos() if repos is None else repos
    urgent = list(dict.fromkeys(ln.strip() for ln in text.splitlines() if ln.strip() and URGENT.search(ln)))
    try:
        per_text = extract_refs([text, *urgent], repos=repos, default_repo=default_repo or _home_repo(), node=node,
                                cli=cli, timeout=min(NODE_MAX_S, budget))
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as e:
        reason = str(e) if isinstance(e, RuntimeError) else f"the refs parser couldn't run ({e.__class__.__name__})"
        return Report("unverified", when, reason=reason)
    keys = list(dict.fromkeys(per_text[0]))
    line_refs = {ln: refs for ln, refs in zip(urgent, per_text[1:]) if refs}
    if not keys:
        return Report("no-refs", when, line_refs=line_refs)
    asked, skipped = keys[:MAX_REFS], max(0, len(keys) - MAX_REFS)
    remaining = budget - (time.monotonic() - start)
    if remaining <= 0.2:
        return Report("unverified", when, refs=len(keys), reason=f"out of time ({budget:g} s budget)")
    try:
        nodes = fetch(asked, run=run, timeout=round(remaining, 2), gh=gh)
    except RuntimeError as e:
        return Report("unverified", when, refs=len(keys), reason=str(e), line_refs=line_refs)
    report = Report("verified", when, refs=len(keys), skipped=skipped, line_refs=line_refs)
    for key in asked:
        node_ = nodes.get(key)
        if not node_:
            report.unreadable.append(key)
            continue
        report.checked += 1
        events = changes_since(node_, when.at, key.rsplit("#", 1)[0])
        if events:
            report.changed.append(Changed(key, node_.get("title") or "", events))
    return report


# ── rendering ────────────────────────────────────────────────────────────────

def _dated(w: When, now: datetime | None = None) -> str:
    src = f", {w.machine}" if w.machine else ""
    age = f", {max(0, ((now or datetime.now(UTC)) - w.at).days)}d old"
    return f"from {_day(w.at)}{src}{age}" if w.dated else f"undated: file modified {_day(w.at)}{src}{age}"


def _title(text: str) -> str:
    t = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.startswith("#")), "")
    return sanitize(t)


def render_section(path: Path, report: Report, home: Path = HOME, text: str = "", now: datetime | None = None) -> str:
    where = str(path).replace(str(home), "~", 1)
    w, title = report.when, _title(text)
    lead = f"{title}. " if title else ""
    notes = []
    if w.note:
        notes.append(f"Note: {w.note}")
    if report.unreadable:
        notes.append(f"{len(report.unreadable)} couldn't be read (private or deleted?): {', '.join(report.unreadable[:5])}"
                     + (" …" if len(report.unreadable) > 5 else ""))
    if report.skipped:
        notes.append(f"{report.skipped} more not checked (cap of {MAX_REFS} per check)")
    tail = ("\n\n" + "\n".join(notes)) if notes else ""

    if report.status == "unverified":
        date = _day(w.at) + ("" if w.dated else " (undated)")
        age = max(0, ((now or datetime.now(UTC)) - w.at).days)
        return (f"## Most recent handoff — {path.name} (as of {date}, unverified: {report.reason}; {age}d old)\n\n"
                f"{lead}Its claims couldn't be checked against GitHub, so read `{where}` as history and check live "
                f"state before acting on it.{tail}")
    if report.status == "no-refs":
        return (f"## Most recent handoff — {path.name} ({_dated(w, now)}; no ticket or PR references to check)\n\n"
                f"{lead}Read `{where}` before resuming that work.{tail}")
    if not report.changed:
        return (f"## Most recent handoff — {path.name} ({_dated(w, now)}; {report.checked} reference(s) checked, none "
                f"changed since)\n\n{lead}Read `{where}` before resuming that work.{tail}")
    n, m = len(report.changed), report.checked
    lines = [f"- {c.line()}" for c in report.changed[:MAX_SHOWN]]
    if n > MAX_SHOWN:
        lines.append(f"- …and {n - MAX_SHOWN} more")
    struck = report.struck_lines()
    strike = ("\n\nUrgent steps that name a changed item, struck:\n" + "\n".join(f"- ~~{s[:200]}~~" for s in struck[:5])
              if struck else "")
    return (f"## Handoff {path.name} ({_dated(w, now)}): {n} of {m} changed since, treat as history\n\n"
            f"{lead}Changed on GitHub after this handoff was written:\n" + "\n".join(lines) + strike +
            f"\n\nRead `{where}` as history, not status.{tail}")


def strike_urgent(prompt: str, report: Report) -> str:
    """The resume prompt with each urgent step that names a changed item struck through, and why."""
    changed = {c.key for c in report.changed}
    out = []
    for line in prompt.splitlines():
        hit = sorted(changed & set(report.line_refs.get(line.strip(), [])))
        if hit:
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f"{indent}~~{line.strip()}~~ (changed since: {', '.join(hit)})")
        else:
            out.append(line)
    return "\n".join(out)


def heading_line(report: Report) -> str:
    """One line for the top of a surfaced resume prompt."""
    w = report.when
    if report.status == "unverified":
        return f"As of {_day(w.at)}, unverified ({report.reason})."
    if report.changed:
        return f"Handoff {_dated(w)}: {len(report.changed)} of {report.checked} changed since, treat as history."
    return f"Handoff {_dated(w)}: nothing it names has changed since."


# ── log + stamp ──────────────────────────────────────────────────────────────

def log_run(report: Report, *, handoff: Path, where: str, path: Path = LOG, machine: str | None = None) -> None:
    row = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "where": where, "machine": machine,
           "handoff": handoff.name, "as_of": report.when.at.isoformat(), "dated": report.when.dated,
           "written_on": report.when.machine, "status": report.status, "refs": report.refs,
           "checked": report.checked, "changed": len(report.changed), "unreadable": len(report.unreadable),
           "skipped": report.skipped, "reason": report.reason, "changed_keys": [c.key for c in report.changed]}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass  # the log is for the probe; it never costs the session start


def stamp(path: Path, *, as_of: datetime, machine: str | None, session: str | None, source: str,
          force: bool = False) -> bool:
    """Write `as_of`/`machine`/`session`/`source` front matter. An existing stamp is kept unless force. True if written."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return False
    fm = parse_front_matter(text)
    if fm.get("as_of") and not force:
        return False
    body = text
    if fm or text.startswith("---\n---"):
        body = text[text.find("\n---", 3) + 4:].lstrip("\n")
    head = [f"as_of: {as_of.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}"]
    head += [f"machine: {machine}"] if machine else []
    head += [f"session: {session}"] if session else []
    head += [f"source: {source}"]
    try:
        path.write_text("---\n" + "\n".join(head) + "\n---\n" + body)
    except OSError:
        return False
    return True


def main(argv: list[str]) -> int:
    now = datetime.now(UTC)
    if argv:
        path = Path(argv[0]).expanduser()
        when = handoff_time(path, now)
    else:
        ranked = ranked_handoffs(HOME / ".claude" / "handoffs", now)
        if not ranked:
            print("no handoffs")
            return 0
        path, when = ranked[0]
        when = handoff_time(path, now)
    text = path.read_text(errors="replace")
    print(render_section(path, check(text, when, now=now), text=text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
