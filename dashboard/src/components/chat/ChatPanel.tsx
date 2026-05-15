import { useStore } from '@/store'
import { TEAM_COLORS } from '@/types'
import { format } from 'date-fns'
import clsx from 'clsx'

export function ChatPanel() {
  const messages = useStore((s) => s.messages)
  const clients = useStore((s) => s.clients)
  const currentUserUid = useStore((s) => s.currentUserUid)

  if (messages.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-48 text-gray-500 text-sm gap-2">
        <span className="text-3xl">💬</span>
        <span>No messages yet</span>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
        {messages.map((msg) => {
          const isOwn = msg.fromUid === currentUserUid
          const sender = clients[msg.fromUid]
          const teamColor = sender ? TEAM_COLORS[sender.teamColor] : '#6b7280'

          return (
            <div key={msg.id} className={clsx('flex flex-col', isOwn && 'items-end')}>
              <div className="flex items-baseline gap-1.5 mb-0.5">
                <span className="text-xs font-medium" style={{ color: teamColor }}>
                  {msg.fromCallsign}
                </span>
                <span className="text-xs text-gray-600">
                  {format(msg.sentAt, 'HH:mm')}
                </span>
                {msg.location && (
                  <span className="text-xs text-gray-600" title="Geo-referenced message">
                    📍
                  </span>
                )}
              </div>
              <div
                className={clsx(
                  'max-w-[85%] px-3 py-2 rounded-lg text-sm',
                  isOwn
                    ? 'bg-accent text-white rounded-tr-sm'
                    : 'bg-surface-raised text-gray-100 rounded-tl-sm',
                )}
              >
                {msg.body}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
