// Plain assert-based tests for Recovery.swift (#175, #176). Run via ../test.sh.
import CoreGraphics
import Foundation

var failures = 0
func check(_ cond: Bool, _ msg: String, line: Int = #line) {
    if !cond { failures += 1; print("FAIL line \(line): \(msg)") }
}

let builtIn = ScreenInfo(id: 1, name: "Built-in Retina Display", frame: CGRect(x: 0, y: 0, width: 1440, height: 900))
let external = ScreenInfo(id: 2, name: "LG UltraFine", frame: CGRect(x: 1440, y: 0, width: 2560, height: 1440))

// ── reconcile: screens in, windows out ───────────────────────────────────

// Nothing changed: nothing to do (the 60-a-second identical display-change bursts land here).
check(reconcile(screens: [builtIn, external], windows: [1: builtIn.frame, 2: external.frame]).isEmpty, "unchanged screens need no rebuild")

// A display attached: one new window for it, the existing one left alone.
let attached = reconcile(screens: [builtIn, external], windows: [1: builtIn.frame])
check(attached == WallpaperPlan(create: [external]), "attach creates one window: \(attached)")

// A display removed: its window goes.
let removed = reconcile(screens: [builtIn], windows: [1: builtIn.frame, 2: external.frame])
check(removed == WallpaperPlan(remove: [2]), "detach removes its window: \(removed)")

// A screen whose frame changed (resolution, arrangement): its window is resized to match.
let bigger = ScreenInfo(id: 1, name: builtIn.name, frame: CGRect(x: 0, y: 0, width: 1728, height: 1117))
let resized = reconcile(screens: [bigger], windows: [1: builtIn.frame])
check(resized == WallpaperPlan(resize: [bigger]), "changed frame resizes: \(resized)")

// No windows at all (every screen was gone at some point): one per screen, in screen order.
let fresh = reconcile(screens: [builtIn, external], windows: [:])
check(fresh == WallpaperPlan(create: [builtIn, external]), "empty start creates one per screen: \(fresh)")

// ── liveness: a page that stops drawing is noticed ───────────────────────

let t0 = Date(timeIntervalSince1970: 1_791_300_000)
let live = Liveness(limit: 20)
live.start("w1", at: t0)
check(live.stalled(at: t0.addingTimeInterval(19)).isEmpty, "inside the limit after start is fine")
check(live.stalled(at: t0.addingTimeInterval(21)).map(\.key) == ["w1"], "no frame for longer than the limit is stalled")

// Frames arriving keep it alive; the same count again is not progress.
live.start("w1", at: t0)
live.report("w1", frames: 10, at: t0.addingTimeInterval(5))
live.report("w1", frames: 10, at: t0.addingTimeInterval(24))
check(live.stalled(at: t0.addingTimeInterval(24)).isEmpty, "last new frame 19s ago is within the limit")
let stuck = live.stalled(at: t0.addingTimeInterval(26))
check(stuck.map(\.key) == ["w1"] && Int(stuck[0].seconds) == 21, "a repeated count is not a drawn frame: \(stuck)")

// A reload restarts the counter at 0; a lower count is still a change.
live.start("w1", at: t0)
live.report("w1", frames: 500, at: t0.addingTimeInterval(1))
live.report("w1", frames: 1, at: t0.addingTimeInterval(15))
check(live.stalled(at: t0.addingTimeInterval(30)).isEmpty, "a counter reset counts as progress")

// While the screens sleep nothing is judged; waking restarts every clock.
live.start("w1", at: t0)
live.pause()
check(live.stalled(at: t0.addingTimeInterval(600)).isEmpty, "paused (screens asleep): never stalled")
live.resume(at: t0.addingTimeInterval(600))
check(live.stalled(at: t0.addingTimeInterval(615)).isEmpty, "after wake the page gets a full limit again")
check(live.stalled(at: t0.addingTimeInterval(621)).map(\.key) == ["w1"], "and is judged once that passes")

// A forgotten window (removed by reconcile) is never reported.
live.forget("w1")
check(live.stalled(at: t0.addingTimeInterval(10_000)).isEmpty, "forgotten window not reported")

if failures > 0 { print("\(failures) failure(s)"); exit(1) }
print("RecoveryTests: all passed")
