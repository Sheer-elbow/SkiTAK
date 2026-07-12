import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { logout } from '@/api'
import { useOtsSocket } from '@/hooks/useOtsSocket'
import { useStore } from '@/store'
import clsx from 'clsx'

export function AppShell() {
  useOtsSocket()

  const clients = useStore((s) => s.clients)
  const activeSession = useStore((s) => s.activeSession)
  const clearAuth = useStore((s) => s.clearAuth)
  const location = useLocation()
  const navigate = useNavigate()

  const onlineCount = Object.values(clients).filter((c) => c.isOnline).length

  async function handleLogout() {
    await logout().catch(() => {})
    clearAuth()
    navigate('/login')
  }

  return (
    <div className="flex flex-col h-full bg-surface">
      {/* ── Top nav ───────────────────────────────────────────────── */}
      <nav className="flex items-center gap-1 px-4 h-11 border-b border-surface-border flex-shrink-0">
        <span className="font-bold text-sm mr-3 tracking-tight">SkiTAK</span>

        <NavLink to="/"         label="Live Map" active={location.pathname === '/'} />
        <NavLink to="/clients"  label="Clients"  active={location.pathname === '/clients'} />
        <NavLink to="/sessions" label="Sessions" active={location.pathname.startsWith('/sessions')} />

        <div className="ml-auto flex items-center gap-2">
          {onlineCount > 0 && (
            <div className="flex items-center gap-1.5 text-xs text-gray-400">
              <span className="w-2 h-2 rounded-full bg-accent-green animate-pulse" />
              {onlineCount} online
            </div>
          )}
          {activeSession && (
            <span className="text-xs bg-accent/20 text-accent px-2 py-0.5 rounded-full max-w-[140px] truncate">
              {activeSession.name}
            </span>
          )}
          <button
            onClick={handleLogout}
            className="text-xs text-gray-500 hover:text-gray-200 px-2 py-1"
          >
            Sign out
          </button>
        </div>
      </nav>

      <EmergencyBanner />

      {/* ── Page content (rendered by router) ─────────────────────── */}
      <div className="flex-1 min-h-0">
        <Outlet />
      </div>
    </div>
  )
}

function EmergencyBanner() {
  const alerts = useStore((s) => s.alerts)
  const dismissAlert = useStore((s) => s.dismissAlert)
  const selectClient = useStore((s) => s.selectClient)

  if (alerts.length === 0) return null

  return (
    <div className="flex-shrink-0">
      {alerts.map((alert) => {
        const isGeofence = alert.alertType.startsWith('geofence')
        return (
        <div
          key={alert.uid}
          className={clsx(
            'flex items-center gap-3 px-4 py-2 text-sm text-white',
            isGeofence ? 'bg-amber-600/95' : 'bg-accent-red/95',
          )}
        >
          <span className="text-lg animate-pulse">{isGeofence ? '⚠️' : '🆘'}</span>
          <span className="font-semibold">
            {isGeofence
              ? `GEOFENCE — ${alert.callsign ?? alert.senderUid} ${
                  alert.alertType === 'geofence-exit' ? 'left' : 'entered'
                } "${alert.geofenceName ?? 'zone'}"`
              : `EMERGENCY — ${alert.callsign ?? alert.senderUid}`}
          </span>
          {alert.location && (
            <button
              onClick={() => selectClient(alert.senderUid)}
              className="underline underline-offset-2 text-white/90 hover:text-white"
            >
              {alert.location.lat.toFixed(5)}, {alert.location.lon.toFixed(5)}
            </button>
          )}
          <span className="text-white/70 text-xs">
            {new Date(alert.startedAt).toLocaleTimeString()}
          </span>
          <button
            onClick={() => dismissAlert(alert.uid)}
            className="ml-auto text-white/70 hover:text-white text-xs font-medium"
          >
            Dismiss
          </button>
        </div>
        )
      })}
    </div>
  )
}

function NavLink({ to, label, active }: { to: string; label: string; active: boolean }) {
  return (
    <Link
      to={to}
      className={clsx(
        'px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
        active
          ? 'bg-surface-raised text-white'
          : 'text-gray-400 hover:text-white hover:bg-surface-raised',
      )}
    >
      {label}
    </Link>
  )
}
