import { apiConfig } from './config'
import { invalidateSession, requestAuth } from '../auth/authSession'

interface ApiErrorBody {
  code?: string
  message?: string
  detail?: string | { msg?: string }
  requestId?: string
  error?: {
    code?: string
    message?: string
    details?: unknown
    request_id?: string
    trace_id?: string
  }
}

export interface ValidationIssue {
  location: (string | number)[]
  message: string
}

export interface PaginatedResult<T> {
  items: T[]
  totalCount: number
  limit: number
  offset: number
}

const apiErrorMessages: Record<string, string> = {
  INVALID_PLAN_DEPENDENCY: '计划步骤依赖无效，只能引用当前步骤之前的步骤序号。',
  DUPLICATE_PLAN_DEPENDENCY: '计划步骤不能重复依赖同一个前置步骤。',
  PLAN_STEP_DEPENDENCIES_UNMET: '前置步骤尚未完成，请先完成或跳过全部依赖步骤。',
  INVALID_EVIDENCE_ID: 'Evidence ID 格式无效，必须使用有效的 UUID。',
  PLAN_STEP_EVIDENCE_NOT_FOUND: '找不到关联 Evidence，或该 Evidence 不属于当前 Incident。',
  TASK_PLAN_STEP_REQUIRED: '当前 Incident 存在活动 Plan，创建 RunnerTask 时必须选择对应的 PlanStep。',
  PLAN_STEP_NOT_RUNNING: '只能为正在运行的 PlanStep 创建 RunnerTask。',
  ACTIVE_INVESTIGATION_RUN_EXISTS: '当前 Incident 已有运行中的 Agent 调查任务，请等待其结束后再创建新运行。',
  INVALID_INVESTIGATION_RUN_TRANSITION: '当前 Agent 调查运行状态不允许执行该操作。',
  INVESTIGATION_RUN_NOT_RUNNING: '当前 Agent 调查运行未处于 running 状态。',
  INVESTIGATION_RUN_VERSION_CONFLICT: 'Agent 调查运行版本已变化，请刷新最新状态后重试。',
  INVESTIGATION_GRAPH_VERSION_UNAVAILABLE: '当前 Agent 调查图版本不可用，请使用 graph-v1 或省略 graphVersion 使用后端默认值。',
  MODEL_REQUEST_BUDGET_EXHAUSTED: 'Agent 模型请求预算已耗尽，运行无法继续调用模型。',
  AGENT_MODEL_PROVIDER_ERROR: '模型 Provider 调用失败，请检查 Provider 配置、网络和服务状态。',
  AUTHENTICATION_REQUIRED: '登录会话不存在或已经失效，请重新登录。',
  INVALID_ACCESS_TOKEN: '用户 Token 无效、已撤销或已过期。',
  PERMISSION_DENIED: '权限不足：当前角色或 Environment 范围不允许执行此请求。',
  CSRF_VALIDATION_FAILED: '安全会话校验失败，请刷新会话后重试。',
  POLICY_RULE_VERSION_CONFLICT: 'Policy 规则已被其他管理员修改，请刷新规则后重新编辑。',
  APPROVAL_VERSION_CONFLICT: '审批已被其他决议人更新，请刷新审批后重试。',
  POLICY_REVALIDATION_FAILED: '当前 Policy 重新校验未通过，操作不能继续，请刷新授权数据并检查最新策略。',
  ACTION_IDEMPOTENCY_CONFLICT: '该幂等键已绑定另一组 Action 参数。网络重试请保留原请求；新操作请创建新的幂等键。',
  ACTION_AUTHORIZATION_ALREADY_CONSUMED: '该 Policy Decision 已创建过 Action，不能重复消费。请重新执行 Policy Evaluate 后创建新的 Action。',
  ACTION_APPROVAL_ALREADY_CONSUMED: '该 Approval 已创建过 Action，不能重复消费。请重新发起并完成审批后创建新的 Action。',
  APPROVAL_SELF_DECISION_FORBIDDEN: '申请人不能审批自己的申请，请由其他有权限的人员处理。',
  COMPENSATION_SELF_APPROVAL_FORBIDDEN: '补偿申请人不能审批自己的补偿请求，请由其他有权限的人员处理。',
  ACTION_PARAMETERS_CHANGED: 'Action 参数与授权或审批完成后的最终参数不一致，请刷新授权数据后重试。',
  RESOURCE_LOCK_CONFLICT: '该资源已被另一项 Action 持有活动锁，请等待锁释放后重试。',
  RESOURCE_LOCK_FENCED: 'Fencing Token 已过期，当前操作已被隔离，请刷新活动锁并使用服务端最新 Token。',
  RESOURCE_LOCK_EXPIRED: '资源锁租约已经到期，请刷新锁状态并重新获取锁。',
  RESOURCE_LOCK_MANUAL_CHANGE_FORBIDDEN: '当前 Action 状态禁止手动变更资源锁，已刷新 Action 与锁状态。',
  ACTION_ROLLBACK_CAPABILITY_UNSUPPORTED: '当前 Action 不支持该回滚能力；请移除回滚配置，失败后转人工升级。',
  ACTION_NOT_RECONCILABLE: '只有 unknown 状态的 Action 可以对账，其他状态不能执行 reconcile。',
  ACTION_VERSION_CONFLICT: 'Action 版本已变化，请刷新 Action 和 Execution 后再进行对账。',
  COMPENSATION_VERSION_CONFLICT: 'Compensation 版本已变化，请刷新补偿请求后重试。',
  COMPENSATION_NOT_REQUIRED: '当前 Action 不满足补偿条件，只有需要补偿的验证失败才能创建请求。',
  COMPENSATION_NOT_APPROVED: 'Compensation 尚未批准，不能派发执行。',
  COMPENSATION_NOT_ESCALATABLE: '当前 Compensation 状态不允许人工升级。',
  COMPENSATION_RESOURCE_LOCK_INVALID: '原 Action 的冻结资源锁或 Fencing Token 已变化，不能派发补偿。',
  LAB_DISABLED: 'Fault Lab 当前未启用。',
  LAB_CONTROLLER_UNAVAILABLE: 'Fault Lab 控制器暂时不可用，请检查本地 Lab 服务。',
  LAB_SCENARIO_NOT_FOUND: '指定的 Fault Lab 场景不存在。',
  LAB_SCENARIO_CONFLICT: '幂等键已绑定其他 Fault Lab 操作，请为新操作生成新的 key。',
  LAB_CONTROLLER_ERROR: 'Fault Lab 控制器拒绝了本次操作。',
  LAB_CONTROLLER_INVALID_RESPONSE: 'Fault Lab 控制器返回了无效响应。',
  BOOTSTRAP_ADMIN_REQUIRED: 'Bootstrap Token 只能创建首个拥有全部 Environment 权限的用户 Admin。',
  BOOTSTRAP_ALREADY_CONSUMED: '首次 Admin 初始化已经完成，请使用普通用户 Token 登录。',
  DEMO_DISABLED: '当前部署未启用 Demo 数据。',
  PRODUCTION_DISABLED: '生产环境禁止初始化或清理 Demo 数据。',
  DEMO_GENERATION_CONFLICT: 'Demo generation 已变化，已刷新最新状态，请重新确认后操作。',
  DEMO_DATA_DRIFT: 'Demo 受管数据与所有权清单不一致，请人工检查；前端不会强制清理。',
  INVALID_TIME_RANGE: '开始时间不能晚于结束时间，请调整审计筛选范围。',
  ENVIRONMENT_NOT_FOUND: '指定的 Environment 不存在，或当前账号无权访问。',
  PRINCIPAL_SELF_DEACTIVATION_FORBIDDEN: '不能停用当前登录的 Principal。请由其他 Admin 执行该操作。',
  LAST_UNRESTRICTED_ADMIN: '不能停用最后一个拥有全部 Environment 权限的 Admin。请先创建或授权另一名 Admin。',
}

