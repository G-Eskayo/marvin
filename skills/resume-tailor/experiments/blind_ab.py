#!/usr/bin/env python3
"""Blind A/B: does a reader prefer the AI-tailored resume over the in-browser "matched" one, and by how much?

`build` makes, for a spread of past jobs, the browser-matched resume (keyword TF-IDF + project priority, w = 0.5,
exactly what the website would do; priorities simulated leave-one-out from the AI's other picks), renders it and the
AI's resume with the SAME render_pdf.py template, randomly labels them X/Y, and writes a local rating page. The key
is stored apart from the page. `score` reads the ratings file the page downloads and unblinds.

    ~/.agents/venv/bin/python blind_ab.py build
    ~/.agents/venv/bin/python blind_ab.py score ~/Downloads/resume-blind-ratings.json

Everything stays in ~/.claude/resume/experiments/blind/ (resume content, never committed).
"""
from __future__ import annotations

import argparse
import html
import json
import random
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import browser_parity as bp  # noqa: E402

JOBS = ["davita-ai-software-engineer-2026-07-31", "home-depot-2026-07-22", "google-2026-08-04",
        "york-space-systems-2026-08-09", "tokin-jew-2026-09-03", "checkpoint-ai-security-2026-08-10"]
BLIND = bp.OUT / "blind"
KEY = bp.OUT / "blind-key.json"  # outside the page's folder on purpose
RENDER = Path(__file__).resolve().parents[1] / "scripts" / "render_pdf.py"
PY = Path.home() / ".agents" / "venv" / "bin" / "python"
W = 0.5


def is_stack_line(b: str) -> bool:
    """A tech-stack line ("Python, gRPC, MLX, Tailscale") rather than an accomplishment."""
    return b.count(",") / max(1, len(b.split())) > 0.2 or "|" in b


def bullets(text: str) -> list[str]:
    """Accomplishment bullets, with unfinished placeholders like [Project Link] removed (the public export does the same)."""
    out = [re.sub(r"\s*\[[^\]]*\]", "", l[2:]).strip(" |") for l in text.splitlines() if l.startswith("- ")]
    return [b for b in out if b and not is_stack_line(b)]


def ai_parts(resume: str) -> tuple[list[str], list[str]]:
    """(header lines without the summary paragraph, the trailing sections Education/Training/Achievements)."""
    lines = resume.splitlines()
    pe = next(i for i, l in enumerate(lines) if l.upper().startswith("## PROFESSIONAL EXPERIENCE"))
    head = lines[:pe]
    while head and not head[-1].strip():
        head.pop()
    while head and head[-1].strip():  # drop the AI's tailored summary paragraph
        head.pop()
    ed = next(i for i, l in enumerate(lines) if l.upper().startswith("## EDUCATION"))
    return head, lines[ed:]


def browser_resume(name: str, ai_resume: str, priors: list[float]) -> str:
    master = bp.strip_comments(bp.MASTER.read_text())
    sec = dict(bp.sections(master, "## "))
    job = bp.job_text((bp.TAILORED / name / "research.md").read_text())
    projects = bp.master_projects(bp.MASTER.read_text())
    k = len([i for i in dict.fromkeys(bp.title_match(t, projects) for t in bp.tailored_projects(ai_resume)) if i is not None])
    score = [r + W * p for r, p in zip(bp.ranks(bp.tfidf_scores(job, [p["text"] for p in projects])), priors)]
    picks = bp.top(score, k)

    summary = " ".join(re.split(r"(?<=[.!?])\s+", " ".join(sec["Summary"].split()))[:2])
    charter = next(b for h, b in bp.sections(sec["Professional Experience"], "### ") if h.startswith("Charter"))
    cb = bullets(charter)
    cb = [cb[i] for i in bp.top(bp.tfidf_scores(job, cb), 3)]

    cats = bp.sections(sec["Technical Skills"], "### ")
    terms = bp.master_skills(bp.MASTER.read_text())
    chosen = {terms[i] for i in bp.top(bp.tfidf_scores(job, terms), 16)}
    skill_lines = []
    for cat, body in cats:
        got = [t for t in terms if t in chosen and t in body]
        if got:
            skill_lines.append(f"• **{cat} –** {', '.join(got)}")
    soft = [s.strip() for s in " ".join(sec["Soft Skills"].split()).split(",")][:6]

    head, tail = ai_parts(ai_resume)
    out = head + ["", summary, "", "## PROFESSIONAL EXPERIENCE", "",
                  "**Charter Communications** *AI Engineer, April 2026–Present*", ""]
    out += [f"• {b}\n" for b in cb]
    out += ["## TECHNICAL SKILLS", ""] + [l + "\n" for l in skill_lines]
    out += ["## SOFT SKILLS", "", "  ·  ".join(soft), "", "## PROJECTS", ""]
    for i in picks:
        p = projects[i]
        pb = bullets(p["text"])
        out += [f"**{p['title'].replace('*', '').strip()}**", ""] + [f"• {pb[j]}\n" for j in sorted(bp.top(bp.tfidf_scores(job, pb), 2))]
    return "\n".join(out + tail) + "\n"


