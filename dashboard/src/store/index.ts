import { create } from 'zustand'
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
  setActiveSession: (session) => set({ activeSession: session }),

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
