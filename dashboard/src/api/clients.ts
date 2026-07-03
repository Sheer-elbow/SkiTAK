import { request } from './http'

const BASE = '/api/skitak/clients'

function req<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(`${BASE}${path}`, init)
}

export interface ClientRecord {
  id: string
  display_name: string
  callsign: string
  email: string | null
  phone: string | null
  notes: string | null
  created_at: string
  last_seen_at: string | null
  enrolled_at: string | null
  cert_expires_at: string | null
  has_enrolled: boolean
  total_sessions: number
  total_distance_km: number
  sessions?: SessionSummary[]
}

export interface SessionSummary {
  id: string
  name: string
  activity_type: string
  started_at: string | null
  ended_at: string | null
  team_name: string
  team_color: string
  distance_km: number | null
  max_speed_kph: number | null
}

export interface EnrollmentResult {
  token: string
  join_url: string
  callsign: string
  expires_at: string
}

export interface AssignResult {
  assigned: Array<{
    client_id: string
    display_name: string
    callsign: string
    join_url: string
  }>
}

export const clientsApi = {
  list: () =>
    req<{ clients: ClientRecord[] }>('').then((r) => r.clients),

  get: (id: string) =>
    req<ClientRecord>(`/${id}`),

  create: (body: {
    display_name: string
    callsign?: string
    email?: string
    phone?: string
    notes?: string
  }) => req<ClientRecord>('', { method: 'POST', body: JSON.stringify(body) }),

  update: (id: string, body: Partial<ClientRecord>) =>
    req(`/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),

  delete: (id: string) =>
    req(`/${id}`, { method: 'DELETE' }),

  enroll: (
    clientId: string,
    opts: { session_id?: string; team_id?: string; team_name?: string; team_color?: string },
  ) =>
    req<EnrollmentResult>(`/${clientId}/enroll`, {
      method: 'POST',
      body: JSON.stringify(opts),
    }),

  assign: (body: {
    client_ids: string[]
    session_id: string
    team_id: string
    team_name: string
    team_color: string
  }) =>
    req<AssignResult>('/assign', { method: 'POST', body: JSON.stringify(body) }),
}
