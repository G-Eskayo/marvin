"""Tests for brief_items: item construction, deduplication, ranking, rendering."""
import pytest

import brief_items as bi


def test_sanitize_collapses_whitespace():
    assert bi.sanitize("hello  \n\t  world") == "hello world"


def test_sanitize_drops_control_chars():
    assert bi.sanitize("hello\x00world") == "hello world"
    assert bi.sanitize("test\x01\x02\x03") == "test"


def test_sanitize_escapes_markdown_special_chars():
    text = bi.sanitize("hello [world] <tag>")
    assert "[" not in text or "\\[" in text  # either escaped or removed
    assert "]" not in text or "\\]" in text
    assert "<" not in text or "\\<" in text
    assert ">" not in text or "\\>" in text


def test_sanitize_truncates_with_ellipsis():
    long_text = "x" * 400
    result = bi.sanitize(long_text, max_len=300)
    assert len(result) <= 300
    assert result.endswith("…")


def test_sanitize_respects_max_len_param():
    text = "x" * 50
    result = bi.sanitize(text, max_len=10)
    assert len(result) == 10
    assert result.endswith("…")


def test_make_item_builds_a_valid_item():
    item = bi.make_item("your_projects", 0, "Review PR #308 MARVIN launcher")
    assert item["section"] == "your_projects"
    assert item["tier"] == 0
    assert item["line"] == "Review PR #308 MARVIN launcher"


def test_make_item_sanitizes_line():
    item = bi.make_item("your_projects", 0, "hello  \n  world")
    assert item["line"] == "hello world"


def test_make_item_rejects_invalid_section():
    with pytest.raises(ValueError, match="invalid section"):
        bi.make_item("invalid_section", 0, "text")


def test_make_item_rejects_tier_out_of_range():
    with pytest.raises(ValueError, match="tier must be 0-3"):
        bi.make_item("your_projects", 4, "text")
    with pytest.raises(ValueError, match="tier must be 0-3"):
        bi.make_item("your_projects", -1, "text")


def test_make_item_rejects_empty_line():
    with pytest.raises(ValueError, match="line is empty"):
        bi.make_item("your_projects", 0, "   \n  \t  ")


def test_make_item_preserves_extra_fields():
    item = bi.make_item("your_projects", 1, "Review PR", number=308, title="Launcher", repo="marvin")
    assert item["number"] == 308
    assert item["title"] == "Launcher"
    assert item["repo"] == "marvin"


def test_dedup_key_uses_number_and_repo():
    item = {"section": "your_projects", "number": 308, "repo": "marvin", "line": "Review PR"}
    key = bi._dedup_key(item)
    assert key == ("your_projects", "ticket", 308, "marvin")


def test_dedup_key_falls_back_to_line():
    item = {"section": "your_projects", "line": "An idea"}
    key = bi._dedup_key(item)
    assert key == ("your_projects", "text", "An idea")


def test_dedup_key_ignores_number_without_repo():
    item = {"section": "your_projects", "number": 308, "line": "Text"}
    key = bi._dedup_key(item)
    assert key == ("your_projects", "text", "Text")


def test_rank_and_cap_sorts_by_tier_then_order_key():
    items = [
        bi.make_item("your_projects", 1, "PR #2"),
        bi.make_item("your_projects", 0, "Check #1"),
        bi.make_item("your_projects", 2, "Ticket #3"),
    ]
    bi.rank_and_cap(items)
    assert items[0]["line"] == "Check #1"
    assert items[1]["line"] == "PR #2"
    assert items[2]["line"] == "Ticket #3"


def test_rank_and_cap_respects_order_key():
    items = [
        bi.make_item("your_projects", 0, "Second", order_key=2),
        bi.make_item("your_projects", 0, "First", order_key=1),
        bi.make_item("your_projects", 0, "Third", order_key=3),
    ]
    bi.rank_and_cap(items)
    assert items[0]["line"] == "First"
    assert items[1]["line"] == "Second"
    assert items[2]["line"] == "Third"


def test_rank_and_cap_deduplicates_by_number_and_repo():
    items = [
        bi.make_item("your_projects", 0, "Review PR", number=308, repo="marvin"),
        bi.make_item("your_projects", 1, "Also PR", number=308, repo="marvin"),  # duplicate
    ]
    bi.rank_and_cap(items)
    assert len(items) == 1
    assert items[0]["tier"] == 0  # keeps the first (higher priority)


def test_rank_and_cap_deduplicates_by_line_text():
    items = [
        bi.make_item("your_projects", 0, "An idea"),
        bi.make_item("your_projects", 1, "An idea"),  # duplicate text
    ]
    bi.rank_and_cap(items)
    assert len(items) == 1


def test_rank_and_cap_caps_at_total():
    items = [
        bi.make_item("your_projects", 0, f"Item {i}") for i in range(10)
    ]
    bi.rank_and_cap(items, total_cap=5)
    assert len(items) == 5
    assert all(item["section"] == "your_projects" for item in items)


