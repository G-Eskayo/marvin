#!/usr/bin/env python3
"""Classify a task and output the optimal Claude profile + model routing.

Usage:
    route.py "what were the bench results?"        # classify + print routing
    route.py "fix the bug in utils.py" --launch   # classify + exec claude
    route.py --recall --launch                     # explicit recall mode + launch
    route.py --table                               # show full routing table
    route.py --aliases                             # print shell alias definitions

Routing is keyword-scored. With ≥2 keyword hits the winning intent is used;
ties or zero-hit tasks fall back to the 'architecture' default (full config,
default model — the conservative, never-wrong choice).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# ── routing table ─────────────────────────────────────────────────────────────

INTENTS: dict[str, dict] = {
    "recall": {
        "profile":    "marvin",
        "model":      "claude-haiku-4-5-20251001",
        "config_dir": "~/.claude",
        "alias":      "claude-recall",
        "keywords": [
            "recall", "remember", "from memory", "what did we", "previous session",
            "last session", "session history", "bench result", "we built",
            "we discussed", "we decided", "handoff", "resume", "do you remember",
            "from last time", "stored", "you know", "what was the",
        ],
        "why": "Memory retrieval — MARVIN's ChromaDB holds the answer. "
               "Haiku handles recall at ~60% Sonnet cost (bench Run 8).",
        "savings": "~60% vs MARVIN + Sonnet",
    },
    "research": {
        "profile":    "marvin",
        "model":      "claude-haiku-4-5-20251001",
        "config_dir": "~/.claude",
        "alias":      "claude-research",
        "keywords": [
            "research", "paper", "arxiv", "what is", "explain", "learn about",
            "summarize", "overview", "how does", "tell me about", "paper-dive",
            "what's new", "recent papers", "state of the art", "literature",
            "investigate", "read this",
        ],
        "why": "Research synthesis — skill routing + ChromaDB retrieval. "
               "Haiku sufficient for synthesis at ~60% Sonnet cost.",
        "savings": "~60% vs MARVIN + Sonnet",
    },
    "coding": {
        "profile":    "lean",
        "model":      None,
        "config_dir": "~/.claude-lean",
        "alias":      "claude-code",
        "keywords": [
            "fix", "implement", "write a", "add a", "refactor", "run tests",
            "debug", "error", "function", "class", "script", "PR", "commit",
            "lint", "format", "deploy", "migrate", "make it work", "failing",
            "broken", "bug", "unittest", "test suite", "edit this file",
        ],
        "why": "Mechanical coding — no recall overhead. "
               "Lean saves 9–10% tokens vs MARVIN (bench Runs 2–6).",
        "savings": "~9% vs MARVIN + Sonnet",
    },
    "architecture": {
        "profile":    "marvin",
        "model":      None,
        "config_dir": "~/.claude",
        "alias":      "claude-arch",
        "keywords": [
            "design", "architect", "plan", "should we", "compare", "evaluate",
            "review", "analyze", "strategy", "approach", "trade-off", "decision",
            "structure", "roadmap", "how should we", "best way", "pros and cons",
            "recommendation", "consider", "what do you think",
        ],
        "why": "Architecture/design — full context and Sonnet reasoning required. "
               "No model optimization (cost of being wrong is too high).",
        "savings": "baseline (optimal for this task type)",
    },
}

DEFAULT_INTENT = "architecture"
MIN_HITS = 2  # require at least 2 keyword matches to override the default


# ── classifier ────────────────────────────────────────────────────────────────

def classify(description: str) -> tuple[str, int]:
    """Return (intent, hit_count). Falls back to DEFAULT_INTENT when hits < MIN_HITS."""
    desc = description.lower()
    scores = {intent: 0 for intent in INTENTS}
    for intent, cfg in INTENTS.items():
        for kw in cfg["keywords"]:
            if kw in desc:
                scores[intent] += 1
    best = max(scores, key=scores.get)
    hits = scores[best]
    return (best if hits >= MIN_HITS else DEFAULT_INTENT), hits


# ── display ───────────────────────────────────────────────────────────────────

def _launch_cmd(intent: str) -> str:
    cfg = INTENTS[intent]
    config = os.path.expanduser(cfg["config_dir"])
    parts = [f"CLAUDE_CONFIG_DIR={config}", "claude"]
    if cfg["model"]:
        parts += ["--model", cfg["model"]]
    return " ".join(parts)


def print_routing(intent: str, description: str, hits: int) -> None:
    cfg = INTENTS[intent]
    reason = "(explicit)" if not description else f"({hits} keyword hits)"
    model_str = cfg["model"] or "default (Sonnet)"
    print(f"""
