import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'
import ActivityDialog from './ActivityDialog'
import ProfileSearch from './ProfileSearch'
import './Layout.css'

// Pages appear here as they're built.
const NAV = [
  { to: '/subscribers', label: 'Subscribers' },
  { to: '/web-events', label: 'Web Events' },
  { to: '/app-events', label: 'App Events' },
  { to: '/segments', label: 'Segments' },
  { to: '/assistant', label: 'Assistant' },
  { to: '/setup', label: 'Setup' },
]

export function BrandMark({ size = 34 }: { size?: number }) {
  return <span className="brand-mark" style={{ width: size, height: size }} aria-hidden="true" />
}

export default function Layout() {
  const { user, signOut } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <div className="shell">
      <header className="site-header">
        <div className="header-inner">
          <NavLink to="/" className="brand" onClick={() => setMenuOpen(false)}>
            <BrandMark />
            <span className="brand-text">
              <span className="brand-name">The Pour Over</span>
              <span className="brand-title">Mini Subscriber Data Platform</span>
            </span>
          </NavLink>

          <ProfileSearch />

          <button
            className="menu-toggle btn btn-ghost"
            aria-expanded={menuOpen}
            aria-controls="main-nav"
            onClick={() => setMenuOpen((open) => !open)}
          >
            Menu
          </button>

          <nav id="main-nav" className={menuOpen ? 'main-nav open' : 'main-nav'} aria-label="Main">
            {NAV.map((item) => (
              <NavLink key={item.to} to={item.to} className="nav-link" onClick={() => setMenuOpen(false)}>
                {item.label}
              </NavLink>
            ))}
            {user && (
              <span className="nav-user">
                <span className="nav-username">{user.name}</span>
                <button className="btn" onClick={() => void signOut()}>
                  Sign out
                </button>
              </span>
            )}
          </nav>
        </div>
      </header>

      <main className="page">
        <Outlet />
      </main>

      <ActivityDialog />

      <footer className="site-footer">
        Prepared by Jason Cox for The Pour Over <span aria-hidden="true">|</span> October 2026{' '}
        <span aria-hidden="true">|</span> Full-stack Developer Pre-Employment Project
      </footer>
    </div>
  )
}
