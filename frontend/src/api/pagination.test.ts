import { afterEach, describe, expect, it, vi } from 'vitest'
import { actionApi } from './actionApi'
import { alertApi } from './alertApi'
import { approvalApi } from './approvalApi'
import { auditApi } from './auditApi'
import { incidentApi } from './incidentApi'

afterEach(() => vi.unstubAllGlobals())

describe('standard list pagination headers', () => {
  it('reads total, limit and offset headers for all five list APIs without changing array bodies', async () => {
    const fetchMock = vi.fn(async (_input: string | URL | Request, _init?: RequestInit) => new Response('[]', {
      status: 200,
      headers: { 'Content-Type': 'application/json', 'X-Total-Count': '77', 'X-Limit': '25', 'X-Offset': '50' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    const pages = await Promise.all([
      incidentApi.incidentPage({ limit: 25, offset: 50 }),
      alertApi.page({ limit: 25, offset: 50 }),
      approvalApi.page({ limit: 25, offset: 50 }),
      actionApi.page({ limit: 25, offset: 50 }),
      auditApi.list({ limit: 25, offset: 50 }),
    ])

    for (const page of pages) expect(page).toEqual({ items: [], totalCount: 77, limit: 25, offset: 50 })
    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual(expect.arrayContaining([
      expect.stringContaining('/incidents'), expect.stringContaining('/alerts'), expect.stringContaining('/approvals'), expect.stringContaining('/actions'), expect.stringContaining('/audit-logs'),
    ]))
  })
})
