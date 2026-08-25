import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiErrorMessage, getJson, postJsonWithoutBody } from './httpClient'
import { requestAuth, setAlphaBearerToken, clearClientCredentials } from '../auth/authSession'

afterEach(() => { vi.unstubAllGlobals(); clearClientCredentials() })

describe('HTTP API errors', () => {
  it.each([
    ['INVALID_PLAN_DEPENDENCY', '计划步骤依赖无效'],
    ['DUPLICATE_PLAN_DEPENDENCY', '不能重复依赖'],
    ['PLAN_STEP_DEPENDENCIES_UNMET', '前置步骤尚未完成'],
    ['INVALID_EVIDENCE_ID', 'Evidence ID 格式无效'],
    ['PLAN_STEP_EVIDENCE_NOT_FOUND', '找不到关联 Evidence'],
    ['ACTIVE_INVESTIGATION_RUN_EXISTS', '已有运行中的 Agent 调查任务'],
    ['INVALID_INVESTIGATION_RUN_TRANSITION', '状态不允许'],
    ['INVESTIGATION_RUN_VERSION_CONFLICT', '版本已变化'],
    ['INVESTIGATION_GRAPH_VERSION_UNAVAILABLE', 'graph-v1'],
    ['MODEL_REQUEST_BUDGET_EXHAUSTED', '模型请求预算已耗尽'],
    ['AGENT_MODEL_PROVIDER_ERROR', '模型 Provider 调用失败'],
    ['POLICY_RULE_VERSION_CONFLICT', '刷新规则'],
    ['APPROVAL_VERSION_CONFLICT', '刷新审批'],
    ['POLICY_REVALIDATION_FAILED', '重新校验未通过'],
    ['ACTION_IDEMPOTENCY_CONFLICT', '幂等键'],
    ['ACTION_PARAMETERS_CHANGED', '最终参数'],
    ['RESOURCE_LOCK_CONFLICT', '活动锁'],
    ['RESOURCE_LOCK_FENCED', '最新 Token'],
    ['RESOURCE_LOCK_EXPIRED', '租约已经到期'],
    ['RESOURCE_LOCK_MANUAL_CHANGE_FORBIDDEN', '禁止手动变更资源锁'],
    ['ACTION_AUTHORIZATION_ALREADY_CONSUMED', '重新执行 Policy Evaluate'],
    ['ACTION_APPROVAL_ALREADY_CONSUMED', '重新发起并完成审批'],
    ['APPROVAL_SELF_DECISION_FORBIDDEN', '不能审批自己的申请'],
    ['COMPENSATION_SELF_APPROVAL_FORBIDDEN', '不能审批自己的补偿请求'],
    ['ACTION_ROLLBACK_CAPABILITY_UNSUPPORTED', '不支持该回滚能力'],
    ['ACTION_NOT_RECONCILABLE', '只有 unknown'],
    ['ACTION_VERSION_CONFLICT', 'Action 版本已变化'],
    ['COMPENSATION_VERSION_CONFLICT', 'Compensation 版本已变化'],
    ['COMPENSATION_NOT_REQUIRED', '不满足补偿条件'],
    ['COMPENSATION_NOT_APPROVED', '尚未批准'],
    ['COMPENSATION_NOT_ESCALATABLE', '不允许人工升级'],
    ['COMPENSATION_RESOURCE_LOCK_INVALID', '冻结资源锁'],
    ['BOOTSTRAP_ADMIN_REQUIRED', '首个'],
    ['BOOTSTRAP_ALREADY_CONSUMED', '初始化已经完成'],
    ['DEMO_GENERATION_CONFLICT', 'generation 已变化'],
    ['DEMO_DATA_DRIFT', '人工检查'],
    ['INVALID_TIME_RANGE', '开始时间不能晚于结束时间'],
    ['ENVIRONMENT_NOT_FOUND', '不存在，或当前账号无权访问'],
  ])('localizes %s while keeping the backend code visible', (code, message) => {
    const result = apiErrorMessage(code, 'backend fallback')
    expect(result).toContain(message)
    expect(result).toContain(code)
  })

  it('parses the backend nested error envelope', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      error: {
        code: 'PLAN_STEP_DEPENDENCIES_UNMET',
        message: 'Plan step dependencies are not complete: 1',
        request_id: 'request-1',
        trace_id: 'trace-1',
      },
    }), { status: 409, headers: { 'Content-Type': 'application/json' } })))

    const error = await getJson('/test').catch((reason: unknown) => reason)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 409,
      code: 'PLAN_STEP_DEPENDENCIES_UNMET',
      requestId: 'request-1',
      traceId: 'trace-1',
      serverMessage: 'Plan step dependencies are not complete: 1',
    })
    expect((error as ApiError).message).toContain('前置步骤尚未完成')
  })

  it('preserves the server message for unmapped errors', () => {
    expect(apiErrorMessage('SOME_NEW_ERROR', 'Server detail')).toBe('Server detail')
  })

  it('reads safe 422 location/message details and ignores legacy sensitive fields', async () => {
    const secret = 'do-not-echo-this-secret'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: {
      code: 'VALIDATION_ERROR', message: 'validation failed', details: [{
        type: 'string_too_short', location: ['body', 'accessToken'], message: '至少需要 20 个字符',
        input: secret, ctx: { min_length: 20 }, loc: ['legacy'], url: 'https://errors.example',
      }],
    } }), { status: 422, headers: { 'Content-Type': 'application/json' } })))

    const error = await getJson('/validation-test').catch((reason: unknown) => reason) as ApiError
    expect(error.validationIssues).toEqual([{ location: ['body', 'accessToken'], message: '至少需要 20 个字符' }])
    expect(error.message).toContain('body.accessToken：至少需要 20 个字符')
    expect(error.message).not.toContain(secret)
    expect(JSON.stringify(error.validationIssues)).not.toMatch(/input|ctx|loc\"|url/)
  })

  it('clears the client session after 401', async () => {
    setAlphaBearerToken('expired-user-token-1234567890')
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'INVALID_ACCESS_TOKEN', message: 'expired' } }), { status: 401, headers: { 'Content-Type': 'application/json' } })))
    await expect(getJson('/dashboard')).rejects.toMatchObject({ status: 401 })
    expect(requestAuth('/dashboard', 'GET').headers.has('Authorization')).toBe(false)
  })

  it('returns a clear permission message after 403', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'PERMISSION_DENIED', message: 'denied' } }), { status: 403, headers: { 'Content-Type': 'application/json' } })))
    await expect(getJson('/dashboard')).rejects.toMatchObject({ status: 403, message: expect.stringContaining('权限不足') })
  })

  it('always includes Session cookies and adds CSRF to cookie-authenticated writes', async () => {
    document.cookie = 'opspilot_csrf=csrf-for-write; path=/'
    const fetchMock = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      expect(init?.credentials).toBe('include')
      expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe('csrf-for-write')
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    await postJsonWithoutBody('/auth/session/refresh')
  })
})
