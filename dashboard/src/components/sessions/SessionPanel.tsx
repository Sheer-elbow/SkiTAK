import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { QRCodeSVG } from 'qrcode.react'
import {
  createSession,
  createTeam,
  endSession,
  getInviteLink,
  getRunningSession,
  startSession,
} from '@/api'
import { useStore } from '@/store'
import { ACTIVITY_LABELS, TEAM_COLORS, type Session, type Team, type TeamColor } from '@/types'
import clsx from 'clsx'

export function SessionPanel() {
  const activeSession = useStore((s) => s.activeSession)
  const setActiveSession = useStore((s) => s.setActiveSession)
  const currentUser = useStore((s) => s.currentUser)

  // Adopt the running session on load (page refresh, second device) and keep
  // its team membership fresh — members appear as clients enroll and move.
  const { data: runningSession } = useQuery({
    queryKey: ['running-session'],
    queryFn: getRunningSession,
    refetchInterval: 15_000,
  })
  useEffect(() => {
    if (runningSession !== undefined) setActiveSession(runningSession)
  }, [runningSession])

  if (!activeSession) {
    return <CreateSessionForm onCreated={setActiveSession} guideUid={currentUser ?? 'guide'} />
  }

  return <ActiveSessionView session={activeSession} onEnd={() => setActiveSession(null)} />
}

