import Foundation

/// The clipboard, as much of it as typing needs. Items are type identifier -> data, so images and rich text come back
/// exactly as they were.
public protocol Clipboard: AnyObject {
    var changeCount: Int { get }
    func snapshot() -> [[String: Data]]
    func restore(_ items: [[String: Data]])
    func setString(_ s: String)
}

/// Types text into whatever app has the cursor by pasting it, then puts the clipboard back. Pasting works in every
/// app (terminals, browsers, Electron), where typing key by key is slow and breaks on some keyboard layouts.
public final class PasteInserter {
    private let pasteboard: Clipboard
    private let pressPaste: () -> Void
    private let schedule: (Double, @escaping () -> Void) -> Void
    /// Long enough for a slow app to read the clipboard before it's put back.
    public var restoreDelay = 0.5

    public init(pasteboard: Clipboard, pressPaste: @escaping () -> Void,
                schedule: @escaping (Double, @escaping () -> Void) -> Void) {
        self.pasteboard = pasteboard
        self.pressPaste = pressPaste
        self.schedule = schedule
    }

    public func insert(_ text: String) {
        guard !text.isEmpty else { return }
        let saved = pasteboard.snapshot()
        pasteboard.setString(text)
        let ours = pasteboard.changeCount
        pressPaste()
        schedule(restoreDelay) { [pasteboard] in
            // Something copied since is the person's; leave it.
            if pasteboard.changeCount == ours { pasteboard.restore(saved) }
        }
    }
}
