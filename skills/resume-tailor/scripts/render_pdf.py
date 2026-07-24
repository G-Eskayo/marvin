#!/usr/bin/env python3
"""
render_pdf.py — convert a Markdown resume/cover letter to PDF via WeasyPrint.
Usage: python render_pdf.py <input.md> <output.pdf> [--cover-letter]
Exits non-zero on error.

Auto-fit-to-page (ADR-006, extended 2026-07-02): 1-page enforcement is this
script's job, not the content's — in both directions. FIT_LADDER runs largest
to smallest; this renders every step and keeps the LARGEST one that still
fits on exactly 1 page, so a light resume grows to fill the page (more
legible, less obviously sparse) and a heavy one shrinks to fit (down to a
legibility floor, then warns rather than shrinking further). At the chosen
step, also measures how much of the page's content box is actually used
(via WeasyPrint's layout tree) — if even the largest step leaves the page
visibly underfilled, that's a content problem (add a project, expand an
entry), not a rendering one, and gets flagged rather than silently
overgrown past a reasonable size.
"""
import os
import sys
from pathlib import Path

# WeasyPrint needs GLib/Pango from Homebrew on macOS.
# Re-exec with the lib path set if not already present.
if sys.platform == "darwin" and "DYLD_LIBRARY_PATH" not in os.environ:
    os.environ["DYLD_LIBRARY_PATH"] = "/opt/homebrew/lib"
    os.execv(sys.executable, [sys.executable] + sys.argv)

SKILL_DIR = Path(__file__).parent.parent
CSS_PATH = SKILL_DIR / "template" / "resume.css"

# Body-size bounds for the auto-fit search, and the ratios every other
# element scales by relative to body size — derived from what had been a
# hand-tuned 6-step ladder (name was consistently exactly 2x body across
# every step, h2 ~0.85x, entry-title ~1.1x, role-header ~1.0x), generalized
# 2026-07-02 into a continuous search: step down from MAX_BODY_PT by
# BODY_STEP_PT until something fits on 1 page, rather than jumping between
# 6 fixed points. MAX_BODY_PT=13 is a hard ceiling — a resume shouldn't read
# as padded/oversized even when content is short; MIN_BODY_PT=8.5 is the
# legibility floor — below it the fix is trimming content, not shrinking text.
MAX_BODY_PT = 13.0
MIN_BODY_PT = 8.5
BODY_STEP_PT = 0.25


def _make_fit_step(body_pt: float) -> dict:
    ratio = body_pt / 10.0
    return {
        "label": f"{body_pt:g}pt",
        "body_size": f"{body_pt:g}pt",
        "name_size": f"{body_pt * 2.0:g}pt",
        "h2_size": f"{round(body_pt * 0.85, 2):g}pt",
        "entry_title_size": f"{round(body_pt * 1.1, 2):g}pt",
        "role_header_size": f"{body_pt:g}pt",
        "line_height": f"{round(1.3 + 0.1 * (body_pt - 10), 3):g}",
        "margin": f"{round(0.6 * ratio, 3):g}in {round(0.65 * ratio, 3):g}in",
    }


def _build_fit_ladder() -> list[dict]:
    steps = []
    body_pt = MAX_BODY_PT
    while body_pt >= MIN_BODY_PT - 1e-9:
        steps.append(_make_fit_step(round(body_pt, 2)))
        body_pt -= BODY_STEP_PT
    return steps


FIT_LADDER = _build_fit_ladder()

# Below this fraction of the content box being used, even at the largest
# fitting step, the page reads as visibly sparse — a content gap, not
# something more font-scaling should paper over.
MIN_FILL_RATIO = 0.85

# Below this fraction — and only when the ladder never even needed to shrink
# below the 13pt ceiling to fit 1 page, i.e. content was never close to
# overflowing — the gap isn't "add a bullet," it's a sign master.md may
# not have enough genuinely JD-relevant, curated content to fill a resume
# for this role at all. Added 2026-07-02 per user direction: surface that as
# an honest fit signal, not a formatting suggestion. Not a hard block —
# FR-11 still ignores years-of-experience by design — but worth a stronger
# flag than "add a project."
CANDIDACY_FLAG_RATIO = 0.65


