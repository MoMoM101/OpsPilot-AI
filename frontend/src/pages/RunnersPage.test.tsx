import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RunnersPage } from './RunnersPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const availability = {
  status: 'ready', configuredRunnerCount: 1, compatibleRunnerCount: 1, incompatibleRunnerCount: 0, onlineRunnerCount: 1,
  readyObserveOperations: ['docker.inspect'], readyActionOperations: ['container.restart'],
}

function renderPage(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchMock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><RunnersPage /></QueryClientProvider>)
}

describe('Runners Connector wizard', () => {
  it('resets Runner offset when the status filter changes', async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname.endsWith('/runners')) return new Response('[]', { headers: { 'Content-Type': 'application/json', 'X-Total-Count': '51', 'X-Limit': '50', 'X-Offset': url.searchParams.get('offset') ?? '0' } })
      if (url.pathname.endsWith('/environments')) return new Response('[]', { headers: { 'Content-Type': 'application/json', 'X-Total-Count': '0', 'X-Limit': '100', 'X-Offset': '0' } })
      return Response.json({ environmentId: null, connectors: [] })
    })
    renderPage(fetchMock)

    fireEvent.click(await screen.findByRole('button', { name: '下一页' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => new URL(String(input), 'http://localhost').pathname.endsWith('/runners') && new URL(String(input), 'http://localhost').searchParams.get('offset') === '50')).toBe(true))
    fireEvent.change(screen.getByLabelText('状态筛选'), { target: { value: 'online' } })
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => {
      const url = new URL(String(input), 'http://localhost')
      return url.pathname.endsWith('/runners') && url.searchParams.get('status') === 'online' && url.searchParams.get('offset') === '0'
    })).toBe(true))
  })

  it('reloads the catalog on Environment changes and displays only online operation fields', async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname.endsWith('/runners')) return new Response('[]', { headers: { 'Content-Type': 'application/json', 'X-Total-Count': '0', 'X-Limit': '50', 'X-Offset': '0' } })
      if (url.pathname.endsWith('/environments')) return new Response(JSON.stringify([{ id: 'env-1', name: '生产环境', slug: 'prod', description: null, createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z' }]), { headers: { 'Content-Type': 'application/json', 'X-Total-Count': '1', 'X-Limit': '100', 'X-Offset': '0' } })
      return Response.json({ environmentId: url.searchParams.get('environmentId'), connectors: [{ connector: 'docker', contractVersion: '1.0', setupKind: 'allowlist', configurationOwner: 'runner', supportedPlatforms: ['linux'], prerequisites: [], runnerSettingKeys: ['DOCKER_HOST', 'DOCKER_ALLOWLIST'], observeOperations: ['must.not.render'], actionOperations: ['must.not.render.action'], availability }] })
    })
    renderPage(fetchMock)

    await screen.findByText('已就绪')
    const heading = screen.getByRole('heading', { name: 'Connector 配置向导' })
    const panel = heading.closest('section') as HTMLElement
    expect(within(panel).getByText('已就绪')).toBeInTheDocument()
    expect(within(panel).getByText('docker.inspect')).toBeInTheDocument()
    expect(within(panel).getByText('container.restart')).toBeInTheDocument()
    expect(within(panel).queryByText('must.not.render')).not.toBeInTheDocument()
    expect(within(panel).queryByText('must.not.render.action')).not.toBeInTheDocument()
    expect(within(panel).getByText('DOCKER_HOST')).toBeInTheDocument()
    expect(within(panel).queryByRole('textbox')).not.toBeInTheDocument()

    fireEvent.change(within(panel).getByLabelText('Environment'), { target: { value: 'env-1' } })
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => new URL(String(input), 'http://localhost').searchParams.get('environmentId') === 'env-1')).toBe(true))
  })

  it('renders all five fixed availability states', async () => {
    const statuses = ['ready', 'partial', 'offline', 'not_configured', 'incompatible'] as const
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname.endsWith('/runners') || url.pathname.endsWith('/environments')) return new Response('[]', { headers: { 'Content-Type': 'application/json', 'X-Total-Count': '0', 'X-Limit': url.pathname.endsWith('/runners') ? '50' : '100', 'X-Offset': '0' } })
      return Response.json({ environmentId: null, connectors: statuses.map((status) => ({ connector: status, contractVersion: '1.0', setupKind: 'built_in', configurationOwner: 'runner', supportedPlatforms: ['linux'], prerequisites: [], runnerSettingKeys: [], observeOperations: [], actionOperations: [], availability: { ...availability, status } })) })
    })
    renderPage(fetchMock)

    const heading = await screen.findByRole('heading', { name: 'Connector 配置向导' })
    const panel = heading.closest('section') as HTMLElement
    for (const label of ['已就绪', '部分就绪', '离线', '未配置', '版本不兼容']) expect(await within(panel).findByText(label)).toBeInTheDocument()
  })
})
