// DesktopLive — renders a local HTML file (the MARVIN brain map) as true
// desktop wallpaper: a borderless window pinned to the desktop window
// level, behind icons, with no dock icon and no menu-bar item at all.
//
// This is not a hack against anything private — NSWindow.Level and
// CGWindowLevelForKey are public AppKit/CoreGraphics API, the same
// mechanism third-party "live wallpaper" apps use. We're just not
// shipping the menu-bar extra, settings UI, or App Store wrapper around
// it, since none of that is needed for one fixed local file.
//
// Build:  swiftc -O main.swift -o DesktopLive
// Run:    ./DesktopLive [path-to-html]   (defaults to ../index.html)

import Cocoa
import WebKit

let htmlPath: String = {
    if CommandLine.arguments.count > 1 {
        return CommandLine.arguments[1]
    }
    // #filePath is a compile-time constant and shouldn't depend on how the
    // binary is later launched — but it did resolve differently under
    // launchd vs. a manual shell run (root "/" instead of the real compile
    // path). Using NSHomeDirectory() directly instead of trusting it.
    return NSHomeDirectory() + "/.agents/brain-map/index.html"
}()

let plainFileURL = URL(fileURLWithPath: htmlPath)
let readAccessDir = plainFileURL.deletingLastPathComponent()

// ?wallpaper=1 tells the page to hide its interactive chrome (legend, mode
// tabs, tooltip, footer) — none of it is clickable once the window ignores
// mouse events below, so leaving it visible just reads as a stray window.
var wallpaperComponents = URLComponents(url: plainFileURL, resolvingAgainstBaseURL: false)!
wallpaperComponents.query = "wallpaper=1"
let fileURL = wallpaperComponents.url ?? plainFileURL

guard FileManager.default.fileExists(atPath: fileURL.path) else {
    FileHandle.standardError.write("DesktopLive: no file at \(fileURL.path)\n".data(using: .utf8)!)
    exit(1)
}

final class DesktopWebView: WKWebView {
    // Wallpaper is looked at, not clicked — pass all mouse events through
    // to the desktop/icons underneath, exactly like a real wallpaper.
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
}

let activityURL = readAccessDir.appendingPathComponent("activity.jsonl")
let demoEventsURL = readAccessDir.appendingPathComponent("demo-events.jsonl")
let treeDataURL = readAccessDir.appendingPathComponent("tree-data.json")

