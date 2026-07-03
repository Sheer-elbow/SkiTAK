// TAK team colours — matches the CoT __group colour values
export const TEAM_COLORS = {
  Cyan:    '#06b6d4',
  Blue:    '#3b82f6',
  Green:   '#22c55e',
  Yellow:  '#eab308',
  Orange:  '#f97316',
  Red:     '#ef4444',
  Maroon:  '#9f1239',
  Purple:  '#a855f7',
  White:   '#e5e7eb',
} as const

export type TeamColor = keyof typeof TEAM_COLORS

export interface Position {
  lat: number
  lon: number
  altitudeM?: number
  accuracyM?: number
}

export interface Client {
  uid: string
  callsign: string
  teamId: string | null
  teamColor: TeamColor
  position: Position | null
  speedMs: number | null
  courseDeg: number | null
  batteryPct: number | null
  heartRateBpm: number | null
  lastSeen: Date
  isOnline: boolean        // false if stale > 5 min
}

export interface TeamMember {
  tak_uid: string
  callsign: string
}

export interface Team {
  id: string
  sessionId: string
  name: string
  color: TeamColor
  members: TeamMember[]
}

export interface EmergencyAlert {
  uid: string
  senderUid: string
  callsign: string | null
  alertType: string
  location: Position | null
  startedAt: string
  cancelled: boolean
}

export interface Session {
  id: string
  name: string
  activityType: ActivityType
  guideUid: string
  createdAt: string
  startedAt: string | null
  endedAt: string | null
  teams: Team[]
}

export type ActivityType =
  | 'skiing'
  | 'trail_run'
  | 'equestrian'
  | 'hiking'
  | 'alpine'
  | 'mountain_bike'
  | 'general'

export const ACTIVITY_LABELS: Record<ActivityType, string> = {
  skiing:        'Skiing',
  trail_run:     'Trail Running',
  equestrian:    'Equestrian',
  hiking:        'Hiking',
  alpine:        'Alpine / Backcountry',
  mountain_bike: 'Mountain Biking',
  general:       'General',
}

export interface ChatMessage {
  id: string
  fromUid: string
  fromCallsign: string
  toUid: string | null       // null = broadcast
  body: string
  location: Position | null  // geo-referenced messages
  sentAt: Date
}

export interface POI {
  id: string
  name: string
  type: 'waypoint' | 'hazard' | 'meetpoint' | 'emergency'
  location: Position
  description?: string
  createdByCallsign: string
}
