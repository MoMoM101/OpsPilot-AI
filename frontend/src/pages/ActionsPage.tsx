import { keepPreviousData, useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useState, type FormEvent } from 'react'
import { actionApi, actionIsFrozen, type ActionCapability, type ActionCreate, type ActionCreateResponse, type ActionFilters, type ActionReconcileRequest, type ActionRequest, type ActionStatus } from '../api/actionApi'
import { actionIdempotencyKey, replaceActionIdempotencyKey } from '../api/actionIdempotency'
import { dataApi } from '../api/dataApi'
import { actionCapabilitiesQuery, actionExecutionQuery, actionVerificationQuery, actionsPageQuery, approvalsQuery, compensationExecutionQuery, compensationsQuery, mockActionQuery, resourceLocksQuery } from '../api/queries'
import { ApiError } from '../api/httpClient'
import { compensationApi, type CompensationDecision, type CompensationEscalate, type CompensationStatus } from '../api/compensationApi'
import { useIncidentStreamTarget } from '../components/IncidentStreamContext'
import { ErrorPanel, LoadingPanel } from '../components/LoadingPanel'
import { ActionStatusBadge } from '../components/StatusBadge'
import { useAuth } from '../auth/AuthContext'
import { PaginationControls } from '../components/PaginationControls'

const uuidPattern = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}'
const uuidRegex = new RegExp(`^${uuidPattern}$`)
const statuses: ActionStatus[] = ['ready', 'dispatching', 'running', 'applied', 'verifying', 'succeeded', 'failed', 'verification_failed', 'compensating', 'compensated', 'escalated', 'unknown', 'cancelled']
const statusLabels: Record<ActionStatus, string> = { ready: '待执行', dispatching: '分发中', running: '执行中', applied: '已应用', verifying: '验证中', succeeded: '已成功', failed: '执行失败', verification_failed: '验证失败', compensating: '补偿中', compensated: '已补偿', escalated: '已升级人工', unknown: '状态未知', cancelled: '已取消' }
const compensationStatusLabels: Record<CompensationStatus, string> = { pending: '待审批', approved: '已批准', rejected: '已拒绝', dispatching: '派发中', running: '执行中', succeeded: '补偿成功', failed: '补偿失败', unknown: '结果未知', escalated: '已升级人工' }
const formatTime = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false })

const riskLabels: Record<ActionCapability['recommendedRisk'], string> = { read_only: '只读', low: '低', medium: '中', high: '高' }

export function actionParametersFromMetadata(capability: ActionCapability, rawValue: string): ActionCreate['parameters'] {
  const value = rawValue.trim()
  if (capability.parameter.required && !value) throw new Error(`${capability.parameter.key} 为必填参数。`)
  if (value && value.length < capability.parameter.minLength) throw new Error(`${capability.parameter.key} 长度不能少于 ${capability.parameter.minLength} 个字符。`)
  if (value.length > capability.parameter.maxLength) throw new Error(`${capability.parameter.key} 长度不能超过 ${capability.parameter.maxLength} 个字符。`)
  return value ? { [capability.parameter.key]: value } : {}
}

function CapabilityMetadata({ capability }: { capability: ActionCapability }) {
  const compensation = capability.compensation.supported
    ? `结构化补偿：${capability.compensation.capability ?? capability.compensation.mode}`
    : capability.compensation.mode === 'manual_escalation' ? '无确定性补偿，失败后人工升级' : capability.compensation.mode === 'not_applicable' ? '补偿不适用' : '当前不提供补偿能力'
  return <div className="span-two action-capability-metadata">
    <div><span>建议风险</span><strong>{riskLabels[capability.recommendedRisk]}</strong><small>仅作默认提示；是否需要审批及最终风险以 Policy Decision 为准。</small></div>
    <div><span>执行链路</span><strong>{capability.executionConnector ?? '未提供'}</strong><small>{capability.effect === 'mutation' ? '变更操作' : '观测操作'} · {capability.approvalMode}</small></div>
    <div><span>验证方式</span><strong>{capability.verification ? `${capability.verification.connector} / ${capability.verification.operation}` : '未提供自动验证映射'}</strong><small>该映射由后端调用 Runner，浏览器不会直接执行。</small></div>
    <div><span>失败处理</span><strong>{compensation}</strong><small>页面不接受自由格式 rollbackCapability。</small></div>
  </div>
}

