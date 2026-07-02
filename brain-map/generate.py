#!/usr/bin/env python3
"""
generate.py — regenerate the MARVIN brain-map HTML from live + hand-maintained data.

Live (always current): ~/.claude/manifest.json — the skill list and calls: edges.
Hand-maintained: ./enrichment.json — prose descriptions, non-skill nodes (ChromaDB
collections, hook scripts, cron agents), category grouping, and the hook/cron/
undeclared synapses manifest.json doesn't capture.

Run whenever the skill set changes materially:
    ~/.agents/venv/bin/python ~/.agents/brain-map/generate.py

Writes ~/.agents/brain-map/index.html — a complete, self-contained file (no CDN
deps, matching the Artifact sandbox's CSP) suitable for opening directly, or
pointing a tool like Plash at for a live desktop wallpaper.
"""
from __future__ import annotations
import json
import re
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
    desc = m.group(1).strip()
    # Graph tooltips are small — keep the first clause, not the whole
    # multi-sentence frontmatter description.
    first_sentence = re.split(r"(?<=[.])\s+", desc, maxsplit=1)[0]
    return first_sentence


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


def build_tree(manifest: dict, enrichment: dict) -> dict:
    skills = {e["name"]: e for e in manifest["index"]}

    # Some manifest.json skills are deliberately represented as a richer
    # hand-authored structural node instead (e.g. research-colony gets its
    # 3-stage pipeline under Autonomous Agents) — not a gap, don't warn.
    structural_ids: set = set()
    for n in enrichment["structural"]:
        collect_ids(n, structural_ids)

    by_category: dict[str, list[dict]] = {c: [] for c in enrichment["category_order"]}
    uncategorized = []
    for name in sorted(skills):
        if name in structural_ids:
            continue
        cat = enrichment["skill_categories"].get(name)
        if cat is None:
            uncategorized.append(name)
            continue
        by_category[cat].append(build_skill_node(name, cat, enrichment))

    if uncategorized:
        print(f"WARNING: {len(uncategorized)} skill(s) in manifest.json have no category "
              f"in enrichment.json's skill_categories — omitted from the graph: {uncategorized}",
              file=sys.stderr)

    skills_trunk_children = []
    for cat in enrichment["category_order"]:
        skills_trunk_children.append({
            "id": enrichment["category_labels"][cat], "cat": cat, "desc": "",
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

    root = {
        "id": enrichment["root"]["id"], "cat": "root", "desc": enrichment["root"]["desc"],
        "expandable": False, "expanded": True,
        "children": [structural[0], skills_trunk] + structural[1:],
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
    print(f"Generated {OUTPUT_PATH} — {n_skills} skills, {len(synapses)} synapses")


if __name__ == "__main__":
    main()
