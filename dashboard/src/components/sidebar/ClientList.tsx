import { useStore } from '@/store'
import { TEAM_COLORS } from '@/types'
import { formatDistanceToNow } from 'date-fns'
import { downloadGpx } from '@/api'
import clsx from 'clsx'

export function ClientList() {
  const clients = useStore((s) => s.clients)
  const activeSession = useStore((s) => s.activeSession)
  const selectedUid = useStore((s) => s.selectedUid)
  const selectClient = useStore((s) => s.selectClient)

  const sorted = Object.values(clients).sort((a, b) =>
    a.callsign.localeCompare(b.callsign),
  )

  if (sorted.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-48 text-gray-500 text-sm gap-2">
        <span className="text-3xl">📡</span>
        <span>No clients connected</span>
      </div>
    )
  }

  return (
    <div className="divide-y divide-surface-border overflow-y-auto">
      {sorted.map((client) => {
        const team = activeSession?.teams.find((t) => t.memberUids.includes(client.uid))
        const teamColor = TEAM_COLORS[client.teamColor]
        const isSelected = client.uid === selectedUid

        return (
          <div
            key={client.uid}
            onClick={() => selectClient(isSelected ? null : client.uid)}
            className={clsx(
              'flex items-start gap-3 px-4 py-3 cursor-pointer transition-colors hover:bg-surface-raised',
              isSelected && 'bg-surface-raised ring-1 ring-inset ring-accent',
            )}
          >
            {/* Avatar */}
            <div
              className="w-9 h-9 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-bold text-white uppercase mt-0.5"
              style={{ background: client.isOnline ? teamColor : '#6b7280' }}
            >
              {client.callsign.slice(0, 2)}
            </div>

            {/* Info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium text-sm truncate">{client.callsign}</span>
                {!client.isOnline && (
                  <span className="text-xs text-gray-500 flex-shrink-0">offline</span>
                )}
              </div>

              {team && (
                <div className="text-xs text-gray-400 mt-0.5" style={{ color: teamColor }}>
                  {team.name}
                </div>
              )}

              <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                {client.speedMs != null && (
                  <span>{(client.speedMs * 3.6).toFixed(1)} km/h</span>
                )}
                {client.batteryPct != null && (
                  <span className={clsx(client.batteryPct < 20 && 'text-accent-amber')}>
                    🔋 {client.batteryPct}%
                  </span>
                )}
                {client.heartRateBpm != null && (
                  <span>♥ {client.heartRateBpm} bpm</span>
                )}
              </div>

              <div className="text-xs text-gray-600 mt-0.5">
                {formatDistanceToNow(client.lastSeen, { addSuffix: true })}
              </div>
            </div>

            {/* Actions (visible on hover/select) */}
            {isSelected && activeSession && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  downloadGpx(activeSession.id, client.uid, client.callsign)
                }}
                className="flex-shrink-0 text-xs text-accent hover:text-blue-300 mt-1"
                title="Export GPX"
              >
                GPX
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}
