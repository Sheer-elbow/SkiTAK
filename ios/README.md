# SkiTAK iOS App

Thin SwiftUI native wrapper providing:
- **Background location** — CLLocationManager keeps tracking when screen locks
- **CoT client** — sends GPS positions over TLS to the SkiTAK server (port 8089)
- **mTLS** — client certificate stored in the iOS Keychain (Secure Enclave)
- **WKWebView shell** — loads the React dashboard from your server
- **Deep link onboarding** — `skitak://join/<token>` auto-installs certs and connects
- **Emergency SOS** — one-tap CoT emergency beacon + critical APNs notification
- **JS bridge** — web app can call native PTT, SOS, share sheet

## Requirements

- Xcode 16+
- iOS 17+ deployment target
- Apple Developer account (for device testing and background location entitlement)

## Setting Up the Xcode Project

The project file is generated from `project.yml` with [XcodeGen](https://github.com/yonaskolb/XcodeGen):

```bash
brew install xcodegen
cd ios
xcodegen generate
open SkiTAK.xcodeproj
```

Then in Xcode → Target → Signing & Capabilities:

1. Select your development **Team** (signing is set to Automatic)
2. Edit `SkiTAK/SkiTAK.entitlements` — replace `skitak.yourdomain.com`
   with your real domain for HTTPS deep links (or remove the associated
   domains entry while testing with the `skitak://` scheme only)

Background modes, location permission strings, and the URL scheme are already
configured in `SkiTAK/Info.plist`; push + associated domains live in the
entitlements file.

## Testing Against a Local Server

Run the Docker Compose stack (`make dev`) and make sure the Mac and the
iPhone share a network. Create a session + invite via the dashboard, then
open the invite link on the phone — enrollment installs the certificate into
the Keychain and connects to port 8089. Test on a **physical device**:
background location does not behave realistically in the simulator.

## Offline Behaviour

`EventQueue` persists undeliverable CoT events to disk: position updates are
kept up to the most recent 500, and emergency (SOS) events are never dropped.
The queue is flushed in order whenever the TLS connection comes back, and an
SOS triggered while offline also forces an immediate reconnect attempt.

## Distribution

- **Internal testing**: TestFlight (guide devices, internal team)
- **Client distribution**: TestFlight public link or Ad Hoc profile

For commercial distribution, a separate "SkiTAK Client" target with a
simplified UI (no guide features) would be App Store appropriate.

## Architecture Notes

```
┌─────────────────────────────────────────────────────────────┐
│  ContentView                                                │
│  ├── OnboardingView (if not enrolled)                       │
│  └── WebViewContainer (WKWebView → React dashboard)         │
│      └── statusBar (connection indicator + SOS button)      │
└────────────────────┬────────────────────────────────────────┘
                     │ reads/writes
┌────────────────────▼────────────────────────────────────────┐
│  LocationManager (CLLocationManager)                        │
│  └── onLocation callback                                    │
│           │ CLLocation                                      │
│           ▼                                                 │
│  CoTClient (NWConnection TLS → port 8089)                   │
│  └── CoTBuilder.saEvent() → CoT XML → TCP stream            │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  DeepLinkHandler                                            │
│  └── skitak://join/<token>                                  │
│      → fetch /api/skitak/enroll/<token>                     │
│      → CertificateManager.importP12()  (Keychain)          │
│      → CoTClient.connect()                                  │
└─────────────────────────────────────────────────────────────┘
```
