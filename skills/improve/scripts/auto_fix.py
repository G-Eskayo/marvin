#!/usr/bin/env python3
"""Autonomous low-risk cosmetic auto-fixer for MARVIN's own codebase.

Gil's direction, 2026-07-08: "I want you to start to own your own
optimization and bug fixes... these similar low risk small daily patches
needs to get automized. Things that don't affect core files or deleting my
files." Deliberately conservative v1 scope, calibrated against the exact
fixes done manually and verified safe the same day:

- Only NAMING and VERBOSITY findings from qa_scan.py — both behavior-
  preserving by construction (a parameter rename, a comment rewrite; never
  logic).
- Only files under ~/.agents (MARVIN's own codebase) — never Gil's actual
  project directories.
- Never files this system depends on to run itself right now (see
  _core_files() below) — derived from settings.local.json's live hooks and
  every com.marvin.*/com.gileskayo.* launchd plist's ProgramArguments, not
  hardcoded, so it grows automatically as more infra gets built.
- Never deletes anything — the fixer subprocess gets Read+Edit only, no
  Bash, no Write (Edit alone can't create new files). "Don't delete my
  files" is enforced by not granting that capability, not by asking nicely.
- Every candidate file is backed up before the fixer runs and restored
  automatically if it fails to compile afterward — safe by construction,
  not just by prompt instruction, matching background_review.py's fork-to-
  review pattern this reuses directly.

Run standalone: ~/.agents/venv/bin/python auto_fix.py
"""
from __future__ import annotations
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

AGENTS_DIR = Path.home() / ".agents"
LOG_PATH = Path.home() / ".claude" / "auto-fix-log.md"
QA_SCAN = AGENTS_DIR / "skills" / "qa-agent" / "scripts" / "qa_scan.py"
VENV_PYTHON = AGENTS_DIR / "venv" / "bin" / "python"
SETTINGS_LOCAL = Path.home() / ".claude" / "settings.local.json"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"

SAFE_CATEGORIES = {"NAMING", "VERBOSITY"}


def _resolve_claude_bin() -> str:
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (
        Path.home() / ".local" / "bin" / "claude",
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
    ):
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError("claude CLI not found on PATH or in common install locations")


def _core_files() -> set[Path]:
    """Every script this system currently depends on to run itself —
    derived live from what's actually wired up, not hardcoded, so new
    hooks/cron jobs are automatically excluded without editing this file."""
    core: set[Path] = set()

    try:
        hooks = json.loads(SETTINGS_LOCAL.read_text()).get("hooks", {})
        for entries in hooks.values():
            for entry in entries:
                for h in entry.get("hooks", []):
                    cmd = h.get("command", "")
                    for token in cmd.split():
                        if token.endswith(".py") and str(AGENTS_DIR) in token:
                            core.add(Path(token).resolve())
    except Exception:
        pass

    try:
        for plist in LAUNCH_AGENTS_DIR.glob("com.marvin.*.plist"):
            text = plist.read_text()
            for match in re.findall(r"<string>([^<]+\.py)</string>", text):
                if str(AGENTS_DIR) in match:
                    core.add(Path(match).resolve())
        for plist in LAUNCH_AGENTS_DIR.glob("com.gileskayo.*.plist"):
            text = plist.read_text()
            for match in re.findall(r"<string>([^<]+\.py)</string>", text):
                if str(AGENTS_DIR) in match:
                    core.add(Path(match).resolve())
    except Exception:
        pass

    return core


FINDING_RE = re.compile(r"\[(\w+)\]\s*(.*?)\s*\(file:\s*([^)]+)\)")


def get_candidates() -> list[dict]:
    """Fresh qa_scan.py pass (via its importable scan() function, same as
    improvement_sweep.py uses), filtered to the safe-category whitelist and
    scoped away from core infrastructure files."""
    sys.path.insert(0, str(QA_SCAN.parent))
    try:
        from qa_scan import scan  # noqa: E402
        entries = scan(AGENTS_DIR)
    except Exception as e:
        print(f"[auto-fix] qa_scan failed: {e}", file=sys.stderr)
        return []

    core = _core_files()
    candidates = []
    for e in entries:
        doc = e.get("document", "")
        m = FINDING_RE.match(doc)
        if not m:
            continue
        kind, message, file_path = m.group(1), m.group(2), m.group(3).strip()
        if kind.upper() not in SAFE_CATEGORIES:
            continue
        try:
            resolved = Path(file_path) if Path(file_path).is_absolute() else (AGENTS_DIR / file_path)
            resolved = resolved.resolve()
        except Exception:
            continue
        if AGENTS_DIR.resolve() not in resolved.parents:
            continue
        if resolved in core:
            continue
        candidates.append({"category": kind.upper(), "message": message, "resolved_path": str(resolved)})
    return candidates


