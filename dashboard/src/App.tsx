import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { checkAuth } from '@/api'
import { AppShell } from '@/components/layout/AppShell'
import { ClientsPage } from '@/pages/ClientsPage'
import { LiveMapPage } from '@/pages/LiveMapPage'
import { Login } from '@/pages/Login'
import { SessionReplayPage } from '@/pages/SessionReplayPage'
import { SessionsPage } from '@/pages/SessionsPage'
import { useStore } from '@/store'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
})

function RequireAuth({ children }: { children: React.ReactNode }) {
  const authStatus = useStore((s) => s.authStatus)
  if (authStatus === 'checking') {
    return (
      <div className="min-h-full flex items-center justify-center text-gray-400 text-sm">
        Connecting…
      </div>
    )
  }
  return authStatus === 'authenticated' ? <>{children}</> : <Navigate to="/login" replace />
}

export function App() {
  const setAuth = useStore((s) => s.setAuth)
  const clearAuth = useStore((s) => s.clearAuth)

  // Restore the Flask-Security session cookie on page load
  useEffect(() => {
    checkAuth().then((username) => {
      if (username) setAuth(username)
      else clearAuth()
    })
  }, [])

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />

          <Route
            element={
              <RequireAuth>
                <AppShell />
              </RequireAuth>
            }
          >
            <Route index element={<LiveMapPage />} />
            <Route path="clients" element={<ClientsPage />} />
            <Route path="sessions" element={<SessionsPage />} />
            <Route path="sessions/:sessionId" element={<SessionReplayPage />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
