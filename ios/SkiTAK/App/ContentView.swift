import SwiftUI

struct ContentView: View {
    @EnvironmentObject var locationManager: LocationManager
    @EnvironmentObject var cotClient: CoTClient
    @EnvironmentObject var deepLinkHandler: DeepLinkHandler

    @State private var webViewRef: WebViewWrapper?
    @State private var isWebLoading = false

    var body: some View {
        ZStack {
            // ── Main screen ───────────────────────────────────────────────
            if cotClient.serverAddress.isEmpty || !CertificateManager.shared.hasIdentity {
                OnboardingView()
            } else {
                mainView
            }

            // ── Enrollment overlay ────────────────────────────────────────
            if deepLinkHandler.isEnrolling {
                enrollingOverlay
            }
        }
        .onAppear {
            UIDevice.current.isBatteryMonitoringEnabled = true
            locationManager.requestPermission()
            wireLocationToCoT()
            wireCoTToWebView()
        }
    }

    // MARK: - Main view

    private var mainView: some View {
        ZStack(alignment: .bottom) {
            // WKWebView loading the React dashboard
            WebViewContainer(
                serverAddress: cotClient.serverAddress,
                isLoading: $isWebLoading
            ) { message in
                handleWebMessage(message)
            }
            .ignoresSafeArea()

            // Status bar — connection + tracking indicator
            statusBar
                .padding(.horizontal, 16)
                .padding(.bottom, 8)
        }
    }

    private var statusBar: some View {
        HStack(spacing: 10) {
            // Connection indicator
            HStack(spacing: 5) {
                Circle()
                    .fill(connectionColor)
                    .frame(width: 8, height: 8)
                    .overlay {
                        if case .connected = cotClient.connectionState {
                            Circle().fill(connectionColor).scaleEffect(1.8).opacity(0.3)
                                .animation(.easeInOut(duration: 1).repeatForever(), value: true)
                        }
                    }
                Text(connectionLabel)
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(.white.opacity(0.8))
            }

            Spacer()

            // SOS button
            Button {
                triggerSOS()
            } label: {
                Text("SOS")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(Color.red)
                    .clipShape(Capsule())
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(.black.opacity(0.5))
        .clipShape(Capsule())
    }

    private var enrollingOverlay: some View {
        ZStack {
            Color.black.opacity(0.8).ignoresSafeArea()
            VStack(spacing: 16) {
                ProgressView()
                    .tint(.white)
                    .scaleEffect(1.5)
                Text("Setting up SkiTAK…")
                    .foregroundStyle(.white)
                    .font(.headline)
                if let error = deepLinkHandler.enrollmentError {
                    Text(error)
                        .foregroundStyle(.red)
                        .font(.subheadline)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal)
                }
            }
        }
    }

    // MARK: - Wiring

    private func wireLocationToCoT() {
        locationManager.onLocation = { [weak cotClient] location in
            cotClient?.sendLocation(location)
        }
    }

    private func wireCoTToWebView() {
        // Incoming CoT events from server → forwarded to web dashboard via JS
        // The web dashboard's useCoTSocket hook handles positioning/chat/POIs
        // from its own WebSocket connection, so this is a fallback for
        // events the web socket misses (e.g. while backgrounded)
    }

    // MARK: - Web → Native messages

    private func handleWebMessage(_ message: WebMessage) {
        switch message.handler {
        case .sos:
            triggerSOS()
        case .pttStart:
            PTTManager.shared.startTransmitting()
        case .pttStop:
            PTTManager.shared.stopTransmitting()
        case .shareTrack:
            shareTrack(message.body)
        case .requestLocation:
            break // location is streamed continuously via CoT
        }
    }

    private func triggerSOS() {
        guard let location = locationManager.location else { return }
        cotClient.sendEmergency(location: location)
        NotificationManager.showEmergency(
            callsign: cotClient.callsign,
            message: "SOS triggered — needs assistance"
        )
    }

    private func shareTrack(_ body: [String: Any]) {
        guard let urlString = body["url"] as? String,
              let url = URL(string: urlString) else { return }
        let av = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .first?.windows.first?.rootViewController?
            .present(av, animated: true)
    }

    // MARK: - Connection display

    private var connectionColor: Color {
        switch cotClient.connectionState {
        case .connected:    return .green
        case .connecting:   return .yellow
        case .disconnected: return .gray
        case .failed:       return .red
        }
    }

    private var connectionLabel: String {
        switch cotClient.connectionState {
        case .connected:       return "\(cotClient.callsign) · LIVE"
        case .connecting:      return "Connecting…"
        case .disconnected:    return "Offline"
        case .failed(let msg): return "Error: \(msg)"
        }
    }
}

// Minimal type alias — resolved at compile time
typealias WebViewWrapper = WebViewContainer
