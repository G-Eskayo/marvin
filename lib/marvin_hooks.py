#!/usr/bin/env python3
"""MARVIN's Claude Code hooks, at user level, each declaring which launch kinds it runs for (marvin#291, ADR 0059).

Hooks used to live in ~/.claude/settings.local.json, which Claude Code applies only to sessions started in the
home folder, so a session started anywhere else (a project, a worktree, ~/.agents) ran none of them. They now live
in the synced ~/.claude/settings.json, so they reach every session on both Macs, and each command goes through
`gate`, which reads the launch-kind marker the MARVIN launcher sets:

- **all**: safety and telemetry (the merge guard, skill activity) run for every kind.
- **interactive**: session upkeep (sync, session report, self-review, handoff prompts, auto-route) runs only
  when a person is in the session. No marker means a person started `claude` by hand: Interactive.

`install` writes the hooks and the one memory folder (`autoMemoryDirectory`) into settings.json and takes the
hooks out of settings.local.json, keeping a backup. Run it on each Mac after this lands:
`~/.agents/venv/bin/python ~/.agents/lib/marvin_hooks.py install`.

The gate runs on every tool call, so it imports nothing beyond the standard library.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

KIND_ENV = "MARVIN_LAUNCH_KIND"  # the same marker marvin_launcher sets
HOME = Path.home()
AGENTS = HOME / ".agents"
PY = str(AGENTS / "venv" / "bin" / "python")
GATE_SCRIPT = AGENTS / "lib" / "marvin_hooks.py"
USER_SETTINGS = HOME / ".claude" / "settings.json"
LOCAL_SETTINGS = HOME / ".claude" / "settings.local.json"
PROJECTS = HOME / ".claude" / "projects"
MAIN_MEMORY = PROJECTS / str(HOME).replace("/", "-") / "memory"


@dataclass(frozen=True)
class Hook:
    event: str
    command: tuple[str, ...]
    kinds: frozenset[str]
    matcher: str | None = None


def _py(script: str) -> tuple[str, ...]:
    return (PY, str(AGENTS / script))


_SESSION_START = " && ".join([
    f"{PY} {AGENTS}/lib/code_sync.py pull {AGENTS}",
    f"{PY} {AGENTS}/lib/code_sync.py pull {HOME}/.claude",
    f"{PY} {AGENTS}/skills/handoff/scripts/check_remote_session.py",
    f"{PY} {AGENTS}/lib/session_start_report.py",
])
_ALL, _INTERACTIVE = frozenset({"all"}), frozenset({"interactive"})
_EDITS = "Write|Edit|MultiEdit|NotebookEdit"

HOOKS: list[Hook] = [
    Hook("PreToolUse", _py("lib/gh_merge_guard.py"), _ALL, "Bash"),
    *(Hook("PostToolUse", _py(s), _INTERACTIVE, "Write|Edit") for s in (
        "skills/self-improve/scripts/rebuild-manifest.py",
        "skills/handoff/scripts/emit-resume-prompt.py",
        "skills/qa-agent/scripts/qa_session_capture.py",
        "skills/improve/scripts/improvement_sweep.py",
        "skills/self-improve/scripts/background_review.py",
        "skills/handoff/scripts/trigger_code_sync.py",
    )),
    Hook("PostToolUse", _py("brain-map/scripts/skill_activity.py"), _ALL),
    Hook("SessionStart", ("/bin/sh", "-c", _SESSION_START), _INTERACTIVE),
    Hook("UserPromptSubmit", _py("skills/route/scripts/auto_route_hook.py"), _INTERACTIVE),
    # Sessions know what other sessions are working on (#326, ADR 0062): every session's request and edits go on
    # the live list; a person's session is asked before editing a file another live session edited.
    Hook("UserPromptSubmit", (*_py("lib/session_work.py"), "hook", "prompt"), _ALL),
    Hook("PostToolUse", (*_py("lib/session_work.py"), "hook", "post"), _ALL, _EDITS),
    Hook("PreToolUse", (*_py("lib/session_work.py"), "hook", "pre"), _INTERACTIVE, _EDITS),
]


def gate(kinds: str, command: list[str]) -> None:
    """Run `command` (replacing this process, so stdin and the exit code pass straight through) when the
    session's launch kind is one of `kinds`; otherwise exit 0 without reading anything."""
    kind = os.environ.get(KIND_ENV) or "interactive"
    wanted = set(kinds.split(","))
    if "all" in wanted or kind in wanted:
        os.execv(command[0], command)
    sys.exit(0)


