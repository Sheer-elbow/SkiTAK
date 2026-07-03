import Foundation

/// Store-and-forward queue for CoT events.
///
/// Offline-first is a core requirement (PLAN.md): positions recorded in a
/// dead zone must reach the server when signal returns, and an SOS pressed
/// offline must never be silently dropped.
///
/// Behaviour:
///   - Events are appended to an in-memory ring buffer and persisted to disk,
///     so a force-quit or crash doesn't lose them.
///   - Position (SA) events are capped at `maxPositionEvents`; oldest are
///     dropped first — a stale position is worthless, a recent one isn't.
///   - Emergency events are never dropped.
///   - `drain` hands back everything in order for replay on reconnect.
final class EventQueue {

    struct QueuedEvent: Codable {
        let xml: String
        let isEmergency: Bool
        let queuedAt: Date
    }

    private let maxPositionEvents: Int
    private var events: [QueuedEvent] = []
    private let queue = DispatchQueue(label: "io.skitak.event-queue")
    private let fileURL: URL

    init(maxPositionEvents: Int = 500, filename: String = "cot-queue.json") {
        self.maxPositionEvents = maxPositionEvents
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        self.fileURL = dir.appendingPathComponent(filename)
        load()
    }

    var count: Int { queue.sync { events.count } }

    func enqueue(xml: String, isEmergency: Bool = false) {
        queue.sync {
            events.append(QueuedEvent(xml: xml, isEmergency: isEmergency, queuedAt: Date()))
            trimLocked()
            persistLocked()
        }
    }

    /// Remove and return all queued events, oldest first.
    /// If sending fails, re-enqueue what wasn't delivered via `requeue`.
    func drain() -> [QueuedEvent] {
        queue.sync {
            let drained = events
            events = []
            persistLocked()
            return drained
        }
    }

    /// Put undelivered events back at the front of the queue.
    func requeue(_ undelivered: [QueuedEvent]) {
        queue.sync {
            events.insert(contentsOf: undelivered, at: 0)
            trimLocked()
            persistLocked()
        }
    }

    // MARK: - Internal (call only on `queue`)

    private func trimLocked() {
        let positionCount = events.filter { !$0.isEmergency }.count
        guard positionCount > maxPositionEvents else { return }
        var toDrop = positionCount - maxPositionEvents
        events.removeAll { event in
            if toDrop > 0 && !event.isEmergency {
                toDrop -= 1
                return true
            }
            return false
        }
    }

    private func persistLocked() {
        if let data = try? JSONEncoder().encode(events) {
            try? data.write(to: fileURL, options: .atomic)
        }
    }

    private func load() {
        guard let data = try? Data(contentsOf: fileURL),
              let saved = try? JSONDecoder().decode([QueuedEvent].self, from: data) else { return }
        events = saved
    }
}
