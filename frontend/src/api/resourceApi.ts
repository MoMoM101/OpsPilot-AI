import type { components } from './generated/schema'
import { getPaginatedJson, type PaginatedResult } from './httpClient'

export type ResourceSummary = components['schemas']['ResourceResponse']
export interface ResourceFilters { limit?: number; offset?: number }

export function buildResourcePath(filters: ResourceFilters = {}): string {
  const query = new URLSearchParams()
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.toString()
  return `/resources${suffix ? `?${suffix}` : ''}`
}

export const resourceApi = {
  list(filters: ResourceFilters = {}, signal?: AbortSignal): Promise<PaginatedResult<ResourceSummary>> {
    return getPaginatedJson<ResourceSummary>(buildResourcePath(filters), signal)
  },
}