def leave_one_out_priors(projects: list[dict], skip: str) -> list[float]:
    others = []
    for d in sorted(bp.TAILORED.iterdir()):
        if d.name == skip or not (d / "resume.md").exists():
            continue
        others.append({bp.title_match(t, projects) for t in bp.tailored_projects((d / "resume.md").read_text())})
    return [sum(i in o for o in others) / len(others) for i in range(len(projects))]


def render(md: Path, pdf: Path) -> None:
    subprocess.run([str(PY), str(RENDER), str(md), str(pdf)], check=True, capture_output=True)


def build() -> None:
    BLIND.mkdir(parents=True, exist_ok=True)
    projects = bp.master_projects(bp.MASTER.read_text())
    rng = random.Random()
    key, cards = {}, []
    for n, name in enumerate(JOBS, 1):
        ai = (bp.TAILORED / name / "resume.md").read_text()
        br = browser_resume(name, ai, leave_one_out_priors(projects, name))
        ai_is_x = rng.random() < 0.5
        x_md, y_md = (ai, br) if ai_is_x else (br, ai)
        for tag, md in (("X", x_md), ("Y", y_md)):
            src = BLIND / f"job{n}-{tag}.md"
            src.write_text(md)
            render(src, BLIND / f"job{n}-{tag}.pdf")
            src.unlink()  # the .md would give the answer away in Finder; only PDFs stay
        key[f"job{n}"] = {"name": name, "ai": "X" if ai_is_x else "Y"}
        job = bp.job_text((bp.TAILORED / name / "research.md").read_text())
        title = next((l.split(":", 1)[1].strip(" *") for l in (bp.TAILORED / name / "research.md").read_text().splitlines()
                      if l.lower().startswith("- **title")), name)
        cards.append((n, title, job))
    KEY.write_text(json.dumps(key, indent=2))
    (BLIND / "rate.html").write_text(page(cards))
    print(f"built {len(cards)} pairs → {BLIND / 'rate.html'}")


