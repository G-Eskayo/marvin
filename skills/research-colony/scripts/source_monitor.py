#!/usr/bin/env python3
"""Fetch daily research items from arXiv, GitHub, HN and store in ChromaDB research-feed."""
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from datetime import date, timedelta, timezone, datetime
from pathlib import Path
from urllib.request import urlopen, Request

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
from machine_profile import machine_label  # noqa: E402

CHROMA_PATH = Path.home() / ".claude" / "chroma"
CACHE_DIR = Path.home() / ".claude" / "research-feed"


def fetch_arxiv() -> list[dict]:
    cats = "cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.MA+OR+cat:cs.PL"
    url = (
        f"http://export.arxiv.org/api/query?search_query={cats}"
        "&max_results=15&sortBy=submittedDate&sortOrder=descending"
    )
    try:
        with urlopen(url, timeout=30) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = []
        for entry in root.findall("atom:entry", ns):
            title = (entry.findtext("atom:title", "", ns) or "").strip().replace("\n", " ")
            summary = (entry.findtext("atom:summary", "", ns) or "").strip().replace("\n", " ")[:500]
            uid_el = entry.find("atom:id", ns)
            link = uid_el.text.strip() if uid_el is not None else ""
            published = (entry.findtext("atom:published", "", ns) or "")[:10]
            items.append({
                "title": title,
                "summary": summary,
                "url": link,
                "source": "arxiv",
                "date": published,
                "tags": "arxiv,research,paper",
            })
        return items
    except Exception as exc:
        print(f"[colony] arXiv fetch failed: {exc}", file=sys.stderr)
        return []


def fetch_github() -> list[dict]:
    lookback = (date.today() - timedelta(days=7)).isoformat()
    # GitHub search: keyword OR keyword + date filter (topic: + OR + created: causes 422)
    query = f"llm+OR+mcp+OR+%22ai+agents%22+pushed:>{lookback}+stars:>10"
    url = (
        f"https://api.github.com/search/repositories?q={query}"
        "&sort=stars&order=desc&per_page=10"
    )
    req = Request(
        url,
        headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "MARVIN-research-colony",
        },
    )
    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        items = []
        for repo in data.get("items", [])[:10]:
            description = repo.get("description") or ""
            items.append({
                "title": repo.get("full_name", ""),
                "summary": description[:300],
                "url": repo.get("html_url", ""),
                "source": "github",
                "date": (repo.get("created_at") or "")[:10],
                "tags": "github," + ",".join((repo.get("topics") or [])[:5]),
            })
        return items
    except Exception as exc:
        print(f"[colony] GitHub fetch failed: {exc}", file=sys.stderr)
        return []


def fetch_hackernews() -> list[dict]:
    AI_TERMS = {
        "llm", "ai", "agent", "gpt", "claude", "mistral", "language model",
        "machine learning", " ml ", "nlp", "transformer", "benchmark",
        "inference", "fine-tun", "embed", "vector", "rag", "mcp",
        "anthropic", "openai", "deepmind", "gemini",
    }
    url = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30"
    try:
        with urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read())
        items = []
        for hit in data.get("hits", []):
            title = hit.get("title", "") or ""
            story_url = hit.get("url", "") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
            if not any(term in title.lower() for term in AI_TERMS):
                continue
            items.append({
                "title": title,
                "summary": title,
                "url": story_url,
                "source": "hackernews",
                "date": (hit.get("created_at") or "")[:10],
                "tags": "hackernews,news",
            })
        return items[:10]
    except Exception as exc:
        print(f"[colony] HN fetch failed: {exc}", file=sys.stderr)
        return []


def store_items(items: list[dict]) -> int:
    try:
        import chromadb
    except ImportError:
        print("[colony] chromadb not installed — skipping store", file=sys.stderr)
        return 0

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    col = client.get_or_create_collection("research-feed")
    existing = set(col.get()["ids"])

    today = date.today().isoformat()
    new = []
    for item in items:
        uid = "rf-" + hashlib.sha256(item["url"].encode()).hexdigest()[:16]
        if uid in existing:
            continue
        new.append({
            "id": uid,
            "document": f"{item['title']}\n{item['summary']}",
            "metadata": {
                "title": item["title"][:500],
                "url": item["url"][:500],
                "source": item["source"],
                "date": today,            # fetch date — used for daily filter
                "published": item["date"],  # original publication date
                "tags": item["tags"],
                "correlated": "false",
                "matched_topics": "",
                "source_machine": machine_label(),
            },
        })

    if new:
        col.add(
            documents=[e["document"] for e in new],
            metadatas=[e["metadata"] for e in new],
            ids=[e["id"] for e in new],
        )

    return len(new)


def save_raw_cache(items: list[dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    path = CACHE_DIR / f"{today}.json"
    existing = []
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            pass
    seen = {i["url"] for i in existing}
    merged = existing + [i for i in items if i["url"] not in seen]
    path.write_text(json.dumps(merged, indent=2))


def main() -> int:
    all_items = fetch_arxiv() + fetch_github() + fetch_hackernews()
    print(f"[colony] fetched {len(all_items)} items total", file=sys.stderr)
    save_raw_cache(all_items)
    added = store_items(all_items)
    print(f"[colony] stored {added} new items in research-feed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
