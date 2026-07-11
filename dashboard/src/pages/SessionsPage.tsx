import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getSessions } from '@/api'
import { ACTIVITY_LABELS, TEAM_COLORS, type TeamColor } from '@/types'

export function SessionsPage() {
  const { data: sessions, isLoading } = useQuery({
    queryKey: ['sessions'],
    queryFn: getSessions,
  })

  if (isLoading) {
    return <div className="p-8 text-sm text-gray-400">Loading sessions…</div>
  }

  if (!sessions || sessions.length === 0) {
    return (
      <div className="p-8 text-sm text-gray-400">
        No sessions yet — start one from the Live Map.
      </div>
    )
  }

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-3 overflow-y-auto h-full">
      <h2 className="text-lg font-semibold">Sessions</h2>
      {sessions.map((s) => {
        const running = s.startedAt && !s.endedAt
        return (
          <Link
            key={s.id}
            to={`/sessions/${s.id}`}
            className="block bg-surface-raised border border-surface-border rounded-xl px-4 py-3 hover:border-accent/50 transition-colors"
          >
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">{s.name}</span>
                  {running && (
                    <span className="text-[10px] uppercase tracking-wide bg-accent-green/20 text-accent-green px-1.5 py-0.5 rounded-full">
                      Live
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-400 mt-0.5">
                  {ACTIVITY_LABELS[s.activityType] ?? s.activityType}
                  {s.startedAt && <> · {new Date(s.startedAt).toLocaleString()}</>}
                  {s.startedAt && s.endedAt && <> · {duration(s.startedAt, s.endedAt)}</>}
                </p>
              </div>
              <div className="flex items-center gap-1">
                {s.teams.map((t) => (
                  <span
                    key={t.id}
                    className="w-3 h-3 rounded-full"
                    style={{ background: TEAM_COLORS[t.color as TeamColor] ?? '#888' }}
                    title={t.name}
                  />
                ))}
              </div>
            </div>
          </Link>
        )
      })}
    </div>
  )
}

function duration(start: string, end: string): string {
  const mins = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 60_000)
  if (mins < 60) return `${mins} min`
  return `${Math.floor(mins / 60)} h ${mins % 60} min`
}
