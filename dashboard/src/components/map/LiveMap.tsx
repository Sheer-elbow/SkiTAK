import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useStore } from '@/store'
import { TEAM_COLORS } from '@/types'
import clsx from 'clsx'

type BaseLayer = 'os-outdoor' | 'topo' | 'satellite'

const BASE_LAYERS: Record<BaseLayer, {
  label: string
  tiles: string[]
  tileSize: number
  maxzoom: number
  attribution: string
}> = {
  'os-outdoor': {
    label: 'OS Outdoor',
    // Proxied through our Nginx — key never reaches the browser
    tiles: ['/os-tiles/{z}/{x}/{y}.png'],
    tileSize: 256,
    maxzoom: 20,
    attribution: '© Crown copyright and database rights OS',
  },
  'topo': {
    label: 'OpenTopo',
    tiles: [
      'https://a.tile.opentopomap.org/{z}/{x}/{y}.png',
      'https://b.tile.opentopomap.org/{z}/{x}/{y}.png',
      'https://c.tile.opentopomap.org/{z}/{x}/{y}.png',
    ],
    tileSize: 256,
    maxzoom: 17,
    attribution: '© OpenTopoMap contributors',
  },
  'satellite': {
    label: 'Satellite',
    tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
    tileSize: 256,
    maxzoom: 19,
    attribution: '© Esri, Maxar, Earthstar Geographics',
  },
}

