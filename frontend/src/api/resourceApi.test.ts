import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildResourcePath, resourceApi } from './resourceApi'

afterEach(() => vi.unstubAllGlobals())

describe('Resource API', () => {
  it('uses offset pagination and reads the scoped total from headers', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { headers: { 'Content-Type': 'application/json', 'X-Total-Count': '66', 'X-Limit': '50', 'X-Offset': '50' } })))
    expect(buildResourcePath({ limit: 50, offset: 50 })).toBe('/resources?limit=50&offset=50')
    await expect(resourceApi.list({ limit: 50, offset: 50 })).resolves.toEqual({ items: [], totalCount: 66, limit: 50, offset: 50 })
  })
})
