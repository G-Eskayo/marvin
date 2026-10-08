#!/usr/bin/env python3
"""Plain-words hover lines (#189, Gil 2026-10-08: "explained to a kindergartner in concise terms what each node is")."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import export_snapshot  # noqa: E402
import generate  # noqa: E402


def tree():
    return {"id": "MARVIN", "children": [
        {"id": "ticket-pipeline", "cat": "agents", "children": []},
        {"id": "Projects", "cat": "projects", "children": [
            {"id": "secret-app", "cat": "projects", "visibility": "PRIVATE", "children": []},
            {"id": "open-app", "cat": "projects", "visibility": "PUBLIC", "children": []},
        ]},
    ]}


def test_attach_plain_sets_it_and_names_every_node_without_one():
    t = tree()
    missing = generate.attach_plain(t, {"MARVIN": "Gil's helper brain.", "ticket-pipeline": "Builds the next ticket.",
                                        "secret-app": "A secret.", "gone-node": "unused"})
    assert t["plain"] == "Gil's helper brain."
    assert t["children"][0]["plain"] == "Builds the next ticket."
    assert sorted(missing) == ["Projects", "open-app"]


def test_enrichment_plain_lines_are_short():
    import json
    plain = json.loads(generate.ENRICHMENT_PATH.read_text())["plain"]
    too_long = {k: v for k, v in plain.items() if len(v.split()) > 22}
    assert too_long == {}, "keep them kindergarten-short"


def test_locked_projects_lose_their_plain_line_on_the_website():
    t = tree()
    generate.attach_plain(t, {"secret-app": "A secret.", "open-app": "An open app."})
    export_snapshot.lock_private_projects(t)
    secret, open_ = t["children"][1]["children"]
    assert "plain" not in secret and secret["locked"]
    assert open_["plain"] == "An open app."
