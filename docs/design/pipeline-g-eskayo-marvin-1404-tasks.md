1. Draft the reply comment body for PR #1401 (plain-text/markdown, no `## Decisions`/`## Open questions`/`## Choose` heading unless paired with a marker):
   - Open with `<!-- marvin:decisions-addressed -->`.
   - `deep-latency`: state "Keep it" is carried out — matches the already-built behavior (holding line, 8 s Siri-doorway wait, Thread fallback for long deep answers); no commit was needed. Note there is no screenshot to retake/pin (backend-only PR, no UI changed; evidence is the CLI/HTTP table already in the PR description).
   - `deep-tools`: state plainly that none of the three options was chosen, the attached note is not a question (so nothing to answer), and that per Gil's own "still working on that," it's being left open rather than re-asked — the same three options remain live, unticked, in the PR description whenever he's ready.
   - Surface the `dashboard-ux-potholes-2026-10-29.md` "status sentence" (#670, S3) connection to the `deep-tools` note, as context/offer, not a forced decision.
   - "Earlier answers" disposition: list the five docs, each marked kept with its one-line reason (per the table above).
2. Validate the draft against `lib/decisions_check.py` locally (no heading trips the gate; marker present).
3. Post the comment on PR #1401 via `~/.agents/bin/gh pr comment 1401 --repo G-Eskayo/marvin --body-file -` (never raw `gh`, never `--no-verify`-equivalent bypass).
4. Verify mechanically: `lib/owner_decisions.py status --repo G-Eskayo/marvin --pr 1401` reports `addressed_by: "reply"` and `built: true`.
5. No edits needed to `instance/docs/plans/*`, the two memory files, PR #1401's source files, or `docs/adr/0075-*` — confirmed above that all five "earlier answer" citations are kept as-is, and no code path carries a chosen, actionable option.
6. No action needed to close ticket #1404 itself — the hourly scan (`lib/owner_decisions.py scan`) closes it automatically once the reply lands (per its own filing code, `lib/owner_decisions.py:390`).