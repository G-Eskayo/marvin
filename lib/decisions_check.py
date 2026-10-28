"""Rule I2, askable questions (ADR 0080, marvin#742): every question to the owner is machine-readable.

The dashboard only shows questions written in its Decisions format (docs/agents/decisions-format.md). Chats were told
the format in their prompts and wrote a prose list anyway (clarity-captions #179 and #181), so the owner was asked
nothing. bin/gh is the place every chat and agent write passes, so it refuses `pr create|edit|comment` and
`issue create|edit|comment` when the new body

  - has a heading that asks (## Decisions, ## Open questions, ## Choose, ...) and no `<!-- marvin:decisions -->`
    block: DECISIONS_NOT_ASKABLE
  - has the block but it doesn't parse (a question with no id, a choice with one option, ...): DECISIONS_UNPARSED

There is one parser, the dashboard's dashboard/webhook-server/decisions.js; this runs it through node
(decisions_cli.js) and never re-implements it. Fails OPEN, with a note, when node or the parser can't run: a broken
check must not stop all GitHub work, and the merge server still refuses unanswerable decisions.
MARVIN_DECISIONS_OK="<reason>" lets one call through, logged. MARVIN_NODE names node when it isn't on PATH.
Stdlib only: bin/gh imports it on every call.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
from pathlib import Path

OVERRIDE = "MARVIN_DECISIONS_OK"
CLI = Path(__file__).resolve().parents[1] / "dashboard" / "webhook-server" / "decisions_cli.js"
FORMAT_DOC = "docs/agents/decisions-format.md"
# Where node usually is when a launchd job's PATH leaves it out.
NODE_PLACES = ("/opt/homebrew/bin/node", "/usr/local/bin/node", "/usr/bin/node")

_CHECKED = {("pr", "create"), ("pr", "edit"), ("pr", "comment"),
            ("issue", "create"), ("issue", "edit"), ("issue", "comment")}
_BODY = {"--body": "body", "-b": "body", "--body-file": "body_file", "-F": "body_file"}
# Flags of these commands that take a value, so the value is never read as a body flag.
_VALUED = {"--title", "-t", "--repo", "-R", "--base", "-B", "--head", "-H", "--label", "-l", "--add-label",
           "--remove-label", "--assignee", "-a", "--add-assignee", "--remove-assignee", "--reviewer", "-r",
           "--add-reviewer", "--remove-reviewer", "--milestone", "-m", "--project", "-p", "--add-project",
           "--remove-project", "--template", "-T", "--recover"}


def body_call(argv) -> dict | None:
    """{cmd, body, body_file} for a call that sets a body this rule checks, else None."""
    if len(argv) < 2 or (argv[0], argv[1]) not in _CHECKED or "--help" in argv or "-h" in argv:
        return None
    call = {"cmd": f"{argv[0]} {argv[1]}", "body": None, "body_file": None}
    rest = list(argv[2:])
    i = 0
    while i < len(rest):
        flag, eq, value = rest[i].partition("=")
        if flag in _BODY:
            if not eq:
                i += 1
                value = rest[i] if i < len(rest) else None
            call[_BODY[flag]] = value
        elif flag in _VALUED and not eq:
            i += 1
        i += 1
    if call["body"] is None and call["body_file"] in (None, "-"):
        return None  # no new body, or it's on stdin, which belongs to gh
    return call


def find_node(path: str | None = None, extra=NODE_PLACES) -> str | None:
    named = os.environ.get("MARVIN_NODE")
    if named:
        return named if os.access(named, os.X_OK) else None
    found = shutil.which("node", path=os.environ.get("PATH", "") if path is None else path)
    if found:
        return found
    return next((p for p in extra if os.access(p, os.X_OK)), None)


def refusal(body: str, node: str | None | bool = True, cli: Path = CLI, say=lambda _m: None) -> str | None:
    """The refusal message for a body that asks the owner something he can't answer in the dashboard, else None."""
    node = find_node() if node is True else node
    if not node:
        say("couldn't check this body's Decisions (node isn't installed); letting it through")
        return None
    try:
        p = subprocess.run([node, str(cli)], input=body or "", capture_output=True, text=True, timeout=20)
        if p.returncode != 0:
            raise RuntimeError((p.stderr or "").strip().splitlines()[-1:] or [f"exit {p.returncode}"])
        r = json.loads(p.stdout)
    except Exception as e:  # noqa: BLE001
        say(f"couldn't check this body's Decisions ({str(e)[:160]}); letting it through")
        return None
    if r["present"] and r["problems"]:
        return (f"DECISIONS_UNPARSED: the <!-- marvin:decisions --> block doesn't parse: {'; '.join(r['problems'])}. "
                f"The dashboard can't show it as questions. Fix it as {FORMAT_DOC} shows.")
    if not r["present"] and r["heading"]:
        return (f'DECISIONS_NOT_ASKABLE: "{r["heading"]}" asks the owner to choose, but there is no '
                f"<!-- marvin:decisions --> block, so the dashboard shows no questions and he is asked nothing. "
                f"Put the marker under the heading, each question as \"### some-id: question\" and its options as "
                f"\"- [ ] option\" lines ({FORMAT_DOC}). A heading that only reports (\"## Decisions recorded\") "
                f"isn't an ask.")
    return None


def gate(argv, say, log, env=os.environ, read_file=None) -> int | None:
    """What bin/gh calls: 1 (refused, said why) or None (go on). `log(entry)` records overrides and refusals."""
    call = body_call(argv)
    if not call:
        return None
    override = (env.get(OVERRIDE) or "").strip()
    if override:
        log({"cmd": call["cmd"], "decisions_override": override[:200]})
        return None
    if call["body_file"] and call["body"] is None:
        try:
            body = (read_file or (lambda f: Path(f).read_text()))(call["body_file"])
        except OSError:
            return None  # gh says the file is missing, in its own words
    else:
        body = call["body"]
    msg = refusal(body, say=say)
    if not msg:
        return None
    say(msg)
    say(f'(only if a person agrees this isn\'t a question to the owner: {OVERRIDE}="<reason>" gh ...)')
    log({"cmd": call["cmd"], "rc": 1, "decisions": msg[:200]})
    return 1
