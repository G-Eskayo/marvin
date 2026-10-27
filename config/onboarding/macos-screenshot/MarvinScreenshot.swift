// MARVIN screenshot contract for Mac apps (G-Eskayo/marvin#727). Copy this file into the app unchanged.
//
// Launched with `-MarvinScreenshot <png path>` (and `-MarvinAppearance light|dark`), the app draws one scene into an
// off-screen window, writes it as a PNG and quits, so the pipeline gets an image of any screen (a menu, a pill, a
// hidden panel) without Screen Recording permission or clicking. The scene's own launch arguments say which screen;
// the app reads them however it likes (UserDefaults parses `-Key value`). Without `-MarvinScreenshot` it does nothing.
//
// Call it before the app starts anything with side effects (microphone, hotkeys, network):
//     MarvinScreenshot.runIfRequested { SceneView(name: UserDefaults.standard.string(forKey: "MarvinScene")) }

import AppKit
import SwiftUI

enum MarvinScreenshot {
    static var requestedPath: String? { UserDefaults.standard.string(forKey: "MarvinScreenshot") }

    /// Draws `scene` and exits when a screenshot was asked for (exit 0 on success, 1 with the reason on stderr).
    @MainActor
    static func runIfRequested<V: View>(@ViewBuilder _ scene: () -> V) {
        guard let path = requestedPath else { return }
        do {
            try write(scene(), to: URL(fileURLWithPath: path))
            exit(0)
        } catch {
            FileHandle.standardError.write(Data("MarvinScreenshot: \(error)\n".utf8))
            exit(1)
        }
    }

    struct Failure: Error, CustomStringConvertible { let description: String }

    @MainActor
    static func write<V: View>(_ scene: V, to url: URL) throws {
        _ = NSApplication.shared
        let dark = UserDefaults.standard.string(forKey: "MarvinAppearance") == "dark"
        let appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        let host = NSHostingView(rootView: scene.background(Color(nsColor: .windowBackgroundColor)))
        host.appearance = appearance
        let size = host.fittingSize
        guard size.width >= 1, size.height >= 1 else { throw Failure(description: "the scene has no size; give it a frame") }
        let window = NSWindow(contentRect: NSRect(origin: .zero, size: size), styleMask: [.borderless],
                              backing: .buffered, defer: false)
        window.appearance = appearance
        window.contentView = host
        host.frame = NSRect(origin: .zero, size: size)
        host.layoutSubtreeIfNeeded()
        // One turn of the run loop so SwiftUI has rendered before the view is cached.
        RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        // Always 2x (Retina), whatever screen the pipeline machine has, so every PR image is equally sharp.
        guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width * 2), pixelsHigh: Int(size.height * 2),
                                         bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                         colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else {
            throw Failure(description: "could not make a bitmap for the scene")
        }
        rep.size = size
        host.cacheDisplay(in: host.bounds, to: rep)
        guard let png = rep.representation(using: .png, properties: [:]) else { throw Failure(description: "PNG encoding failed") }
        try png.write(to: url)
    }
}
