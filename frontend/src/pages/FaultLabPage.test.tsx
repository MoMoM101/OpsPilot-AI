import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LabScenario } from '../api/labApi'
import { ApiError } from '../api/httpClient'
import { FaultLabPage } from './FaultLabPage'

const labMocks = vi.hoisted(() => ({
  list: vi.fn(),
  mutate: vi.fn(),
}))

vi.mock('../api/labApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api/labApi')>()
  return { ...original, labApi: labMocks }
})

const scenarios: LabScenario[] = [
  { id: 'redis_latency', title: 'Redis 延迟', description: '增加缓存访问延迟', status: 'ready', active: false, supported: true, version: 1 },
  { id: 'qdrant_down', title: 'Qdrant 停机', description: '暂停向量数据库', status: 'active', active: true, supported: true, version: 2 },
  { id: 'runner_loss', title: 'Runner 离线', description: '模拟执行节点离线', status: 'unavailable', active: false, supported: false, version: 1 },
  { id: 'api_latency', title: 'API 延迟', description: '增加 API 响应时间', status: 'ready', active: false, supported: true, version: 1 },
  { id: 'event_drop', title: '事件丢失', description: '模拟事件传递失败', status: 'ready', active: false, supported: true, version: 1 },
]

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><FaultLabPage /></QueryClientProvider>)
}

async function scenarioCard(title: string) {
  return (await screen.findByRole('heading', { name: title })).closest('article') as HTMLElement
}

beforeEach(() => {
  labMocks.list.mockReset().mockResolvedValue(scenarios)
  labMocks.mutate.mockReset()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('Fault Lab page', () => {
  it('shows the loading state and all five scenario states', async () => {
    let resolveList!: (value: LabScenario[]) => void
    labMocks.list.mockReturnValueOnce(new Promise((resolve) => { resolveList = resolve }))
    renderPage()

    expect(screen.getByRole('status')).toHaveTextContent('加载 Fault Lab 场景')
    resolveList(scenarios)

    expect(await screen.findByText('Redis 延迟')).toBeInTheDocument()
    expect(screen.getByText('Qdrant 停机')).toBeInTheDocument()
    expect(screen.getByText('Runner 离线')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()
    expect(within(await scenarioCard('Redis 延迟')).getByRole('button', { name: '注入故障' })).toBeEnabled()
    expect(within(await scenarioCard('Redis 延迟')).getByRole('button', { name: '清理故障' })).toBeDisabled()
    expect(within(await scenarioCard('Qdrant 停机')).getByRole('button', { name: '注入故障' })).toBeDisabled()
    expect(within(await scenarioCard('Qdrant 停机')).getByRole('button', { name: '清理故障' })).toBeEnabled()
    expect(within(await scenarioCard('Runner 离线')).getAllByRole('button').every((button) => button.hasAttribute('disabled'))).toBe(true)
  })

  it('confirms an operation and disables actions while it is running', async () => {
    let resolveMutation!: (value: { replayed: boolean; scenario: LabScenario }) => void
    labMocks.mutate.mockReturnValueOnce(new Promise((resolve) => { resolveMutation = resolve }))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue('11111111-1111-4111-8111-111111111111')
    renderPage()

    fireEvent.click(within(await scenarioCard('Redis 延迟')).getByRole('button', { name: '注入故障' }))
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Redis 延迟'))
    await waitFor(() => expect(labMocks.mutate).toHaveBeenCalledWith('redis_latency', 'inject', { idempotencyKey: 'fault-lab-inject-11111111-1111-4111-8111-111111111111' }))
    expect(screen.getAllByRole('button', { name: /注入故障|清理故障/ }).every((button) => button.hasAttribute('disabled'))).toBe(true)

    resolveMutation({ replayed: false, scenario: { ...scenarios[0], status: 'active', active: true, version: 2 } })
    expect(await screen.findByText(/注入故障已完成/)).toBeInTheDocument()
    await waitFor(() => expect(labMocks.list).toHaveBeenCalledTimes(2))
  })

  it('reuses the original idempotency key when retrying a failed request', async () => {
    const randomUUID = vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue('22222222-2222-4222-8222-222222222222')
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    labMocks.mutate
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce({ replayed: true, scenario: { ...scenarios[0], status: 'active', active: true, version: 2 } })
    renderPage()

    fireEvent.click(within(await scenarioCard('Redis 延迟')).getByRole('button', { name: '注入故障' }))
    fireEvent.click(await screen.findByRole('button', { name: '重试本次操作' }))

    await screen.findByText(/请求已幂等重放/)
    expect(labMocks.mutate).toHaveBeenCalledTimes(2)
    expect(labMocks.mutate.mock.calls[0]).toEqual(labMocks.mutate.mock.calls[1])
    expect(randomUUID).toHaveBeenCalledTimes(1)
    expect(screen.getByText('REPLAYED')).toBeInTheDocument()
  })

  it.each([
    [new ApiError('场景状态冲突', 409, 'LAB_SCENARIO_CONFLICT'), 'CONFLICT', false],
    [new ApiError('Lab 服务离线', 503, 'LAB_CONTROLLER_UNAVAILABLE'), 'CONTROLLER UNAVAILABLE', true],
  ])('shows operation feedback for %s', async (error, heading, retryable) => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue('33333333-3333-4333-8333-333333333333')
    labMocks.mutate.mockRejectedValueOnce(error)
    renderPage()

    fireEvent.click(within(await scenarioCard('Redis 延迟')).getByRole('button', { name: '注入故障' }))

    expect(await screen.findByText(heading)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重试本次操作' }) !== null).toBe(retryable)
    await waitFor(() => expect(labMocks.list).toHaveBeenCalledTimes(2))
  })

  it('renders a backend 403 as a permission error', async () => {
    labMocks.list.mockRejectedValueOnce(new ApiError('拒绝访问', 403, 'PERMISSION_DENIED'))
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('权限不足')
    expect(labMocks.mutate).not.toHaveBeenCalled()
  })
})
