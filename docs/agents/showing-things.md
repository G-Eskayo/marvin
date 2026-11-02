# Showing Gil things: `marvin show`

Whenever a reply asks Gil to look at something (a screenshot, a mock-up, a PR image, a rendered page, a plan, a
report), show it with `marvin show`. It opens in that project's own MARVIN window, on top, with "Open in Docs" for
the full tab. Never send a file card (SendUserFile), a claude.ai artifact or a bare temp path instead: Gil's client
may not show the card, and he can't find a temp path later (2026-11-02, #715).

```
marvin-show <file>                          a file in a project's clone, the outbox, or a temp folder
marvin-show <repo path> --pr 934            a file on a PR branch, read at the PR's head (--repo owner/name if not here)
marvin-show https://github.com/o/r/blob/<branch>/<path>   the same, from a GitHub link
marvin-show <url>                           any web address, as a link Gil opens in his browser
  --project <id>   whose it is, when the session isn't in that project's folder
  --topic <words>  names the outbox folder for a temp file (default: the file's name)
```

- A file under `/tmp`, `/private/tmp` or `/var/folders` is copied into
  `~/.claude/outbox/<project>-<YYYY-MM-DD>-<topic>/` first, so nothing Gil is shown lives only in temp. The folder
  starts with the project's id, which is how the Docs tab files it under that project. An HTML page brings the files
  it names (scripts, styles, images). Over 50 MB is refused (the outbox syncs through git).
- One window per project, reused: the next `marvin show` for the same project replaces what it shows. A strip under
  the title lists that project's earlier items; a click shows one again.
- It opens on the Mac Gil is using (the most recent keyboard or mouse input). An asleep or unreachable Mac is skipped,
  and if the other Mac can't take it, it opens here. `--here` keeps it on this Mac.
- HTML runs in a sandboxed frame: clickable, but no network, no pop-ups, no access to the app.
- Refused: anything outside the outbox, `~/.agents`, the project clones and `~/Developer`, and anything that looks
  like a secret. Exit codes: 0 shown, 2 refused, 3 the dashboard can't be reached.
- The dashboard not running: it is started. If it can't be reached, say so and give the outbox path; don't fall back
  to a file card.
- Put the command in your reply too (`marvin show <path>`), so Gil can run it again.

## Enforced, not only remembered

- `deliverable_location_guard.py` (PreToolUse, every session and helper): a file card (SendUserFile) or artifact from
  a temp folder is refused, with `marvin-show` named as the way.
- `temp_deliverable_hook.py` (PostToolUse + Stop/SubagentStop, every session and helper): writing an image, PDF or
  HTML file under a temp folder puts a one-line reminder in context; a reply that points Gil at a temp-only file it
  never showed gets a reminder before the turn ends. How strict is `config/show_rule.json` `mode`: `note`, `nudge`
  (default: one reminder, then the session may stop), `hold`.
