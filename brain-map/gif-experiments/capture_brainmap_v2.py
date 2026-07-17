#!/usr/bin/env python3
"""Headless capture v2: deterministic yaw control (via simulated drag) instead
of relying on the page's own real-time autoRotate. This guarantees an exact,
seamless 360-degree loop (frame N-1 -> frame 0 is the same angular step as any
other pair) and decouples rotation smoothness/speed from screenshot overhead
or timing jitter. Nothing real touched — same guarantee as demo.py, this only
calls the page's own exposed demo hooks plus synthetic mouse events."""
import math
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

FRAMES_DIR = Path("/private/tmp/claude-501/-Users-gileskayo/be77c549-8390-4112-9f3a-f7e8c41c333b/scratchpad/brain_map_frames_v2")
URL = "http://127.0.0.1:8791/index.html?wallpaper=1"
N_FRAMES = 900          # frames per full 360 rotation -> 0.4 deg/frame
STEP_DELAY = 0.09       # real seconds between steps (paces pulse animations)
YAW_PER_PIXEL = 0.006   # from index.html's mousemove handler
VIEWPORT = {"width": 1100, "height": 850}
ZOOM_WHEEL_STEPS = 7    # matches the tested no-clip zoom level
CANVAS_CENTER = (550, 425)

PULSE_SEQUENCE = ["diagnose", "research", "creative", "self-improve",
                  "resume-tailor", "daily-digest", "qa-knowledge"]

def build_events():
    """(step_index, kind, arg) — spread across the loop by fraction, twice."""
    events = []
    def cycle(start_frac):
        t = start_frac
        for skill in PULSE_SEQUENCE:
            events.append((int(t * N_FRAMES), "pulse", skill))
            t += 0.03
        events.append((int((t + 0.05) * N_FRAMES), "add", None))
        events.append((int((t + 0.09) * N_FRAMES), "remove", None))
    cycle(0.03)
    cycle(0.55)
    return sorted(events)

def main():
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    for f in FRAMES_DIR.glob("*.png"):
        f.unlink()

    events = build_events()
    fired = [False] * len(events)

    dx_per_step = (2 * math.pi / N_FRAMES) / YAW_PER_PIXEL

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
        page.goto(URL)
        page.wait_for_timeout(1000)

        for _ in range(ZOOM_WHEEL_STEPS):
            page.mouse.wheel(0, 200)
            page.wait_for_timeout(20)
        page.wait_for_timeout(300)

        x, y = CANVAS_CENTER
        page.mouse.move(x, y)
        page.mouse.down()

        start = time.monotonic()
        for i in range(N_FRAMES):
            for ei, (step, kind, arg) in enumerate(events):
                if not fired[ei] and i >= step:
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
            if i < N_FRAMES - 1:
                x += dx_per_step
                page.mouse.move(x, y)
                time.sleep(STEP_DELAY)

        page.mouse.up()
        browser.close()

    print(f"Captured {N_FRAMES} frames over {time.monotonic() - start:.1f}s -> {FRAMES_DIR}")

if __name__ == "__main__":
    main()
