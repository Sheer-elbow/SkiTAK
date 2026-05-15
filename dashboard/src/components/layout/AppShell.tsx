import { useState } from 'react'
import { LiveMap } from '@/components/map/LiveMap'
import { ClientList } from '@/components/sidebar/ClientList'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { SessionPanel } from '@/components/sessions/SessionPanel'
import { useStore } from '@/store'
import { useCoTSocket } from '@/hooks/useCoTSocket'
import clsx from 'clsx'

type Tab = 'clients' | 'chat' | 'session'

export function AppShell() {
  useCoTSocket()

  const [tab, setTab] = useState<Tab>('clients')
  const clients = useStore((s) => s.clients)
  const messages = useStore((s) => s.messages)
  const activeSession = useStore((s) => s.activeSession)

  const onlineCount = Object.values(clients).filter((c) => c.isOnline).length
  const unreadCount = 0  // TODO: track unread

  return (
    <div className="flex h-full bg-surface">
      {/* ── Sidebar ─────────────────────────────────────────────────────── */}
      <div className="w-72 flex-shrink-0 flex flex-col border-r border-surface-border">

        {/* Header */}
        <div className="px-4 py-3 border-b border-surface-border">
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold tracking-tight">SkiTAK</span>
            {activeSession && (
              <span className="text-xs bg-accent/20 text-accent px-2 py-0.5 rounded-full truncate max-w-[140px]">
                {activeSession.name}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1.5 mt-1">
            <span className={clsx(
              'w-2 h-2 rounded-full',
              onlineCount > 0 ? 'bg-accent-green animate-pulse' : 'bg-gray-600',
            )} />
            <span className="text-xs text-gray-400">
              {onlineCount} client{onlineCount !== 1 ? 's' : ''} online
            </span>
          </div>
        </div>

        {/* Tab bar */}
        <div className="flex border-b border-surface-border">
          {([
            { id: 'clients' as Tab, label: 'Clients', badge: onlineCount },
            { id: 'chat' as Tab, label: 'Chat', badge: unreadCount },
            { id: 'session' as Tab, label: 'Session', badge: 0 },
          ] as const).map(({ id, label, badge }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={clsx(
                'flex-1 py-2 text-xs font-medium transition-colors relative',
                tab === id
                  ? 'text-white border-b-2 border-accent -mb-px'
                  : 'text-gray-400 hover:text-gray-200',
              )}
            >
              {label}
              {badge > 0 && id === 'clients' && (
                <span className="ml-1 text-accent-green font-mono">{badge}</span>
              )}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="flex-1 overflow-hidden">
          {tab === 'clients' && <ClientList />}
          {tab === 'chat' && <ChatPanel />}
          {tab === 'session' && <SessionPanel />}
        </div>
      </div>

      {/* ── Map ─────────────────────────────────────────────────────────── */}
      <div className="flex-1 relative">
        <LiveMap />
      </div>
    </div>
  )
}
