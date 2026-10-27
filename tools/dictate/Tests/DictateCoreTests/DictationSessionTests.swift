import Speech
import XCTest
@testable import DictateCore

/// The real engine on a real recording: `say` speaks a sentence into a file, the engine writes it back. Skipped where
/// the English model isn't installed (CI runners), since installing it is a system download.
final class DictationSessionTests: XCTestCase {
    private let english = Locale(identifier: "en-US")

    private func spoken(_ sentence: String) throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("dictate-\(UUID()).aiff")
        let say = Process()
        say.executableURL = URL(fileURLWithPath: "/usr/bin/say")
        say.arguments = ["-o", url.path, sentence]
        try say.run(); say.waitUntilExit()
        try XCTSkipUnless(say.terminationStatus == 0 && FileManager.default.fileExists(atPath: url.path), "say couldn't record")
        return url
    }

    private func requireModel() async throws {
        let installed = await SpeechTranscriber.installedLocales.contains { $0.identifier(.bcp47) == "en-US" }
        try XCTSkipUnless(installed, "Apple's en-US speech model isn't installed on this machine")
    }

    private func words(_ s: String) -> [String] {
        s.lowercased().split { !$0.isLetter && !$0.isNumber }.map(String.init)
    }

    func testARecordedSentenceComesBackAsItsWords() async throws {
        try await requireModel()
        let file = try spoken("Please send the report to the team before lunch tomorrow.")
        defer { try? FileManager.default.removeItem(at: file) }
        let heard = try await DictationSession.transcribe(file: file, locale: english)
        let got = Set(words(heard))
        let want = ["send", "report", "team", "before", "lunch", "tomorrow"]
        XCTAssertTrue(want.allSatisfy(got.contains), "heard: \(heard)")
        XCTAssertEqual(TextCleanup.clean(heard).first?.isUppercase, true)
    }

    func testSilenceTypesNothing() async throws {
        try await requireModel()
        let session = try await DictationSession.prepare(locale: english)
        try await session.start()
        let format = AVAudioFormat(standardFormatWithSampleRate: 48_000, channels: 1)!
        let silence = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 48_000)!
        silence.frameLength = 48_000
        session.feed(silence)
        XCTAssertEqual(session.fedSeconds, 1, accuracy: 0.05, "48 kHz in is converted, one second of it")
        let heard = try await session.finish()
        XCTAssertEqual(TextCleanup.clean(heard), "")
    }

    func testACancelledSessionEndsWithoutHanging() async throws {
        try await requireModel()
        let session = try await DictationSession.prepare(locale: english)
        try await session.start()
        await session.cancel()
    }

    func testTheDevicesLanguageIsUsedWhenTheEngineHasIt() async throws {
        let l = await DictationSession.locale(preferred: ["xx-XX", "en-GB"])
        XCTAssertEqual(l.language.languageCode?.identifier, "en")
        let fallback = await DictationSession.locale(preferred: ["xx-XX"])
        XCTAssertEqual(fallback.identifier(.bcp47), "en-US")
    }
}
