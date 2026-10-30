// Pure logic for the live map's activity feed (#843): one activity.jsonl line to the page call that delivers it.
//
// The page (template.html ingestEvent) lights a node from each event and a thread only from a causal pair inside
// one session, so it needs the whole line, not just the skill id. Only the fields it reads are passed, each only
// with its own type, and the argument is re-serialised JSON, so a hostile value can never break out of the call.
import Foundation

private let stringFields = ["skill", "tool", "session", "file", "agent"]

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

/// work.json (brain-map/scripts/work_view.py, #854) to `applyWork({...})`, re-serialised so nothing in it can break out
/// of the call. nil when it doesn't parse or has no `workers` list.
func workCall(text: String) -> String? {
    guard let data = text.data(using: .utf8),
          let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
          obj["workers"] is [Any],
          let out = try? JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys]),
          let json = String(data: out, encoding: .utf8) else { return nil }
    return "if (window.applyWork) window.applyWork(\(json));"
}

/// tree-data.json to `updateTreeData(tree, synapses, work)`. `work` is the Body and Work layout (#854), passed so a
/// wallpaper showing it regenerates like the browser page does; null when absent. nil when the file doesn't parse.
func treeCall(text: String) -> String? {
    guard let data = text.data(using: .utf8),
          let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
          let tree = try? JSONSerialization.data(withJSONObject: obj["tree"] ?? [String: Any]()),
          let syn = try? JSONSerialization.data(withJSONObject: obj["synapses"] ?? [Any]()) else { return nil }
    var workStr = "null"
    if let w = obj["work"] as? [String: Any], let wd = try? JSONSerialization.data(withJSONObject: w) {
        workStr = String(data: wd, encoding: .utf8) ?? "null"
    }
    let treeStr = String(data: tree, encoding: .utf8) ?? "{}"
    let synStr = String(data: syn, encoding: .utf8) ?? "[]"
    return "if (window.updateTreeData) window.updateTreeData(\(treeStr), \(synStr), \(workStr));"
}
