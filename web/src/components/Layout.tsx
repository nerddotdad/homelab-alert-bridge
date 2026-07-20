import { NavLink, Outlet } from 'react-router-dom'
import { useLiveUpdates } from '../hooks/useLiveUpdates'
import {
  faBell,
  faGear,
  faPlus,
  faTicket,
  faWifi,
} from '../lib/icons'
import { Icon } from './Icon'

const links = [
  { to: '/', label: 'Incidents', end: true, icon: faTicket },
  { to: '/alerts', label: 'Alerts', icon: faBell },
  { to: '/incidents/new', label: 'New', icon: faPlus },
  { to: '/settings', label: 'Settings', icon: faGear },
]

export function Layout() {
  const live = useLiveUpdates()

  return (
    <div className="wrap">
      <header className="site-header">
        <div>
          <h1>
            <NavLink to="/" className="brand-link">
              Hearth
            </NavLink>
          </h1>
          <div className="muted">Homelab incident desk</div>
        </div>
        <div className="header-right">
          <span className={`live-pill live-${live}`} title="Server-sent live updates">
            <Icon icon={faWifi} />
            {live === 'live' ? 'Live' : live === 'reconnect' ? 'Reconnecting…' : 'Connecting…'}
          </span>
          <nav className="site-nav" aria-label="Primary">
            {links.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.end}
                className={({ isActive }) => (isActive ? 'active' : undefined)}
              >
                <Icon icon={link.icon} />
                {link.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <Outlet />
    </div>
  )
}
