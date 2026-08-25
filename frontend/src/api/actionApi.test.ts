import { afterEach, describe, expect, it, vi } from 'vitest'
import { actionApi, actionIsFrozen, buildActionPath } from './actionApi'

afterEach(() => vi.unstubAllGlobals())

describe('Action API', () => {
  it('loads the server-owned Action capability catalog', async () => {
    const catalog = { contractVersion: '1.0', capabilities: [] }
    const fetchMock = vi.fn(async (url: string | URL | Request) => {
      expect(String(url)).toContain('/action-capabilities')
      return Response.json(catalog)
    })
    vi.stubGlobal('fetch', fetchMock)
    await expect(actionApi.capabilities()).resolves.toEqual(catalog)
  })
  it('builds Incident and status filters using the OpenAPI query names', () => {
    expect(buildActionPath({ incidentId: 'incident-1', status: 'cancelled', limit: 20, offset: 5 }))
      .toBe('/actions?incidentId=incident-1&status=cancelled&limit=20&offset=5')
  })

  it('creates an Action with its complete authorization and verification contract', async () => {
    const body = {
      policyDecisionId: 'policy-decision-1',
      approvalId: 'approval-1',
      parameters: { replicas: 2 },
      verificationCriteria: ['health endpoint returns 200', 'P95 below 500ms'],
      rollbackCapability: 'service.rollback',
      idempotencyKey: 'action-stable-key-1',
    }
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      expect(String(url)).toContain('/actions')
      expect(init?.method).toBe('POST')
      expect(JSON.parse(String(init?.body))).toEqual(body)
      return new Response(JSON.stringify({ action: {}, replayed: false }), { status: 201, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    await actionApi.create(body)
  })

  it('queries Execution, dispatches without exposing lock tokens and reconciles with Action version', async () => {
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(url), method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined })
      return new Response(JSON.stringify({ status: 'unknown', version: 2 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))
    await actionApi.execution('action-1')
    await actionApi.dispatch('action-1')
    await actionApi.reconcile('action-1', { expectedVersion: 6, outcome: 'failed', summary: 'target unchanged', errorCode: 'RECONCILED_NOT_APPLIED' })
    expect(calls).toEqual([
      { url: expect.stringContaining('/actions/action-1/execution'), method: 'GET', body: undefined },
      { url: expect.stringContaining('/actions/action-1/dispatch'), method: 'POST', body: undefined },
      { url: expect.stringContaining('/actions/action-1/reconcile'), method: 'POST', body: { expectedVersion: 6, outcome: 'failed', summary: 'target unchanged', errorCode: 'RECONCILED_NOT_APPLIED' } },
    ])
  })

  it('freezes controls whenever Action or Execution is unknown', () => {
    expect(actionIsFrozen('unknown', 'running')).toBe(true)
    expect(actionIsFrozen('running', 'unknown')).toBe(true)
    expect(actionIsFrozen('running', 'running')).toBe(false)
  })

  it('queries the Action Verification snapshot', async () => {
    const verification = {
      actionRequestId: 'action-1',
      status: 'failed',
      runnerTaskId: 'task-1',
      evidenceId: 'evidence-1',
      errorCode: 'VERIFY_FAILED',
      compensationRequired: true,
    }
    const fetchMock = vi.fn(async (url: string | URL | Request) => {
      expect(String(url)).toContain('/actions/action-1/verification')
      return new Response(JSON.stringify(verification), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    await expect(actionApi.verification('action-1')).resolves.toEqual(verification)
  })
})
