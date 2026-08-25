import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildRunnerTaskPath, runnerTaskApi, type RunnerTaskCreate } from './runnerTaskApi'

afterEach(() => vi.unstubAllGlobals())

describe('RunnerTask API', () => {
  it('uses snake_case list filters', () => {
    const url = new URL(buildRunnerTaskPath({ status: 'succeeded', incidentId: 'incident-1', planStepId: 'step-1', runnerId: 'runner-1' }), 'http://localhost')
    expect(Object.fromEntries(url.searchParams)).toEqual({ status: 'succeeded', incident_id: 'incident-1', plan_step_id: 'step-1', runner_id: 'runner-1' })
  })

  it('reads the four-filter total from pagination headers', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { headers: { 'Content-Type': 'application/json', 'X-Total-Count': '81', 'X-Limit': '50', 'X-Offset': '50' } })))
    await expect(runnerTaskApi.tasks({ status: 'queued', incidentId: 'incident-1', runnerId: 'runner-1', planStepId: 'step-1', limit: 50, offset: 50 })).resolves.toEqual({ items: [], totalCount: 81, limit: 50, offset: 50 })
  })

  it('posts the bounded file query without Runner credentials', async () => {
    const body: RunnerTaskCreate = {
      incidentId: 'incident-1',
      planStepId: 'step-1',
      resourceId: 'resource-1',
      connector: 'file',
      operation: 'file.tail',
      parameters: { path: 'D:/logs/service.log', lines: 200 },
      idempotencyKey: 'bounded-file-tail-001',
    }
    const response = { id: 'task-1', ...body, runnerId: null, status: 'queued', timeoutSeconds: 30, maxAttempts: 1, attempt: 0, leaseExpiresAt: null, taskFencingToken: null, evidenceId: null, resultSummary: null, errorCode: null, outputTruncated: false, completedAt: null, createdAt: '2026-08-09T01:00:00Z', updatedAt: '2026-08-09T01:00:00Z' }
    const fetchMock = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      expect(init?.method).toBe('POST')
      expect(new Headers(init?.headers).has('Authorization')).toBe(false)
      expect(JSON.parse(String(init?.body))).toEqual(body)
      return new Response(JSON.stringify(response), { status: 201, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)

    const task = await runnerTaskApi.create(body)
    expect(task.status).toBe('queued')
    expect(task.planStepId).toBe('step-1')
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it.each([
    {
      connector: 'http' as const,
      operation: 'http.probe' as const,
      parameters: { url: 'http://api.internal.example:8000/health', method: 'GET' as const, expectedStatuses: [200, 204], captureBody: false },
      idempotencyKey: 'http-probe-unique-001',
    },
    {
      connector: 'tcp' as const,
      operation: 'tcp.probe' as const,
      parameters: { host: 'database.internal.example', port: 5432 },
      idempotencyKey: 'tcp-probe-unique-001',
    },
  ])('posts the $operation payload exactly as the control plane expects', async (probe) => {
    const body: RunnerTaskCreate = { incidentId: 'incident-1', resourceId: 'resource-1', ...probe }
    const response = { id: 'task-probe', ...body, runnerId: null, status: 'queued', timeoutSeconds: 30, maxAttempts: 1, attempt: 0, leaseExpiresAt: null, taskFencingToken: null, evidenceId: null, resultSummary: null, errorCode: null, outputTruncated: false, completedAt: null, createdAt: '2026-08-09T01:00:00Z', updatedAt: '2026-08-09T01:00:00Z' }
    const fetchMock = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toEqual(body)
      return new Response(JSON.stringify(response), { status: 201, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)

    const task = await runnerTaskApi.create(body)
    expect(task.operation).toBe(probe.operation)
  })

  it.each([
    {
      operation: 'prometheus.query' as const,
      parameters: { baseUrl: 'http://prometheus.internal.example:9090', query: 'up' },
      idempotencyKey: 'prometheus-instant-001',
    },
    {
      operation: 'prometheus.query_range' as const,
      parameters: { baseUrl: 'http://prometheus.internal.example:9090', query: 'rate(http_requests_total[5m])', start: '2026-08-09T00:00:00Z', end: '2026-08-09T01:00:00Z', stepSeconds: 60 },
      idempotencyKey: 'prometheus-range-001',
    },
  ])('posts the $operation request contract', async (item) => {
    const body: RunnerTaskCreate = { incidentId: 'incident-1', resourceId: 'resource-1', connector: 'prometheus', ...item }
    const response = { id: 'task-prometheus', ...body, runnerId: null, status: 'queued', timeoutSeconds: 30, maxAttempts: 1, attempt: 0, leaseExpiresAt: null, taskFencingToken: null, evidenceId: null, resultSummary: null, errorCode: null, outputTruncated: false, completedAt: null, createdAt: '2026-08-09T01:00:00Z', updatedAt: '2026-08-09T01:00:00Z' }
    const fetchMock = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toEqual(body)
      return new Response(JSON.stringify(response), { status: 201, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)

    expect((await runnerTaskApi.create(body)).operation).toBe(item.operation)
  })

  it('posts Host Snapshot with an empty parameters object', async () => {
    const body: RunnerTaskCreate = { incidentId: 'incident-1', resourceId: 'resource-1', connector: 'host', operation: 'host.snapshot', parameters: {}, idempotencyKey: 'host-snapshot-unique-001' }
    const response = { id: 'task-host', ...body, runnerId: null, status: 'queued', timeoutSeconds: 30, maxAttempts: 1, attempt: 0, leaseExpiresAt: null, taskFencingToken: null, evidenceId: null, resultSummary: null, errorCode: null, outputTruncated: false, completedAt: null, createdAt: '2026-08-09T01:00:00Z', updatedAt: '2026-08-09T01:00:00Z' }
    const fetchMock = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toEqual(body)
      return new Response(JSON.stringify(response), { status: 201, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)

    expect((await runnerTaskApi.create(body)).operation).toBe('host.snapshot')
  })
})
