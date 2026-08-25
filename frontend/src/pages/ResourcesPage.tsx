import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { resourcesQuery } from '../api/queries'
import { ErrorPanel, LoadingPanel } from '../components/LoadingPanel'
import { PaginationControls } from '../components/PaginationControls'

export function ResourcesPage() {
  const [offset, setOffset] = useState(0)
  const query = useQuery({ ...resourcesQuery({ limit: 50, offset }), placeholderData: keepPreviousData })
  if (query.error) return <ErrorPanel error={query.error} />
  if (query.isPending) return <LoadingPanel label="加载资源列表" />

  return <>
    <section className="page-heading"><div><span className="eyebrow">RESOURCE INVENTORY</span><h1>资源拓扑</h1><p>查看当前授权 Environment Scope 内的资源清单。</p></div><span className="panel-note">共 {query.data.totalCount} 条</span></section>
    <section className="panel"><div className="table-wrap"><table><thead><tr><th>资源</th><th>类型</th><th>环境</th><th>关键级别</th><th>版本</th><th>更新时间</th></tr></thead><tbody>{query.data.items.map((resource) => <tr key={resource.id}><td><strong>{resource.name}</strong><span className="table-subline">{resource.id}</span></td><td className="mono-cell">{resource.kind}</td><td className="mono-cell">{resource.environmentId}</td><td>{resource.criticality}</td><td className="mono-cell">v{resource.version}</td><td className="mono-cell">{new Date(resource.updatedAt).toLocaleString('zh-CN', { hour12: false })}</td></tr>)}{!query.data.items.length && <tr><td colSpan={6} className="empty-table">当前授权范围内没有资源</td></tr>}</tbody></table></div><PaginationControls page={query.data} disabled={query.isFetching} onOffsetChange={setOffset} /></section>
  </>
}
