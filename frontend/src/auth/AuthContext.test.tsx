import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from './AuthContext'
import { RequireRole } from '../components/AuthRoot'
import { clearClientCredentials } from './authSession'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); clearClientCredentials() })

describe('role-aware UI', () => {
  const renderWithQuery = (content: React.ReactNode) => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(<QueryClientProvider client={queryClient}><AuthProvider>{content}</AuthProvider></QueryClientProvider>)
  }

  it('does not expose operator write controls to Viewer', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      id: '019fdb57-c58c-7200-bae7-6dbb07bb34ad', name: 'viewer-one', kind: 'user', role: 'viewer', environmentIds: [], unrestrictedEnvironments: true,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

    renderWithQuery(<RequireRole role="operator"><button>执行写操作</button></RequireRole>)
    expect(await screen.findByText('当前角色无权访问此功能')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '执行写操作' })).not.toBeInTheDocument()
  })

  it('does not expose the Admin Fault Lab page to a Viewer', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      id: '019fdb57-c58c-7200-bae7-6dbb07bb34ad', name: 'viewer-one', kind: 'user', role: 'viewer', environmentIds: [], unrestrictedEnvironments: true,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

    renderWithQuery(<RequireRole role="admin"><button>Fault Lab 场景</button></RequireRole>)
    expect(await screen.findByText('当前角色无权访问此功能')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Fault Lab 场景' })).not.toBeInTheDocument()
    expect(screen.getByText(/该页面需要 admin 权限/)).toBeInTheDocument()
  })

  it('invalidates Dashboard data when the user Environment scope changes', async () => {
    const firstPrincipal = { id: '019fdb57-c58c-7200-bae7-6dbb07bb34ad', name: 'operator-one', kind: 'user', role: 'operator', environmentIds: ['env-1'], unrestrictedEnvironments: false }
    const secondPrincipal = { ...firstPrincipal, environmentIds: ['env-2'] }
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => String(input).endsWith('/auth/me')
      ? Response.json(firstPrincipal)
      : Response.json({ principal: secondPrincipal, csrfToken: 'csrf-next', expiresAt: '2026-08-22T00:00:00Z' })))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    function ScopeHarness() {
      const { user, refreshSession } = useAuth()
      return <><span>{user?.environmentIds.join(',') ?? 'loading'}</span><button type="button" onClick={() => void refreshSession()}>刷新授权</button></>
    }
    render(<QueryClientProvider client={queryClient}><AuthProvider><ScopeHarness /></AuthProvider></QueryClientProvider>)
    expect(await screen.findByText('env-1')).toBeInTheDocument()
    invalidate.mockClear()

    fireEvent.click(screen.getByRole('button', { name: '刷新授权' }))

    expect(await screen.findByText('env-2')).toBeInTheDocument()
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['dashboard'] }))
  })
})
