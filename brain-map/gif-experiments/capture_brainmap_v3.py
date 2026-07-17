#!/usr/bin/env python3
"""Headless capture v3: native autoRotate + native camera-easing toward
whichever node just pulsed (both behaviors are gated on `!dragging`, so this
deliberately never touches the mouse — unlike v2's manual drag, which
silently disabled the easing). Records each frame's actual yaw so a later
pass can trim to the frame whose yaw is closest to (start_yaw + 2*pi),
giving a seamless loop without guessing a fixed duration in advance."""
import json
import math
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

FRAMES_DIR = Path("/private/tmp/claude-501/-Users-gileskayo/be77c549-8390-4112-9f3a-f7e8c41c333b/scratchpad/brain_map_frames_v3")
YAW_LOG = FRAMES_DIR.parent / "yaw_log_v3.json"
URL = "http://127.0.0.1:8791/index.html?wallpaper=1"
VIEWPORT = {"width": 1100, "height": 850}
ZOOM_WHEEL_STEPS = 7
CAPTURE_INTERVAL = 0.22   # real seconds between frames
MAX_DURATION = 185.0      # safety cap; native full rotation is ~131s but
                          # easing periods can add or subtract some of that

PULSE_SEQUENCE = ["diagnose", "research", "creative", "self-improve",
                  "resume-tailor", "daily-digest", "qa-knowledge"]

def build_events():
    events = []
    def cycle(start_t, gap=3.2):
        t = start_t
        for skill in PULSE_SEQUENCE:
            events.append((t, "pulse", skill))
            t += gap
        events.append((t + 5.0, "add", None))
        events.append((t + 9.0, "remove", None))
        return t + 12.0
    t = build_events_first = cycle(4.0)
    cycle(t + 20.0)
    return sorted(events)

def main():
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    for f in FRAMES_DIR.glob("*.png"):
        f.unlink()

    events = build_events()
    fired = [False] * len(events)
    yaw_log = []

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
        target_yaw = start_yaw + 2 * math.pi
        print(f"start_yaw={start_yaw:.4f} target={target_yaw:.4f}")

        start = time.monotonic()
        i = 0
        # unwrap yaw so it's monotonically comparable to target_yaw even
        # though the page's own yaw value doesn't wrap (it keeps
        # increasing/decreasing per the code we read), so this is direct.
        while True:
            elapsed = time.monotonic() - start
            if elapsed >= MAX_DURATION:
                print("hit MAX_DURATION safety cap")
                break
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
            cur_yaw = page.evaluate("() => window.getYaw()")
            yaw_log.append(cur_yaw)
            if cur_yaw >= target_yaw and elapsed > 30:
                print(f"reached target yaw at frame {i}, elapsed={elapsed:.1f}s")
                break
            i += 1
            time.sleep(CAPTURE_INTERVAL)

        browser.close()

    YAW_LOG.write_text(json.dumps({"start_yaw": start_yaw, "target_yaw": target_yaw, "yaws": yaw_log}))
    print(f"Captured {len(yaw_log)} frames over {time.monotonic() - start:.1f}s -> {FRAMES_DIR}")

if __name__ == "__main__":
    main()
