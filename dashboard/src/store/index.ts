import { create } from 'zustand'
import type { Client, Session, Team, ChatMessage, POI } from '@/types'

interface AppState {
  // Auth
  isAuthenticated: boolean
  currentUserUid: string | null
  setAuth: (uid: string) => void
  clearAuth: () => void

  // Active session
  activeSession: Session | null
  setActiveSession: (session: Session | null) => void

  // Live clients — keyed by TAK UID
  clients: Record<string, Client>
  upsertClient: (client: Client) => void
  markStaleClients: () => void

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
  isAuthenticated: false,
  currentUserUid: null,
  setAuth: (uid) => set({ isAuthenticated: true, currentUserUid: uid }),
  clearAuth: () => set({ isAuthenticated: false, currentUserUid: null }),

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
