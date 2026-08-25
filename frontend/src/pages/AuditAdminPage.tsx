import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { auditApi, type AuditFilters } from '../api/auditApi'
import { ErrorPanel, LoadingPanel } from '../components/LoadingPanel'
import { PaginationControls } from '../components/PaginationControls'

interface AuditFilterForm { actorId: string; action: string; outcome: string; from: string; to: string }
const emptyFilters: AuditFilterForm = { actorId: '', action: '', outcome: '', from: '', to: '' }

function isoDate(value: string): string | undefined {
  return value ? new Date(value).toISOString() : undefined
}

function toFilters(form: AuditFilterForm): AuditFilters {
  return {
    actorId: form.actorId.trim() || undefined,
    action: form.action.trim() || undefined,
    outcome: form.outcome || undefined,
    from: isoDate(form.from),
    to: isoDate(form.to),
  }
}

export function AuditAdminPage() {
  const [draft, setDraft] = useState<AuditFilterForm>(emptyFilters)
  const [filters, setFilters] = useState<AuditFilters>({})
  const [offset, setOffset] = useState(0)
  const query = useQuery({ queryKey: ['audit-logs', filters, offset], queryFn: ({ signal }) => auditApi.list({ ...filters, limit: 50, offset }, signal), placeholderData: keepPreviousData })

  const applyFilters = (event: FormEvent) => {
    event.preventDefault()
    setOffset(0)
    setFilters(toFilters(draft))
  }
  const resetFilters = () => {
    setDraft(emptyFilters)
    setOffset(0)
    setFilters({})
  }

  if (query.isPending) return <LoadingPanel label="加载审计日志" />
  if (query.error) return <ErrorPanel error={query.error} />

  return <>
    <section className="page-heading"><div><span className="eyebrow">ADMIN · AUDIT LOG</span><h1>日志与审计</h1><p>按 Actor、动作、结果和闭区间时间范围查询控制面安全审计记录。</p></div><span className="panel-note">{query.isFetching ? '正在查询…' : `共 ${query.data.totalCount} 条`}</span></section>
    <form className="filter-bar audit-filter-bar" onSubmit={applyFilters}>
      <label>Actor ID<input value={draft.actorId} maxLength={100} onChange={(event) => setDraft((current) => ({ ...current, actorId: event.target.value }))} placeholder="用户、服务或 anonymous" /></label>
      <label>Action<input value={draft.action} maxLength={100} onChange={(event) => setDraft((current) => ({ ...current, action: event.target.value }))} placeholder="例如 auth.session.create" /></label>
      <label>结果<select value={draft.outcome} onChange={(event) => setDraft((current) => ({ ...current, outcome: event.target.value }))}><option value="">全部</option><option value="success">success</option><option value="failure">failure</option></select></label>
      <label>开始时间<input type="datetime-local" value={draft.from} onChange={(event) => setDraft((current) => ({ ...current, from: event.target.value }))} /></label>
      <label>结束时间<input type="datetime-local" value={draft.to} onChange={(event) => setDraft((current) => ({ ...current, to: event.target.value }))} /></label>
      <div className="filter-actions"><button type="submit" className="filter-submit">应用筛选</button><button type="button" onClick={resetFilters}>重置</button></div>
    </form>
    <section className="panel"><div className="table-wrap"><table><thead><tr><th>时间</th><th>Actor</th><th>角色</th><th>动作</th><th>请求</th><th>结果</th><th>错误码</th><th>Request / Trace</th></tr></thead><tbody>{query.data.items.map((record) => <tr key={record.id}><td className="mono-cell">{new Date(record.occurredAt).toLocaleString('zh-CN', { hour12: false })}</td><td><strong>{record.actorId}</strong><span className="table-subline">{record.actorType}</span></td><td>{record.actorRole}</td><td className="mono-cell">{record.action ?? '—'}</td><td><span className="mono-cell">{record.method} {record.path}</span><span className="table-subline">HTTP {record.statusCode}</span></td><td><span className={`badge audit-${record.outcome ?? 'unknown'}`}>{record.outcome ?? '—'}</span></td><td className="mono-cell">{record.errorCode ?? '—'}</td><td><span className="mono-cell">{record.requestId ?? '—'}</span><span className="table-subline">{record.traceId ?? '—'}</span></td></tr>)}{!query.data.items.length && <tr><td colSpan={8} className="empty-table">没有符合当前筛选条件的审计记录</td></tr>}</tbody></table></div></section>
    <PaginationControls page={query.data} disabled={query.isFetching} onOffsetChange={setOffset} />
  </>
}
