import type { components } from './generated/schema'
import { getPaginatedJson, type PaginatedResult } from './httpClient'

export type ResourceLock = components['schemas']['ResourceLockResponse']
export interface ResourceLockFilters { limit?: number; offset?: number }

export function buildResourceLockPath(filters: ResourceLockFilters = {}): string {
  const query = new URLSearchParams()
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.toString()
  return `/resource-locks${suffix ? `?${suffix}` : ''}`
}

export const resourceLockApi = {
  list(filters: ResourceLockFilters = {}, signal?: AbortSignal): Promise<PaginatedResult<ResourceLock>> {
    return getPaginatedJson<ResourceLock>(buildResourceLockPath(filters), signal)
  },
}
