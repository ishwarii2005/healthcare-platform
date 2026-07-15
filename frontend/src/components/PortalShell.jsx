import { useAuth } from '../context/AuthContext'

export default function PortalShell({ tagline, links, active, onNavigate, children }) {
  const { user, logout } = useAuth()

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">City Care</div>
        <div className="brand-tag">{tagline}</div>
        <nav>
          {links.map((l) => (
            <button
              key={l.key}
              className={`nav-link ${active === l.key ? 'active' : ''}`}
              onClick={() => onNavigate(l.key)}
            >
              {l.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          Signed in as<br /><strong>{user?.full_name}</strong>
          <button onClick={logout}>Log out</button>
        </div>
      </aside>
      <main className="main-content">{children}</main>
    </div>
  )
}
