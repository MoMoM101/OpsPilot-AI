import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildRunnerPath, runnerApi } from './runnerApi'

afterEach(() => vi.unstubAllGlobals())

describe('Runner API', () => {
  it('builds only the read-only list endpoint and supported filters', () => {
    const path = buildRunnerPath({ status: 'online', limit: 25, offset: 50 })
    const url = new URL(path, 'http://localhost')

    expect(url.pathname).toBe('/runners')
    expect(Object.fromEntries(url.searchParams)).toEqual({
      status: 'online',
      limit: '25',
      offset: '50',
    })
  })

  it('does not add credentials or registration parameters to the list URL', () => {
    expect(buildRunnerPath()).toBe('/runners')
    expect(buildRunnerPath()).not.toMatch(/token|register|heartbeat/i)
  })

  it('reads the filtered total from pagination headers', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { headers: { 'Content-Type': 'application/json', 'X-Total-Count': '73', 'X-Limit': '25', 'X-Offset': '50' } })))
    await expect(runnerApi.runners({ status: 'online', limit: 25, offset: 50 })).resolves.toEqual({ items: [], totalCount: 73, limit: 25, offset: 50 })
  })
})
