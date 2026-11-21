"""Test that triage-labels.md documents the PRD exception."""
import re
from pathlib import Path


def test_triage_labels_documents_prd_no_triage_role_label():
    """Verify that triage-labels.md Consumer rules state parent PRDs carry no triage-role label."""
    triage_path = Path(__file__).resolve().parents[1] / "docs" / "agents" / "triage-labels.md"
    content = triage_path.read_text()

    # Find the Consumer rules section
    consumer_match = re.search(r'^##\s+Consumer rules\s*$(.*?)(?=^##|\Z)', content,
                               re.MULTILINE | re.DOTALL)
    assert consumer_match, "Could not find 'Consumer rules' section in triage-labels.md"

    consumer_text = consumer_match.group(1)

    # Extract bullet points from Consumer rules
    bullets = re.findall(r'^-\s+(.+?)(?=\n-\s|\Z)', consumer_text, re.MULTILINE | re.DOTALL)
    assert len(bullets) > 0, "Consumer rules should have bullet points"

    # Find the bullet about parent PRDs and triage-role labels
    # It should mention:
    # 1. parent PRD or title with PRD: prefix
    # 2. carry no triage-role label or similar wording
    prd_rule_found = False
    for bullet in bullets:
        has_prd_mention = "PRD:" in bullet or ("prd" in bullet.lower() and "title" in bullet.lower())
        has_no_triage_mention = any(phrase in bullet.lower() for phrase in [
            "carry no triage-role label",
            "carries no triage-role label",
            "no triage-role label",
            "skip",  # "triage skips it"
        ])

        if has_prd_mention and has_no_triage_mention:
            prd_rule_found = True
            break

    assert prd_rule_found, \
        "Consumer rules should have a bullet explicitly stating parent PRDs (title PRD: ...) carry no triage-role label"
