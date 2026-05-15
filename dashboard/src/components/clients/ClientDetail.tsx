import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { clientsApi, ClientRecord, SessionSummary } from '@/api/clients'
import { ACTIVITY_LABELS } from '@/types'
import { formatDistanceToNow, format, isPast } from 'date-fns'
import clsx from 'clsx'

interface Props {
  client: ClientRecord
  onClose: () => void
  onDeleted: () => void
}

export function ClientDetail({ client, onClose, onDeleted }: Props) {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['client', client.id],
    queryFn: () => clientsApi.get(client.id),
    initialData: client,
  })

  const [enrollResult, setEnrollResult] = useState<{ join_url: string; callsign: string } | null>(null)
  const [enrolling, setEnrolling] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [editing, setEditing] = useState(false)

  const certExpired = data.cert_expires_at ? isPast(new Date(data.cert_expires_at)) : true
  const needsEnrollment = !data.has_enrolled || certExpired

  async function handleEnroll() {
    setEnrolling(true)
    try {
      const result = await clientsApi.enroll(data.id, {})
      setEnrollResult(result)
      await navigator.clipboard.writeText(result.join_url).catch(() => {})
      qc.invalidateQueries({ queryKey: ['clients'] })
    } finally {
      setEnrolling(false)
    }
  }

  async function handleDelete() {
    if (!confirm(`Remove ${data.display_name} from your client list? Their session history will also be removed.`)) return
    setDeleting(true)
    try {
      await clientsApi.delete(data.id)
      onDeleted()
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-start justify-between px-6 py-4 border-b border-surface-border">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-accent flex items-center justify-center font-bold text-sm uppercase">
            {data.display_name.slice(0, 2)}
          </div>
          <div>
            <h2 className="font-semibold">{data.display_name}</h2>
            <p className="text-xs text-gray-400 font-mono">{data.callsign}</p>
          </div>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-white text-xl">×</button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Stats strip */}
        <div className="grid grid-cols-3 divide-x divide-surface-border border-b border-surface-border">
          <Stat label="Sessions" value={String(data.total_sessions)} />
          <Stat label="Distance" value={`${data.total_distance_km.toFixed(0)} km`} />
          <Stat
            label="Last seen"
            value={data.last_seen_at
              ? formatDistanceToNow(new Date(data.last_seen_at), { addSuffix: true })
              : 'Never'}
          />
        </div>

        <div className="px-6 py-5 space-y-6">
          {/* Contact info */}
          <Section title="Contact">
            <InfoRow label="Email" value={data.email} />
            <InfoRow label="Phone" value={data.phone} />
            {data.notes && (
              <div className="mt-2 text-sm text-gray-300 bg-surface rounded-lg px-3 py-2 leading-relaxed">
                {data.notes}
              </div>
            )}
          </Section>

          {/* Enrollment */}
          <Section title="Enrollment">
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className={clsx('text-sm font-medium',
                  data.has_enrolled && !certExpired ? 'text-accent-green' : 'text-accent-amber'
                )}>
                  {!data.has_enrolled
                    ? 'Not yet enrolled'
                    : certExpired
                    ? 'Certificate expired'
                    : 'Enrolled'}
                </p>
                {data.cert_expires_at && !certExpired && (
                  <p className="text-xs text-gray-500 mt-0.5">
                    Cert expires {format(new Date(data.cert_expires_at), 'd MMM yyyy')}
                  </p>
                )}
              </div>
              <button
                onClick={handleEnroll}
                disabled={enrolling}
                className="text-xs bg-accent hover:bg-blue-500 disabled:opacity-40 rounded-lg px-3 py-1.5 font-medium transition-colors"
              >
                {enrolling ? 'Generating…' : needsEnrollment ? 'Send Invite' : 'Resend Invite'}
              </button>
            </div>

            {enrollResult && (
              <div className="bg-accent/10 border border-accent/30 rounded-lg px-3 py-3 space-y-2">
                <p className="text-xs text-accent font-medium">Link copied to clipboard</p>
                <p className="text-xs text-gray-300 break-all font-mono">{enrollResult.join_url}</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => navigator.clipboard.writeText(enrollResult.join_url)}
                    className="text-xs text-accent hover:text-blue-300"
                  >
                    Copy again
                  </button>
                  <button
                    onClick={() => setEnrollResult(null)}
                    className="text-xs text-gray-500"
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            )}
          </Section>

          {/* Session history */}
          <Section title="Session history">
            {!data.sessions?.length ? (
              <p className="text-sm text-gray-500">No sessions yet.</p>
            ) : (
              <div className="space-y-2">
                {data.sessions!.map((s) => (
                  <SessionRow key={s.id} session={s} />
                ))}
              </div>
            )}
          </Section>
        </div>
      </div>

      {/* Footer actions */}
      <div className="px-6 py-4 border-t border-surface-border flex justify-end">
        <button
          onClick={handleDelete}
          disabled={deleting}
          className="text-xs text-accent-red hover:text-red-300 disabled:opacity-40"
        >
          {deleting ? 'Removing…' : 'Remove client'}
        </button>
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-4 py-3 text-center">
      <p className="text-lg font-semibold">{value}</p>
      <p className="text-xs text-gray-500">{label}</p>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-xs text-gray-400 uppercase tracking-wider mb-3">{title}</h3>
      {children}
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null
  return (
    <div className="flex justify-between text-sm py-1">
      <span className="text-gray-500">{label}</span>
      <span className="text-gray-200">{value}</span>
    </div>
  )
}

function SessionRow({ session }: { session: SessionSummary }) {
  return (
    <div className="bg-surface rounded-lg px-3 py-2.5">
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium truncate">{session.name}</p>
          <p className="text-xs text-gray-500 mt-0.5">
            {ACTIVITY_LABELS[session.activity_type as keyof typeof ACTIVITY_LABELS] ?? session.activity_type}
            {session.started_at && ` · ${format(new Date(session.started_at), 'd MMM yyyy')}`}
          </p>
        </div>
        <div className="text-right ml-3 flex-shrink-0">
          {session.distance_km != null && (
            <p className="text-sm font-medium">{session.distance_km.toFixed(1)} km</p>
          )}
          {session.max_speed_kph != null && (
            <p className="text-xs text-gray-500">{session.max_speed_kph.toFixed(0)} km/h max</p>
          )}
        </div>
      </div>
    </div>
  )
}
