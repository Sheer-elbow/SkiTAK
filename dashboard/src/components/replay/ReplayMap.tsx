import { useEffect, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { ReplayTrackPoint } from '@/api'

export interface ReplayTrack {
  uid: string
  callsign: string
  color: string
  points: Array<ReplayTrackPoint & { t: number }>  // t = epoch ms
}

// OpenTopo for replay — always available (no API key), and replay is
// usually reviewed after the fact on good connectivity.
const REPLAY_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    topo: {
      type: 'raster',
      tiles: [
        'https://a.tile.opentopomap.org/{z}/{x}/{y}.png',
        'https://b.tile.opentopomap.org/{z}/{x}/{y}.png',
        'https://c.tile.opentopomap.org/{z}/{x}/{y}.png',
      ],
      tileSize: 256,
      attribution: '© OpenTopoMap contributors',
      maxzoom: 17,
    },
  },
  layers: [{ id: 'topo', type: 'raster', source: 'topo' }],
}

export function ReplayMap({
  tracks,
  currentTime,
}: {
  tracks: ReplayTrack[]
  currentTime: number
}) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const markers = useRef<Record<string, maplibregl.Marker>>({})
  const ready = useRef(false)

  // ── Map + track polylines ────────────────────────────────────────────────
  useEffect(() => {
    if (!container.current || map.current) return
    map.current = new maplibregl.Map({
      container: container.current,
      style: REPLAY_STYLE,
      center: [0, 51.5],
      zoom: 12,
    })
    map.current.addControl(new maplibregl.NavigationControl(), 'top-right')
    map.current.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right')

    map.current.on('load', () => {
      ready.current = true
      drawTracks()
      fitToTracks()
    })

    return () => {
      map.current?.remove()
      map.current = null
      ready.current = false
      markers.current = {}
    }
  }, [])

  useEffect(() => {
    if (ready.current) {
      drawTracks()
      fitToTracks()
    }
  }, [tracks])

  function drawTracks() {
    const m = map.current
    if (!m) return
    tracks.forEach((track) => {
      const sourceId = `track-${track.uid}`
      const data: GeoJSON.Feature = {
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'LineString',
          coordinates: track.points.map((p) => [p.lon, p.lat]),
        },
      }
      const existing = m.getSource(sourceId) as maplibregl.GeoJSONSource | undefined
      if (existing) {
        existing.setData(data)
      } else {
        m.addSource(sourceId, { type: 'geojson', data })
        m.addLayer({
          id: sourceId,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': track.color,
            'line-width': 3,
            'line-opacity': 0.65,
          },
          layout: { 'line-cap': 'round', 'line-join': 'round' },
        })
      }
    })
  }

  function fitToTracks() {
    const m = map.current
    const all = tracks.flatMap((t) => t.points)
    if (!m || all.length === 0) return
    const lons = all.map((p) => p.lon)
    const lats = all.map((p) => p.lat)
    m.fitBounds(
      [
        [Math.min(...lons), Math.min(...lats)],
        [Math.max(...lons), Math.max(...lats)],
      ],
      { padding: 60, maxZoom: 16, duration: 0 },
    )
  }

  // ── Moving markers ───────────────────────────────────────────────────────
  useEffect(() => {
    const m = map.current
    if (!m) return
    tracks.forEach((track) => {
      const pos = positionAt(track.points, currentTime)
      if (!pos) {
        markers.current[track.uid]?.remove()
        delete markers.current[track.uid]
        return
      }
      if (markers.current[track.uid]) {
        markers.current[track.uid].setLngLat([pos.lon, pos.lat])
      } else {
        const el = document.createElement('div')
        el.innerHTML = `
          <div style="background:${track.color};border:2px solid white"
               class="w-7 h-7 rounded-full flex items-center justify-center shadow-lg text-white text-[10px] font-bold uppercase">
            ${track.callsign.slice(0, 2)}
          </div>`
        markers.current[track.uid] = new maplibregl.Marker({ element: el })
          .setLngLat([pos.lon, pos.lat])
          .addTo(m)
      }
    })
  }, [currentTime, tracks])

  return <div ref={container} className="w-full h-full" />
}

/** Latest point at or before `time` (binary search); null before track start. */
export function positionAt(
  points: Array<ReplayTrackPoint & { t: number }>,
  time: number,
): (ReplayTrackPoint & { t: number }) | null {
  if (points.length === 0 || time < points[0].t) return null
  let lo = 0
  let hi = points.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (points[mid].t <= time) lo = mid
    else hi = mid - 1
  }
  return points[lo]
}
