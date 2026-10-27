import XCTest
@testable import DictateCore

/// What gets typed: fillers out, spacing right, the person's own spellings in. These try to break it with fillers at
/// the start, the end and between commas, real words that contain a filler, and empty speech.
final class TextCleanupTests: XCTestCase {
    func testFillersAreDropped() {
        XCTAssertEqual(TextCleanup.clean("Um, I think we should ship it."), "I think we should ship it.")
        XCTAssertEqual(TextCleanup.clean("So, um, yeah."), "So, yeah.")
        XCTAssertEqual(TextCleanup.clean("It's uh about ten uhh minutes."), "It's about ten minutes.")
        XCTAssertEqual(TextCleanup.clean("Let's go, erm."), "Let's go.")
        XCTAssertEqual(TextCleanup.clean("Open the request. Ah, in Claude Code."), "Open the request. In Claude Code.")
    }

    func testWordsThatContainAFillerAreKept() {
        XCTAssertEqual(TextCleanup.clean("Umbrella, user, error, summer, her, aha, Ahab."), "Umbrella, user, error, summer, her, aha, Ahab.")
    }

    func testOnlyFillersTypesNothing() {
        XCTAssertEqual(TextCleanup.clean("Um. Uh, um."), "")
        XCTAssertEqual(TextCleanup.clean("   "), "")
        XCTAssertEqual(TextCleanup.clean(""), "")
    }

    func testSpacingIsTidied() {
        XCTAssertEqual(TextCleanup.clean("  hello   there , friend ."), "Hello there, friend.")
    }

    func testTheFirstLetterIsCapitalisedAfterAFillerIsRemoved() {
        XCTAssertEqual(TextCleanup.clean("uh, maybe later"), "Maybe later")
    }

    func testTheWordListFixesSpellings() {
        let words = WordList.parse("""
        # names the engine gets wrong
        MARVIN
        clod code => Claude Code
        seal speak => Seal Speak
        """)
        XCTAssertEqual(TextCleanup.clean("Ask marvin to open clod code.", words: words), "Ask MARVIN to open Claude Code.")
        XCTAssertEqual(TextCleanup.clean("Marvin, test Seal speak.", words: words), "MARVIN, test Seal Speak.")
    }

    func testWordListMatchesWholeWordsOnly() {
        let words = WordList.parse("ai => AI")
        XCTAssertEqual(TextCleanup.clean("The ai said hi to Aiden.", words: words), "The AI said hi to Aiden.")
    }

    func testTheLongerEntryWinsWhenEntriesOverlap() {
        let words = WordList.parse("code => Code\nclaude code => Claude Code")
        XCTAssertEqual(TextCleanup.clean("open claude code", words: words), "Open Claude Code")
    }

    func testReplacementTextIsTakenLiterally() {
        // `$1` and backslashes in the list are text, not regex templates.
        let words = WordList.parse("price => $1.99\npath => a\\b")
        XCTAssertEqual(TextCleanup.clean("the price and path", words: words), "The $1.99 and a\\b")
    }

    func testBadListLinesAreIgnored() {
        let words = WordList.parse("=> nothing\n   \n# only a comment\nfoo =>\n=>")
        XCTAssertTrue(words.entries.isEmpty)
    }

    func testTheEngineIsToldTheListsSpellings() {
        XCTAssertEqual(WordList.parse("MARVIN\nclod code => Claude Code").contextualStrings, ["MARVIN", "Claude Code"])
    }

    func testATrailingSpaceSeparatesOneSentenceFromTheNextDictation() {
        XCTAssertEqual(TextCleanup.forTyping("Done."), "Done. ")
        XCTAssertEqual(TextCleanup.forTyping("Really?"), "Really? ")
        XCTAssertEqual(TextCleanup.forTyping("half a thought"), "half a thought")
        XCTAssertEqual(TextCleanup.forTyping(""), "")
    }
}
