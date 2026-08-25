import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useState, type FormEvent } from 'react'
import { approvalApi, type Approval, type ApprovalDecisionRequest, type ApprovalFilters, type ApprovalParameter, type ApprovalStatus } from '../api/approvalApi'
import { ApiError } from '../api/httpClient'
import { approvalsPageQuery } from '../api/queries'
import { ErrorPanel, LoadingPanel } from '../components/LoadingPanel'
import { PaginationControls } from '../components/PaginationControls'
import { useIncidentStreamTarget } from '../components/IncidentStreamContext'
import { useAuth } from '../auth/AuthContext'

const uuidPattern = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}'
const statuses: ApprovalStatus[] = ['pending', 'approved', 'rejected', 'expired']
const statusLabels: Record<ApprovalStatus, string> = { pending: '待审批', approved: '已批准', rejected: '已拒绝', expired: '已过期' }
const formatTime = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'

interface FilterForm { incidentId: string; status: '' | ApprovalStatus }
const emptyFilters: FilterForm = { incidentId: '', status: '' }

function editableValues(approval: Approval): Record<string, ApprovalParameter> {
  return Object.fromEntries(approval.editableParameterKeys.map((key) => [key, approval.parameters[key] ?? null]))
}

function ParameterInput({ name, value, onChange }: { name: string; value: ApprovalParameter; onChange: (value: ApprovalParameter) => void }) {
  if (typeof value === 'boolean') return <label className="check-field"><input type="checkbox" checked={value} onChange={(event) => onChange(event.target.checked)} />{name}</label>
  if (typeof value === 'number') return <label>{name}<input type="number" value={value} onChange={(event) => onChange(event.target.valueAsNumber)} /></label>
  return <label>{name}<input value={value ?? ''} onChange={(event) => onChange(event.target.value)} placeholder={value === null ? 'null（填写后将作为字符串）' : undefined} /></label>
}

export function isSelfApprovalDecision(approval: Pick<Approval, 'requestedBy'>, currentUserId?: string | null): boolean {
  return Boolean(currentUserId && approval.requestedBy === currentUserId)
}

function ApprovalDecisionForm({ approval, onResolved }: { approval: Approval; onResolved: () => void }) {
  const { user } = useAuth()
  const [parameterEdits, setParameterEdits] = useState(() => editableValues(approval))
  const mutation = useMutation({
    mutationFn: (body: ApprovalDecisionRequest) => approvalApi.decide(approval.id, body),
    onSuccess: onResolved,
    onError: (error) => {
      if (error instanceof ApiError && (error.code === 'APPROVAL_VERSION_CONFLICT' || error.code === 'POLICY_REVALIDATION_FAILED')) onResolved()
    },
  })
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    mutation.mutate({
      decision: String(form.get('decision')) as ApprovalDecisionRequest['decision'],
      comment: String(form.get('comment')).trim() || null,
      expectedVersion: approval.version,
      parameterEdits,
    })
  }
  if (approval.status !== 'pending') return <p className="inline-empty">该审批已结束，参数和决议不可再修改。</p>
  if (isSelfApprovalDecision(approval, user?.id)) return <p className="form-error" role="alert">申请人不能审批自己的申请。</p>
  return <form className="approval-decision-form" onSubmit={submit}>
    <div className="approval-editable"><h3>后端允许修改的参数</h3>{approval.editableParameterKeys.length ? approval.editableParameterKeys.map((key) => <ParameterInput key={key} name={key} value={parameterEdits[key]} onChange={(value) => setParameterEdits((current) => ({ ...current, [key]: value }))} />) : <p>本次审批不允许修改任何参数。</p>}</div>
    <label>审批决议<select name="decision" defaultValue="approve"><option value="approve">批准</option><option value="reject">拒绝</option></select></label>
    <label>评论<textarea name="comment" maxLength={2000} placeholder="填写决议依据或补充说明" /></label>
    <div className="panel-actions"><button type="submit" className="primary-button" disabled={mutation.isPending}>{mutation.isPending ? '提交中…' : `提交决议 · expectedVersion ${approval.version}`}</button></div>
    {mutation.error && <p className="form-error" role="alert">{mutation.error.message}</p>}
  </form>
}

