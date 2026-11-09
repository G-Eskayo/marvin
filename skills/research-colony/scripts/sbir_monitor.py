#!/usr/bin/env python3
"""SBIR/STTR topic monitor (#1165, PRD #1164): DoD's open and pre-release topics, scored against a capability profile.

DSIP (dodsbirsttr.mil) carries every DoD SBIR/STTR topic, AFWERX's and the Army's included. Its public API needs no
login (checked 2026-11-09): a paged search of the topics in pre-release or open, and one details call per topic for
its objective, description, keywords, ITAR flag and CMMC level. Each run:

1. pages through the search (status 591 + 592 = Pre-Release + Open); a failure leaves the saved state untouched;
2. fetches details only for topics it hasn't seen (cached per topic, so a quiet week costs one search);
3. scores each against the owner's profile: whole-word terms with weights, a title hit counting double, each term
   counted once per field so repetition can't inflate it, and any `exclude` word vetoing the topic;
4. tells the owner once per run, through the one alert path, about matches it hasn't told before and about matched
   topics that have moved from pre-release to open (when talking to the topic's author stops being allowed).

Deterministic: no model call. The maximum period of performance (AFWERX's top disqualifier) isn't in the topic record:
it's in each component's BAA instructions, which slice 4's linter (#1168) reads.

The profile is the owner's, so it lives in the private instance (ADR 0071): instance/config/sbir/profile.json,
{"name", "threshold", "terms": {"phrase": weight}, "require_any": [core phrases], "exclude": [...]}: a match needs the
threshold AND, when require_any is set, at least one core capability term (supporting words alone never match). State and raw responses are per machine under
~/.agents/var/sbir/; install the job on one always-on machine only, or each Mac tells you separately.

When: DoD publishes on Wednesdays (pre-release on the first Wednesday of the month), so the job runs on a weekly
Wednesday calendar slot (config/jobs/sbir-monitor.json). DSIP has no feed or webhook to trigger on; the publisher's own
schedule is the trigger, never an interval check.

    sbir_monitor.py run [--profile PATH]     fetch, score, tell; prints a JSON summary
    sbir_monitor.py show                     the current matches, best first, as a table
Part of the research-desk pack (an add-on, not the default run).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

LIB = Path(__file__).resolve().parents[3] / "lib"
sys.path.insert(0, str(LIB))

BASE = "https://www.dodsbirsttr.mil"
TOPICS_PAGE = f"{BASE}/topics-app/"
OPEN_STATUSES = [591, 592]   # Pre-Release and Open (verified against the live API, 2026-11-09: 82 + 18 topics)
PAGE_SIZE = 100
MAX_PAGES = 50               # 5,000 topics: far above any release, so a runaway paging loop stops
TIMEOUT_S = 30
USER_AGENT = "MARVIN-sbir-monitor"
STATE_DIR = Path.home() / ".agents" / "var" / "sbir"
FIELDS = ("title", "objective", "description", "keywords", "phase1", "phase2", "phase3")


class SourceError(Exception):
    """DSIP couldn't be reached or answered something unexpected."""


class ProfileError(Exception):
    """The capability profile is missing or malformed."""


# ── fetching ───────────────────────────────────────────────────────────────────────────────────────────────────

def http_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read())
    except (OSError, ValueError) as exc:
        raise SourceError(f"{url}: {exc}") from None


def search_url(page: int) -> str:
    param = json.dumps({"searchText": None, "topicReleaseStatus": OPEN_STATUSES}, separators=(",", ":"))
    return f"{BASE}/topics/api/public/topics/search?searchParam={urllib.parse.quote(param)}&size={PAGE_SIZE}&page={page}"


def details_url(topic_id: str) -> str:
    return f"{BASE}/topics/api/public/topics/{urllib.parse.quote(topic_id, safe='')}/details"


def fetch_topics(get_json: Callable[[str], object]) -> list[dict]:
    """Every pre-release and open topic, across pages. Raises SourceError on any bad page."""
    out: list[dict] = []
    for page in range(MAX_PAGES):
        body = get_json(search_url(page))
        if not isinstance(body, dict) or not isinstance(body.get("data"), list) or not isinstance(body.get("total"), int):
            raise SourceError(f"DSIP search page {page} wasn't the expected shape")
        out += [t for t in body["data"] if isinstance(t, dict) and t.get("topicId")]
        if not body["data"] or len(out) >= body["total"]:
            return out
    raise SourceError(f"DSIP search kept paging past {MAX_PAGES} pages")


# ── a topic record ─────────────────────────────────────────────────────────────────────────────────────────────

