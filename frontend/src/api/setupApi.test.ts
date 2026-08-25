import { afterEach, describe, expect, it, vi } from 'vitest'
import { clearClientCredentials, getAlphaBearerToken, setAlphaBearerToken } from '../auth/authSession'
import { setupApi } from './setupApi'

afterEach(() => { vi.unstubAllGlobals(); clearClientCredentials() })

describe('Setup API', () => {
  it('checks public setup status without sending a stored user Bearer', async () => {
    setAlphaBearerToken('old-user-access-token-1234567890')
    vi.stubGlobal('fetch', vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      expect(new Headers(init?.headers).has('Authorization')).toBe(false)
      return new Response(JSON.stringify({ status: 'ready', service: 'opspilot', version: '1.0', authenticationEnabled: true, initialAdminCreated: true, bootstrapAvailable: false }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))

    await setupApi.status()
  })

  it('sends the Bootstrap Token only in Authorization and creates a fixed unrestricted Admin', async () => {
    const bootstrapToken = 'bootstrap-secret-token-1234567890'
    const fetchMock = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      expect(new Headers(init?.headers).get('Authorization')).toBe(`Bearer ${bootstrapToken}`)
      expect(JSON.parse(String(init?.body))).toEqual({ name: 'first-admin', kind: 'user', role: 'admin', environmentIds: [], unrestrictedEnvironments: true })
      return new Response(JSON.stringify({ accessToken: 'new-admin-access-token-1234567890' }), { status: 201, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)

    await setupApi.createInitialAdmin('first-admin', bootstrapToken)

    expect(getAlphaBearerToken()).toBeUndefined()
    expect(JSON.stringify({ ...window.sessionStorage })).not.toContain(bootstrapToken)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
