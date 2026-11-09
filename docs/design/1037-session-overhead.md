# Cutting MARVIN's per-session overhead (#1037): what the cost really is, and the levers left

Status: design, measured 2026-11-04 on the MacBook (Claude Code 2.1.318, `claude-opus-5-5`). Part a (the
session-start report) is built in its own PR. Gil answered the decisions on 2026-11-04; §5 records them and what
was built.

## 1. Where a session's tokens actually go

Read straight from the request Claude Code records in each transcript (`api-request` / `api-request-blob` lines),
for a MARVIN session started in a fresh folder:

| Request part | Size | Cache behaviour across sessions |
|---|---|---|
| System prompt + tool definitions | ~23.7k tokens | read from cache (MARVIN's `autoMemoryDirectory` keeps the system prompt identical) |
| `messages[0]`: CLAUDE.md + MEMORY.md index (23.1k chars), user context, attribution, **the prompt** | ~6k tokens | read from cache when the prompt is the same; trimming CLAUDE.md lowered *reads*, not writes |
| `messages[1]`: SessionStart hook output (2.1k chars), Environment with the working folder (0.7k), deferred tools (2.7k), agent types (2.2k), MCP instructions (1.9k), **skill listing (23.7k)** | ~13.3k tokens | **rewritten every session**: it starts with the hook output and the working folder, and both change |

The cache breakpoint sits at the end of `messages[1]`. Claude Code's own docs say the same: the project-context layer
is rebuilt when a session starts ("Changes when: session starts").

### Consequences for the ticket's plan

- **Part a as written (a byte-stable report, with the changing bits moved to the end) can't create cache hits.**
  The report shares a cached block with the working folder (a fresh temp folder per bench run) and comes after the
  user's prompt. In real use the prompt changes every session; in the bench the folder does. Measured: the new report
  saved 83 tokens of cache writes per session (13,391 to 13,308).
- **The real defect in the report was size.** At 12.8-15.4 KB it went over Claude Code's 10,000-character hook cap.
  Claude Code then saved it to a file and passed on only the path and a 2,000-character preview. Every session saw
  the banner, the checklist and a sliver of the lexicon, and never the handoff. The part-a PR fixes this
  (1.6 KB live, all of it delivered, with a budget enforced by tests).
- **Part b's trim of CLAUDE.md is nearly free money but small.** CLAUDE.md is cache-*read*. Trimming it from 7.5 KB to
  2.8 KB (text in §4) cut 1.7k read tokens per request: −1% of a trivial session ($0.1217 to $0.1203).
- **The lever MARVIN owns is the skill listing.** It is rewritten every session, and MARVIN adds 7.3k characters
  (about 1.8k tokens) over plain Claude Code's listing: 18 command stubs ("Invoke the X skill. Read ...", 2.0k) and
  18 more skills (5.2k). A skill marked `disable-model-invocation: true` still runs from its slash command but
  leaves the listing. Moving the routing table's triggers into the stubs would make things *worse*: it moves
  cache-read text into the rewritten block.
- **Output style (standing rules in the system prompt) was measured worse:** 14,433 tokens written and 20,863 read,
  against 13,309 and 21,946 for the plain CLAUDE.md trim. Dropped.

### Probe numbers (Run 31's overhead probe, "Reply with just: ok", second run of each, fresh temp folder)

| Variant | cache write | cache read | output | cost |
|---|---|---|---|---|
| plain Claude Code (clean) | 23,467 | 0 | 4 | $0.1878 |
| MARVIN today (live) | 13,391 | 23,681 | 492 | $0.1217 |
| + new session-start report (part a) | 13,308 | 23,681 | 495 | $0.1211 |
| + trimmed CLAUDE.md (§4) | 13,309 | 21,946 | 470 | $0.1203 |
| + rules moved to an output style | 14,433 | 20,863 | 286 | $0.1254 |

N = 1 steady-state run each (the first run of a new variant is cold), so treat them as a size check, not an effect
estimate. Total spend for these probes: $1.87 API-equivalent, from the plan.

## 2. The bench can't be re-run like-for-like right now

- **Plain Claude Code's caching changed between 2.1.316 (Run 31) and 2.1.318.** Today plain Claude Code rewrites
  everything (23.5k tokens) every run in the bench, because its system prompt embeds the auto-memory path, which
  is derived from the working folder. The bench gives every run a fresh temp folder. In Run 31 the same cell read
  11.4k tokens from cache. MARVIN pins `autoMemoryDirectory`, so it doesn't pay this. A re-run of
  `cost_validation.sh` today would very likely show MARVIN *cheaper* per session than plain Claude Code. That
  would be an artifact of the bench's folders, not of anything MARVIN changed. A person who works in one repo gets
  the cache.
- The fair fix is a stable working folder per (task, cell), emptied between runs. Then both cells' folder-dependent
  parts behave as they would in real repeated use. It's a bench change and needs a decision, because it moves the
  baseline against Run 31.
- The account was at its seven-day usage warning on 2026-11-04 (`bench.py`'s quota preflight refused a 6-session
  run). The full `cost_validation.sh` is about 75 sessions, about $25 API-equivalent (Run 31's figure).

## 3. Part c: routing that acts (design only)

Constraints already decided:
- **"Delegate, never switch"** (CONTEXT.md, launch kinds). A session doesn't change its own kind, and a model
  switch mid-session re-reads the whole conversation uncached (Claude Code's prompt-caching docs).
- **Run 31:** Haiku −67% on an explain task at the same quality, but **0/3 on the knowledge-base question**,
  because it never invoked the skill. `route.py` still sends `recall` to Haiku.

Options:
- **A. Route at launch, where the prompt is known before the session starts.** Examples: the phone Thread, a
  `marvin ask "<question>"` entry point, the launcher's dispatch. Reuse `route.py --launch` (`route.launch()`
  already execs `claude` with the routed model) and `auto_route_hook.classify()`. Confident `research`/explain goes
  to Haiku. `recall` and anything that needs a skill stays on the session model. No mid-session switch, so the
  cache stays intact. Sessions typed into a terminal keep today's suggestion.
- **B. In-session delegation.** On a confident explain-type first prompt, the UserPromptSubmit hook adds context
  telling the session to answer through a Haiku subagent (Agent tool, `model: haiku`). The parent has already paid
  its ~37k-token prefix by then, and the subagent starts cold on a 5-minute TTL, so a saving on short questions is
  doubtful. It would need its own measurement before anyone relies on it.
- **C. Suggest only** (today, once #560 is fixed).

Recommendation: **A**, plus changing `route.py`'s `recall` row to the session model. The table's own source (Run 8)
predates the skill-invocation failure Run 31 found.

## 4. Proposed CLAUDE.md (not applied: `~/.claude/CLAUDE.md` is live on every Mac the moment it syncs)

```markdown
# MARVIN

## Skills

Skills live at `~/.agents/skills/<name>/SKILL.md`. When a trigger below matches, read that SKILL.md and any file it names, and follow it.

- `diagnose`: bug, "debug/diagnose this", broken/throwing/failing, perf regression
- `tdd`: TDD, red-green-refactor, test-first, integration tests
- `grill-with-docs`: any grilling ("grill me", stress-test a plan) when a repo exists; `grill-me` only with no repo or when asked to skip doc-tracking
- `zoom-out`: unfamiliar code area; `improve-codebase-architecture`: refactor, reduce coupling
- `prototype`: prototype, mock up UI, "try a few designs"
- `handoff`: before any context switch (different project, major topic shift, unit of work done); save to `~/.claude/handoffs/`, show the resume prompt, then go on
- `caveman`: "caveman mode", "less tokens", "be brief"
- `write-a-skill`: create a skill; `setup-matt-pocock-skills`: first use in a new repo
- `to-tasklist`: design confirmed and the project has no issue tracker
- `self-improve`: a pattern worth keeping; `lexicon`: a new term with a stable meaning
- `research`: research, investigate a claim, evaluate a technology; `creative`: ideation, "surprise me"
- `architecture-review`: every 3-5 sessions or when this file grows; append to `~/.claude/suggestions.md`, never implement unapproved
- `index`: pick only the skill/knowledge files a task needs via `~/.claude/manifest.json`
- `qa-agent`: "qa", best practices for X, what worked/failed; query its KB before unfamiliar library work
- `improve`, `research-colony`, `paper-dive`, `route`: their slash names, digests, papers, model choice
- `audit`: docs/ADRs say one thing, the system does another; `writing-style`: prose for Gil (portfolio, resume, outreach)
- `readme`: write or check a README (`~/.agents/docs/readme-criteria.md`); `portfolio-page`: a gileskayo.me project page

## Every session

- **Interactive only:** the first line of your first reply is the `MARVIN active — ...` line from the session-start report, verbatim. Headless runs (no report) skip it.
- The session-start report (SessionStart hook) has already done the checklist; don't redo it by hand (`~/.agents/docs/session-start-checklist.md`). Lexicon terms it lists are defined in `~/.claude/lexicon.md`: read the definition before using one.
- Dev work (writing or changing code) defaults to `tdd` + `grill-with-docs`; off with "skip tdd" / "skip grill" / "no tests".
- `~/.claude/suggestions.md` is the approval-only backlog: mention only the count.
- When Gil asks something MARVIN's own data can't answer and you have to dig, guess or say you don't know, log it at once: `~/.agents/venv/bin/python ~/.agents/lib/question_log.py add "<question>" --why "<what was missing>" --want "<signal that would have answered it>"`.
```

Two things to check before applying it:
- In one probe (1 of 2) the model left out the banner under this wording. Keep the original wording of the
  banner rule ("headless launches (no session report in context) skip this") if it's applied.
- "Load ~/.claude/lexicon.md every session" is gone. The report now lists every term and points at the file.

## 5. Decisions recorded (Gil, 2026-11-04) and what was built

- **bench-folders: a stable folder per (task, cell), emptied between runs.** Built: `bench.py --workdir stable` is
  the default (`prepare_workdir`, `finish_workdir`); the folder sits in the same temp area as before, so it's still
  outside home. The cell's Claude Code auto memory is cleared between runs too, since a stable folder would
  otherwise carry one run's notes into the next. `--workdir fresh` keeps the Run 31 behaviour, and every run records
  `workdir_mode`. This moves the baseline against Run 31: compare a re-run with a re-run, not with Run 31.
- **rerun: not until #1037's task set exists (3 or more tasks per type), then once.** Nothing to build yet. Gil's
  note asks for semi-regular runs to keep it current; how often is a new decision in the PR.
- **skill-listing: none chosen; route skills to the chats that need them, from what is used, never slash-only, and
  drop deprecated tools.** Usage (`lib/tool_usage.py`, 30 days, MacBook): 12 of 29 skills used, 17 never. The
  per-chat skill sets are #1179 (Load only the skills a chat needs). The dead `self-optimize` command link (its skill
  folder was gone) was removed; which other deprecated tools go is a new decision in the PR.
- **claude-md: leave `~/.claude/CLAUDE.md` as it is.** Not applied. §4 stays as a record.
- **routing: A, route at launch where the prompt is known first.** Built: `route.launch_model(prompt)` (confident
  embedding match only: keyword fallback, no match, bad output or a classifier failure keep the session model; only
  `research` changes model) and `bin/marvin-ask "<question>"`, which opens an interactive session on that model.
  The phone Thread's backend and a prompt-carrying dispatch don't exist yet; when they're built they call
  `launch_model()`. Typed sessions keep the suggestion.
- **recall-model: keep recall on the session model.** Built: `route.INTENTS["recall"]["model"]` is `None`, and the
  first-prompt hook no longer suggests switching for recall. Gil's note asks whether Haiku is still the best pick;
  the table still pins Haiku 4.5 while Haiku 5.5 is out, so which Haiku research uses is a new decision, and #1087
  (model usage by kind of work, against quality) is where the ongoing answer lives.
