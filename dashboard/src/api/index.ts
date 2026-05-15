const BASE = '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

// ── Auth ──────────────────────────────────────────────────────────────────

export function login(username: string, password: string) {
  return request<{ uid: string; token: string }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

// ── Sessions ──────────────────────────────────────────────────────────────

export function getSessions() {
  return request<{ sessions: import('@/types').Session[] }>('/skitak/sessions')
}

export function createSession(body: {
  name: string
  activity_type: string
  guide_uid: string
}) {
  return request<{ session_id: string }>('/skitak/sessions', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function startSession(sessionId: string) {
  return request(`/skitak/sessions/${sessionId}/start`, { method: 'POST' })
}

export function endSession(sessionId: string) {
  return request(`/skitak/sessions/${sessionId}/end`, { method: 'POST' })
}

export function getSessionSummary(sessionId: string) {
  return request<import('@/types').Session>(`/skitak/sessions/${sessionId}/summary`)
}

// ── Teams ─────────────────────────────────────────────────────────────────

export function createTeam(sessionId: string, name: string, color: string) {
  return request<{ team_id: string }>(`/skitak/sessions/${sessionId}/teams`, {
    method: 'POST',
    body: JSON.stringify({ name, color }),
  })
}

export function getInviteLink(sessionId: string, teamId: string) {
  return request<{ invite_url: string; qr_url: string }>(
    `/skitak/sessions/${sessionId}/teams/${teamId}/invite`,
  )
}

// ── Tracks ────────────────────────────────────────────────────────────────

export function downloadGpx(sessionId: string, takUid: string, callsign: string) {
  window.location.href = `/api/skitak/sessions/${sessionId}/tracks/${takUid}/gpx?callsign=${encodeURIComponent(callsign)}`
}

// ── Connected clients (OTS API) ───────────────────────────────────────────

export function getConnectedClients() {
  return request<{ Clients: Array<{ uid: string; callsign: string; lastEventTime: string }> }>(
    '/Marti/api/clientEndPoints',
  )
}
