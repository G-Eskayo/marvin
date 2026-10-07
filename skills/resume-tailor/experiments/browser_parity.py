#!/usr/bin/env python3
"""How close does in-browser matching get to the AI resume tailor? (docs/plans/resume-browser-vs-ai-2026-10-07.md)

Reference: the AI tailor's past outputs (~/.claude/resume/tailored/*/resume.md + research.md). Methods are ones a
browser can run: keyword TF-IDF overlap, all-MiniLM-L6-v2 embeddings (what transformers.js ships), and a hybrid.
No paid model calls. master.md is private: per-job detail goes to ~/.claude/resume/experiments/, never the repo.

    ~/.agents/venv/bin/python browser_parity.py [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path

RESUME = Path.home() / ".claude" / "resume"
MASTER = RESUME / "master.md"
TAILORED = RESUME / "tailored"
OUT = RESUME / "experiments"

STOP = set("""a an and are as at be by for from has have in into is it its of on or that the to was were will with
we you your our their this these those who what which while within across using use used via per not can may must
should able including include such other more most new all any each etc years year experience strong ability""".split())
SKIP_SECTIONS = re.compile(r"company|contact|signal|source|context|fit", re.I)


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z0-9+#.\-]*[a-z0-9+#]|[a-z]", text.lower()) if w not in STOP and len(w) > 1]


def drop_suppressed(text: str) -> str:
    """Remove every ### entry whose heading is followed by a `<!-- suppress: ... -->` marker (kept in master only)."""
    return re.sub(r"^### [^\n]*\n<!-- suppress:.*?-->\n.*?(?=^#{2,3} |\Z)", "", text, flags=re.S | re.M)


def strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", drop_suppressed(text), flags=re.S)


def sections(md: str, level: str) -> list[tuple[str, str]]:
    """(heading, body) pairs for headings of exactly `level` (e.g. '## ')."""
    out, head, buf = [], None, []
    for line in md.splitlines():
        if line.startswith(level) and not line.startswith(level + "#"):
            if head is not None:
                out.append((head, "\n".join(buf)))
            head, buf = line[len(level):].strip(), []
        elif head is not None:
            buf.append(line)
    if head is not None:
        out.append((head, "\n".join(buf)))
    return out


def master_projects(md: str) -> list[dict]:
    body = dict(sections(strip_comments(md), "## ")).get("Projects", "")
    return [{"title": h.split("|")[0].strip(" *"), "text": h + "\n" + b} for h, b in sections(body, "### ")]


def master_skills(md: str) -> list[str]:
    body = dict(sections(strip_comments(md), "## ")).get("Technical Skills", "")
    terms = []
    for _, b in sections(body, "### "):
        for part in re.split(r",|·|•|;", " ".join(b.split())):
            t = part.strip(" -–.")
            if 1 < len(t) < 60:
                terms.append(t)
    return list(dict.fromkeys(terms))


def tailored_projects(md: str) -> list[str]:
    body = next((b for h, b in sections(md, "## ") if h.upper().startswith("PROJECTS")), "")
    return [m.group(1).strip() for m in re.finditer(r"^\*\*(.+?)\*\*", body, re.M)]


def tailored_skills_text(md: str) -> str:
    return next((b for h, b in sections(md, "## ") if h.upper().startswith("TECHNICAL SKILLS")), "")


def job_text(research: str) -> str:
    kept = [b for h, b in sections(research, "## ") if not SKIP_SECTIONS.search(h)]
    text = "\n".join(kept)
    return "\n".join(l for l in text.splitlines() if "http" not in l)


def title_match(name: str, projects: list[dict]) -> int | None:
    """Index of the master project a tailored project heading came from (titles get lightly reworded)."""
    a = set(words(name))
    best, idx = 0.0, None
    for i, p in enumerate(projects):
        b = set(words(p["title"]))
        j = len(a & b) / max(1, len(a | b))
        if j > best:
            best, idx = j, i
    return idx if best >= 0.25 else None


# --- methods --------------------------------------------------------------------------------------------------

def tfidf_scores(job: str, docs: list[str]) -> list[float]:
    n = len(docs)
    df = Counter(w for d in docs for w in set(words(d)))
    jw = Counter(words(job))
    out = []
    for d in docs:
        dw = set(words(d))
        out.append(sum(c * math.log(1 + n / df[w]) for w, c in jw.items() if w in dw) / math.sqrt(1 + len(dw)))
    return out