def _day(ms: object) -> str | None:
    if isinstance(ms, bool) or not isinstance(ms, (int, float)) or ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat()


def _plain(text: object) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split()) if isinstance(text, str) else ""


def normalise(t: dict, d: dict) -> dict:
    """One topic, from its search record and its details, in the shape the rest of the desk reads."""
    return {
        "id": t["topicId"], "code": t.get("topicCode") or t["topicId"], "title": _plain(t.get("topicTitle")),
        "program": t.get("program"), "component": t.get("component"), "status": t.get("topicStatus"),
        "solicitation": t.get("solicitationTitle"), "cycle": t.get("cycleName"),
        "cmmc": d.get("cmmcLevel") or t.get("cmmcLevel") or None, "itar": bool(d.get("itar")),
        "dates": {"pre_release": _day(t.get("topicPreReleaseStartDate")), "opens": _day(t.get("topicStartDate")),
                  "qa_ends": _day(t.get("topicQAEndDate")), "closes": _day(t.get("topicEndDate"))},
        "text": {"objective": _plain(d.get("objective")), "description": _plain(d.get("description")),
                 "keywords": _plain(d.get("keywords")), "phase1": _plain(d.get("phase1Description")),
                 "phase2": _plain(d.get("phase2Description")), "phase3": _plain(d.get("phase3Description"))},
    }


# ── the profile and scoring ────────────────────────────────────────────────────────────────────────────────────

def load_profile(path: Path) -> dict:
    try:
        prof = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ProfileError(f"no readable capability profile at {path}: {exc}") from None
    return load_profile_dict(prof, where=str(path))


def load_profile_dict(prof: object, where: str = "profile") -> dict:
    path = where
    terms = prof.get("terms") if isinstance(prof, dict) else None
    if not isinstance(terms, dict) or not terms or not all(
            isinstance(k, str) and k.strip() and isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
            for k, v in terms.items()):
        raise ProfileError(f"{path}: 'terms' must map phrases to positive weights")
    thr = prof.get("threshold", 6)
    if isinstance(thr, bool) or not isinstance(thr, (int, float)) or thr <= 0:
        raise ProfileError(f"{path}: 'threshold' must be a positive number")
    excl = prof.get("exclude", [])
    if not isinstance(excl, list) or not all(isinstance(w, str) and w.strip() for w in excl):
        raise ProfileError(f"{path}: 'exclude' must be a list of words")
    core = prof.get("require_any", [])
    known = {k.lower() for k in terms}
    if not isinstance(core, list) or not all(isinstance(w, str) and w.lower() in known for w in core):
        raise ProfileError(f"{path}: 'require_any' must list phrases that 'terms' scores")
    return {"name": prof.get("name") or "profile", "threshold": thr, "terms": terms, "exclude": excl,
            "require_any": [w.lower() for w in core]}


def is_match(s: float, reasons: list[str], profile: dict) -> bool:
    """At or over the threshold, and (when the profile names core terms) at least one core term hit.

    Live run 2026-11-09: without the core rule, generic words (edge, offline, acoustic, noise) made 9 of 110 topics
    "match", none of them about speech, captions or translation."""
    core = profile.get("require_any") or []
    return s >= profile["threshold"] and (not core or any(r in core for r in reasons))


def _pattern(phrase: str) -> re.Pattern:
    # Whole words, case-insensitive, plural allowed ("translations"), never inside another word ("captionless").
    words = r"[\s-]+".join(re.escape(w) for w in re.split(r"[\s-]+", phrase.strip().lower()))
    return re.compile(rf"(?<![\w-]){words}(?:s|es)?(?![\w])", re.I)


def score(rec: dict, profile: dict) -> tuple[float, list[str]]:
    fields = {"title": rec["title"], **rec["text"]}
    every = " ".join(fields.values())
    for word in profile.get("exclude", []):
        if _pattern(word).search(every):
            return 0, [f"excluded: {word}"]
    total, hit = 0.0, set()
    for phrase, weight in profile["terms"].items():
        pat = _pattern(phrase)
        for name in FIELDS:
            if pat.search(fields.get(name, "")):
                total += weight * (2 if name == "title" else 1)
                hit.add(phrase.lower())
    return total, sorted(hit)


# ── state ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _state_path() -> Path:
    return STATE_DIR / "topics.json"


def load_state() -> dict:
    try:
        data = json.loads(_state_path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, path)   # atomic: a crash mid-write never leaves half a state file


def tell(title: str, message: str, target: str | None = None) -> None:
    import notify   # the one alert path (ADR 0083)
    notify.notify(title, message, target)


