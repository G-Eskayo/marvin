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
let evil = activityCall(line: #"{"skill":"x'); window.pwned = 1; ('"}"#)
check(argument(evil)?["skill"] as? String == "x'); window.pwned = 1; ('", "hostile text stays text: \(evil ?? "nil")")

// #843: activity.jsonl is trimmed to its last 500 lines on every write, so once it is full the count never grows
// and the old count-based reader saw nothing new again. New lines are the ones after the last line seen.
let capped: [String] = (0..<500).map { #"{"skill":"MARVIN","ts":\#($0)}"# }
let trimmed: [String] = Array(capped.dropFirst()) + [#"{"skill":"tdd","ts":500}"#]
check(newActivityLines(trimmed, after: capped.last) == [#"{"skill":"tdd","ts":500}"#], "a full, trimmed file still yields its new line")
check(newActivityLines(trimmed, after: trimmed.last).isEmpty, "nothing new is nothing")
check(newActivityLines(["a", "b"], after: "zzz") == ["a", "b"], "the last line seen is gone: all new")
check(newActivityLines([], after: "b").isEmpty, "an emptied file yields nothing")
check(newActivityLines(["a"], after: nil) == ["a"], "nothing seen yet: all new")

if failures > 0 { print("\(failures) failure(s)"); exit(1) }
print("ActivityTests: all passed")