export function consumedActionAuthorization(error: unknown): 'policy' | 'approval' | undefined {
  if (!(error instanceof ApiError)) return undefined
  if (error.code === 'ACTION_AUTHORIZATION_ALREADY_CONSUMED') return 'policy'
  if (error.code === 'ACTION_APPROVAL_ALREADY_CONSUMED') return 'approval'
  return undefined
}

function ActionExecutionPanel({ action }: { action: ActionRequest }) {
  const queryClient = useQueryClient()
  const execution = useQuery(actionExecutionQuery(action.id))
  const notDispatched = execution.error instanceof ApiError && execution.error.status === 404
  const frozen = actionIsFrozen(action.status, execution.data?.status)
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['actions'] }),
      queryClient.invalidateQueries({ queryKey: ['action-execution', action.id] }),
      queryClient.invalidateQueries({ queryKey: ['resource-locks'] }),
    ])
  }
  const dispatch = useMutation({
    mutationFn: () => actionApi.dispatch(action.id),
    onSuccess: async (value) => { queryClient.setQueryData(['action-execution', action.id], value); await refresh() },
  })
  const reconcile = useMutation({
    mutationFn: (body: ActionReconcileRequest) => actionApi.reconcile(action.id, body),
    onSuccess: async (value) => { queryClient.setQueryData(['action-execution', action.id], value); await refresh() },
  })
  const submitReconcile = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    reconcile.mutate({
      expectedVersion: action.version,
      outcome: String(form.get('outcome')) as ActionReconcileRequest['outcome'],
      summary: String(form.get('summary')).trim(),
      errorCode: String(form.get('errorCode')).trim() || null,
    })
  }
  const current = execution.data
  return <>
    <section className="action-execution">
      <div className="resource-lock-heading"><div><h3>Execution</h3><p>Runner 执行快照与租约状态</p></div>{current && <span className={`badge action-request-${current.status}`}>{statusLabels[current.status]}</span>}</div>
      {frozen && <div className="unknown-freeze" role="alert"><strong>UNKNOWN · 执行已冻结</strong><p>目标状态不确定，禁止重新派发、锁操作或直接改写结果。只能依据目标系统实际状态执行 reconcile，并落为 succeeded 或 failed。</p></div>}
      {execution.isPending ? <LoadingPanel label="加载 Execution" /> : notDispatched ? <div className="execution-empty"><p>当前 Action 尚未派发，没有 Execution 快照。</p><button type="button" className="primary-button" onClick={() => dispatch.mutate()} disabled={action.status !== 'ready' || dispatch.isPending}>{dispatch.isPending ? '派发中…' : '派发 Action'}</button><small>服务端将在同一事务中获取资源锁、选择 Runner 并创建 Execution。</small></div> : execution.error ? <p className="form-error" role="alert">{execution.error.message}</p> : current ? <dl className="execution-meta"><div><dt>执行状态</dt><dd>{statusLabels[current.status]}</dd></div><div><dt>租约到期</dt><dd>{current.leaseExpiresAt ? formatTime(current.leaseExpiresAt) : '—'}</dd></div><div><dt>开始时间</dt><dd>{current.startedAt ? formatTime(current.startedAt) : '—'}</dd></div><div><dt>结果摘要</dt><dd>{current.resultSummary ?? '—'}</dd></div><div><dt>错误码</dt><dd>{current.errorCode ?? '—'}</dd></div></dl> : null}
      {dispatch.error && <p className="form-error" role="alert">{dispatch.error.message}</p>}
    </section>
    {frozen && <form className="action-reconcile" onSubmit={submitReconcile}><div><h3>UNKNOWN 对账</h3><p>expectedVersion {action.version} · 只能确认 succeeded 或 failed</p></div><label>最终结果<select name="outcome" defaultValue="failed"><option value="succeeded">succeeded</option><option value="failed">failed</option></select></label><label>对账摘要<textarea name="summary" required minLength={1} maxLength={2000} /></label><label>错误码<input name="errorCode" maxLength={100} placeholder="failed 时建议填写" /></label><button type="submit" className="primary-button" disabled={reconcile.isPending}>{reconcile.isPending ? '对账中…' : '提交 reconcile'}</button>{reconcile.error && <p className="form-error" role="alert">{reconcile.error.message}</p>}</form>}
  </>
}

