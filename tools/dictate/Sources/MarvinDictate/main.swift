import AppKit
import AVFoundation
import DictateCore
import ServiceManagement

// MARVIN Dictate (marvin#730). `MarvinDictate --transcribe <audio file>` prints what the engine hears and exits;
// otherwise it runs as a menu-bar app: hold Fn to talk, let go to type.

if let i = CommandLine.arguments.firstIndex(of: "--transcribe"), i + 1 < CommandLine.arguments.count {
    let file = URL(fileURLWithPath: CommandLine.arguments[i + 1])
    let done = DispatchSemaphore(value: 0)
    Task {
        do {
            let words = WordList.parse(Words.load())
            let heard = try await DictationSession.transcribe(file: file, locale: await DictationSession.locale(), hints: words.contextualStrings)
            print(TextCleanup.clean(heard, words: words))
        } catch { FileHandle.standardError.write(Data("\(error)\n".utf8)); exit(1) }
        done.signal()
    }
    done.wait()
    exit(0)
}

/// `~/.config/marvin-dictate/words.txt`, made with a short how-to the first time.
enum Words {
    static let url = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".config/marvin-dictate/words.txt")
    static let template = """
    # MARVIN Dictate word list: spellings the speech engine gets wrong.
    #   wrong => right     replaces a word or phrase (ignores capitals, whole words only)
    #   Word               fixes a word's capitals, e.g. MARVIN
    # Saved changes apply from the next dictation.
    MARVIN
    Claude Code

    """

    static func load() -> String {
        if let text = try? String(contentsOf: url, encoding: .utf8) { return text }
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? template.write(to: url, atomically: true, encoding: .utf8)
        return template
    }
}

/// The real clipboard. Our own writes are marked transient so clipboard managers skip them.
final class SystemClipboard: Clipboard {
    private let pb = NSPasteboard.general
    var changeCount: Int { pb.changeCount }

    func snapshot() -> [[String: Data]] {
        (pb.pasteboardItems ?? []).map { item in
            Dictionary(item.types.compactMap { t in item.data(forType: t).map { (t.rawValue, $0) } }, uniquingKeysWith: { a, _ in a })
        }
    }

    func restore(_ items: [[String: Data]]) {
        pb.clearContents()
        guard !items.isEmpty else { return }
        pb.writeObjects(items.map { types in
            let item = NSPasteboardItem()
            for (t, d) in types { item.setData(d, forType: NSPasteboard.PasteboardType(t)) }
            return item
        })
    }

    func setString(_ s: String) {
        pb.clearContents()
        let item = NSPasteboardItem()
        item.setString(s, forType: .string)
        item.setData(Data(), forType: NSPasteboard.PasteboardType("org.nspasteboard.TransientType"))
        pb.writeObjects([item])
    }
}

