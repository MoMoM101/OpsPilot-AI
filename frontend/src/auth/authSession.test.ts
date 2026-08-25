import { afterEach, describe, expect, it, vi } from 'vitest'
import { authEpochSnapshot, clearClientCredentials, holdAutomaticSessionRefresh, isAutomaticSessionRefreshHeld, requestAuth, setAlphaBearerToken, setCsrfToken, subscribeAuthEpoch } from './authSession'

afterEach(() => {
  clearClientCredentials()
  document.cookie = 'opspilot_csrf=; Max-Age=0; path=/'
})

describe('authentication request policy', () => {
  it('injects an Alpha user Bearer only into protected control-plane APIs', () => {
    setAlphaBearerToken('user-access-token-1234567890')
    expect(requestAuth('/dashboard', 'GET').headers.get('Authorization')).toBe('Bearer user-access-token-1234567890')
    expect(requestAuth('/health', 'GET').headers.has('Authorization')).toBe(false)
    expect(requestAuth('/auth/session', 'POST').headers.has('Authorization')).toBe(false)
    expect(requestAuth('/runner/v1/runners/id/heartbeat', 'POST')).toMatchObject({ credentials: 'omit' })
    expect(requestAuth('/runner/v1/runners/id/heartbeat', 'POST').headers.has('Authorization')).toBe(false)
  })

  it('uses browser Session credentials and CSRF when no Bearer is present', () => {
    document.cookie = 'opspilot_csrf=csrf-token; path=/'
    const request = requestAuth('/runner-tasks', 'POST')
    expect(request.credentials).toBe('include')
    expect(request.headers.has('Authorization')).toBe(false)
    expect(request.headers.get('X-CSRF-Token')).toBe('csrf-token')
  })

  it('prefers the CSRF Token returned by login or refresh over the cookie fallback', () => {
    document.cookie = 'opspilot_csrf=stale-cookie-token; path=/'
    setCsrfToken('rotated-response-token')
    expect(requestAuth('/outbox/dead-letters/event-1/replay', 'POST').headers.get('X-CSRF-Token')).toBe('rotated-response-token')
  })

  it('notifies SSE consumers when the token changes', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeAuthEpoch(listener)
    const before = authEpochSnapshot()
    setAlphaBearerToken('updated-user-token-1234567890')
    expect(authEpochSnapshot()).toBeGreaterThan(before)
    expect(listener).toHaveBeenCalled()
    unsubscribe()
  })

  it('holds automatic Session refresh while a one-time Token is visible', () => {
    const release = holdAutomaticSessionRefresh()
    expect(isAutomaticSessionRefreshHeld()).toBe(true)
    release()
    release()
    expect(isAutomaticSessionRefreshHeld()).toBe(false)
  })
})