function ActionVerificationPanel({ action }: { action: ActionRequest }) {
  const verification = useQuery(actionVerificationQuery(action.id))
  const notCreated = verification.error instanceof ApiError && verification.error.status === 404
  if (verification.isPending) return <section className="action-verification-detail"><LoadingPanel label="加载 Verification" /></section>
  if (notCreated) return <section className="action-verification-detail"><div className="resource-lock-heading"><div><h3>Verification</h3><p>Action 应用后由控制面创建只读验证任务</p></div><span className="badge lock-inactive">NOT CREATED</span></div><p className="inline-empty">当前尚无 Verification 快照。</p></section>
  if (verification.error) return <section className="action-verification-detail"><div className="resource-lock-heading"><h3>Verification</h3></div><p className="form-error" role="alert">{verification.error.message}</p></section>
  const value = verification.data
  return <section className={`action-verification-detail verification-${value.status}`}><div className="resource-lock-heading"><div><h3>Verification</h3><p>{value.connector} · {value.operation} · version {value.version}</p></div><span className={`badge verification-status-${value.status}`}>{value.status}</span></div>{value.compensationRequired && <div className="compensation-warning" role="alert"><strong>需要补偿操作</strong><p>验证未通过且 Action 定义了回滚能力，请进入受控补偿流程，不要将执行成功误认为目标已恢复。</p></div>}<dl className="verification-detail-meta"><div><dt>验证状态</dt><dd>{value.status}</dd></div><div><dt>RunnerTask</dt><dd>{value.runnerTaskId ?? '—'}</dd></div><div><dt>Evidence</dt><dd>{value.evidenceId ? <Link to="/incidents/$incidentId/evidence/$evidenceId" params={{ incidentId: value.incidentId, evidenceId: value.evidenceId }}>{value.evidenceId}</Link> : '—'}</dd></div><div><dt>错误码</dt><dd>{value.errorCode ?? '—'}</dd></div><div><dt>结果摘要</dt><dd>{value.resultSummary ?? '—'}</dd></div><div><dt>Compensation</dt><dd>{value.compensationRequired ? 'REQUIRED' : '不需要'}</dd></div></dl><div className="verification-criteria-snapshot"><h4>验证标准快照</h4>{value.criteriaSnapshot.length ? <ol>{value.criteriaSnapshot.map((criterion, index) => <li key={`${index}:${criterion}`}>{criterion}</li>)}</ol> : <p>无验证标准</p>}</div></section>
}

