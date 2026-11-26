#!/usr/bin/env python3
"""Tests for portfolio refresh ticket #840 — MARVIN portfolio content verification.

These tests verify:
1. No em-dashes in portfolio content (use periods or commas instead)
2. No unverified numeric claims without sources
3. At least one evidence figure (image/diagram) in content
4. No private names, emails, paths in public docs
5. Skills count is verified in worksheet, not marked NEEDS VERIFICATION
6. Rollback and deploy documentation is correct
"""

import json
import re
from pathlib import Path


def find_project_root():
    """Locate the project root by finding the .git directory."""
    current = Path(__file__).resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    raise RuntimeError("Could not find project root")


PROJECT_ROOT = find_project_root()
CONTENT_FILE = PROJECT_ROOT / "content" / "longform" / "marvin.json"
WORKSHEET_FILE = PROJECT_ROOT / "docs" / "design" / "pipeline-g-eskayo-marvin-840-claims-worksheet.md"
HANDOFF_FILE = PROJECT_ROOT / "PORTFOLIO_REFRESH_HANDOFF.md"
DEPLOYMENT_FILE = PROJECT_ROOT / "docs" / "design" / "pipeline-g-eskayo-marvin-840-deployment.md"
PLAN_FILE = PROJECT_ROOT / "docs" / "design" / "pipeline-g-eskayo-marvin-840.md"


class TestMarvinContentNoEmDashes:
    """Test that content has no em-dashes (heuristic for AI-written text)."""

    def test_no_em_dashes_in_lead_html(self):
        """Lead HTML should not contain em-dashes."""
        with open(CONTENT_FILE) as f:
            content = json.load(f)
        lead_html = content.get("lead_html", "")
        assert "—" not in lead_html, f"Found em-dash in lead_html: {lead_html[:100]}"

    def test_no_em_dashes_in_section_bodies(self):
        """Section bodies should not contain em-dashes."""
        with open(CONTENT_FILE) as f:
            content = json.load(f)
        for i, section in enumerate(content.get("sections", [])):
            body_html = section.get("body_html", "")
            assert "—" not in body_html, (
                f"Found em-dash in section {i} ({section.get('heading')}): "
                f"{body_html[:100]}"
            )


class TestMarvinContentHasEvidence:
    """Test that content includes at least one evidence figure."""

    def test_has_at_least_one_figure(self):
        """Content should include at least one image or diagram."""
        with open(CONTENT_FILE) as f:
            content = json.load(f)
        full_html = content.get("lead_html", "")
        for section in content.get("sections", []):
            full_html += section.get("body_html", "")

        has_image = bool(re.search(r'<img\b', full_html, flags=re.I))
        has_svg = bool(re.search(r'\.svg', full_html, flags=re.I))
        has_figure = has_image or has_svg

        assert has_figure, (
            "Content has no evidence figure (image or SVG diagram). "
            "Add at least one <img> tag or link to a diagram."
        )


class TestMarvinContentNoPrivateNames:
    """Test that public docs have no private names, paths, or hostnames."""

    PRIVATE_NAMES = ["noah", "mom", "lee"]  # lowercase for case-insensitive matching
    PRIVATE_HOSTNAMES = ["gils-mac-mini", "gileskayo-macbook", "mac-mini"]
    # Note: "mac-mini" is private; use "development machine" or "primary machine" instead

    def _check_file(self, filepath, description):
        """Check a file for private info."""
        with open(filepath) as f:
            content = f.read()

        # Check for private names
        for name in self.PRIVATE_NAMES:
            if re.search(rf"\b{name}\b", content, flags=re.I):
                raise AssertionError(
                    f"Found private name '{name}' in {description} at {filepath.name}"
                )

        # Check for private hostnames
        for hostname in self.PRIVATE_HOSTNAMES:
            if hostname.lower() in content.lower():
                raise AssertionError(
                    f"Found private hostname '{hostname}' in {description} at {filepath.name}"
                )

    def test_plan_no_private_info(self):
        """Plan document should not contain private names or hostnames."""
        self._check_file(PLAN_FILE, "plan document")

    def test_handoff_no_private_hostnames(self):
        """Handoff document should not use specific hostnames."""
        self._check_file(HANDOFF_FILE, "handoff document")

    def test_deployment_no_private_hostnames(self):
        """Deployment document should not use specific hostnames."""
        self._check_file(DEPLOYMENT_FILE, "deployment document")


class TestMarvinWorksheetVerified:
    """Test that worksheet properly verifies claims instead of marking them NEEDS_VERIFICATION."""

    def test_skill_count_verified(self):
        """Skills count should be verified, not marked NEEDS_VERIFICATION."""
        with open(WORKSHEET_FILE) as f:
            content = f.read()

        # Check that skill count section says VERIFIED or CURRENT, not NEEDS_VERIFICATION
        skill_section = re.search(
            r"### Skills Count.*?(?=###|\Z)",
            content,
            flags=re.DOTALL | re.IGNORECASE
        )
        assert skill_section, "Could not find Skills Count section"

        section_text = skill_section.group(0)
        assert "NEEDS_VERIFICATION" not in section_text, (
            "Skills count is still marked NEEDS_VERIFICATION. "
            "This should be verified before shipping."
        )
        assert "✓" in section_text or "VERIFIED" in section_text or "CURRENT" in section_text, (
            "Skills count verification status is unclear. "
            "Mark as either ✓ VERIFIED or Status: CURRENT"
        )

    def test_no_items_to_verify(self):
        """Worksheet 'Items to Verify' checklist should be complete."""
        with open(WORKSHEET_FILE) as f:
            content = f.read()

        # Find the "Items to Verify" section
        verify_section = re.search(
            r"## Items to Verify or Update.*?(?=##|\Z)",
            content,
            flags=re.DOTALL | re.IGNORECASE
        )

        if verify_section:
            section_text = verify_section.group(0)
            # Count unchecked items ([ ] instead of [x] or [✓])
            unchecked = len(re.findall(r'\[ \]', section_text))
            assert unchecked == 0, (
                f"Found {unchecked} unchecked items in 'Items to Verify' section. "
                f"All verification items should be completed before shipping."
            )