export function ApprovalsPage() {
  const queryClient = useQueryClient()
  const { setRequestedIncidentId } = useIncidentStreamTarget()
  const [draft, setDraft] = useState<FilterForm>(emptyFilters)
  const [filters, setFilters] = useState<ApprovalFilters>({})
  const [offset, setOffset] = useState(0)
  const [selectedId, setSelectedId] = useState<string>()
  const query = useQuery({ ...approvalsPageQuery({ ...filters, limit: 25, offset }), placeholderData: keepPreviousData })
  const approvals = query.data?.items ?? []
  const selected = approvals.find((approval) => approval.id === selectedId) ?? approvals[0]
  const notFound = query.error instanceof ApiError && query.error.status === 404

  useEffect(() => { setRequestedIncidentId(filters.incidentId ?? selected?.incidentId); return () => setRequestedIncidentId(undefined) }, [filters.incidentId, selected?.incidentId, setRequestedIncidentId])
  useEffect(() => { if (!selectedId && approvals[0]) setSelectedId(approvals[0].id) }, [approvals, selectedId])
  useEffect(() => {
    if (!notFound) return
    setSelectedId(undefined)
    queryClient.removeQueries({ queryKey: ['approvals'] })
    queryClient.setQueryData(approvalsPageQuery({ ...filters, limit: 25, offset }).queryKey, { items: [], totalCount: 0, limit: 25, offset })
  }, [filters, notFound, offset, queryClient])

  const applyFilters = (event: FormEvent) => {
    event.preventDefault()
    const next = { incidentId: draft.incidentId.trim() || undefined, status: draft.status || undefined }
    setOffset(0)
    setFilters(next)
    setSelectedId(undefined)
  }
  const refresh = async () => { await queryClient.invalidateQueries({ queryKey: ['approvals'] }) }

  if (query.error) return <ErrorPanel error={query.error} />
  return <>
    <section className="page-heading"><div><span className="eyebrow">CONTROLLED APPROVAL</span><h1>Agent 决策审批</h1><p>审批状态和可编辑参数均以后端为准；决议使用乐观版本控制，并在提交时重新校验 Policy。</p></div><span className="panel-note">{query.isFetching ? '正在刷新…' : `共 ${query.data?.totalCount ?? 0} 条`}</span></section>
    <form className="filter-bar approval-filter-bar" onSubmit={applyFilters}>
      <label>Incident ID<input value={draft.incidentId} onChange={(event) => setDraft((current) => ({ ...current, incidentId: event.target.value }))} pattern={uuidPattern} placeholder="Incident UUID" /></label>
      <label>状态<select value={draft.status} onChange={(event) => setDraft((current) => ({ ...current, status: event.target.value as FilterForm['status'] }))}><option value="">全部状态</option>{statuses.map((status) => <option key={status} value={status}>{statusLabels[status]}</option>)}</select></label>
      <div className="filter-actions"><button type="submit" className="filter-submit">应用筛选</button><button type="button" onClick={() => { setDraft(emptyFilters); setFilters({}); setOffset(0); setSelectedId(undefined) }}>重置</button></div>
    </form>
    {query.isPending ? <LoadingPanel label="加载审批列表" /> : <section className="approval-layout">
      <div className="panel"><div className="table-wrap"><table><thead><tr><th>审批</th><th>状态</th><th>能力</th><th>申请人</th><th>过期时间</th></tr></thead><tbody>{approvals.map((approval) => <tr key={approval.id} className={approval.id === selected?.id ? 'selected-row' : undefined} onClick={() => setSelectedId(approval.id)}><td><strong>{approval.id}</strong><span className="table-subline"><Link to="/incidents/$incidentId" params={{ incidentId: approval.incidentId }}>{approval.incidentId}</Link> · v{approval.version}</span></td><td><span className={`badge approval-status-${approval.status}`}>{statusLabels[approval.status]}</span></td><td className="mono-cell">{approval.capability}</td><td>{approval.requestedBy}</td><td className="mono-cell">{formatTime(approval.expiresAt)}</td></tr>)}{!approvals.length && <tr><td colSpan={5} className="empty-table">没有符合当前条件的审批</td></tr>}</tbody></table></div></div>
      <aside className="panel approval-detail">{selected ? <><div className="panel-heading"><div><h2>审批详情</h2><p>{selected.id} · version {selected.version}</p></div><span className={`badge approval-status-${selected.status}`}>{statusLabels[selected.status]}</span></div><dl className="approval-meta"><div><dt>当前状态</dt><dd>{statusLabels[selected.status]}</dd></div><div><dt>过期时间</dt><dd>{formatTime(selected.expiresAt)}</dd></div><div><dt>申请人</dt><dd>{selected.requestedBy}</dd></div><div><dt>决议人</dt><dd>{selected.decidedBy ?? '—'}</dd></div><div><dt>决议时间</dt><dd>{formatTime(selected.decidedAt)}</dd></div><div><dt>评论</dt><dd>{selected.decisionComment ?? '—'}</dd></div></dl><div className="approval-parameters"><h3>请求参数</h3><pre>{JSON.stringify(selected.parameters, null, 2)}</pre></div><ApprovalDecisionForm key={`${selected.id}:${selected.version}`} approval={selected} onResolved={() => void refresh()} /></> : <p className="inline-empty">选择一条审批查看详情</p>}</aside>
    </section>}
    {query.data && <PaginationControls page={query.data} disabled={query.isFetching} onOffsetChange={(value) => { setOffset(value); setSelectedId(undefined) }} />}
  </>
}