function ActionCompensationPanel({ action }: { action: ActionRequest }) {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const verification = useQuery(actionVerificationQuery(action.id))
  const list = useQuery(compensationsQuery({ incidentId: action.incidentId, limit: 100, offset: 0 }))
  const compensation = list.data?.items.find((item) => item.actionRequestId === action.id)
  const execution = useQuery({ ...compensationExecutionQuery(compensation?.id ?? ''), enabled: Boolean(compensation), retry: false })
  const [idempotencyKey] = useState(() => `compensation-${action.id}-${crypto.randomUUID()}`)
  const refresh = async (id = compensation?.id) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['actions'] }),
      queryClient.invalidateQueries({ queryKey: ['compensations'] }),
      id ? queryClient.invalidateQueries({ queryKey: ['compensation-execution', id] }) : Promise.resolve(),
      queryClient.invalidateQueries({ queryKey: ['resource-locks'] }),
    ])
  }
  const create = useMutation({ mutationFn: () => compensationApi.create(action.id, { parameters: action.parameters, idempotencyKey, expiresInSeconds: 3600 }), onSuccess: async (value) => { await refresh(value.id) } })
  const decide = useMutation({ mutationFn: (body: CompensationDecision) => { if (!compensation) throw new Error('Compensation 请求不存在。'); return compensationApi.decide(compensation.id, body) }, onSuccess: async (value) => { await refresh(value.id) } })
  const dispatch = useMutation({ mutationFn: () => { if (!compensation) throw new Error('Compensation 请求不存在。'); return compensationApi.dispatch(compensation.id, { expectedVersion: compensation.version }) }, onSuccess: async (value) => { queryClient.setQueryData(['compensation-execution', value.compensationRequestId], value); await refresh(value.compensationRequestId) } })
  const escalate = useMutation({ mutationFn: (body: CompensationEscalate) => { if (!compensation) throw new Error('Compensation 请求不存在。'); return compensationApi.escalate(compensation.id, body) }, onSuccess: async (value) => { await refresh(value.id) } })
  const submitDecision = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!compensation) return
    const form = new FormData(event.currentTarget)
    decide.mutate({ decision: String(form.get('decision')) as CompensationDecision['decision'], expectedVersion: compensation.version, comment: String(form.get('comment')).trim() || null })
  }
  const submitEscalation = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!compensation) return
    escalate.mutate({ expectedVersion: compensation.version, reason: String(new FormData(event.currentTarget).get('reason')).trim() })
  }
  const canCreate = action.status === 'verification_failed' && verification.data?.compensationRequired === true && !compensation
  const canEscalate = compensation ? ['approved', 'rejected', 'failed', 'unknown'].includes(compensation.status) : false
  const isSelfDecision = Boolean(compensation && user?.id === compensation.requestedBy)
  const executionMissing = execution.error instanceof ApiError && execution.error.status === 404
  return <section className="compensation-panel"><div className="resource-lock-heading"><div><h3>Compensation</h3><p>补偿请求、人工审批、派发执行与升级接管</p></div><span className={`badge compensation-status-${compensation?.status ?? 'none'}`}>{compensation ? compensationStatusLabels[compensation.status] : 'NOT REQUESTED'}</span></div>
    {list.error ? <p className="form-error" role="alert">{list.error.message}</p> : !compensation ? <div className="compensation-empty"><p>{canCreate ? '验证已失败且后端要求补偿，可使用原 Action 最终参数创建补偿请求。' : '当前 Action 尚不满足补偿请求条件。'}</p><button type="button" className="danger-button" disabled={!canCreate || create.isPending} onClick={() => create.mutate()}>{create.isPending ? '创建中…' : '请求 Compensation'}</button><small>幂等键：{idempotencyKey}</small>{create.error && <p className="form-error" role="alert">{create.error.message}</p>}</div> : <>
      <dl className="compensation-meta"><div><dt>请求状态</dt><dd>{compensationStatusLabels[compensation.status]}</dd></div><div><dt>到期时间</dt><dd>{formatTime(compensation.expiresAt)}</dd></div><div><dt>申请人</dt><dd>{compensation.requestedBy}</dd></div><div><dt>决议人</dt><dd>{compensation.decidedBy ?? '—'}</dd></div><div><dt>决议评论</dt><dd>{compensation.decisionComment ?? '—'}</dd></div><div><dt>人工升级原因</dt><dd>{compensation.escalationReason ?? '—'}</dd></div><div><dt>补偿能力</dt><dd>{compensation.capability}</dd></div><div><dt>版本</dt><dd>{compensation.version}</dd></div></dl>
      {compensation.status === 'pending' && (isSelfDecision ? <p className="form-error compensation-decision" role="alert">申请人不能审批自己的 Compensation 请求。</p> : <form className="compensation-decision" onSubmit={submitDecision}><label>审批决定<select name="decision" defaultValue="approve"><option value="approve">批准</option><option value="reject">拒绝</option></select></label><label>评论<textarea name="comment" maxLength={2000} /></label><button type="submit" className="primary-button" disabled={decide.isPending}>{decide.isPending ? '提交中…' : '提交批准/拒绝'}</button>{decide.error && <p className="form-error" role="alert">{decide.error.message}</p>}</form>)}
      {compensation.status === 'approved' && <div className="compensation-dispatch"><button type="button" className="primary-button" disabled={dispatch.isPending} onClick={() => dispatch.mutate()}>{dispatch.isPending ? '派发中…' : '派发补偿'}</button><small>服务端将校验原 Action 的冻结资源锁并使用当前内部 Token。</small>{dispatch.error && <p className="form-error" role="alert">{dispatch.error.message}</p>}</div>}
      {execution.data ? <dl className="compensation-execution"><div><dt>执行状态</dt><dd>{compensationStatusLabels[execution.data.status]}</dd></div><div><dt>租约到期</dt><dd>{execution.data.leaseExpiresAt ? formatTime(execution.data.leaseExpiresAt) : '—'}</dd></div><div><dt>结果摘要</dt><dd>{execution.data.resultSummary ?? '—'}</dd></div><div><dt>错误码</dt><dd>{execution.data.errorCode ?? '—'}</dd></div></dl> : execution.isPending ? <LoadingPanel label="加载 Compensation Execution" /> : !executionMissing && execution.error ? <p className="form-error" role="alert">{execution.error.message}</p> : null}
      {canEscalate && <form className="compensation-escalate" onSubmit={submitEscalation}><label>人工升级原因<textarea name="reason" required minLength={1} maxLength={2000} /></label><button type="submit" className="danger-button" disabled={escalate.isPending}>{escalate.isPending ? '升级中…' : '升级为人工接管'}</button>{escalate.error && <p className="form-error" role="alert">{escalate.error.message}</p>}</form>}
    </>}
  </section>
}

