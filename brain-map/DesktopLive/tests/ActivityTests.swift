// Plain assert-based tests for Activity.swift (#843). Run via ../test.sh.
import Foundation

var failures = 0
func check(_ cond: Bool, _ msg: String, line: Int = #line) {
    if !cond { failures += 1; print("FAIL line \(line): \(msg)") }
}

// The JS argument decoded back, the way the page would receive it.
func argument(_ js: String?) -> [String: Any]? {
    guard let js = js,
          let open = js.range(of: "window.triggerActivity("), js.hasSuffix(");") else { return nil }
    let body = String(js[open.upperBound..<js.index(js.endIndex, offsetBy: -2)])
    return (try? JSONSerialization.jsonObject(with: Data(body.utf8))) as? [String: Any]
}

// The whole line reaches the page (the session and file are what let it light a thread), limited to the
// fields it reads.
let full = #"{"skill":"MARVIN","ts":1.5,"tool":"Edit","session":"s1","file":"skills/tdd/SKILL.md","ok":false,"extra":"x"}"#
let got = argument(activityCall(line: full))
check(got?["skill"] as? String == "MARVIN", "skill passed: \(String(describing: got))")
check(got?["ts"] as? Double == 1.5, "ts passed")
check(got?["tool"] as? String == "Edit" && got?["session"] as? String == "s1", "tool and session passed")
check(got?["file"] as? String == "skills/tdd/SKILL.md", "file passed")
check(got?["ok"] as? Bool == false, "ok passed as a boolean")
check(got?["extra"] == nil, "unknown fields dropped")

// An older {skill, ts} line still works.
check(argument(activityCall(line: #"{"skill":"tdd","ts":2}"#))?["skill"] as? String == "tdd", "old lines still fire")

// Bad lines fire nothing; wrong-typed fields are dropped, not passed.
check(activityCall(line: "not json") == nil, "garbage skipped")
check(activityCall(line: #"{"no_skill":1}"#) == nil, "no skill skipped")
check(activityCall(line: #"{"skill":7}"#) == nil, "non-string skill skipped")
let odd = argument(activityCall(line: #"{"skill":"tdd","ts":"soon","tool":3,"session":null,"ok":"yes"}"#))
check(odd?.keys.sorted() == ["skill"], "wrong types dropped: \(String(describing: odd))")
// ok:1 must not arrive as true (NSNumber bridges Int and Bool).
check(argument(activityCall(line: #"{"skill":"tdd","ok":1}"#))?["ok"] == nil, "a number is not a boolean")

// A hostile skill name arrives as plain data: the call is still exactly one triggerActivity(...) of JSON.
let evilID = "x\"); window.pwned=1; (\""
let evilDoc = String(data: try! JSONSerialization.data(withJSONObject: ["workers": [["id": evilID]]]), encoding: .utf8)!
if let js = workCall(text: evilDoc), let open = js.range(of: "window.applyWork("), js.hasSuffix(");") {
    let body = String(js[open.upperBound..<js.index(js.endIndex, offsetBy: -2)])
    let back = (try? JSONSerialization.jsonObject(with: Data(body.utf8))) as? [String: Any]
    check(((back?["workers"] as? [[String: Any]])?.first?["id"] as? String) == evilID, "a hostile id arrives as plain text")
} else { check(false, "hostile work.json not passed through as data") }
let tjs = treeCall(text: #"{"tree":{"id":"MARVIN"},"synapses":[],"work":{"tree":{"id":"W"},"synapses":[]}}"#) ?? ""
check(tjs.hasPrefix(#"if (window.updateTreeData) window.updateTreeData({"id":"MARVIN"}, [], {"#) && tjs.contains(#""id":"W""#),
      "work passed as the third argument: \(tjs)")
check(treeCall(text: #"{"tree":{},"synapses":[]}"#)?.hasSuffix(", null);") == true, "no work: null")
check(treeCall(text: "{") == nil, "unparseable tree data: nil (the host reloads)")

if failures > 0 { print("\(failures) failure(s)"); exit(1) }
print("ActivityTests: all passed")
