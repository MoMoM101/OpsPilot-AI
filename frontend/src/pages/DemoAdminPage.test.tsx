import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/httpClient'
import type { DemoStatus } from '../api/demoApi'
import { DemoAdminPage } from './DemoAdminPage'

const demoMocks = vi.hoisted(() => ({ status: vi.fn(), initialize: vi.fn(), cleanup: vi.fn() }))
vi.mock('../api/demoApi', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api/demoApi')>()), demoApi: demoMocks }))
vi.mock('@tanstack/react-router', () => ({
  Link: ({ children, to, params }: { children: React.ReactNode; to: string; params?: { incidentId?: string } }) => <a href={to.replace('$incidentId', params?.incidentId ?? '')}>{children}</a>,
}))

const baseStatus: DemoStatus = {
  available: true,
  reasonCode: null,
  status: 'active',
  manifestVersion: 1,
  generation: 2,
  environmentId: '019d0000-0000-7000-8000-000000000001',
  resourceIds: ['019d0000-0000-7000-8000-000000000002'],
  incidentIds: ['019d0000-0000-7000-8000-000000000003'],
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  render(<QueryClientProvider client={client}><DemoAdminPage /></QueryClientProvider>)
  return { client, invalidate }
}

beforeEach(() => {
  demoMocks.status.mockReset().mockResolvedValue(baseStatus)
  demoMocks.initialize.mockReset()
  demoMocks.cleanup.mockReset()
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('Demo Admin page', () => {
  it('shows drift as manual review only and exposes no cleanup or initialization action', async () => {
    demoMocks.status.mockResolvedValue({ ...baseStatus, status: 'drifted' })
    renderPage()

    expect(await screen.findByText('需要人工检查')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /清理 Demo|初始化 Demo|复用当前 Demo|强制清理/ })).not.toBeInTheDocument()
    expect(screen.getByText(/不会提供清理、强制清理或重新初始化/)).toBeInTheDocument()
  })

  it('refetches status and cleans up with the latest generation', async () => {
    const latest = { ...baseStatus, generation: 3 }
    demoMocks.status.mockResolvedValueOnce(baseStatus).mockResolvedValue(latest)
    demoMocks.cleanup.mockResolvedValue({ ...latest, status: 'inactive', incidentIds: [], replayed: false, deletedIncidentCount: 1 })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { invalidate } = renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '清理 Demo' }))

    await waitFor(() => expect(demoMocks.status).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(demoMocks.cleanup).toHaveBeenCalledWith(3))
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('generation 3'))
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['incidents'] })
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['dashboard'] })
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['resources'] })
    })
  })

  it('refreshes status after a generation conflict without retrying cleanup', async () => {
    demoMocks.cleanup.mockRejectedValue(new ApiError('generation changed', 409, 'DEMO_GENERATION_CONFLICT'))
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '清理 Demo' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('generation changed')
    expect(demoMocks.cleanup).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(demoMocks.status.mock.calls.length).toBeGreaterThanOrEqual(3))
  })

  it('shows replayed initialization data and Incident shortcuts while invalidating consumers', async () => {
    const inactive = { ...baseStatus, status: 'inactive' as const, incidentIds: [] }
    const initialized = { ...baseStatus, generation: 4, replayed: true }
    demoMocks.status.mockResolvedValueOnce(inactive).mockResolvedValue(initialized)
    demoMocks.initialize.mockResolvedValue(initialized)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { invalidate } = renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '初始化 Demo' }))

    expect(await screen.findByText(/直接复用现有数据/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Demo Incident 1/ })).toHaveAttribute('href', expect.stringContaining(initialized.incidentIds[0]))
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['incidents'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['dashboard'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['resources'] })
  })

  it('explains why Demo is unavailable without rendering write actions', async () => {
    demoMocks.status.mockResolvedValue({ ...baseStatus, available: false, status: 'unavailable', reasonCode: 'PRODUCTION_DISABLED' })
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('生产环境强制禁用')
    expect(screen.queryByRole('button', { name: /初始化 Demo|清理 Demo/ })).not.toBeInTheDocument()
  })
})
