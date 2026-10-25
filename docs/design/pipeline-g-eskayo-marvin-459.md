## North-star fit

**Reuses, unchanged:** `morning_brief.py`'s two-tier tuple loop in `_digest_idea`/`_research_idea` (`lib/morning_brief.py:135-150`, iterating `(f"{day}-merged.md", f"{day}.md")`) already implements AC2's "merged preferred, then fall back" — correctly, per ADR 0067's two-tier collapse (Mini builds `{day}.md` first; MacBook's `{day}.md` is the only fallback; there is no third machine-named file). No change needed there. `verify.py`'s `quarantine_placeholder_text`/`is_quarantine_placeholder` (`skills/safety-monitor/scripts/verify.py:94-107`) and both digest writers' use of them (`skills/improve/scripts/daily_digest.py:280-284`, `skills/research-colony/scripts/research_digest.py:142-147`) are already implemented, tested, and correct — AC3's "never shown as ready" is already true for the digest-writing side. `session_start_report.py`'s own repo-relative `sys.path` insert for `verify.py` (`lib/session_start_report.py:39`, via `Path(__file__).resolve().parents[1]`) is already correct — the worktree/production path-collision the earlier design doc described does **not** exist in the code currently sitting in this worktree; that part of the prior write-up was stale.

**What's actually still broken (verified by reading the real current files, not re-describing the old design):**
1. `lib/morning_brief.py:116-117` — `_BOLD_LINE_RE` still hard-requires `[:—]` directly after the closing `**`; `_LEADING_NOISE_RE` is defined but never called from `_first_paragraph` (`lib/morning_brief.py:120-132`). Checked against five real files (`2026-10-03.md`, `2026-10-03-merged.md`, `2026-10-07-merged.md`, `2026-07-03.md`, `2026-10-16.md`, read directly, not from memory): the merged writer produces ` (confirmed on both). ` (plain parenthetical + period) and ` *(confirmed on both)*: ` (italicised parenthetical + colon) — neither matches `[:—]` directly after `**`, so merged content is silently skipped in exactly the cases AC2 cares about most.
2. `lib/session_start_report.py:44` — `_load_quarantine_detector` catches only `ImportError`. Its own module-level call (`line 48: _QUARANTINE_DETECT_AVAILABLE = _load_quarantine_detector()`) runs outside `_safe()`, so any other import-time failure in `verify.py` (a `SyntaxError`, a `RuntimeError` from `calibrate.py` or `marvin_launcher.py`, which `verify.py` itself imports at module scope) takes down the whole SessionStart hook — the opposite of this file's own stated contract ("every check degrades independently... the whole thing never raises").
3. `lib/tests/test_morning_brief.py:161-165` — asserts `result is None or isinstance(result, str)`, which is true of any possible return value and can't fail.

**Fix, not redesign:** two one-step, line-local changes plus the matching tests — no new files, no new modules, no restructuring of working code.

**Tokens:** zero model calls anywhere in this fix (pure string parsing + an `except` clause). It makes research the colony already paid tokens to produce actually reach the brief, instead of being silently dropped by a regex narrower than what the model actually writes — the Watts check this ticket itself names. 

**Capability:** the user gets a real research line in the brief on days the merged digest is the only good content (most days, since merged is preferred) instead of silence, and the SessionStart hook can't be taken down by an unrelated import-time exception three files deep — more capable, more reliable, never more passive.

## Fix detail

**`lib/morning_brief.py`** — replace lines 116-132:

```python
_BOLD_LINE_RE = re.compile(r"^[ \t\-*0-9.]*\*\*(.+?)\*\*(.*)$", re.M)
_LEADING_NOISE_RE = re.compile(r"^(?:\s*\*?\([^)]*\)\*?|\s*[:\-\u2013\u2014.])+")


def _first_paragraph(path: Path, heading: str | None) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(errors="ignore")
    if heading:
        m = re.search(rf"^## {re.escape(heading)}\s*$\n+(.+?)(?:\n\n|\n##|\Z)", text, re.M | re.S)
        return m.group(1).strip() if m else None
    m = _BOLD_LINE_RE.search(text)
    if not m:
        return None
    title = m.group(1).strip()
    rest = _LEADING_NOISE_RE.sub("", m.group(2)).strip()
    content = rest.split(". ")[0].strip().rstrip(".")
    return f"{title}: {content}." if content else None
```

Prefix class stays `[ \t\-*0-9.]` (space/tab/hyphen/asterisk/digit/period, no generic `\s`) deliberately — a generic `\s*` prefix could slurp across a blank line and bleed one bullet's bold marker into a position before the next one; this keeps the match line-local, same reasoning as the no-`re.S` content group. `_LEADING_NOISE_RE` now strips, from the front of whatever follows the closing `**`, zero or more of: a parenthetical annotation (optionally wrapped in `*...*`), or a single separator character (`:`, `-`, `—`, `–`, `.`) — covering all four real separator shapes found in the fixtures plus the three already-tested synthetic ones (plain colon, em dash, no separator). Hand-verified against all five real files; traced through all 14 existing passing tests in `test_morning_brief.py` (lines 99-211) line-by-line — none regress.

**`lib/session_start_report.py`** — line 44, one-word change:

```python
    except ImportError:
```
→
```python
    except Exception:
```

