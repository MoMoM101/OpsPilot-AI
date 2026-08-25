import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { components } from '../api/generated/schema'
import { authApi } from '../api/authApi'
import { setupApi, type SetupStatus } from '../api/setupApi'
import { clearClientCredentials, getAlphaBearerToken, isAutomaticSessionRefreshHeld, setAlphaBearerToken, setCsrfToken, subscribeSessionInvalidation } from './authSession'

export type CurrentUser = components['schemas']['PrincipalSessionResponse']
type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated' | 'setup_required'

interface AuthContextValue {
  status: AuthStatus
  user: CurrentUser | null
  canWrite: boolean
  isAdmin: boolean
  loginWithSession: (token: string) => Promise<void>
  loginWithBearer: (token: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
  refreshSession: () => Promise<void>
  sessionExpiresAt: string | null
  setupStatus: SetupStatus | null
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function authorizationScopeKey(user: CurrentUser | null): string {
  if (!user) return 'unauthenticated'
  return [user.id, user.role, user.unrestrictedEnvironments ? 'all' : 'restricted', [...user.environmentIds].sort().join(',')].join('|')
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [user, setUser] = useState<CurrentUser | null>(null)
  const currentUserRef = useRef<CurrentUser | null>(null)
  const [sessionExpiresAt, setSessionExpiresAt] = useState<string | null>(null)
  const [setupStatus, setSetupStatus] = useState<SetupStatus | null>(null)

  const updateUser = (nextUser: CurrentUser | null) => {
    if (authorizationScopeKey(currentUserRef.current) !== authorizationScopeKey(nextUser)) {
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    }
    currentUserRef.current = nextUser
    setUser(nextUser)
  }

  const becomeUnauthenticated = () => {
    updateUser(null)
    setSessionExpiresAt(null)
    setStatus('unauthenticated')
  }

  const refresh = async () => {
    try {
      updateUser(await authApi.me())
      setSetupStatus(null)
      setStatus('authenticated')
    } catch {
      updateUser(null)
      setSessionExpiresAt(null)
      try {
        const setup = await setupApi.status()
        setSetupStatus(setup)
        setStatus(setup.status === 'initialization_required' ? 'setup_required' : 'unauthenticated')
      } catch {
        setSetupStatus(null)
        setStatus('unauthenticated')
      }
    }
  }

  useEffect(() => {
    void refresh()
    return subscribeSessionInvalidation(becomeUnauthenticated)
  }, [])

  useEffect(() => {
    if (status !== 'authenticated' || getAlphaBearerToken()) return
    const timer = window.setInterval(() => {
      if (isAutomaticSessionRefreshHeld()) return
      void authApi.refresh().then((session) => {
        setCsrfToken(session.csrfToken)
        updateUser(session.principal)
        setSessionExpiresAt(session.expiresAt)
      }).catch(() => undefined)
    }, 30 * 60 * 1_000)
    return () => window.clearInterval(timer)
  }, [status])

  const value = useMemo<AuthContextValue>(() => ({
    status,
    user,
    canWrite: user?.role === 'operator' || user?.role === 'admin',
    isAdmin: user?.role === 'admin',
    loginWithSession: async (token) => {
      clearClientCredentials()
      const session = await authApi.exchange(token)
      setCsrfToken(session.csrfToken)
      updateUser(session.principal)
      setSessionExpiresAt(session.expiresAt)
      setSetupStatus(null)
      setStatus('authenticated')
    },
    loginWithBearer: async (token) => {
      setAlphaBearerToken(token)
      try {
        updateUser(await authApi.me())
        setSetupStatus(null)
        setStatus('authenticated')
      } catch (error) {
        clearClientCredentials()
        throw error
      }
    },
    logout: async () => {
      try { await authApi.logout() } finally {
        clearClientCredentials()
        becomeUnauthenticated()
      }
    },
    refresh,
    refreshSession: async () => {
      const session = await authApi.refresh()
      setCsrfToken(session.csrfToken)
      updateUser(session.principal)
      setSessionExpiresAt(session.expiresAt)
    },
    sessionExpiresAt,
    setupStatus,
  }), [sessionExpiresAt, setupStatus, status, user])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used within AuthProvider')
  return value
}