final class AppDelegate: NSObject, NSApplicationDelegate {
    var windows: [NSWindow] = []
    var lastMTime: Date?
    var reloadTimer: Timer?
    var activityTimer: Timer?
    var demoTimer: Timer?
    var lastActivityLineCount = 0
    var lastDemoLineCount = 0

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory) // no Dock icon, no menu bar

        for screen in NSScreen.screens {
            let window = NSWindow(
                contentRect: screen.frame,
                styleMask: [.borderless],
                backing: .buffered,
                defer: false,
                screen: screen
            )
            // One level above the desktop picture itself, but still below
            // the desktop icons layer — the same slot real wallpaper apps use.
            let desktopLevel = Int(CGWindowLevelForKey(.desktopWindow))
            window.level = NSWindow.Level(rawValue: desktopLevel + 1)
            window.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle, .fullScreenAuxiliary]
            window.isOpaque = true
            window.backgroundColor = NSColor.black
            window.ignoresMouseEvents = true
            window.hasShadow = false

            let webView = DesktopWebView(frame: screen.frame)
            webView.setValue(false, forKey: "drawsBackground") // avoid a white flash before first paint
            webView.loadFileURL(fileURL, allowingReadAccessTo: readAccessDir)

            window.contentView = webView
            window.orderBack(nil)
            windows.append(window)
        }

        lastMTime = mtime()
        lastActivityLineCount = currentLines(activityURL).count
        lastDemoLineCount = currentLines(demoEventsURL).count
        // Cheap poll (a single stat() call), not continuous work — a real
        // update pushes fresh tree/synapses data in place (see
        // checkForUpdate) instead of reloading the page, so a real skill
        // being added/removed animates the same way the demo does instead
        // of the whole graph flashing back into existence.
        reloadTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            self?.checkForUpdate()
        }
        // Faster polls for activity/demo — small files, pushed into the
        // page directly via evaluateJavaScript rather than relying on the
        // page's own fetch() (unreliable for file:// origins across
        // WebKit versions — see template.html's comment on this).
        activityTimer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            self?.checkForActivity()
        }
        demoTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            self?.checkForDemoEvents()
        }
    }

    func mtime() -> Date? {
        (try? FileManager.default.attributesOfItem(atPath: treeDataURL.path))?[.modificationDate] as? Date
    }

    func checkForUpdate() {
        guard let m = mtime(), m != lastMTime else { return }
        lastMTime = m
        guard let data = try? Data(contentsOf: treeDataURL),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let treeJSON = try? JSONSerialization.data(withJSONObject: obj["tree"] ?? [:]),
              let synJSON = try? JSONSerialization.data(withJSONObject: obj["synapses"] ?? []) else {
            // tree-data.json didn't parse (e.g. generate.py mid-write) — fall
            // back to a full reload rather than silently staying stale.
            for window in windows {
                (window.contentView as? WKWebView)?.loadFileURL(fileURL, allowingReadAccessTo: readAccessDir)
            }
            return
        }
        let treeStr = String(data: treeJSON, encoding: .utf8) ?? "{}"
        let synStr = String(data: synJSON, encoding: .utf8) ?? "[]"
        let js = "if (window.updateTreeData) window.updateTreeData(\(treeStr), \(synStr));"
        for window in windows {
            (window.contentView as? WKWebView)?.evaluateJavaScript(js, completionHandler: nil)
        }
    }

    func currentLines(_ url: URL) -> [String] {
        guard let text = try? String(contentsOf: url, encoding: .utf8) else { return [] }
        return text.split(separator: "\n").map(String.init)
    }

    func checkForActivity() {
        let lines = currentLines(activityURL)
        guard lines.count > lastActivityLineCount else {
            if lines.count < lastActivityLineCount { lastActivityLineCount = lines.count } // trimmed/rotated
            return
        }
        let newLines = lines[lastActivityLineCount...]
        lastActivityLineCount = lines.count
        for line in newLines {
            guard let data = line.data(using: .utf8),
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let skill = obj["skill"] as? String else { continue }
            let escaped = skill.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "'", with: "\\'")
            let js = "if (window.triggerActivity) window.triggerActivity('\(escaped)');"
            for window in windows {
                (window.contentView as? WKWebView)?.evaluateJavaScript(js, completionHandler: nil)
            }
        }
    }

    // demo.py writes {"type":"add","node":{...},"parent":"..."} or
    // {"type":"remove","id":"..."} — a lighter channel than a full
    // tree-data.json regeneration, purely for showing the animation live
    // without touching any real skill file.
    func checkForDemoEvents() {
        let lines = currentLines(demoEventsURL)
        guard lines.count > lastDemoLineCount else {
            if lines.count < lastDemoLineCount { lastDemoLineCount = lines.count }
            return
        }
        let newLines = lines[lastDemoLineCount...]
        lastDemoLineCount = lines.count
        for line in newLines {
            guard let data = line.data(using: .utf8),
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let type = obj["type"] as? String else { continue }
            var js = ""
            if type == "add", let node = obj["node"], let parent = obj["parent"] as? String,
               let nodeJSON = try? JSONSerialization.data(withJSONObject: node),
               let nodeStr = String(data: nodeJSON, encoding: .utf8) {
                let escapedParent = parent.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "'", with: "\\'")
                js = "if (window.demoAddNode) window.demoAddNode(\(nodeStr), '\(escapedParent)');"
            } else if type == "remove", let id = obj["id"] as? String {
                let escaped = id.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "'", with: "\\'")
                js = "if (window.demoRemoveNode) window.demoRemoveNode('\(escaped)');"
            }
            guard !js.isEmpty else { continue }
            for window in windows {
                (window.contentView as? WKWebView)?.evaluateJavaScript(js, completionHandler: nil)
            }
        }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