@MainActor
final class Dictator: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    private var gesture = KeyGesture()
    private var tap: CFMachPort?
    private var engine: AVAudioEngine?
    private var next: Task<DictationSession, Error>?
    private var current: DictationSession?
    private var startedAt = 0.0
    private var problem: String?
    private var last: DictationRecord?
    private let history = HistoryLog.standard
    private lazy var inserter = PasteInserter(pasteboard: SystemClipboard(), pressPaste: Dictator.pressPaste,
                                              schedule: { delay, work in DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work) })

    func applicationDidFinishLaunching(_ note: Notification) {
        let menu = NSMenu()
        menu.delegate = self
        item.menu = menu
        last = (try? history.recent(1))?.first
        _ = CGRequestListenEventAccess()
        _ = CGRequestPostEventAccess()
        installTap()
        // Accessibility being switched on posts this; no polling.
        DistributedNotificationCenter.default().addObserver(forName: Notification.Name("com.apple.accessibility.api"), object: nil, queue: .main) { _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { MainActor.assumeIsolated { self.installTap() } }
        }
        AVCaptureDevice.requestAccess(for: .audio) { _ in }
        prepareNext()
        registerLoginItemOnce()
        showIcon()
    }

    // MARK: keys

    private func installTap() {
        guard tap == nil else { return }
        let mask = (1 << CGEventType.flagsChanged.rawValue) | (1 << CGEventType.keyDown.rawValue)
        let refcon = Unmanaged.passUnretained(self).toOpaque()
        guard let port = CGEvent.tapCreate(tap: .cgSessionEventTap, place: .headInsertEventTap, options: .defaultTap,
                                           eventsOfInterest: CGEventMask(mask), callback: { _, type, event, refcon in
            let me = Unmanaged<Dictator>.fromOpaque(refcon!).takeUnretainedValue()
            return MainActor.assumeIsolated { me.onKey(type, event) }
        }, userInfo: refcon) else {
            problem = "Needs Accessibility and Input Monitoring for MARVIN Dictate"
            showIcon()
            return
        }
        tap = port
        CFRunLoopAddSource(CFRunLoopGetMain(), CFMachPortCreateRunLoopSource(nil, port, 0), .commonModes)
        CGEvent.tapEnable(tap: port, enable: true)
        problem = nil
        showIcon()
    }

    private var fnDown = false

    private func onKey(_ type: CGEventType, _ event: CGEvent) -> Unmanaged<CGEvent>? {
        let now = ProcessInfo.processInfo.systemUptime
        switch type {
        case .tapDisabledByTimeout, .tapDisabledByUserInput:
            if let tap { CGEvent.tapEnable(tap: tap, enable: true) }
        case .flagsChanged:
            let code = event.getIntegerValueField(.keyboardEventKeycode)
            guard code == 63 || code == 179 else { break }      // Fn / Globe
            let down = event.flags.contains(.maskSecondaryFn)
            guard down != fnDown else { break }
            fnDown = down
            act(gesture.handle(down ? .fnDown(now) : .fnUp(now)))
        case .keyDown:
            if event.getIntegerValueField(.keyboardEventKeycode) == 53 {   // Esc
                let wasListening = isListening
                act(gesture.handle(.escape(now)))
                // Esc that threw away a recording is ours; it must not also reach the app (in Claude Code it stops
                // the agent).
                if wasListening && !isListening { return nil }
            } else {
                act(gesture.handle(.otherKey(now)))
            }
        default: break
        }
        return Unmanaged.passUnretained(event)
    }

    private var isListening: Bool {
        switch gesture.state {
        case .holding, .tapped, .handsFree: true
        case .idle, .endingHandsFree: false
        }
    }

    private func act(_ action: GestureAction?) {
        switch action {
        case .start: start()
        case .commit: commit()
        case .cancel: cancel()
        case .restart: cancel(); start()
        case nil: break
        }
        if let deadline = gesture.tickDeadline {
            let wait = max(0, deadline - ProcessInfo.processInfo.systemUptime) + 0.01
            DispatchQueue.main.asyncAfter(deadline: .now() + wait) {
                MainActor.assumeIsolated { self.act(self.gesture.handle(.tick(ProcessInfo.processInfo.systemUptime))) }
            }
        }
        showIcon()
    }

    // MARK: listening

    private func prepareNext() {
        let hints = WordList.parse(Words.load()).contextualStrings
        next = Task { try await DictationSession.prepare(locale: await DictationSession.locale(), hints: hints) }
    }

    private func start() {
        guard let next else { return }
        self.next = nil
        startedAt = ProcessInfo.processInfo.systemUptime
        let engine = AVAudioEngine()
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            problem = "No microphone (or MARVIN Dictate isn't allowed to use it)"
            self.next = next
            return
        }
        // Audio is captured from the first instant and queued until the prepared session is ready.
        let pending = AudioQueue()
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in pending.push(buffer) }
        do { try engine.start() } catch {
            problem = "Couldn't start the microphone: \(error.localizedDescription)"
            input.removeTap(onBus: 0)
            self.next = next
            return
        }
        problem = nil
        self.engine = engine
        Task {
            do {
                let session = try await next.value
                try await session.start()
                pending.drain(into: session)
                current = session
            } catch {
                problem = "Speech engine: \(error)"
                prepareNext()
                showIcon()
            }
        }
    }

    private func stopAudio() {
        engine?.inputNode.removeTap(onBus: 0)
        engine?.stop()
        engine = nil
    }

    private func commit() {
        let released = ProcessInfo.processInfo.systemUptime
        let spoken = released - startedAt
        stopAudio()
        let app = NSWorkspace.shared.frontmostApplication?.bundleIdentifier
        Task {
            // The session may still be getting ready if Fn was let go very quickly.
            while current == nil, problem == nil, next == nil { try? await Task.sleep(for: .milliseconds(20)) }
            guard let session = current else { return }
            current = nil
            prepareNext()
            do {
                let words = WordList.parse(Words.load())
                let text = TextCleanup.clean(try await session.finish(), words: words)
                guard !text.isEmpty else { return }
                inserter.insert(TextCleanup.forTyping(text))
                let ms = Int((ProcessInfo.processInfo.systemUptime - released) * 1000)
                let record = DictationRecord(at: Date(), spokenSeconds: (spoken * 10).rounded() / 10, finishMs: ms, app: app, text: text)
                last = record
                try? history.append(record)
            } catch {
                problem = "Speech engine: \(error)"
            }
            showIcon()
        }
    }

    private func cancel() {
        stopAudio()
        Task {
            while current == nil, problem == nil, next == nil { try? await Task.sleep(for: .milliseconds(20)) }
            guard let session = current else { return }
            current = nil
            prepareNext()
            await session.cancel()
        }
    }

    private static func pressPaste() {
        let src = CGEventSource(stateID: .combinedSessionState)
        for down in [true, false] {
            let e = CGEvent(keyboardEventSource: src, virtualKey: 9, keyDown: down)   // V
            e?.flags = .maskCommand
            e?.post(tap: .cghidEventTap)
        }
    }

    // MARK: menu bar

    private func showIcon() {
        let name = problem != nil ? "mic.slash" : (isListening ? "mic.fill" : "mic")
        item.button?.image = NSImage(systemSymbolName: name, accessibilityDescription: "MARVIN Dictate")
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        installTap()
        menu.removeAllItems()
        let hint = NSMenuItem(title: "Hold Fn to talk · double-tap Fn for hands-free · Esc cancels", action: nil, keyEquivalent: "")
        hint.isEnabled = false
        menu.addItem(hint)
        if let problem {
            menu.addItem(entry(problem + "…", #selector(openPrivacy)))
        }
        menu.addItem(.separator())
        if let last {
            let shown = last.text.count > 60 ? String(last.text.prefix(60)) + "…" : last.text
            menu.addItem(entry("Copy “\(shown)”", #selector(copyLast)))
        }
        menu.addItem(entry("Open word list", #selector(openWords)))
        menu.addItem(entry("Open history", #selector(openHistory)))
        menu.addItem(.separator())
        menu.addItem(entry("Quit MARVIN Dictate", #selector(quit)))
    }

    private func entry(_ title: String, _ action: Selector) -> NSMenuItem {
        let m = NSMenuItem(title: title, action: action, keyEquivalent: "")
        m.target = self
        return m
    }

    @objc private func copyLast() {
        guard let last else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(last.text, forType: .string)
    }
    @objc private func openWords() { _ = Words.load(); NSWorkspace.shared.open(Words.url) }
    @objc private func openHistory() { NSWorkspace.shared.activateFileViewerSelecting([history.url]) }
    @objc private func quit() { NSApp.terminate(nil) }
    @objc private func openPrivacy() {
        let pane = problem?.contains("microphone") == true ? "Privacy_Microphone" : "Privacy_Accessibility"
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(pane)") { NSWorkspace.shared.open(url) }
    }

    /// Starts at login, once. If the person later turns it off in Login Items, that stays off.
    private func registerLoginItemOnce() {
        guard Bundle.main.bundleURL.pathExtension == "app", !UserDefaults.standard.bool(forKey: "registeredLoginItem") else { return }
        if (try? SMAppService.mainApp.register()) != nil { UserDefaults.standard.set(true, forKey: "registeredLoginItem") }
    }
}

/// Microphone buffers caught before the session is ready, then passed straight through.
final class AudioQueue: @unchecked Sendable {
    private let lock = NSLock()
    private var buffers: [AVAudioPCMBuffer] = []
    private var session: DictationSession?

    func push(_ buffer: AVAudioPCMBuffer) {
        lock.lock(); defer { lock.unlock() }
        if let session { session.feed(buffer) } else { buffers.append(buffer) }
    }

    func drain(into session: DictationSession) {
        lock.lock(); defer { lock.unlock() }
        buffers.forEach(session.feed)
        buffers = []
        self.session = session
    }
}

MainActor.assumeIsolated {
    let app = NSApplication.shared
    let dictator = Dictator()
    app.delegate = dictator
    app.setActivationPolicy(.accessory)
    app.run()
}