# ── a run ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _line(rec: dict, s: float) -> str:
    closes = rec["dates"]["closes"] or "date unknown"
    return f"{rec['code']} {rec['title'][:70]} ({rec['component']}, closes {closes}, score {s:g})"


def run(profile_path: Path, get_json: Callable[[str], object] = http_json, today: str | None = None) -> dict:
    profile = load_profile(profile_path)   # refused before anything is fetched
    today = today or date.today().isoformat()
    result = {"fetched": 0, "new_matches": [], "now_open": [], "skipped": [], "error": None}
    try:
        raw = fetch_topics(get_json)
    except SourceError as exc:
        result["error"] = str(exc)
        tell("SBIR monitor couldn't reach DSIP", f"{exc}. Nothing changed; the next Wednesday run tries again.")
        return result
    state = load_state()
    result["fetched"] = len(raw)
    details_seen: dict[str, dict] = {}
    listed = set()
    for t in raw:
        tid = t["topicId"]
        listed.add(tid)
        prev = state.get(tid, {})
        d = prev.get("details")
        if d is None:
            try:
                d = get_json(details_url(tid))
                if not isinstance(d, dict):
                    raise SourceError("details weren't an object")
            except SourceError:
                result["skipped"].append(t.get("topicCode") or tid)   # not stored: the next run retries it
                continue
        details_seen[tid] = d
        rec = normalise(t, d)
        s, reasons = score(rec, profile)
        matched = is_match(s, reasons, profile)
        entry = {"record": rec, "details": d, "score": s, "reasons": reasons, "matched": matched, "listed": True,
                 "told": prev.get("told", False), "told_open": prev.get("told_open", False),
                 "first_seen": prev.get("first_seen", today), "last_seen": today}
        if matched and not entry["told"]:
            result["new_matches"].append(rec["code"])
            entry["told"] = True
            entry["told_open"] = rec["status"] == "Open"
        elif matched and entry["told"] and not entry["told_open"] and rec["status"] == "Open":
            result["now_open"].append(rec["code"])
            entry["told_open"] = True
        state[tid] = entry
    for tid, entry in state.items():
        if tid not in listed:
            entry["listed"] = False
    _write_json(_state_path(), state)
    _write_json(STATE_DIR / "raw" / f"{today}.json", {"topics": raw, "details": details_seen})
    by_code = {e["record"]["code"]: e for e in state.values()}
    parts, lines = [], []
    if result["new_matches"]:
        n = len(result["new_matches"])
        parts.append(f"{n} new matching topic{'s' if n != 1 else ''}")
        lines += [_line(by_code[c]["record"], by_code[c]["score"]) for c in result["new_matches"]]
    if result["now_open"]:
        n = len(result["now_open"])
        parts.append(f"{n} matched topic{'s' if n != 1 else ''} now open")
        lines += ["Now open: " + _line(by_code[c]["record"], by_code[c]["score"]) for c in result["now_open"]]
    if parts:
        tell(f"SBIR ({profile['name']}): " + ", ".join(parts),
             "\n".join(lines) + f"\nDetails: sbir_monitor.py show · {TOPICS_PAGE}", TOPICS_PAGE)
    return result


def show() -> str:
    rows = sorted((e for e in load_state().values() if e.get("matched") and e.get("listed")),
                  key=lambda e: -e["score"])
    if not rows:
        return "no matching topics are open or in pre-release"
    out = ["| score | topic | title | who | status | opens | Q&A ends | closes | CMMC | ITAR | why |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in rows:
        r, d = e["record"], e["record"]["dates"]
        out.append(f"| {e['score']:g} | {r['code']} | {r['title'][:60]} | {r['component']} {r['program']} | "
                   f"{r['status']} | {d['opens'] or '?'} | {d['qa_ends'] or '?'} | {d['closes'] or '?'} | "
                   f"{r['cmmc'] or '?'} | {'yes' if r['itar'] else 'no'} | {', '.join(e['reasons'])} |")
    return "\n".join(out)


def default_profile() -> Path:
    import instance
    return instance.path("config", "sbir", "profile.json")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="fetch DSIP, score against the profile, tell the owner about new matches")
    r.add_argument("--profile", type=Path, default=None)
    sub.add_parser("show", help="the current matches, best first")
    a = ap.parse_args(argv)
    if a.cmd == "show":
        print(show())
        return 0
    try:
        out = run(a.profile or default_profile())
    except ProfileError as exc:
        print(f"sbir_monitor: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out))
    return 1 if out["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
