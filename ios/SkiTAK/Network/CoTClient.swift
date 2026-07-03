import Foundation
import CoreLocation
import Network
import Combine

/// Maintains a persistent TLS connection to the SkiTAK server on port 8089.
/// Sends CoT XML events (position updates, emergencies) and receives
/// incoming CoT from other clients (forwarded to the web dashboard via JS bridge).
///
/// Offline-first: events that can't be delivered are stored in `EventQueue`
/// and replayed in order when the connection comes back.
final class CoTClient: ObservableObject {

    @Published var connectionState: ConnectionState = .disconnected
    @Published var serverAddress: String = UserDefaults.standard.string(forKey: "skitak.server") ?? ""
    @Published var callsign: String = UserDefaults.standard.string(forKey: "skitak.callsign") ?? ""
    @Published var teamName: String = UserDefaults.standard.string(forKey: "skitak.team") ?? "Cyan"
    @Published var queuedEventCount: Int = 0

    private var connection: NWConnection?
    private let sendQueue = DispatchQueue(label: "io.skitak.cot-send", qos: .utility)
    private var receiveBuffer = Data()
    private let eventQueue = EventQueue()
    private var reconnectAttempts = 0

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

        connection?.cancel()
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
        let xml = CoTBuilder.saEvent(
            location: location,
            callsign: callsign,
            teamName: teamName
        )
        deliverOrQueue(xml: xml, isEmergency: false)
    }

    /// SOS must never be lost: queued if offline, and a reconnect is kicked
    /// off immediately so it goes out the moment there's any signal.
    func sendEmergency(location: CLLocation) {
        let xml = CoTBuilder.emergencyEvent(location: location, callsign: callsign)
        deliverOrQueue(xml: xml, isEmergency: true)
        if case .connected = connectionState {} else {
            connect(host: serverAddress)
        }
    }

    private func deliverOrQueue(xml: String, isEmergency: Bool) {
        guard case .connected = connectionState else {
            enqueue(xml: xml, isEmergency: isEmergency)
            return
        }
        send(xml: xml) { [weak self] error in
            if error != nil {
                self?.enqueue(xml: xml, isEmergency: isEmergency)
            }
        }
    }

    private func enqueue(xml: String, isEmergency: Bool) {
        eventQueue.enqueue(xml: xml, isEmergency: isEmergency)
        DispatchQueue.main.async { self.queuedEventCount = self.eventQueue.count }
    }

    private func send(xml: String, completion: ((Error?) -> Void)? = nil) {
        guard let data = xml.data(using: .utf8) else { return }
        // TAK streaming format: send raw XML; server parses the stream
        connection?.send(content: data, completion: .contentProcessed { error in
            if let error { print("[CoT] Send error: \(error)") }
            completion?(error)
        })
    }

    /// Replay everything that queued up while offline, oldest first.
    private func flushQueue() {
        let pending = eventQueue.drain()
        DispatchQueue.main.async { self.queuedEventCount = 0 }
        guard !pending.isEmpty else { return }
        print("[CoT] Flushing \(pending.count) queued event(s)")
        for event in pending {
            send(xml: event.xml) { [weak self] error in
                if error != nil {
                    self?.eventQueue.requeue([event])
                    DispatchQueue.main.async {
                        self?.queuedEventCount = self?.eventQueue.count ?? 0
                    }
                }
            }
        }
    }

    // MARK: - Receiving

    private func receiveNextMessage() {
        connection?.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, isComplete, error in
            guard let self else { return }
            if let data, !data.isEmpty {
                self.receiveBuffer.append(data)
                self.parseBuffer()
            }
            if let error {
                // Do not re-arm on a dead connection — that spins. The state
                // handler drives reconnection.
                print("[CoT] Receive error: \(error)")
                return
            }
            if isComplete {
                DispatchQueue.main.async { self.connectionState = .disconnected }
                self.scheduleReconnect()
                return
            }
            self.receiveNextMessage()
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
        if let identity = CertificateManager.shared.loadIdentity(),
           let tlsIdentity = sec_identity_create(identity) {
            sec_protocol_options_set_local_identity(secOptions, tlsIdentity)
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
            reconnectAttempts = 0
            flushQueue()
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
        // Exponential backoff: 2s, 4s, 8s … capped at 60s
        let delay = min(60.0, pow(2.0, Double(min(reconnectAttempts, 5))) * 2.0)
        reconnectAttempts += 1
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self else { return }
            switch self.connectionState {
            case .failed, .disconnected:
                self.connect(host: self.serverAddress)
            default:
                break
            }
        }
    }
}
