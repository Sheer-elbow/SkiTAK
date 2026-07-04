import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  downloadGpx,
  getSessionDetail,
  getSessionTracks,
  type SessionParticipant,
} from '@/api'
import { ReplayMap, type ReplayTrack } from '@/components/replay/ReplayMap'
import { ACTIVITY_LABELS, TEAM_COLORS, type ActivityType, type TeamColor } from '@/types'
import clsx from 'clsx'

const SPEEDS = [10, 30, 120] as const

export function SessionReplayPage() {
  const { sessionId = '' } = useParams()

  const { data: detail } = useQuery({
    queryKey: ['session-detail', sessionId],
    queryFn: () => getSessionDetail(sessionId),
    enabled: !!sessionId,
  })
  const { data: rawTracks } = useQuery({
    queryKey: ['session-tracks', sessionId],
    queryFn: () => getSessionTracks(sessionId),
    enabled: !!sessionId,
  })

  // Colour per participant from their team; parse timestamps once
  const tracks: ReplayTrack[] = useMemo(() => {
    if (!rawTracks || !detail) return []
    const colorByTeam = Object.fromEntries(
      detail.teams.map((t) => [t.id, TEAM_COLORS[t.color as TeamColor] ?? '#06b6d4']),
    )
    return detail.participants
      .filter((p) => rawTracks[p.tak_uid]?.length)
      .map((p) => ({
        uid: p.tak_uid,
        callsign: p.callsign,
        color: (p.team_id && colorByTeam[p.team_id]) || '#06b6d4',
        points: rawTracks[p.tak_uid].map((pt) => ({
          ...pt,
          t: new Date(pt.recorded_at).getTime(),
        })),
      }))
  }, [rawTracks, detail])

  const [t0, t1] = useMemo(() => {
    const times = tracks.flatMap((tr) => [tr.points[0]?.t, tr.points[tr.points.length - 1]?.t])
      .filter((t): t is number => t != null)
    return times.length ? [Math.min(...times), Math.max(...times)] : [0, 0]
  }, [tracks])

  const [currentTime, setCurrentTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(30)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => setCurrentTime(t0), [t0])

  useEffect(() => {
    if (!playing) return
    timer.current = setInterval(() => {
      setCurrentTime((t) => {
        const next = t + speed * 100 // 100ms tick × replay speed
        if (next >= t1) {
          setPlaying(false)
          return t1
        }
        return next
      })
    }, 100)
    return () => {
      if (timer.current) clearInterval(timer.current)
    }
  }, [playing, speed, t1])

  if (!detail) {
    return <div className="p-8 text-sm text-gray-400">Loading session…</div>
  }

  const hasTracks = tracks.length > 0

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-surface-border flex-shrink-0">
        <Link to="/sessions" className="text-xs text-gray-400 hover:text-white">
          ← Sessions
        </Link>
        <h2 className="font-semibold text-sm">{detail.name}</h2>
        <span className="text-xs text-gray-400">
          {ACTIVITY_LABELS[detail.activity_type as ActivityType] ?? detail.activity_type}
        </span>
        {!detail.ended_at && detail.started_at && (
          <span className="text-[10px] uppercase tracking-wide bg-accent-green/20 text-accent-green px-1.5 py-0.5 rounded-full">
            Live
          </span>
        )}
      </div>

      <div className="flex flex-1 min-h-0">
        {/* Participants sidebar */}
        <div className="w-80 flex-shrink-0 border-r border-surface-border overflow-y-auto">
          {detail.participants.length === 0 && (
            <p className="p-4 text-xs text-gray-500">
              No track data recorded for this session.
            </p>
          )}
          {detail.participants.map((p) => (
            <ParticipantCard
              key={p.tak_uid}
              participant={p}
              color={tracks.find((t) => t.uid === p.tak_uid)?.color ?? '#6b7280'}
              sessionId={sessionId}
            />
          ))}
        </div>

        {/* Map + scrubber */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 min-h-0">
            {hasTracks ? (
              <ReplayMap tracks={tracks} currentTime={currentTime} />
            ) : (
              <div className="h-full flex items-center justify-center text-sm text-gray-500">
                Nothing to replay yet
              </div>
            )}
          </div>

          {hasTracks && (
            <div className="flex items-center gap-3 px-4 py-3 border-t border-surface-border flex-shrink-0">
              <button
                onClick={() => setPlaying(!playing)}
                className="w-9 h-9 rounded-full bg-accent hover:bg-blue-500 flex items-center justify-center text-sm"
                title={playing ? 'Pause' : 'Play'}
              >
                {playing ? '❚❚' : '▶'}
              </button>

              <span className="text-xs font-mono text-gray-300 w-20">
                {new Date(currentTime).toLocaleTimeString()}
              </span>

              <input
                type="range"
                min={t0}
                max={t1}
                value={currentTime}
                onChange={(e) => setCurrentTime(Number(e.target.value))}
                className="flex-1 accent-blue-500"
                aria-label="Replay position"
              />

              <span className="text-xs font-mono text-gray-500 w-20 text-right">
                {new Date(t1).toLocaleTimeString()}
              </span>

              <div className="flex gap-1">
                {SPEEDS.map((s) => (
                  <button
                    key={s}
                    onClick={() => setSpeed(s)}
                    className={clsx(
                      'text-xs px-2 py-1 rounded-md border',
                      speed === s
                        ? 'bg-accent/20 border-accent text-accent'
                        : 'border-surface-border text-gray-400 hover:text-white',
                    )}
                  >
                    {s}×
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ParticipantCard({
  participant: p,
  color,
  sessionId,
}: {
  participant: SessionParticipant
  color: string
  sessionId: string
}) {
  return (
    <div className="px-4 py-3 border-b border-surface-border">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-full" style={{ background: color }} />
          <span className="text-sm font-medium">{p.callsign}</span>
        </div>
        <button
          onClick={() => downloadGpx(sessionId, p.tak_uid, p.callsign)}
          className="text-xs text-accent hover:text-blue-300"
          title="Download GPX"
        >
          GPX ↓
        </button>
      </div>
      <dl className="grid grid-cols-3 gap-x-2 gap-y-1 mt-2 text-xs">
        <Stat label="Distance" value={`${p.distance_km} km`} />
        <Stat label="Max speed" value={p.max_speed_kph != null ? `${p.max_speed_kph} km/h` : '—'} />
        <Stat label="Points" value={String(p.point_count)} />
        <Stat
          label="Elevation"
          value={
            p.max_altitude_m != null && p.min_altitude_m != null
              ? `${p.min_altitude_m}–${p.max_altitude_m} m`
              : '—'
          }
        />
        <Stat
          label="Duration"
          value={durationLabel(p.first_at, p.last_at)}
        />
      </dl>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-gray-500">{label}</dt>
      <dd className="text-gray-200 font-mono">{value}</dd>
    </div>
  )
}

function durationLabel(first: string, last: string): string {
  const mins = Math.round((new Date(last).getTime() - new Date(first).getTime()) / 60_000)
  if (mins < 1) return '<1 min'
  if (mins < 60) return `${mins} min`
  return `${Math.floor(mins / 60)} h ${mins % 60} m`
}
