# Safety Monitor — Retrospective

## 2026-07-13 — verify() timeout root cause

**I:** Root-caused a recurring `verify()` failed-open timeout that cron_health
had surfaced 3 times across daily_digest and research_colony. The rubric's own
"does it reference something that doesn't exist" framing was inviting haiku
to go verify that by actually exploring the filesystem via tool access — even
though `source_context` already handed it everything it needed. Measured live:
113s with default tool access (it genuinely explored the repo) vs ~50-58s with
tools off. Generalizes beyond this one script: any subagent call (`claude -p
...`) that pairs a verification-flavored prompt with live tool access risks
the model "helpfully" going to check for itself instead of judging from the
context it was already given — inflating latency unpredictably and risking
timeouts even when the fast path would've been plenty.

**S:** The fix needed both halves, not either alone — confirmed by testing
each in isolation. `--tools ""` alone wasn't sufficient: haiku still emitted
hallucinated pseudo-tool-call text that broke the score-parsing regex. Adding
an explicit "you have no tool access and cannot read any files" line to the
prompt, on top of `--tools ""`, was what actually fixed it. Also raised the
timeout 60s→120s since even the clean, tools-off case measured close to the
old 60s limit with no slack. Verified end-to-end with a real `verify()` call
(clean score, no failed-open). See `scripts/verify.py`'s inline comment for
the exact fix site.
