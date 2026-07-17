#!/usr/bin/env python3
"""v5: segment A drives yaw directly via window.setYaw (instant, exact 2*pi
sweep, independent of the browser's actual rAF rate) -- setYaw doesn't touch
`dragging`, so it doesn't disable anything, it just repositions the camera
before each screenshot. Segment B switches to native autoRotate + the real
activity-pulse/camera-easing behavior (never touches the mouse), continuing
from wherever segment A left off. Segment B's tail (after the last event) is
over-captured so a later pass can trim to the frame whose yaw lands closest
back to segment A's start, closing the loop seamlessly."""
import json
import math
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

FRAMES_DIR = Path("/private/tmp/claude-501/-Users-gileskayo/be77c549-8390-4112-9f3a-f7e8c41c333b/scratchpad/brain_map_frames_v5")
META_PATH = FRAMES_DIR.parent / "capture_v5_meta.json"
URL = "http://127.0.0.1:8791/index.html?wallpaper=1"
VIEWPORT = {"width": 1100, "height": 850}
ZOOM_WHEEL_STEPS = 7
N_SEG_A = 420             # frames for the exact 360 sweep
SEG_A_SETTLE = 0.045      # real seconds to let a repaint happen after setYaw
CAPTURE_INTERVAL_B = 0.22
SEG_B_TAIL = 18.0

PULSE_SEQUENCE = ["diagnose", "research", "creative", "self-improve",
                  "resume-tailor", "daily-digest", "qa-knowledge"]

def build_segment_b_events():
    events = []
    t = 3.0
    for skill in PULSE_SEQUENCE:
        events.append((t, "pulse", skill))
        t += 3.4
    events.append((t + 4.0, "add", None))
    events.append((t + 8.0, "remove", None))
    return sorted(events), t + 8.0

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

        # ---- segment A: deterministic exact 2*pi sweep ----
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

        # ---- segment B: native autoRotate + real pulse easing ----
        events, last_event_t = build_segment_b_events()
        fired = [False] * len(events)
        t_b0 = time.monotonic()
        tail_start_t = last_event_t
        while True:
            elapsed = time.monotonic() - t_b0
            for ei, (t, kind, arg) in enumerate(events):
                if not fired[ei] and elapsed >= t:
                    fired[ei] = True
                    if kind == "pulse":
                        page.evaluate("(s) => window.triggerActivity(s)", arg)
                    elif kind == "add":
                        page.evaluate("""() => window.demoAddNode({
                            id: 'demo-showcase-node', cat: 'quality',
                            desc: 'Synthetic demo node for the README capture.'
                        }, 'Quality')""")
                    elif kind == "remove":
                        page.evaluate("() => window.demoRemoveNode('demo-showcase-node')")
            page.screenshot(path=str(FRAMES_DIR / f"frame_{i:05d}.png"))
            yaws.append(page.evaluate("() => window.getYaw()"))
            i += 1
            if elapsed >= tail_start_t + SEG_B_TAIL:
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
