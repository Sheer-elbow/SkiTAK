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

1. Open Xcode → **File → New → Project → App**
2. Set:
   - Product Name: `SkiTAK`
   - Bundle Identifier: `io.skitak.app`
   - Interface: SwiftUI
   - Language: Swift
3. Delete the auto-generated `ContentView.swift` and `<App>.swift`
4. Drag all `.swift` files from `ios/SkiTAK/` into the project (preserving folder structure)
5. Replace the generated `Info.plist` with the one in `ios/SkiTAK/Info.plist`

## Required Capabilities (Xcode → Target → Signing & Capabilities)

| Capability | Setting |
|-----------|---------|
| Background Modes | ✅ Location updates, Remote notifications, Voice over IP, Background fetch |
| Push Notifications | ✅ |
| Associated Domains | `applinks:yourdomain.com` (for HTTPS deep links) |
| Keychain Sharing | Optional (for shared keychain groups) |

## Testing Without a Server

Run the Docker Compose stack locally:

```bash
make dev   # starts on localhost:8080
```

In the app, the deep link can be simulated by setting `skitak.server` in UserDefaults
to `localhost` and manually importing a test P12 cert.

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
