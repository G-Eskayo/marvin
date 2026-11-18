## North-star fit

**Reuses before adding anything new:**
- `lib/ticket_agents.py:542-544` `board_repos()` — already the canonical "every repo the board covers" (`[b["repo"] for b in board_registry.list_boards()]`), used by `ticket_pipeline.py:479` and `owner_decisions.py:447`. I call this directly instead of re-deriving the repo list from the project catalog.
- `brain-map/scripts/facts.py:61-69` `_merged_pipeline_prs()`'s subprocess try/except shape — kept as the template for every new subprocess helper (never raise, return `None` on any failure).
- `site/scripts/facts.mjs:24-44` (`npm run facts`, hand-run today) already contains the exact counting recipes the ticket asks for in Python form: `pytest --collect-only -q` + the `/(\d+) tests? collected/` regex, and `npx vitest list` + non-blank-line count. I port these instead of inventing a new counting method.
- `lib/project_catalog.py:342-346` `write_catalog()`'s tmp-file-then-`replace()` pattern — reused for `facts.json`'s write, which from now on is also *read back* (see below), so a half-written file would corrupt the next run too.
- `brain-map/export_snapshot.py:275-289` `write_facts()` needs **no changes at all**: the "keep last good value" logic lives entirely inside `facts.gather()`/`compute_facts()`, so `write_facts`'s existing contract (pure override via `gather=`) is untouched and its two existing tests keep passing unmodified.

