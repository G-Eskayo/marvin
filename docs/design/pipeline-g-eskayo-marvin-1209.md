I'm blocked and can't produce a verified plan. Here's the situation:

## Blocker: cannot read issue #1209

I retried `gh issue view 1209 --repo G-Eskayo/marvin` (plain and `--comments`) five times over several minutes, plus `gh issue list` and `gh repo view` as a sanity check — all fail identically:

```
error connecting to api.github.com
check your internet connection or https://githubstatus.com
```

This sandbox only permits `gh` (view/list/diff), `git` (log/diff/show/blame), and `graphify query` — no `curl`, `WebFetch`, `env`, or `ping` to probe further. `git log`/`git remote -v` on the local repo still work fine, but that doesn't exercise network I/O, so I can't confirm whether this is a `github.com`-wide outage or something scoped to this sandbox's DNS/egress for `api.github.com`. There's no local mirror of the issue text in this worktree (checked — no match beyond an unrelated `11209` substring in a bench fixture).

**What I have instead, clearly unverified:** my memory note [[claude-child-session-env-no-transcript]] (8 days old) says ticket 1209 is about `helper-tab … claude --resume` inheriting the parent's `CLAUDE_CODE_CHILD_SESSION`/`CLAUDE_CODE_SESSION_ID`/etc. env vars, which disables transcript saving in the child session. That's a plausible shape for this ticket, but I have zero visibility into its actual "What to build," acceptance criteria, "How we'll try to break it" list, or any denial/failure-note comments from a prior attempt — and the instructions explicitly treat those as requirements, not optional context. Writing a plan against a guess instead of the real ticket would violate "Verified, not assumed" and risks missing exactly the feedback this ticket says to check for.

I'm not going to fabricate acceptance criteria or a task list from an aging memory snapshot. Two ways forward:

1. **Retry later** — if this is a transient outage, re-run the same `gh issue view` command once connectivity is back.
2. **You paste the issue body/comments** here and I'll build the plan immediately from the real text.

## Task List
TOO_VAGUE: not applicable — the blocker isn't ticket vagueness, it's that `gh` cannot reach `api.github.com` from this sandbox, so issue #1209's actual content (What to build, acceptance criteria, break-it list, comments) was never retrieved. No plan or task list can be verified against the ticket until that access is restored.