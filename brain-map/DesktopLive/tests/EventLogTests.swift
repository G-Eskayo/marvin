// Plain assert-based tests for EventLog (no XCTest: DesktopLive is built
// with bare swiftc, not a package). Run via ../test.sh.
import Foundation

var failures = 0
func check(_ cond: Bool, _ msg: String, line: Int = #line) {
    if !cond { failures += 1; print("FAIL line \(line): \(msg)") }
}

let fixed = Date(timeIntervalSince1970: 1_791_300_000) // 2026-10-06T...Z

// A line is: ISO-8601 UTC time, event name, then key=value fields in the order given.
let line = EventLog.format(event: "window", fields: [("screen", "Built-in Retina Display"), ("frame", "0,0,1440,900")], at: fixed)
check(line.hasPrefix("2026-10-06T"), "starts with an ISO date: \(line)")
check(line.hasSuffix("Z window screen=\"Built-in Retina Display\" frame=0,0,1440,900"), "event then fields, spaces quoted: \(line)")

// Newlines inside a value never split a log entry over two lines.
let multi = EventLog.format(event: "load-failed", fields: [("error", "a\nb \"c\"")], at: fixed)
check(!multi.contains("\n"), "no raw newline: \(multi)")
check(multi.hasSuffix("error=\"a\\nb \\\"c\\\"\""), "newline and quotes escaped: \(multi)")

// No fields: just time and event.
check(EventLog.format(event: "wake", fields: [], at: fixed).hasSuffix("Z wake"), "bare event")

// Writing appends one line per event.
let dir = FileManager.default.temporaryDirectory.appendingPathComponent("eventlog-\(UUID().uuidString)")
try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
let path = dir.appendingPathComponent("d.log")
let log = EventLog(path: path, maxBytes: 200)
log.write("launch", "pid", "1")
log.write("wake")
let text = try! String(contentsOf: path, encoding: .utf8)
check(text.split(separator: "\n").count == 2, "two lines written: \(text)")

// Past maxBytes the file rotates to .1 (one old copy kept) and a fresh file starts.
for i in 0..<20 { log.write("tick", "i", "\(i)") }
let size = (try! FileManager.default.attributesOfItem(atPath: path.path)[.size] as! NSNumber).intValue
check(size <= 200, "current file stays under the cap: \(size)")
check(FileManager.default.fileExists(atPath: path.path + ".1"), "rotated copy exists")
let rotated = try! String(contentsOf: URL(fileURLWithPath: path.path + ".1"), encoding: .utf8)
check(rotated.contains("tick"), "rotated copy holds older lines")
check(!FileManager.default.fileExists(atPath: path.path + ".2"), "only one old copy kept")

// A missing log directory is created rather than dropping lines.
let deep = dir.appendingPathComponent("a/b/c.log")
EventLog(path: deep, maxBytes: 1000).write("launch")
check(FileManager.default.fileExists(atPath: deep.path), "creates missing directories")

if failures == 0 { print("EventLog: all tests passed") } else { print("EventLog: \(failures) failure(s)"); exit(1) }