def md_to_html(md_text: str, cover_letter: bool = False) -> str:
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        print("ERROR: missing dependency. Run: ~/.agents/venv/bin/pip install markdown-it-py", file=sys.stderr)
        sys.exit(2)

    md = MarkdownIt()
    body_html = md.render(md_text)
    body_html = _annotate_sections(body_html, cover_letter=cover_letter)

    body_class = ' class="cover-letter"' if cover_letter else ""
    css_uri = CSS_PATH.as_uri()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="{css_uri}">
</head>
<body{body_class}>
{body_html}
</body>
</html>"""


def _annotate_sections(html: str, cover_letter: bool = False) -> str:
    """Wrap the header cluster (name + short metadata lines) in CSS-hookable
    structure. Resume: h1 + up to 3 following <p> (title, contact, contact) ->
    two-column .header/.header-left/.header-right. Cover letter: h1 + up to 2
    following <p> (contact, date) -> single-column .header.cover-header.
    Text order in the source stays linear either way — this only affects
    visual layout, not the underlying stream (see ADR-008)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1 is None:
        return str(soup)

    h1.name = "p"
    h1["class"] = "name"

    max_meta = 2 if cover_letter else 3
    meta_ps = []
    node = h1.find_next_sibling()
    while node is not None and getattr(node, "name", None) == "p" and len(meta_ps) < max_meta:
        meta_ps.append(node)
        node = node.find_next_sibling()

    header_div = soup.new_tag("div")
    header_div["class"] = "header cover-header" if cover_letter else "header"
    h1.insert_before(header_div)
    h1.extract()

    if cover_letter:
        header_div.append(h1)
        for p in meta_ps:
            p["class"] = p.get("class", []) + ["contact"]
            header_div.append(p.extract())
        next_p = header_div.find_next_sibling("p")
        if next_p is not None:
            next_p["class"] = next_p.get("class", []) + ["salutation"]
    else:
        left = soup.new_tag("div")
        left["class"] = "header-left"
        right = soup.new_tag("div")
        right["class"] = "header-right"
        header_div.append(left)
        header_div.append(right)
        left.append(h1)
        if meta_ps:
            title_p = meta_ps[0]
            title_p["class"] = title_p.get("class", []) + ["title"]
            left.append(title_p.extract())
        for p in meta_ps[1:]:
            p["class"] = p.get("class", []) + ["contact"]
            right.append(p.extract())
        next_p = header_div.find_next_sibling("p")
        if next_p is not None:
            next_p["class"] = next_p.get("class", []) + ["summary"]

        _tag_section_paragraphs(soup)

    return str(soup)


def _tag_section_paragraphs(soup) -> None:
    """Give Projects entries and Experience role headers a distinct visual
    weight from generic bold text (e.g. Technical Skills category labels,
    which also start with <strong> but shouldn't get the same treatment).
    Scoped by which h2 section a <p> falls under, not just "starts with
    strong", so this can't misfire on other bold-led lines. Projects'
    visual priority comes from this sizing alone, not header color — every
    h2 shares identical styling (see resume.css, revised 2026-07-02 after
    a distinct PROJECTS header color read as inconsistent, not prioritized)."""
    for h2 in soup.find_all("h2"):
        section = h2.get_text(strip=True).upper()
        if section not in ("PROJECTS", "PROFESSIONAL EXPERIENCE"):
            continue
        target_class = "entry-title" if section == "PROJECTS" else "role-header"
        node = h2.find_next_sibling()
        while node is not None and getattr(node, "name", None) != "h2":
            if getattr(node, "name", None) == "p":
                first = next((c for c in node.children if not (isinstance(c, str) and not c.strip())), None)
                if first is not None and getattr(first, "name", None) == "strong":
                    node["class"] = node.get("class", []) + [target_class]
            node = node.find_next_sibling()


def _override_css(step: dict) -> str:
    entry_title_pt = float(step["entry_title_size"].rstrip("pt"))
    role_header_pt = float(step["role_header_size"].rstrip("pt"))
    entry_sub_pt = max(entry_title_pt - 2, float(step["body_size"].rstrip("pt")) - 0.5)
    return f"""
    @page {{ margin: {step['margin']} !important; }}
    body {{ font-size: {step['body_size']} !important; line-height: {step['line_height']} !important; }}
    p, li {{ font-size: {step['body_size']} !important; line-height: {step['line_height']} !important; }}
    .name {{ font-size: {step['name_size']} !important; }}
    h2 {{ font-size: {step['h2_size']} !important; }}
    .entry-title {{ font-size: {step['entry_title_size']} !important; }}
    .entry-title em {{ font-size: {entry_sub_pt}pt !important; }}
    .role-header {{ font-size: {step['role_header_size']} !important; }}
    """


