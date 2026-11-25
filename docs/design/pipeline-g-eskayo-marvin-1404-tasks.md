1. Immediately before acting: re-fetch PR #1401's current body, comments, and commit list; re-check branch `voice-endpoint-670` is still the head and the PR is still open.
2. Confirm no "Decisions from the owner" comment newer than `7084843647` exists; if one does, restart analysis from that comment instead.
3. Verify `deep-latency`'s "Keep it" against the current code on `origin/voice-endpoint-670` (`dashboard/mobile-backend/voice_api.js`: the `deepWaitMs`/`deepStreamMaxMs` race and `deepPending` Thread-fallback path) and note the exact file/behavior as evidence in the reply.
4. Draft the PR reply (statements only, no question-shaped prose):
   - `deep-latency`: confirmed as-built, cites the code, nothing changed.
   - `deep-tools`: states the owner gave a note but chose no option; nothing built; the note is quoted; the existing `deep-tools` Decisions block in PR #1401's body stays open and unanswered for him, with a one-line pointer to ADR 0085 (front-desk / human-readable reporting direction) as where the broader "lab assistant" idea belongs once it's concrete enough to turn into options.
   - Earlier-answers checklist: all 5 items marked kept, each with its one-line "relation only, no restated decision" reason.
   - Screenshots: states this PR has no UI/visual surface, so there is nothing to retake or pin.
   - Ends with `<!-- marvin:decisions-addressed -->`.
5. Post the comment on PR #1401 via `~/.agents/bin/gh pr comment 1401 --repo G-Eskayo/marvin --body-file -` (not raw `gh`).
6. Confirm issue #1404 closes itself as documented; take no manual close action.