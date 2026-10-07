// Recovery — the decisions behind a self-healing wallpaper (#136), kept free
// of AppKit so tests/RecoveryTests.swift can check them with plain values.
//
// reconcile (#175): given the screens now present and the windows we have,
// what to create, resize or remove so each screen has exactly one window
// matching its frame.
//
// Liveness (#176): which windows' pages have stopped drawing. The page
// counts the frames it really draws; a count that hasn't changed for
// `limit` seconds means the page is frozen or gone.

import CoreGraphics
import Foundation

struct ScreenInfo: Equatable {
    let id: UInt32      // CGDirectDisplayID — stable for a display across arrangement changes
    let name: String
    let frame: CGRect
}

struct WallpaperPlan: Equatable, CustomStringConvertible {
    var create: [ScreenInfo] = []
    var resize: [ScreenInfo] = []
    var remove: [UInt32] = []

    var isEmpty: Bool { create.isEmpty && resize.isEmpty && remove.isEmpty }
    var description: String {
        "create=\(create.map(\.name)) resize=\(resize.map(\.name)) remove=\(remove)"
    }
}

/// `windows`: display id → the frame of the window we hold for it.
func reconcile(screens: [ScreenInfo], windows: [UInt32: CGRect]) -> WallpaperPlan {
    var plan = WallpaperPlan()
    for screen in screens {
        guard let frame = windows[screen.id] else { plan.create.append(screen); continue }
        if frame != screen.frame { plan.resize.append(screen) }
    }
    let present = Set(screens.map(\.id))
    plan.remove = windows.keys.filter { !present.contains($0) }.sorted()
    return plan
}

final class Liveness {
    let limit: TimeInterval
    private var lastFrames: [String: Int] = [:]
    private var lastProgress: [String: Date] = [:]
    private var paused = false

    init(limit: TimeInterval) { self.limit = limit }

    /// A window's page (re)started loading: give it a full `limit` to draw.
    func start(_ key: String, at now: Date) {
        lastFrames[key] = nil
        lastProgress[key] = now
    }

    /// The page reported its drawn-frame count. Any change counts as progress
    /// (a reload restarts it at 0).
    func report(_ key: String, frames: Int, at now: Date) {
        guard lastProgress[key] != nil else { return }
        if lastFrames[key] != frames {
            lastFrames[key] = frames
            lastProgress[key] = now
        }
    }

    func forget(_ key: String) {
        lastFrames[key] = nil
        lastProgress[key] = nil
    }

    /// Screens asleep: pages aren't expected to draw.
    func pause() { paused = true }

    /// Screens awake again: every page gets a full `limit` from now.
    func resume(at now: Date) {
        paused = false
        for key in lastProgress.keys { lastProgress[key] = now }
    }

    func stalled(at now: Date) -> [(key: String, seconds: TimeInterval)] {
        guard !paused else { return [] }
        return lastProgress
            .map { (key: $0.key, seconds: now.timeIntervalSince($0.value)) }
            .filter { $0.seconds > limit }
            .sorted { $0.key < $1.key }
    }
}
