#!/usr/bin/env python3
"""Blind A/B for the prototype skill's aesthetics guidance (marvin#1116).

Does `skills/prototype/AESTHETICS.md` (Mode 2, "new design") make better-looking pages than no guidance, on the same
model? Anthropic's cookbook only shows screenshots, so this measures it:

    python3 bench/aesthetics_ab.py generate --reps 3          # pages with and without the guidance (claude -p)
    python3 bench/aesthetics_ab.py render                     # headless Chrome screenshots
    python3 bench/aesthetics_ab.py judge                      # blind pairwise judge, both orders
    python3 bench/aesthetics_ab.py sheet                      # blind sheet for the owner (sheet/index.html)
    python3 bench/aesthetics_ab.py unblind LRTL...            # the owner's picks, one letter per pair (L, R or T)
    python3 bench/aesthetics_ab.py report                     # judge tally + the "default look" counts

Model calls run under the bench's clean profile (`profiles/setup.sh`) with the system prompt replaced and no tools,
so the only difference between the arms is the guidance text. Every call's cost is logged; the run stops before
passing --budget (default $4.50). Output goes to bench/results/aesthetics/ (not committed).
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BENCH = Path(__file__).resolve().parent
REPO = BENCH.parent
SKILL_FILE = REPO / "skills" / "prototype" / "AESTHETICS.md"
OUT = BENCH / "results" / "aesthetics"
CLEAN = BENCH / "profiles" / "clean"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CONDITIONS = ("control", "treatment")

# The cookbook's base prompt, shortened. Same for both arms.
BASE = """You are an expert frontend engineer who builds beautiful, performant pages.
Write one complete, self-contained HTML file: vanilla HTML, CSS and JS. You may load Google Fonts and Tailwind from
their CDNs. Use realistic content, not lorem ipsum, and invent every name and contact detail (example.com addresses):
never use the account holder's own. Reply with the file in a single ```html block and nothing else."""

PROMPTS = {
    "landing": "A landing page for Tidepool, an app that tells sea kayakers when the tide, wind and swell line up "
               "for a safe paddle at their local launch spots.",
    "dashboard-card": "A dashboard card that shows one household's electricity use today: the total in kWh, the "
                      "hourly trend, the peak hour, and how today compares with the last 7 days. Centre the card "
                      "on the page.",
    "settings": "The settings screen of a note-taking app: account, sync, appearance (theme, font size), "
                "notifications and a danger zone to delete all notes.",
}

JUDGE_PROMPT = """Two web pages were made from the same brief by different designers. Look at both screenshots:
{a} is design A, {b} is design B (read both files).

Brief: {brief}

Which is the better design for this brief overall? Weigh typography, colour, layout, polish and how well it fits the
subject, and count readability and usability: a striking page that is hard to read or use is worse. Don't reward
length or the amount of content. Think briefly, then end with exactly one line: WINNER: A, WINNER: B or WINNER: TIE."""


# ── pure parts (tested) ─────────────────────────────────────────────────────

def guidance(path: Path = SKILL_FILE) -> str:
    """Mode 2 of the shipped skill file, from its heading to the Source line: exactly what the treatment sees."""
    text = path.read_text()
    m = re.search(r"^## Mode 2[^\n]*\n(.*?)(?=^Source:|\Z)", text, re.S | re.M)
    if not m or "<frontend_aesthetics>" not in m.group(1):
        raise SystemExit(f"aesthetics_ab: no Mode 2 section with <frontend_aesthetics> in {path}")
    return m.group(1).strip()


def extract_html(reply: str) -> str | None:
    blocks = re.findall(r"```html\s*\n(.*?)(?:```|\Z)", reply or "", re.S | re.I)
    if blocks:
        return max(blocks, key=len).strip()
    s = (reply or "").strip()
    return s if re.match(r"<!doctype html|<html", s, re.I) else None


GENERIC_FONTS = {"inter", "roboto", "arial", "helvetica", "helvetica neue", "open sans", "lato", "system", "default",
                 "system-ui", "-apple-system", "blinkmacsystemfont", "segoe ui", "sans-serif", "ui-sans-serif"}


def _first_family(decl: str, html: str = "") -> str:
    v = re.match(r"\s*var\(\s*(--[\w-]+)", decl)
    if v:
        d = re.search(re.escape(v.group(1)) + r"\s*:\s*([^;}]+)", html)
        if not d:
            return f"var({v.group(1)})"
        decl = d.group(1)
    first = decl.split(",")[0].strip().strip("'\"").strip()
    return first.lower()


