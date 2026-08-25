import type { components } from './generated/schema'
import { getPaginatedJson, postJson, putJson, type PaginatedResult } from './httpClient'

export type PolicyRule = components['schemas']['PolicyRuleResponse']
export type PolicyRuleCreate = components['schemas']['PolicyRuleCreate']
export type PolicyRuleUpdate = components['schemas']['PolicyRuleUpdate']
export type PolicyDryRunRequest = components['schemas']['PolicyDryRunRequest']
export type PolicyDecision = components['schemas']['PolicyDecisionResponse']
export interface PolicyFilters { environmentId: string; limit?: number; offset?: number }

export function buildPolicyPath(filters: PolicyFilters): string {
  const query = new URLSearchParams({ environmentId: filters.environmentId })
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  return `/policies?${query}`
}

export const policyApi = {
  rules: (filters: PolicyFilters, signal?: AbortSignal): Promise<PaginatedResult<PolicyRule>> =>
    getPaginatedJson<PolicyRule>(buildPolicyPath(filters), signal),
  create: (body: PolicyRuleCreate, signal?: AbortSignal) =>
    postJson<PolicyRuleCreate, PolicyRule>('/policies', body, signal),
  update: (policyId: string, body: PolicyRuleUpdate, signal?: AbortSignal) =>
    putJson<PolicyRuleUpdate, PolicyRule>(`/policies/${encodeURIComponent(policyId)}`, body, signal),
  dryRun: (body: PolicyDryRunRequest, signal?: AbortSignal) =>
    postJson<PolicyDryRunRequest, PolicyDecision>('/policies/dry-run', body, signal),
}
