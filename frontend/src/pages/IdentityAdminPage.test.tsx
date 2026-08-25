import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IdentityAdminPage } from './IdentityAdminPage'

vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 'principal-self', role: 'admin' } }) }))

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

const principal = (id: string, name: string) => ({ id, name, kind: 'user', role: 'admin', environmentIds: [], unrestrictedEnvironments: true, active: true, tokenIssuedAt: '2026-08-01T00:00:00Z', tokenExpiresAt: '2026-09-01T00:00:00Z', createdAt: '2026-08-01T00:00:00Z', updatedAt: '2026-08-01T00:00:00Z' })

function renderPage(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchMock)
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><IdentityAdminPage /></QueryClientProvider>)
}

describe('Identity Admin safety', () => {
  it('disables self rotation and self deactivation with explicit reasons', async () => {
    renderPage(vi.fn(async () => new Response(JSON.stringify([principal('principal-self', '当前 Admin'), principal('principal-other', '其他 Admin')]), { headers: { 'Content-Type': 'application/json', 'X-Total-Count': '2', 'X-Limit': '100', 'X-Offset': '0' } })))

    const row = (await screen.findByText('当前 Admin')).closest('tr') as HTMLElement
    expect(within(row).getByRole('button', { name: '轮换 Token' })).toBeDisabled()
    expect(within(row).getByRole('button', { name: '轮换 Token' })).toHaveAttribute('title', expect.stringContaining('当前登录用户'))
    expect(within(row).getByRole('button', { name: '停用' })).toBeDisabled()
    expect(within(row).getByRole('button', { name: '停用' })).toHaveAttribute('title', '当前登录用户不能停用自己。')
    expect(within(row).getByText('当前用户不可自轮换或自停用')).toBeInTheDocument()
  })

  it('keeps the one-time Token visible without refreshing old credentials until acknowledgement', async () => {
    let listRequests = 0
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname.endsWith('/principals') && (init?.method ?? 'GET') === 'GET') {
        listRequests += 1
        return new Response(JSON.stringify([principal('principal-self', '当前 Admin'), principal('principal-other', '其他 Admin')]), { headers: { 'Content-Type': 'application/json', 'X-Total-Count': '2', 'X-Limit': '100', 'X-Offset': '0' } })
      }
      if (url.pathname.endsWith('/rotate-token')) return Response.json({ principalId: 'principal-other', accessToken: 'one-time-secret', tokenIssuedAt: '2026-08-25T00:00:00Z', tokenExpiresAt: '2026-09-25T00:00:00Z' })
      throw new Error(`Unexpected ${url.pathname}`)
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPage(fetchMock)

    const otherRow = (await screen.findByText('其他 Admin')).closest('tr') as HTMLElement
    fireEvent.click(within(otherRow).getByRole('button', { name: '轮换 Token' }))
    expect(await screen.findByText('one-time-secret')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '请先保存 Token' })).toBeDisabled()
    expect(listRequests).toBe(1)

    fireEvent.click(screen.getByRole('button', { name: '我已安全保存并关闭' }))
    await waitFor(() => expect(listRequests).toBeGreaterThan(1))
    expect(screen.queryByText('one-time-secret')).not.toBeInTheDocument()
  })

  it('shows backend Admin safety conflicts and refreshes the Principal snapshot', async () => {
    let listRequests = 0
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = new URL(String(input), 'http://localhost')
      if ((init?.method ?? 'GET') === 'GET') {
        listRequests += 1
        return new Response(JSON.stringify([principal('principal-self', '当前 Admin'), principal('principal-other', '最后 Admin')]), { headers: { 'Content-Type': 'application/json', 'X-Total-Count': '2', 'X-Limit': '100', 'X-Offset': '0' } })
      }
      return new Response(JSON.stringify({ error: { code: 'LAST_UNRESTRICTED_ADMIN', message: 'last admin' } }), { status: 409, headers: { 'Content-Type': 'application/json' } })
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPage(fetchMock)

    const row = (await screen.findByText('最后 Admin')).closest('tr') as HTMLElement
    fireEvent.click(within(row).getByRole('button', { name: '停用' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('不能停用最后一个拥有全部 Environment 权限的 Admin')
    await waitFor(() => expect(listRequests).toBeGreaterThan(1))
  })
})