FIX_PROMPT_TEMPLATE = """You are MARVIN's autonomous low-risk cosmetic fixer, running unattended with Read and Edit only — no Bash, no Write, no other tools. This is deliberate: you physically cannot create new files, run commands, or do anything beyond read and edit existing files, so it's safe to run without anyone watching.

Fix ONLY the specific findings listed below, exactly as described. Each is either a generic/unclear variable or parameter name (rename it to something descriptive, update every reference in that function), or a filler word in a comment (tighten the wording, preserve the meaning). Do not touch anything else in any file — no refactoring, no other renames, no logic changes, no reformatting unrelated lines.

If a finding looks wrong, already fixed, or you're not fully confident the fix is safe and correct, skip it rather than guess.

Findings to fix:
{findings_list}
"""


def build_prompt(candidates: list[dict]) -> str:
    lines = []
    for c in candidates:
        lines.append(f"- [{c.get('category')}] {c.get('message', '')} — file: {c['resolved_path']}")
    return FIX_PROMPT_TEMPLATE.format(findings_list="\n".join(lines))


def backup_files(paths: list[Path], backup_dir: Path) -> dict[Path, Path]:
    mapping = {}
    for p in paths:
        if p.exists():
            dest = backup_dir / p.name.replace("/", "_")
            dest = backup_dir / f"{abs(hash(str(p)))}_{p.name}"
            shutil.copy2(p, dest)
            mapping[p] = dest
    return mapping


def verify_and_revert(paths: list[Path], backups: dict[Path, Path]) -> tuple[list[Path], list[Path]]:
    """Returns (fixed_ok, reverted) — reverts any .py file that no longer compiles."""
    fixed_ok, reverted = [], []
    for p in paths:
        if not p.exists():
            continue
        original = backups.get(p)
        if original is None:
            continue
        if p.read_bytes() == original.read_bytes():
            continue  # untouched
        if p.suffix == ".py":
            check = subprocess.run([str(VENV_PYTHON), "-m", "py_compile", str(p)], capture_output=True)
            if check.returncode != 0:
                shutil.copy2(original, p)
                reverted.append(p)
                continue
        fixed_ok.append(p)
    return fixed_ok, reverted


def log_run(candidates: list[dict], fixed_ok: list[Path], reverted: list[Path], skipped: bool, reason: str = "") -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    lines = [f"\n## {ts}"]
    if skipped:
        lines.append(f"Skipped — {reason}")
    else:
        lines.append(f"{len(candidates)} candidate(s) found, {len(fixed_ok)} fixed, {len(reverted)} reverted (failed compile check)")
        for p in fixed_ok:
            lines.append(f"- fixed: `{p}`")
        for p in reverted:
            lines.append(f"- reverted (broke compile, restored from backup): `{p}`")
    with LOG_PATH.open("a") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    candidates = get_candidates()
    if not candidates:
        log_run([], [], [], skipped=True, reason="no safe-category findings")
        return

    paths = [Path(c["resolved_path"]) for c in candidates]
    with tempfile.TemporaryDirectory(prefix="marvin-autofix-") as tmpdir:
        backups = backup_files(paths, Path(tmpdir))

        try:
            claude_bin = _resolve_claude_bin()
        except FileNotFoundError as e:
            log_run(candidates, [], [], skipped=True, reason=str(e))
            return

        prompt = build_prompt(candidates)
        subprocess.run(
            [
                claude_bin, "-p", prompt,
                "--tools", "Read,Edit",
                "--permission-mode", "bypassPermissions",
                "--output-format", "text",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            timeout=300,
        )

        fixed_ok, reverted = verify_and_revert(paths, backups)
        log_run(candidates, fixed_ok, reverted, skipped=False)


if __name__ == "__main__":
    main()
