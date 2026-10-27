#!/usr/bin/env python3
"""Retrieval eval (marvin#705): for real MARVIN questions with known answers, which retriever puts the answer on top,
and how many tokens does an agent read to get it?

Why: CLAUDE.md says "for codebase questions, first run `graphify query`", and nobody had measured it. The research
(docs/research/knowledge-graphs-2026-10-26.md) found that LLM-judged comparisons swing by more than 30 points on answer
order alone. So this scores against known answers only: hit@1, hit@5, recall@5, MRR. No LLM anywhere.

Retrievers:
- rg: keywords from the question; a file scores by how many distinct keywords it contains, then by total hits. This
  is what an agent grepping does.
- graphify: `graphify query`, files in order of first mention.
- memory: `memory_graph.py related` (memory questions only).
- hybrid: reciprocal rank fusion of rg and graphify.

The question file names private memory notes, so it lives in the instance (bench/retrieval-questions.json), not here.

    retrieval_eval.py --questions FILE [--repo ~/.agents] [--memory-dir DIR] [--json OUT]
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
KINDS = ("code", "decision", "memory", "multihop")
K = 5
STOP = set("""a an the is are was were be being been do does did done to of in on at for by with from and or not no
what where which who whom whose why how when does do we our us i me my you your it its this that these those there here
into about over under than then so if else any some all each every can could should would will shall may might must
has have had get gets got make makes made use uses used find marvin""".split())


@dataclass
class Retrieved:
    ranked: list[str]
    tokens: int = 0
    error: str | None = field(default=None)


def keywords(question: str) -> list[str]:
    seen, out = set(), []
    for w in re.findall(r"[A-Za-z0-9_]+", question.lower()):
        if len(w) >= 3 and w not in STOP and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def _run(cmd: list[str], cwd: Path) -> str:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True, timeout=120,
                          stdin=subprocess.DEVNULL).stdout


def _failed(exc: Exception) -> Retrieved:
    extra = getattr(exc, "output", None) or getattr(exc, "stderr", None) or ""
    return Retrieved([], 0, f"{type(exc).__name__}: {exc} {str(extra).strip()[:200]}".strip())


def _rg() -> str:
    return shutil.which("rg") or "/opt/homebrew/bin/rg"


def rg_retrieve(question: str, root: Path) -> Retrieved:
    kws = keywords(question)
    if not kws:
        return Retrieved([])
    distinct: dict[str, int] = {}
    total: dict[str, int] = {}
    try:
        for kw in kws:
            # An explicit "." and a closed stdin: with neither, rg searches stdin and waits forever (2026-10-26)
            r = subprocess.run([_rg(), "-i", "-c", "-F", "--glob", "!graphify-out/**", "-e", kw, "."],
                               cwd=root, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
            for line in r.stdout.splitlines():
                path, _, n = line.rpartition(":")
                path = path[2:] if path.startswith("./") else path
                if path:
                    distinct[path] = distinct.get(path, 0) + 1
                    total[path] = total.get(path, 0) + int(n or 0)
        ranked = sorted(distinct, key=lambda p: (-distinct[p], -total[p], p))
        # tokens: the matching lines an agent would read in the top K files
        shown = subprocess.run([_rg(), "-i", "-n", "-F", *sum((["-e", k] for k in kws), []), *ranked[:K]],
                               cwd=root, capture_output=True, text=True, timeout=60,
                               stdin=subprocess.DEVNULL).stdout if ranked else ""
    except (OSError, subprocess.SubprocessError) as exc:
        return _failed(exc)
    return Retrieved(ranked, len(shown) // 4)


_SRC = re.compile(r"^NODE .*?\[src=([^ \]]*)")


def parse_graphify(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        m = _SRC.match(line)
        if m and m.group(1) and m.group(1) not in out:
            out.append(m.group(1))
    return out


def graphify_retrieve(question: str, root: Path) -> Retrieved:
    exe = os.environ.get("GRAPHIFY_BIN") or shutil.which("graphify") or str(Path.home() / ".local/bin/graphify")
    try:
        text = _run([exe, "query", question], root)
    except (OSError, subprocess.SubprocessError) as exc:
        return _failed(exc)
    return Retrieved(parse_graphify(text), len(text) // 4)


def memory_retrieve(question: str, memory_dir: Path) -> Retrieved:
    try:
        tool = os.environ.get("MARVIN_MEMORY_GRAPH") or str(ENGINE / "lib" / "memory_graph.py")
        text = _run([sys.executable, tool, "--dir", str(memory_dir),
                     "related", question, "--k", "10"], ENGINE)
    except (OSError, subprocess.SubprocessError) as exc:
        return _failed(exc)
    ranked = [f"memory:{line.split()[1]}" for line in text.splitlines() if len(line.split()) > 1]
    return Retrieved(ranked, len(text) // 4)


RETRIEVERS = {"rg": rg_retrieve, "graphify": graphify_retrieve, "memory": memory_retrieve}


def _dedupe(ranked: list[str]) -> list[str]:
    seen, out = set(), []
    for x in ranked:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def score(ranked: list[str], gold: set[str]) -> dict:
    r = _dedupe(ranked)
    first = next((i for i, x in enumerate(r) if x in gold), None)
    return {"hit@1": int(first == 0), "hit@5": int(first is not None and first < K),
            "recall@5": len(gold & set(r[:K])) / len(gold), "mrr": 0.0 if first is None else 1 / (first + 1)}


def rrf(lists: list[list[str]], k: int = 60) -> list[str]:
    """Reciprocal rank fusion: each list adds 1/(k + rank). Agreement between retrievers rises to the top."""
    s: dict[str, float] = {}
    for lst in lists:
        for i, x in enumerate(_dedupe(lst)):
            s[x] = s.get(x, 0) + 1 / (k + i + 1)
    return sorted(s, key=lambda x: (-s[x], x))


def load_questions(path: Path) -> list[dict]:
    qs = json.loads(Path(path).read_text())
    for q in qs:
        if not (q.get("id") and q.get("q") and q.get("kind") in KINDS and q.get("gold")):
            raise ValueError(f"question {q.get('id', '?')} needs id, q, kind ({'/'.join(KINDS)}) and a non-empty gold")
    return qs


def run(questions: list[dict], repo: Path, memory_dir: Path) -> dict:
    rows = []
    for q in questions:
        gold = set(q["gold"])
        memory = q["kind"] == "memory"
        got: dict[str, Retrieved] = {}
        rg = RETRIEVERS["rg"](q["q"], memory_dir if memory else repo)
        if memory:  # a memory note answers as memory:<slug>
            rg = Retrieved([x if x.startswith("memory:") else f"memory:{Path(x).stem}" for x in rg.ranked], rg.tokens, rg.error)
        got["rg"] = rg
        if memory:
            got["memory"] = RETRIEVERS["memory"](q["q"], memory_dir)
        else:
            got["graphify"] = RETRIEVERS["graphify"](q["q"], repo)
            got["hybrid"] = Retrieved(rrf([got["rg"].ranked, got["graphify"].ranked]),
                                      got["rg"].tokens + got["graphify"].tokens)
        for name, r in got.items():
            rows.append({"id": q["id"], "kind": q["kind"], "retriever": name, **score(r.ranked, gold),
                         "tokens": r.tokens, "top": r.ranked[:3], "error": r.error})
    summary: dict[str, dict] = {}
    for name in sorted({r["retriever"] for r in rows}):
        rs = [r for r in rows if r["retriever"] == name]
        n = len(rs)
        summary[name] = {"questions": n, **{m: round(sum(r[m] for r in rs) / n, 3) for m in ("hit@1", "hit@5", "recall@5", "mrr")},
                         "mean_tokens": round(sum(r["tokens"] for r in rs) / n), "errors": sum(1 for r in rs if r["error"])}
    return {"rows": rows, "summary": summary}


def render(out: dict) -> str:
    lines = ["| Retriever | Questions | hit@1 | hit@5 | recall@5 | MRR | Mean tokens | Errors |", "|---|---|---|---|---|---|---|---|"]
    for name, s in out["summary"].items():
        lines.append(f"| {name} | {s['questions']} | {s['hit@1']:.2f} | {s['hit@5']:.2f} | {s['recall@5']:.2f} | "
                     f"{s['mrr']:.2f} | {s['mean_tokens']} | {s['errors']} |")
    return "\n".join(lines)


def _cli(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--questions", required=True, type=Path)
    ap.add_argument("--repo", type=Path, default=Path.home() / ".agents")
    ap.add_argument("--memory-dir", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    if a.memory_dir is None:
        sys.path.insert(0, str(ENGINE / "lib"))
        import host_os
        a.memory_dir = host_os.memory_dir()
    out = run(load_questions(a.questions), a.repo, a.memory_dir)
    if a.json:
        a.json.write_text(json.dumps(out, indent=2))
    print(render(out))
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
