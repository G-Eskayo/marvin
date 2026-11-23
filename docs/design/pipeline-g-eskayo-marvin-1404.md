## North-star fit

**Reuses:** `docs/agents/decisions-format.md`'s rule ("don't answer the questions yourself, and don't pre-tick a box unless it records an answer he already gave") plus the earlier-answer matching this ticket's own scan already ran (`lib/supersession.py`, marvin#1226) — I re-verified its five hits by reading each file rather than trusting the grep. Also reuses the "pair a ticket number with its title" convention (`feedback-avoid-bare-numeric-ids`) for the reply text. No new abstraction, file, or pattern is added.

**Why simplest-sufficient:** I read PR #1401's actual diff (`dashboard/mobile-backend/session_runner.js`, lines ~361–379, ~1147–1182) and confirmed the deep brain's tool set is already `Read,Grep,Glob,WebSearch,WebFetch` with no warm-session/lean-config code anywhere in the diff. That means:
- **deep-latency** — owner ticked "Keep it." That's exactly what's already built (commit `9b94ec7d`). Nothing to carry out.
- **deep-tools** — owner ticked **nothing** (`"choices": []`). He attached a *note*, not an answer: "I want it to be interactive like a lab assistant... report on anything... in human understandable form... but we are still working on that." Per the decisions format, a Note is explicitly allowed alongside an unanswered question — it is not a hidden fourth checkbox, and the owner's own words ("still working on that") say this isn't settled. The ticket's own break-it case — *"The notes contradict a chosen option: say so in the reply instead of guessing"* — plus the generic misuse case *"a person's mistakes / ambiguous input shouldn't be silently resolved by guessing"* both point the same way: don't invent an implementation for an unanswered question. I believe this guess-and-build is exactly what the prior attempt did and why code review called it must-fix (issue #1404's first comment: 3 failed iterations, "code review found must-fix issues," with no PR or branch commit surviving to show what was tried).

So the correct, minimal action is almost entirely a **reply, not a diff**: confirm the one already-built choice, truthfully report the other as unchosen, resolve the five "earlier answer" citations (all are ticket-number *mentions*, none restate either question — confirmed by reading each file, matching `lib/supersession.py`'s own "by relation, no id hit" classification), and surface the owner's open direction as a tracking ticket rather than guessed code.

**Resource cost:** near zero — no new files, no new tests, one GitHub comment and one small tracking issue. Spends nothing it doesn't have to.

**More capable, not more passive:** leaves the one real design call ("what does 'report on anything, human-understandably' mean, concretely") with Gil, who said himself it isn't resolved — building something now would be MARVIN deciding for him on a question he's still working out, which north star 3 argues against.

## Decisions

None required from the owner for *this* ticket — the one place a choice could be invented (what "report on anything, human-understandable" should look like) is explicitly not mine to guess, per above, so I'm not fabricating options for it. Filing a lightweight tracking issue to hold the note is housekeeping, not a design choice, so I'm making that call myself rather than blocking on a button (noted below).

## Tests (verification checks, since this ticket produces no new code path)

1. **Reply contradicts/guesses a chosen option** — assert the reply never claims deep-tools was built, and the deep-latency claim ("already built, matches 'Keep it'") is checked against the actual diff lines (`session_runner.js` `READ_ONLY_TOOLS`/`allowedTools`, no warm-session code) before posting, not assumed from the PR description text.
2. **PR changed since the decisions comment was posted** — re-fetch `gh pr view 1401` and `gh pr view 1401 --comments` immediately before posting, to confirm no newer commit or comment supersedes what I read.
3. **Reply rejected by the decisions-structure gate** — draft must contain no `## Decisions` / `## Open questions` / `## Choose` heading (I'm reporting, not asking), so `bin/gh pr comment` doesn't hit `DECISIONS_NOT_ASKABLE`/`DECISIONS_UNPARSED`.
4. **Owner-decisions gate still blocks merge after the reply** — both questions are marked `(optional)` in the PR description, and a reply carrying `<!-- marvin:decisions-addressed -->` counts as "built" for the unresolved-but-optional one; confirm this reading against `docs/agents/decisions-format.md`'s "Merge-time and merged-PR re-checks" section before relying on it.
5. **Bare numeric IDs in the reply** — every ticket number cited (#670, #1399, the new tracking ticket) is paired with its title.
6. **"No id hit" ≠ "safe to skip"** — don't trust `lib/supersession.py`'s classification alone; I already read all five files' actual text around the `#670` mention and confirmed none restate either `deep-tools` or `deep-latency`'s question/answer.
7. **Posting through the wrong path** — comment goes through `~/.agents/bin/gh`, never raw `gh` (`reference-github-gate`).
8. **New tracking issue scope-creeps into a design decision** — the issue body only quotes the owner's note verbatim and links PR #1401/ADR 0075; it proposes no implementation and asks no question, so it can't itself trip the decisions gate.

## Task List

1. Draft the PR #1401 reply (plain comment, no Decisions heading): states (a) `deep-latency` — "Keep it" is already built in `9b94ec7d`/`session_runner.js`, no new commit; (b) `deep-tools` — no option was chosen, nothing was guessed or built, the question stays open in the PR description for whenever you're ready; your note is the start of a separate, bigger question (what "report on anything, human-understandable" means) that I'm not inventing an answer to; (c) the five earlier-answer citations, each marked kept with the one-line reason "mentions ticket #670, doesn't restate either decision's question or answer"; (d) screenshots: none retaken — this PR has no UI surface (backend API + tests only); (e) the `<!-- marvin:decisions-addressed -->` marker.
2. File a small tracking issue (label `needs-info`, `project:marvin`) quoting the owner's `deep-tools` note verbatim, linking PR #1401 and ADR 0075, asking nothing and proposing nothing — just so the direction isn't lost once this ticket closes.
3. Re-fetch PR #1401's current state right before posting (test 2), to catch any change since this plan was written.
4. Post the reply comment via `~/.agents/bin/gh`, then verify it rendered as "addressed" (no gate rejection) and that the tracking issue link resolves.
5. Confirm issue #1404 auto-closes once the reply lands (it closes itself per its own filing rule); if it doesn't close within a reasonable window, say so rather than force-close it.