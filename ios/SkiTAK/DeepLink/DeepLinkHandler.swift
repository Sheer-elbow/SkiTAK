import Foundation
import UIKit

/// Handles the zero-friction client onboarding deep link.
///
/// Flow:
///   1. Guide creates a session + team, copies invite link
///   2. Client receives link (WhatsApp, AirDrop, SMS): skitak://join/<token>
///      or https://server/join/<token>
///   3. App opens, hits /api/enroll/<token> on the server
///   4. Server returns: callsign, PKCS12 cert data, CA cert, server address
///   5. App stores certs in Keychain, saves server/callsign, starts tracking
///
final class DeepLinkHandler: ObservableObject {

    @Published var isEnrolling = false
    @Published var enrollmentError: String?
    @Published var didEnroll = false

    func handle(_ url: URL, cotClient: CoTClient) {
        // Accept both skitak://join/<token> and https://<host>/join/<token>
        guard let token = extractToken(from: url),
              let serverHost = extractHost(from: url) else { return }

        Task { @MainActor in
            await enroll(token: token, serverHost: serverHost, cotClient: cotClient)
        }
    }

    @MainActor
    private func enroll(token: String, serverHost: String, cotClient: CoTClient) async {
        isEnrolling = true
        enrollmentError = nil

        do {
            let payload = try await fetchEnrollmentPackage(token: token, host: serverHost)

            // Import CA cert so we trust the server
            if let caData = Data(base64Encoded: payload.caCertBase64) {
                try CertificateManager.shared.importCACert(data: caData)
            }

            // Import client identity (PKCS12)
            let clientP12 = Data(base64Encoded: payload.clientP12Base64)!
            try CertificateManager.shared.importP12(data: clientP12, passphrase: payload.p12Passphrase)

            // Persist config
            cotClient.callsign = payload.callsign
            cotClient.teamName = payload.teamName
            cotClient.serverAddress = serverHost
            UserDefaults.standard.set(payload.callsign, forKey: "skitak.callsign")
            UserDefaults.standard.set(payload.teamName, forKey: "skitak.team")
            UserDefaults.standard.set(serverHost, forKey: "skitak.server")

            // Connect
            cotClient.connect(host: serverHost)
            didEnroll = true

        } catch {
            enrollmentError = error.localizedDescription
        }

        isEnrolling = false
    }

    // MARK: - Helpers

    private func extractToken(from url: URL) -> String? {
        // skitak://join/<token>  or  https://host/join/<token>
        let components = url.pathComponents
        guard let joinIndex = components.firstIndex(of: "join"),
              joinIndex + 1 < components.count else { return nil }
        return components[joinIndex + 1]
    }

    private func extractHost(from url: URL) -> String? {
        if url.scheme == "skitak" {
            // Host stored in first path component for skitak:// scheme
            return UserDefaults.standard.string(forKey: "skitak.server")
        }
        return url.host
    }

    private func fetchEnrollmentPackage(token: String, host: String) async throws -> EnrollmentPayload {
        let url = URL(string: "https://\(host)/api/skitak/enroll/\(token)")!
        let (data, response) = try await URLSession.shared.data(from: url)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw EnrollError.serverError
        }
        return try JSONDecoder().decode(EnrollmentPayload.self, from: data)
    }
}

struct EnrollmentPayload: Decodable {
    let callsign: String
    let teamName: String
    let caCertBase64: String
    let clientP12Base64: String
    let p12Passphrase: String
    let sessionId: String
}

enum EnrollError: LocalizedError {
    case serverError
    var errorDescription: String? { "Could not reach the SkiTAK server. Check your link." }
}
