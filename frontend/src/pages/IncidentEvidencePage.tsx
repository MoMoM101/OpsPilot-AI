import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { assessEvidence, evidenceIsTruncated } from '../api/evidenceAssessment'
import { evidenceDetailQuery, incidentEvidenceQuery, incidentQuery } from '../api/queries'
import { ErrorPanel, LoadingPanel } from '../components/LoadingPanel'
import { PaginationControls } from '../components/PaginationControls'

const EVIDENCE_PAGE_SIZE = 50

function EvidenceWorkspace({ incidentId, initialEvidenceId }: { incidentId: string; initialEvidenceId?: string }) {
  const incident = useQuery(incidentQuery(incidentId))
  const [offset, setOffset] = useState(0)
  useEffect(() => setOffset(0), [incidentId])
  const list = useQuery({ ...incidentEvidenceQuery(incidentId, { limit: EVIDENCE_PAGE_SIZE, offset }), placeholderData: keepPreviousData })
  const [selectedId, setSelectedId] = useState(initialEvidenceId)

  useEffect(() => {
    if (initialEvidenceId) setSelectedId(initialEvidenceId)
  }, [initialEvidenceId])
  useEffect(() => {
    if (!selectedId && list.data?.items[0]) setSelectedId(list.data.items[0].id)
  }, [list.data, selectedId])

  const detail = useQuery({ ...evidenceDetailQuery(selectedId ?? ''), enabled: Boolean(selectedId) })
  if (incident.error) return <ErrorPanel error={incident.error} />
  if (list.error) return <ErrorPanel error={list.error} />
  if (incident.isPending || list.isPending) return <LoadingPanel label="加载 Incident Evidence" />

  const evidence = detail.data
  const assessment = evidence ? assessEvidence(evidence) : undefined
  const content = evidence?.data.content
  const metadata = evidence ? Object.fromEntries(Object.entries(evidence.data).filter(([key]) => key !== 'content')) : undefined

  return <>
    <div className="breadcrumb"><Link to="/incidents">Incident 列表</Link><span>/</span><Link to="/incidents/$incidentId" params={{ incidentId }}>Incident 详情</Link><span>/</span><span>Evidence</span></div>
    <section className="page-heading"><div><span className="eyebrow">INCIDENT EVIDENCE</span><h1>证据工作台</h1><p>{incident.data?.title} · {incident.data?.resource} · 共 {list.data?.totalCount ?? 0} 条不可变证据</p></div><button onClick={() => void list.refetch()} disabled={list.isFetching}>{list.isFetching ? '刷新中…' : '刷新证据'}</button></section>
    <section className="evidence-layout">
      <aside className="panel evidence-list"><div className="panel-heading"><h2>Incident Evidence</h2><span className="panel-note">COLLECTED DESC</span></div>{list.data?.items.length ? list.data.items.map((item) => <Link key={item.id} to="/incidents/$incidentId/evidence/$evidenceId" params={{ incidentId, evidenceId: item.id }} className={item.id === selectedId ? 'evidence-item evidence-selected' : 'evidence-item'} onClick={() => setSelectedId(item.id)}><div><span className={`evidence-collection evidence-${item.collectionStatus}`}>{item.collectionStatus}</span><small>{item.evidenceType}</small></div><strong>{item.summary}</strong><time>{new Date(item.collectedAt ?? item.createdAt).toLocaleString('zh-CN', { hour12: false })}</time><div className="evidence-flags">{evidenceIsTruncated(item) && <span>内容已截断</span>}{item.redacted && <span>敏感信息已脱敏</span>}</div></Link>) : <p className="inline-empty">当前 Incident 尚无 Evidence</p>}{list.data && <PaginationControls page={list.data} disabled={list.isFetching} onOffsetChange={(nextOffset) => { setSelectedId(undefined); setOffset(nextOffset) }} />}</aside>
      <section className="panel evidence-detail">
        <div className="panel-heading"><h2>Evidence 详情</h2>{evidence && <span className="panel-note">{evidence.id}</span>}</div>
        {detail.isFetching && !evidence ? <LoadingPanel label="加载 Evidence 详情" /> : detail.error ? <ErrorPanel error={detail.error} /> : evidence ? <div className="evidence-body">
          <div className={`evidence-assessment assessment-${assessment?.state}`}><span>目标判断</span><strong>{assessment?.label}</strong>{assessment?.detail && <small>{assessment.detail}</small>}<p>该结论来自 Evidence 数据，不由 RunnerTask succeeded 状态推断。</p></div>
          <div className="evidence-notices">{evidenceIsTruncated(evidence) && <strong className="notice-truncated">内容已截断</strong>}{evidence.redacted && <strong className="notice-redacted">敏感信息已脱敏</strong>}</div>
          <dl className="evidence-meta"><div><dt>采集状态</dt><dd>{evidence.collectionStatus}</dd></div><div><dt>时间可信度</dt><dd>{evidence.timeConfidence}</dd></div><div><dt>来源</dt><dd>{evidence.source}</dd></div><div><dt>资源 ID</dt><dd>{evidence.resourceId ?? '—'}</dd></div><div><dt>内容哈希</dt><dd>{evidence.contentHash}</dd></div><div><dt>采集时间</dt><dd>{new Date(evidence.collectedAt ?? evidence.createdAt).toLocaleString('zh-CN', { hour12: false })}</dd></div></dl>
          <div className="evidence-content"><div><span>Result Summary</span><p>{evidence.summary}</p></div><div><span>Normalized Data</span><pre>{JSON.stringify(metadata, null, 2)}</pre></div>{typeof content === 'string' && <div><span>Bounded Content</span><pre>{content}</pre></div>}</div>
        </div> : <p className="inline-empty">从左侧选择一条 Evidence</p>}
      </section>
    </section>
  </>
}

export function IncidentEvidencePage() {
  const { incidentId } = useParams({ from: '/incidents/$incidentId/evidence' })
  return <EvidenceWorkspace incidentId={incidentId} />
}

export function IncidentEvidenceDetailPage() {
  const { incidentId, evidenceId } = useParams({ from: '/incidents/$incidentId/evidence/$evidenceId' })
  return <EvidenceWorkspace incidentId={incidentId} initialEvidenceId={evidenceId} />
}