function CreateSessionForm({
  onCreated,
  guideUid,
}: {
  onCreated: (s: Session) => void
  guideUid: string
}) {
  const [name, setName] = useState('')
  const [activity, setActivity] = useState<string>('general')
  const [loading, setLoading] = useState(false)
  const queryClient = useQueryClient()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) return
    setLoading(true)
    try {
      const { session_id } = await createSession({
        name: name.trim(),
        activity_type: activity,
        guide_uid: guideUid,
      })
      await startSession(session_id)
      onCreated({
        id: session_id,
        name: name.trim(),
        activityType: activity as Session['activityType'],
        guideUid,
        createdAt: new Date().toISOString(),
        startedAt: new Date().toISOString(),
        endedAt: null,
        teams: [],
      })
      queryClient.invalidateQueries({ queryKey: ['running-session'] })
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="px-4 py-4 space-y-4">
      <h3 className="font-semibold text-sm text-gray-300">New Session</h3>

      <div>
        <label className="block text-xs text-gray-400 mb-1">Session name</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Morning trail run"
          className="w-full bg-surface-raised border border-surface-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
        />
      </div>

      <div>
        <label className="block text-xs text-gray-400 mb-1">Activity</label>
        <select
          value={activity}
          onChange={(e) => setActivity(e.target.value)}
          className="w-full bg-surface-raised border border-surface-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
        >
          {Object.entries(ACTIVITY_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </div>

      <button
        type="submit"
        disabled={loading || !name.trim()}
        className="w-full bg-accent hover:bg-blue-500 disabled:opacity-40 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
      >
        {loading ? 'Creating…' : 'Start Session'}
      </button>
    </form>
  )
}

function ActiveSessionView({ session, onEnd }: { session: Session; onEnd: () => void }) {
  const [newTeamName, setNewTeamName] = useState('')
  const [newTeamColor, setNewTeamColor] = useState<TeamColor>('Cyan')
  const [localTeams, setLocalTeams] = useState<Team[]>([])
  const [invite, setInvite] = useState<{ url: string; teamName: string } | null>(null)
  const [ending, setEnding] = useState(false)
  const queryClient = useQueryClient()

  // Server-known teams (with live membership) + any just added locally
  const teams: Team[] = [
    ...session.teams,
    ...localTeams.filter((lt) => !session.teams.some((t) => t.id === lt.id)),
  ]

  async function handleAddTeam(e: React.FormEvent) {
    e.preventDefault()
    if (!newTeamName.trim()) return
    const { team_id } = await createTeam(session.id, newTeamName.trim(), newTeamColor)
    setLocalTeams([
      ...localTeams,
      {
        id: team_id,
        sessionId: session.id,
        name: newTeamName.trim(),
        color: newTeamColor,
        members: [],
      },
    ])
    setNewTeamName('')
    queryClient.invalidateQueries({ queryKey: ['running-session'] })
  }

  async function handleInvite(team: Team) {
    const { invite_url } = await getInviteLink(session.id, team.id)
    setInvite({ url: invite_url, teamName: team.name })
    await navigator.clipboard.writeText(invite_url).catch(() => {})
  }

  async function handleEnd() {
    setEnding(true)
    try {
      const { revoked_devices } = await endSession(session.id)
      if (revoked_devices.length > 0) {
        // Devices are deactivated on session end so ex-clients lose access
        console.info(`Revoked device access: ${revoked_devices.join(', ')}`)
      }
      queryClient.invalidateQueries({ queryKey: ['running-session'] })
      onEnd()
    } finally {
      setEnding(false)
    }
  }

  return (
    <div className="px-4 py-4 space-y-4 overflow-y-auto h-full">
      {/* Session header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-semibold text-sm">{session.name}</h3>
          <p className="text-xs text-gray-400 mt-0.5">
            {ACTIVITY_LABELS[session.activityType] ?? session.activityType}
          </p>
        </div>
        <button
          onClick={handleEnd}
          disabled={ending}
          className="text-xs text-accent-red hover:text-red-300 font-medium disabled:opacity-50"
          title="Ends the session and revokes client device access"
        >
          {ending ? 'Ending…' : 'End'}
        </button>
      </div>

      {/* Teams */}
      <div className="space-y-2">
        <h4 className="text-xs text-gray-400 uppercase tracking-wider">Teams</h4>
        {teams.length === 0 && (
          <p className="text-xs text-gray-500">No teams yet — add one below</p>
        )}
        {teams.map((team) => (
          <div
            key={team.id}
            className="flex items-center justify-between bg-surface-raised rounded-lg px-3 py-2"
          >
            <div className="flex items-center gap-2">
              <div
                className="w-3 h-3 rounded-full flex-shrink-0"
                style={{ background: TEAM_COLORS[team.color] ?? '#888' }}
              />
              <span className="text-sm">{team.name}</span>
              <span className="text-xs text-gray-500">({team.members.length})</span>
            </div>
            <button
              onClick={() => handleInvite(team)}
              className="text-xs text-accent hover:text-blue-300"
              title="Create invite link"
            >
              Invite
            </button>
          </div>
        ))}
      </div>

      {/* Add team */}
      <form onSubmit={handleAddTeam} className="space-y-2">
        <input
          value={newTeamName}
          onChange={(e) => setNewTeamName(e.target.value)}
          placeholder="Team name"
          className="w-full bg-surface-raised border border-surface-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <div className="flex gap-2">
          <div className="flex gap-1 flex-wrap flex-1">
            {(Object.keys(TEAM_COLORS) as TeamColor[]).map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setNewTeamColor(c)}
                className={clsx(
                  'w-6 h-6 rounded-full border-2 transition-transform hover:scale-110',
                  newTeamColor === c ? 'border-white scale-110' : 'border-transparent',
                )}
                style={{ background: TEAM_COLORS[c] }}
                title={c}
              />
            ))}
          </div>
          <button
            type="submit"
            disabled={!newTeamName.trim()}
            className="text-xs bg-surface-raised hover:bg-surface-border disabled:opacity-40 border border-surface-border rounded-lg px-3 py-1.5"
          >
            Add
          </button>
        </div>
      </form>

      {/* Invite link + QR — scan it from a phone standing next to you */}
      {invite && (
        <div className="bg-accent/10 border border-accent/30 rounded-lg px-3 py-3 text-xs space-y-2">
          <p className="text-accent font-medium">
            Invite for {invite.teamName} — link copied
          </p>
          <div className="bg-white rounded-lg p-2 w-fit mx-auto">
            <QRCodeSVG value={invite.url} size={148} />
          </div>
          <p className="text-gray-400 break-all">{invite.url}</p>
          <p className="text-gray-500">
            Single use · expires in 24 h · opens the join page
          </p>
          <button onClick={() => setInvite(null)} className="text-gray-500">
            Dismiss
          </button>
        </div>
      )}
    </div>
  )
}
