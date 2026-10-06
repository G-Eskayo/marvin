#!/usr/bin/env python3
"""
generate.py — regenerate the MARVIN brain-map HTML from live + hand-maintained data.

Live (always current):
  - ~/.claude/manifest.json                — the skill list and calls: edges
  - ~/Library/LaunchAgents/com.marvin.*.plist — recurring cron agents (ADR 0018)
  - ~/.claude/settings.local.json (hooks)   — infrastructure hook wiring (ADR 0019)
  - ~/.claude/marvin-network.json (devices) — registered cross-machine devices (ADR 0020)
  - ~/.agents/dashboard/src/App.jsx (TABS)  — the dashboard's tabs (ADR 0049)
  - ~/.claude/catalog/projects.*.json       — active and recent projects (ADR 0049)

Hand-maintained: ./enrichment.json — prose descriptions, non-skill nodes (ChromaDB
collections, exo/task-dispatch), category grouping, and optional overrides for any
of the live-derived node types above (skill_desc_overrides, agent_overrides,
hook_overrides). A missing override for a live-discovered id still produces a node —
existence is never gated on a hand-authored entry, only its polish is (a skill with
no skill_categories entry goes under "Other" rather than being dropped).

Run whenever the skill set changes materially (also chained automatically by
rebuild-manifest.py's PostToolUse hook):
    ~/.agents/venv/bin/python ~/.agents/brain-map/generate.py

Writes ~/.agents/brain-map/index.html — a complete, self-contained file (no CDN
deps, matching the Artifact sandbox's CSP) suitable for opening directly, or
pointing a tool like Plash at for a live desktop wallpaper.
"""
from __future__ import annotations
import json
import plistlib
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
MANIFEST_PATH = Path.home() / ".claude" / "manifest.json"
ENRICHMENT_PATH = HERE / "enrichment.json"
TEMPLATE_PATH = HERE / "template.html"
OUTPUT_PATH = HERE / "index.html"
# Plain-JSON sidecar of the same data embedded in index.html — DesktopLive
# reads this instead of scraping JS out of the HTML, since Swift has a real
# JSON decoder and regex-extracting a <script> block is fragile by nature.
TREE_DATA_PATH = HERE / "tree-data.json"

SKILLS_DIR = Path.home() / ".agents" / "skills"
LAUNCHD_DIR = Path.home() / "Library" / "LaunchAgents"
SETTINGS_LOCAL_PATH = Path.home() / ".claude" / "settings.local.json"
NETWORK_PATH = Path.home() / ".claude" / "marvin-network.json"
DASHBOARD_APP_PATH = Path.home() / ".agents" / "dashboard" / "src" / "App.jsx"
CATALOG_DIR = Path.home() / ".claude" / "catalog"


def first_sentence(desc: str) -> str:
    """Graph tooltips are small — keep the first clause of a longer description,
    not the whole multi-sentence original. Collapses internal whitespace first:
    a docstring's first sentence often line-wraps in the source, and a tooltip
    is a single line, not a paragraph."""
    collapsed = re.sub(r"\s+", " ", desc.strip())
    return re.split(r"(?<=[.])\s+", collapsed, maxsplit=1)[0]


def read_skill_description(skill_name: str) -> str:
    """Pull the description straight from the skill's own SKILL.md frontmatter
    — this is what makes descriptions 'live' rather than a second copy that
    drifts from the real one."""
    path = SKILLS_DIR / skill_name / "SKILL.md"
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return ""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end == -1:
        return ""
    fm = text[3:end]
    m = re.search(r"^description:\s*(.+)$", fm, re.MULTILINE)
    if not m:
        return ""
    return first_sentence(m.group(1).strip())