def page(cards) -> str:
    sections = []
    for n, title, job in cards:
        jl = "".join(f"<li>{html.escape(l.strip(' -*•'))}</li>" for l in job.splitlines() if len(l.strip()) > 3)
        sections.append(f"""
<section data-job="job{n}">
  <h2>Job {n}: {html.escape(title)}</h2>
  <details><summary>What the job asks for</summary><ul>{jl}</ul></details>
  <div class="pair">
    <figure><figcaption>Resume X</figcaption><iframe src="job{n}-X.pdf#view=FitH" title="Resume X"></iframe></figure>
    <figure><figcaption>Resume Y</figcaption><iframe src="job{n}-Y.pdf#view=FitH" title="Resume Y"></iframe></figure>
  </div>
  <fieldset><legend>Which would you rather send for this job?</legend>
    <label><input type="radio" name="job{n}" value="X"> X</label>
    <label><input type="radio" name="job{n}" value="tie"> About the same</label>
    <label><input type="radio" name="job{n}" value="Y"> Y</label>
  </fieldset>
  <fieldset><legend>How big is the difference?</legend>
    <label><input type="radio" name="job{n}-gap" value="1"> Small</label>
    <label><input type="radio" name="job{n}-gap" value="2"> Clear</label>
    <label><input type="radio" name="job{n}-gap" value="3"> Big</label>
  </fieldset>
  <textarea name="job{n}-note" rows="2" placeholder="Optional: what made the difference?"></textarea>
</section>""")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Resume Blind Test</title>
<style>
:root{{--bg:#fafaf9;--fg:#1c1917;--muted:#57534e;--card:#fff;--line:#e7e5e4;--accent:#2563eb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1c1917;--fg:#f5f5f4;--muted:#a8a29e;--card:#292524;--line:#44403c;--accent:#60a5fa}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}}
main{{max-width:1400px;margin:0 auto;padding:16px}}
section{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:16px 0}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:12px}} @media (max-width:800px){{.pair{{grid-template-columns:1fr}}}}
figure{{margin:0}} figcaption{{font-weight:600;margin-bottom:4px}} iframe{{width:100%;height:80vh;border:1px solid var(--line);border-radius:8px;background:#fff}}
fieldset{{border:0;padding:8px 0;margin:0}} legend{{font-weight:600}} label{{margin-right:16px;cursor:pointer}}
textarea{{width:100%;box-sizing:border-box;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:8px}}
.bar{{position:sticky;top:0;background:var(--bg);padding:8px 0;display:flex;gap:12px;align-items:center;border-bottom:1px solid var(--line)}}
button{{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:8px 16px;font-size:16px;cursor:pointer}}
p.muted{{color:var(--muted)}}
</style></head><body><main>
<h1>Resume blind test</h1>
<p class="muted">Each job has two resumes, X and Y. One was written by the AI resume tailor, one is the in-browser "matched" version. You don't know which. Pick the one you would rather send. Your answers are saved as you go; when done, press <b>Download my ratings</b> and tell Claude.</p>
<div class="bar"><span id="progress"></span><button id="dl">Download my ratings</button></div>
{''.join(sections)}
</main><script>
const KEY='resume-blind-ratings';
const load=()=>{{try{{return JSON.parse(localStorage.getItem(KEY)||'{{}}')}}catch{{return {{}}}}}};
const save=(v)=>{{try{{localStorage.setItem(KEY,JSON.stringify(v))}}catch{{}}}};
let state=load();
document.querySelectorAll('input,textarea').forEach(el=>{{
  const v=state[el.name]; if(el.type==='radio'){{if(v===el.value)el.checked=true}} else if(v)el.value=v;
  el.addEventListener('input',()=>{{state[el.name]=el.value;save(state);progress()}});
}});
function progress(){{const n=document.querySelectorAll('section').length;const d=[...document.querySelectorAll('section')].filter(s=>state[s.dataset.job]).length;document.getElementById('progress').textContent=`${{d}} of ${{n}} rated`}}
progress();
document.getElementById('dl').onclick=()=>{{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(state,null,2)],{{type:'application/json'}}));a.download='resume-blind-ratings.json';a.click()}};
</script></body></html>"""


def score(path: Path) -> None:
    ratings, key = json.loads(path.read_text()), json.loads(KEY.read_text())
    ai = br = tie = 0
    for job, k in key.items():
        pick = ratings.get(job)
        if pick is None:
            continue
        who = "tie" if pick == "tie" else ("AI" if pick == k["ai"] else "browser")
        ai += who == "AI"; br += who == "browser"; tie += who == "tie"
        print(f"{job} {k['name']:<45} preferred: {who:<8} gap: {ratings.get(job + '-gap', '?')}  {ratings.get(job + '-note', '')}")
    print(f"\nAI preferred {ai}, browser preferred {br}, about the same {tie}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    s = sub.add_parser("score"); s.add_argument("ratings", type=Path)
    a = ap.parse_args()
    build() if a.cmd == "build" else score(a.ratings)
