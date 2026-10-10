#!/usr/bin/env python3
"""What a portfolio page says, checked against its content template (ADR 0051).

Layout is the Evaluation's other half (portfolio_eval.py). This module reads the content templates
(`templates/content/<type>.json`) and each long-form page's source (`content/longform/<slug>.json`, which records its
`content_type` and each section's `role`) and reports:

  coverage        which required sections and evidence a page is missing against its template
  check_copy      phrases that read as AI-written, and em-dashes (heuristics: they flag, a person decides)
  media           images without alt text; a long-form page with no figure at all
  MARVIN links    a page built with MARVIN links to the MARVIN page, and the MARVIN page links back

Nothing is stored: coverage is computed from the files every time. Run: portfolio_content.py --json
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_catalog  # noqa: E402

PROJECT = project_catalog.portfolio_repo_path()
CLAIMS_LEDGER_PATH = Path.home() / ".claude" / "logs" / "claims-ledger.json"

# Generic-LLM tells from the writing-style skill. Kept short and specific: each one has been seen on this site or is a
# well-known tic. Matched as whole words, case-insensitively, in visible text only.
AI_PHRASES = [
    "revolutionize", "revolutionise", "seamless", "seamlessly", "cutting-edge", "game-changer", "game changer",
    "leverage", "leveraging", "delve", "in today's", "it's worth noting", "furthermore", "moreover", "not just",
    "unlock", "empower", "elevate", "deeply engaging", "rewarding journey", "sophisticated yet", "in conclusion",
    "this project demonstrates", "plays a crucial role", "it is crucial to",
]
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def _finding(rule: str, detail: str, severity: str = "warning") -> dict:
    return {"rule": rule, "severity": severity, "detail": detail}


def _visible_text(html: str) -> str:
    html = re.sub(r"<(code|pre|script|style)\b.*?</\1>", " ", html or "", flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _page_html(content: dict) -> str:
    return (content.get("lead_html") or "") + "".join(s.get("body_html") or "" for s in content.get("sections") or [])


# ── evidence and coverage ──

def evidence_in(html: str) -> set[str]:
    """The kinds of evidence a piece of markup carries."""
    kinds: set[str] = set()
    for src in re.findall(r"<img\b[^>]*\bsrc=[\"']([^\"']+)", html or "", flags=re.I):
        path = src.split("?")[0].lower()
        if path.endswith(".svg"):
            kinds |= {"diagram", "chart"}
        elif path.endswith(IMAGE_EXT):
            kinds |= {"screenshot", "real-output"}
    if re.search(r"<a\b[^>]*\bhref=", html or "", flags=re.I):
        kinds.add("link")
    if re.search(r"<table\b", html or "", flags=re.I) or len(re.findall(r"\d[\d,.]*", _visible_text(html))) >= 2:
        kinds.add("numbers")
    return kinds


def coverage(content: dict, template: dict) -> dict:
    """Required roles the page lacks, and evidence its sections of each role lack."""
    by_role: dict[str, str] = {}
    for s in content.get("sections") or []:
        by_role[s.get("role") or ""] = by_role.get(s.get("role") or "", "") + (s.get("body_html") or "")
    missing_roles, missing_evidence = [], []
    for spec in template.get("sections", []):
        condition = spec.get("only_if")
        required = spec.get("required") and (not condition or bool(content.get(condition)))
        role = spec["role"]
        if role not in by_role:
            if required:
                missing_roles.append(role)
            continue
        have = evidence_in(by_role[role])
        # "a|b" means either kind satisfies it
        missing_evidence += [{"role": role, "evidence": e} for e in spec.get("evidence", []) if not set(e.split("|")) & have]
    return {"type": template.get("id"), "missing_roles": missing_roles, "missing_evidence": missing_evidence}


# ── copy ──

def check_copy(html: str) -> list[dict]:
    text = _visible_text(html)
    found = []
    if "—" in text:
        found.append(_finding("copy-em-dash", f"{text.count('—')} em-dash(es): use a period or a comma"))
    for phrase in AI_PHRASES:
        if re.search(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", text, flags=re.I):
            found.append(_finding("copy-ai-phrase", f'"{phrase}" reads as generic AI writing'))
    return found


# ── media ──

def check_media_markup(html: str) -> list[dict]:
    found = []
    for tag in re.findall(r"<img\b[^>]*>", html or "", flags=re.I):
        alt = re.search(r"\balt=[\"']([^\"']*)[\"']", tag, flags=re.I)
        if not alt or not alt.group(1).strip():
            src = (re.search(r"\bsrc=[\"']([^\"']+)", tag) or [None, "an image"])[1]
            found.append(_finding("image-no-alt", f"{src.rsplit('/', 1)[-1]} has no alt text"))
    return found


def check_has_figure(content: dict) -> list[dict]:
    if re.search(r"<img\b", _page_html(content), flags=re.I):
        return []
    return [_finding("no-evidence-figure", "a long-form page with no screenshot, diagram or chart")]


# ── MARVIN links both ways ──

def check_marvin_links(contents: dict[str, dict], urls: dict[str, str]) -> list[dict]:
    marvin_url = urls.get("marvin", "/ai-projects/marvin/")
    built = [s for s, c in contents.items() if s != "marvin" and c.get("built_with_marvin")]
    found = []
    for slug in built:
        if f'href="{marvin_url}"' not in _page_html(contents[slug]):
            found.append({"page": slug, **_finding("marvin-link-missing", f"says it was built with MARVIN but never links to {marvin_url}")})
    if "marvin" in contents:
        listing = "".join(s.get("body_html") or "" for s in contents["marvin"].get("sections") or [] if s.get("role") == "built-with")
        missing = [s for s in built if urls.get(s) and f'href="{urls[s]}"' not in listing]
        if missing:
            found.append({"page": "marvin", **_finding("marvin-missing-backlink", "Built with MARVIN doesn't link to: " + ", ".join(missing))})
    return found


# ── the whole project ──

def _slug(url: str) -> str:
    return url.strip("/").split("/")[-1]


def _read_claims_ledger(ledger_path: Path | None = None) -> dict | None:
    """Read the claims ledger for the marvin page. Returns None if missing/stale."""
    if ledger_path is None:
        ledger_path = CLAIMS_LEDGER_PATH

    try:
        data = json.loads(ledger_path.read_text())
        # Check if ledger is stale (older than 24 hours)
        checked_at = data.get("checked_at")
        if checked_at:
            try:
                # Parse ISO format with timezone safety
                check_time = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                if (now - check_time).total_seconds() > 24 * 3600:
                    return {"stale": True, "data": data}
            except (ValueError, TypeError):
                # Unparseable timestamp = stale
                return {"stale": True, "data": data}
        else:
            # Missing checked_at = stale
            return {"stale": True, "data": data}
        return {"stale": False, "data": data}
    except (OSError, json.JSONDecodeError):
        return None


def _claims_findings(ledger_info: dict | None) -> list[dict]:
    """Convert claims ledger info to findings."""
    findings = []
    if ledger_info is None:
        findings.append(_finding("claim-ledger-missing", "claims ledger not found or unreadable", "warning"))
    elif ledger_info.get("stale"):
        findings.append(_finding("claim-ledger-stale", "claims ledger is older than 24 hours", "warning"))

    if ledger_info and ledger_info.get("data"):
        data = ledger_info["data"]
        # Add failed claim findings
        for claim_id, result in data.get("failed", {}).items():
            # Find the claim's section from the ledger data
            section = None
            for cid, claim in data.get("checked", {}).items():
                if isinstance(claim, dict) and claim.get("id") == claim_id:
                    section = claim.get("section")
                    break

            findings.append({
                "rule": "claim-untrue",
                "severity": "warning",
                "detail": f"claim no longer true: '{result.get('detail', 'failed')}'",
                "section": section
            })

        # Add unknown claim findings
        for claim_id, result in data.get("unknown", {}).items():
            # Find the claim's section from the ledger data
            section = None
            for cid, claim in data.get("checked", {}).items():
                if isinstance(claim, dict) and claim.get("id") == claim_id:
                    section = claim.get("section")
                    break

            findings.append({
                "rule": "claim-unknown",
                "severity": "info",
                "detail": f"claim check inconclusive: '{result.get('detail', 'unknown')}'",
                "section": section
            })

        # Add unchecked claim findings
        for sentence in data.get("unchecked", []):
            findings.append({
                "rule": "claim-unregistered",
                "severity": "info",
                "detail": f"sentence states a fact without a claim check: '{sentence[:80]}...'" if len(sentence) > 80 else f"sentence states a fact without a claim check: '{sentence}'",
                "section": None
            })

    return findings


def evaluate(project: Path = PROJECT, ledger_path: Path | None = None) -> dict:
    project = Path(project)
    templates = {p.stem: json.loads(p.read_text()) for p in sorted((project / "templates" / "content").glob("*.json"))}
    contents = {p.stem: json.loads(p.read_text()) for p in sorted((project / "content" / "longform").glob("*.json"))}
    manifest_path = project / "deploy" / "other-projects" / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    urls = {_slug(m["url"]): m["url"] for m in manifest}
    titles = {_slug(m["url"]): m.get("title") for m in manifest}
    urls.setdefault("marvin", "/ai-projects/marvin/")
    pages = {}
    for slug, c in contents.items():
        ctype = c.get("content_type") if c.get("content_type") in templates else None
        html = _page_html(c)
        findings = check_copy(html) + check_media_markup(html) + check_has_figure(c)
        pages[slug] = {"template": ctype, "url": urls.get(slug), "title": titles.get(slug), "coverage": coverage(c, templates[ctype]) if ctype else None,
                       "findings": findings}
    for slug in urls:   # manifest pages with no content file yet: listed, not failed
        if slug not in pages and slug in titles:
            pages[slug] = {"template": None, "url": urls[slug], "title": titles[slug], "coverage": None, "findings": []}
    for f in check_marvin_links(contents, urls):
        pages[f.pop("page")]["findings"].append(f)

    # For marvin page only: add claims ledger findings
    if "marvin" in pages:
        ledger_info = _read_claims_ledger(ledger_path)
        pages["marvin"]["findings"].extend(_claims_findings(ledger_info))

    return {"templates": sorted(templates), "pages": pages}


def findings_for_evaluation(project: Path = PROJECT, include_copy: bool = True, ledger_path: Path | None = None) -> list[dict]:
    """The content findings in the Evaluation's shape: one row per finding, labelled by page. The Evaluation checks copy on
    every rendered page itself (legacy pages have no content file), so it passes include_copy=False."""
    report = evaluate(project, ledger_path=ledger_path)
    rows = []
    for slug, p in report["pages"].items():
        label = f"{p['url'] or slug} (content)"
        rows += [{"page": label, **f} for f in p["findings"] if include_copy or not f["rule"].startswith("copy-")]
        cov = p["coverage"] or {}
        rows += [{"page": label, "rule": "template-missing-section", "severity": "warning", "detail": f"no '{r}' section ({p['template']})"}
                 for r in cov.get("missing_roles", [])]
        rows += [{"page": label, "rule": "template-missing-evidence", "severity": "warning", "detail": f"'{m['role']}' has no {m['evidence']}"}
                 for m in cov.get("missing_evidence", [])]
    return rows


def main() -> None:
    if "--json" in sys.argv:
        print(json.dumps(evaluate(), indent=1))
    else:
        for row in findings_for_evaluation():
            print(f"{row['page']}: {row['rule']}: {row['detail']}")


if __name__ == "__main__":
    main()
