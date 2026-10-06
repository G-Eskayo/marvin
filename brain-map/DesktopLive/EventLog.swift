// EventLog — one line per thing that affects whether the wallpaper draws
// (launch, windows, page loads, crashes, sleep/wake, display changes), so a
// missing, black or frozen background leaves a trace (#136: before this the
// app wrote nothing and both launchd log files sat empty).
//
// Its own file, not launchd's StandardOutPath: rotating a file launchd holds
// open would leave launchd writing into the renamed copy.

import Foundation

final class EventLog {
    let path: URL
    let maxBytes: Int

    init(path: URL, maxBytes: Int = 1_000_000) {
        self.path = path
        self.maxBytes = maxBytes
    }

    // "<ISO time> <event> key=value key="value with spaces"" — one entry per
    // line no matter what the values contain.
    static func format(event: String, fields: [(String, String)], at date: Date = Date()) -> String {
        let time = ISO8601DateFormatter().string(from: date)
        let parts = fields.map { "\($0.0)=\(quote($0.1))" }
        return ([time, event] + parts).joined(separator: " ")
    }

    static func quote(_ value: String) -> String {
        let needsQuotes = value.isEmpty || value.contains { $0 == " " || $0 == "\"" || $0 == "\n" || $0 == "\r" || $0 == "=" }
        guard needsQuotes else { return value }
        let escaped = value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
            .replacingOccurrences(of: "\n", with: "\\n")
            .replacingOccurrences(of: "\r", with: "\\r")
        return "\"\(escaped)\""
    }

    // Fields as flat key/value pairs: write("window", "screen", name, "frame", f).
    func write(_ event: String, _ kv: String...) {
        write(event, pairs: kv)
    }

    func write(_ event: String, pairs kv: [String]) {
        var fields: [(String, String)] = []
        var i = 0
        while i + 1 < kv.count { fields.append((kv[i], kv[i + 1])); i += 2 }
        append(EventLog.format(event: event, fields: fields) + "\n")
    }

    private func append(_ line: String) {
        let fm = FileManager.default
        try? fm.createDirectory(at: path.deletingLastPathComponent(), withIntermediateDirectories: true)
        let data = Data(line.utf8)
        let current = ((try? fm.attributesOfItem(atPath: path.path))?[.size] as? NSNumber)?.intValue ?? 0
        if current > 0 && current + data.count > maxBytes {
            let old = URL(fileURLWithPath: path.path + ".1")
            try? fm.removeItem(at: old)
            try? fm.moveItem(at: path, to: old)
        }
        if let handle = try? FileHandle(forWritingTo: path) {
            handle.seekToEndOfFile()
            handle.write(data)
            try? handle.close()
        } else {
            try? data.write(to: path)
        }
    }
}
