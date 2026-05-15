import { Outlet, Link, useLocation } from 'react-router-dom'
import { useStore } from '@/store'
import { useCoTSocket } from '@/hooks/useCoTSocket'
import clsx from 'clsx'

export function AppShell() {
  useCoTSocket()

  const clients = useStore((s) => s.clients)
  const activeSession = useStore((s) => s.activeSession)
  const location = useLocation()

  const onlineCount = Object.values(clients).filter((c) => c.isOnline).length

  return (
    <div className="flex flex-col h-full bg-surface">
      {/* ── Top nav ───────────────────────────────────────────────── */}
      <nav className="flex items-center gap-1 px-4 h-11 border-b border-surface-border flex-shrink-0">
        <span className="font-bold text-sm mr-3 tracking-tight">SkiTAK</span>

        <NavLink to="/"        label="Live Map" active={location.pathname === '/'} />
        <NavLink to="/clients" label="Clients"  active={location.pathname === '/clients'} />

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
        </div>
      </nav>

      {/* ── Page content (rendered by router) ─────────────────────── */}
      <div className="flex-1 min-h-0">
        <Outlet />
      </div>
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
