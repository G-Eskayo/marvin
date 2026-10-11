"""Additions to portfolio_content.py to include research section checking.

This shows the changes needed to integrate portfolio_research.py checking into
the evaluate() and findings_for_evaluation() functions.
"""

# Add to portfolio_content.py after the existing imports:
# import portfolio_research as pr  # (at module level)

# Add this function after check_has_figure:

def check_research_section(content: dict) -> list[dict]:
    """Check whether a content object has a research section.

    If the project has an evidence log (docs/research/evidence-log.md), a research
    section should be present in the content. This is an info-level check, not a
    hard requirement, since not all projects will have supporting research.
    """
    sections = content.get("sections", [])
    has_research = any(s.get("role") == "research" for s in sections)

    if not has_research:
        return [{
            "rule": "research-section-missing",
            "severity": "info",
            "detail": "no 'research' section; run portfolio_research.py to auto-generate from an evidence log"
        }]

    return []


# Update evaluate() to call check_research_section:
# In the evaluate() function, update this line (around line 156):
#
#   findings = check_copy(html) + check_media_markup(html) + check_has_figure(c)
#
# Change to:
#
#   findings = check_copy(html) + check_media_markup(html) + check_has_figure(c) + check_research_section(c)


# Update findings_for_evaluation() if needed:
# The existing code already iterates over findings and includes them, so no change
# is needed there. The check_research_section findings will automatically be included.
