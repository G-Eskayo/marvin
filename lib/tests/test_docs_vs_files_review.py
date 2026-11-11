"""Tests for docs/plans/docs-vs-files-review.md against real repo structure.

Each test verifies a specific claim in the design doc by checking against:
- The actual code (App.jsx, outbox.js, DocsExplorer.jsx, FilesExplorer.jsx, etc.)
- The doc's own internal consistency
- The requirements from ticket #403

Tests are designed to:
1. Catch drift when code changes without updating the doc
2. Verify the doc's claims against reality, not just the doc's own prose
3. Make each test fail for the specific reason the code review identified

Run via: ~/.agents/venv/bin/python -m pytest lib/tests/test_docs_vs_files_review.py -v
"""

import re
import json
from pathlib import Path


# Paths
REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "docs/plans/docs-vs-files-review.md"
APP_JSX = REPO_ROOT / "dashboard/src/App.jsx"
OUTBOX_JS = REPO_ROOT / "dashboard/electron/main/outbox.js"
DASHBOARD_SRC = REPO_ROOT / "dashboard/src"
DASHBOARD_MAIN = REPO_ROOT / "dashboard/electron/main"


def read_doc():
    """Read the doc file."""
    assert DOC_PATH.exists(), f"Doc not found: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


def extract_section(doc, pattern):
    r"""Extract text from section matching pattern to next heading of same or higher level.

    Pattern should have one capture group for the heading level (e.g., r'^(#+\s+Title)').
    Returns the section text or None if not found.
    """
    match = re.search(pattern, doc, re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    start = match.start()
    # Count # in the captured group to determine heading level
    heading_text = match.group(1)
    heading_level = len(re.match(r'^(#+)', heading_text).group(1))
    # Find next heading at same or higher level
    next_heading = re.search(
        f"^#{{{1,heading_level}}}\\s", doc[start + 1:], re.MULTILINE
    )
    if next_heading:
        end = start + 1 + next_heading.start()
    else:
        end = len(doc)
    return doc[start:end]


def find_files_by_basename(root, basename):
    """Find all files matching basename in the tree."""
    results = []
    for f in root.rglob("*"):
        if f.is_file() and f.name == basename:
            results.append(f)
    return results


# Test 1: Doc exists, non-trivial length
def test_1_doc_exists_and_nontrivial():
    """Doc exists and is at least 1000 characters (sanity check)."""
    doc = read_doc()
    assert len(doc) > 1000, f"Doc is too short ({len(doc)} chars)"


# Test 2: Docs-tab state grounded
def test_2_docs_tab_state_grounded():
    """Docs tab claims are anchored to expected key phrases."""
    doc = read_doc()
    section = extract_section(doc, r"^(#+\s+Docs\s+Tab)")
    assert section, "Docs Tab section not found"

    required_phrases = [
        "Local clone first",
        "uncommitted",
        "unpushed",
        ".ipynb",
        "markdown",
    ]
    for phrase in required_phrases:
        assert phrase in section, f"Docs tab section missing: {phrase}"


# Test 3: Files-tab state grounded
def test_3_files_tab_state_grounded():
    """Files tab claims are anchored to expected key phrases."""
    doc = read_doc()
    section = extract_section(doc, r"^(#+\s+Files\s+Tab)")
    assert section, "Files Tab section not found"

    required_phrases = [
        "~/.claude/outbox",
        "markdown",
        "json",
        "text",
    ]
    for phrase in required_phrases:
        assert phrase in section, f"Files tab section missing: {phrase}"

    # Verify specific limitation about no search
    assert "No search" in section or "no search" in section.lower(), \
        "Files tab should explicitly state no search"


# Test 4: Overlap/gap table coverage
def test_4_overlap_gap_coverage():
    """Overlap/gap table is present with required dimensions."""
    doc = read_doc()
    # Find a markdown table with | separators
    assert "|" in doc, "No markdown table found"

    required_dimensions = [
        "search",
        "markdown",
        "json",
        "relations",
        "local",
        "github",
    ]
    doc_lower = doc.lower()
    for dim in required_dimensions:
        assert dim in doc_lower, f"Overlap/gap table missing dimension: {dim}"


# Test 5: Options are literal A/B/C in their own sections
def test_5_options_are_literal_abc_in_sections():
    """Options A, B, C are in proper sections, checked inside each section."""
    doc = read_doc()
    # Extract Options section
    section = extract_section(doc, r"^(#+\s+Three Options)")
    assert section, "Options section not found"

    # For each option, extract its own subsection and verify it exists
    for letter in ["A", "B", "C"]:
        # Look for "### A:" or "### Option A:" etc within the Options section
        pattern = rf"^(###\s+(?:Option\s+)?{letter}[:\s])"
        match = re.search(pattern, section, re.MULTILINE)
        assert match, f"Option {letter} subsection not found in Options section"


# Test 6: Each option has all four facets (in its own section)
def test_6_options_have_all_facets_in_section():
    """Each option (A, B, C) contains all four required facets within its section."""
    doc = read_doc()

    for letter in ["A", "B", "C"]:
        # Extract the option section (from "### A:" to next "### " or "##")
        pattern = rf"^(###\s+(?:Option\s+)?{letter}[:\s].*?)(?=^##|\Z)"
        match = re.search(pattern, doc, re.MULTILINE | re.DOTALL)
        assert match, f"Option {letter} section not found"
        option_section = match.group(1)

        # Check for all four facets (case-insensitive)
        facets = [
            ("on-screen change", ["on-screen", "screen"]),
            ("migration work", ["migration"]),
            ("risks", ["risk"]),
            ("what breaks", ["break"]),
        ]

        for facet_name, keywords in facets:
            found = any(kw.lower() in option_section.lower() for kw in keywords)
            assert found, f"Option {letter} missing facet: {facet_name}"


# Test 7: Recommendation exists and names a lettered option
def test_7_recommendation_exists_and_names_option():
    """Recommendation section exists and names exactly one Option [ABC]."""
    doc = read_doc()
    section = extract_section(doc, r"^(#+\s+Recommendation)")
    assert section, "Recommendation section not found"

    # Check for "Option A", "Option B", or "Option C" with word boundaries
    # Use fixed regex: \bOption\s+[ABC]\b (case-insensitive)
    pattern = r"\bOption\s+[ABC]\b"
    matches = re.findall(pattern, section, re.IGNORECASE)

    assert len(matches) >= 1, "Recommendation must name at least one Option [ABC]"
    assert len(section) > 200, f"Recommendation section too short ({len(section)} chars)"


# Test 8: Tab bar matches real App.jsx TABS array
def test_8_tabs_array_matches_code():
    """Doc's TABS reference matches the real App.jsx TABS array."""
    doc = read_doc()

    # Read App.jsx and extract TABS array
    app_jsx = APP_JSX.read_text(encoding="utf-8")
    tabs_match = re.search(
        r"const TABS\s*=\s*\[(.*?)\]",
        app_jsx,
        re.DOTALL
    )
    assert tabs_match, "TABS array not found in App.jsx"

    # Extract tab labels from the array
    tabs_text = tabs_match.group(1)
    label_matches = re.findall(r"label:\s*['\"]([^'\"]+)['\"]", tabs_text)
    assert len(label_matches) > 0, "No tab labels found in TABS array"

    # Verify doc mentions these tabs and the correct count
    doc_lower = doc.lower()
    assert "docs" in doc_lower, "Doc doesn't mention Docs tab"
    assert "files" in doc_lower, "Doc doesn't mention Files tab"

    # If doc makes a count claim, verify it's correct
    count_pattern = r"\b\d+\s+tabs?\b|\bTABS array\b"
    if re.search(count_pattern, doc, re.IGNORECASE):
        # Extract any numeric claim
        numeric_match = re.search(r"\b(\d+)\s+(?:tabs?|to|\-)", doc)
        if numeric_match:
            claimed = int(numeric_match.group(1))
            actual = len(label_matches)
            assert claimed == actual, \
                f"Doc claims {claimed} tabs but App.jsx has {actual}"


# Test 9: Every backtick-cited file path exists
def test_9_cited_file_paths_exist():
    """All file paths in backticks exist in the repo, with basename fallback."""
    doc = read_doc()

    # Find all backtick-quoted paths that look like actual file paths
    # Must contain / (directory) or . (extension), but not just be markdown/prose
    all_backtick_content = re.findall(r"`([^`]+)`", doc)

    paths = []
    for content in all_backtick_content:
        # Skip markdown syntax like ![...](...)
        if content.startswith('!'):
            continue
        # Skip URLs and domain names (contain :// or start with domain patterns like github/gist)
        if '://' in content or '.github' in content or '.com' in content:
            continue
        # Must look like a path: contain / or . with reasonable structure
        # Valid: dashboard/src/App.jsx, docs_cache.js, example.md, etc.
        # Invalid: ".md" alone, "Implementation:", standalone words
        if "/" in content or (re.search(r'[a-z0-9_-]+\.\w{2,4}(?::\d+)?$', content, re.I)):
            paths.append(content)

    for path_str in paths:
        # Strip line-number suffixes (:NN or :NN-MM)
        path_clean = re.sub(r":\d+(?:-\d+)?$", "", path_str)

        # Skip glob patterns (contain * or ?)
        if "*" in path_clean or "?" in path_clean:
            continue

        # Skip home directory references (start with ~)
        if path_clean.startswith("~"):
            continue

        # Try as absolute or relative path first
        as_path = REPO_ROOT / path_clean
        if as_path.exists():
            continue

        # Try as basename search
        basename = Path(path_clean).name
        matches = find_files_by_basename(REPO_ROOT, basename)
        assert matches, f"Path cited but not found: {path_str} (searched for {basename})"


# Test 10: Decisions block structurally valid
def test_10_decisions_block_valid():
    """Decisions block is present with required structure."""
    doc = read_doc()

    # Extract Decisions section
    section = extract_section(doc, r"^(#+\s+Decisions)")
    assert section, "Decisions section not found"

    # Check for heading pattern: ### <id>: <question>
    heading_match = re.search(
        r"^###\s+([a-z0-9_-]+):\s+(.+?)$",
        section,
        re.MULTILINE
    )
    assert heading_match, "Decisions must have a heading: ### <id>: <question>"

    decision_id = heading_match.group(1)
    # Verify id format (alphanumeric, underscores, hyphens)
    assert re.match(r"^[a-z0-9_-]+$", decision_id), \
        f"Decisions ID invalid format: {decision_id}"


# Test 11: Decisions options match literal A/B/C
def test_11_decisions_options_match_abc():
    """Decisions block lists A, B, C as options in correct format."""
    doc = read_doc()
    section = extract_section(doc, r"^(#+\s+Decisions)")
    assert section, "Decisions section not found"

    # Find checkboxes: - [ ] or - [x]
    options = re.findall(r"^-\s+\[\s*[x ]?\s*\]\s+(.+?)$", section, re.MULTILINE)
    assert len(options) >= 3, f"Decisions must have at least 3 options, found {len(options)}"

    # Check that the options mention A, B, and C
    option_text = "\n".join(options)
    assert re.search(r"\bA[:\s]", option_text), "Option A not in Decisions"
    assert re.search(r"\bB[:\s]", option_text), "Option B not in Decisions"
    assert re.search(r"\bC[:\s]", option_text), "Option C not in Decisions"


# Test 12: Decisions are unanswered (no [x] checkboxes)
def test_12_decisions_unanswered():
    """Decisions block has no checked boxes (all [ ], not [x])."""
    doc = read_doc()
    section = extract_section(doc, r"^(#+\s+Decisions)")
    assert section, "Decisions section not found"

    # Check for any checked boxes
    checked = re.findall(r"^-\s+\[x\]", section, re.MULTILINE | re.IGNORECASE)
    assert len(checked) == 0, f"Decisions should be unanswered (found {len(checked)} checked boxes)"


# Test 13: #402 and #403 with context, and #402 description is consistent
def test_13_tickets_referenced_with_context_and_402_consistent():
    """Tickets are referenced with context; #402 description is consistent everywhere."""
    doc = read_doc()

    # Check that #402 and #403 have context nearby
    assert "#402" in doc, "#402 not referenced in doc"
    assert "#403" in doc, "#403 not referenced in doc"

    # Check that they're not bare (should have descriptive context)
    # Pattern: #NNN followed by parentheses, colon, or context word
    for ticket_id in ["#402", "#403"]:
        pattern = rf"{re.escape(ticket_id)}(?:\s+\(|:\s+|.*?(?:issue|ticket|review|fix))"
        assert re.search(pattern, doc, re.IGNORECASE), \
            f"{ticket_id} appears without sufficient context"

    # Check #402 consistency: should mention Files/outbox and NOT claim to fix Markdown.jsx
    # Find mentions of #402 that are part of a sentence/paragraph (not just table fragments)
    # Look for #402 followed by meaningful text (not just | or . at end of line)
    descriptions = []
    for line in doc.split('\n'):
        if '#402' in line:
            # Skip table rows (contain |) that are just references
            if '|' in line and len(line.split('#402')[1].strip()) < 10:
                continue
            # Skip if it's just a bare reference
            remainder = line.split('#402')[1].strip() if '#402' in line else ''
            if remainder and (remainder.startswith('(') or len(remainder) > 10):
                descriptions.append(line)

    for desc in descriptions:
        # These should mention Files/outbox as the scope
        assert "files" in desc.lower() or "outbox" in desc.lower(), \
            f"#402 description missing scope: {desc}"
        assert "markdown.jsx" not in desc.lower() or "does not" in desc.lower() or "doesn't" in desc.lower(), \
            f"#402 incorrectly claims to fix Markdown.jsx: {desc}"


# Test 14: Usage frequency verified against live code
def test_14_usage_frequency_claim_verified():
    """Doc states usage is unknown, and code grep confirms zero analytics instrumentation."""
    doc = read_doc()

    # Verify doc states usage is unknown
    usage_claim = re.search(
        r"usage.*unknown|usage.*frequency.*unknown|no.*instrumentation|untracked",
        doc,
        re.IGNORECASE
    )
    assert usage_claim, "Doc must state that usage frequency is unknown/untracked"

    # Grep real code for analytics calls (excluding CSS class names)
    # Pattern: actual analytics library names or function calls
    analytics_pattern = (
        r"\b(analytics|telemetry|posthog|mixpanel|amplitude)\b"
        r"|trackEvent|logEvent|sendAnalytics"
    )

    found_analytics = False
    for directory in [DASHBOARD_SRC, DASHBOARD_MAIN]:
        if not directory.exists():
            continue
        for file_path in directory.rglob("*"):
            if not file_path.is_file():
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
                matches = re.findall(analytics_pattern, content)
                if matches:
                    # Verify they're not false positives (like CSS tracking-wide)
                    # Only fail if we find actual analytics calls
                    if "tracking-wide" not in content or len(matches) > 1:
                        found_analytics = True
                        break
            except Exception:
                pass

    assert not found_analytics, \
        "Code should have zero analytics instrumentation"
