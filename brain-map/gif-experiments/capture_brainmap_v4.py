#!/usr/bin/env python3
"""v4: two sequential segments, both using native autoRotate/easing (never
touches the mouse, so nothing suppresses the app's own behavior):

  Segment A ("the tour"): pure auto-rotate, no pulses -> one full, smooth
  360-degree sweep. Trimmed by yaw-readback to the exact frame where it
  returns to start_yaw, so segment A alone is already a seamless loop.

  Segment B ("the showcase"): starting from segment A's end position, fires
  the same activity-pulse/add/remove sequence as demo.py. The camera eases
  toward whichever node just lit up (this is why v2/v3's manual mouse-drag
  approach was wrong -- easing is gated on !dragging). After the last event,
  auto-rotate keeps running undisturbed for a tail window; segment B is
  trimmed wherever yaw in that tail comes closest back to segment A's start
  position, so the whole A+B sequence loops seamlessly end-to-end.
"""
import json
import math
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

FRAMES_DIR = Path("/private/tmp/claude-501/-Users-gileskayo/be77c549-8390-4112-9f3a-f7e8c41c333b/scratchpad/brain_map_frames_v4")
META_PATH = FRAMES_DIR.parent / "capture_v4_meta.json"
URL = "http://127.0.0.1:8791/index.html?wallpaper=1"
VIEWPORT = {"width": 1100, "height": 850}
ZOOM_WHEEL_STEPS = 7
CAPTURE_INTERVAL = 0.24
SEG_A_MAX = 160.0
SEG_B_TAIL = 18.0       # extra auto-rotate-only seconds after the last event,
                        # to search for a clean return to the loop point

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
    return sorted(events), t + 8.0  # last scheduled time

def capture_loop(page, frames, yaws, i, elapsed_offset, start_t,
                  events=None, fired=None, stop_fn=None):
    while True:
        elapsed = time.monotonic() - start_t
        if events is not None:
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
        yaws.append(cur_yaw)
        i += 1
        if stop_fn and stop_fn(elapsed, cur_yaw, i):
            break
        time.sleep(CAPTURE_INTERVAL)
    return i

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
        target_yaw = start_yaw + 2 * math.pi
        print(f"segment A: start_yaw={start_yaw:.4f} target={target_yaw:.4f}")

        t0 = time.monotonic()
        def stop_a(elapsed, cur_yaw, i):
            if elapsed >= SEG_A_MAX:
                print("segment A hit safety cap"); return True
            return cur_yaw >= target_yaw and elapsed > 30
        seg_a_end_i = capture_loop(page, FRAMES_DIR, yaws, i, 0, t0, stop_fn=stop_a)
        seg_a_end_yaw = yaws[-1]
        print(f"segment A done at frame {seg_a_end_i}, yaw={seg_a_end_yaw:.4f}")

        events, last_event_t = build_segment_b_events()
        fired = [False] * len(events)
        t1 = time.monotonic()
        tail_start_t = last_event_t
        def stop_b(elapsed, cur_yaw, i):
            if elapsed < tail_start_t:
                return False
            if elapsed >= tail_start_t + SEG_B_TAIL:
                return True
            return False
        seg_b_end_i = capture_loop(page, FRAMES_DIR, yaws, seg_a_end_i, 0, t1,
                                    events=events, fired=fired, stop_fn=stop_b)
        print(f"segment B done at frame {seg_b_end_i}")

        browser.close()

    META_PATH.write_text(json.dumps({
        "start_yaw": start_yaw,
        "seg_a_end_frame": seg_a_end_i,
        "seg_a_end_yaw": seg_a_end_yaw,
        "seg_b_tail_start_frame": None,
        "yaws": yaws,
    }))
    print(f"Total {len(yaws)} frames -> {FRAMES_DIR}")

if __name__ == "__main__":
    main()
