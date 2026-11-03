# Showing Gil things: `marvin show`

Whenever a reply asks Gil to look at something (a screenshot, a mock-up, a PR image, a rendered page, a plan, a
report), show it with `marvin show`. It opens in that project's own MARVIN window, on top, with "Open in Docs" for
the full tab. Never send a file card (SendUserFile), a claude.ai artifact or a bare temp path instead: Gil's client
may not show the card, and he can't find a temp path later (2026-11-02, #715).

```
marvin-show <file>                          a file in a project's clone, the outbox, or a temp folder
marvin-show <repo path> --pr 934            a file on a PR branch, read at the PR's head (--repo owner/name if not here)
marvin-show https://github.com/o/r/blob/<branch>/<path>   the same, from a GitHub link
marvin-show <url>                           any web address, drawn in the window ("Open in browser" in the header)
  --project <id>   whose it is, when the session isn't in that project's folder
  --topic <words>  names the outbox folder for a temp file (default: the file's name)
```

- A file under `/tmp`, `/private/tmp` or `/var/folders` is copied into
  `~/.claude/outbox/<project>-<YYYY-MM-DD>-<topic>/` first, so nothing Gil is shown lives only in temp. The folder
  starts with the project's id, which is how the Docs tab files it under that project. An HTML page brings the files
  it names (scripts, styles, images). Over 50 MB is refused (the outbox syncs through git).
- One window per project, reused: the next `marvin show` for the same project replaces what it shows. A new window
  opens with the size and place of the last show window Gil moved (back to 920×760, centred, if that screen is gone).
- A web page loads in the window, in its own in-memory session with no access to the app, this Mac's files or the
  local network (a local address you show, like a dev server, is the one exception). "Open in browser" is always in
  the header; if the page can't be drawn, the window shows the link card with the reason.
- HTML runs in a sandboxed frame: clickable, but no network, no pop-ups, no access to the app.
- Refused: anything outside the outbox, `~/.agents`, the project clones and `~/Developer`, and anything that looks
  like a secret. Exit codes: 0 shown, 2 refused, 3 the dashboard can't be reached.
- The dashboard not running: it is started. If it can't be reached, say so and give the outbox path; don't fall back
  to a file card.
- Put the command in your reply too (`marvin show <path>`), so Gil can run it again.
