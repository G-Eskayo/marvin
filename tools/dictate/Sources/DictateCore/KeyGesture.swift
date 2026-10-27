import Foundation

/// What the keyboard did, with the time in seconds (any clock that only goes forward).
public enum GestureEvent: Equatable {
    case fnDown(Double), fnUp(Double), otherKey(Double), escape(Double)
    /// The double-tap window may have run out; sent at `KeyGesture.tickDeadline`.
    case tick(Double)
}

public enum GestureAction: Equatable {
    /// Start listening.
    case start
    /// Stop listening and type what was said.
    case commit
    /// Stop listening and throw it away.
    case cancel
    /// Throw away the current recording and start a new one.
    case restart
}

/// Hold Fn to talk, let go to type. A quick tap followed by a second tap is hands-free; the next Fn press types it.
/// Esc throws a recording away. Listening starts the moment Fn goes down so the first word is never lost; a press that
/// turns out to be a lone tap or a Fn+key shortcut is thrown away afterwards. Pure, so every rule is tested.
public struct KeyGesture {
    public enum State: Equatable {
        case idle
        case holding(since: Double)
        /// A short tap: waiting to see if a second one comes.
        case tapped(upAt: Double)
        case handsFree
        /// The press that ended hands-free is still down; its release does nothing.
        case endingHandsFree
    }

    public private(set) var state = State.idle
    /// A press shorter than this is a tap.
    public var tapMax = 0.3
    /// How long after a tap the second one may come.
    public var doubleTapWindow = 0.35

    public init() {}

    /// When to send `.tick`: only while waiting for a second tap.
    public var tickDeadline: Double? {
        if case .tapped(let up) = state { return up + doubleTapWindow }
        return nil
    }

    public mutating func handle(_ event: GestureEvent) -> GestureAction? {
        switch (state, event) {
        case (.idle, .fnDown(let t)):
            state = .holding(since: t); return .start
        case (.holding(let since), .fnUp(let t)):
            if t - since >= tapMax { state = .idle; return .commit }
            state = .tapped(upAt: t); return nil
        case (.holding, .otherKey), (.holding, .escape):
            state = .idle; return .cancel
        case (.tapped(let up), .fnDown(let t)):
            if t - up <= doubleTapWindow { state = .handsFree; return nil }
            state = .holding(since: t); return .restart
        case (.tapped(let up), .tick(let t)):
            if t - up > doubleTapWindow { state = .idle; return .cancel }
            return nil
        case (.tapped, .otherKey), (.tapped, .escape):
            state = .idle; return .cancel
        case (.handsFree, .fnDown):
            state = .endingHandsFree; return .commit
        case (.handsFree, .escape):
            state = .idle; return .cancel
        case (.endingHandsFree, .fnUp):
            state = .idle; return nil
        default:
            return nil
        }
    }
}