export function LiveMap() {
  const mapContainer = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const markers = useRef<Record<string, maplibregl.Marker>>({})
  const [activeLayer, setActiveLayer] = useState<BaseLayer>('os-outdoor')

  const clients = useStore((s) => s.clients)
  const pois = useStore((s) => s.pois)
  const selectedUid = useStore((s) => s.selectedUid)
  const selectClient = useStore((s) => s.selectClient)
  const plannedRoute = useStore((s) => s.plannedRoute)
  const routeRef = useRef(plannedRoute)
  routeRef.current = plannedRoute

  // ── Initialise map ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!mapContainer.current || map.current) return

    const layer = BASE_LAYERS['os-outdoor']

    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style: buildStyle('os-outdoor', layer),
      center: [-2.0, 54.0],   // centre on UK by default
      zoom: 6,
    })

    map.current.addControl(new maplibregl.NavigationControl(), 'top-right')
    map.current.addControl(
      new maplibregl.GeolocateControl({ trackUserLocation: false }),
      'top-right',
    )
    map.current.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right')

    // Custom sources are wiped by setStyle (base-layer switch) — re-sync the
    // planned route whenever a style finishes loading.
    map.current.on('load', () => syncRoute(map.current!, routeRef.current))
    map.current.on('styledata', () => syncRoute(map.current!, routeRef.current))

    return () => {
      map.current?.remove()
      map.current = null
    }
  }, [])

  // ── Planned route overlay ────────────────────────────────────────────────
  useEffect(() => {
    if (map.current?.isStyleLoaded()) syncRoute(map.current, plannedRoute)
  }, [plannedRoute])

  // ── Switch base layer ────────────────────────────────────────────────────
  useEffect(() => {
    if (!map.current || !map.current.isStyleLoaded()) return
    const layer = BASE_LAYERS[activeLayer]
    map.current.setStyle(buildStyle(activeLayer, layer))
    // Re-add markers after style reload
    Object.values(markers.current).forEach((m) => m.remove())
    markers.current = {}
  }, [activeLayer])

  // ── Update client markers ────────────────────────────────────────────────
  useEffect(() => {
    if (!map.current) return

    const activeUids = new Set(Object.keys(clients))

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
        markers.current[client.uid].setLngLat([lon, lat])
        updateMarkerElement(markers.current[client.uid], color, isSelected, isOffline)
      } else {
        const el = createMarkerElement(client.callsign, color, isSelected, isOffline)
        el.addEventListener('click', () => selectClient(client.uid))

        markers.current[client.uid] = new maplibregl.Marker({ element: el, anchor: 'bottom' })
          .setLngLat([lon, lat])
          .setPopup(
            new maplibregl.Popup({ offset: 25 }).setHTML(`
              <div class="font-medium text-sm">${client.callsign}</div>
              ${client.speedMs != null ? `<div class="text-xs text-gray-400">${(client.speedMs * 3.6).toFixed(1)} km/h</div>` : ''}
              ${client.batteryPct != null ? `<div class="text-xs">🔋 ${client.batteryPct}%</div>` : ''}
              ${client.heartRateBpm != null ? `<div class="text-xs">♥ ${client.heartRateBpm} bpm</div>` : ''}
            `),
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

  // ── Auto-fit bounds to connected clients ─────────────────────────────────
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
      [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
      { padding: 80, maxZoom: 16 },
    )
  }, [Object.keys(clients).length])

  const onlineCount = Object.values(clients).filter((c) => c.isOnline).length

  return (
    <div className="relative w-full h-full">
      <div ref={mapContainer} className="w-full h-full" />

      {/* Online count */}
      <div className="absolute top-3 left-3 bg-surface-raised/90 backdrop-blur rounded-lg px-3 py-1.5 text-sm font-medium border border-surface-border pointer-events-none">
        <span className="text-accent-green">{onlineCount}</span>
        <span className="text-gray-400">/{Object.keys(clients).length} online</span>
      </div>

      {/* Layer switcher */}
      <div className="absolute bottom-10 left-3 flex gap-1 bg-surface-raised/90 backdrop-blur rounded-lg p-1 border border-surface-border">
        {(Object.entries(BASE_LAYERS) as [BaseLayer, typeof BASE_LAYERS[BaseLayer]][]).map(([key, { label }]) => (
          <button
            key={key}
            onClick={() => setActiveLayer(key)}
            className={clsx(
              'px-2.5 py-1 rounded-md text-xs font-medium transition-colors',
              activeLayer === key
                ? 'bg-accent text-white'
                : 'text-gray-400 hover:text-white',
            )}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────

function buildStyle(id: BaseLayer, layer: typeof BASE_LAYERS[BaseLayer]): maplibregl.StyleSpecification {
  return {
    version: 8,
    sources: {
      'base-tiles': {
        type: 'raster',
        tiles: layer.tiles,
        tileSize: layer.tileSize,
        attribution: layer.attribution,
        maxzoom: layer.maxzoom,
      },
    },
    layers: [{ id: 'base-layer', type: 'raster', source: 'base-tiles' }],
  }
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

function updateMarkerElement(marker: maplibregl.Marker, color: string, selected: boolean, offline: boolean) {
  const circle = marker.getElement().querySelector('div') as HTMLElement | null
  if (!circle) return
  circle.style.background = offline ? '#6b7280' : color
  circle.style.border = selected ? '3px solid white' : '2px solid rgba(0,0,0,0.4)'
}

// Add / update / remove the planned-route line on the current style.
// Safe to call repeatedly (idempotent per style).
function syncRoute(
  m: maplibregl.Map,
  route: { points: Array<{ lat: number; lon: number }> } | null,
) {
  const SOURCE = 'skitak-planned-route'
  try {
    const existing = m.getSource(SOURCE) as maplibregl.GeoJSONSource | undefined
    if (!route || route.points.length < 2) {
      if (m.getLayer(SOURCE)) m.removeLayer(SOURCE)
      if (existing) m.removeSource(SOURCE)
      return
    }
    const data: GeoJSON.Feature = {
      type: 'Feature',
      properties: {},
      geometry: {
        type: 'LineString',
        coordinates: route.points.map((p) => [p.lon, p.lat]),
      },
    }
    if (existing) {
      existing.setData(data)
    } else {
      m.addSource(SOURCE, { type: 'geojson', data })
    }
    if (!m.getLayer(SOURCE)) {
      m.addLayer({
        id: SOURCE,
        type: 'line',
        source: SOURCE,
        paint: {
          'line-color': '#22c55e',
          'line-width': 4,
          'line-opacity': 0.8,
          'line-dasharray': [2, 1.5],
        },
        layout: { 'line-cap': 'round', 'line-join': 'round' },
      })
    }
  } catch {
    // styledata can fire mid-style-swap; the next event re-syncs
  }
}