intent:    {intent}  {reason}
profile:   {cfg['profile']}
model:     {model_str}
savings:   {cfg['savings']}
why:       {cfg['why']}

launch:    {_launch_cmd(intent)}
alias:     {cfg['alias']}
""".rstrip())


def print_table() -> None:
    rows = [("INTENT", "PROFILE", "MODEL", "ALIAS", "SAVINGS")]
    for intent, cfg in INTENTS.items():
        rows.append((
            intent,
            cfg["profile"],
            cfg["model"] or "default",
            cfg["alias"],
            cfg["savings"],
        ))
    widths = [max(len(r[i]) for r in rows) for i in range(5)]
    sep = "  ".join("-" * w for w in widths)
    for i, row in enumerate(rows):
        print("  ".join(f[i].ljust(widths[i]) for i, f in enumerate(zip(widths, row))))  # noqa
        if i == 0:
            print(sep)
    print("\nKeyword threshold:", MIN_HITS, "hits required to override default.")


def print_table_proper() -> None:
    rows = [("INTENT", "PROFILE", "MODEL", "ALIAS", "SAVINGS")]
    for intent, cfg in INTENTS.items():
        rows.append((
            intent,
            cfg["profile"],
            cfg["model"] or "default",
            cfg["alias"],
            cfg["savings"],
        ))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    sep = "  ".join("-" * w for w in widths)
    for idx, row in enumerate(rows):
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
        if idx == 0:
            print(sep)
    print(f"\nKeyword threshold: {MIN_HITS} hits required to override default ('{DEFAULT_INTENT}').")


def print_aliases() -> None:
    """Print shell alias definitions. Append to ~/.zshrc or source directly."""
    home = Path.home()
    script_path = Path(__file__).resolve()
    venv_python = home / ".agents" / "venv" / "bin" / "python"
    print("# MARVIN profile routing aliases — paste into ~/.zshrc or run: source <(route.py --aliases)")
    for intent, cfg in INTENTS.items():
        config = str(home / cfg["config_dir"].lstrip("~/"))
        parts = [f'CLAUDE_CONFIG_DIR="{config}"', "claude"]
        if cfg["model"]:
            parts += ["--model", cfg["model"]]
        print(f"alias {cfg['alias']}='{' '.join(parts)}'")
    print(f"alias route='{venv_python} {script_path}'")


# ── launcher ──────────────────────────────────────────────────────────────────

def launch(intent: str) -> None:
    """Replace this process with claude using the routed config + model."""
    cfg = INTENTS[intent]
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(cfg["config_dir"])
    # strip inherited session vars so the child starts clean
    for k in list(env):
        if k.startswith("CLAUDE_CODE_") or k in ("CLAUDECODE", "CLAUDE_EFFORT"):
            env.pop(k)
    cmd = ["claude"]
    if cfg["model"]:
        cmd += ["--model", cfg["model"]]
    print(f"→ {' '.join(cmd)}  (CLAUDE_CONFIG_DIR={env['CLAUDE_CONFIG_DIR']})\n", flush=True)
    os.execvpe("claude", cmd, env)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Classify a task and route to the optimal Claude profile + model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("task", nargs="?", default="", help="task description to classify")
    ap.add_argument("--launch", action="store_true", help="exec claude with the routed settings")
    ap.add_argument("--table", action="store_true", help="print the full routing table and exit")
    ap.add_argument("--aliases", action="store_true", help="print shell alias definitions and exit")
    # explicit intent overrides
    for intent in INTENTS:
        ap.add_argument(f"--{intent}", action="store_true", help=f"force {intent} routing")
    args = ap.parse_args()

    if args.table:
        print_table_proper()
        return

    if args.aliases:
        print_aliases()
        return

    # explicit intent flag overrides classifier
    forced = next((i for i in INTENTS if getattr(args, i, False)), None)
    if forced:
        intent, hits = forced, -1
    elif args.task:
        intent, hits = classify(args.task)
    else:
        # no task given and no explicit flag — just show the table
        print_table_proper()
        return

    print_routing(intent, args.task, hits)

    if args.launch:
        launch(intent)


if __name__ == "__main__":
    main()
