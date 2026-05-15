import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { clientsApi, ClientRecord } from '@/api/clients'
import { AddClientModal } from '@/components/clients/AddClientModal'
import { ClientDetail } from '@/components/clients/ClientDetail'
import { formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'

export function ClientsPage() {
  const qc = useQueryClient()
  const { data: clients = [], isLoading } = useQuery({
    queryKey: ['clients'],
    queryFn: clientsApi.list,
  })

  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<ClientRecord | null>(null)
  const [showAdd, setShowAdd] = useState(false)

  const filtered = clients.filter((c) =>
    [c.display_name, c.callsign, c.email, c.phone]
      .filter(Boolean)
      .some((v) => v!.toLowerCase().includes(search.toLowerCase())),
  )

  function handleCreated() {
    qc.invalidateQueries({ queryKey: ['clients'] })
    setShowAdd(false)
  }

  function handleDeleted() {
    qc.invalidateQueries({ queryKey: ['clients'] })
    setSelected(null)
  }

  return (
    <div className="flex h-full bg-surface">
      {/* ── Client list ────────────────────────────────────────────── */}
      <div className={clsx(
        'flex flex-col border-r border-surface-border transition-all',
        selected ? 'w-72 flex-shrink-0' : 'flex-1',
      )}>
        {/* Toolbar */}
        <div className="px-4 py-3 border-b border-surface-border space-y-3">
          <div className="flex items-center justify-between">
            <h1 className="font-semibold">Clients</h1>
            <button
              onClick={() => setShowAdd(true)}
              className="flex items-center gap-1.5 bg-accent hover:bg-blue-500 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors"
            >
              <span className="text-base leading-none">+</span> Add Client
            </button>
          </div>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name, callsign, email…"
            className="w-full bg-surface-raised border border-surface-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-accent placeholder:text-gray-600"
          />
          <p className="text-xs text-gray-500">
            {filtered.length} {filtered.length === 1 ? 'client' : 'clients'}
          </p>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto divide-y divide-surface-border">
          {isLoading && (
            <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
              Loading…
            </div>
          )}

          {!isLoading && filtered.length === 0 && (
            <div className="flex flex-col items-center justify-center h-48 text-gray-500 text-sm gap-2 px-6 text-center">
              <span className="text-3xl">👥</span>
              {clients.length === 0
                ? <>
                    <span>No clients yet.</span>
                    <button
                      onClick={() => setShowAdd(true)}
                      className="text-accent hover:text-blue-300 text-sm"
                    >
                      Add your first client →
                    </button>
                  </>
                : <span>No clients match "{search}"</span>
              }
            </div>
          )}

          {filtered.map((client) => (
            <ClientRow
              key={client.id}
              client={client}
              isSelected={selected?.id === client.id}
              onClick={() => setSelected(selected?.id === client.id ? null : client)}
            />
          ))}
        </div>
      </div>

      {/* ── Detail panel ───────────────────────────────────────────── */}
      {selected && (
        <div className="flex-1 flex flex-col min-w-0">
          <ClientDetail
            client={selected}
            onClose={() => setSelected(null)}
            onDeleted={handleDeleted}
          />
        </div>
      )}

      {/* ── Add client modal ───────────────────────────────────────── */}
      {showAdd && (
        <AddClientModal
          onClose={() => setShowAdd(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  )
}

function ClientRow({
  client,
  isSelected,
  onClick,
}: {
  client: ClientRecord
  isSelected: boolean
  onClick: () => void
}) {
  const certExpired = client.cert_expires_at
    ? new Date(client.cert_expires_at) < new Date()
    : true
  const needsAttention = !client.has_enrolled || certExpired

  return (
    <button
      onClick={onClick}
      className={clsx(
        'w-full flex items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-raised',
        isSelected && 'bg-surface-raised ring-1 ring-inset ring-accent',
      )}
    >
      {/* Avatar */}
      <div className={clsx(
        'w-9 h-9 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-bold uppercase mt-0.5',
        client.has_enrolled && !certExpired ? 'bg-accent' : 'bg-surface-border',
      )}>
        {client.display_name.slice(0, 2)}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm truncate">{client.display_name}</span>
          {needsAttention && (
            <span className="text-[10px] text-accent-amber flex-shrink-0">
              {!client.has_enrolled ? 'Not enrolled' : 'Cert expired'}
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500 font-mono">{client.callsign}</p>
        <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-600">
          <span>{client.total_sessions} sessions</span>
          <span>·</span>
          <span>{client.total_distance_km.toFixed(0)} km</span>
          {client.last_seen_at && (
            <>
              <span>·</span>
              <span>{formatDistanceToNow(new Date(client.last_seen_at), { addSuffix: true })}</span>
            </>
          )}
        </div>
      </div>
    </button>
  )
}