def primary_font(html: str) -> str:
    """The body text's first font family: Tailwind config sans, then body/html CSS, then a font-sans class."""
    m = re.search(r"fontFamily\s*:\s*\{[^}]*?\b(?:sans|body)\s*:\s*\[\s*['\"]([^'\"]+)", html)
    if m:
        return m.group(1).strip().lower()
    for rule in re.finditer(r"(?<![\w.#:-])(?:body|html)\s*\{([^}]*)\}", html):
        d = re.search(r"font-family\s*:\s*([^;}]+)", rule.group(1))
        if d:
            return _first_family(d.group(1), html)
        d = re.search(r"\bfont\s*:\s*[^;}]*?\d(?:px|rem|em|%)(?:/[\d.]+\w*)?\s+([^;}]+)", rule.group(1))
        if d:
            return _first_family(d.group(1), html)
    if re.search(r"class=['\"][^'\"]*\bfont-sans\b", html):
        return "system"
    return "default"


def is_generic_font(font: str) -> bool:
    return font.lower() in GENERIC_FONTS


_PURPLE = r"(?:purple|violet|indigo|#667eea|#764ba2|#8b5cf6|#7c3aed|#6d28d9|#a855f7|#9333ea|#6366f1|#4f46e5)"


def has_purple_gradient(html: str) -> bool:
    if re.search(r"(?:linear|radial|conic)-gradient\([^;]*?" + _PURPLE, html, re.I):
        return True
    return bool(re.search(r"\b(?:from|via|to)-" + r"(?:purple|violet|indigo)-\d", html))


def parse_verdict(text: str) -> str | None:
    m = re.findall(r"WINNER\s*:\s*(A|B|TIE)\b", text or "", re.I)
    return m[-1].upper() if m else None


def tally(pairs) -> dict:
    """pairs: (verdict with treatment as A, verdict with treatment as B). A win needs both orders to agree."""
    t = {"treatment": 0, "control": 0, "tie": 0, "n": 0}
    for as_a, as_b in pairs:
        t["n"] += 1
        if as_a == "A" and as_b == "B":
            t["treatment"] += 1
        elif as_a == "B" and as_b == "A":
            t["control"] += 1
        else:
            t["tie"] += 1
    return t


def blind_sheet(pairs, rng: random.Random):
    """HTML for the owner with each pair's sides shuffled, and the key that unblinds it (kept in a separate file)."""
    key, rows = [], []
    for i, p in enumerate(pairs, 1):
        left, right = ("control", "treatment") if rng.random() < 0.5 else ("treatment", "control")
        key.append({"pair": i, "prompt": p["prompt"], "rep": p["rep"], "left": left, "right": right,
                    "left_src": p[left], "right_src": p[right]})
        rows.append(f"""<section><h2>Pair {i}</h2><p class="brief">{htmllib.escape(PROMPTS.get(p['prompt'], p['prompt']))}</p>
<div class="two"><figure><img src="p{i}-L.png" alt="Pair {i} left"><figcaption>L</figcaption></figure>
<figure><img src="p{i}-R.png" alt="Pair {i} right"><figcaption>R</figcaption></figure></div>
<p class="pick" data-pair="{i}"><button>L</button><button>T</button><button>R</button></p></section>""")
    page = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Blind design pairs</title>
