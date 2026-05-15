import Foundation
import AVFoundation

/// Push-to-talk manager — Phase 2 placeholder.
/// Will connect to Mumble via the Mumble protocol or WebRTC.
/// For Phase 1, voice is handled by the Mumble iOS app separately.
final class PTTManager {

    static let shared = PTTManager()
    private init() {}

    private var isTransmitting = false

    func startTransmitting() {
        guard !isTransmitting else { return }
        isTransmitting = true
        configureAudioSession()
        // TODO Phase 2: open Mumble UDP audio stream to server
    }

    func stopTransmitting() {
        guard isTransmitting else { return }
        isTransmitting = false
        // TODO Phase 2: close audio stream
    }

    private func configureAudioSession() {
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playAndRecord, mode: .voiceChat, options: [.allowBluetooth, .defaultToSpeaker])
        try? session.setActive(true)
    }
}
