import { create } from 'zustand'
import type { Geofence, PlannedRoute } from '@/api'
import type { ChatMessage, Client, EmergencyAlert, POI, Session } from '@/types'

type AuthStatus = 'checking' | 'authenticated' | 'anonymous'

interface AppState {
  // Auth — 'checking' until the session cookie has been validated on load
  authStatus: AuthStatus
  currentUser: string | null
  setAuth: (username: string) => void
  clearAuth: () => void

  // Active session
  activeSession: Session | null
  setActiveSession: (session: Session | null) => void

  // Planned route for the active session
  plannedRoute: PlannedRoute | null
  setPlannedRoute: (route: PlannedRoute | null) => void

  // Geofences for the active session
  geofences: Geofence[]
  setGeofences: (fences: Geofence[]) => void
  // Click-to-draw state: non-null while the guide is placing polygon points
  drawingFence: Array<{ lat: number; lon: number }> | null
  startDrawingFence: () => void
  addDrawingPoint: (p: { lat: number; lon: number }) => void
  cancelDrawingFence: () => void

  // Live clients — keyed by device (EUD) UID
  clients: Record<string, Client>
  upsertClient: (client: Client) => void
  markStaleClients: () => void

  // Emergency alerts (b-a-o-* CoT)
  alerts: EmergencyAlert[]
  upsertAlert: (alert: EmergencyAlert) => void
  dismissAlert: (uid: string) => void

  // Chat
  messages: ChatMessage[]
  addMessage: (msg: ChatMessage) => void

  // POIs
  pois: POI[]
  addPoi: (poi: POI) => void
  removePoi: (id: string) => void

  // UI state
  selectedUid: string | null
  selectClient: (uid: string | null) => void
  sidebarTab: 'clients' | 'chat' | 'session'
  setSidebarTab: (tab: AppState['sidebarTab']) => void
}

const STALE_THRESHOLD_MS = 5 * 60 * 1000  // 5 minutes

export const useStore = create<AppState>((set) => ({
  authStatus: 'checking',
  currentUser: null,
  setAuth: (username) => set({ authStatus: 'authenticated', currentUser: username }),
  clearAuth: () => set({ authStatus: 'anonymous', currentUser: null }),

  activeSession: null,
  setActiveSession: (session) =>
    set((state) => ({
      activeSession: session,
      // Route belongs to a session — drop it when the session changes
      plannedRoute: session && session.id === state.activeSession?.id ? state.plannedRoute : null,
    })),

  plannedRoute: null,
  setPlannedRoute: (route) => set({ plannedRoute: route }),

  geofences: [],
  setGeofences: (fences) => set({ geofences: fences }),
  drawingFence: null,
  startDrawingFence: () => set({ drawingFence: [] }),
  addDrawingPoint: (p) =>
    set((state) => ({
      drawingFence: state.drawingFence ? [...state.drawingFence, p] : state.drawingFence,
    })),
  cancelDrawingFence: () => set({ drawingFence: null }),

  clients: {},
  upsertClient: (client) =>
    set((state) => ({
      clients: { ...state.clients, [client.uid]: client },
    })),
  markStaleClients: () =>
    set((state) => {
      const now = Date.now()
      const updated = Object.fromEntries(
        Object.entries(state.clients).map(([uid, c]) => [
          uid,
          { ...c, isOnline: now - c.lastSeen.getTime() < STALE_THRESHOLD_MS },
        ]),
      )
      return { clients: updated }
    }),

  alerts: [],
  upsertAlert: (alert) =>
    set((state) => ({
      alerts: [...state.alerts.filter((a) => a.uid !== alert.uid), alert],
    })),
  dismissAlert: (uid) =>
    set((state) => ({ alerts: state.alerts.filter((a) => a.uid !== uid) })),

  messages: [],
  addMessage: (msg) =>
    set((state) => ({
      // Keep last 200 messages in memory
      messages: [...state.messages.slice(-199), msg],
    })),

  pois: [],
  addPoi: (poi) => set((state) => ({ pois: [...state.pois, poi] })),
  removePoi: (id) =>
    set((state) => ({ pois: state.pois.filter((p) => p.id !== id) })),

  selectedUid: null,
  selectClient: (uid) => set({ selectedUid: uid }),

  sidebarTab: 'clients',
  setSidebarTab: (tab) => set({ sidebarTab: tab }),
}))