def _content_fill_ratio(document) -> float | None:
    """Fraction of page 1's content box actually used, via WeasyPrint's
    layout tree. Uses the private `_page_box` attribute (no stable public
    API for this in WeasyPrint 69) — best-effort; returns None rather than
    raising if the internal shape ever changes, so a fit-quality signal
    never breaks an actual render."""
    try:
        page = document.pages[0]
        page_box = page._page_box

        def max_bottom(box) -> float:
            # Only leaf boxes (no children) reflect actual rendered content
            # extent — an intermediate/container box's own `.height` is
            # determined by CSS layout (e.g. the page content box is always
            # exactly the margin-constrained area), not by how much content
            # it holds, so including it made this always read ~100% full
            # regardless of actual whitespace. Caught 2026-07-02 when a
            # deliberately sparse test resume still reported 100% fill.
            children = getattr(box, "children", None) or []
            if not children:
                return (getattr(box, "position_y", 0) or 0) + (getattr(box, "height", 0) or 0)
            return max((max_bottom(child) for child in children), default=0)

        content_height = page_box.height
        if not content_height:
            return None
        return max_bottom(page_box) / content_height
    except Exception:
        return None


def render(input_md: str, output_pdf: str, cover_letter: bool = False) -> None:
    try:
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration
    except ImportError:
        print(
            "ERROR: WeasyPrint not installed.\n"
            "Run: ~/.agents/venv/bin/pip install weasyprint",
            file=sys.stderr,
        )
        sys.exit(2)

    src = Path(input_md).expanduser().resolve()
    dst = Path(output_pdf).expanduser().resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)

    md_text = src.read_text(encoding="utf-8")
    html_str = md_to_html(md_text, cover_letter=cover_letter)

    font_config = FontConfiguration()
    html_obj = HTML(string=html_str, base_url=str(SKILL_DIR))
    base_css = CSS(filename=str(CSS_PATH), font_config=font_config)

    for i, step in enumerate(FIT_LADDER):
        stylesheets = [base_css, CSS(string=_override_css(step), font_config=font_config)]
        document = html_obj.render(stylesheets=stylesheets, font_config=font_config)
        page_count = len(document.pages)
        is_last_step = i == len(FIT_LADDER) - 1

        if page_count <= 1 or is_last_step:
            document.write_pdf(str(dst))
            label = step["label"]
            if page_count > 1:
                print(
                    f"WARNING: content still spans {page_count} pages at the smallest size "
                    f"(auto-fit step '{label}', floor of the ladder). Consider trimming content — "
                    f"see resume-tailor SKILL.md curation guidance.",
                    file=sys.stderr,
                )
            elif not cover_letter:
                fill_ratio = _content_fill_ratio(document)
                at_ceiling = i == 0  # 13pt fit without ever needing to shrink
                if fill_ratio is not None and at_ceiling and fill_ratio < CANDIDACY_FLAG_RATIO:
                    print(
                        f"FLAG: page is only ~{fill_ratio:.0%} full even at the 13pt ceiling — content "
                        f"was never close to overflowing at any size. That's more than a formatting gap: "
                        f"it usually means master.md doesn't have enough genuinely JD-relevant, curated "
                        f"content to fill a resume for this role. Worth an honest check on whether this "
                        f"is a real concept-match or a stretch beyond what the experience supports — not "
                        f"a hard block (years-of-experience is ignored by design, FR-11), but a stronger "
                        f"signal than the usual 'add a project' suggestion.",
                        file=sys.stderr,
                    )
                elif fill_ratio is not None and fill_ratio < MIN_FILL_RATIO:
                    print(
                        f"NOTE: page is only ~{fill_ratio:.0%} full at the largest size that still fits "
                        f"one page (step '{label}'). This reads as sparse rather than well-scaled — "
                        f"consider adding the next-strongest Project or expanding an existing entry "
                        f"rather than growing the font further.",
                        file=sys.stderr,
                    )
            print(f"PDF written: {dst} (fit step '{label}')")
            return


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 2:
        print("Usage: render_pdf.py <input.md> <output.pdf> [--cover-letter]", file=sys.stderr)
        sys.exit(2)
    input_md, output_pdf = args[0], args[1]
    is_cover = "--cover-letter" in args
    render(input_md, output_pdf, cover_letter=is_cover)