def read_docstring_first_sentence(script_path: Path) -> str:
    """Fallback description for an auto-discovered agent/hook node with no
    hand-authored override: the first sentence of the script's own module
    docstring. Rougher than a curated override, but means a brand-new cron
    job or hook still shows up with SOME description on day one instead of
    silently missing from the graph until someone gets around to it."""
    try:
        text = script_path.read_text(encoding="utf-8")
    except Exception:
        return ""
    # [^\n]* (not .*) for the shebang line specifically — under re.DOTALL,
    # a greedy .* there would span newlines too and backtrack from the END
    # of the file looking for the nearest """, landing on some unrelated
    # triple-quoted string deep in the script instead of stopping at the
    # actual module docstring right after the shebang.
    m = re.match(r'^\s*(?:#![^\n]*\n)?\s*"""(.*?)(?:"""|\Z)', text, re.DOTALL)
    if not m:
        return ""
    return first_sentence(m.group(1).strip())


def build_skill_node(name: str, category: str, enrichment: dict) -> dict:
    override = enrichment["skill_desc_overrides"].get(name)
    desc = override if override else read_skill_description(name)
    return {"id": name, "cat": category, "desc": desc, "children": [], "expandable": False, "expanded": True}


def normalize_structural(node: dict) -> dict:
    """Fill in expandable/expanded defaults on hand-authored structural nodes
    from enrichment.json, recursively."""
    out = {
        "id": node["id"],
        "cat": node["cat"],
        "desc": node.get("desc", ""),
        "expandable": bool(node.get("expandable", False)),
        "children": [normalize_structural(c) for c in node.get("children", [])],
    }
    out["expanded"] = not out["expandable"]
    return out


# ── ADR 0018: Autonomous Agents live from launchd ───────────────────────────

def load_plist(path: Path) -> dict | None:
    """Parse a launchd plist the way launchd does. Python's parser rejects some
    files launchd accepts (e.g. "--" inside an XML comment), which used to drop
    that agent from the map with no warning — fall back to plutil, and say so
    if even that fails."""
    try:
        with path.open("rb") as f:
            return plistlib.load(f)
    except Exception:
        pass
    try:
        out = subprocess.run(["/usr/bin/plutil", "-convert", "xml1", "-o", "-", str(path)],
                             capture_output=True, check=True, timeout=10).stdout
        return plistlib.loads(out)
    except Exception as exc:
        print(f"WARNING: could not read {path.name} — left off the map: {exc}", file=sys.stderr)
        return None


def describe_schedule(data: dict) -> str | None:
    """How often a launchd job repeats, or None if it doesn't (a one-off task
    or an always-on service). See brain-map/CONTEXT.md, "Recurring agent"."""
    interval = data.get("StartInterval")
    if isinstance(interval, int) and interval > 0:
        if interval % 3600 == 0:
            return f"every {interval // 3600} h"
        return f"every {max(1, interval // 60)} min"
    cal = data.get("StartCalendarInterval")
    entries = cal if isinstance(cal, list) else [cal] if isinstance(cal, dict) else []
    # launchd sets Day/Month/Year together only for one specific date — a one-off.
    entries = [e for e in entries if isinstance(e, dict) and not any(k in e for k in ("Day", "Month", "Year"))]
    if not entries:
        return None
    first = entries[0]
    return f"{first.get('Hour', 0):02d}:{first.get('Minute', 0):02d}"


def discover_recurring_agents() -> list[dict]:
    """Every com.marvin.*.plist that repeats on a schedule — a daily/weekly
    calendar time or a fixed interval. One-off tasks and always-on services
    (RunAtLoad/KeepAlive with no schedule, e.g. desktoplive) are excluded."""
    agents = []
    for plist_path in sorted(LAUNCHD_DIR.glob("com.marvin.*.plist")):
        data = load_plist(plist_path)
        if data is None:
            continue
        schedule = describe_schedule(data)
        if schedule is None:
            continue
        agent_id = data.get("Label", "").removeprefix("com.marvin.")
        if not agent_id:
            continue
        program_args = data.get("ProgramArguments") or []
        script_path = Path(program_args[-1]) if program_args else None
        fallback_desc = read_docstring_first_sentence(script_path) if script_path else ""
        agents.append({"id": agent_id, "schedule": schedule, "fallback_desc": fallback_desc})
    return agents


