import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState, type FormEvent } from 'react'
import type { AlertFilters } from '../api/alertApi'
import { alertsPageQuery } from '../api/queries'
import { ErrorPanel } from '../components/LoadingPanel'
import { PaginationControls } from '../components/PaginationControls'
import { SeverityBadge } from '../components/StatusBadge'
import type { AlertStatus } from '../domain/types'

interface FilterForm {
  status: '' | AlertStatus
  resourceId: string
  incidentId: string
}

const emptyFilters: FilterForm = { status: '', resourceId: '', incidentId: '' }
const uuidPattern = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}'

function toApiFilters(form: FilterForm): AlertFilters {
  return {
    status: form.status || undefined,
    resourceId: form.resourceId.trim() || undefined,
    incidentId: form.incidentId.trim() || undefined,
  }
}

function AlertStatusBadge({ status }: { status: AlertStatus }) {
  return <span className={`badge status-${status}`}>{status === 'firing' ? '告警中' : '已恢复'}</span>
}

export function AlertsPage() {
  const [draft, setDraft] = useState<FilterForm>(emptyFilters)
  const [filters, setFilters] = useState<AlertFilters>({})
  const [offset, setOffset] = useState(0)
  const query = useQuery({ ...alertsPageQuery({ ...filters, limit: 25, offset }), placeholderData: keepPreviousData })

  const applyFilters = (event: FormEvent) => {
    event.preventDefault()
    setOffset(0)
    setFilters(toApiFilters(draft))
  }
  const resetFilters = () => {
    setDraft(emptyFilters)
    setOffset(0)
    setFilters({})
  }

  if (query.error) return <ErrorPanel error={query.error} />
  const page = query.data
  const alerts = page?.items ?? []

  return <>
    <section className="page-heading"><div><span className="eyebrow">ALERTS</span><h1>告警列表</h1><p>查看 Alertmanager 告警、去重次数，以及与资源和 Incident 的关联关系。</p></div><span className="panel-note">{query.isFetching ? '正在刷新…' : `共 ${page?.totalCount ?? 0} 条`}</span></section>
    <form className="filter-bar alert-filter-bar" onSubmit={applyFilters}>
      <label>状态<select value={draft.status} onChange={(event) => setDraft((current) => ({ ...current, status: event.target.value as FilterForm['status'] }))}><option value="">全部状态</option><option value="firing">告警中</option><option value="resolved">已恢复</option></select></label>
      <label>资源 ID<input value={draft.resourceId} onChange={(event) => setDraft((current) => ({ ...current, resourceId: event.target.value }))} placeholder="Resource UUID" pattern={uuidPattern} title="请输入有效的 Resource UUID" /></label>
      <label>Incident ID<input value={draft.incidentId} onChange={(event) => setDraft((current) => ({ ...current, incidentId: event.target.value }))} placeholder="Incident UUID" pattern={uuidPattern} title="请输入有效的 Incident UUID" /></label>
      <div className="filter-actions"><button type="submit" className="filter-submit">应用筛选</button><button type="button" onClick={resetFilters}>重置</button></div>
    </form>
    <section className="panel"><div className="table-wrap"><table><thead><tr><th>告警</th><th>状态</th><th>级别</th><th>来源</th><th>出现次数</th><th>资源</th><th>Incident</th><th>最后收到</th></tr></thead><tbody>{alerts.length ? alerts.map((alert) => <tr key={alert.id}><td><strong>{alert.title}</strong><span className="table-subline" title={alert.fingerprint}>{alert.id}</span></td><td><AlertStatusBadge status={alert.status} /></td><td><SeverityBadge severity={alert.severity} /></td><td className="mono-cell">{alert.source}</td><td className="mono-cell">{alert.occurrenceCount}</td><td className="mono-cell">{alert.resourceId ?? '未匹配'}</td><td>{alert.incidentId ? <Link to="/incidents/$incidentId" params={{ incidentId: alert.incidentId }} className="mono-link">{alert.incidentId}</Link> : <span className="mono-cell">未关联</span>}</td><td className="mono-cell">{new Date(alert.lastSeenAt).toLocaleString('zh-CN', { hour12: false })}</td></tr>) : <tr><td colSpan={8} className="empty-table">没有符合当前条件的告警</td></tr>}</tbody></table></div></section>
    {page && <PaginationControls page={page} disabled={query.isFetching} onOffsetChange={setOffset} />}
  </>
}
