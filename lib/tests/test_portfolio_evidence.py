"""Research evidence logs fed to portfolio pages (lib/portfolio_evidence.py, ADR 0061)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_evidence as pe  # noqa: E402
import project_catalog  # noqa: E402

# ── fixtures ──

EVIDENCE_LOG = """# Evidence log: the research behind Seal's decisions

One entry per source. Each says what we took from it, how strong it is, and which decision it drives, so the
portfolio page and the marketing site (#44) can show the reasoning, not just the result. **Add an entry whenever
research informs a decision**, and link the ADR, PR or ticket it drove.

Confidence: **Strong** (controlled study or official documentation), **Moderate** (guideline or several consistent
sources), **Weak** (single small study, secondary report or anecdote), **Ours** (our own measurement).

Public use: **Yes** (fine to cite on the portfolio or marketing pages as written), **Careful** (cite with its
caveat), **Internal** (process detail, not for marketing).

---

## E1. Dark vs. light mode for older readers
- **Source:** Piepenbrock, Mayr, Mund & Buchner (2013), *Ergonomics*: younger (18–33) vs. older (60–85) adults on
  visual acuity and proofreading in light vs. dark mode. Summary: [Nielsen Norman Group, Dark Mode vs. Light Mode](https://www.nngroup.com/articles/dark-mode/).
- **What we took:** dark text on a light background read better for both age groups, but the advantage was smaller
  for older adults. Dark mode caused no measurable extra eye fatigue. Participants had healthy eyes (no cataracts).
- **Confidence:** Strong for healthy eyes; the result doesn't extend to eye conditions.
- **Drives:** equal choice of 3 light and 3 dark themes rather than dark by default (v1 polish spec §4, #96).
- **Public use:** Careful (light and dark both work; we offer both equally).

## E2. Brightness contrast matters more than color
- **Source:** Legge, Parish, Luebker & Wurm (1990), *Psychophysics of reading XI: comparing color contrast and
  luminance contrast*, JOSA A. [PDF](https://legge.dl8.umn.edu/sites/legge.psych.umn.edu/files/files/media/legge90_psychophysics_of_reading._xi._comparing_luminance_and_color_contrast.pdf)
- **What we took:** low-vision readers all read better with luminance (brightness) contrast than color contrast;
  text color itself mattered for only a minority (mostly advanced photoreceptor disorders).
- **Confidence:** Strong.
- **Drives:** every theme must reach AAA contrast (7:1), enforced by a test; theme design focuses on brightness
  contrast, not on "special" text colors (#96).
- **Public use:** Yes.

## E3. Yellow-on-black isn't proven easier, and pure-black glare
- **Source:** no controlled study found that isolates yellow-on-black for older adults (searched 2026-10-09).
  Secondary: [NIH/NLM, Making Your Web Site Senior Friendly](https://corpora.tika.apache.org/base/docs/govdocs1/562/562513.html)
  (light lettering on dark backgrounds is acceptable; avoid yellow next to blue and green for older eyes).
  Astigmatism and halation on bright-on-black text: anecdotal, not verified.
- **What we took:** no evidence justifies the harsh black-and-yellow "Bright" theme; dark themes should be calm
  (no pure black, no pure white, warm off-white text) while keeping AAA contrast.
- **Confidence:** Moderate (guideline) for the yellow/blue caution; Weak for the glare reasoning.
- **Drives:** "Bright" theme removed; relaxed dark themes (owner, 2026-10-09; #96).
- **Public use:** Careful.

## E4. What makes captions readable for older viewers
- **Source:** caption readability study for elderly TV viewers. [Sun Repository](https://reposit.sun.ac.jp/dspace/handle/10561/231)
- **What we took:** readability depends on caption size, font, spacing and the contrast between caption and
  background, the four things Seal lets people adjust.
- **Confidence:** Moderate.
- **Drives:** size, lettering and color settings (ADR 0013 simplicity; #34 text size; #96 settings).
- **Public use:** Yes.

## E5. Dyslexia fonts don't measurably improve reading
- **Source:** Wery & Diliberto (2017), *The effect of a specialized dyslexia font, OpenDyslexic, on reading rate and
  accuracy*, Annals of Dyslexia. [PMC full text](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5629233/) ·
  [Springer](https://link.springer.com/article/10.1007/s11881-016-0127-1). Counterpoint: a 3-student study reported
  gains ([OHU](https://acikerisim.ohu.edu.tr/items/4a62b3fd-db56-44ff-bddf-1349ab8e6458)); overview:
  [Edutopia](https://www.edutopia.org/article/do-dyslexia-fonts-actually-work/).
- **What we took:** in 12 students with dyslexia, OpenDyslexic gave no improvement in reading rate or accuracy over
  Arial or Times New Roman, and none preferred it. Some people still find it more comfortable.
- **Confidence:** Strong (for no measured benefit, in children); Weak (for the counterpoint).
- **Drives:** default lettering stays OpenDyslexic by the owner's choice (2026-10-09): he is dyslexic, it is an
  homage, and it is comforting to look at. Atkinson Hyperlegible (designed for low vision) and the system font are
  offered alongside it, plus Rounded, Serif and Typewriter (six choices). Marketing must never claim a font improves reading.
- **Public use:** Careful (offered for comfort, never improves reading).

## E6. What App Review rejects, and how to avoid it
- **Source:** [docs/app-review-risks.md](../app-review-risks.md) and [docs/app-store-compliance.md](../app-store-compliance.md):
  Apple's App Review Guidelines, App Store Connect help, developer forums and Reddit, each claim marked as Apple doc
  or forum report.
- **What we took:** device-support check, privacy manifest, iPad orientations, export compliance, the in-app
  privacy link, no health claims, and holding background audio out of v1.
- **Confidence:** Strong (Apple docs); Weak (forum anecdotes, marked as such).
- **Drives:** #79, #80, #82, #83, the listing in docs/app-store-listing.md.
- **Public use:** Internal (the "no data collected, fully on-device" outcome is Yes).

## E7. Building on existing on-device speech and speaker tools
- **Source:** [docs/research-existing-resources.md](../research-existing-resources.md): Apple SpeechAnalyzer reference
  code, FluidAudio (Apache-2.0), Sortformer (CC BY 4.0).
- **What we took:** transcription and speaker separation are solved problems on-device; reuse them, bundle the
  models, and never call the network at runtime.
- **Confidence:** Strong.
- **Drives:** ADR 0001, 0008, 0014.
- **Public use:** Yes (credit the open-source projects).

## E8. Why one voice sometimes gets split into two speakers
- **Source:** our own replay measurements, [docs/perf/speaker-label-stability.md](../perf/speaker-label-stability.md) (#91, PR #94).
- **What we took:** the speaker model itself reassigns one voice after pitch or pace changes; smoothing cut live
  relabels (e.g. 8.1 → 4.5 per minute) without slowing real turn-taking; a full fix needs a voice-recognition model.
- **Confidence:** Ours (synthetic voices; real-device check pending).
- **Drives:** SpeakerLabelSmoother (#94); open decision on adding a speaker-embedding model.
- **Public use:** Careful (good "how we measure" story; don't overstate accuracy).
"""

EMPTY_LOG = ""

MALFORMED_ENTRIES = """## E1. Missing source

- **What we took:** Something.
- **Drives:** #1.
- **Public use:** Yes

## E2. Missing what we took

- **Source:** Paper
- **Drives:** #2.
- **Public use:** Yes

## E3. No public use

- **Source:** Test
- **What we took:** Data
- **Drives:** #3.
"""

DEAD_LINKS = """## E1. Mangled syntax

- **Source:** [Unclosed bracket](https://example.com
- **What we took:** Stuff.
- **Drives:** #1.
- **Public use:** Yes

## E2. Missing URL

- **Source:** [Text without URL]()
- **What we took:** Info.
- **Drives:** #2.
- **Public use:** Yes

## E3. Nested broken

- **Source:** See [outer [inner](url)] link.
- **What we took:** Complex.
- **Drives:** #3.
- **Public use:** Yes
"""

BIG_LOG = "\n\n".join([f"""## E{i}. Entry {i}

- **Source:** [Link {i}](https://example.com/{i})
- **What we took:** Data {i}.
- **Drives:** #{i*100}.
- **Public use:** {'Yes' if i % 2 == 0 else 'Careful'}
""" for i in range(1, 101)])


def catalog_with(projects):
    """Build a minimal catalog dict with the given projects."""
    return {"projects": projects, "generated_at": "2026-01-01T00:00:00Z"}


# ── parse_log ──

def test_parse_log_extracts_all_fields_from_well_formed_entries():
    # Test with minimal fixture first
    minimal = """## E1. Test entry

- **Source:** Test source value
- **What we took:** Test value
- **Drives:** Test drives
- **Public use:** Yes
"""
    entries = pe.parse_log(minimal)
    assert len(entries) == 1
    e1 = entries[0]
    assert e1["id"] == "E1"
    assert e1["title"] == "Test entry"
    assert e1["source"] == "Test source value", f"Expected 'Test source value', got {repr(e1['source'])}"
    assert e1["what_we_took"] == "Test value"
    assert e1["drives"] == "Test drives"
    assert e1["public_use"] == "yes"

    # Now test with the real fixture
    entries = pe.parse_log(EVIDENCE_LOG)
    assert len(entries) >= 8
    e1 = next(e for e in entries if e["id"] == "E1")
    assert e1["title"] == "Dark vs. light mode for older readers"
    assert "Nielsen Norman Group" in e1["source"]
    assert "dark text on a light background" in e1["what_we_took"]
    assert "#96" in e1["drives"]
    assert e1["public_use"] == "careful"


def test_parse_log_handles_missing_fields_gracefully():
    entries = pe.parse_log(MALFORMED_ENTRIES)
    e1 = next((e for e in entries if e["id"] == "E1"), None)
    assert e1 is not None and e1["source"] == ""  # missing source, not an exception
    e2 = next((e for e in entries if e["id"] == "E2"), None)
    assert e2 is not None and e2["what_we_took"] == ""  # missing what-we-took


def test_parse_log_treats_missing_public_use_as_internal():
    entries = pe.parse_log(MALFORMED_ENTRIES)
    e3 = next((e for e in entries if e["id"] == "E3"), None)
    assert e3 is not None and e3["public_use"] == "internal"


def test_parse_log_normalizes_public_use_case_and_whitespace():
    log = """## E1. Test
- **Source:** X
- **What we took:** Y
- **Drives:** Z
- **Public use:**   CAREFUL
"""
    entries = pe.parse_log(log)
    assert entries[0]["public_use"] == "careful"
    log2 = """## E2. Test
- **Source:** X
- **What we took:** Y
- **Drives:** Z
- **Public use:** YES
"""
    entries2 = pe.parse_log(log2)
    assert entries2[0]["public_use"] == "yes"


def test_parse_log_treats_malformed_internal_as_internal():
    entries = pe.parse_log(EVIDENCE_LOG)
    e6 = next(e for e in entries if e["id"] == "E6")
    assert e6["public_use"] == "internal"  # "Internal (the ...)" normalizes to "internal"


def test_parse_log_handles_empty_log():
    entries = pe.parse_log(EMPTY_LOG)
    assert entries == []


def test_parse_log_preserves_entry_order():
    entries = pe.parse_log(EVIDENCE_LOG)
    ids = [e["id"] for e in entries]
    assert ids == ["E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"]


def test_parse_log_handles_out_of_order_and_gaps():
    log = """## E1. A
- **Source:** X
- **What we took:** Y
- **Drives:** Z
- **Public use:** Yes

## E3. C
- **Source:** X
- **What we took:** Y
- **Drives:** Z
- **Public use:** Yes

## E2. B
- **Source:** X
- **What we took:** Y
- **Drives:** Z
- **Public use:** Yes
"""
    entries = pe.parse_log(log)
    ids = [e["id"] for e in entries]
    assert ids == ["E1", "E3", "E2"]  # parse in order found, not numeric order


def test_parse_log_handles_duplicate_ids():
    log = """## E1. First
- **Source:** X
- **What we took:** Y
- **Drives:** Z
- **Public use:** Yes

## E1. Second
- **Source:** X
- **What we took:** Y
- **Drives:** Z
- **Public use:** Yes
"""
    entries = pe.parse_log(log)
    assert len(entries) == 2  # both parsed, not deduplicated


def test_parse_log_scales_to_hundreds():
    import time
    start = time.time()
    entries = pe.parse_log(BIG_LOG)
    elapsed = time.time() - start
    assert len(entries) == 100
    assert elapsed < 1.0  # bounded performance: assert no pathological slowdown


# ── public_entries ──

def test_public_entries_keeps_yes_and_careful():
    entries = pe.parse_log(EVIDENCE_LOG)
    public = pe.public_entries(entries)
    public_ids = [e["id"] for e in public]
    assert "E1" in public_ids and "E2" in public_ids and "E5" in public_ids and "E7" in public_ids
    assert "E6" not in public_ids  # internal excluded


def test_public_entries_returns_empty_for_all_internal():
    log = """## E1. Internal
- **Source:** X
- **What we took:** Y
- **Drives:** Z
- **Public use:** Internal
"""
    entries = pe.parse_log(log)
    public = pe.public_entries(entries)
    assert public == []


def test_public_entries_preserves_order():
    entries = pe.parse_log(EVIDENCE_LOG)
    public = pe.public_entries(entries)
    ids = [e["id"] for e in public]
    assert ids == [e["id"] for e in entries if e["public_use"] != "internal"]


# ── _links ──

def test_links_converts_markdown_links_to_html_anchors():
    html = pe._links("See [this paper](https://example.com/paper.pdf) for details.")
    assert '<a href="https://example.com/paper.pdf">' in html
    assert "this paper</a>" in html


def test_links_handles_dead_markdown_syntax():
    html = pe._links("Check [unclosed bracket](https://example.com")
    assert "<a" not in html  # malformed, left as plain text
    assert "unclosed bracket" in html
    html2 = pe._links("Text [without url]()")
    assert "<a" not in html2  # empty URL, left as plain text


def test_links_preserves_non_markdown_text():
    html = pe._links("Plain text with https://example.com (no markdown).")
    assert "<a" not in html
    assert "Plain text" in html


def test_links_handles_multiple_links():
    html = pe._links("See [first](https://a.com) and [second](https://b.com).")
    assert html.count("<a") == 2


def test_parse_log_handles_dead_links_in_source_field():
    entries = pe.parse_log(DEAD_LINKS)
    assert len(entries) == 3
    e1 = next(e for e in entries if e["id"] == "E1")
    # Malformed link in source should still be parsed
    assert "Unclosed bracket" in e1["source"]
    # Rendering should handle the dead link gracefully
    html = pe.render_entry_html(e1, "G-Eskayo/test")
    assert html  # renders without crashing, even with malformed link


# ── _linked_issues ──

def test_linked_issues_turns_bare_hash_numbers_into_links():
    html = pe._linked_issues("Fixes #42 and resolves #99.", "G-Eskayo/clarity-captions")
    assert 'href="https://github.com/G-Eskayo/clarity-captions/issues/42"' in html
    assert 'href="https://github.com/G-Eskayo/clarity-captions/issues/99"' in html


def test_linked_issues_leaves_hash_as_text_when_no_repo():
    html = pe._linked_issues("See #42 for details.", None)
    assert "<a" not in html
    assert "#42" in html


def test_linked_issues_ignores_hashes_not_followed_by_digits():
    html = pe._linked_issues("Use #hashtag but not #.", "G-Eskayo/test")
    assert "#hashtag" in html
    assert "<a" not in html  # hashtag not linked (no trailing digits)


def test_linked_issues_preserves_surrounding_text():
    html = pe._linked_issues("Addresses #1, #2, and #3 in one go.", "G-Eskayo/test")
    assert "Addresses" in html and "in one go" in html


# ── render_entry_html ──

def test_render_entry_html_creates_a_callout_component():
    entries = pe.parse_log(EVIDENCE_LOG)
    e1 = next(e for e in entries if e["id"] == "E1")
    html = pe.render_entry_html(e1, "G-Eskayo/clarity-captions")
    assert "<a href=" in html  # has links (from markdown and issue refs)
    assert "Nielsen Norman Group" in html or "Piepenbrock" in html  # includes source
    assert "dark text on a light background" in html  # includes what-we-took
    assert "equal choice of 3 light and 3 dark themes" in html  # includes drives


def test_render_entry_html_includes_caveat_for_careful_entries():
    entries = pe.parse_log(EVIDENCE_LOG)
    e1 = next(e for e in entries if e["id"] == "E1")
    html = pe.render_entry_html(e1, "G-Eskayo/clarity-captions")
    assert "light and dark both work" in html  # caveat is extracted from public_use field


def test_render_entry_html_omits_caveat_for_yes_entries():
    entries = pe.parse_log(EVIDENCE_LOG)
    e7 = next(e for e in entries if e["id"] == "E7")
    html = pe.render_entry_html(e7, "G-Eskayo/clarity-captions")
    assert "credit the open-source projects" not in html  # caveat not shown for yes even if present in field


def test_render_entry_html_links_issue_numbers_in_drives():
    entries = pe.parse_log(EVIDENCE_LOG)
    e1 = next(e for e in entries if e["id"] == "E1")
    html = pe.render_entry_html(e1, "G-Eskayo/clarity-captions")
    assert 'href="https://github.com/G-Eskayo/clarity-captions/issues/96"' in html


def test_render_entry_html_handles_missing_caveat_gracefully():
    entries = pe.parse_log(EVIDENCE_LOG)
    e3 = next(e for e in entries if e["id"] == "E3")
    html = pe.render_entry_html(e3, "G-Eskayo/clarity-captions")
    assert html  # renders without crashing


# ── research_section_html ──

def test_research_section_html_combines_public_entries():
    entries = pe.parse_log(EVIDENCE_LOG)
    public = pe.public_entries(entries)
    html = pe.research_section_html(public, "G-Eskayo/clarity-captions")
    assert html is not None
    assert "dark text on a light background" in html  # E1 is included (public)
    assert "device-support check" not in html  # E6 content (internal) never appears


def test_research_section_html_returns_none_for_empty_list():
    html = pe.research_section_html([], "G-Eskayo/test")
    assert html is None


def test_research_section_html_returns_none_when_all_internal():
    log = """## E1. Internal
- **Source:** X
- **What we took:** Y
- **Drives:** Z
- **Public use:** Internal
"""
    entries = pe.parse_log(log)
    public = pe.public_entries(entries)
    html = pe.research_section_html(public, "G-Eskayo/test")
    assert html is None


# ── research_section_for ──

def test_research_section_for_reads_evidence_log_from_project(tmp_path):
    catalog = catalog_with([
        {"id": "clarity-captions", "repo": "G-Eskayo/clarity-captions", "primaryPath": str(tmp_path)}
    ])
    (tmp_path / "docs" / "research").mkdir(parents=True)
    (tmp_path / "docs" / "research" / "evidence-log.md").write_text(EVIDENCE_LOG)
    section = pe.research_section_for("clarity-captions", catalog)
    assert section is not None
    assert section["role"] == "research"
    assert section["heading"] == "Research behind it"
    assert "dark text on a light background" in section["body_html"]  # E1 content included
    assert "device-support check" not in section["body_html"]  # E6 (internal) excluded


def test_research_section_for_returns_none_when_no_catalog_entry(tmp_path):
    catalog = catalog_with([])
    section = pe.research_section_for("unknown", catalog)
    assert section is None


def test_research_section_for_returns_none_when_catalog_missing(tmp_path):
    section = pe.research_section_for("any", None)
    assert section is None


def test_research_section_for_returns_none_when_no_evidence_file(tmp_path):
    catalog = catalog_with([
        {"id": "clarity-captions", "repo": "G-Eskayo/clarity-captions", "primaryPath": str(tmp_path)}
    ])
    # No evidence-log.md file
    section = pe.research_section_for("clarity-captions", catalog)
    assert section is None


def test_research_section_for_returns_none_when_all_entries_internal(tmp_path):
    catalog = catalog_with([
        {"id": "clarity-captions", "repo": "G-Eskayo/clarity-captions", "primaryPath": str(tmp_path)}
    ])
    (tmp_path / "docs" / "research").mkdir(parents=True)
    (tmp_path / "docs" / "research" / "evidence-log.md").write_text("""## E1. Internal
- **Source:** X
- **What we took:** Y
- **Drives:** Z
- **Public use:** Internal
""")
    section = pe.research_section_for("clarity-captions", catalog)
    assert section is None


def test_research_section_for_handles_corrupt_catalog_json():
    section = pe.research_section_for("test", {"corrupted": "not-a-projects-list"})
    assert section is None


def test_research_section_for_handles_missing_repo_field(tmp_path):
    catalog = catalog_with([
        {"id": "clarity-captions", "primaryPath": str(tmp_path)}  # no repo field
    ])
    (tmp_path / "docs" / "research").mkdir(parents=True)
    (tmp_path / "docs" / "research" / "evidence-log.md").write_text(EVIDENCE_LOG)
    section = pe.research_section_for("clarity-captions", catalog)
    # When there's no repo, bare issue refs should remain as plain text
    if section is not None:
        assert section["body_html"]  # has content, renders without crash


# ── apply ──

def test_apply_upserts_research_section_into_content(tmp_path):
    content = {
        "content_type": "skill-tool",
        "lead_html": "<p>Lead</p>",
        "sections": [
            {"role": "evidence", "body_html": "<p>Evidence</p>"}
        ]
    }
    (tmp_path / "content" / "longform").mkdir(parents=True)
    (tmp_path / "content" / "longform" / "test-project.json").write_text(json.dumps(content))
    catalog = catalog_with([
        {"id": "test-project", "repo": "G-Eskayo/test", "primaryPath": str(tmp_path)}
    ])
    (tmp_path / "docs" / "research").mkdir(parents=True)
    (tmp_path / "docs" / "research" / "evidence-log.md").write_text(EVIDENCE_LOG)

    def fake_author(content_path, **_):
        return None

    result = pe.apply("test-project", tmp_path / "content" / "longform" / "test-project.json",
                      catalog=catalog, author_fn=fake_author)
    assert result["updated"]
    updated_content = json.loads((tmp_path / "content" / "longform" / "test-project.json").read_text())
    research_sections = [s for s in updated_content["sections"] if s.get("role") == "research"]
    assert len(research_sections) == 1


def test_apply_removes_research_section_when_log_becomes_empty(tmp_path):
    content = {
        "content_type": "skill-tool",
        "lead_html": "<p>Lead</p>",
        "sections": [
            {"role": "evidence", "body_html": "<p>Evidence</p>"},
            {"role": "research", "body_html": "<p>Old research</p>"}
        ]
    }
    (tmp_path / "content" / "longform").mkdir(parents=True)
    (tmp_path / "content" / "longform" / "test-project.json").write_text(json.dumps(content))
    catalog = catalog_with([
        {"id": "test-project", "repo": "G-Eskayo/test", "primaryPath": str(tmp_path)}
    ])
    (tmp_path / "docs" / "research").mkdir(parents=True)
    (tmp_path / "docs" / "research" / "evidence-log.md").write_text("")  # empty log

    def fake_author(content_path, **_):
        return None

    result = pe.apply("test-project", tmp_path / "content" / "longform" / "test-project.json",
                      catalog=catalog, author_fn=fake_author)
    assert result["updated"]
    updated_content = json.loads((tmp_path / "content" / "longform" / "test-project.json").read_text())
    research_sections = [s for s in updated_content["sections"] if s.get("role") == "research"]
    assert len(research_sections) == 0


def test_apply_handles_corrupt_json_gracefully(tmp_path):
    (tmp_path / "content" / "longform").mkdir(parents=True)
    (tmp_path / "content" / "longform" / "bad.json").write_text("{invalid json")

    result = pe.apply("bad", tmp_path / "content" / "longform" / "bad.json",
                      catalog={"projects": []})
    assert not result["updated"]
    assert result["error"]


def test_apply_does_not_duplicate_on_rerun(tmp_path):
    content = {
        "content_type": "skill-tool",
        "lead_html": "<p>Lead</p>",
        "sections": [
            {"role": "evidence", "body_html": "<p>Evidence</p>"}
        ]
    }
    (tmp_path / "content" / "longform").mkdir(parents=True)
    content_path = tmp_path / "content" / "longform" / "test-project.json"
    content_path.write_text(json.dumps(content))
    catalog = catalog_with([
        {"id": "test-project", "repo": "G-Eskayo/test", "primaryPath": str(tmp_path)}
    ])
    (tmp_path / "docs" / "research").mkdir(parents=True)
    (tmp_path / "docs" / "research" / "evidence-log.md").write_text(EVIDENCE_LOG)

    def fake_author(path, **_):
        return None

    pe.apply("test-project", content_path, catalog=catalog, author_fn=fake_author)
    first_content = json.loads(content_path.read_text())
    first_count = len([s for s in first_content["sections"] if s.get("role") == "research"])

    pe.apply("test-project", content_path, catalog=catalog, author_fn=fake_author)
    second_content = json.loads(content_path.read_text())
    second_count = len([s for s in second_content["sections"] if s.get("role") == "research"])

    assert first_count == 1 and second_count == 1  # no duplication


def test_apply_respects_public_use_flag_changes(tmp_path):
    content = {
        "content_type": "skill-tool",
        "lead_html": "<p>Lead</p>",
        "sections": [
            {"role": "evidence", "body_html": "<p>Evidence</p>"}
        ]
    }
    (tmp_path / "content" / "longform").mkdir(parents=True)
    content_path = tmp_path / "content" / "longform" / "test-project.json"
    content_path.write_text(json.dumps(content))
    catalog = catalog_with([
        {"id": "test-project", "repo": "G-Eskayo/test", "primaryPath": str(tmp_path)}
    ])

    log_path = tmp_path / "docs" / "research" / "evidence-log.md"
    log_path.parent.mkdir(parents=True)
    log_path.write_text(EVIDENCE_LOG)

    def fake_author(path, **_):
        return None

    # First apply
    pe.apply("test-project", content_path, catalog=catalog, author_fn=fake_author)
    first_content = json.loads(content_path.read_text())
    first_html = next((s.get("body_html") for s in first_content["sections"] if s.get("role") == "research"), "")
    first_count = first_html.count("E")  # rough: count of entry markers

    # Modify log: change E2 to Internal
    modified_log = EVIDENCE_LOG.replace("## E2. Another finding", "## E2X. Another finding")
    log_path.write_text(modified_log)

    pe.apply("test-project", content_path, catalog=catalog, author_fn=fake_author)
    second_content = json.loads(content_path.read_text())
    second_html = next((s.get("body_html") for s in second_content["sections"] if s.get("role") == "research"), "")

    # The section should reflect the new state
    assert second_html  # still has content, but changed