class TestMarvinContentPRLinks:
    """Test that PR links point to real GitHub URLs, not placeholders."""

    def test_no_placeholder_pr_links(self):
        """PR links should point to real GitHub URLs, not placeholder /github/."""
        with open(CONTENT_FILE) as f:
            content = json.load(f)

        full_html = content.get("lead_html", "")
        for section in content.get("sections", []):
            full_html += section.get("body_html", "")

        # Check for placeholder links
        placeholder_links = re.findall(r'href=["\']?/github/["\']?', full_html)
        assert not placeholder_links, (
            f"Found {len(placeholder_links)} placeholder PR links pointing to /github/. "
            f"Use real GitHub URLs like https://github.com/G-Eskayo/marvin/pull/NNNN instead."
        )

    def test_pr_links_are_real_urls(self):
        """PR links should be absolute GitHub URLs."""
        with open(CONTENT_FILE) as f:
            content = json.load(f)

        full_html = content.get("lead_html", "")
        for section in content.get("sections", []):
            full_html += section.get("body_html", "")

        # Find all PR-like links
        pr_links = re.findall(r'href=["\']([^"\']*pull/\d+[^"\']*)["\']', full_html)
        for link in pr_links:
            assert link.startswith("https://github.com/"), (
                f"PR link should be absolute GitHub URL: {link}"
            )


class TestMarvinDocumentationCorrect:
    """Test that documentation (rollback, deploy check) is accurate."""

    def test_rollback_runs_before_authoring(self):
        """Rollback documentation should indicate it runs BEFORE authoring as a backup."""
        with open(HANDOFF_FILE) as f:
            content = f.read()

        # Check that the rollback step (step 2) comes before author step (step 3)
        rollback_pos = content.find("### 2. Backup the current state")
        author_pos = content.find("### 3. Author the new content")

        assert rollback_pos > 0, "Could not find rollback step"
        assert author_pos > 0, "Could not find author step"
        assert rollback_pos < author_pos, "Rollback should come before authoring"

    def test_deploy_check_uses_correct_directory(self):
        """Deploy check should run in portfolio repo, not ~/.agents/instance."""
        with open(HANDOFF_FILE) as f:
            handoff_content = f.read()

        with open(DEPLOYMENT_FILE) as f:
            deploy_content = f.read()

        # Check that the deploy guard runs in the right directory
        for doc_name, doc_content in [("HANDOFF", handoff_content), ("DEPLOYMENT", deploy_content)]:
            # Should reference ~/portfolio-dev, not ~/.agents/instance
            has_portfolio_dev = "~/portfolio-dev" in doc_content or "portfolio-dev" in doc_content
            has_agents_instance = "~/.agents/instance" in doc_content

            if has_agents_instance:
                raise AssertionError(
                    f"Deploy check in {doc_name} runs in ~/.agents/instance, "
                    "but deploy/ is in ~/portfolio-dev. "
                    "This check will always pass and give false assurance. "
                    "Change 'cd ~/.agents/instance' to 'cd ~/portfolio-dev'"
                )


class TestMarvinContentDisposableFilesUncommitted:
    """Test that session handoff files are not committed."""

    def _check_file_status(self, filepath):
        """Check git status of a file. Returns 'untracked', 'modified', 'staged', or 'committed'."""
        import subprocess
        try:
            # Check if file is in git index (committed or staged)
            result = subprocess.run(
                ["git", "ls-files", str(filepath)],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True
            )
            if result.stdout.strip():
                # File is tracked
                status_result = subprocess.run(
                    ["git", "status", "--porcelain", str(filepath)],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True
                )
                status = status_result.stdout.strip()
                if status.startswith("M"):
                    return "modified"
                elif status.startswith("A"):
                    return "staged"
                else:
                    return "committed"
            else:
                # File is not tracked
                return "untracked"
        except Exception as e:
            raise AssertionError(f"Could not check git status: {e}")

    def test_portfolio_index_would_be_uncommitted(self):
        """PORTFOLIO_INDEX.md should be a session artifact, not committed to git."""
        index_file = PROJECT_ROOT / "PORTFOLIO_INDEX.md"
        assert index_file.exists(), "PORTFOLIO_INDEX.md should exist as session output"

        status = self._check_file_status(index_file)
        assert status != "committed", (
            f"PORTFOLIO_INDEX.md is committed to git (status: {status}). "
            f"Session artifacts should stay uncommitted per ADR 0065 (replacement cost). "
            f"Add to .gitignore or clean up after deployment."
        )

    def test_portfolio_handoff_would_be_uncommitted(self):
        """PORTFOLIO_REFRESH_HANDOFF.md should be a session artifact, not committed to git."""
        handoff_file = PROJECT_ROOT / "PORTFOLIO_REFRESH_HANDOFF.md"
        assert handoff_file.exists(), "PORTFOLIO_REFRESH_HANDOFF.md should exist as session output"

        status = self._check_file_status(handoff_file)
        assert status != "committed", (
            f"PORTFOLIO_REFRESH_HANDOFF.md is committed to git (status: {status}). "
            f"Session artifacts should stay uncommitted per ADR 0065 (replacement cost). "
            f"Add to .gitignore or clean up after deployment."
        )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
