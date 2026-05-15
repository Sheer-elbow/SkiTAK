import { useEffect, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useStore } from '@/store'
import { TEAM_COLORS } from '@/types'

// Outdoor-appropriate tile sources
const TILE_SOURCES = {
  topo: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
  osm: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  local: '/tiles/{z}/{x}/{y}.png',  // our mbtileserver when available
} as const

export function LiveMap() {
  const mapContainer = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const markers = useRef<Record<string, maplibregl.Marker>>({})

  const clients = useStore((s) => s.clients)
  const pois = useStore((s) => s.pois)
  const selectedUid = useStore((s) => s.selectedUid)
  const selectClient = useStore((s) => s.selectClient)

  // ── Initialise map ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!mapContainer.current || map.current) return

    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style: {
        version: 8,
        sources: {
          'topo-tiles': {
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
        layers: [
          {
            id: 'topo-layer',
            type: 'raster',
            source: 'topo-tiles',
          },
        ],
      },
      center: [0, 51.5],
      zoom: 10,
    })

    map.current.addControl(new maplibregl.NavigationControl(), 'top-right')
    map.current.addControl(
      new maplibregl.GeolocateControl({ trackUserLocation: false }),
      'top-right',
    )
    map.current.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right')

    return () => {
      map.current?.remove()
      map.current = null
    }
  }, [])

  // ── Update client markers ────────────────────────────────────────────────
  useEffect(() => {
    if (!map.current) return

    const activeUids = new Set(Object.keys(clients))

    // Remove markers for clients that have disappeared
    Object.keys(markers.current).forEach((uid) => {
      if (!activeUids.has(uid)) {
        markers.current[uid].remove()
        delete markers.current[uid]
      }
    })

    Object.values(clients).forEach((client) => {
      if (!client.position) return

      const { lat, lon } = client.position
      const color = TEAM_COLORS[client.teamColor]
      const isSelected = client.uid === selectedUid
      const isOffline = !client.isOnline

      if (markers.current[client.uid]) {
        // Update existing marker position
        markers.current[client.uid].setLngLat([lon, lat])
        updateMarkerElement(markers.current[client.uid], client.callsign, color, isSelected, isOffline)
      } else {
        // Create new marker
        const el = createMarkerElement(client.callsign, color, isSelected, isOffline)
        el.addEventListener('click', () => selectClient(client.uid))

        markers.current[client.uid] = new maplibregl.Marker({ element: el, anchor: 'bottom' })
          .setLngLat([lon, lat])
          .setPopup(
            new maplibregl.Popup({ offset: 25 }).setHTML(
              `<div class="text-sm font-medium">${client.callsign}</div>
               <div class="text-xs text-gray-400">${client.speedMs != null ? `${(client.speedMs * 3.6).toFixed(1)} km/h` : '—'}</div>
               ${client.batteryPct != null ? `<div class="text-xs">🔋 ${client.batteryPct}%</div>` : ''}`,
            ),
          )
          .addTo(map.current!)
      }
    })
  }, [clients, selectedUid])

  // ── POI markers ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!map.current) return
    pois.forEach((poi) => {
      const el = document.createElement('div')
      el.className = 'flex items-center justify-center w-8 h-8 rounded-full text-lg shadow-lg cursor-pointer'
      el.style.backgroundColor = poi.type === 'emergency' ? '#ef4444' : '#f59e0b'
      el.textContent = poi.type === 'emergency' ? '🆘' : '📍'
      el.title = poi.name

      new maplibregl.Marker({ element: el })
        .setLngLat([poi.location.lon, poi.location.lat])
        .setPopup(new maplibregl.Popup().setHTML(
          `<strong>${poi.name}</strong>${poi.description ? `<p>${poi.description}</p>` : ''}`,
        ))
        .addTo(map.current!)
    })
  }, [pois])

  // ── Auto-fit to clients ──────────────────────────────────────────────────
  useEffect(() => {
    if (!map.current) return
    const positioned = Object.values(clients).filter((c) => c.position)
    if (positioned.length === 0) return

    if (positioned.length === 1) {
      const { lat, lon } = positioned[0].position!
      map.current.flyTo({ center: [lon, lat], zoom: 14 })
      return
    }

    const lons = positioned.map((c) => c.position!.lon)
    const lats = positioned.map((c) => c.position!.lat)
    map.current.fitBounds(
      [
        [Math.min(...lons), Math.min(...lats)],
        [Math.max(...lons), Math.max(...lats)],
      ],
      { padding: 80, maxZoom: 16 },
    )
  }, [Object.keys(clients).length])

  return (
    <div className="relative w-full h-full">
      <div ref={mapContainer} className="w-full h-full" />
      <ClientCount count={Object.keys(clients).length} online={Object.values(clients).filter(c => c.isOnline).length} />
    </div>
  )
}

function ClientCount({ count, online }: { count: number; online: number }) {
  return (
    <div className="absolute top-3 left-3 bg-surface-raised/90 backdrop-blur rounded-lg px-3 py-1.5 text-sm font-medium border border-surface-border">
      <span className="text-accent-green">{online}</span>
      <span className="text-gray-400">/{count} online</span>
    </div>
  )
}

function createMarkerElement(callsign: string, color: string, selected: boolean, offline: boolean) {
  const el = document.createElement('div')
  el.className = 'flex flex-col items-center cursor-pointer group'
  el.innerHTML = `
    <div style="background:${offline ? '#6b7280' : color};border:${selected ? '3px solid white' : '2px solid rgba(0,0,0,0.4)'}"
         class="w-10 h-10 rounded-full flex items-center justify-center shadow-lg text-white text-xs font-bold uppercase transition-transform group-hover:scale-110">
      ${callsign.slice(0, 2)}
    </div>
    <div class="mt-0.5 px-1.5 py-0.5 rounded text-xs font-medium text-white shadow"
         style="background:rgba(0,0,0,0.65)">
      ${callsign}
    </div>
  `
  return el
}

function updateMarkerElement(
  marker: maplibregl.Marker,
  callsign: string,
  color: string,
  selected: boolean,
  offline: boolean,
) {
  const el = marker.getElement()
  const circle = el.querySelector('div') as HTMLElement
  if (!circle) return
  circle.style.background = offline ? '#6b7280' : color
  circle.style.border = selected ? '3px solid white' : '2px solid rgba(0,0,0,0.4)'
}