That's the entire fix for finding #2 — `_load_quarantine_detector` already swallows everything it needs to once the except-class is widened, so nothing escapes past it to module scope regardless of `_safe()`. No further restructuring.

## Tests (written first)

`lib/tests/test_morning_brief.py` — real fixture excerpts copied verbatim as string literals (never read live), plus the fixed corrupt-file assertion:

1. Real `2026-10-03.md` excerpt (`- **Title**: blurb. [link]`) → `_research_idea` yields a real sentence — AC1.
2. Real `2026-10-03-merged.md` excerpt (`**KaliBench...** (confirmed on both). Its fine-grained scoring...`) → annotation stripped, real sentence surfaces, not `"KaliBench...: (confirmed on both)."` — this is the exact case the previous attempt's regex missed.
3. Real `2026-10-07-merged.md` excerpt (`**EmbeddingGemma 2: An open...** *(confirmed on both)*: A possible replacement...`) → title with its own internal colon extracted whole; italicised-parenthetical-then-colon form stripped correctly.
4. Real `2026-07-03.md` excerpt (bare `**Title** — blurb.`, no bullet, blank-line-paragraph style) → extracted correctly (regression guard for the already-passing em-dash case against a *real*, not synthetic, line).
5. Real `2026-10-03-merged.md` + real `2026-10-03.md` pair, both copied into the same `tmp_path`, same day → merged wins, its (different) content appears, not the own-digest content — AC2, "both present and different," with real data instead of synthetic.
6. Real `2026-10-16.md` (verbatim quarantine-placeholder content, no `**` anywhere in it) used as `{day}.md` with no merged file present → `_research_idea` returns `None`, not the placeholder sentence — AC4, with the real placeholder text instead of a hand-written stand-in.
7. Yesterday's real `2026-10-03.md` content written under *yesterday's* filename only, nothing under today's → `_research_idea(now=today)` returns `None`, never yesterday's content — regression guard for "digest dated yesterday must not be used as today's."
8. Empty file (`""`) as `{day}.md` → `None`, no exception.
9. Truncated line: bold title with no closing `**` (`"**Title: no closing marker here"`) → `None`, not a garbled partial match.
10. Fixed assertion for the existing corrupt-file test (`lib/tests/test_morning_brief.py:161-165`): keep the non-UTF-8-bytes input (`b"\xff\xfe**Title**: text."`), but assert the *exact* extracted string (`"Title: text."`) instead of `result is None or isinstance(result, str)` — proves the bold line still survives `errors="ignore"` dropping the bad bytes, which is what the finding said this test never actually checked.
11. Calling `_research_idea` twice against the same unchanged real-fixture files → identical result both times (idempotent reads; no shared mutable state, so this also stands in for "repeats/concurrency" — two readers of the same file concurrently are safe for the same reason).
12. Title with nothing usable after it on the line (`"**Title**: ."`) → `None`, not `"Title: ."` (regression guard specific to the two-step parse introducing this case).

`lib/tests/test_session_start_digest.py` — new tests for the broadened except:

13. Monkeypatch `builtins.__import__` to raise `ImportError` only when importing `"verify"` → `ssr._load_quarantine_detector()` returns `False`, doesn't raise (existing behavior, now exercised directly rather than only via the module-level side effect).
14. Monkeypatch `builtins.__import__` to raise an arbitrary `RuntimeError` only when importing `"verify"` → `ssr._load_quarantine_detector()` returns `False`, doesn't raise — this is the test that would have caught finding #2; today, without the fix, this raises straight through and crashes the test (and in production, the SessionStart hook).
15. `ssr._is_quarantine_placeholder is not None` as a hard assertion in at least one existing test (currently implicit/untested) — proves the detector actually loaded in this test environment rather than silently falling back to "ready" for every digest.

No changes needed to `skills/safety-monitor/scripts/verify.py`, `skills/safety-monitor/scripts/tests/test_verify.py`, `skills/improve/scripts/daily_digest.py`, or `skills/research-colony/scripts/research_digest.py` — all four are already correct and already tested for this ticket's scope; re-touching them would be scope creep against north star 1.

No Decisions section: nothing here requires the owner to choose between options. The three-tier-vs-two-tier question was already settled against ADR 0067 in the prior pass and holds; the regex fix is fully determined by the real fixture formats, not a judgment call.

## Task List

1. `lib/morning_brief.py`: replace `_BOLD_LINE_RE`/`_LEADING_NOISE_RE` and the no-heading branch of `_first_paragraph` (lines 116-132) with the two-step parse above.
2. `lib/session_start_report.py`: widen `_load_quarantine_detector`'s `except ImportError:` (line 44) to `except Exception:`.
3. `lib/tests/test_morning_brief.py`: add tests 1-9, 11-12 (real fixture excerpts as literals); rewrite the corrupt-file test (test 10) to assert the exact extracted string.
4. `lib/tests/test_session_start_digest.py`: add tests 13-15.
5. Run `lib/tests/test_morning_brief.py`, `lib/tests/test_session_start_digest.py`, and `skills/safety-monitor/scripts/tests/test_verify.py` together; confirm all 14 pre-existing `test_morning_brief.py` tests still pass unchanged alongside the new ones, and that `ssr._QUARANTINE_DETECT_AVAILABLE` is `True` in the test environment (proves the detector loads, not just that the except-clause is wider).