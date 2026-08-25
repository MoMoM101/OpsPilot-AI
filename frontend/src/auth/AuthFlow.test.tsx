import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { router } from '../app/router'
import { AuthProvider } from './AuthContext'
import { clearClientCredentials } from './authSession'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); clearClientCredentials(); window.history.replaceState({}, '', '/') })

describe('authentication flow', () => {
  it('redirects an unauthenticated protected route to login', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'AUTHENTICATION_REQUIRED', message: 'login required' } }), { status: 401, headers: { 'Content-Type': 'application/json' } })))
    window.history.replaceState({}, '', '/incidents')
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(<QueryClientProvider client={queryClient}><AuthProvider><RouterProvider router={router} /></AuthProvider></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '登录运维控制台' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/login')
  })

  it('checks setup status and redirects to first-run initialization when required', async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith('/auth/me')) return new Response(JSON.stringify({ error: { code: 'AUTHENTICATION_REQUIRED', message: 'login required' } }), { status: 401, headers: { 'Content-Type': 'application/json' } })
      if (url.endsWith('/setup/status')) return new Response(JSON.stringify({ status: 'initialization_required', service: 'opspilot', version: '1.0', authenticationEnabled: true, initialAdminCreated: false, bootstrapAvailable: true }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState({}, '', '/incidents')
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(<QueryClientProvider client={queryClient}><AuthProvider><RouterProvider router={router} /></AuthProvider></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '初始化控制面' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/setup')
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/setup/status'))).toBe(true)
  })
})
