#!/usr/bin/env python3
"""Draws the three diagrams in docs/life-of-a-ticket.md as SVG (re-run after a fix to recolor a box):

    ~/.agents/venv/bin/python ~/.agents/docs/diagrams/make_pipeline_diagrams.py

Colors carry meaning everywhere: GREEN works on its own, AMBER works but needs a person or is fragile,
RED is a known problem (each red box is listed in the doc), GRAY is planned, not built.
"""
from __future__ import annotations
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent
FILL = {"ok": "#dcfce7", "warn": "#fef3c7", "bad": "#fee2e2", "plan": "#f3f4f6", "you": "#e0e7ff"}
EDGE = {"ok": "#16a34a", "warn": "#d97706", "bad": "#dc2626", "plan": "#9ca3af", "you": "#4f46e5"}
FONT = "font-family='-apple-system, Segoe UI, Helvetica, Arial, sans-serif'"


class Svg:
    def __init__(self, w, h, title):
        self.w, self.h, self.parts = w, h, []
        self.parts.append(f"<rect width='{w}' height='{h}' fill='white'/>")
        self.text(w / 2, 34, title, 24, weight="700")

    def text(self, x, y, s, size=15, color="#111827", anchor="middle", weight="400"):
        self.parts.append(f"<text x='{x}' y='{y}' {FONT} font-size='{size}' font-weight='{weight}' fill='{color}' "
                          f"text-anchor='{anchor}'>{escape(s)}</text>")

    def box(self, x, y, w, h, lines, kind="ok", size=15, bold_first=True):
        self.parts.append(f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='10' fill='{FILL[kind]}' "
                          f"stroke='{EDGE[kind]}' stroke-width='{3 if kind == 'bad' else 2}'/>")
        lh = size + 5
        top = y + h / 2 - (len(lines) - 1) * lh / 2 + size / 3
        for i, ln in enumerate(lines):
            self.text(x + w / 2, top + i * lh, ln, size if i else size + 1, weight="700" if (i == 0 and bold_first) else "400")

    def arrow(self, x1, y1, x2, y2, color="#374151", label=None, dash=False, lx=None, ly=None, anchor="middle"):
        d = " stroke-dasharray='7 5'" if dash else ""
        self.parts.append(f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' stroke='{color}' stroke-width='2.5'{d} "
                          f"marker-end='url(#a{color[1:]})'/>")
        if label:
            self.text(lx if lx is not None else (x1 + x2) / 2, ly if ly is not None else (y1 + y2) / 2 - 6, label, 13, color, anchor)

    def path(self, d, color="#374151", label=None, lx=0, ly=0, anchor="middle", dash=True):
        dd = " stroke-dasharray='7 5'" if dash else ""
        self.parts.append(f"<path d='{d}' fill='none' stroke='{color}' stroke-width='2.5'{dd} marker-end='url(#a{color[1:]})'/>")
        if label:
            self.text(lx, ly, label, 13, color, anchor)

    def save(self, name):
        colors = {"#374151", "#dc2626", "#d97706", "#16a34a", "#4f46e5", "#9ca3af"}
        markers = "".join(f"<marker id='a{c[1:]}' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' "
                          f"orient='auto-start-reverse'><path d='M0,0 L10,5 L0,10 z' fill='{c}'/></marker>" for c in colors)
        svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='{self.w}' height='{self.h}' viewBox='0 0 {self.w} {self.h}'>"
               f"<defs>{markers}</defs>{''.join(self.parts)}</svg>\n")
        (OUT / name).write_text(svg)

    def legend(self, y):
        x = 40
        for kind, label in (("ok", "Works on its own"), ("warn", "Works, but needs you or is fragile"),
                            ("bad", "Known problem (listed in the doc)"), ("plan", "Planned, not built"), ("you", "Your step")):
            self.parts.append(f"<rect x='{x}' y='{y - 14}' width='22' height='18' rx='4' fill='{FILL[kind]}' stroke='{EDGE[kind]}' stroke-width='2'/>")
            self.text(x + 30, y, label, 14, anchor="start")
            x += 60 + len(label) * 7.2


# ── 1. The life of a ticket, start to finish, with every loop ──────────────────────────────────────────────

