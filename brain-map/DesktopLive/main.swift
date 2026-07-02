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
    let scriptDir = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
    return scriptDir.deletingLastPathComponent().appendingPathComponent("index.html").path
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

final class AppDelegate: NSObject, NSApplicationDelegate {
    var windows: [NSWindow] = []
    var lastMTime: Date?
    var reloadTimer: Timer?

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
        // Cheap poll (a single stat() call), not continuous work — reload
        // only actually happens when brain-map/generate.py has run again.
        reloadTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            self?.checkForUpdate()
        }
    }

    func mtime() -> Date? {
        (try? FileManager.default.attributesOfItem(atPath: fileURL.path))?[.modificationDate] as? Date
    }

    func checkForUpdate() {
        guard let m = mtime(), m != lastMTime else { return }
        lastMTime = m
        for window in windows {
            (window.contentView as? WKWebView)?.loadFileURL(fileURL, allowingReadAccessTo: readAccessDir)
        }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
