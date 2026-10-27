import Foundation

/// The person's own spellings, from `words.txt`: `wrong => right` per line, or a bare word to fix its capitals
/// (`MARVIN`). `#` starts a comment. Matches whole words, ignoring case.
public struct WordList: Equatable {
    public struct Entry: Equatable { public let from: String, to: String }
    public let entries: [Entry]

    public static let empty = WordList(entries: [])

    public static func parse(_ text: String) -> WordList {
        let entries: [Entry] = text.split(whereSeparator: \.isNewline).compactMap { raw in
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.isEmpty || line.hasPrefix("#") { return nil }
            let parts = line.components(separatedBy: "=>").map { $0.trimmingCharacters(in: .whitespaces) }
            if parts.count == 1 { return Entry(from: line, to: line) }
            guard parts.count == 2, !parts[0].isEmpty, !parts[1].isEmpty else { return nil }
            return Entry(from: parts[0], to: parts[1])
        }
        return WordList(entries: entries)
    }

    /// Spellings handed to the speech engine as hints.
    public var contextualStrings: [String] { entries.map(\.to) }

    func apply(_ text: String) -> String {
        // Longest first, so "claude code" wins over "code".
        entries.sorted { $0.from.count > $1.from.count }.reduce(text) { s, e in
            let pattern = "(?<![\\w])" + NSRegularExpression.escapedPattern(for: e.from) + "(?![\\w])"
            return s.replacing(pattern, with: NSRegularExpression.escapedTemplate(for: e.to), caseInsensitive: true)
        }
    }
}

/// What gets typed from what the engine heard.
public enum TextCleanup {
    /// um, umm, uh, uhh, ah, er, erm, with the comma after them. Apple's engine often writes "uh" as "Ah".
    private static let filler = "\\b(?:u+m+|u+h+|a+h+|erm|er)\\b,?"

    public static func clean(_ raw: String, words: WordList = .empty) -> String {
        // A mark where each filler was, so a sentence that started with one gets its capital back ("Ah, in" -> "In").
        var s = raw.replacing(filler, with: "\u{1}", caseInsensitive: true)
        s = s.replacing("([.!?]\\s*)\u{1}[\\s\u{1}]*(\\p{Ll})", with: "$1\u{2}$2")
        var out = ""
        var rest = s[...]
        while let mark = rest.range(of: "\u{2}") {
            out += rest[..<mark.lowerBound]
            let after = rest[mark.upperBound...]
            out += after.prefix(1).uppercased()
            rest = after.dropFirst()
        }
        s = (out + rest).replacingOccurrences(of: "\u{1}", with: "")
        s = s.replacing("\\s+", with: " ")
        s = s.replacing("\\s+([,.!?;:])", with: "$1")
        // Commas or stops left in front of a stop when everything before it was a filler ("Uh, um." -> ".").
        s = s.replacing("[,;:]+([.!?])", with: "$1")
        s = s.replacing("^[\\s,.;:!?]+", with: "")
        s = s.trimmingCharacters(in: .whitespaces)
        s = words.apply(s)
        guard let first = s.first else { return "" }
        return first.uppercased() + s.dropFirst()
    }

    /// A finished sentence gets a space after it, so the next dictation doesn't run into it.
    public static func forTyping(_ cleaned: String) -> String {
        guard let last = cleaned.last else { return "" }
        return ".!?".contains(last) ? cleaned + " " : cleaned
    }
}

extension String {
    func replacing(_ pattern: String, with template: String, caseInsensitive: Bool = false) -> String {
        let re = try! NSRegularExpression(pattern: pattern, options: caseInsensitive ? [.caseInsensitive] : [])
        return re.stringByReplacingMatches(in: self, range: NSRange(startIndex..., in: self), withTemplate: template)
    }
}
