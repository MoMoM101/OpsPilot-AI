import { describe, expect, it } from 'vitest'
import { actionParametersFromMetadata, consumedActionAuthorization } from './ActionsPage'
import type { ActionCapability } from '../api/actionApi'
import { isSelfApprovalDecision } from './ApprovalsPage'
import { ApiError } from '../api/httpClient'
import { policyAccessForRole } from './PoliciesPage'

describe('operator safety boundaries', () => {
  it('prevents an approval requester from deciding their own request', () => {
    expect(isSelfApprovalDecision({ requestedBy: 'principal-1' }, 'principal-1')).toBe(true)
    expect(isSelfApprovalDecision({ requestedBy: 'principal-1' }, 'principal-2')).toBe(false)
  })

  it('identifies consumed Policy Decisions and Approvals so the form cannot reuse them', () => {
    expect(consumedActionAuthorization(new ApiError('consumed', 409, 'ACTION_AUTHORIZATION_ALREADY_CONSUMED'))).toBe('policy')
    expect(consumedActionAuthorization(new ApiError('consumed', 409, 'ACTION_APPROVAL_ALREADY_CONSUMED'))).toBe('approval')
    expect(consumedActionAuthorization(new ApiError('conflict', 409, 'ACTION_IDEMPOTENCY_CONFLICT'))).toBeUndefined()
  })

  it('splits Policy read, Dry Run and management capabilities by role', () => {
    expect(policyAccessForRole('viewer')).toEqual({ canRead: true, canDryRun: false, canManage: false })
    expect(policyAccessForRole('operator')).toEqual({ canRead: true, canDryRun: true, canManage: false })
    expect(policyAccessForRole('admin')).toEqual({ canRead: true, canDryRun: true, canManage: true })
    expect(policyAccessForRole('runtime')).toEqual({ canRead: true, canDryRun: false, canManage: false })
  })

  it('builds Action parameters from server metadata instead of a local capability map', () => {
    const capability = { parameter: { key: 'serverOwnedKey', valueType: 'string', required: true, minLength: 2, maxLength: 12 } } as ActionCapability
    expect(actionParametersFromMetadata(capability, ' target-1 ')).toEqual({ serverOwnedKey: 'target-1' })
    expect(() => actionParametersFromMetadata(capability, '')).toThrow('serverOwnedKey 为必填参数')
    expect(() => actionParametersFromMetadata(capability, 'x')).toThrow('不能少于 2')
  })
})
