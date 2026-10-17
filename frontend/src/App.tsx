import { useEffect } from 'react'
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { apiGet } from './api/client'
import { AuthProvider } from './auth/AuthContext'
import { useAuth } from './auth/useAuth'
import Layout from './components/Layout'
import { setToday } from './lib/format'
import LoginPage from './pages/LoginPage'
import AppEventsPage from './pages/AppEventsPage'
import SubscribersPage from './pages/SubscribersPage'
import WebEventsPage from './pages/WebEventsPage'

function RequireAuth() {
  const { user, checking } = useAuth()
  const location = useLocation()
  if (checking) return <p className="page-status">Loading…</p>
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  return <Outlet />
}

export default function App() {
  // The server owns "today" (2026-09-28 per the brief); the UI follows it.
  useEffect(() => {
    apiGet<{ today: string }>('/health')
      .then((health) => setToday(health.today))
      .catch(() => undefined)
  }, [])

  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RequireAuth />}>
            <Route element={<Layout />}>
              <Route path="/subscribers" element={<SubscribersPage />} />
              <Route path="/web-events" element={<WebEventsPage />} />
              <Route path="/app-events" element={<AppEventsPage />} />
              <Route path="*" element={<Navigate to="/subscribers" replace />} />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
