import type { Runner, RunnerStatus } from '../domain/types'
import type { RunnerDto } from './contracts'
import { getPaginatedJson, type PaginatedResult } from './httpClient'

export interface RunnerFilters {
  status?: RunnerStatus
  limit?: number
  offset?: number
}

export function buildRunnerPath(filters: RunnerFilters = {}): string {
  const query = new URLSearchParams()
  if (filters.status) query.set('status', filters.status)
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.toString()
  return `/runners${suffix ? `?${suffix}` : ''}`
}

export const runnerApi = {
  async runners(filters: RunnerFilters = {}, signal?: AbortSignal): Promise<PaginatedResult<Runner>> {
    return getPaginatedJson<RunnerDto>(buildRunnerPath(filters), signal)
  },
}
