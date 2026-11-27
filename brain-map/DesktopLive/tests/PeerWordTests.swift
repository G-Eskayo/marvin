import Foundation

var failures = 0
func check(_ cond: Bool, _ msg: String, line: Int = #line) {
    if !cond { failures += 1; print("FAIL line \(line): \(msg)") }
}

check(eventToArgs("poweroff") == ["expect-asleep", "macbook-pro-1", "--word", "off"], "poweroff maps to full args")
check(eventToArgs("sleep") == ["expect-asleep", "macbook-pro-1", "--word", "asleep"], "sleep maps to full args")
check(eventToArgs("wake") == nil, "wake maps to nil")

let now = Date()
let old = now.addingTimeInterval(-3)
check(shouldDebounce(nil, now, nil) == true, "debounce with no prior event")
check(shouldDebounce("poweroff", now, old) == true, "debounce with old event")
check(shouldDebounce("poweroff", now, now) == false, "don't debounce within window")

if failures > 0 { exit(1) }
