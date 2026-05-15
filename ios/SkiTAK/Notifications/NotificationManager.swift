import Foundation
import UserNotifications

/// Registers the APNs device token with the SkiTAK server so the server
/// can push emergency alerts and session invites to this device.
final class NotificationManager {

    static let shared = NotificationManager()
    private init() {}

    private var deviceToken: String?

    func registerToken(_ token: String) {
        deviceToken = token
        guard let server = UserDefaults.standard.string(forKey: "skitak.server"),
              !server.isEmpty,
              let uid = UserDefaults.standard.string(forKey: "skitak.callsign") else { return }
        Task { await uploadToken(token, server: server, uid: uid) }
    }

    private func uploadToken(_ token: String, server: String, uid: String) async {
        guard let url = URL(string: "https://\(server)/api/skitak/push-token") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONEncoder().encode(["token": token, "uid": uid, "platform": "apns"])
        _ = try? await URLSession.shared.data(for: req)
    }

    // MARK: - Local notifications (emergency alerts shown immediately)

    static func showEmergency(callsign: String, message: String) {
        let content = UNMutableNotificationContent()
        content.title = "⚠️ EMERGENCY"
        content.body = "\(callsign): \(message)"
        content.sound = .defaultCritical
        content.interruptionLevel = .critical

        let request = UNNotificationRequest(
            identifier: "emergency-\(UUID().uuidString)",
            content: content,
            trigger: nil  // deliver immediately
        )
        UNUserNotificationCenter.current().add(request, withCompletionHandler: nil)
    }
}
