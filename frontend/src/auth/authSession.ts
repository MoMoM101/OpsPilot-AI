import { apiConfig } from '../api/config'

const alphaBearerKey = 'opspilot.alpha.user-token'

let epoch = 0
let csrfToken: string | undefined
let sessionRefreshHolds = 0
const listeners = new Set<() => void>()
const invalidationListeners = new Set<() => void>()

function emit() {
  epoch += 1
  for (const listener of listeners) listener()
}

function sessionStorageSafe() {
  try { return window.sessionStorage } catch { return undefined }
}

export function getAlphaBearerToken() {
  return sessionStorageSafe()?.getItem(alphaBearerKey) ?? undefined
}

export function setAlphaBearerToken(token: string) {
  sessionStorageSafe()?.setItem(alphaBearerKey, token)
  emit()
}

export function clearClientCredentials() {
  sessionStorageSafe()?.removeItem(alphaBearerKey)
  csrfToken = undefined
  emit()
}

export function setCsrfToken(token: string | undefined) {
  csrfToken = token || undefined
}

export function getCsrfToken() {
  if (csrfToken) return csrfToken
  const cookieValue = readCookie(apiConfig.csrfCookieName)
  return cookieValue ? decodeURIComponent(cookieValue) : undefined
}

export function authEpochSnapshot() { return epoch }
export function subscribeAuthEpoch(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function subscribeSessionInvalidation(listener: () => void) {
  invalidationListeners.add(listener)
  return () => { invalidationListeners.delete(listener) }
}

export function invalidateSession() {
  clearClientCredentials()
  for (const listener of invalidationListeners) listener()
}

export function holdAutomaticSessionRefresh() {
  sessionRefreshHolds += 1
  let released = false
  return () => {
    if (released) return
    released = true
    sessionRefreshHolds = Math.max(0, sessionRefreshHolds - 1)
  }
}

export function isAutomaticSessionRefreshHeld() {
  return sessionRefreshHolds > 0
}

export function readCookie(name: string) {
  const prefix = `${encodeURIComponent(name)}=`
  return document.cookie.split(';').map((part) => part.trim()).find((part) => part.startsWith(prefix))?.slice(prefix.length)
}

const publicPaths = new Set(['/health', '/ready', '/setup/status', '/auth/session'])

export function requestAuth(path: string, method: string) {
  const normalized = path.startsWith('/') ? path : `/${path}`
  const isRunnerService = normalized.startsWith('/runner/') || normalized.startsWith('/runner/v1/')
  const isPublic = publicPaths.has(normalized) && !(normalized === '/auth/session' && method === 'DELETE')
  const headers = new Headers()

  if (!isPublic && !isRunnerService) {
    const bearer = getAlphaBearerToken()
    if (bearer) headers.set('Authorization', `Bearer ${bearer}`)
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      const csrf = getCsrfToken()
      if (csrf) headers.set('X-CSRF-Token', decodeURIComponent(csrf))
    }
  }
  return { headers, credentials: isRunnerService ? 'omit' as const : 'include' as const }
}
