#!/usr/bin/env python3
"""The portfolio's site rules, in ONE place.

What a project, a page, a button or an image must be -- as data, so a program can apply them and check them. The
add-project pipeline, the template renderer, the image tools and the evaluation all read this module; none of them
holds its own copy. Gil's overrides live in templates/design-rules.json in the portfolio repo (edited in the dashboard's
Guide & rules tab) and are merged over these defaults one level deep.

  categories     category name -> URL prefix (also the slug of that category's hub page)
  project_spec   what a person must supply for a new project, and the slug shape
  project_page   which action buttons a project page may have, in order
  images         the hero and card-thumbnail sizes and how different two projects' images must be
  card, footer, github_button, viewports, hub_pages, tolerance_px   what the evaluation measures
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

PROJECT = Path.home() / "Documents" / "Projects" / "portfolio-website-updater"
RULES_PATH = PROJECT / "templates" / "design-rules.json"

DEFAULT_RULES = {
    "tolerance_px": 2,
    "categories": {"AI & Machine Learning": "ai-projects", "Cybersecurity": "cybersecurity-projects", "Software Engineering": "software-engineering"},
    "project_spec": {
        "required": ["title", "slug", "category", "subtitle", "description", "body_html", "hero_image_url", "thumbnail"],
        "slug_pattern": "[a-z0-9][a-z0-9-]*",
    },
    "project_page": {"action_order": ["button-github", "button-download"]},
    "images": {"thumb_size": [800, 500], "hero_size": [2200, 600], "min_distance": 24},
    "footer": {"expected_cards": 2},
    # one card design everywhere: the photo frame height and how far the card overlays the photo (px); used only until
    # the project-card element has been captured, after which the element is the reference
    "card": {"image_height": 240, "overlap": 56},
    "github_button": {"text": "View on GitHub", "classes": ["btn", "btn-default"], "owner": "G-Eskayo"},
    "viewports": [1440, 1100, 390],
    "hub_pages": ["/ai-projects/", "/cybersecurity-projects/", "/software-engineering/", "/all-projects/"],
}


def load_rules(path: Path = RULES_PATH) -> dict:
    """DEFAULT_RULES with the file's values merged over them (one level deep)."""
    rules = copy.deepcopy(DEFAULT_RULES)
    try:
        override = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return rules
    if not isinstance(override, dict):
        return rules
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(rules.get(key), dict):
            rules[key].update(value)
        else:
            rules[key] = value
    return rules


def categories(path: Path = RULES_PATH) -> dict[str, str]:
    return load_rules(path)["categories"]


if __name__ == "__main__":
    print(json.dumps(load_rules(), indent=2))