function RealActionsPage() {
  const queryClient = useQueryClient()
  const { setRequestedIncidentId } = useIncidentStreamTarget()
  const [draftIncidentId, setDraftIncidentId] = useState('')
  const [draftStatus, setDraftStatus] = useState<'' | ActionStatus>('')
  const [filters, setFilters] = useState<ActionFilters>({})
  const [offset, setOffset] = useState(0)
  const [lockOffset, setLockOffset] = useState(0)
  const [selectedId, setSelectedId] = useState<string>()
  const [authorizationMode, setAuthorizationMode] = useState<'direct' | 'approval'>('direct')
  const [policyDecisionId, setPolicyDecisionId] = useState('')
  const [approvalIncidentId, setApprovalIncidentId] = useState('')
  const [approvalId, setApprovalId] = useState('')
  const [directCapability, setDirectCapability] = useState('')
  const [parameterValue, setParameterValue] = useState('')
  const [idempotencyKey, setIdempotencyKey] = useState(actionIdempotencyKey)
  const [createResult, setCreateResult] = useState<ActionCreateResponse>()
  const [formError, setFormError] = useState<string>()

  const actions = useQuery({ ...actionsPageQuery({ ...filters, limit: 25, offset }), placeholderData: keepPreviousData })
  const capabilityCatalog = useQuery(actionCapabilitiesQuery)
  const availableCapabilities = capabilityCatalog.data?.capabilities.filter((item) => item.availability === 'available') ?? []
  const reservedCapabilities = capabilityCatalog.data?.capabilities.filter((item) => item.availability === 'reserved') ?? []
  const actionItems = actions.data?.items ?? []
  const locks = useQuery({ ...resourceLocksQuery({ limit: 100, offset: lockOffset }), placeholderData: keepPreviousData })
  const approved = useQuery({ ...approvalsQuery({ incidentId: approvalIncidentId, status: 'approved' }), enabled: authorizationMode === 'approval' && uuidRegex.test(approvalIncidentId) })
  const approvedItems = (approved.data ?? []).filter((item) => availableCapabilities.some((capability) => capability.capability === item.capability))
  const selectedApproval = approvedItems.find((item) => item.id === approvalId)
  const authorizationApproval = authorizationMode === 'approval' ? selectedApproval : undefined
  const selectedCapability = authorizationMode === 'approval'
    ? availableCapabilities.find((item) => item.capability === authorizationApproval?.capability)
    : availableCapabilities.find((item) => item.capability === directCapability)
  const criteriaRequired = selectedCapability?.verificationCriteriaRequired ?? true
  const selected = actionItems.find((item) => item.id === selectedId) ?? (createResult && createResult.action.id === selectedId ? createResult.action : actionItems[0])

  useEffect(() => { setRequestedIncidentId(filters.incidentId ?? selected?.incidentId ?? (uuidRegex.test(approvalIncidentId) ? approvalIncidentId : undefined)); return () => setRequestedIncidentId(undefined) }, [approvalIncidentId, filters.incidentId, selected?.incidentId, setRequestedIncidentId])
  useEffect(() => {
    if (!availableCapabilities.length || availableCapabilities.some((item) => item.capability === directCapability)) return
    setDirectCapability(availableCapabilities[0].capability)
    setParameterValue('')
  }, [availableCapabilities, directCapability])

  const create = useMutation({
    mutationFn: (body: ActionCreate) => actionApi.create(body),
    onSuccess: async (result) => {
      setCreateResult(result)
      setSelectedId(result.action.id)
      setPolicyDecisionId('')
      setApprovalId('')
      setIdempotencyKey('')
      await queryClient.invalidateQueries({ queryKey: ['actions'] })
    },
    onError: (error) => {
      const consumed = consumedActionAuthorization(error)
      if (consumed === 'policy') setPolicyDecisionId('')
      if (consumed === 'approval') {
        setApprovalId('')
        void queryClient.invalidateQueries({ queryKey: ['approvals'] })
      }
      if (consumed) setIdempotencyKey('')
    },
  })

  const submitCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setFormError(undefined)
    const form = new FormData(event.currentTarget)
    try {
      const criteria = String(form.get('verificationCriteria')).split('\n').map((item) => item.trim()).filter(Boolean)
      if (!selectedCapability || selectedCapability.availability !== 'available') throw new Error('请选择当前可用的 Action 能力。')
      if (criteriaRequired && !criteria.length) throw new Error('该能力至少需要一条验证标准。')
      if (!idempotencyKey) throw new Error('该授权已提交或不可复用，请先准备新的授权并开始新的逻辑请求。')
      if (authorizationMode === 'approval' && !authorizationApproval) throw new Error('请选择一条已批准的审批。')
      const parameters = authorizationApproval?.parameters ?? actionParametersFromMetadata(selectedCapability, parameterValue)
      create.mutate({
        policyDecisionId: authorizationApproval?.policyDecisionId ?? policyDecisionId,
        approvalId: authorizationApproval?.id ?? null,
        parameters,
        verificationCriteria: criteria,
        idempotencyKey,
      })
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Action 请求格式无效。')
    }
  }

  const applyFilters = (event: FormEvent) => {
    event.preventDefault()
    setOffset(0)
    setFilters({ incidentId: draftIncidentId.trim() || undefined, status: draftStatus || undefined })
    setSelectedId(undefined)
  }

  const actionsNotFound = actions.error instanceof ApiError && actions.error.status === 404
  useEffect(() => {
    if (!actionsNotFound) return
    setSelectedId(undefined)
    setCreateResult(undefined)
    queryClient.removeQueries({ queryKey: ['actions'] })
    queryClient.setQueryData(actionsPageQuery({ ...filters, limit: 25, offset }).queryKey, { items: [], totalCount: 0, limit: 25, offset })
  }, [actionsNotFound, filters, offset, queryClient])

  if (actions.error) return <ErrorPanel error={actions.error} />
  return <>
    <section className="page-heading"><div><span className="eyebrow">CONTROLLED EXECUTION</span><h1>动作执行中心</h1><p>每个 Action 必须绑定正式 Policy 决策、能力要求的验证标准和稳定幂等键；需要审批时，只使用审批完成后的最终参数。</p></div><span className="panel-note">{actions.isFetching ? '正在刷新…' : `共 ${actions.data?.totalCount ?? 0} 条`}</span></section>
    <section className="action-create-grid">
      <form className="panel action-create-form" onSubmit={submitCreate}><div className="panel-heading"><div><h2>创建 Action</h2><p>网络重试复用当前幂等键，不会自动生成新键</p></div><span className="panel-note">SERVER AUTHORIZED</span></div>
        <div className="action-form-body">
          <fieldset className="span-two"><legend>授权来源</legend><label><input type="radio" checked={authorizationMode === 'direct'} onChange={() => { setAuthorizationMode('direct'); setApprovalId('') }} /> Policy 直接授权</label><label><input type="radio" checked={authorizationMode === 'approval'} onChange={() => { setAuthorizationMode('approval'); setPolicyDecisionId('') }} /> 已完成审批</label></fieldset>
          {capabilityCatalog.error && <p className="span-two form-error" role="alert">Action 能力目录加载失败：{capabilityCatalog.error.message}</p>}
          {authorizationMode === 'direct' ? <><label>Policy Decision UUID<input name="policyDecisionId" value={policyDecisionId} onChange={(event) => setPolicyDecisionId(event.target.value)} required pattern={uuidPattern} /></label><label>Action 能力<select aria-label="Action 能力" value={directCapability} onChange={(event) => { setDirectCapability(event.target.value); setParameterValue('') }} required disabled={capabilityCatalog.isPending || !availableCapabilities.length}><option value="">{capabilityCatalog.isPending ? '加载能力目录…' : '请选择可用能力'}</option>{availableCapabilities.map((capability) => <option value={capability.capability} key={capability.capability}>{capability.capability}</option>)}</select></label>{selectedCapability && <><label className="span-two">{selectedCapability.parameter.key}<input name={selectedCapability.parameter.key} type={selectedCapability.parameter.secret ? 'password' : 'text'} value={parameterValue} onChange={(event) => setParameterValue(event.target.value)} required={selectedCapability.parameter.required} minLength={selectedCapability.parameter.minLength} maxLength={selectedCapability.parameter.maxLength} autoComplete="off" /><small>字符串，长度 {selectedCapability.parameter.minLength}–{selectedCapability.parameter.maxLength}；参数不会写入前端遥测。</small></label><CapabilityMetadata capability={selectedCapability} /></>}</> : <><label>Incident UUID<input value={approvalIncidentId} onChange={(event) => { setApprovalIncidentId(event.target.value); setApprovalId('') }} required pattern={uuidPattern} placeholder="用于加载已批准审批" /></label><label>已批准审批<select value={approvalId} onChange={(event) => setApprovalId(event.target.value)} required disabled={!approvedItems.length}><option value="">{approved.isFetching ? '加载中…' : '请选择可用能力的审批'}</option>{approvedItems.map((approval) => <option value={approval.id} key={approval.id}>{approval.id} · {approval.capability} · v{approval.version}</option>)}</select></label><div className="span-two approval-final-parameters"><span>审批完成后的最终参数</span><pre>{selectedApproval ? JSON.stringify(selectedApproval.parameters, null, 2) : '请先输入有效 Incident UUID 并选择已批准审批'}</pre>{selectedApproval && <small>Policy Decision：{selectedApproval.policyDecisionId} · 能力：{selectedApproval.capability}</small>}</div>{selectedCapability && <CapabilityMetadata capability={selectedCapability} />}</>}
          {reservedCapabilities.length > 0 && <div className="span-two action-reserved-capabilities"><span>尚未提供</span><code>{reservedCapabilities.map((item) => item.capability).join(' · ')}</code><small>reserved 能力仅作目录说明，不能选择或提交。</small></div>}
          <label className="span-two">验证标准（每行一条）<textarea name="verificationCriteria" required={criteriaRequired} placeholder={criteriaRequired ? '该能力要求至少填写一条验证标准' : '可选；每行一条'} /></label>
          <div className="span-two idempotency-field"><span>幂等键</span><code>{idempotencyKey || '尚未开始新的逻辑请求'}</code><button type="button" onClick={() => { setIdempotencyKey(replaceActionIdempotencyKey()); setCreateResult(undefined); setFormError(undefined) }}>开始新的逻辑请求</button><small>只有创建全新 Action 意图时才更换；创建成功或授权已被消费后必须显式开始新请求。</small></div>
        </div><div className="panel-actions"><button className="primary-button" type="submit" disabled={create.isPending || !idempotencyKey || !selectedCapability}>{create.isPending ? '提交中…' : '提交 Action 请求'}</button></div>{(formError || create.error) && <p className="form-error" role="alert">{formError ?? create.error?.message}</p>}</form>
      <aside className="panel action-create-result"><div className="panel-heading"><h2>最近创建结果</h2></div>{createResult ? <div className="action-result-body"><span className={`replay-indicator ${createResult.replayed ? 'replayed' : ''}`}>{createResult.replayed ? 'REPLAYED · 幂等重放' : 'CREATED · 新建成功'}</span><strong>{createResult.action.id}</strong><p>{statusLabels[createResult.action.status]} · version {createResult.action.version}</p><button type="button" onClick={() => setSelectedId(createResult.action.id)}>查看 Action 快照</button></div> : <p className="inline-empty">提交后显示后端返回的 replayed 与 Action 状态。</p>}</aside>
    </section>
    <form className="filter-bar action-filter-bar" onSubmit={applyFilters}><label>Incident ID<input value={draftIncidentId} onChange={(event) => setDraftIncidentId(event.target.value)} pattern={uuidPattern} placeholder="Incident UUID" /></label><label>状态<select value={draftStatus} onChange={(event) => setDraftStatus(event.target.value as '' | ActionStatus)}><option value="">全部状态</option>{statuses.map((status) => <option value={status} key={status}>{statusLabels[status]}</option>)}</select></label><div className="filter-actions"><button type="submit" className="filter-submit">应用筛选</button><button type="button" onClick={() => { setDraftIncidentId(''); setDraftStatus(''); setFilters({}); setOffset(0); setSelectedId(undefined) }}>重置</button></div></form>
    {actions.isPending ? <LoadingPanel label="加载 Action 列表" /> : <section className="action-record-layout"><div className="panel"><div className="table-wrap"><table><thead><tr><th>Action</th><th>状态</th><th>能力</th><th>创建人</th><th>更新时间</th></tr></thead><tbody>{actionItems.map((action) => <tr key={action.id} className={action.id === selected?.id ? 'selected-row' : undefined} onClick={() => setSelectedId(action.id)}><td><strong>{action.id}</strong><span className="table-subline"><Link to="/incidents/$incidentId" params={{ incidentId: action.incidentId }}>{action.incidentId}</Link> · v{action.version}</span></td><td><span className={`badge action-request-${action.status}`}>{statusLabels[action.status]}</span></td><td className="mono-cell">{action.capability}</td><td>{action.createdBy}</td><td className="mono-cell">{formatTime(action.updatedAt)}</td></tr>)}{!actionItems.length && <tr><td colSpan={5} className="empty-table">没有符合当前条件的 Action</td></tr>}</tbody></table></div></div><aside className="panel action-record-detail">{selected ? <><div className="panel-heading"><div><h2>Action 快照</h2><p>{selected.id} · version {selected.version}</p></div><span className={`badge action-request-${selected.status}`}>{statusLabels[selected.status]}</span></div><dl className="action-record-meta"><div><dt>当前状态</dt><dd>{statusLabels[selected.status]}</dd></div><div><dt>取消原因</dt><dd>{selected.cancellationReason ?? '—'}</dd></div><div><dt>Policy Decision</dt><dd>{selected.policyDecisionId}</dd></div><div><dt>Approval</dt><dd>{selected.approvalId ?? '不需要审批'}</dd></div><div><dt>幂等键</dt><dd>{selected.idempotencyKey}</dd></div><div><dt>取消人</dt><dd>{selected.cancelledBy ?? '—'}</dd></div></dl><ActionExecutionPanel key={`execution:${selected.id}`} action={selected} /><ActionVerificationPanel key={`verification:${selected.id}`} action={selected} /><ActionCompensationPanel key={`compensation:${selected.id}`} action={selected} /><div className="action-verification-list"><h3>验证标准</h3>{selected.verificationCriteria.length ? <ol>{selected.verificationCriteria.map((criterion, index) => <li key={`${index}:${criterion}`}>{criterion}</li>)}</ol> : <p>未提供验证标准</p>}</div><div className="approval-parameters"><h3>最终 Action 参数</h3><pre>{JSON.stringify(selected.parameters, null, 2)}</pre></div></> : <p className="inline-empty">选择一条 Action 查看详情</p>}</aside></section>}
    {actions.data && <PaginationControls page={actions.data} disabled={actions.isFetching} onOffsetChange={(value) => { setOffset(value); setSelectedId(undefined) }} />}
    <section className="panel resource-lock-list"><div className="panel-heading"><div><h2>活动资源锁</h2><p>只读展示控制面当前执行占用；锁事件与定时刷新会同步更新列表和总数</p></div><span className="panel-note">{locks.isFetching ? '正在刷新…' : `${locks.data?.totalCount ?? 0} ACTIVE`}</span></div>{locks.error ? <p className="form-error" role="alert">{locks.error.message}</p> : <><div className="table-wrap"><table><thead><tr><th>资源</th><th>Action</th><th>Incident</th><th>获取时间</th><th>到期时间</th></tr></thead><tbody>{locks.data?.items.map((lock) => <tr key={lock.id}><td className="mono-cell">{lock.resourceId}</td><td><button type="button" className="table-select-button" onClick={() => { setDraftIncidentId(lock.incidentId); setFilters({ incidentId: lock.incidentId }); setSelectedId(lock.actionRequestId) }}>{lock.actionRequestId}</button></td><td><Link to="/incidents/$incidentId" params={{ incidentId: lock.incidentId }} className="mono-link">{lock.incidentId}</Link></td><td className="mono-cell">{formatTime(lock.acquiredAt)}</td><td className="mono-cell">{formatTime(lock.expiresAt)}</td></tr>)}{!locks.isPending && !locks.data?.items.length && <tr><td colSpan={5} className="empty-table">当前没有活动资源锁</td></tr>}</tbody></table></div>{locks.data && <PaginationControls page={locks.data} disabled={locks.isFetching} onOffsetChange={setLockOffset} />}</>}</section>
  </>
}

export function ActionsPage() {
  return dataApi.mode === 'http' ? <RealActionsPage /> : <MockActionsPage />
}

function MockActionsPage() {
  const { data } = useSuspenseQuery(mockActionQuery)
  const currentIndex = data.stages.indexOf(data.status)
  return <><section className="demo-banner" role="status"><strong>DEMO / MOCK</strong><span>以下执行状态仅用于界面演示，不代表真实环境。</span></section><section className="page-heading"><div><span className="eyebrow">CONTROLLED EXECUTION</span><h1>动作执行中心</h1><p>Mock 模式不具备真实执行能力。</p></div><ActionStatusBadge status={data.status} /></section><section className="panel"><div className="action-header"><div><span className="eyebrow">MOCK · {data.id}</span><h2>{data.title}</h2><p>{data.resource} · 演示数据</p></div><ActionStatusBadge status={data.status} /></div><div className="state-rail">{data.stages.map((stage, index) => <div className={`rail-stage ${index < currentIndex ? 'rail-done' : ''} ${index === currentIndex ? 'rail-current' : ''}`} key={stage}><i /><span>{stage}</span></div>)}</div></section></>
}
