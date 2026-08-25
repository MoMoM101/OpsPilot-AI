import type { components } from './generated/schema'
import { getJson, getPaginatedJson, type PaginatedResult } from './httpClient'

export type ConnectorCatalog = components['schemas']['ConnectorCatalogResponse']
export type ConnectorCatalogItem = components['schemas']['ConnectorCatalogItemResponse']
export type ConnectorAvailabilityStatus = components['schemas']['ConnectorAvailabilityResponse']['status']
export type EnvironmentSummary = components['schemas']['EnvironmentResponse']
export interface EnvironmentFilters { limit?: number; offset?: number }
export const ENVIRONMENT_PAGE_SIZE = 100

export function buildEnvironmentPath(filters: EnvironmentFilters = {}): string {
  const query = new URLSearchParams()
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.toString()
  return `/environments${suffix ? `?${suffix}` : ''}`
}

export function buildConnectorCatalogPath(environmentId?: string): string {
  const query = new URLSearchParams()
  if (environmentId) query.set('environmentId', environmentId)
  const suffix = query.toString()
  return `/connectors${suffix ? `?${suffix}` : ''}`
}

export const connectorApi = {
  catalog(environmentId?: string, signal?: AbortSignal): Promise<ConnectorCatalog> {
    return getJson<ConnectorCatalog>(buildConnectorCatalogPath(environmentId), signal)
  },

  environments(filters: EnvironmentFilters = {}, signal?: AbortSignal): Promise<PaginatedResult<EnvironmentSummary>> {
    return getPaginatedJson<EnvironmentSummary>(buildEnvironmentPath(filters), signal)
  },

  async allEnvironments(signal?: AbortSignal): Promise<EnvironmentSummary[]> {
    const firstPage = await getPaginatedJson<EnvironmentSummary>(buildEnvironmentPath({ limit: ENVIRONMENT_PAGE_SIZE, offset: 0 }), signal)
    const remainingOffsets: number[] = []
    for (let offset = ENVIRONMENT_PAGE_SIZE; offset < firstPage.totalCount; offset += ENVIRONMENT_PAGE_SIZE) remainingOffsets.push(offset)
    const remainingPages = await Promise.all(remainingOffsets.map((offset) =>
      getPaginatedJson<EnvironmentSummary>(buildEnvironmentPath({ limit: ENVIRONMENT_PAGE_SIZE, offset }), signal),
    ))
    return [firstPage, ...remainingPages].flatMap((page) => page.items)
  },
}