export function apiErrorMessage(code: string | undefined, fallback: string): string {
  const localized = code ? apiErrorMessages[code] : undefined
  return localized && code ? `${localized}（${code}）` : fallback
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly requestId?: string,
    readonly serverMessage?: string,
    readonly traceId?: string,
    readonly validationIssues: ValidationIssue[] = [],
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  let body: ApiErrorBody | undefined
  try { body = await response.json() as ApiErrorBody } catch { body = undefined }
  const envelope = body?.error
  const code = envelope?.code ?? body?.code
  const serverMessage = envelope?.message ?? body?.message
  const validationIssues: ValidationIssue[] = response.status === 422 && Array.isArray(envelope?.details)
    ? envelope.details.flatMap((issue) => {
      if (!issue || typeof issue !== 'object') return []
      const value = issue as Record<string, unknown>
      if (!Array.isArray(value.location) || typeof value.message !== 'string') return []
      const location = value.location.filter((part): part is string | number => typeof part === 'string' || typeof part === 'number')
      return [{ location, message: value.message }]
    })
    : []
  const detail = typeof body?.detail === 'string' ? body.detail : body?.detail?.msg
  const validationMessage = validationIssues.length
    ? `请求参数校验失败：${validationIssues.map((issue) => `${issue.location.join('.')}：${issue.message}`).join('；')}`
    : undefined
  const fallback = validationMessage || serverMessage || detail || `请求失败：HTTP ${response.status}`
  return new ApiError(
    apiErrorMessage(code, fallback),
    response.status,
    code,
    response.headers.get('X-Request-ID') || envelope?.request_id || body?.requestId,
    serverMessage,
    envelope?.trace_id,
    validationIssues,
  )
}

