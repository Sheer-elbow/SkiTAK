import Foundation
import Network
import Combine

/// Maintains a persistent TLS connection to the SkiTAK server on port 8089.
/// Sends CoT XML events (position updates, emergencies) and receives
/// incoming CoT from other clients (forwarded to the web dashboard via JS bridge).
final class CoTClient: ObservableObject {

    @Published var connectionState: ConnectionState = .disconnected
    @Published var serverAddress: String = UserDefaults.standard.string(forKey: "skitak.server") ?? ""
    @Published var callsign: String = UserDefaults.standard.string(forKey: "skitak.callsign") ?? ""
    @Published var teamName: String = UserDefaults.standard.string(forKey: "skitak.team") ?? "Cyan"

    private var connection: NWConnection?
    private var sendQueue = DispatchQueue(label: "io.skitak.cot-send", qos: .utility)
    private var receiveBuffer = Data()

    // Fired when a CoT event arrives from the server (passed to JS bridge)
    var onIncomingCoT: ((String) -> Void)?

    enum ConnectionState {
        case disconnected, connecting, connected, failed(String)
    }

    // MARK: - Connection lifecycle

    func connect(host: String, port: UInt16 = 8089) {
        guard !host.isEmpty else { return }
        serverAddress = host
        UserDefaults.standard.set(host, forKey: "skitak.server")

        connectionState = .connecting
        let endpoint = NWEndpoint.hostPort(
            host: NWEndpoint.Host(host),
            port: NWEndpoint.Port(rawValue: port)!
        )
        let params = buildTLSParameters()
        connection = NWConnection(to: endpoint, using: params)
        connection?.stateUpdateHandler = { [weak self] state in
            DispatchQueue.main.async { self?.handleStateChange(state) }
        }
        connection?.start(queue: sendQueue)
        receiveNextMessage()
    }

    func disconnect() {
        connection?.cancel()
        connection = nil
        DispatchQueue.main.async { self.connectionState = .disconnected }
    }

    // MARK: - Sending

    func sendLocation(_ location: CLLocation) {
        guard case .connected = connectionState else { return }
        let xml = CoTBuilder.saEvent(
            location: location,
            callsign: callsign,
            teamName: teamName
        )
        send(xml: xml)
    }

    func sendEmergency(location: CLLocation) {
        let xml = CoTBuilder.emergencyEvent(location: location, callsign: callsign)
        send(xml: xml)
    }

    private func send(xml: String) {
        guard let data = xml.data(using: .utf8) else { return }
        // TAK streaming format: send raw XML; server parses the stream
        connection?.send(content: data, completion: .contentProcessed { error in
            if let error { print("[CoT] Send error: \(error)") }
        })
    }

    // MARK: - Receiving

    private func receiveNextMessage() {
        connection?.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, isComplete, error in
            guard let self else { return }
            if let data, !data.isEmpty {
                self.receiveBuffer.append(data)
                self.parseBuffer()
            }
            if let error { print("[CoT] Receive error: \(error)") }
            if !isComplete { self.receiveNextMessage() }
        }
    }

    private func parseBuffer() {
        // CoT XML events end with </event> — extract complete events from buffer
        let marker = Data("</event>".utf8)
        while let range = receiveBuffer.range(of: marker) {
            let end = range.upperBound
            let eventData = receiveBuffer[..<end]
            receiveBuffer.removeSubrange(..<end)
            if let xml = String(data: eventData, encoding: .utf8) {
                DispatchQueue.main.async { self.onIncomingCoT?(xml) }
            }
        }
    }

    // MARK: - TLS configuration (mTLS with client certificate)

    private func buildTLSParameters() -> NWParameters {
        let tlsOptions = NWProtocolTLS.Options()
        let secOptions = tlsOptions.securityProtocolOptions

        // Attach client identity if enrolled
        if let identity = CertificateManager.shared.loadIdentity() {
            let secIdentity = identity as! SecIdentity
            if let tlsIdentity = sec_identity_create(secIdentity) {
                sec_protocol_options_set_local_identity(secOptions, tlsIdentity)
            }
        }

        // Trust the server's CA cert if we have it
        if let caCert = CertificateManager.shared.loadCACert() {
            sec_protocol_options_set_verify_block(secOptions, { _, trust, verifyComplete in
                let sslTrust = sec_trust_copy_ref(trust).takeRetainedValue()
                SecTrustSetAnchorCertificates(sslTrust, [caCert] as CFArray)
                SecTrustSetAnchorCertificatesOnly(sslTrust, true)
                SecTrustEvaluateAsyncWithError(sslTrust, .global()) { _, trusted, _ in
                    verifyComplete(trusted)
                }
            }, .global())
        }

        let tcpOptions = NWProtocolTCP.Options()
        tcpOptions.enableKeepalive = true
        tcpOptions.keepaliveIdle = 60

        return NWParameters(tls: tlsOptions, tcp: tcpOptions)
    }

    // MARK: - State handling

    private func handleStateChange(_ state: NWConnection.State) {
        switch state {
        case .ready:
            connectionState = .connected
        case .waiting(let error):
            connectionState = .failed(error.localizedDescription)
        case .failed(let error):
            connectionState = .failed(error.localizedDescription)
            scheduleReconnect()
        case .cancelled:
            connectionState = .disconnected
        default:
            break
        }
    }

    private func scheduleReconnect() {
        guard !serverAddress.isEmpty else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self] in
            guard let self, case .failed = self.connectionState else { return }
            self.connect(host: self.serverAddress)
        }
    }
}
