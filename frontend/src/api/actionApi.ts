import type { components } from './generated/schema'
import { getJson, getPaginatedJson, postJson, postJsonWithoutBody, type PaginatedResult } from './httpClient'

export type ActionRequest = components['schemas']['ActionRequestResponse']
export type ActionStatus = components['schemas']['ActionRequestStatus']
export type ActionCreate = components['schemas']['ActionRequestCreate']
export type ActionCreateResponse = components['schemas']['ActionRequestCreateResponse']
export type ActionExecution = components['schemas']['ActionExecutionResponse']
export type ActionReconcileRequest = components['schemas']['ActionReconcileRequest']
export type ActionVerification = components['schemas']['ActionVerificationResponse']
export type ActionCapabilityCatalog = components['schemas']['ActionCapabilityCatalogResponse']
export type ActionCapability = components['schemas']['ActionCapabilityResponse']

export interface ActionFilters {
  incidentId?: string
  status?: ActionStatus
  limit?: number
  offset?: number
}

export function actionIsFrozen(actionStatus: ActionStatus, executionStatus?: ActionStatus): boolean {
  return actionStatus === 'unknown' || executionStatus === 'unknown'
}

export function buildActionPath(filters: ActionFilters = {}): string {
  const query = new URLSearchParams()
  if (filters.incidentId) query.set('incidentId', filters.incidentId)
  if (filters.status) query.set('status', filters.status)
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.toString()
  return `/actions${suffix ? `?${suffix}` : ''}`
}

export const actionApi = {
  capabilities(signal?: AbortSignal): Promise<ActionCapabilityCatalog> {
    return getJson<ActionCapabilityCatalog>('/action-capabilities', signal)
  },
  list(filters: ActionFilters = {}, signal?: AbortSignal): Promise<ActionRequest[]> {
    return getJson<ActionRequest[]>(buildActionPath(filters), signal)
  },
  page(filters: ActionFilters = {}, signal?: AbortSignal): Promise<PaginatedResult<ActionRequest>> {
    return getPaginatedJson<ActionRequest>(buildActionPath(filters), signal)
  },
  create(body: ActionCreate, signal?: AbortSignal): Promise<ActionCreateResponse> {
    return postJson<ActionCreate, ActionCreateResponse>('/actions', body, signal)
  },
  execution(actionId: string, signal?: AbortSignal): Promise<ActionExecution> {
    return getJson<ActionExecution>(`/actions/${actionId}/execution`, signal)
  },
  verification(actionId: string, signal?: AbortSignal): Promise<ActionVerification> {
    return getJson<ActionVerification>(`/actions/${actionId}/verification`, signal)
  },
  dispatch(actionId: string, signal?: AbortSignal): Promise<ActionExecution> {
    return postJsonWithoutBody<ActionExecution>(`/actions/${actionId}/dispatch`, signal)
  },
  reconcile(actionId: string, body: ActionReconcileRequest, signal?: AbortSignal): Promise<ActionExecution> {
    return postJson<ActionReconcileRequest, ActionExecution>(`/actions/${actionId}/reconcile`, body, signal)
  },
}