def build_agent_children(enrichment: dict) -> list[dict]:
    overrides = enrichment.get("agent_overrides", {})
    children = []
    for agent in discover_recurring_agents():
        override = overrides.get(agent["id"])
        if override:
            children.append(normalize_structural(override))
            continue
        desc = f"Cron {agent['schedule']}"
        if agent["fallback_desc"]:
            desc += f" — {agent['fallback_desc']}"
        children.append({
            "id": agent["id"], "cat": "agents", "desc": desc,
            "expandable": False, "expanded": True, "children": [],
        })
    return children


# ── ADR 0019: Infrastructure hooks live from settings.local.json ───────────

def discover_hooks() -> list[dict]:
    """Every hook command wired into settings.local.json's `hooks` key,
    across all event types (PostToolUse today, but not hardcoded to it).
    A script referenced by more than one hook entry is deduplicated by id."""
    try:
        data = json.loads(SETTINGS_LOCAL_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    hooks_cfg = data.get("hooks", {})
    seen: dict[str, dict] = {}
    for event_type, entries in hooks_cfg.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            matcher = entry.get("matcher", "")
            trigger = f"{event_type}: {matcher}" if matcher else event_type
            for h in entry.get("hooks", []):
                if h.get("type") != "command":
                    continue
                cmd = h.get("command", "")
                parts = cmd.split()
                if not parts:
                    continue
                script_path = Path(parts[-1])
                hook_id = script_path.name
                if hook_id in seen:
                    continue
                fallback_desc = read_docstring_first_sentence(script_path)
                seen[hook_id] = {"id": hook_id, "trigger": trigger, "fallback_desc": fallback_desc}
    return sorted(seen.values(), key=lambda h: h["id"])


def build_hook_children(enrichment: dict) -> list[dict]:
    overrides = enrichment.get("hook_overrides", {})
    children = []
    for hook in discover_hooks():
        override = overrides.get(hook["id"])
        if override:
            children.append(normalize_structural(override))
            continue
        desc = f"Hook ({hook['trigger']})"
        if hook["fallback_desc"]:
            desc += f" — {hook['fallback_desc']}"
        children.append({
            "id": hook["id"], "cat": "infra", "desc": desc,
            "expandable": False, "expanded": True, "children": [],
        })
    return children


# ── ADR 0020: Cross-Machine Network devices live from marvin-network.json ──

def discover_devices() -> list[dict]:
    try:
        data = json.loads(NETWORK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    devices = data.get("devices", {})
    out = []
    for device_id, info in sorted(devices.items()):
        kind = info.get("kind", "device")
        added = info.get("added", "")
        host = info.get("tailscale_hostname", "")
        desc = f"{kind} — added {added}" + (f" — {host}" if host else "")
        out.append({"id": device_id, "desc": desc})
    return out


def build_device_children(enrichment: dict) -> list[dict]:
    children = []
    for device in discover_devices():
        children.append({
            "id": device["id"], "cat": "cross-machine", "desc": device["desc"],
            "expandable": False, "expanded": True, "children": [],
        })
    extra = enrichment.get("cross_machine_network", {}).get("extra_nodes", [])
    children.extend(normalize_structural(n) for n in extra)
    return children


# ── ADR 0049: dashboard tabs and projects, live ─────────────────────────────

def discover_dashboard_tabs() -> list[dict]:
    """The dashboard's tabs, read from the TABS list in its App.jsx."""
    try:
        src = DASHBOARD_APP_PATH.read_text(encoding="utf-8")
    except OSError:
        return []
    block = re.search(r"const TABS\s*=\s*\[(.*?)\]", src, re.S)
    if not block:
        return []
    labels = re.findall(r"label:\s*['\"]([^'\"]+)['\"]", block.group(1))
    return [{"id": f"{label} tab", "desc": f"Dashboard tab: {label}"} for label in labels]


def build_dashboard_trunk() -> dict:
    tabs = [{"id": t["id"], "cat": "dashboard", "desc": t["desc"],
             "expandable": False, "expanded": True, "children": []} for t in discover_dashboard_tabs()]
    return {"id": "Dashboard", "cat": "dashboard",
            "desc": "The desktop app for watching and steering MARVIN",
            "expandable": False, "expanded": True, "children": tabs}


def discover_projects() -> list[dict]:
    """Active and recent projects from the newest machine catalog. marvin itself
    is the root, not a project node; dormant projects are left off."""
    catalogs = sorted(CATALOG_DIR.glob("projects.*.json"), key=lambda p: p.stat().st_mtime) if CATALOG_DIR.is_dir() else []
    if not catalogs:
        return []
    try:
        projects = json.loads(catalogs[-1].read_text(encoding="utf-8")).get("projects", [])
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for p in projects:
        if p.get("status") not in ("active", "recent") or p.get("id") == "marvin":
            continue
        out.append({"id": p.get("name") or p["id"], "desc": first_sentence(p.get("description") or ""),
                    "visibility": p.get("visibility") or "LOCAL", "kind": p.get("kind", "")})
    return sorted(out, key=lambda p: p["id"].lower())


def build_projects_trunk() -> dict:
    children = [{"id": p["id"], "cat": "projects", "desc": p["desc"], "visibility": p["visibility"],
                 "expandable": False, "expanded": True, "children": []} for p in discover_projects()]
    return {"id": "Projects", "cat": "projects",
            "desc": f"{len(children)} active or recent projects MARVIN works on",
            "expandable": False, "expanded": True, "children": children}


def build_tree(manifest: dict, enrichment: dict) -> dict:
    skills = {e["name"]: e for e in manifest["index"]}

    # The three live-derived trunks keep an empty <children> placeholder in
    # enrichment.json's structural list (so trunk-level desc/cat still comes
    # from one place) — filled in here from their respective live sources
    # merged with any hand-authored override, per ADRs 0018/0019/0020.
    live_children_by_trunk_id = {
        "Autonomous Agents": build_agent_children(enrichment),
        "Infrastructure": build_hook_children(enrichment),
        "Cross-Machine Network": build_device_children(enrichment),
    }

    # Some manifest.json skills are deliberately represented as a richer
    # node elsewhere instead (e.g. research-colony has its own SKILL.md but
    # is shown as an Autonomous Agents node with its 3-stage pipeline,
    # since it's also a recurring cron job) — not a gap, don't warn. Collect
    # ids from the live trunk children (computed above) as well as the
    # purely hand-authored structural nodes (Memory's ChromaDB/hook nodes).
    structural_ids: set = set()
    for n in enrichment["structural"]:
        collect_ids(n, structural_ids)
    for children in live_children_by_trunk_id.values():
        for c in children:
            collect_ids(c, structural_ids)

    by_category: dict[str, list[dict]] = {c: [] for c in enrichment["category_order"]}
    uncategorized = []
    for name in sorted(skills):
        if name in structural_ids:
            continue
        cat = enrichment["skill_categories"].get(name)
        if cat is None:
            uncategorized.append(name)
            cat = "other"
        by_category.setdefault(cat, []).append(build_skill_node(name, cat, enrichment))

    if uncategorized:
        print(f"NOTE: {len(uncategorized)} skill(s) have no category in enrichment.json's "
              f"skill_categories — shown under Other: {uncategorized}", file=sys.stderr)

    skills_trunk_children = []
    labels = {**enrichment["category_labels"], "other": "Other"}
    for cat in enrichment["category_order"] + (["other"] if by_category.get("other") else []):
        skills_trunk_children.append({
            "id": labels[cat], "cat": cat, "desc": "",
            "expandable": False, "expanded": True,
            "children": by_category[cat],
        })

    skills_trunk = {
        "id": "Skills", "cat": "skills-trunk",
        "desc": f"{len(skills)} {enrichment['skills_trunk_desc']}",
        "expandable": False, "expanded": True,
        "children": skills_trunk_children,
    }

    structural = [normalize_structural(n) for n in enrichment["structural"]]

    for node in structural:
        if node["id"] in live_children_by_trunk_id:
            node["children"] = live_children_by_trunk_id[node["id"]]

    root = {
        "id": enrichment["root"]["id"], "cat": "root", "desc": enrichment["root"]["desc"],
        "expandable": False, "expanded": True,
        "children": [structural[0], skills_trunk] + structural[1:] + [build_dashboard_trunk(), build_projects_trunk()],
    }
    return root


def build_synapses(manifest: dict, enrichment: dict) -> list[dict]:
    out = []
    labels = enrichment.get("synapse_labels", {})
    fallback = enrichment.get("synapse_label_fallback", "declared calls: dependency")
    for entry in manifest["index"]:
        a = entry["name"]
        for b in entry.get("calls", []):
            key = f"{a}->{b}"
            out.append({"a": a, "b": b, "label": labels.get(key, fallback), "type": "calls"})
    out.extend(enrichment.get("extra_synapses", []))
    return out


def collect_ids(node: dict, out: set) -> None:
    out.add(node["id"])
    for c in node.get("children", []):
        collect_ids(c, out)


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    enrichment = json.loads(ENRICHMENT_PATH.read_text(encoding="utf-8"))

    tree = build_tree(manifest, enrichment)
    synapses = build_synapses(manifest, enrichment)

    known_ids = set()
    collect_ids(tree, known_ids)
    dropped = [s for s in synapses if s["a"] not in known_ids or s["b"] not in known_ids]
    synapses = [s for s in synapses if s["a"] in known_ids and s["b"] in known_ids]
    if dropped:
        print(f"WARNING: {len(dropped)} synapse(s) reference a node not in the tree — dropped: "
              f"{[(s['a'], s['b']) for s in dropped]}", file=sys.stderr)

    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    # ensure_ascii=False keeps arrows etc. as real UTF-8 in the output, not
    # \uXXXX escapes; a lambda repl (not a string) sidesteps re.sub trying to
    # interpret any backslash sequence in the JSON as a regex backreference —
    # both bit on the first run (a literal "→" tripped re.sub's escape parser).
    tree_js = "var tree = " + json.dumps(tree, indent=2, ensure_ascii=False) + ";"
    synapses_js = "var synapses = " + json.dumps(synapses, indent=2, ensure_ascii=False) + ";"

    template = re.sub(
        r"/\*__TREE_START__\*/.*?/\*__TREE_END__\*/",
        lambda _m: "/*__TREE_START__*/\n  " + tree_js + "\n  /*__TREE_END__*/",
        template, flags=re.DOTALL,
    )
    template = re.sub(
        r"/\*__SYNAPSES_START__\*/.*?/\*__SYNAPSES_END__\*/",
        lambda _m: "/*__SYNAPSES_START__*/\n  " + synapses_js + "\n  /*__SYNAPSES_END__*/",
        template, flags=re.DOTALL,
    )

    OUTPUT_PATH.write_text(template, encoding="utf-8")
    TREE_DATA_PATH.write_text(
        json.dumps({"tree": tree, "synapses": synapses}, ensure_ascii=False), encoding="utf-8"
    )
    n_skills = len(manifest["index"])
    n_agents = len(discover_recurring_agents())
    n_hooks = len(discover_hooks())
    n_devices = len(discover_devices())
    print(f"Generated {OUTPUT_PATH} — {n_skills} skills, {n_agents} agents, "
          f"{n_hooks} hooks, {n_devices} devices, {len(synapses)} synapses")


if __name__ == "__main__":
    main()
