#!/usr/bin/env python3
"""
fetch_related.py — find related papers via Semantic Scholar API and arXiv.

Usage:
    python fetch_related.py --doi 10.1234/example
    python fetch_related.py --title "attention is all you need" --keywords "transformer self-attention"
    python fetch_related.py --slug my-paper-slug   # reads DOI from session state.json

Outputs Markdown to stdout. Saves to ~/.claude/paper-sessions/<slug>/related.md if --slug given.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

# Helpers live next to this file in the standalone repo (G-Eskayo/paper-dive) and in ~/.agents/lib inside MARVIN.
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path.home() / ".agents" / "lib")]
from s2_client import get_with_retry, s2_id, S2_PAPER_BASE

SESSION_DIR = Path.home() / ".claude" / "paper-sessions"
ARXIV_BASE = "http://export.arxiv.org/api/query"

failures: list[tuple[str, str]] = []


def get_requests():
    try:
        import requests
        return requests
    except ImportError:
        print("ERROR: missing requests — run: ~/.agents/venv/bin/pip install requests", file=sys.stderr)
        sys.exit(2)


def s2_paper_by_doi(doi: str) -> dict | None:
    try:
        url = f"{S2_PAPER_BASE}/{s2_id(doi)}"
        fields = "title,authors,year,abstract,citationCount,externalIds,openAccessPdf,references,citations"
        resp = get_with_retry(url, params={"fields": fields}, timeout=15)
        return resp.json()
    except get_requests().RequestException as e:
        failures.append(("DOI lookup", str(e)))
        return None
    except (ValueError, KeyError, TypeError) as e:
        failures.append(("DOI lookup", f"JSON decode error: {e}"))
        return None


def s2_search(query: str, limit: int = 20) -> list[dict]:
    try:
        url = f"{S2_PAPER_BASE}/search"
        params = {
            "query": query,
            "limit": limit,
            "fields": "title,authors,year,abstract,citationCount,openAccessPdf,externalIds",
        }
        resp = get_with_retry(url, params=params, timeout=15)
        return resp.json().get("data", [])
    except get_requests().RequestException as e:
        failures.append(("search", str(e)))
        return []
    except (ValueError, KeyError, TypeError) as e:
        failures.append(("search", f"JSON decode error: {e}"))
        return []


def s2_recommendations(paper_id: str, limit: int = 10) -> list[dict]:
    try:
        r = get_requests()
        resp = r.post(
            "https://api.semanticscholar.org/recommendations/v1/papers/",
            json={"positivePaperIds": [paper_id], "negativePaperIds": []},
            params={"limit": limit, "fields": "title,authors,year,abstract,citationCount,openAccessPdf,externalIds"},
            timeout=15,
        )
        if resp.status_code != 200:
            failures.append(("recommendations", f"HTTP {resp.status_code}"))
            return []
        return resp.json().get("recommendedPapers", [])
    except r.RequestException as e:
        failures.append(("recommendations", str(e)))
        return []
    except (ValueError, KeyError, TypeError) as e:
        failures.append(("recommendations", f"JSON decode error: {e}"))
        return []


def arxiv_search(query: str, max_results: int = 5) -> list[dict]:
    r = get_requests()
    try:
        resp = r.get(ARXIV_BASE, params={"search_query": f"all:{query}", "max_results": max_results,
                                          "sortBy": "relevance"}, timeout=15)
        resp.raise_for_status()
    except Exception:
        return []

    import re
    entries = []
    for entry in re.findall(r'<entry>(.*?)</entry>', resp.text, re.DOTALL):
        title = re.search(r'<title>(.*?)</title>', entry, re.DOTALL)
        summary = re.search(r'<summary>(.*?)</summary>', entry, re.DOTALL)
        link = re.search(r'<id>(.*?)</id>', entry)
        published = re.search(r'<published>(.*?)</published>', entry)
        if title and link:
            entries.append({
                "title": title.group(1).strip().replace("\n", " "),
                "abstract": summary.group(1).strip().replace("\n", " ")[:300] if summary else "",
                "url": link.group(1).strip(),
                "year": published.group(1)[:4] if published else "?",
                "source": "arXiv",
            })
    return entries


def recency_score(year) -> float:
    try:
        y = int(year)
        if y >= 2024: return 1.0
        if y >= 2022: return 0.85
        if y >= 2020: return 0.65
        if y >= 2017: return 0.40
        return 0.20
    except Exception:
        return 0.40


def rank_papers(papers: list[dict]) -> list[dict]:
    for p in papers:
        cit = p.get("citationCount") or 0
        cit_norm = min(cit / 1000, 1.0)
        rec = recency_score(p.get("year"))
        p["_score"] = round(cit_norm * 0.6 + rec * 0.4, 3)
    return sorted(papers, key=lambda x: x["_score"], reverse=True)


def fmt_paper(p: dict, idx: int) -> str:
    title = p.get("title", "Unknown")
    authors = p.get("authors", [])
    if isinstance(authors, list) and authors and isinstance(authors[0], dict):
        author_str = ", ".join(a.get("name", "") for a in authors[:3])
        if len(authors) > 3:
            author_str += " et al."
    else:
        author_str = str(authors)[:80]
    year = p.get("year", "?")
    abstract = (p.get("abstract") or "")[:250]
    cit = p.get("citationCount", "?")
    source = p.get("source", "Semantic Scholar")
    pdf = (p.get("openAccessPdf") or {}).get("url") or p.get("url") or ""
    return (f"{idx}. **{title}** ({year}) — {author_str}\n"
            f"   Citations: {cit} | Source: {source}\n"
            f"   {abstract}{'...' if len(abstract) == 250 else ''}\n"
            f"   {pdf if pdf else 'No open-access PDF found'}")


def main() -> None:
    failures.clear()
    ap = argparse.ArgumentParser()
    ap.add_argument("--doi", help="DOI of the paper to find relatives for")
    ap.add_argument("--title", help="Paper title (used for search if no DOI)")
    ap.add_argument("--keywords", help="Additional keywords for search")
    ap.add_argument("--slug", help="Session slug — reads DOI + title from state.json")
    args = ap.parse_args()

    doi = args.doi
    title = args.title
    keywords = args.keywords
    slug = args.slug

    if slug:
        state_path = SESSION_DIR / slug / "state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text())
            doi = doi or state.get("doi")
            title = title or state.get("title")

    if not doi and not title and not keywords:
        print("ERROR: provide --doi, --title, or --slug", file=sys.stderr)
        sys.exit(1)

    query = " ".join(filter(None, [title, keywords]))
    lines = ["# Related Papers\n"]
    all_supporting: list[dict] = []
    all_challenging: list[dict] = []

    # --- Semantic Scholar ---
    s2_paper = None
    if doi:
        s2_paper = s2_paper_by_doi(doi)
        time.sleep(0.5)

    if s2_paper:
        paper_id = s2_paper.get("paperId")
        if paper_id:
            recs = s2_recommendations(paper_id, limit=10)
            for p in recs:
                p["source"] = "Semantic Scholar"
            all_supporting.extend(recs)
            time.sleep(0.5)

    if query:
        search_results = s2_search(query, limit=15)
        for p in search_results:
            p["source"] = "Semantic Scholar"
        all_supporting.extend(search_results)
        time.sleep(0.5)

    # --- arXiv ---
    if query:
        arxiv_results = arxiv_search(query, max_results=5)
        all_supporting.extend(arxiv_results)

    # Deduplicate by title
    seen = set()
    unique = []
    for p in all_supporting:
        key = (p.get("title") or "").lower()[:60]
        if key not in seen:
            seen.add(key)
            unique.append(p)

    ranked = rank_papers(unique)

    if failures:
        reasons = "; ".join(f"{source}: {reason}" for source, reason in failures)
        # Check if ranked results include non-arXiv sources
        has_s2_results = any(p.get("source") != "arXiv" for p in ranked)
        if has_s2_results:
            lines.append(f"> **Issues with Semantic Scholar** ({reasons}): some services unavailable, but results shown are from working services.\n")
        else:
            lines.append(f"> **Semantic Scholar unavailable** ({reasons}): results below are arXiv-only.\n")

    lines.append("## Supporting / Extending\n")
    for i, p in enumerate(ranked[:5], 1):
        lines.append(fmt_paper(p, i))
        lines.append("")

    lines.append("\n## To Explore for Contradictions / Challenges\n")
    lines.append("Run `/challenge` to surface methodological critiques from the citing literature.")
    lines.append("Or search manually: query Semantic Scholar for papers that cite this work and filter by those with diverging conclusions.")

    output = "\n".join(lines)
    print(output)

    if slug:
        out_path = SESSION_DIR / slug / "related.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"\nSaved to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
