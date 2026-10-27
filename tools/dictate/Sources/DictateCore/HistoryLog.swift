import Foundation

/// One dictation: when, how long the person spoke, how long from letting go of Fn to the words being typed, and the
/// app they went into.
public struct DictationRecord: Codable, Equatable {
    public let at: Date
    public let spokenSeconds: Double
    public let finishMs: Int
    public let app: String?
    public let text: String

    public init(at: Date, spokenSeconds: Double, finishMs: Int, app: String?, text: String) {
        self.at = at; self.spokenSeconds = spokenSeconds; self.finishMs = finishMs; self.app = app; self.text = text
    }
}

/// Every dictation, one JSON object per line, appended. Stays on this Mac.
public struct HistoryLog {
    public let url: URL
    public init(url: URL) { self.url = url }

    public static var standard: HistoryLog {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return HistoryLog(url: dir.appendingPathComponent("MARVIN Dictate/history.jsonl"))
    }

    private static let encoder: JSONEncoder = {
        let e = JSONEncoder(); e.dateEncodingStrategy = .iso8601; e.outputFormatting = [.sortedKeys]; return e
    }()
    private static let decoder: JSONDecoder = {
        let d = JSONDecoder(); d.dateDecodingStrategy = .iso8601; return d
    }()

    public func append(_ record: DictationRecord) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        var line = try Self.encoder.encode(record)
        line.append(0x0A)
        if !FileManager.default.fileExists(atPath: url.path) {
            try line.write(to: url)
            return
        }
        let handle = try FileHandle(forWritingTo: url)
        defer { try? handle.close() }
        try handle.seekToEnd()
        try handle.write(contentsOf: line)
    }

    /// Newest first. A line that doesn't read is skipped, not fatal.
    public func recent(_ limit: Int) throws -> [DictationRecord] {
        guard let data = FileManager.default.contents(atPath: url.path) else { return [] }
        let records = data.split(separator: 0x0A).compactMap { try? Self.decoder.decode(DictationRecord.self, from: Data($0)) }
        return Array(records.suffix(limit).reversed())
    }
}
