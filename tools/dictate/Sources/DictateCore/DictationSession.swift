import AVFoundation
import Foundation
import Speech

public enum DictationError: Error, CustomStringConvertible {
    case noAudioFormat, noConverter, languageUnsupported(String)
    public var description: String {
        switch self {
        case .noAudioFormat: "The speech engine has no audio format to take."
        case .noConverter: "Can't convert the microphone's audio for the speech engine."
        case .languageUnsupported(let id): "Apple's on-device speech engine doesn't have \(id)."
        }
    }
}

/// One dictation through Apple's on-device speech engine (SpeechAnalyzer + SpeechTranscriber, the engine Seal Speak
/// uses). `prepare` does the slow part (model, format, analyzer) ahead of time, so pressing Fn only starts the audio.
/// Feed it audio in any format, then `finish` for the words. A session is used once.
public final class DictationSession: @unchecked Sendable {
    private let transcriber: SpeechTranscriber
    private let analyzer: SpeechAnalyzer
    private let format: AVAudioFormat
    private let input: AsyncStream<AnalyzerInput>
    private let builder: AsyncStream<AnalyzerInput>.Continuation
    private var converter: AVAudioConverter?
    private var results: Task<String, Error>?
    private let lock = NSLock()
    public private(set) var fedSeconds = 0.0

    private init(transcriber: SpeechTranscriber, analyzer: SpeechAnalyzer, format: AVAudioFormat) {
        self.transcriber = transcriber
        self.analyzer = analyzer
        self.format = format
        (input, builder) = AsyncStream.makeStream(of: AnalyzerInput.self)
    }

    /// The person's language when the engine has it, else US English.
    public static func locale(preferred: [String] = Locale.preferredLanguages) async -> Locale {
        for id in preferred {
            if let l = await SpeechTranscriber.supportedLocale(equivalentTo: Locale(identifier: id)) { return l }
        }
        return Locale(identifier: "en-US")
    }

    public static func prepare(locale: Locale, hints: [String] = []) async throws -> DictationSession {
        let transcriber = SpeechTranscriber(locale: locale, transcriptionOptions: [], reportingOptions: [], attributeOptions: [])
        if !(await SpeechTranscriber.installedLocales.contains { $0.identifier(.bcp47) == locale.identifier(.bcp47) }) {
            guard await SpeechTranscriber.supportedLocale(equivalentTo: locale) != nil else {
                throw DictationError.languageUnsupported(locale.identifier(.bcp47))
            }
            // A one-time system download of the language's model.
            if let request = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
                try await request.downloadAndInstall()
            }
        }
        guard let format = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [transcriber]) else {
            throw DictationError.noAudioFormat
        }
        let analyzer = SpeechAnalyzer(modules: [transcriber])
        if !hints.isEmpty {
            let context = AnalysisContext()
            context.contextualStrings[.general] = hints
            try? await analyzer.setContext(context)
        }
        try await analyzer.prepareToAnalyze(in: format)
        return DictationSession(transcriber: transcriber, analyzer: analyzer, format: format)
    }

    public func start() async throws {
        let transcriber = self.transcriber
        results = Task {
            var parts: [String] = []
            for try await r in transcriber.results where r.isFinal { parts.append(String(r.text.characters)) }
            return parts.joined(separator: " ")
        }
        try await analyzer.start(inputSequence: input)
    }

    /// Safe to call from the audio thread.
    public func feed(_ buffer: AVAudioPCMBuffer) {
        lock.lock(); defer { lock.unlock() }
        if converter == nil || converter?.inputFormat != buffer.format {
            converter = AVAudioConverter(from: buffer.format, to: format)
        }
        guard let converter else { return }
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * format.sampleRate / buffer.format.sampleRate) + 1024
        guard let out = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: capacity) else { return }
        var supplied = false
        var error: NSError?
        converter.convert(to: out, error: &error) { _, status in
            if supplied { status.pointee = .noDataNow; return nil }
            supplied = true
            status.pointee = .haveData
            return buffer
        }
        guard error == nil, out.frameLength > 0 else { return }
        fedSeconds += Double(out.frameLength) / format.sampleRate
        builder.yield(AnalyzerInput(buffer: out))
    }

    /// No more audio: the words heard, before clean-up.
    public func finish() async throws -> String {
        builder.finish()
        try await analyzer.finalizeAndFinishThroughEndOfInput()
        return try await results?.value ?? ""
    }

    public func cancel() async {
        builder.finish()
        await analyzer.cancelAndFinishNow()
        results?.cancel()
    }

    /// The words in an audio file, as fast as the engine goes. For tests and `MarvinDictate --transcribe`.
    public static func transcribe(file: URL, locale: Locale, hints: [String] = []) async throws -> String {
        let session = try await prepare(locale: locale, hints: hints)
        try await session.start()
        let audio = try AVAudioFile(forReading: file)
        // Reading past the end throws rather than returning an empty buffer, so stop on the frame count.
        while audio.framePosition < audio.length {
            guard let buffer = AVAudioPCMBuffer(pcmFormat: audio.processingFormat, frameCapacity: 4096) else { break }
            try audio.read(into: buffer)
            if buffer.frameLength == 0 { break }
            session.feed(buffer)
        }
        return try await session.finish()
    }
}
