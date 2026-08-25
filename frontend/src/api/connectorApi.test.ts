import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildConnectorCatalogPath, buildEnvironmentPath, connectorApi } from './connectorApi'

afterEach(() => vi.unstubAllGlobals())

describe('Connector API', () => {
  it('reads Environment pagination headers', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { headers: { 'Content-Type': 'application/json', 'X-Total-Count': '61', 'X-Limit': '50', 'X-Offset': '50' } })))
    expect(buildEnvironmentPath({ limit: 50, offset: 50 })).toBe('/environments?limit=50&offset=50')
    await expect(connectorApi.environments({ limit: 50, offset: 50 })).resolves.toEqual({ items: [], totalCount: 61, limit: 50, offset: 50 })
  })
  it('uses the catalog endpoint and scopes by Environment', () => {
    expect(buildConnectorCatalogPath()).toBe('/connectors')
    expect(buildConnectorCatalogPath('env id')).toBe('/connectors?environmentId=env+id')
  })

  it('does not construct Runner settings or credential parameters', () => {
    expect(buildConnectorCatalogPath('env-1')).not.toMatch(/secret|token|address|setting/i)
  })
})
