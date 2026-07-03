import CoreLocation
import Combine

/// Wraps CLLocationManager and publishes location updates.
/// Background location is the reason this app exists as a native wrapper —
/// a PWA/WKWebView stops updating GPS when the screen locks; this does not.
final class LocationManager: NSObject, ObservableObject {

    @Published var location: CLLocation?
    @Published var authorizationStatus: CLAuthorizationStatus = .notDetermined
    @Published var isTracking = false

    private let manager = CLLocationManager()

    // Callback fired on each location update — used by CoTClient to send a CoT event
    var onLocation: ((CLLocation) -> Void)?

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBest
        manager.distanceFilter = 5          // update every 5 metres minimum
        manager.pausesLocationUpdatesAutomatically = false
        manager.showsBackgroundLocationIndicator = true
        // allowsBackgroundLocationUpdates is set once authorization lands
        // (see locationManagerDidChangeAuthorization) — setting it without
        // Always authorization raises an exception.
    }

    func requestPermission() {
        manager.requestAlwaysAuthorization()
    }

    func startTracking() {
        guard authorizationStatus == .authorizedAlways ||
              authorizationStatus == .authorizedWhenInUse else {
            requestPermission()
            return
        }
        manager.startUpdatingLocation()
        isTracking = true
    }

    func stopTracking() {
        manager.stopUpdatingLocation()
        isTracking = false
    }
}

extension LocationManager: CLLocationManagerDelegate {

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let loc = locations.last, loc.horizontalAccuracy >= 0 else { return }
        // Always keep the latest fix (an SOS in a gorge needs the bad fix
        // rather than none); only suppress *sending* very poor fixes.
        location = loc
        guard loc.horizontalAccuracy < 100 else { return }
        onLocation?(loc)
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        authorizationStatus = manager.authorizationStatus
        if authorizationStatus == .authorizedAlways {
            // Safe to enable now: Always authorization + location background
            // mode (Info.plist) are both in place.
            manager.allowsBackgroundLocationUpdates = true
            startTracking()
        }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        print("[Location] Error: \(error.localizedDescription)")
    }
}
