"""
Model-scope parsing and matching for skills.

Defines per-skill constraints on which Claude models can run them.
Syntax:
  - 'all' or omitted: no restriction (default)
  - 'haiku,sonnet,opus': explicit list
  - 'sonnet+': tier and above
"""

TIER_ORDER = {"haiku": 0, "sonnet": 1, "opus": 2}
TIER_NAMES = set(TIER_ORDER.keys())


def parse_scope(raw: str) -> set[str]:
    """Parse model-scope string into a normalized set of tier names.

    Args:
        raw: raw scope string from frontmatter (e.g., "haiku,sonnet", "sonnet+", "all")

    Returns:
        Set of normalized tier names, or empty set for "all"

    Behavior on invalid/unknown tiers: returns empty set (fail open, allow on any tier).
    Callers should handle empty set as "no restriction" when deciding behavior.
    """
    if not raw or raw.strip().lower() == "all":
        return set()

    raw = raw.strip().lower()

    if "+" in raw:
        parts = raw.split("+")
        if len(parts) != 2 or parts[1] != "":
            return set()
        tier = parts[0].strip()
        if tier not in TIER_ORDER:
            return set()
        min_tier = TIER_ORDER[tier]
        return {t for t, idx in TIER_ORDER.items() if idx >= min_tier}

    tiers = {t.strip() for t in raw.split(",")}
    valid = tiers & TIER_NAMES
    if not valid:
        return set()
    return valid


def is_allowed(scope: str, tier: str) -> bool:
    """Check if a given model tier is allowed by scope.

    Args:
        scope: parsed scope string (from frontmatter model-scope field)
        tier: model tier name ('haiku', 'sonnet', 'opus')

    Returns:
        True if tier is allowed (or scope is "all"/empty), False otherwise.
        Unknown tiers return True (fail open).
    """
    if tier not in TIER_ORDER:
        return True

    parsed = parse_scope(scope)
    if not parsed:
        return True

    return tier in parsed