def settings_hooks() -> dict:
    """The `hooks` block for settings.json, every command wrapped in the gate. Hooks sharing an event and
    matcher stay in one group, in table order."""
    out: dict[str, list[dict]] = {}
    for hook in HOOKS:
        cmd = f"{PY} {GATE_SCRIPT} gate {','.join(sorted(hook.kinds))} -- {shlex.join(hook.command)}"
        groups = out.setdefault(hook.event, [])
        group = next((g for g in groups if g.get("matcher") == hook.matcher), None)
        if group is None:
            group = {"matcher": hook.matcher, "hooks": []} if hook.matcher else {"hooks": []}
            groups.append(group)
        group["hooks"].append({"type": "command", "command": cmd})
    return out


def _scripts_in(command: str) -> list[str]:
    """The .py/.sh scripts a hook command runs, in order: the gate itself, the script after `--`, and each script
    of a `sh -c '... && ...'` chain (a quoted chain is one shell word, so it is split again)."""
    try:
        words = shlex.split(command)
    except ValueError:  # an unbalanced quote: plain words, quotes dropped, still better than losing the script
        words = command.replace("'", " ").replace('"', " ").split()
    out: list[str] = []
    for w in words:
        found = _scripts_in(w) if any(c.isspace() for c in w) else [w] if w.endswith((".py", ".sh")) else []
        out += [s for s in found if s not in out]
    return out


def wired_scripts(paths=(USER_SETTINGS, LOCAL_SETTINGS)) -> list[dict]:
    """Every script a Claude Code hook actually runs, read from the live settings files (user level, and the old
    home-folder level), one entry per script with each trigger it runs on ("PostToolUse: Write|Edit"). The map's
    Infrastructure section and auto_fix's never-touch list read this, so neither needs to know how hooks are
    wired; both read settings.local.json alone until #291 moved the hooks out of it and they each saw none."""
    found: dict[str, dict] = {}
    for path in paths:
        try:
            hooks = json.loads(Path(path).read_text(encoding="utf-8")).get("hooks", {})
        except (OSError, ValueError, AttributeError):
            continue
        for event, entries in hooks.items() if isinstance(hooks, dict) else ():
            for entry in entries if isinstance(entries, list) else ():
                if not isinstance(entry, dict):
                    continue
                trigger = f"{event}: {entry['matcher']}" if entry.get("matcher") else event
                for h in entry.get("hooks") or ():
                    if not isinstance(h, dict) or h.get("type") != "command":
                        continue
                    for script in _scripts_in(h.get("command") or ""):
                        triggers = found.setdefault(script, {"path": script, "triggers": []})["triggers"]
                        if trigger not in triggers:
                            triggers.append(trigger)
    return sorted(found.values(), key=lambda r: (Path(r["path"]).name, r["path"]))


def _load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _save(path: Path, settings: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n")
    tmp.replace(path)


def install(user_path: Path = USER_SETTINGS, local_path: Path = LOCAL_SETTINGS,
            memory_dir: Path = MAIN_MEMORY) -> None:
    user = _load(user_path)
    user["hooks"] = settings_hooks()
    user["autoMemoryDirectory"] = str(memory_dir)
    _save(user_path, user)
    local = _load(local_path)
    if "hooks" in local:
        backup = local_path.with_name(local_path.name + ".pre-marvin-hooks")
        if not backup.exists():
            shutil.copy2(local_path, backup)
        del local["hooks"]
        _save(local_path, local)


def stray_memories(projects: Path = PROJECTS, main: Path = MAIN_MEMORY) -> list[Path]:
    """Notes written to a memory folder other than the main one: the split this ticket ends."""
    return sorted(p for p in projects.glob("*/memory/*.md") if p.parent.resolve() != main.resolve())


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["gate"] and len(args) >= 4 and args[2] == "--":
        gate(args[1], args[3:])
    elif args == ["install"]:
        install()
        import commit_check  # the direct-commit check (ADR 0063 gate 4, #337) in ~/.agents' git hooks
        print("commit check:", commit_check.install_hook(AGENTS))
        strays = stray_memories()
        print(f"hooks installed in {USER_SETTINGS}; memory -> {MAIN_MEMORY}")
        if strays:
            print(f"{len(strays)} note(s) in other memory folders, merge them into the main memory:")
            print("\n".join(f"  {p}" for p in strays))
    else:
        sys.exit("usage: marvin_hooks.py gate <kinds> -- <command...> | install")
