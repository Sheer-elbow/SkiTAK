import { useState } from 'react'
import { LiveMap } from '@/components/map/LiveMap'
import { ClientList } from '@/components/sidebar/ClientList'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { SessionPanel } from '@/components/sessions/SessionPanel'
import { useStore } from '@/store'
import clsx from 'clsx'

type Tab = 'clients' | 'chat' | 'session'

export function LiveMapPage() {
  const [tab, setTab] = useState<Tab>('clients')
  const clients = useStore((s) => s.clients)
  const onlineCount = Object.values(clients).filter((c) => c.isOnline).length

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <div className="w-72 flex-shrink-0 flex flex-col border-r border-surface-border">
        <div className="flex border-b border-surface-border">
          {([
            { id: 'clients' as Tab, label: 'Tracking' },
            { id: 'chat'    as Tab, label: 'Chat' },
            { id: 'session' as Tab, label: 'Session' },
          ] as const).map(({ id, label }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={clsx(
                'flex-1 py-2 text-xs font-medium transition-colors',
                tab === id
                  ? 'text-white border-b-2 border-accent -mb-px'
                  : 'text-gray-400 hover:text-gray-200',
              )}
            >
              {label}
              {id === 'clients' && onlineCount > 0 && (
                <span className="ml-1 text-accent-green font-mono">{onlineCount}</span>
              )}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-hidden">
          {tab === 'clients' && <ClientList />}
          {tab === 'chat'    && <ChatPanel />}
          {tab === 'session' && <SessionPanel />}
        </div>
      </div>

      {/* Map */}
      <div className="flex-1 relative">
        <LiveMap />
      </div>
    </div>
  )
}
