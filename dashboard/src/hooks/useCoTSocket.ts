import { useEffect, useRef } from 'react'
import { useStore } from '@/store'
import type { Client, ChatMessage, POI, TeamColor } from '@/types'

// OTS emits CoT events as JSON over WebSocket at /ws/
// This hook parses position updates, chat messages, and emergency alerts.

export function useCoTSocket() {
  const ws = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const { upsertClient, addMessage, addPoi, activeSession } = useStore()

  useEffect(() => {
    connect()
    const staleInterval = setInterval(
      () => useStore.getState().markStaleClients(),
      30_000,
    )
    return () => {
      clearInterval(staleInterval)
      reconnectTimer.current && clearTimeout(reconnectTimer.current)
      ws.current?.close()
    }
  }, [])

  function connect() {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    ws.current = new WebSocket(`${proto}://${window.location.host}/ws/`)

    ws.current.onmessage = (event) => {
      try {
        const cot = JSON.parse(event.data as string)
        handleCoT(cot)
      } catch {
        // Non-JSON frame — ignore
      }
    }

    ws.current.onclose = () => {
      // Exponential backoff reconnect: 2s, 4s, 8s … max 30s
      reconnectTimer.current = setTimeout(connect, Math.min(
        30_000,
        2_000 * 2 ** (reconnectAttempts.current++),
      ))
    }

    ws.current.onopen = () => {
      reconnectAttempts.current = 0
    }
  }

  const reconnectAttempts = useRef(0)

  function handleCoT(cot: CoTEvent) {
    const { type, uid, time } = cot

    // ── Position update (SA events) ───────────────────────────────────────
    if (type.startsWith('a-') && cot.point) {
      const team = activeSession?.teams.find((t) =>
        t.memberUids.includes(uid),
      )
      const client: Client = {
        uid,
        callsign: cot.detail?.contact?.callsign ?? uid,
        teamId: team?.id ?? null,
        teamColor: (team?.color ?? 'Cyan') as TeamColor,
        position: {
          lat: cot.point.lat,
          lon: cot.point.lon,
          altitudeM: cot.point.hae ?? undefined,
          accuracyM: cot.point.ce ?? undefined,
        },
        speedMs: cot.detail?.track?.speed ?? null,
        courseDeg: cot.detail?.track?.course ?? null,
        batteryPct: cot.detail?.status?.battery ?? null,
        heartRateBpm: cot.detail?.skitak?.heart_rate_bpm ?? null,
        lastSeen: new Date(time),
        isOnline: true,
      }
      upsertClient(client)
      return
    }

    // ── GeoChat ──────────────────────────────────────────────────────────
    if (type === 'b-t-f' && cot.detail?.remarks) {
      const msg: ChatMessage = {
        id: `${uid}-${time}`,
        fromUid: uid,
        fromCallsign: cot.detail?.contact?.callsign ?? uid,
        toUid: null,
        body: cot.detail.remarks,
        location: cot.point
          ? { lat: cot.point.lat, lon: cot.point.lon }
          : null,
        sentAt: new Date(time),
      }
      addMessage(msg)
      return
    }

    // ── Emergency beacon ─────────────────────────────────────────────────
    if (type === 'b-a-o-tbl') {
      const poi: POI = {
        id: uid,
        name: `EMERGENCY: ${cot.detail?.contact?.callsign ?? uid}`,
        type: 'emergency',
        location: { lat: cot.point?.lat ?? 0, lon: cot.point?.lon ?? 0 },
        description: cot.detail?.remarks,
        createdByCallsign: cot.detail?.contact?.callsign ?? uid,
      }
      addPoi(poi)
    }

    // ── Waypoint / map item ───────────────────────────────────────────────
    if (type === 'b-m-p-s-m' && cot.point) {
      const poi: POI = {
        id: uid,
        name: cot.detail?.contact?.callsign ?? 'Waypoint',
        type: 'waypoint',
        location: { lat: cot.point.lat, lon: cot.point.lon },
        description: cot.detail?.remarks,
        createdByCallsign: cot.detail?.contact?.callsign ?? '',
      }
      addPoi(poi)
    }
  }
}

// Minimal CoT JSON shape from OTS WebSocket feed
interface CoTEvent {
  type: string
  uid: string
  time: string
  point?: { lat: number; lon: number; hae?: number; ce?: number }
  detail?: {
    contact?: { callsign?: string }
    track?: { speed?: number; course?: number }
    status?: { battery?: number }
    remarks?: string
    skitak?: { heart_rate_bpm?: number }
  }
}
