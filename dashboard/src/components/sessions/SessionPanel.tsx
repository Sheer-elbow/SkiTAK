import { useState } from 'react'
import { useStore } from '@/store'
import { ACTIVITY_LABELS, TEAM_COLORS, TeamColor } from '@/types'
import { createSession, createTeam, startSession, endSession, getInviteLink } from '@/api'
import clsx from 'clsx'

export function SessionPanel() {
  const activeSession = useStore((s) => s.activeSession)
  const setActiveSession = useStore((s) => s.setActiveSession)
  const currentUserUid = useStore((s) => s.currentUserUid)

  if (!activeSession) {
    return <CreateSessionForm onCreated={setActiveSession} guideUid={currentUserUid ?? ''} />
  }

  return <ActiveSessionView session={activeSession} onEnd={() => setActiveSession(null)} />
}

function CreateSessionForm({
  onCreated,
  guideUid,
}: {
  onCreated: (s: any) => void
  guideUid: string
}) {
  const [name, setName] = useState('')
  const [activity, setActivity] = useState<string>('general')
  const [loading, setLoading] = useState(false)

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
      onCreated({ id: session_id, name, activityType: activity, guideUid, teams: [] })
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

function ActiveSessionView({ session, onEnd }: { session: any; onEnd: () => void }) {
  const [newTeamName, setNewTeamName] = useState('')
  const [newTeamColor, setNewTeamColor] = useState<TeamColor>('Cyan')
  const [teams, setTeams] = useState(session.teams ?? [])
  const [inviteUrl, setInviteUrl] = useState<string | null>(null)

  async function handleAddTeam(e: React.FormEvent) {
    e.preventDefault()
    if (!newTeamName.trim()) return
    const { team_id } = await createTeam(session.id, newTeamName.trim(), newTeamColor)
    setTeams([...teams, { id: team_id, name: newTeamName, color: newTeamColor, memberUids: [] }])
    setNewTeamName('')
  }

  async function handleInvite(teamId: string) {
    const { invite_url } = await getInviteLink(session.id, teamId)
    setInviteUrl(invite_url)
    await navigator.clipboard.writeText(invite_url).catch(() => {})
  }

  async function handleEnd() {
    await endSession(session.id)
    onEnd()
  }

  return (
    <div className="px-4 py-4 space-y-4">
      {/* Session header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-semibold text-sm">{session.name}</h3>
          <p className="text-xs text-gray-400 mt-0.5">
            {ACTIVITY_LABELS[session.activityType as keyof typeof ACTIVITY_LABELS] ?? session.activityType}
          </p>
        </div>
        <button
          onClick={handleEnd}
          className="text-xs text-accent-red hover:text-red-300 font-medium"
        >
          End
        </button>
      </div>

      {/* Teams */}
      <div className="space-y-2">
        <h4 className="text-xs text-gray-400 uppercase tracking-wider">Teams</h4>
        {teams.length === 0 && (
          <p className="text-xs text-gray-500">No teams yet — add one below</p>
        )}
        {teams.map((team: any) => (
          <div
            key={team.id}
            className="flex items-center justify-between bg-surface-raised rounded-lg px-3 py-2"
          >
            <div className="flex items-center gap-2">
              <div
                className="w-3 h-3 rounded-full flex-shrink-0"
                style={{ background: TEAM_COLORS[team.color as TeamColor] ?? '#888' }}
              />
              <span className="text-sm">{team.name}</span>
              <span className="text-xs text-gray-500">({team.memberUids?.length ?? 0})</span>
            </div>
            <button
              onClick={() => handleInvite(team.id)}
              className="text-xs text-accent hover:text-blue-300"
              title="Copy invite link"
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

      {/* Invite URL toast */}
      {inviteUrl && (
        <div className="bg-accent/10 border border-accent/30 rounded-lg px-3 py-2 text-xs">
          <p className="text-accent font-medium mb-1">Link copied to clipboard</p>
          <p className="text-gray-400 break-all">{inviteUrl}</p>
          <button onClick={() => setInviteUrl(null)} className="text-gray-500 mt-1">Dismiss</button>
        </div>
      )}
    </div>
  )
}
