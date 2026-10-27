import XCTest
@testable import DictateCore

final class HistoryLogTests: XCTestCase {
    func testRecordsAreAppendedOnePerLineAndReadBack() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("dictate-\(UUID())/nested")
        defer { try? FileManager.default.removeItem(at: dir.deletingLastPathComponent()) }
        let log = HistoryLog(url: dir.appendingPathComponent("history.jsonl"))
        XCTAssertEqual(try log.recent(5), [], "no file yet is an empty history, not an error")
        let a = DictationRecord(at: Date(timeIntervalSince1970: 1), spokenSeconds: 2.5, finishMs: 310, app: "com.apple.Terminal", text: "first, \"quoted\"\nline")
        let b = DictationRecord(at: Date(timeIntervalSince1970: 2), spokenSeconds: 1, finishMs: 200, app: nil, text: "second")
        try log.append(a)
        try log.append(b)
        let lines = try String(contentsOf: log.url, encoding: .utf8).split(separator: "\n")
        XCTAssertEqual(lines.count, 2, "a newline in the words stays inside its record")
        XCTAssertEqual(try log.recent(5), [b, a], "newest first")
        XCTAssertEqual(try log.recent(1), [b])
    }

    func testABrokenLineDoesNotHideTheRest() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("dictate-\(UUID()).jsonl")
        defer { try? FileManager.default.removeItem(at: url) }
        let log = HistoryLog(url: url)
        try log.append(DictationRecord(at: Date(timeIntervalSince1970: 1), spokenSeconds: 1, finishMs: 1, app: nil, text: "ok"))
        let h = try FileHandle(forWritingTo: url); h.seekToEndOfFile(); h.write(Data("{not json\n".utf8)); try h.close()
        XCTAssertEqual(try log.recent(5).map(\.text), ["ok"])
    }
}