<style>body{{margin:0;padding:16px;background:#f4f2ee;color:#151515;font:16px/1.5 Georgia,serif}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}@media(max-width:900px){{.two{{grid-template-columns:1fr}}}}
img{{width:100%;border:1px solid #ccc}}figure{{margin:0}}figcaption{{font-weight:700;text-align:center}}
.pick button{{font:inherit;padding:8px 18px;margin-right:6px}}.pick button.on{{background:#151515;color:#fff}}
#out{{position:sticky;bottom:0;background:#fff;padding:10px;border:1px solid #999;font-family:monospace}}</style>
<h1>Which design is better for its brief?</h1>
<p>For each pair pick L (left), R (right) or T (tie). The two sides are shuffled per pair. Then send the code at the
bottom back to MARVIN.</p>
{''.join(rows)}
<p id="out">Picks: <span id="code"></span></p>
<script>const picks={{}};document.querySelectorAll('.pick').forEach(p=>p.querySelectorAll('button').forEach(b=>
b.onclick=()=>{{picks[p.dataset.pair]=b.textContent;p.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));
const n={len(pairs)};let s='';for(let i=1;i<=n;i++)s+=picks[i]||'_';document.getElementById('code').textContent=s;}}));</script>"""
    return page, key


def unblind(picks: str, key) -> dict:
    picks = picks.strip().upper()
    if len(picks) != len(key) or set(picks) - set("LRT"):
        raise SystemExit(f"aesthetics_ab: need {len(key)} picks of L, R or T, got {picks!r}")
    t = {"treatment": 0, "control": 0, "tie": 0, "n": 0}
    for c, k in zip(picks, key):
        t["n"] += 1
        t["tie" if c == "T" else (k["left"] if c == "L" else k["right"])] += 1
    return t


# ── model calls, rendering, files ───────────────────────────────────────────

def _env():
    if not (CLEAN / ".credentials.json").exists():
        raise SystemExit("aesthetics_ab: no clean profile; run bench/profiles/setup.sh first")
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(CLEAN)}
    for k in list(env):
        if k.startswith("CLAUDE_CODE_") or k in ("CLAUDECODE", "CLAUDE_EFFORT"):
            env.pop(k, None)
    return env


def _spent() -> float:
    log = OUT / "costs.jsonl"
    if not log.exists():
        return 0.0
    return sum(json.loads(l).get("cost", 0) for l in log.read_text().splitlines() if l.strip())


def claude(prompt: str, system: str, model: str, tools: str, cwd: Path, label: str, budget: float) -> str:
    if _spent() >= budget:
        raise SystemExit(f"aesthetics_ab: stopped, ${_spent():.2f} spent of the ${budget:.2f} budget")
    cmd = ["claude", "-p", prompt, "--model", model, "--system-prompt", system, "--output-format", "json",
           "--tools", tools, "--no-session-persistence", "--strict-mcp-config"]
    if tools:
        cmd += ["--allowedTools", tools]
    p = subprocess.run(cmd, cwd=cwd, env=_env(), capture_output=True, text=True, timeout=900)
    try:
        d = json.loads(p.stdout)
    except json.JSONDecodeError:
        d = {"result": "", "total_cost_usd": 0, "error": (p.stderr or p.stdout)[-400:]}
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "costs.jsonl").open("a") as f:
        f.write(json.dumps({"call": label, "model": model, "cost": d.get("total_cost_usd", 0),
                            "usage": d.get("usage"), "error": d.get("error")}) + "\n")
    return d.get("result") or ""


def cmd_generate(a):
    g = guidance()
    work = Path(tempfile.mkdtemp(prefix="aesthetics-gen-"))  # empty cwd: no CLAUDE.md to pick up
    for rep in range(1, a.reps + 1):
        for name, brief in PROMPTS.items():
            for cond in CONDITIONS:
                f = OUT / name / f"{cond}-{rep}.html"
                if f.exists():
                    continue
                system = BASE if cond == "control" else BASE + "\n\n" + g
                page = extract_html(claude(brief, system, a.model, "", work, f"gen {name} {cond} {rep}", a.budget))
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(page or "<!-- no html in reply -->")
                print(f"{f.relative_to(OUT)}  {'ok' if page else 'NO HTML'}  spent ${_spent():.2f}", flush=True)


# One browser for every page (headless Chrome's --screenshot mode took 45 s a page here). playwright-core comes from
# the dashboard's node_modules, the same driver dashboard/scripts/capture_screenshot.mjs uses.
SHOOT_JS = r"""
const { createRequire } = await import('node:module');
const req = createRequire(process.env.PW_FROM);
const { chromium } = req('playwright-core');
const [w, h, ...files] = process.argv.slice(1);
const b = await chromium.launch({ executablePath: process.env.CHROME });
const pg = await b.newPage({ viewport: { width: +w, height: +h } });
for (const f of files) {
  try {
    await pg.goto('file://' + f, { waitUntil: 'networkidle', timeout: 20000 }).catch(() => {});
    await pg.waitForTimeout(3000);  // let the entrance animation finish
    await pg.screenshot({ path: f.replace(/\.html$/, '.png') });
    console.log('ok', f);
  } catch (e) { console.log('FAILED', f, String(e).slice(0, 200)); }
}
await b.close();
"""


def cmd_render(a):
    files = [str(f) for f in sorted(f for n in PROMPTS for f in (OUT / n).glob("*.html")) if a.force or not f.with_suffix(".png").exists()]
    if not files:
        return
    env = {**os.environ, "CHROME": CHROME,
           "PW_FROM": str(Path.home() / ".agents" / "dashboard" / "node_modules" / "_")}
    subprocess.run(["node", "--input-type=module", "-e", SHOOT_JS, str(a.width), str(a.height), *files],
                   env=env, timeout=60 * len(files))


def _pairs():
    out = []
    for name in PROMPTS:
        for c in sorted((OUT / name).glob("control-*.png")):
            rep = int(c.stem.split("-")[1])
            t = OUT / name / f"treatment-{rep}.png"
            if t.exists():
                out.append({"prompt": name, "rep": rep, "control": str(c.relative_to(OUT)),
                            "treatment": str(t.relative_to(OUT))})
    return out


def cmd_judge(a):
    verdicts = OUT / "verdicts.json"
    done = json.loads(verdicts.read_text()) if verdicts.exists() else {}
    for p in _pairs():
        for order in ("treatment-as-A", "treatment-as-B"):
            k = f"{p['prompt']}-{p['rep']}-{order}"
            if k in done:
                continue
            first, second = ("treatment", "control") if order == "treatment-as-A" else ("control", "treatment")
            d = Path(tempfile.mkdtemp(prefix="judge-"))  # neutral names: the judge never sees the condition
            shutil.copy(OUT / p[first], d / "A.png")
            shutil.copy(OUT / p[second], d / "B.png")
            text = claude(JUDGE_PROMPT.format(a=d / "A.png", b=d / "B.png", brief=PROMPTS[p["prompt"]]),
                          "You are a senior product designer reviewing work blind.", a.judge_model, "Read", d,
                          f"judge {k}", a.budget)
            done[k] = {"verdict": parse_verdict(text), "why": text[-600:]}
            verdicts.write_text(json.dumps(done, indent=1))
            print(k, done[k]["verdict"], f"spent ${_spent():.2f}", flush=True)
            shutil.rmtree(d, ignore_errors=True)


def cmd_sheet(a):
    pairs = _pairs()
    page, key = blind_sheet(pairs, random.Random(a.seed))
    d = OUT / "sheet"
    d.mkdir(parents=True, exist_ok=True)
    for k in key:
        shutil.copy(OUT / k["left_src"], d / f"p{k['pair']}-L.png")
        shutil.copy(OUT / k["right_src"], d / f"p{k['pair']}-R.png")
    (d / "index.html").write_text(page)
    (OUT / "sheet-key.json").write_text(json.dumps(key, indent=1))  # outside the sheet folder
    print(d / "index.html")


def cmd_unblind(a):
    print(json.dumps(unblind(a.picks, json.loads((OUT / "sheet-key.json").read_text()))))


def cmd_report(a):
    done = json.loads((OUT / "verdicts.json").read_text())
    rows, per = [], {}
    for p in _pairs():
        va = done.get(f"{p['prompt']}-{p['rep']}-treatment-as-A", {}).get("verdict")
        vb = done.get(f"{p['prompt']}-{p['rep']}-treatment-as-B", {}).get("verdict")
        rows.append((va, vb))
        per.setdefault(p["prompt"], []).append((va, vb))
    print("judge, all pairs:", tally(rows))
    for name, r in per.items():
        print(f"  {name}:", tally(r))
    raw = [v["verdict"] for v in done.values()]
    print("position check, verdicts by slot:", {s: raw.count(s) for s in ("A", "B", "TIE", None)})
    for cond in CONDITIONS:
        pages = [f.read_text() for f in sorted(OUT.glob(f"*/{cond}-*.html"))]
        fonts = [primary_font(h) for h in pages]
        print(f"{cond}: {len(pages)} pages, generic body font {sum(map(is_generic_font, fonts))}, "
              f"purple gradient {sum(map(has_purple_gradient, pages))}, distinct fonts {len(set(fonts))}: {fonts}")
    print(f"spent ${_spent():.2f}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--reps", type=int, default=3)
    g.add_argument("--model", default="sonnet")
    g.add_argument("--budget", type=float, default=4.5)
    r = sub.add_parser("render")
    r.add_argument("--width", type=int, default=1280)
    r.add_argument("--height", type=int, default=900)
    r.add_argument("--force", action="store_true")
    j = sub.add_parser("judge")
    j.add_argument("--judge-model", default="opus")
    j.add_argument("--budget", type=float, default=4.5)
    s = sub.add_parser("sheet")
    s.add_argument("--seed", type=int, default=1116)
    u = sub.add_parser("unblind")
    u.add_argument("picks")
    sub.add_parser("report")
    a = ap.parse_args(argv)
    {"generate": cmd_generate, "render": cmd_render, "judge": cmd_judge, "sheet": cmd_sheet,
     "unblind": cmd_unblind, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
