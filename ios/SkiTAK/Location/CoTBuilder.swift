import CoreLocation
import Foundation
import UIKit

/// Builds Cursor-on-Target XML events from device state.
/// The XML is sent as a streaming CoT event over TCP/TLS to the server.
enum CoTBuilder {

    static let deviceUID: String = {
        // Stable per-device identifier, stored in UserDefaults on first launch
        let key = "skitak.device_uid"
        if let existing = UserDefaults.standard.string(forKey: key) { return existing }
        let uid = "SKITAK-IOS-\(UUID().uuidString)"
        UserDefaults.standard.set(uid, forKey: key)
        return uid
    }()

    /// UIDevice.batteryLevel returns -1 until monitoring is enabled once.
    private static let batteryMonitoringEnabled: Bool = {
        UIDevice.current.isBatteryMonitoringEnabled = true
        return true
    }()

    static func currentBatteryLevel() -> Float {
        _ = batteryMonitoringEnabled
        return UIDevice.current.batteryLevel
    }

    /// SA position update — sent on every location fix
    static func saEvent(
        location: CLLocation,
        callsign: String,
        teamName: String = "Cyan",
        role: String = "Team Member",
        batteryLevel: Float? = nil,
        heartRateBpm: Int? = nil
    ) -> String {
        let now = Date()
        let stale = now.addingTimeInterval(5 * 60)  // stale after 5 min
        let speed = max(0, location.speed)
        let course = location.course >= 0 ? location.course : 0

        var heartRateXML = ""
        if let bpm = heartRateBpm {
            heartRateXML = "<skitak heart_rate_bpm=\"\(bpm)\"/>"
        }

        let level = batteryLevel ?? currentBatteryLevel()
        let battery = level >= 0 ? Int(level * 100) : -1
        let batteryAttr = battery >= 0 ? "battery=\"\(battery)\"" : ""

        return """
        <event version="2.0" \
        uid="\(deviceUID)" \
        type="a-f-G-U-C" \
        how="m-g" \
        time="\(iso8601(now))" \
        start="\(iso8601(now))" \
        stale="\(iso8601(stale))">
          <point \
        lat="\(location.coordinate.latitude)" \
        lon="\(location.coordinate.longitude)" \
        hae="\(location.altitude)" \
        ce="\(location.horizontalAccuracy)" \
        le="\(location.verticalAccuracy)"/>
          <detail>
            <contact callsign="\(callsign)" endpoint="*:-1:stcp"/>
            <__group name="\(teamName)" role="\(role)"/>
            <track speed="\(String(format: "%.2f", speed))" course="\(String(format: "%.1f", course))"/>
            <status \(batteryAttr)/>
            <precisionlocation geopointsrc="GPS" altsrc="GPS"/>
            \(heartRateXML)
          </detail>
        </event>
        """
    }

    /// Emergency beacon — sent when SOS is triggered
    static func emergencyEvent(location: CLLocation, callsign: String) -> String {
        let now = Date()
        let stale = now.addingTimeInterval(10 * 60)
        return """
        <event version="2.0" \
        uid="\(deviceUID)-9-1-1" \
        type="b-a-o-tbl" \
        how="h-g" \
        time="\(iso8601(now))" \
        start="\(iso8601(now))" \
        stale="\(iso8601(stale))">
          <point \
        lat="\(location.coordinate.latitude)" \
        lon="\(location.coordinate.longitude)" \
        hae="\(location.altitude)" \
        ce="\(location.horizontalAccuracy)" \
        le="9999999.0"/>
          <detail>
            <contact callsign="\(callsign)"/>
            <remarks>EMERGENCY — \(callsign) requires assistance</remarks>
            <emergency type="911"/>
          </detail>
        </event>
        """
    }

    private static let formatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    private static func iso8601(_ date: Date) -> String {
        formatter.string(from: date)
    }
}