def life():
    s = Svg(1240, 2010, "The life of a MARVIN ticket — start to finish, with every loop back")
    s.legend(66)
    X, W, H = 330, 420, 74      # the main path runs down the middle
    steps = [
        ("1  IDEA", ["You notice something, a digest or sweep", "suggests it, or a session finds a bug"], "warn"),
        ("2  TICKET FILED", ["A GitHub issue with acceptance criteria,", "a project: label and 'Blocked by' links"], "ok"),
        ("3  TRIAGE  (hourly)", ["ready-for-agent / ready-for-human /", "needs-info — decided by the triage agent"], "ok"),
        ("4  PRIORITIZE  (hourly)", ["priority:p0–p3 from what it unblocks,", "due dates, bug-ness, age"], "warn"),
        ("5  SCAN + CLAIM  (hourly, mini)", ["picks the top unclaimed, unblocked ticket", "and labels it claimed:<machine>"], "ok"),
        ("6  BUILD  (an agent, own worktree)", ["plan → write code + tests → commit", "on branch pipeline/<repo>#<n>"], "ok"),
        ("7  VERIFY", ["the project's own tests and checks", "must pass before anything leaves"], "ok"),
        ("8  PR RAISED", ["evidence in the PR body: metrics,", "tests, 'Closes #n'"], "ok"),
        ("9  MR REVIEW  (dashboard)", ["one card per PR: one headline,", "only the buttons that make sense"], "warn"),
        ("10  YOU APPROVE", ["the one human step on the main path"], "you"),
        ("11  MERGE GATE", ["behind main AND shares files? rebase + retest;", "otherwise merge directly (ADR 0061)"], "ok"),
        ("12  MERGED TO MAIN", ["GitHub closes the ticket"], "ok"),
        ("13  AFTER THE MERGE", ["stacked PRs move onto main, other PRs get a", "conflict check, the app rebuilds, main-health runs"], "warn"),
        ("14  RUNNING ON BOTH MACS", ["code_sync pulls it within ~30 min;", "long-running servers restart on rebuild"], "bad"),
        ("15  PROVES ITS PURPOSE", ["a purpose metric is checked after a date", "(✅ met / ❌ missed → new ticket)"], "plan"),
    ]
    ys = []
    y = 100
    for title, lines, kind in steps:
        s.box(X, y, W, H, [title, *lines], kind, 14)
        ys.append(y)
        y += H + 52
    for i in range(len(steps) - 1):
        s.arrow(X + W / 2, ys[i] + H, X + W / 2, ys[i + 1] - 4)

    R = X + W + 40               # loop boxes on the right
    RW = 360
    L = 30                       # problem / human boxes on the left
    LW = 260

    lanes = iter((R + RW + 22, R + RW + 42, R + RW + 62))   # each loop gets its own straight lane on the right

    def right(i, lines, kind, back_to, label, dy=0):
        by = ys[i] + dy
        s.box(R, by, RW, 74, lines, kind, 13)
        s.arrow(X + W, ys[i] + H / 2, R - 4, by + 37)
        if back_to is not None:
            lane = next(lanes)
            ty = ys[back_to] + 14 + 22 * ((lane - R - RW - 22) // 20)   # each loop enters at its own height
            color = EDGE[kind] if kind != "ok" else "#374151"
            s.path(f"M {R + RW} {by + 37} H {lane} V {ty} H {X + W + 6}", color)
            s.text(lane - 6, ty - 8, f"↩ {label}", 13, color, "end", "700")

    right(2, ["needs-info", "the agent comments what's missing;", "you answer → back to triage"], "warn", None, None)
    right(6, ["TESTS FAIL", "the agent fixes and re-runs; after the", "attempt budget → failure breaker"], "warn", 5, "retry")
    right(8, ["YOU DENY", "the reason goes back to the ticket;", "refeed re-queues it (propose-only!)"], "bad", 4, "rebuild (denied)")
    right(10, ["CONFLICT / CI FAIL", "cheap repair first (both-sides-added);", "real conflict → sent back"], "warn", 4, "rebuild (conflict)", dy=10)
    right(12, ["MAIN GOES RED", "main-health refuses all merges", "until main is fixed"], "warn", None, None)

    def left(i, lines, kind, dy=0):
        by = ys[i] + dy
        s.box(L, by, LW, 74, lines, kind, 13)
        s.arrow(L + LW, by + 37, X - 4, ys[i] + H / 2, EDGE[kind])

    left(0, ["SESSIONS OVERLAP", "two tabs + the pipeline built", "the same fixes (fix: #326)"], "bad")
    left(3, ["STUCK BEHIND YOU", "chains wait on ready-for-human", "tickets (e.g. #153 push key)"], "bad")
    left(4, ["STALE CLAIMS", "a claim that outlives its run blocks", "a rebuild (agent is propose-only)"], "bad")
    left(8, ["APPROVE IS MANUAL", "every PR waits for you, even", "low-risk green ones"], "bad")
    left(13, ["SYNC COLLISIONS", "generated metrics files collide", "in code_sync stashes (#280)"], "bad")
    left(12, ["UI BUGS REACH MAIN", "no screenshot / UI test before", "merge (#126); hooks rule now tested"], "bad")
    # the whole cycle closes: a missed purpose becomes a new idea
    s.path(f"M {X} {ys[-1] + H / 2} H {X - 18} V {ys[0] + H - 12} H {X - 4}", EDGE["plan"])
    s.text(X - 24, ys[-1] + H / 2 + 22, "↩ missed? it becomes a new ticket", 13, EDGE["plan"], "end", "700")
    s.save("life-of-a-ticket.svg")


# ── 2. The architecture: where each part runs ──────────────────────────────────────────────────────────────

def architecture():
    s = Svg(1240, 940, "MARVIN's architecture — what runs where, and what talks to what")
    s.legend(66)
    # machines
    def machine(x, y, w, h, name, sub):
        s.parts.append(f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='16' fill='#f9fafb' stroke='#6b7280' stroke-width='2'/>")
        s.text(x + w / 2, y + 30, name, 19, weight="700")
        s.text(x + w / 2, y + 52, sub, 13, "#4b5563")
    machine(30, 95, 380, 640, "MacBook Pro (laptop)", "where you work; standby scanner")
    machine(830, 95, 380, 640, "Mac mini (primary host)", "runs the pipeline 24/7")
    machine(440, 95, 360, 470, "GitHub (shared truth)", "tickets, PRs, claims, main branch")

    s.box(55, 165, 330, 70, ["Claude sessions (you + MARVIN)", "interactive; hooks: session_work, gh gate"], "warn", 13)
    s.box(55, 250, 330, 70, ["Dashboard app", "Activity · MR Review · Docs · Metrics · Health"], "warn", 13)
    s.box(55, 335, 330, 70, ["Merge server (webhook :7878)", "Approve / Deny → merge gate"], "ok", 13)
    s.box(55, 420, 330, 70, ["Scanner (standby)", "runs only if the mini goes quiet"], "ok", 13)
    s.box(55, 505, 330, 70, ["gh gate (bin/gh)", "cooldowns, 20% floor, who-called log"], "ok", 13)
    s.box(55, 590, 330, 70, ["code_sync (every 30 min)", "commits + pulls ~/.agents and ~/.claude"], "bad", 13)

    s.box(855, 165, 330, 70, ["Ticket pipeline scanner (hourly)", "triage · prioritize · claim · dispatch"], "ok", 13)
    s.box(855, 250, 330, 70, ["Agent runs (run_ticket.py)", "own worktree · build · verify · PR"], "ok", 13)
    s.box(855, 335, 330, 70, ["Merge server (primary)", "gate · after-merge checks · rebuild"], "ok", 13)
    s.box(855, 420, 330, 70, ["main-health", "re-runs the suite on every main move"], "warn", 13)
    s.box(855, 505, 330, 70, ["Health checks + ticket agents", "stale_claims + refeed: propose-only"], "bad", 13)
    s.box(855, 590, 330, 70, ["Dashboard app + local models", "Ollama, FLUX; map snapshot deploy"], "warn", 13)

    s.box(465, 165, 310, 70, ["Issues = tickets", "labels carry state and claims"], "ok", 13)
    s.box(465, 250, 310, 70, ["Pull requests", "evidence, checks, stacked PRs"], "ok", 13)
    s.box(465, 335, 310, 70, ["main branch", "what both Macs run"], "ok", 13)
    s.box(465, 420, 310, 70, ["Shared allowance: 5,000/h", "both Macs + every job share it"], "warn", 13)

    s.arrow(385, 200, 461, 200, label="file / claim", ly=192)
    s.arrow(855, 200, 779, 200, label="triage, claim", ly=192)
    s.arrow(855, 285, 779, 285, label="push + PR", ly=277)
    s.arrow(385, 285, 461, 285, label="read (on change)", ly=277)
    s.arrow(855, 370, 779, 370, label="merge", ly=362)
    s.arrow(385, 370, 461, 370, label="merge", ly=362)
    s.arrow(620, 405, 620, 416)

    s.box(30, 770, 380, 80, ["MARVIN Mobile (iPhone)", "talks to the mini over Tailscale — building"], "plan", 14)
    s.box(440, 770, 360, 80, ["gileskayo.me", "map auto-publishes; pages: you promote"], "warn", 14)
    s.box(830, 770, 380, 80, ["Linux box / third node", "more capacity — planned"], "plan", 14)
    s.text(620, 900, "Tailscale connects the Macs (ssh gils-mac-mini). The laptop sleeps; the mini doesn't.", 14, "#4b5563")
    s.save("marvin-architecture.svg")


# ── 3. Where we are vs where you want to be ───────────────────────────────────────────────────────────────

def readiness():
    rows = [  # stage, how automatic today (0-100, my estimate), target, kind, note
        ("Ideas → tickets", 45, 85, "warn", "digests and sweeps suggest; most tickets still start from you"),
        ("Triage", 80, 95, "ok", "acting since 2026-10-09; needs-info waits for answers"),
        ("Prioritize", 40, 90, "warn", "still propose-only: scores are computed, not applied"),
        ("Dispatch (MARVIN)", 75, 95, "ok", "hourly on the mini; parallel dispatch built"),
        ("Dispatch (other projects)", 15, 85, "bad", "profiles ready, dispatch off for most"),
        ("Build + verify", 75, 90, "ok", "agents build and test in worktrees"),
        ("Review + approve", 10, 70, "bad", "every PR waits for you"),
        ("Merge + integrate", 70, 95, "warn", "gate + repair fixed today; edge cases still surfacing"),
        ("Deploy (both Macs, apps)", 45, 95, "bad", "30-min sync; app rebuild lags; server restarts"),
        ("Recovery (stale, sent back)", 30, 90, "bad", "stale_claims and refeed are propose-only"),
        ("Outcomes / purpose checks", 10, 80, "plan", "built (#304), few tickets carry a metric yet"),
        ("Goals → tickets (north stars)", 20, 80, "plan", "north stars guide planning; no goal loop yet"),
    ]
    s = Svg(1240, 150 + len(rows) * 58, "How close to 'constant flow' — today vs where you want to be (my estimate)")
    s.legend(66)
    x0, bw = 330, 520
    s.text(x0, 112, "0%", 13, "#6b7280", "start")
    s.text(x0 + bw, 112, "100% automatic", 13, "#6b7280", "end")
    for i, (stage, now, target, kind, note) in enumerate(rows):
        y = 130 + i * 58
        s.text(310, y + 24, stage, 15, anchor="end", weight="700")
        s.parts.append(f"<rect x='{x0}' y='{y + 6}' width='{bw}' height='26' rx='6' fill='#f3f4f6'/>")
        s.parts.append(f"<rect x='{x0}' y='{y + 6}' width='{bw * now / 100}' height='26' rx='6' fill='{EDGE[kind]}'/>")
        tx = x0 + bw * target / 100
        s.parts.append(f"<line x1='{tx}' y1='{y}' x2='{tx}' y2='{y + 38}' stroke='#111827' stroke-width='3'/>")
        s.text(x0 + 8, y + 25, f"{now}%", 13, "white" if now > 12 else "#111827", "start", "700")
        s.text(x0 + bw + 16, y + 24, note, 13, "#374151", "start")
    s.text(x0 + bw * 0.5, 130 + len(rows) * 58 + 12, "colored bar = today   ·   black line = where you want to be", 13, "#4b5563")
    s.save("flow-readiness.svg")


def diamond(s, cx, cy, w, h, lines, kind="warn", size=14):
    """A yes/no question."""
    pts = f"{cx},{cy - h / 2} {cx + w / 2},{cy} {cx},{cy + h / 2} {cx - w / 2},{cy}"
    s.parts.append(f"<polygon points='{pts}' fill='{FILL[kind]}' stroke='{EDGE[kind]}' stroke-width='2'/>")
    lh = size + 4
    top = cy - (len(lines) - 1) * lh / 2 + size / 3
    for i, ln in enumerate(lines):
        s.text(cx, top + i * lh, ln, size, weight="700" if i == 0 else "400")


# ── 4. Ticket states: the labels a ticket carries, and what moves it ─────────────────────────────────────

def states():
    s = Svg(1240, 760, "Ticket states — the labels a ticket carries, and what moves it along")
    s.legend(66)
    B = 74
    s.box(40, 110, 220, B, ["NEW", "just filed, no state"], "warn", 14)
    s.box(330, 110, 240, B, ["needs-info", "something's missing"], "warn", 14)
    s.box(330, 230, 240, B, ["ready-for-human", "needs you (login, choice)"], "you", 14)
    s.box(330, 350, 240, B, ["ready-for-agent", "an agent can build it"], "ok", 14)
    s.box(640, 350, 240, B, ["claimed:<machine>", "being built — hands off"], "ok", 14)
    s.box(950, 350, 250, B, ["PR open", "waiting for your Approve"], "warn", 14)
    s.box(950, 500, 250, B, ["MERGED → closed", "card moves to Done"], "ok", 14)
    s.box(640, 500, 240, B, ["needs-reengagement", "sent back: rebuild it"], "bad", 14)
    s.box(950, 640, 250, B, ["ARCHIVED", "whole board quiet 14 days"], "plan", 14)
    s.box(40, 350, 220, B, ["pinned / held", "agents never touch it"], "plan", 14)
    s.arrow(260, 147, 326, 147, label="triage", ly=139)
    s.arrow(260, 160, 326, 260, label="triage", lx=318, ly=215, anchor="start")
    s.arrow(260, 170, 326, 380, label="triage", lx=262, ly=330, anchor="end")
    s.path("M 450 110 V 92 H 150 V 106", "#d97706")
    s.text(300, 86, "you answer → triaged again", 13, "#d97706", weight="700")
    s.arrow(450, 304, 450, 346, "#4f46e5")
    s.arrow(570, 387, 636, 387, label="scan", ly=379)
    s.arrow(880, 387, 946, 387, label="PR raised", ly=379)
    s.arrow(1075, 424, 1075, 496, label="you Approve", lx=1085, ly=465, anchor="start")
    s.arrow(1075, 574, 1075, 636, "#9ca3af", "later", lx=1085, ly=612, anchor="start")
    s.arrow(1000, 424, 884, 520, "#dc2626", "deny / conflict / CI fail", lx=930, ly=455)
    s.path("M 640 537 H 600 V 400 H 574", "#dc2626", None)
    s.text(592, 470, "rebuild", 13, "#dc2626", "end", "700")
    s.text(620, 735, "A label is the ticket's state: the pipeline only ever reads labels, so what you see on GitHub is the truth.", 14, "#4b5563")
    s.save("ticket-states.svg")


# ── 5. Where the time goes in one ticket's life ──────────────────────────────────────────────────────────

def timeline():
    segs = [  # label, typical minutes (my estimate from logs), kind
        ("wait for triage", 30, "ok"), ("wait for a scan", 30, "ok"), ("build + verify", 25, "ok"),
        ("WAIT FOR YOUR APPROVE", 564, "bad"), ("merge gate", 2, "ok"), ("WAIT FOR DEPLOY", 45, "bad"),
    ]
    total = sum(m for _, m, _ in segs)
    s = Svg(1240, 420, "Where the time goes — one typical ticket, idea to running")
    s.legend(66)
    x, y, W = 40, 130, 1160
    for label, mins, kind in segs:
        w = max(W * mins / total, 4)
        s.parts.append(f"<rect x='{x}' y='{y}' width='{w}' height='70' fill='{EDGE[kind]}' stroke='white' stroke-width='2'/>")
        if w > 90:
            s.text(x + w / 2, y + 32, label, 14, "white", weight="700")
            s.text(x + w / 2, y + 52, f"~{mins / 60:.1f} h (measured median)" if mins >= 120 else f"~{mins} min", 13, "white")
        x += w
    s.text(40, 240, "Small slices (left): triage ~30 min, scan ~30 min, build ~25 min, merge ~2 min — the machine parts are fast.", 15, "#111827", "start")
    s.text(40, 270, "Big slices (red): waiting for Approve (median 9.4 h over the last 46 pipeline PRs) and for the code to reach both Macs.", 15, "#dc2626", "start", "700")
    s.text(40, 300, "So: the fastest way to more flow is not faster agents, it is less waiting (auto-merge for low-risk PRs, deploy on merge).", 15, "#111827", "start")
    s.text(40, 360, "Approve wait is measured (PR opened → merged, 2026-10-02 to 10-09). The other slices are estimates: hourly scans, 10–40 min builds, 30-min sync.", 13, "#6b7280", "start")
    s.save("where-time-goes.svg")


# ── 6. The merge gate: the questions Approve asks ────────────────────────────────────────────────────────

def gate():
    s = Svg(1240, 1060, "The merge gate — the questions it asks when you press Approve")
    s.legend(66)
    cx = 470
    qs = [(170, ["Does it target main?"]), (310, ["Was its ticket", "sent back?"]), (450, ["Do its GitHub", "checks pass?"]),
          (590, ["Is it behind main?"]), (730, ["Did main change", "files it changes?"])]
    for cy, lines in qs:
        diamond(s, cx, cy, 300, 100, lines)
    for i in range(len(qs) - 1):
        s.arrow(cx, qs[i][0] + 50, cx, qs[i + 1][0] - 52, label="yes" if i != 1 else "no", lx=cx + 12, ly=(qs[i][0] + qs[i + 1][0]) / 2 + 4, anchor="start")
    R = 760
    s.box(R, 135, 430, 70, ["REFUSED: WRONG_BASE", "stacked PR: merge its parent first (moves itself)"], "warn", 13)
    s.box(R, 275, 430, 70, ["REFUSED: SENT_BACK", "a rebuild will update this same PR"], "warn", 13)
    s.box(R, 415, 430, 70, ["WAIT (running) or SENT BACK (failed)", "failing checks go back to the ticket"], "warn", 13)
    s.box(40, 555, 250, 70, ["MERGE NOW", "seconds"], "ok", 14)
    s.box(40, 695, 250, 70, ["MERGE NOW", "'no retest needed'"], "ok", 14)
    s.box(R, 695, 430, 70, ["REBASE + RETEST", "the full suite on the rebased branch (≤ 40 min)"], "ok", 13)
    s.arrow(cx + 150, 170, R - 4, 170, label="no", ly=162)
    s.arrow(cx + 150, 310, R - 4, 310, label="yes", ly=302)
    s.arrow(cx + 150, 450, R - 4, 450, label="no", ly=442)
    s.arrow(cx - 150, 590, 294, 590, label="no", ly=582)
    s.arrow(cx - 150, 730, 294, 730, label="no", ly=722)
    s.arrow(cx + 150, 730, R - 4, 730, label="yes", ly=722)
    diamond(s, 975, 860, 300, 100, ["Do the tests pass?"], "warn")
    s.arrow(975, 765, 975, 808)
    s.box(40, 900, 330, 70, ["MERGE", "then everything in 'After the merge'"], "ok", 14)
    s.box(R, 960, 430, 70, ["NOT MERGED", "main already red? → MAIN_RED, nothing sent back; else sent back"], "bad", 12)
    s.arrow(825, 860, 374, 935, label="yes", lx=600, ly=890)
    s.arrow(975, 910, 975, 956, label="no", lx=985, ly=940, anchor="start")
    s.text(620, 1050, "Can't tell if files overlap? It retests, to be safe. The machine broke, not the code? GATE_INFRA: approve again.", 13, "#4b5563")
    s.save("merge-gate.svg")


# ── 7. After the merge, in order ─────────────────────────────────────────────────────────────────────────

def after_merge():
    s = Svg(1240, 600, "After the merge — what happens on its own, in order")
    s.legend(66)
    steps = [
        ("1  STACKED PRs MOVE", ["a PR built on this one is", "pointed at main"], "ok"),
        ("2  CONFLICT CHECK", ["every other open PR, in", "seconds (no tests, no push)"], "ok"),
        ("3  APP REBUILDS", ["if dashboard/ changed;", "merge server restarts"], "warn"),
        ("4  MAIN-HEALTH", ["the full suite on main;", "red = merges refused"], "warn"),
        ("5  NEXT SCAN", ["the next ticket starts", "right away"], "ok"),
    ]
    x, y, w, h = 30, 130, 220, 110
    for i, (t, lines, kind) in enumerate(steps):
        s.box(x + i * 240, y, w, h, [t, *lines], kind, 13)
        if i:
            s.arrow(x + i * 240 - 18, y + h / 2, x + i * 240 - 4, y + h / 2)
    s.box(30, 300, 460, 80, ["SAFETY NET for step 1", "MR Review's refresh moves any PR whose parent merged"], "ok", 13)
    s.box(510, 300, 460, 80, ["IF STEP 2 FINDS A CONFLICT", "the hourly scan tries the cheap repair first"], "ok", 13)
    s.box(30, 410, 460, 80, ["🔴 Laptop + mini get the code", "via code_sync, every 30 min (slow)"], "bad", 13)
    s.box(510, 410, 460, 80, ["🔴 Mini app didn't relaunch once", "after a rebuild (2026-10-09)"], "bad", 13)
    s.arrow(140, 240, 140, 296, "#16a34a")
    s.arrow(390, 240, 690, 296, "#16a34a")
    s.text(620, 560, "Steps 1–5 take minutes. What's slow is step 0: the new code reaching every Mac and every long-running program.", 14, "#4b5563")
    s.save("after-merge.svg")


# ── 8. When a PR conflicts ───────────────────────────────────────────────────────────────────────────────

def conflicts():
    s = Svg(1240, 760, "When a PR conflicts with main — cheap repair first, then who does what")
    s.legend(66)
    s.box(470, 110, 300, 70, ["GitHub: CONFLICTING", "found by the after-merge check or the scan"], "warn", 13)
    s.box(420, 230, 400, 80, ["CHEAP REPAIR (conflict_repair.py)", "rebase in a scratch copy; resolve only safe conflicts:", "generated files · already on main · both only ADDED"], "ok", 12)
    s.arrow(620, 180, 620, 226)
    diamond(s, 620, 400, 300, 100, ["All conflicts safe,", "and tests pass?"], "warn")
    s.arrow(620, 310, 620, 348)
    s.box(940, 365, 270, 70, ["PUSHED ✅", "comment says what was resolved"], "ok", 13)
    s.arrow(770, 400, 936, 400, label="yes", ly=392)
    diamond(s, 620, 560, 300, 100, ["Made by the", "pipeline?"], "warn")
    s.arrow(620, 450, 620, 508, label="no (a real conflict)", lx=632, ly=485, anchor="start")
    s.box(940, 525, 270, 70, ["SENT BACK", "rebuilt on main; files named"], "warn", 13)
    s.box(30, 525, 300, 70, ["FLAGGED FOR YOU", "once per commit; never auto-rebuilt"], "you", 13)
    s.arrow(770, 560, 936, 560, label="yes", ly=552)
    s.arrow(470, 560, 334, 560, label="no (hand-made)", ly=552)
    s.text(620, 690, "Safe = nobody's existing line was changed on both sides. Anything else is a real conflict and is never papered over.", 14, "#4b5563")
    s.text(620, 715, "Max 2 repairs per scan (each runs the tests). A commit that failed a repair isn't retried; a new push gets a new try.", 13, "#6b7280")
    s.save("conflicts.svg")


if __name__ == "__main__":
    life()
    architecture()
    readiness()
    states()
    timeline()
    gate()
    after_merge()
    conflicts()
    print("wrote", ", ".join(p.name for p in sorted(OUT.glob("*.svg"))))
