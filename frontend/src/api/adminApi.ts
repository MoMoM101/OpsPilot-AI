import type { components } from './generated/schema'
import { deleteJson, getJson, getPaginatedJson, postJson, postJsonWithoutBody, type PaginatedResult } from './httpClient'

export type Principal = components['schemas']['PrincipalResponse']
export type PrincipalCreate = components['schemas']['PrincipalCreate']
export type PrincipalCreateResponse = components['schemas']['PrincipalCreateResponse']
export type PrincipalTokenRotation = components['schemas']['PrincipalTokenRotateResponse']
export type OutboxStatus = components['schemas']['OutboxStatusResponse']
export type OutboxDeadLetter = components['schemas']['OutboxDeadLetterResponse']
export type OutboxReplay = components['schemas']['OutboxReplayResponse']
export interface AdminListFilters { limit?: number; offset?: number }

function queryPath(path: string, filters: { limit?: number; offset?: number } = {}) {
  const params = new URLSearchParams()
  if (filters.limit !== undefined) params.set('limit', String(filters.limit))
  if (filters.offset !== undefined) params.set('offset', String(filters.offset))
  return `${path}${params.size ? `?${params}` : ''}`
}

export const adminApi = {
  principals: (filters: AdminListFilters = {}, signal?: AbortSignal): Promise<PaginatedResult<Principal>> =>
    getPaginatedJson<Principal>(queryPath('/principals', filters), signal),
  createPrincipal: (body: PrincipalCreate, signal?: AbortSignal) =>
    postJson<PrincipalCreate, PrincipalCreateResponse>('/principals', body, signal),
  deactivatePrincipal: (principalId: string, signal?: AbortSignal) =>
    deleteJson(`/principals/${encodeURIComponent(principalId)}`, signal),
  rotatePrincipalToken: (principalId: string, signal?: AbortSignal) =>
    postJsonWithoutBody<PrincipalTokenRotation>(`/principals/${encodeURIComponent(principalId)}/rotate-token`, signal),
  outboxStatus: (signal?: AbortSignal) => getJson<OutboxStatus>('/outbox/status', signal),
  deadLetters: (filters: { limit?: number; offset?: number } = {}, signal?: AbortSignal) =>
    getPaginatedJson<OutboxDeadLetter>(queryPath('/outbox/dead-letters', filters), signal),
  replayDeadLetter: (eventId: string, signal?: AbortSignal) =>
    postJsonWithoutBody<OutboxReplay>(`/outbox/dead-letters/${encodeURIComponent(eventId)}/replay`, signal),
}
