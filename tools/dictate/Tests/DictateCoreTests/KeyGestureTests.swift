import XCTest
@testable import DictateCore

/// Hold Fn to talk, double-tap for hands-free, Esc to throw it away. These try to break it with quick taps, slow
/// second taps, Fn used as a shortcut key (Fn+arrow) and keys pressed in the wrong state.
final class KeyGestureTests: XCTestCase {
    private func run(_ events: [GestureEvent]) -> (actions: [GestureAction?], state: KeyGesture.State) {
        var g = KeyGesture()
        let actions = events.map { g.handle($0) }
        return (actions, g.state)
    }

    func testHoldingFnRecordsAndLettingGoTypes() {
        let r = run([.fnDown(0), .fnUp(1.2)])
        XCTAssertEqual(r.actions, [.start, .commit])
        XCTAssertEqual(r.state, .idle)
    }

    func testRecordingStartsTheMomentFnGoesDown() {
        // Nothing waits to see if it's a tap: the first word must not be lost.
        XCTAssertEqual(run([.fnDown(0)]).actions, [.start])
    }

    func testAQuickTapAloneIsThrownAwayOnceTheDoubleTapWindowPasses() {
        let r = run([.fnDown(0), .fnUp(0.1), .tick(0.3), .tick(0.5)])
        XCTAssertEqual(r.actions, [.start, nil, nil, .cancel])
        XCTAssertEqual(r.state, .idle)
    }

    func testDoubleTapIsHandsFreeAndTheNextPressTypes() {
        let r = run([.fnDown(0), .fnUp(0.1), .fnDown(0.25), .fnUp(0.3), .tick(5), .fnDown(9), .fnUp(9.1)])
        XCTAssertEqual(r.actions, [.start, nil, nil, nil, nil, .commit, nil])
        XCTAssertEqual(r.state, .idle)
    }

    func testHandsFreeKeepsListeningWhileOtherKeysAreTyped() {
        let r = run([.fnDown(0), .fnUp(0.1), .fnDown(0.2), .fnUp(0.25), .otherKey(2)])
        XCTAssertEqual(r.actions.last, .some(nil))
        XCTAssertEqual(r.state, .handsFree)
    }

    func testEscapeThrowsAwayAHoldAndHandsFree() {
        XCTAssertEqual(run([.fnDown(0), .escape(0.5)]).actions, [.start, .cancel])
        let r = run([.fnDown(0), .fnUp(0.1), .fnDown(0.2), .fnUp(0.25), .escape(3)])
        XCTAssertEqual(r.actions.last, .cancel)
        XCTAssertEqual(r.state, .idle)
    }

    func testFnUsedAsAShortcutKeyIsNotDictation() {
        // Fn+arrow (Page Up) or Fn+F-key: another key while Fn is down means it was a shortcut.
        let r = run([.fnDown(0), .otherKey(0.2), .fnUp(0.4)])
        XCTAssertEqual(r.actions, [.start, .cancel, nil])
        XCTAssertEqual(r.state, .idle)
    }

    func testASecondTapThatComesTooLateStartsAFreshRecording() {
        // The window's timer can fire late; the old recording is dropped and this press is a new one.
        let r = run([.fnDown(0), .fnUp(0.1), .fnDown(2), .fnUp(3)])
        XCTAssertEqual(r.actions, [.start, nil, .restart, .commit])
    }

    func testStrayEventsWhileIdleDoNothing() {
        let r = run([.fnUp(0), .escape(1), .otherKey(2), .tick(3)])
        XCTAssertEqual(r.actions, [nil, nil, nil, nil])
        XCTAssertEqual(r.state, .idle)
    }

    func testTheReleaseAfterEndingHandsFreeIsIgnored() {
        var g = KeyGesture()
        for e in [GestureEvent.fnDown(0), .fnUp(0.1), .fnDown(0.2), .fnUp(0.25), .fnDown(4)] { _ = g.handle(e) }
        XCTAssertEqual(g.state, .endingHandsFree)
        XCTAssertNil(g.handle(.escape(4.05)), "already typed; Esc can't take it back")
        XCTAssertNil(g.handle(.fnUp(4.1)))
        XCTAssertEqual(g.state, .idle)
    }

    func testDeadlineIsOnlySetWhileWaitingForASecondTap() {
        var g = KeyGesture()
        XCTAssertNil(g.tickDeadline)
        _ = g.handle(.fnDown(0)); XCTAssertNil(g.tickDeadline)
        _ = g.handle(.fnUp(0.1)); XCTAssertEqual(g.tickDeadline!, 0.1 + g.doubleTapWindow, accuracy: 1e-9)
    }
}
