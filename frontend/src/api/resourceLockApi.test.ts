import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildResourceLockPath, resourceLockApi } from './resourceLockApi'

afterEach(() => vi.unstubAllGlobals())

describe('Resource Lock API', () => {
  it('builds the active lock list query', () => {
    expect(buildResourceLockPath({ limit: 50, offset: 10 })).toBe('/resource-locks?limit=50&offset=10')
  })

  it('lists sanitized active locks without exposing fencing tokens', async () => {
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      expect(String(url)).toContain('/resource-locks')
      expect(init?.method).toBe('GET')
      expect(init?.body).toBeUndefined()
      return new Response(JSON.stringify([{ id: 'lock-1', resourceId: 'resource-1' }]), { status: 200, headers: { 'Content-Type': 'application/json', 'X-Total-Count': '11', 'X-Limit': '100', 'X-Offset': '0' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    const result = await resourceLockApi.list()
    expect(result).toMatchObject({ totalCount: 11, limit: 100, offset: 0 })
    expect(result.items[0]).not.toHaveProperty('fencingToken')
  })
})
