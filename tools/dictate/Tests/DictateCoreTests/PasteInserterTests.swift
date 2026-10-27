import XCTest
@testable import DictateCore

/// Typing goes through the clipboard, so whatever was on it must come back, unless the person copied something new
/// in the meantime.
final class PasteInserterTests: XCTestCase {
    final class FakePasteboard: Clipboard {
        var items: [[String: Data]] = [["public.utf8-plain-text": Data("before".utf8)], ["public.png": Data([1, 2])]]
        var changeCount = 7
        func snapshot() -> [[String: Data]] { items }
        func restore(_ items: [[String: Data]]) { self.items = items; changeCount += 1 }
        func setString(_ s: String) { items = [["public.utf8-plain-text": Data(s.utf8)]]; changeCount += 1 }
        var text: String? { items.first?["public.utf8-plain-text"].map { String(decoding: $0, as: UTF8.self) } }
    }

    private var later: [() -> Void] = []
    private var pastes = 0
    private var pasteboard = FakePasteboard()
    private lazy var inserter = PasteInserter(pasteboard: pasteboard, pressPaste: { [unowned self] in
        pastes += 1
        XCTAssertEqual(pasteboard.text, "hello", "the words are on the clipboard when paste is pressed")
    }, schedule: { [unowned self] _, work in later.append(work) })

    func testThePreviousClipboardComesBackAfterPasting() {
        let before = pasteboard.items
        inserter.insert("hello")
        XCTAssertEqual(pastes, 1)
        later.forEach { $0() }
        XCTAssertEqual(pasteboard.items, before)
    }

    func testSomethingCopiedInTheMeantimeIsNotOverwritten() {
        inserter.insert("hello")
        pasteboard.setString("copied by the person")
        later.forEach { $0() }
        XCTAssertEqual(pasteboard.text, "copied by the person")
    }

    func testNothingToTypeTouchesNothing() {
        inserter.insert("")
        XCTAssertEqual(pastes, 0)
        XCTAssertEqual(pasteboard.changeCount, 7)
        XCTAssertTrue(later.isEmpty)
    }
}