_EMB = None


def embed(texts: list[str]):
    global _EMB
    if _EMB is None:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction  # all-MiniLM-L6-v2 ONNX
        _EMB = DefaultEmbeddingFunction()
    import numpy as np
    v = np.array(_EMB(texts), dtype=float)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def embed_scores(job: str, docs: list[str]) -> list[float]:
    """Mean of each doc's best matches against the job's requirement lines (max-pooled, top 3)."""
    import numpy as np
    lines = [l.strip(" -*•") for l in job.splitlines() if len(words(l)) >= 3] or [job]
    J, D = embed(lines), embed(docs)
    sims = D @ J.T
    k = min(3, sims.shape[1])
    return list(np.sort(sims, axis=1)[:, -k:].mean(axis=1))


def ranks(scores: list[float]) -> list[float]:
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    r = [0.0] * len(scores)
    for pos, i in enumerate(order):
        r[i] = 1 - pos / max(1, len(scores) - 1)
    return r


def top(scores: list[float], k: int) -> list[int]:
    return sorted(range(len(scores)), key=lambda i: -scores[i])[:k]


# --- run ------------------------------------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    master = MASTER.read_text()
    projects = master_projects(master)
    skills = master_skills(master)
    docs = [p["text"] for p in projects]
    results = []
    for d in sorted(p for p in TAILORED.iterdir() if (p / "resume.md").exists() and (p / "research.md").exists()):
        resume, job = (d / "resume.md").read_text(), job_text((d / "research.md").read_text())
        mapped = [title_match(t, projects) for t in tailored_projects(resume)]
        ai = [i for i in dict.fromkeys(mapped) if i is not None]
        if not ai:
            continue
        k = len(ai)
        kw, em = tfidf_scores(job, docs), embed_scores(job, docs)
        hy = [a + b for a, b in zip(ranks(kw), ranks(em))]
        ai_skill_text = tailored_skills_text(resume).lower()
        ai_skills = {i for i, s in enumerate(skills) if s.lower() in ai_skill_text}
        sk_kw, sk_em = tfidf_scores(job, skills), embed_scores(job, skills)
        sk_hy = [a + b for a, b in zip(ranks(sk_kw), ranks(sk_em))]
        row = {"job": d.name, "k": k, "unmapped": sum(m is None for m in mapped), "n_projects": len(projects),
               "ai": [projects[i]["title"] for i in ai], "ai_skills": len(ai_skills)}
        for name, sc, ssc in (("keyword", kw, sk_kw), ("meaning", em, sk_em), ("hybrid", hy, sk_hy)):
            pick = top(sc, k)
            row[name] = {
                "overlap": len(set(pick) & set(ai)) / k,
                "first_in_topk": ai[0] in pick,
                "picked": [projects[i]["title"] for i in pick],
                "skills_overlap": (len(set(top(ssc, len(ai_skills))) & ai_skills) / len(ai_skills)) if ai_skills else None,
            }
        row["random"] = k / len(projects)
        row["random_skills"] = (len(ai_skills) / len(skills)) if skills else None
        results.append(row)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "browser_parity.json").write_text(json.dumps(results, indent=2))

    def mean(xs):
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else float("nan")
    print(f"jobs={len(results)} master_projects={len(projects)} master_skills={len(skills)} "
          f"unmapped_titles={sum(r['unmapped'] for r in results)}")
    print(f"{'method':<9} {'project overlap':>16} {'AI #1 in top-k':>15} {'skills overlap':>15}")
    print(f"{'random':<9} {mean(r['random'] for r in results):>16.0%} {'':>15} {mean(r['random_skills'] for r in results):>15.0%}")
    for m in ("keyword", "meaning", "hybrid"):
        print(f"{m:<9} {mean(r[m]['overlap'] for r in results):>16.0%} "
              f"{mean(float(r[m]['first_in_topk']) for r in results):>15.0%} "
              f"{mean(r[m]['skills_overlap'] for r in results):>15.0%}")
    print(f"\nper-job detail: {args.out / 'browser_parity.json'}")


if __name__ == "__main__":
    main()
