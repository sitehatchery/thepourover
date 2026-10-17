import { createContext, useContext } from 'react'
import type { CurrentUser } from '../api/types'

export type AuthState = {
  user: CurrentUser | null
  checking: boolean
  signIn: (username: string, password: string) => Promise<void>
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
