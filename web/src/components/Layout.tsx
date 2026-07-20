import { NavLink, Outlet } from 'react-router-dom'

const links = [
  { to: '/', label: 'Incidents', end: true },
  { to: '/alerts', label: 'Alerts' },
  { to: '/incidents/new', label: 'New' },
  { to: '/settings', label: 'Settings' },
]

export function Layout() {
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
        <nav className="site-nav" aria-label="Primary">
          {links.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) => (isActive ? 'active' : undefined)}
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <Outlet />
    </div>
  )
}
