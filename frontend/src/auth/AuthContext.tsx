import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { apiGet, apiSend, onSessionEnded, refreshSession, setAccessToken } from '../api/client'
import type { CurrentUser } from '../api/types'
import { AuthContext } from './useAuth'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [checking, setChecking] = useState(true)

  // On load, a valid refresh cookie restores the session without asking for the password again.
  useEffect(() => {
    onSessionEnded(() => setUser(null))
    refreshSession()
      .then(async (ok) => (ok ? setUser(await apiGet<CurrentUser>('/auth/me')) : null))
      .catch(() => setUser(null))
      .finally(() => setChecking(false))
  }, [])

  const signIn = useCallback(async (username: string, password: string) => {
    const tokens = await apiSend<{ access_token: string }>('POST', '/auth/login', { username, password })
    setAccessToken(tokens.access_token)
    setUser(await apiGet<CurrentUser>('/auth/me'))
  }, [])

  const signOut = useCallback(async () => {
    await apiSend('POST', '/auth/logout').catch(() => undefined)
    setAccessToken(null)
    setUser(null)
  }, [])

  const value = useMemo(() => ({ user, checking, signIn, signOut }), [user, checking, signIn, signOut])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