**Simplest sufficient approach:** everything stays inside `brain-map/scripts/facts.py` (one file, already the ticket's whole target). No new module, no new service. The "last good value" mechanism is scoped *only* to the two sources the acceptance criteria call out (tests, prs_merged) — the other four facts (skills/agents/decisions/machines) keep their current "omit when unavailable" behaviour untouched, since nothing in the ticket asks to change them and they're cheap local reads that don't benefit from carry-forward.

**Token/compute cost:** this spends more subprocess time per run (one more `pytest --collect-only`, one `npx vitest list`, one `node --test`, N paginated `gh api` calls instead of 1 search call) — a few minutes instead of seconds, run nightly/on-commit, off the interactive path. It saves tokens long-term by ending the recurring "hand recount disagrees with the live tiles" cycle that generated this ticket (and #1153 before it).

**Phone-OS direction:** neutral — this is a correctness fix to an existing auto-publishing surface (ADR 0057), not new reach.

**More capable or more passive:** more capable — it removes a manual reconciliation step (Gil no longer hand-recounts PRs/tests to catch the page lying) without removing any judgment from him; nothing here decides anything *for* him, it just makes the numbers true.

No north star argues against this work.

---

## Design

### 1. PR count (`brain-map/scripts/facts.py`)

Replace `_merged_pipeline_prs()`'s title search with:

```
def _repo_pipeline_prs(repo: str) -> int | None:
    """Closed PRs for one repo, REST, paginated (own rate limit, not the pipeline's GraphQL budget)."""
    total, page = 0, 1
    while page <= 50:  # ~5,000 closed PRs; a real repo stopping short of this is fine, a runaway loop is not
        try:
            p = subprocess.run(["gh", "api", f"repos/{repo}/pulls", "-X", "GET", "-f", "state=closed",
                                "-f", "per_page=100", "-f", f"page={page}",
                                "--jq", "[.[] | {ref: .head.ref, merged: .merged_at}]"],
                               capture_output=True, text=True, timeout=30)
            batch = json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None
        if batch is None:
            return None
        if not batch:
            break
        total += sum(1 for pr in batch if pr.get("merged") and str(pr.get("ref", "")).startswith("pipeline/"))
        if len(batch) < 100:
            break
        page += 1
    return total


def _merged_pipeline_prs(repos: list[str]) -> int | None:
    totals = [_repo_pipeline_prs(r) for r in repos]
    return None if any(t is None for t in totals) else sum(totals)
```

`gather()` calls `_merged_pipeline_prs(ticket_agents.board_repos())`. Any single repo's failure (rate limit, 403, bad auth, corrupt JSON) fails the whole figure — a partial sum would be a *confidently wrong* number, which is worse than a stale-but-labelled one. `board_repos()` itself can raise (`board_registry._load` raises `ValueError` on a corrupt registry); `gather()` wraps that call too, so a broken board registry degrades PR counting only, not the whole `facts.json`.

### 2. Test suite size, in three parts

```
def _py_tests_collected(repo_root: Path) -> int | None:
    env = {**os.environ}; env.pop("MARVIN_SELECTED_TESTS", None)  # always the whole suite, never a PR's subset
    try:
        p = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                           cwd=repo_root, env=env, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(\d+) tests? collected", p.stdout)  # present even when pytest also reports a collection error
    return int(m.group(1)) if m else None

def _js_tests_listed(dashboard_dir: Path) -> int | None:
    try:
        p = subprocess.run(["npx", "vitest", "list"], cwd=dashboard_dir, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return len([l for l in p.stdout.splitlines() if l.strip()]) if p.returncode == 0 else None

def _site_tests_run(site_dir: Path) -> int | None:
    files = sorted(str(f) for f in (site_dir / "scripts").glob("*.test.mjs"))
    if not files:
        return None
    try:
        p = subprocess.run(["node", "--test", "--test-reporter=tap", *files], cwd=site_dir,
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"# tests (\d+)", p.stdout)
    return int(m.group(1)) if m else None
```

- Python: whole-repo `pytest --collect-only -q` (not `lib/tests` only, which is why `facts.mjs`'s own count undercounts against a real hand recount) — this is exactly what the existing repo-root `conftest.py` is built to collect when `MARVIN_SELECTED_TESTS` is unset.
- JS: unchanged recipe from `facts.mjs`, ported.
- Site: `node --test`'s TAP reporter always prints `# tests N` in its summary (total declared, independent of pass/fail/skip), which is the closest thing to a "collect-only" count the built-in runner has — running the site's own two tiny, dependency-free test files is cheap and matches `site/package.json`'s own `"test"` script.

### 3. Carrying the last good value + its own date

Scope: **only** `tests_python`, `tests_js`, `tests_site` (and the `tests` total they sum to) and `prs_merged`, since those are the sources the acceptance criteria name as able to fail. Everything else keeps today's "omit when unavailable" behaviour.

`compute_facts()` gains `previous: dict | None = None` (still pure — the caller hands it a plain dict, built from whatever `gather()` read off disk):

```
def _resolve(key: str, fresh: int | None, previous: dict, today: str) -> tuple[int | None, str | None]:
    """(value, counted_on) for one fact: fresh if available, else the last good one. Never (0, today)."""
    if fresh is not None:
        return fresh, today
    prev_val = previous.get(key)
    if isinstance(prev_val, str):
        prev_val = int(prev_val.replace(",", "")) if prev_val.replace(",", "").isdigit() else None
    return (prev_val, previous.get(f"{key}_counted_on")) if prev_val is not None else (None, None)
```

For each of the four scoped keys, `compute_facts` writes `out[key]` and `out[f"{key}_counted_on"]` using `_resolve`; `out["tests"]` is the sum of whichever of the three parts resolved (fresh or carried), and gets its own `tests_counted_on` only if any part was carried (otherwise it's just `today`, same as the global `counted_on`, so a healthy run adds **no** new visible staleness markers — additive, backward-compatible with whatever already reads the flat `tests`/`prs_merged` keys).

`gather()` reads the previous published file once:

```
SNAPSHOT_FACTS = REPO / "brain-map" / "snapshot" / "facts.json"

def _previous() -> dict:
    try:
        data = json.loads(SNAPSHOT_FACTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
```

This is the same file `export_snapshot.write_facts()` is about to overwrite — `gather()` runs and returns *before* that write happens, so there's no read/write race within one export. `write_facts` itself needs **no code change**.

Write it atomically (tmp + `os.replace`, same pattern as `project_catalog.write_catalog`) inside `export_snapshot.write_facts`, since this file is now also a read dependency for the next run — a half-written `facts.json` would poison every future "previous" read, not just this page load.

---

## Decisions

None. Every open point above (repo list source, partial-failure policy for PR pagination, how to count the site's tests without a true collect-only mode, Python collection scope, the exact additive JSON shape) is resolvable from the codebase and the ticket text itself, is reversible (a generated file), and doesn't touch anything only Gil has visibility into. No `## Decisions` block is needed.

---

## Tests to write first (`brain-map/scripts/test_facts.py`)

From "How we'll try to break it":
1. `_repo_pipeline_prs` / `_merged_pipeline_prs`: `gh` returning non-zero, timing out, or returning truncated/malformed JSON on **one** of several repos → whole PR count is `None` (never a confidently-wrong partial sum).
2. A pipeline PR with a hand-edited title but `head.ref` starting `pipeline/` and `merged_at` set → counted. A closed-not-merged `pipeline/*` PR → not counted. A non-pipeline PR titled `"Implement ..."` → not counted. (Pure assertions against `compute_facts`/a fake `batch`, no real `gh`.)
3. Pagination: a repo with exactly 100, 101, and 250 closed PRs (fake paginator returning full/partial pages) → every PR counted, loop terminates on the short page, never double-counts.
4. `_py_tests_collected`: pytest stdout containing `"1,234 tests collected, 3 errors in 9.1s"` → returns 1234 (error present, count not deflated/inflated). Stdout with no match (crash before collection) → `None`.
5. `_js_tests_listed`: `npx` raising `FileNotFoundError` (no JS deps / no `npx` on PATH) → `None`, not `0`.
6. `_site_tests_run`: TAP output containing `# tests 7` → 7, regardless of pass/fail lines mixed in.
7. `_resolve`/`compute_facts`: fresh value present → used, dated `today`. Fresh `None` + a previous value → previous value and *its* stored date are carried, never `0`. Fresh `None` and **no** previous (first run ever) → key omitted entirely (matches the existing/unchanged behaviour for first-run sources).
8. `tests` total = sum of whichever of python/js/site resolved (mix of fresh and carried) stays correct arithmetic; `tests_counted_on` only appears when at least one part was carried.

Misuse the ticket's list didn't name, added per the "tests try to break it" checklist:
9. **Empty, not failed:** a board repo with zero closed PRs ever → contributes `0` for that repo (a real, valid zero), not treated as a failure — must not be conflated with "GitHub refused."
10. **Malformed previous file:** `brain-map/snapshot/facts.json` missing, empty, truncated JSON, or a JSON array instead of an object → `_previous()` returns `{}`, `gather()` proceeds as a cold start, never raises.
11. **Each dependency failing independently:** `board_registry` registry corrupt (`ValueError` from `_load`) must only blank out `prs_merged`/its carry, not crash `skills`/`adrs`/`machines`/`agents`. Same for `pytest`/`node`/`npx` missing: each independently degrades only its own fact.
12. **Repeats/concurrency:** calling `gather()` twice in a row with an unchanged environment is idempotent (same output both times); the atomic tmp+rename write never leaves a partially-written `facts.json` on disk for a concurrent reader to trip over (simulate a write interrupted between tmp-write and replace).
13. **Stale carried-forward state doesn't self-heal silently:** previous value/date already 30 days old and this run also fails → the *same* old value and *same* old date are re-emitted (not refreshed to today), so the page never lies about freshness.
14. **A person's mistake:** `facts.json` hand-edited with a non-numeric string in a carried field (e.g. `"tests_python": "n/a"`) → `_resolve` treats it as unavailable (not a crash, not a wrong number).

---

## Task List

1. Add `_repo_pipeline_prs(repo)` (REST, paginated, `head.ref`/`merged_at`) and rewrite `_merged_pipeline_prs(repos)` to sum per-repo results, `None` on any repo failure.
2. Wire `gather()` to call `_merged_pipeline_prs(ticket_agents.board_repos())`, with the `board_repos()` call itself wrapped so a corrupt board registry only blanks the PR figure.
3. Add `_py_tests_collected`, `_js_tests_listed`, `_site_tests_run` helpers (whole-repo `pytest --collect-only -q`, `npx vitest list` in `dashboard/`, `node --test --test-reporter=tap` over `site/scripts/*.test.mjs`).
4. Add `_previous()` (read `brain-map/snapshot/facts.json`, tolerate anything unreadable) and `_resolve(key, fresh, previous, today)`.
5. Extend `compute_facts()` with `previous: dict | None = None`; emit `tests`, `tests_python`, `tests_js`, `tests_site`, `prs_merged`, and their `_counted_on` siblings per `_resolve`; leave `skills`/`agents`/`decisions`/`machines` behaviour untouched.
6. Update `gather()` to pass the three test-part results, the new PR total, and `_previous()`'s output into `compute_facts`.
7. Make `facts.json`'s write atomic (tmp file + `os.replace`) in `export_snapshot.write_facts`, reusing `project_catalog.write_catalog`'s pattern — no other change to `export_snapshot.py`.
8. Update the module docstring to describe each number's new source (REST pagination across board repos; three-part collected test count; last-good-value-and-date fallback).
9. Write the tests listed above in `brain-map/scripts/test_facts.py` first; run them red, then implement 1–7 to green.
10. On the day of shipping: hand-count merged `pipeline/*` PRs across the current board repos and run the three collect commands on `main` by hand; put both the hand count and the computed count in the PR description (acceptance criterion #1).