async function apiFetch(path: string, init: RequestInit = {}) {
  const method = (init.method ?? 'GET').toUpperCase()
  const auth = requestAuth(path, method)
  const headers = new Headers(auth.headers)
  new Headers(init.headers).forEach((value, key) => headers.set(key, value))
  const response = await fetch(`${apiConfig.baseUrl}${path}`, {
    ...init,
    method,
    headers,
    credentials: auth.credentials,
  })
  if (!response.ok) {
    const error = await errorFromResponse(response)
    if (response.status === 401) invalidateSession()
    if (response.status === 403 && !error.code) {
      throw new ApiError('权限不足：当前角色或 Environment 范围不允许执行此请求。', 403, 'PERMISSION_DENIED')
    }
    throw error
  }
  return response
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await apiFetch(path, {
    headers: { Accept: 'application/json' },
    signal,
  })
  return response.json() as Promise<T>
}

function paginationHeader(response: Response, name: string): number {
  const value = response.headers.get(name)
  const parsed = value === null ? Number.NaN : Number(value)
  if (!Number.isInteger(parsed) || parsed < 0) throw new ApiError(`分页响应缺少有效的 ${name} Header。`, 500, 'INVALID_PAGINATION_RESPONSE')
  return parsed
}

export async function getPaginatedJson<T>(path: string, signal?: AbortSignal): Promise<PaginatedResult<T>> {
  const response = await apiFetch(path, { headers: { Accept: 'application/json' }, signal })
  return {
    items: await response.json() as T[],
    totalCount: paginationHeader(response, 'X-Total-Count'),
    limit: paginationHeader(response, 'X-Limit'),
    offset: paginationHeader(response, 'X-Offset'),
  }
}

export async function postJson<TBody, TResponse>(path: string, body: TBody, signal?: AbortSignal): Promise<TResponse> {
  const response = await apiFetch(path, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  return response.json() as Promise<TResponse>
}

export async function postJsonWithBearer<TBody, TResponse>(path: string, body: TBody, bearerToken: string, signal?: AbortSignal): Promise<TResponse> {
  const response = await apiFetch(path, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', Authorization: `Bearer ${bearerToken}` },
    body: JSON.stringify(body),
    signal,
  })
  return response.json() as Promise<TResponse>
}

export async function patchJson<TBody, TResponse>(path: string, body: TBody, signal?: AbortSignal): Promise<TResponse> {
  const response = await apiFetch(path, {
    method: 'PATCH',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  return response.json() as Promise<TResponse>
}

export async function putJson<TBody, TResponse>(path: string, body: TBody, signal?: AbortSignal): Promise<TResponse> {
  const response = await apiFetch(path, {
    method: 'PUT',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  return response.json() as Promise<TResponse>
}

export async function postJsonWithoutBody<TResponse>(path: string, signal?: AbortSignal): Promise<TResponse> {
  const response = await apiFetch(path, { method: 'POST', headers: { Accept: 'application/json' }, signal })
  return response.json() as Promise<TResponse>
}

export async function deleteJson(path: string, signal?: AbortSignal): Promise<void> {
  await apiFetch(path, { method: 'DELETE', headers: { Accept: 'application/json' }, signal })
}