def test_rank_and_cap_caps_at_total_across_multiple_sections():
    items = [
        bi.make_item("your_projects", 0, f"P{i}") for i in range(6)
    ] + [
        bi.make_item("your_day", 0, f"D{i}") for i in range(6)
    ]
    bi.rank_and_cap(items, total_cap=5)
    p_items = [i for i in items if i["section"] == "your_projects"]
    d_items = [i for i in items if i["section"] == "your_day"]
    assert len(p_items) + len(d_items) == 5
    assert len(p_items) == 5  # all 5 from first section (they come first in order)
    assert len(d_items) == 0  # no room for second section


def test_rank_and_cap_assigns_rank():
    items = [
        bi.make_item("your_projects", 0, "Item 1"),
        bi.make_item("your_projects", 0, "Item 2"),
        bi.make_item("your_day", 0, "Day 1"),
    ]
    bi.rank_and_cap(items)
    your_p = [i for i in items if i["section"] == "your_projects"]
    your_d = [i for i in items if i["section"] == "your_day"]
    assert your_p[0]["rank"] == 0
    assert your_p[1]["rank"] == 1
    assert your_d[0]["rank"] == 0


def test_rank_and_cap_modifies_in_place():
    items = [bi.make_item("your_projects", 0, "Text")]
    result = bi.rank_and_cap(items)
    assert result is items
    assert "rank" in items[0]


def test_rank_and_cap_total_cap_across_all_sections():
    """The brief caps at exactly 5 items total, not per section."""
    items = [
        bi.make_item("your_projects", 0, "Project 1"),
        bi.make_item("your_projects", 0, "Project 2"),
        bi.make_item("your_day", 0, "Deadline 1"),
        bi.make_item("your_day", 0, "Deadline 2"),
        bi.make_item("research", 0, "Research 1"),
        bi.make_item("research", 0, "Research 2"),
        bi.make_item("world_security", 0, "Security 1"),
    ]
    bi.rank_and_cap(items, total_cap=5)
    assert len(items) == 5
    # Items are sorted by section order, so we get 2 from your_projects, 2 from your_day, 1 from research
    sections = [i["section"] for i in items]
    assert sections == ["your_projects", "your_projects", "your_day", "your_day", "research"]


def test_rank_and_cap_hundreds_of_candidates_exactly_5():
    """With hundreds of candidates, output is exactly capped at 5 total."""
    items = [
        bi.make_item("your_projects", 0, f"Project {i}") for i in range(100)
    ]
    bi.rank_and_cap(items, total_cap=5)
    assert len(items) == 5
    for i, item in enumerate(items):
        assert item["rank"] == i


def test_rank_and_cap_respects_tier_within_section():
    """Within a section, higher-priority tiers (lower number) are kept first."""
    items = [
        bi.make_item("your_projects", 2, "Low priority"),
        bi.make_item("your_projects", 0, "High priority"),
        bi.make_item("your_projects", 1, "Medium priority"),
    ]
    bi.rank_and_cap(items, total_cap=5)
    # Items are sorted by tier within the section
    assert items[0]["tier"] == 0
    assert items[1]["tier"] == 1
    assert items[2]["tier"] == 2


def test_render_sections_groups_by_section():
    items = [
        bi.make_item("your_projects", 0, "Check #1"),
        bi.make_item("your_day", 0, "Deadline"),
        bi.make_item("your_projects", 1, "PR #2"),
    ]
    bi.rank_and_cap(items)
    text = bi.render_sections(items)
    assert "## Needs you" in text
    assert "## Today" in text
    assert text.index("## Needs you") < text.index("## Today")


def test_render_sections_uses_section_labels():
    items = [
        bi.make_item("your_projects", 0, "Text"),
        bi.make_item("research", 2, "Idea"),
    ]
    bi.rank_and_cap(items)
    text = bi.render_sections(items)
    assert "## Needs you" in text
    assert "## One idea each" in text


def test_render_sections_skips_empty_sections():
    items = [bi.make_item("your_projects", 0, "Text")]
    bi.rank_and_cap(items)
    text = bi.render_sections(items)
    assert "## Today" not in text
    assert "## One idea each" not in text


def test_render_sections_formats_bullets():
    items = [
        bi.make_item("your_projects", 0, "Check #1"),
        bi.make_item("your_projects", 1, "PR #2"),
    ]
    bi.rank_and_cap(items)
    text = bi.render_sections(items)
    assert "- Check #1" in text
    assert "- PR #2" in text


def test_render_sections_respects_section_order():
    items = [
        bi.make_item("world_security", 0, "Security"),
        bi.make_item("your_projects", 0, "Project"),
        bi.make_item("research", 0, "Research"),
        bi.make_item("your_day", 0, "Day"),
    ]
    bi.rank_and_cap(items)
    text = bi.render_sections(items)
    assert (text.index("## Needs you") < text.index("## Today") <
            text.index("## One idea each") < text.index("## World"))


def test_render_sections_no_trailing_blank_lines():
    items = [bi.make_item("your_projects", 0, "Text")]
    bi.rank_and_cap(items)
    text = bi.render_sections(items)
    assert not text.endswith("\n\n")
    assert not text.endswith("\n\n\n")
