import type { Session, Team } from '@/types'
import { request, setCsrfToken } from './http'

// ── Auth (Flask-Security session endpoints) ───────────────────────────────

interface LoginResponse {
  response: {
    csrf_token?: string
    user?: { username?: string }
    errors?: string[]
  }
}

export async function login(username: string, password: string): Promise<string> {
  const data = await request<LoginResponse>('/api/login?include_auth_token', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
  if (data.response?.errors?.length) throw new Error(data.response.errors[0])
  setCsrfToken(data.response?.csrf_token ?? null)
  return username
}

export async function logout(): Promise<void> {
  try {
    await request('/api/logout', { method: 'POST', body: '{}' })
  } finally {
    setCsrfToken(null)
  }
}

/** Restore an existing session cookie on page load. Returns the username or null. */
export async function checkAuth(): Promise<string | null> {
  try {
    const me = await request<{ username?: string; response?: { user?: { username?: string } } }>(
      '/api/me',
    )
    return me.username ?? me.response?.user?.username ?? 'guide'
  } catch {
    return null
  }
}

// ── Sessions ──────────────────────────────────────────────────────────────

interface ApiTeam {
  id: string
  session_id: string
  name: string
  color: string
  members?: Array<{ tak_uid: string; callsign: string }>
}

interface ApiSession {
  id: string
  name: string
  activity_type: string
  guide_uid: string
  created_at: string | null
  started_at: string | null
  ended_at: string | null
  teams: ApiTeam[]
}

function toTeam(t: ApiTeam): Team {
  return {
    id: t.id,
    sessionId: t.session_id,
    name: t.name,
    color: (t.color as Team['color']) ?? 'Cyan',
    members: t.members ?? [],
  }
}

function toSession(s: ApiSession): Session {
  return {
    id: s.id,
    name: s.name,
    activityType: s.activity_type as Session['activityType'],
    guideUid: s.guide_uid,
    createdAt: s.created_at ?? '',
    startedAt: s.started_at,
    endedAt: s.ended_at,
    teams: (s.teams ?? []).map(toTeam),
  }
}

export async function getSessions(): Promise<Session[]> {
  const data = await request<{ sessions: ApiSession[] }>('/api/skitak/sessions')
  return data.sessions.map(toSession)
}

/** The most recent session that is started and not ended, if any. */
export async function getRunningSession(): Promise<Session | null> {
  const sessions = await getSessions()
  return sessions.find((s) => s.startedAt && !s.endedAt) ?? null
}

export function createSession(body: {
  name: string
  activity_type: string
  guide_uid: string
}) {
  return request<{ session_id: string }>('/api/skitak/sessions', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function startSession(sessionId: string) {
  return request(`/api/skitak/sessions/${sessionId}/start`, { method: 'POST', body: '{}' })
}

export function endSession(sessionId: string, revokeDevices = true) {
  return request<{ status: string; revoked_devices: string[] }>(
    `/api/skitak/sessions/${sessionId}/end`,
    { method: 'POST', body: JSON.stringify({ revoke_devices: revokeDevices }) },
  )
}

export function getSessionSummary(sessionId: string) {
  return request<{
    name: string
    activity_type: string
    started_at: string | null
    ended_at: string | null
    participant_count: number
    total_km: string | number
    elevation_range_m: number | null
    max_speed_kph: number | null
  }>(`/api/skitak/sessions/${sessionId}/summary`)
}

// ── Session history / replay ──────────────────────────────────────────────

export interface SessionParticipant {
  tak_uid: string
  callsign: string
  team_id: string | null
  point_count: number
  first_at: string
  last_at: string
  distance_km: string | number
  max_speed_kph: string | number | null
  max_altitude_m: string | number | null
  min_altitude_m: string | number | null
}

export interface SessionDetail {
  id: string
  name: string
  activity_type: string
  guide_uid: string
  created_at: string | null
  started_at: string | null
  ended_at: string | null
  teams: Array<{ id: string; name: string; color: string }>
  participants: SessionParticipant[]
}

export interface ReplayTrackPoint {
  recorded_at: string
  lat: number
  lon: number
  altitude_m: number | null
  speed_ms: number | null
  course_deg: number | null
  battery_pct: number | null
}

export function getSessionDetail(sessionId: string) {
  return request<SessionDetail>(`/api/skitak/sessions/${sessionId}`)
}

export function getSessionTracks(sessionId: string, every = 1) {
  return request<{ tracks: Record<string, ReplayTrackPoint[]> }>(
    `/api/skitak/sessions/${sessionId}/tracks?every=${every}`,
  ).then((r) => r.tracks)
}

// ── Planned route ─────────────────────────────────────────────────────────

export interface PlannedRoute {
  id: string
  name: string
  point_count: number
  uploaded_by: string | null
  uploaded_at: string
  points: Array<{ lat: number; lon: number }>
}

export function uploadRoute(sessionId: string, file: File) {
  const form = new FormData()
  form.append('gpx', file)
  return request<{ route_id: string; name: string; point_count: number; broadcast_teams: number }>(
    `/api/skitak/sessions/${sessionId}/route`,
    { method: 'POST', body: form },
  )
}

export function getSessionRoute(sessionId: string) {
  return request<{ route: PlannedRoute | null }>(
    `/api/skitak/sessions/${sessionId}/route`,
  ).then((r) => r.route)
}

export function deleteSessionRoute(sessionId: string) {
  return request(`/api/skitak/sessions/${sessionId}/route`, { method: 'DELETE' })
}

// ── Teams ─────────────────────────────────────────────────────────────────

export function createTeam(sessionId: string, name: string, color: string) {
  return request<{ team_id: string }>(`/api/skitak/sessions/${sessionId}/teams`, {
    method: 'POST',
    body: JSON.stringify({ name, color }),
  })
}

export function getInviteLink(sessionId: string, teamId: string) {
  return request<{ invite_url: string; expires_in_hours: number }>(
    `/api/skitak/sessions/${sessionId}/teams/${teamId}/invite`,
  )
}

// ── Tracks ────────────────────────────────────────────────────────────────

export function downloadGpx(sessionId: string, takUid: string, callsign: string) {
  window.location.href = `/api/skitak/sessions/${sessionId}/tracks/${encodeURIComponent(takUid)}/gpx?callsign=${encodeURIComponent(callsign)}`
}
