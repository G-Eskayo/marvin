// Pure logic for the live map's activity feed (#843): one activity.jsonl line to the page call that delivers it.
//
// The page (template.html ingestEvent) lights a node from each event and a thread only from a causal pair inside
// one session, so it needs the whole line, not just the skill id. Only the fields it reads are passed, each only
// with its own type, and the argument is re-serialised JSON, so a hostile value can never break out of the call.
import Foundation

private let stringFields = ["skill", "tool", "session", "file"]

/// `if (window.triggerActivity) window.triggerActivity({...});` for a line with a string `skill`, else nil.
func activityCall(line: String) -> String? {
    guard let data = line.data(using: .utf8),
          let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
          obj["skill"] is String else { return nil }
    var ev: [String: Any] = [:]
    for key in stringFields { if let v = obj[key] as? String { ev[key] = v } }
    // NSNumber bridges both numbers and booleans: tell them apart by their CF type.
    if let n = obj["ts"] as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(), n.doubleValue.isFinite { ev["ts"] = n.doubleValue }
    if let b = obj["ok"] as? NSNumber, CFGetTypeID(b) == CFBooleanGetTypeID() { ev["ok"] = b.boolValue }
    guard let out = try? JSONSerialization.data(withJSONObject: ev, options: [.sortedKeys]),
          let json = String(data: out, encoding: .utf8) else { return nil }
    return "if (window.triggerActivity) window.triggerActivity(\(json));"
}

/// Activity lines after the last one seen. activity.jsonl is trimmed to its last 500 lines on every write, so once
/// it is full its line count never grows and a count can't tell new lines from old (#843). If the last line seen is
/// gone (the file was replaced), everything in it is new; nothing seen yet means everything is new too.
func newActivityLines(_ lines: [String], after last: String?) -> [String] {
    guard let last = last else { return lines }
    if let i = lines.lastIndex(of: last) { return Array(lines[(i + 1)...]) }
    return lines
}
