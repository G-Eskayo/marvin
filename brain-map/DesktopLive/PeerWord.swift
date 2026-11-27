import Foundation

// PeerWord: map system events to expect-asleep CLI args, with debounce.
// Pure functions: eventToArgs maps an event string to ("asleep" | "off"), and shouldDebounce
// decides whether to cancel-and-reschedule or ignore (same idiom as scheduleReconcile in main.swift).

func eventToArgs(_ event: String) -> [String]? {
    let machineId = "macbook-pro-1"  // this machine
    switch event {
    case "poweroff":
        return ["expect-asleep", machineId, "--word", "off"]
    case "sleep":
        return ["expect-asleep", machineId, "--word", "asleep"]
    default:
        return nil
    }
}

func shouldDebounce(_ lastEvent: String?, _ now: Date, _ lastEventTime: Date?) -> Bool {
    guard let lastEventTime = lastEventTime else { return true }
    let debounceWindow: TimeInterval = 2.0  // seconds: suppress rapid duplicate events
    return now.timeIntervalSince(lastEventTime) > debounceWindow
}
