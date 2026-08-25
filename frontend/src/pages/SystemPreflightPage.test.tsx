import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SystemPreflightPage } from './SystemPreflightPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><SystemPreflightPage /></QueryClientProvider>)
}

describe('System Preflight page', () => {
  it('separates blocking action-required checks from warnings', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      status: 'action_required',
      checkedAt: '2026-08-20T08:00:00Z',
      checks: [
        { key: 'initial_admin', status: 'action_required', blocking: true, message: '需要创建初始 Admin' },
        { key: 'tls', status: 'warning', blocking: false, message: '建议启用 TLS' },
        { key: 'database', status: 'pass', blocking: false, message: '数据库连接正常' },
      ],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
    renderPage()

    expect(await screen.findByText('ACTION REQUIRED')).toBeInTheDocument()
    const blocking = screen.getByRole('heading', { name: '必须处理' }).closest('section') as HTMLElement
    const warning = screen.getByRole('heading', { name: '警告' }).closest('section') as HTMLElement
    expect(within(blocking).getByText('需要创建初始 Admin')).toBeInTheDocument()
    expect(within(blocking).queryByText('建议启用 TLS')).not.toBeInTheDocument()
    expect(within(warning).getByText('建议启用 TLS')).toBeInTheDocument()
    expect(screen.getByText('数据库连接正常')).toBeInTheDocument()
  })

  it('shows loading and request errors', async () => {
    let reject!: (reason: Error) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise((_resolve, rejectPromise) => { reject = rejectPromise })))
    renderPage()
    expect(screen.getByRole('status')).toHaveTextContent('执行系统 Preflight')
    reject(new Error('preflight offline'))
    expect(await screen.findByRole('alert')).toHaveTextContent('preflight offline')
  })

  it.each([
    ['ok', '连接正常', null, 'Model provider connectivity check succeeded'],
    ['failed', '连接失败', 'MODEL_TIMEOUT', 'Model provider did not respond before the diagnostic timeout'],
    ['disabled', 'Runtime 未启用', null, 'Agent runtime is disabled'],
    ['not_configured', 'Provider 未配置', null, 'Agent model provider is not configured'],
  ] as const)('shows the %s model connection result without sending model settings', async (status, label, errorCode, message) => {
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'POST') {
        expect(String(input)).toContain('/system/model-connection-check')
        expect(init?.body).toBeUndefined()
        const serialized = JSON.stringify(init)
        expect(serialized).not.toMatch(/apiKey|modelName|baseUrl|prompt/i)
        return new Response(JSON.stringify({
          status,
          provider: 'openai',
          runtimeEnabled: status !== 'disabled',
          connectivityChecked: status === 'ok' || status === 'failed',
          cached: status === 'ok',
          latencyMs: status === 'ok' || status === 'failed' ? 120 : null,
          errorCode,
          message,
          checkedAt: '2026-08-20T08:00:00Z',
        }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      return new Response(JSON.stringify({ status: 'ready', checkedAt: '2026-08-20T08:00:00Z', checks: [] }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '检查模型连接' }))

    expect(await screen.findByText(label)).toBeInTheDocument()
    expect(screen.getByText(message)).toBeInTheDocument()
    if (errorCode) expect(screen.getByText(errorCode)).toBeInTheDocument()
    if (status === 'ok') expect(screen.getByText('近期缓存结果')).toBeInTheDocument()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  })
})
