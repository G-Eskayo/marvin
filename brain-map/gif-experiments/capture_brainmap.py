#!/usr/bin/env python3
"""Headless capture of the brain-map wallpaper view: full auto-rotation +
scripted activity pulses + a synthetic node grow/shrink, as a PNG frame
sequence for later ffmpeg -> GIF conversion. Nothing real touched (same
guarantee as demo.py) — this only calls the page's own exposed demo hooks."""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

FRAMES_DIR = Path("/private/tmp/claude-501/-Users-gileskayo/be77c549-8390-4112-9f3a-f7e8c41c333b/scratchpad/brain_map_frames")
URL = "http://127.0.0.1:8791/index.html?wallpaper=1"
TOTAL_DURATION = 136.0  # > one full 360 rotation at yaw += 0.0008 rad/frame (~131s)
FRAME_INTERVAL = 0.12

PULSE_SEQUENCE = ["diagnose", "research", "creative", "self-improve",
                  "resume-tailor", "daily-digest", "qa-knowledge"]

def build_events():
    events = []
    t = 3.0
    for skill in PULSE_SEQUENCE:
        events.append((t, "pulse", skill))
        t += 3.0
    events.append((t + 6.0, "add", None))
    events.append((t + 10.0, "remove", None))
    # second lap so pulses show up from different camera angles too
    t2 = 72.0
    for skill in PULSE_SEQUENCE:
        events.append((t2, "pulse", skill))
        t2 += 3.0
    events.append((t2 + 6.0, "add", None))
    events.append((t2 + 10.0, "remove", None))
    return sorted(events)

def main():
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    for f in FRAMES_DIR.glob("*.png"):
        f.unlink()

    events = build_events()
    fired = [False] * len(events)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 900, "height": 700}, device_scale_factor=2)
        page.goto(URL)
        page.wait_for_timeout(1500)

        start = time.monotonic()
        frame_idx = 0
        while True:
            elapsed = time.monotonic() - start
            if elapsed >= TOTAL_DURATION:
                break
            for i, (t, kind, arg) in enumerate(events):
                if not fired[i] and elapsed >= t:
                    fired[i] = True
                    if kind == "pulse":
                        page.evaluate("(s) => window.triggerActivity(s)", arg)
                    elif kind == "add":
                        page.evaluate("""() => window.demoAddNode({
                            id: 'demo-showcase-node', cat: 'quality',
                            desc: 'Synthetic demo node for the README capture.'
                        }, 'Quality')""")
                    elif kind == "remove":
                        page.evaluate("() => window.demoRemoveNode('demo-showcase-node')")
            page.screenshot(path=str(FRAMES_DIR / f"frame_{frame_idx:05d}.png"))
            frame_idx += 1
            time.sleep(FRAME_INTERVAL)

        browser.close()

    print(f"Captured {frame_idx} frames over {time.monotonic() - start:.1f}s -> {FRAMES_DIR}")

if __name__ == "__main__":
    main()
