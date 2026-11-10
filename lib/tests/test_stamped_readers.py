"""Every reader of a stamped file goes through lib/stamped.py or dashboard/electron/main/stamped.js (marvin#1223), so
each one knows the copy's Mac and age. A raw read (read_text / readFileSync / json.load(open(...))) of one of these
files anywhere else fails here. Writers are fine; reading is the ratchet.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAMPED = ("health-status.json", "ticket-agent-proposals.json", "dispatch-state.json", "registry.json")
CODE = [*ROOT.glob("lib/*.py"), *ROOT.glob("skills/*/scripts/*.py"), *ROOT.glob("dashboard/electron/main/*.js"),
        *ROOT.glob("dashboard/webhook-server/*.js")]
HELPERS = {"lib/stamped.py", "dashboard/electron/main/stamped.js"}
# The readers the plan names (data-freshness §3): Health tab, boot verdict, morning brief, support, loops, the registry
# and proposal readers. Some read through a path passed in (boot_data's healthPath), which no grep can follow, so
# they are listed: each must use the helper.
READERS = ("dashboard/electron/main/health.js", "dashboard/electron/main/boot_data.js", "dashboard/electron/main/boards.js",
           "dashboard/electron/main/ticket_agents.js", "dashboard/electron/main/dispatch_status.js", "lib/morning_brief.py",
           "lib/support.py", "lib/loops.py", "lib/board_registry.py", "lib/ticket_agents.py", "lib/task_dispatch.py",
           "lib/pr_ticket_check.py")
RAW = re.compile(r"read_text\(|readFileSync\(|json\.load\(\s*open\(|\.open\(")


def offenders() -> list[str]:
    out = []
    for f in CODE:
        rel = str(f.relative_to(ROOT))
        if rel in HELPERS:
            continue
        text = f.read_text(errors="replace")
        if not any(name in text for name in STAMPED):
            continue
        consts = set()
        for line in text.splitlines():
            m = re.match(r"\s*(?:export\s+)?(?:const\s+)?([A-Z][A-Z0-9_]*)\s*=.*(" + "|".join(map(re.escape, STAMPED)) + ")", line)
            if m and (m.group(2) != "registry.json" or "boards" in line):
                consts.add(m.group(1))
        imports = re.search(r"^\s*(import stamped|from stamped import|import .*stamped.*|.*from '\./stamped\.js')", text, re.M)
        if consts and not imports:
            out.append(f"{rel}: defines {', '.join(sorted(consts))} but doesn't read it through stamped")
        for n, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith(("#", "//", "*")) or not RAW.search(line):
                continue
            if any(name in line for name in STAMPED if name != "registry.json") or \
                    ("registry.json" in line and "boards" in line) or \
                    any(re.search(rf"\b{c}\b", line) for c in consts):
                out.append(f"{rel}:{n}: {line.strip()[:120]}")
    return out


def test_every_named_reader_uses_the_helper():
    pat = re.compile(r"^\s*(import stamped|from stamped import)|from '\./(stamped|peer_copy)\.js'|import\s+stamped\b", re.M)
    missing = [r for r in READERS if not pat.search((ROOT / r).read_text())]
    assert missing == [], f"these readers don't read through stamped: {missing}"


def test_no_raw_reads_of_stamped_files():
    assert offenders() == [], "read these through stamped.read / readStamped:\n" + "\n".join(offenders())
