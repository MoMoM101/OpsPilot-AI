import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useState } from 'react'
import { allEnvironmentsQuery, filteredIncidentsPageQuery } from '../api/queries'
import { PaginationControls } from '../components/PaginationControls'
import { IncidentStatusBadge, ObservabilityBadge, SeverityBadge } from '../components/StatusBadge'
import type { IncidentStatus } from '../domain/types'

const statusOptions: Array<[IncidentStatus, string]> = [
  ['DETECTED', '已检测'], ['CORRELATING', '关联中'], ['INVESTIGATING', '调查中'], ['DIAGNOSED', '已诊断'],
  ['PLANNING', '计划中'], ['WAITING_APPROVAL', '待审批'], ['REMEDIATING', '修复中'], ['VERIFYING', '验证中'],
  ['RESOLVED', '已恢复'], ['CLOSED', '已关闭'], ['OBSERVABILITY_LOST', '观测能力丢失'], ['NEEDS_HUMAN', '需要人工'],
  ['MITIGATED_NOT_RESOLVED', '已缓解未恢复'], ['FAILED', '失败'], ['CANCELLED', '已取消'],
]

export function IncidentsPage() {
  const [offset, setOffset] = useState(0)
  const search = useSearch({ from: '/incidents' })
  const navigate = useNavigate({ from: '/incidents' })
  const { data: environments } = useSuspenseQuery(allEnvironmentsQuery)
  const { data, isFetching } = useSuspenseQuery(filteredIncidentsPageQuery({ status: search.status, environmentId: search.environment, q: search.q, limit: 25, offset }))
  const incidents = data.items
  const updateSearch = (patch: Partial<typeof search>) => { setOffset(0); void navigate({ search: (previous) => ({ ...previous, ...patch }), replace: true }) }

  return <>
    <section className="page-heading"><div><span className="eyebrow">INCIDENTS</span><h1>Incident 列表</h1><p>统一追踪检测、调查、审批、修复与恢复验证。</p></div></section>
    <section className="filter-bar" aria-label="Incident 筛选">
      <label>状态<select value={search.status ?? ''} onChange={(event) => updateSearch({ status: event.target.value as IncidentStatus || undefined })}><option value="">全部状态</option>{statusOptions.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      <label>环境<select value={search.environment ?? ''} onChange={(event) => updateSearch({ environment: event.target.value || undefined })}><option value="">全部环境</option>{search.environment && !environments.some((environment) => environment.id === search.environment) && <option value={search.environment}>{search.environment}</option>}{environments.map((environment) => <option value={environment.id} key={environment.id}>{environment.name} · {environment.slug}</option>)}</select></label>
      <label className="search-field">搜索<input value={search.q ?? ''} onChange={(event) => updateSearch({ q: event.target.value || undefined })} placeholder="Incident ID、标题、资源或负责人" /></label>
    </section>
    <section className="filter-summary"><span>当前页显示 {incidents.length} 条 · 服务端筛选共 {data.totalCount} 条</span>{(search.status || search.environment || search.q) && <button onClick={() => { setOffset(0); void navigate({ search: {}, replace: true }) }}>清除筛选</button>}</section>
    <section className="panel"><div className="table-wrap"><table><thead><tr><th>ID</th><th>标题</th><th>状态</th><th>观测</th><th>资源</th><th>环境</th><th>级别</th><th>负责人</th><th>更新时间</th></tr></thead><tbody>
      {incidents.map((incident) => <tr key={incident.id}><td><Link to="/incidents/$incidentId" params={{ incidentId: incident.id }} className="mono-link">{incident.id}</Link></td><td>{incident.title}</td><td><IncidentStatusBadge status={incident.status} /></td><td><ObservabilityBadge status={incident.observabilityStatus} /></td><td className="mono-cell">{incident.resource}</td><td>{incident.environment}</td><td><SeverityBadge severity={incident.severity} /></td><td>{incident.owner ?? '—'}</td><td className="mono-cell">{new Date(incident.updatedAt).toLocaleString('zh-CN', { hour12: false })}</td></tr>)}
      {incidents.length === 0 && <tr><td colSpan={9} className="empty-table">没有符合当前筛选条件的 Incident</td></tr>}
    </tbody></table></div></section>
    <PaginationControls page={data} disabled={isFetching} onOffsetChange={setOffset} />
  </>
}
