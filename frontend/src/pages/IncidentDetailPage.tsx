import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import { incidentQuery, incidentTimelinePageQuery, INCIDENT_TIMELINE_PAGE_SIZE } from '../api/queries'
import { IncidentStatusBadge, ObservabilityBadge, SeverityBadge } from '../components/StatusBadge'
import { HypothesisPanel } from '../components/HypothesisPanel'
import { InvestigationRunPanel } from '../components/InvestigationRunPanel'
import { ActionProposalPanel } from '../components/ActionProposalPanel'
import { useAuth } from '../auth/AuthContext'
import { useEffect, useState } from 'react'
import type { IncidentDetail } from '../domain/types'
import { PaginationControls } from '../components/PaginationControls'

const stepMark = (status: string, ordinal: number) => {
  if (status === 'completed') return '✓'
  if (status === 'failed') return '!'
  if (status === 'skipped') return '—'
  return ordinal
}

export function IncidentTimelinePanel({ incident }: { incident: Pick<IncidentDetail, 'id' | 'timeline' | 'timelineTotal' | 'timelineTruncated'> }) {
  const [offset, setOffset] = useState(0)
  useEffect(() => setOffset(0), [incident.id])
  const firstPage = useQuery({
    ...incidentTimelinePageQuery(incident.id, { limit: INCIDENT_TIMELINE_PAGE_SIZE, offset: 0 }),
    enabled: incident.timelineTruncated,
  })
  const olderPage = useQuery({
    ...incidentTimelinePageQuery(incident.id, { limit: INCIDENT_TIMELINE_PAGE_SIZE, offset }),
    enabled: incident.timelineTruncated && offset > 0,
  })
  const currentPage = offset === 0 ? firstPage : olderPage
  const events = incident.timelineTruncated ? currentPage.data?.items ?? (offset === 0 ? incident.timeline : []) : incident.timeline
  const totalCount = firstPage.data?.totalCount ?? incident.timelineTotal
  const page = currentPage.data ? { ...currentPage.data, totalCount } : undefined

  return <div className="panel">
    <div className="panel-heading"><div><h2>Agent 决策与执行流</h2><p>{incident.timelineTruncated ? '长期事件已分页，最新事件在前' : '完整时间线快照'}</p></div><span className="panel-note">{totalCount} EVENTS</span></div>
    {currentPage.error && <p className="form-error timeline-error" role="alert">Timeline 加载失败：{currentPage.error.message}</p>}
    <div className="timeline">{currentPage.isPending && offset > 0 ? <p className="inline-empty">正在加载更早事件…</p> : events.length ? events.map((event) => <article className={`timeline-item timeline-${event.type}`} key={event.id}><time>{event.occurredAt}</time><i /><div><strong>{event.title}</strong><p>{event.detail}</p></div></article>) : <p className="inline-empty">暂无时间线事件</p>}</div>
    {incident.timelineTruncated && page && <PaginationControls page={page} disabled={currentPage.isFetching} onOffsetChange={setOffset} />}
  </div>
}

export function IncidentDetailPage() {
  const { incidentId } = useParams({ from: '/incidents/$incidentId' })
  const { data } = useSuspenseQuery(incidentQuery(incidentId))
  const { canWrite } = useAuth()
  const activeStep = data.steps.find((step) => step.status === 'running')
  const progressedSteps = data.steps.filter((step) => step.status === 'completed' || step.status === 'skipped').length
  const agentStage = activeStep ? 'TOOL_RUNNING' : data.steps.length ? 'PLAN_IDLE' : 'NO_PLAN'

  return <>
    <div className="breadcrumb"><Link to="/incidents">Incident 列表</Link><span>/</span><span>{data.id}</span></div>
    <section className="incident-title">
      <div>
        <div className="badge-row"><span className="mono-link">{data.id}</span><SeverityBadge severity={data.severity} /><IncidentStatusBadge status={data.status} /></div>
        <h1>{data.title}</h1>
        <p>{data.resource} · {data.environment} 环境 · 负责人 {data.owner ?? '未分配'} · trace {data.traceId.slice(0, 8)}…</p>
      </div>
      <div className="button-row"><Link className="primary-button" to="/incidents/$incidentId/evidence" params={{ incidentId: data.id }}>查看 Evidence</Link>{canWrite && <><button disabled title="后端能力尚未接入">补充上下文</button><button disabled title="后端能力尚未接入">要求 Replan</button><button className="danger-button" disabled title="后端能力尚未接入">人工接管</button></>}</div>
    </section>
    {data.observabilityStatus === 'lost' && <section className="observability-warning" role="status"><div><strong>观测能力丢失</strong><p>Runner 离线后当前无法继续采集证据；这不代表目标服务宕机。</p></div><dl><div><dt>关联 Runner</dt><dd>{data.observabilityRunnerId ?? '未知'}</dd></div><div><dt>丢失时间</dt><dd>{data.observabilityLostAt ? new Date(data.observabilityLostAt).toLocaleString('zh-CN', { hour12: false }) : '未知'}</dd></div></dl></section>}
    <section className="state-banner"><i /><strong>Incident · {data.status}</strong><ObservabilityBadge status={data.observabilityStatus} /><span>Agent · {agentStage}</span><span>自主等级 · {data.autonomyLevel}</span><small>当前工具预算 {data.toolBudget.used} / {data.toolBudget.limit}</small></section>
    <section className="agent-status-grid">
      <div><span>Agent 阶段</span><strong className="accent-text">{agentStage}</strong></div>
      <div><span>计划进度</span><strong>Step {activeStep?.ordinal ?? progressedSteps} / {data.steps.length}</strong></div>
      <div><span>主要假设</span><strong className={data.hypothesis ? 'warn-text' : undefined}>{data.hypothesis ? `${data.hypothesis.id} · ${data.hypothesis.confidence}%` : '尚未形成'}</strong></div>
      <div><span>工具预算</span><strong>{data.toolBudget.used} / {data.toolBudget.limit}</strong></div>
      <div><span>计划版本</span><strong>v{data.planVersion} · Replan {data.replanCount}</strong></div>
    </section>
    <InvestigationRunPanel incidentId={data.id} />
    <ActionProposalPanel incidentId={data.id} />
    <HypothesisPanel incidentId={data.id} primary={data.hypothesis} />
    <section className="detail-grid">
      <IncidentTimelinePanel incident={data} />
      <div className="panel">
        <div className="panel-heading"><h2>调查计划</h2><span className="panel-note">PLAN v{data.planVersion}</span></div>
        <div className="plan-list">{data.steps.length ? data.steps.map((step) => <article className={`plan-step plan-${step.status}`} key={step.id}><span className="step-number">{stepMark(step.status, step.ordinal)}</span><div><strong>{step.title}</strong><p>{step.kind} · risk {step.risk} · {step.status} · 尝试 {step.attempts}</p>{step.resultSummary && <small>{step.resultSummary}</small>}</div></article>) : <p className="inline-empty">当前 Incident 尚未生成调查计划</p>}</div>
        <div className="next-action"><span>AGENT NEXT</span><p>计划将依据当前证据继续推进；涉及变更资源的动作仍需进入 ActionProposal、审批与资源仲裁流程。</p><Link to="/actions">查看动作执行模型 →</Link></div>
      </div>
    </section>
  </>
}
