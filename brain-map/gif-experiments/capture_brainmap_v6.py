#!/usr/bin/env python3
"""v6: segment A unchanged (deterministic exact 2*pi sweep via setYaw).
Segment B redesigned per feedback:
  - a dense multi-node "christmas tree" cascade (many real nodes across every
    category, overlapping pulses) instead of one skill at a time
  - a real branch-with-sub-branches grow-in, held, then deleted as a whole
    clump (demoAddNode supports nested .children, so one call blooms a
    small multi-level subtree; demoRemoveNode on the top id removes all of it)
  - denser sampling (0.1s vs v5's 0.22s) so the camera's easing lerp is
    actually captured smoothly instead of skipped over
Still never touches the mouse, so autoRotate + real camera-easing stay live.
"""
import json
import math
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

FRAMES_DIR = Path("/private/tmp/claude-501/-Users-gileskayo/be77c549-8390-4112-9f3a-f7e8c41c333b/scratchpad/brain_map_frames_v6")
META_PATH = FRAMES_DIR.parent / "capture_v6_meta.json"
URL = "http://127.0.0.1:8791/index.html?wallpaper=1"
VIEWPORT = {"width": 1100, "height": 850}
ZOOM_WHEEL_STEPS = 7
N_SEG_A = 420
SEG_A_SETTLE = 0.045
CAPTURE_INTERVAL_B = 0.1
SEG_B_TAIL = 16.0

CASCADE = [
    "diagnose", "audit", "tdd", "qa-agent", "grill-with-docs",
    "improve-codebase-architecture", "research", "paper-dive", "zoom-out",
    "research-colony", "creative", "prototype", "improve",
    "handoff", "index", "self-improve", "architecture-review",
    "write-a-skill", "caveman", "lexicon", "route",
    "setup-matt-pocock-skills", "triage", "to-issues", "to-prd", "resume-tailor",
    "daily-digest", "rebuild-manifest.py", "skill_activity.py",
    "background_review.py", "trigger_code_sync.py", "cron-health",
    "exo", "mac-mini-1", "macbook-pro-1", "task-dispatch",
]
CASCADE_GAP = 0.5

BRANCH_NODE = {
    "id": "demo-showcase-branch", "cat": "quality",
    "desc": "Synthetic demo branch for the README capture.",
    "children": [
        {"id": "demo-leaf-1", "cat": "quality", "desc": "Synthetic demo leaf.", "children": []},
        {
            "id": "demo-leaf-2", "cat": "quality", "desc": "Synthetic demo leaf.",
            "children": [
                {"id": "demo-leaf-2a", "cat": "quality", "desc": "Synthetic demo grandchild.", "children": []},
                {"id": "demo-leaf-2b", "cat": "quality", "desc": "Synthetic demo grandchild.", "children": []},
            ],
        },
        {"id": "demo-leaf-3", "cat": "quality", "desc": "Synthetic demo leaf.", "children": []},
    ],
}

def build_segment_b_events():
    events = []
    t = 2.0
    for skill in CASCADE:
        events.append((t, "pulse", skill))
        t += CASCADE_GAP
    t += 1.5
    events.append((t, "add_branch", None)); t += 4.5
    events.append((t, "remove_branch", None)); t += 3.5
    return events, t

def main():
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    for f in FRAMES_DIR.glob("*.png"):
        f.unlink()

    yaws = []
    i = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
        page.goto(URL)
        page.wait_for_timeout(1000)
        for _ in range(ZOOM_WHEEL_STEPS):
            page.mouse.wheel(0, 200)
            page.wait_for_timeout(20)
        page.wait_for_timeout(300)

        start_yaw = page.evaluate("() => window.getYaw()")
        print(f"start_yaw={start_yaw:.4f}")

        t_a0 = time.monotonic()
        for k in range(N_SEG_A):
            target = start_yaw + (2 * math.pi) * (k / N_SEG_A)
            page.evaluate("(v) => window.setYaw(v)", target)
            time.sleep(SEG_A_SETTLE)
            page.screenshot(path=str(FRAMES_DIR / f"frame_{i:05d}.png"))
            yaws.append(page.evaluate("() => window.getYaw()"))
            i += 1
        seg_a_end_i = i
        print(f"segment A done: {seg_a_end_i} frames in {time.monotonic()-t_a0:.1f}s")

        events, last_event_t = build_segment_b_events()
        fired = [False] * len(events)
        t_b0 = time.monotonic()
        while True:
            elapsed = time.monotonic() - t_b0
            for ei, (t, kind, arg) in enumerate(events):
                if not fired[ei] and elapsed >= t:
                    fired[ei] = True
                    if kind == "pulse":
                        page.evaluate("(s) => window.triggerActivity(s)", arg)
                    elif kind == "add_branch":
                        page.evaluate("(a) => window.demoAddNode(a[0], a[1])", [BRANCH_NODE, "Quality"])
                    elif kind == "remove_branch":
                        page.evaluate("(id) => window.demoRemoveNode(id)", BRANCH_NODE["id"])
            page.screenshot(path=str(FRAMES_DIR / f"frame_{i:05d}.png"))
            yaws.append(page.evaluate("() => window.getYaw()"))
            i += 1
            if elapsed >= last_event_t + SEG_B_TAIL:
                break
            time.sleep(CAPTURE_INTERVAL_B)
        print(f"segment B done: total {i} frames, seg B elapsed {time.monotonic()-t_b0:.1f}s")

        browser.close()

    META_PATH.write_text(json.dumps({
        "start_yaw": start_yaw,
        "seg_a_end_frame": seg_a_end_i,
        "yaws": yaws,
    }))
    print(f"Total {len(yaws)} frames -> {FRAMES_DIR}")

if __name__ == "__main__":
    main()
