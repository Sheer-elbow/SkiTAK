import { useEffect } from 'react'
import { io, type Socket } from 'socket.io-client'
import { useStore } from '@/store'
import type { Client, EmergencyAlert, TeamColor } from '@/types'

// OpenTAKServer pushes live updates over Socket.IO (namespace /socket.io,
// same-origin session cookie auth):
//   point — EUD position updates (from the CoT parser)
//   alert — emergency beacons
//   eud   — device connect/status changes

interface PointEvent {
  uid: string
  device_uid: string
  latitude: number
  longitude: number
  ce: number | null
  hae: number | null
  course: number | null
  speed: number | null
  battery: number | null
  timestamp: string
  callsign: string | null
  type: string | null
}

interface AlertEvent {
  uid: string
  sender_uid: string
  start_time: string
  cancel_time: string | null
  alert_type: string
  callsign: string | null
  point: { latitude: number; longitude: number } | null
}

export function useOtsSocket() {
  useEffect(() => {
    const socket: Socket = io('/socket.io', {
      path: '/socket.io',
      transports: ['websocket', 'polling'],
      withCredentials: true,
    })

    socket.on('point', handlePoint)
    socket.on('alert', handleAlert)

    const staleInterval = setInterval(
      () => useStore.getState().markStaleClients(),
      30_000,
    )

    return () => {
      clearInterval(staleInterval)
      socket.close()
    }
  }, [])
}

function handlePoint(p: PointEvent) {
  if (p.latitude == null || p.longitude == null) return
  const uid = p.device_uid ?? p.uid
  if (!uid) return

  // Read fresh state — this handler outlives renders (no stale closures)
  const { activeSession, upsertClient } = useStore.getState()
  const team = activeSession?.teams.find((t) =>
    t.members.some((m) => m.tak_uid === uid || (p.callsign && m.callsign === p.callsign)),
  )

  const client: Client = {
    uid,
    callsign: p.callsign ?? uid,
    teamId: team?.id ?? null,
    teamColor: (team?.color ?? 'Cyan') as TeamColor,
    position: {
      lat: p.latitude,
      lon: p.longitude,
      altitudeM: p.hae ?? undefined,
      accuracyM: p.ce ?? undefined,
    },
    speedMs: p.speed,
    courseDeg: p.course,
    batteryPct: p.battery,
    heartRateBpm: null,
    lastSeen: p.timestamp ? new Date(p.timestamp) : new Date(),
    isOnline: true,
  }
  upsertClient(client)
}

function handleAlert(a: AlertEvent) {
  const alert: EmergencyAlert = {
    uid: a.uid,
    senderUid: a.sender_uid,
    callsign: a.callsign,
    alertType: a.alert_type,
    location: a.point
      ? { lat: a.point.latitude, lon: a.point.longitude }
      : null,
    startedAt: a.start_time,
    cancelled: a.cancel_time != null,
  }
  const { upsertAlert, dismissAlert, addPoi } = useStore.getState()
  if (alert.cancelled) {
    dismissAlert(alert.uid)
    return
  }
  upsertAlert(alert)
  if (alert.location) {
    addPoi({
      id: alert.uid,
      name: `EMERGENCY: ${alert.callsign ?? alert.senderUid}`,
      type: 'emergency',
      location: alert.location,
      createdByCallsign: alert.callsign ?? alert.senderUid,
    })
  }
}
